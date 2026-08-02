"""Tests for food-safety risk assessment.

Replaces the old two-line check (PbO>0, BaO>0.1 only) with the risk
factors data/reference/safety_guide.json actually documents from
Digitalfire's food-safety article. Each test pins one specific factor so
a future edit can't silently drop a check without a test failing.
"""

import pytest

from src.models.glaze import GlazeRecipe, GlazeIngredient, Colorant, ConeTemperature
from src.models.umf import UMF
from src.services.materials_db import MaterialsDatabase
from src.services.safety_assessor import SafetyAssessor


@pytest.fixture
def materials_db():
    db = MaterialsDatabase()
    db.load()
    return db


@pytest.fixture
def assessor(materials_db):
    return SafetyAssessor(materials_db)


def recipe(ingredients=None, colorants=None, umf=None, cone="6"):
    return GlazeRecipe(
        name="t",
        ingredients=ingredients or [],
        colorants=colorants or [],
        umf=umf or UMF(),
        target_cone=ConeTemperature(cone),
    )


class TestLeadAndBarium:
    def test_lead_is_a_concern(self, assessor):
        result = assessor.assess(recipe(umf=UMF(PbO=0.1)))
        assert any(f.key == "lead" and f.severity == "concern" for f in result.findings)
        assert result.risk_level == "high"

    def test_barium_above_threshold_is_a_concern(self, assessor):
        result = assessor.assess(recipe(umf=UMF(BaO=0.15)))
        assert any(f.key == "barium" for f in result.findings)
        assert result.risk_level == "high"

    def test_barium_below_threshold_not_flagged(self, assessor):
        result = assessor.assess(recipe(umf=UMF(BaO=0.05)))
        assert not any(f.key == "barium" for f in result.findings)

    def test_clean_recipe_is_low_risk(self, assessor):
        result = assessor.assess(recipe(umf=UMF(SiO2=3.5, Al2O3=0.4, CaO=0.7, K2O=0.3)))
        assert result.risk_level == "low"
        assert not any(f.severity in ("caution", "concern") for f in result.findings)


class TestChemistryLinkedFactors:
    def test_low_silica_alumina_issue_reused_from_analyzer(self, assessor):
        issues = ["SiO2 (2.10) is below typical range for cone 6"]
        result = assessor.assess(recipe(), chemistry_issues=issues)
        assert any(f.key == "low_glass_formers" for f in result.findings)

    def test_no_issues_means_no_finding(self, assessor):
        result = assessor.assess(recipe(), chemistry_issues=[])
        assert not any(f.key == "low_glass_formers" for f in result.findings)

    def test_crazing_risk_flagged(self, assessor):
        result = assessor.assess(recipe(), crazing_risk="high")
        assert any(f.key == "crazing" for f in result.findings)

    def test_low_crazing_risk_not_flagged(self, assessor):
        result = assessor.assess(recipe(), crazing_risk="low")
        assert not any(f.key == "crazing" for f in result.findings)


class TestFormulationRedFlags:
    def test_excess_talc_flagged(self, assessor):
        r = recipe(ingredients=[
            GlazeIngredient(material_name="Talc", percentage=8),
            GlazeIngredient(material_name="Custer Feldspar", percentage=92),
        ])
        result = assessor.assess(r)
        finding = next(f for f in result.findings if f.key == "excess_talc")
        assert "8.0%" in finding.message

    def test_talc_under_threshold_not_flagged(self, assessor):
        r = recipe(ingredients=[
            GlazeIngredient(material_name="Talc", percentage=3),
            GlazeIngredient(material_name="Custer Feldspar", percentage=97),
        ])
        result = assessor.assess(r)
        assert not any(f.key == "excess_talc" for f in result.findings)

    def test_concentrated_lithium_flagged(self, assessor):
        r = recipe(ingredients=[
            GlazeIngredient(material_name="Lithium Carbonate", percentage=6),
            GlazeIngredient(material_name="Custer Feldspar", percentage=94),
        ])
        result = assessor.assess(r)
        assert any(f.key == "concentrated_lithium" for f in result.findings)

    def test_diffuse_lithium_feldspar_not_flagged(self, assessor):
        """Spodumene (7.5% Li2O) is a lithium feldspar, not a 'concentrated
        lithium carbonate' source in the source article's sense - even at
        a large percentage it should not trip this specific check."""
        r = recipe(ingredients=[
            GlazeIngredient(material_name="Spodumene", percentage=20),
            GlazeIngredient(material_name="Custer Feldspar", percentage=80),
        ])
        result = assessor.assess(r)
        assert not any(f.key == "concentrated_lithium" for f in result.findings)

    def test_high_boron_frit_at_high_fire_flagged(self, assessor):
        r = recipe(
            ingredients=[
                GlazeIngredient(material_name="Frit 3134", percentage=15),
                GlazeIngredient(material_name="Custer Feldspar", percentage=85),
            ],
            cone="10",
        )
        result = assessor.assess(r)
        assert any(f.key == "high_boron_frit" for f in result.findings)

    def test_high_boron_frit_at_low_fire_not_flagged(self, assessor):
        """The source article calls this out for high-fire glazes
        specifically - normal at cone 04/06."""
        r = recipe(
            ingredients=[
                GlazeIngredient(material_name="Frit 3134", percentage=40),
                GlazeIngredient(material_name="Custer Feldspar", percentage=60),
            ],
            cone="04",
        )
        result = assessor.assess(r)
        assert not any(f.key == "high_boron_frit" for f in result.findings)


class TestColorantInteractions:
    def test_copper_and_manganese_together_is_a_concern(self, assessor):
        r = recipe(colorants=[
            Colorant(material_name="Copper Carbonate", percentage=2),
            Colorant(material_name="Manganese Dioxide", percentage=2),
        ])
        result = assessor.assess(r)
        finding = next(f for f in result.findings if f.key == "copper_manganese_combination")
        assert finding.severity == "concern"
        assert result.risk_level == "high"

    def test_copper_alone_not_flagged_as_combination(self, assessor):
        r = recipe(colorants=[Colorant(material_name="Copper Carbonate", percentage=2)])
        result = assessor.assess(r)
        assert not any(f.key == "copper_manganese_combination" for f in result.findings)
        assert not any(f.key == "copper_with_other_colorants" for f in result.findings)

    def test_copper_with_unrelated_colorant_is_a_caution(self, assessor):
        r = recipe(colorants=[
            Colorant(material_name="Copper Carbonate", percentage=2),
            Colorant(material_name="Cobalt Carbonate", percentage=1),
        ])
        result = assessor.assess(r)
        finding = next(f for f in result.findings if f.key == "copper_with_other_colorants")
        assert finding.severity == "caution"


class TestCadmiumDisclosure:
    def test_cadmium_note_always_present(self, assessor):
        """Not a computed check - a permanent disclosure of a blind spot,
        since cadmium isn't tracked anywhere in this app's chemistry model."""
        result = assessor.assess(recipe())
        finding = next(f for f in result.findings if f.key == "cadmium_not_tracked")
        assert finding.severity == "info"

    def test_cadmium_note_does_not_affect_risk_level(self, assessor):
        result = assessor.assess(recipe(umf=UMF(SiO2=3.5, Al2O3=0.4, CaO=0.7)))
        assert result.risk_level == "low"


class TestRiskLevelRollup:
    def test_three_cautions_escalate_to_high(self, assessor):
        r = recipe(ingredients=[
            GlazeIngredient(material_name="Talc", percentage=8),
            GlazeIngredient(material_name="Lithium Carbonate", percentage=6),
            GlazeIngredient(material_name="Custer Feldspar", percentage=86),
        ])
        # crazing_risk is a separate assess() kwarg, not part of the recipe
        result = assessor.assess(r, crazing_risk="high")
        cautions = [f for f in result.findings if f.severity == "caution"]
        assert len(cautions) >= 3
        assert result.risk_level == "high"

    def test_testing_recommendation_always_present(self, assessor):
        result = assessor.assess(recipe())
        assert result.testing_recommendation
