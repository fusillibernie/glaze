"""Tests for the executable defect guide.

data/reference/defect_guide.json used to be almost entirely unreachable:
only crazing and shivering were read, only their chemistry_remedies, and
only when a clay-body COE happened to be supplied - which the UI does not
do by default. Meanwhile the predictor scored defects from four hardcoded
rules whose own docstring conceded they were "not calibrated against
firing data", which is exactly what the guide was archived to replace.

Now every risk the predictor emits comes from a trigger in the guide and
carries its source and an `evidence` tag, so a threshold quoted from a
book is distinguishable from one inherited from those guesses.
"""

import json
from pathlib import Path

import pytest

from src.models.glaze import (
    AtmosphereType,
    ClayBody,
    ConeTemperature,
    FiringSchedule,
    FiringType,
    GlazeIngredient,
    GlazeRecipe,
)
from src.models.umf import UMF
from src.services.materials_db import MaterialsDatabase
from src.services.predictor import OutcomePredictor


GUIDE_PATH = Path(__file__).parent.parent / "data" / "reference" / "defect_guide.json"
KNOWN_KINDS = {"umf", "umf_ratio", "batch_pct", "cone", "firing", "clay_body"}
KNOWN_OPS = {">", ">=", "<", "<=", "==", "!="}
KNOWN_EVIDENCE = {"book_quantified", "uncalibrated_heuristic"}


@pytest.fixture(scope="module")
def guide():
    return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))["defects"]


@pytest.fixture(scope="module")
def materials_db():
    db = MaterialsDatabase()
    db.load()
    return db


@pytest.fixture
def predictor(materials_db):
    return OutcomePredictor(results_database=[], materials_db=materials_db)


def firing(cone="6", atmosphere=AtmosphereType.OXIDATION, cooling_rate=None):
    return FiringSchedule(
        name="test",
        cone=ConeTemperature(cone),
        atmosphere=atmosphere,
        firing_type=FiringType.ELECTRIC,
        cooling_rate=cooling_rate,
    )


def recipe(umf=None, ingredients=()):
    return GlazeRecipe(
        name="test",
        ingredients=[GlazeIngredient(material_name=m, percentage=p) for m, p in ingredients],
        umf=umf or UMF(SiO2=3.0, Al2O3=0.35, CaO=0.6, K2O=0.4),
    )


class TestSchema:
    def test_every_trigger_is_well_formed(self, guide):
        for defect, entry in guide.items():
            for trigger in entry.get("triggers", []):
                assert trigger.get("id"), f"{defect}: trigger missing id"
                assert 0 <= trigger["risk"] <= 1, f"{defect}: risk out of range"
                assert trigger.get("when"), f"{defect}: trigger has no conditions"
                assert trigger.get("source"), f"{defect}: trigger has no source"
                assert trigger["evidence"] in KNOWN_EVIDENCE, f"{defect}: bad evidence tag"

    def test_every_condition_is_understood(self, guide):
        for defect, entry in guide.items():
            for trigger in entry.get("triggers", []):
                for condition in trigger["when"]:
                    assert condition["kind"] in KNOWN_KINDS, f"{defect}: {condition['kind']}"
                    assert condition["op"] in KNOWN_OPS, f"{defect}: {condition['op']}"

    def test_umf_conditions_name_real_oxides(self, guide):
        umf = UMF()
        for defect, entry in guide.items():
            for trigger in entry.get("triggers", []):
                for condition in trigger["when"]:
                    if condition["kind"] == "umf":
                        assert hasattr(umf, condition["oxide"]), f"{defect}: {condition['oxide']}"
                    elif condition["kind"] == "umf_ratio":
                        assert hasattr(umf, condition["ratio"]), f"{defect}: {condition['ratio']}"

    def test_batch_conditions_name_resolvable_materials(self, guide, materials_db):
        """A trigger keyed to a material nobody can resolve would never
        fire, and would do so silently."""
        for defect, entry in guide.items():
            for trigger in entry.get("triggers", []):
                for condition in trigger["when"]:
                    if condition["kind"] == "batch_pct":
                        for name in condition["materials"]:
                            assert materials_db.get(name), f"{defect}: {name!r} does not resolve"

    def test_risk_keys_are_unique(self, guide):
        keys = [e["risk_key"] for e in guide.values() if "risk_key" in e]
        assert len(keys) == len(set(keys))

    def test_message_placeholders_are_bindable(self, guide):
        """Every {placeholder} must correspond to a value some condition
        in the same trigger actually binds."""
        binds = {
            "umf": {"oxide_value"}, "umf_ratio": {"ratio_value"},
            "batch_pct": {"batch_pct"}, "cone": {"cone"},
            "firing": {"firing_value"}, "clay_body": {"clay_body_value"},
        }
        import string
        for defect, entry in guide.items():
            for trigger in entry.get("triggers", []):
                available = set()
                for condition in trigger["when"]:
                    available |= binds.get(condition["kind"], set())
                used = {f for _, f, _, _ in string.Formatter().parse(trigger["message"]) if f}
                assert used <= available, f"{defect}/{trigger['id']}: unbindable {used - available}"


class TestBookSourcedRules:
    """Fraser's and Digitalfire's quantified thresholds, which no code
    path could reach before."""

    def test_colemanite_above_10_percent_fires(self, predictor):
        r = recipe(ingredients=[("Custer Feldspar", 38), ("Gerstley Borate", 12),
                                ("Silica (Flint)", 30), ("EPK Kaolin", 20)])
        _, findings = predictor._calculate_defect_risks(r, firing(), ClayBody.STONEWARE)
        hit = next(f for f in findings if f.defect == "colemanite_splutter")
        assert hit.risk == 0.55
        assert hit.evidence == "book_quantified"
        assert hit.source == "fraser-ceramic-faults-2005"
        assert "12%" in hit.message

    def test_colemanite_between_7_and_10_gives_the_lower_tier(self, predictor):
        r = recipe(ingredients=[("Custer Feldspar", 42), ("Gerstley Borate", 8),
                                ("Silica (Flint)", 30), ("EPK Kaolin", 20)])
        _, findings = predictor._calculate_defect_risks(r, firing(), ClayBody.STONEWARE)
        hit = next(f for f in findings if f.defect == "colemanite_splutter")
        assert hit.risk == 0.25

    def test_no_colemanite_no_risk(self, predictor):
        r = recipe(ingredients=[("Custer Feldspar", 50), ("Silica (Flint)", 30), ("EPK Kaolin", 20)])
        risks, findings = predictor._calculate_defect_risks(r, firing(), ClayBody.STONEWARE)
        assert "colemanite_splutter" not in risks
        assert not any(f.defect == "colemanite_splutter" for f in findings)

    def test_high_boron_blisters_at_mid_fire_but_not_high_fire(self, predictor):
        umf = UMF(SiO2=2.5, Al2O3=0.3, B2O3=0.8, CaO=0.6, Na2O=0.4)
        _, mid = predictor._calculate_defect_risks(recipe(umf), firing("6"), ClayBody.STONEWARE)
        _, high = predictor._calculate_defect_risks(recipe(umf), firing("10"), ClayBody.STONEWARE)
        assert any(f.defect == "blistering" for f in mid)
        assert not any(f.defect == "blistering" for f in high)

    def test_boron_threshold_is_exact(self, predictor):
        def fired(b2o3):
            umf = UMF(SiO2=2.5, Al2O3=0.3, B2O3=b2o3, CaO=0.6, Na2O=0.4)
            _, f = predictor._calculate_defect_risks(recipe(umf), firing("6"), ClayBody.STONEWARE)
            return any(x.defect == "blistering" for x in f)
        assert fired(0.70)
        assert not fired(0.69)

    def test_bloating_needs_both_reduction_and_an_iron_body(self, predictor):
        iron_body = {"analysis": {"Fe2O3": 2.3}}
        white_body = {"analysis": {"Fe2O3": 0.4}}
        r = recipe()

        def fired(body, atmosphere):
            _, f = predictor._calculate_defect_risks(
                r, firing("10", atmosphere), ClayBody.STONEWARE, clay_body_record=body)
            return any(x.defect == "bloating" for x in f)

        assert fired(iron_body, AtmosphereType.REDUCTION)
        assert not fired(white_body, AtmosphereType.REDUCTION)
        assert not fired(iron_body, AtmosphereType.OXIDATION)

    def test_bloating_message_names_the_unmodelled_gap(self, predictor):
        """Fraser's actual mechanism is the heating rate through
        650-1000C, which FiringSchedule does not carry. The message has to
        say so rather than imply the rule is complete."""
        _, findings = predictor._calculate_defect_risks(
            recipe(), firing("10", AtmosphereType.REDUCTION), ClayBody.STONEWARE,
            clay_body_record={"analysis": {"Fe2O3": 2.3}})
        hit = next(f for f in findings if f.defect == "bloating")
        assert "does not model" in hit.message


class TestLegacyRulesPreserved:
    def test_the_four_original_keys_always_appear(self, predictor):
        """The UI renders these as a fixed grid; they must not vanish."""
        risks, _ = predictor._calculate_defect_risks(recipe(), firing(), ClayBody.STONEWARE)
        for key in ("crawling", "crazing", "running", "pinholing"):
            assert key in risks

    def test_legacy_thresholds_are_unchanged(self, predictor):
        high_alumina = recipe(UMF(SiO2=3.0, Al2O3=0.55, CaO=0.6, K2O=0.4))
        risks, _ = predictor._calculate_defect_risks(high_alumina, firing(), ClayBody.STONEWARE)
        assert risks["crawling"] == 0.3

        low_alumina = recipe(UMF(SiO2=3.0, Al2O3=0.15, CaO=0.6, K2O=0.4))
        risks, _ = predictor._calculate_defect_risks(low_alumina, firing(), ClayBody.STONEWARE)
        assert risks["running"] == 0.5

    def test_legacy_rules_are_tagged_as_uncalibrated(self, predictor):
        r = recipe(UMF(SiO2=3.0, Al2O3=0.55, CaO=0.6, K2O=0.4))
        _, findings = predictor._calculate_defect_risks(r, firing(), ClayBody.STONEWARE)
        crawling = next(f for f in findings if f.defect == "crawling")
        assert crawling.evidence == "uncalibrated_heuristic"

    def test_crash_cooling_raises_pinholing(self, predictor):
        _, findings = predictor._calculate_defect_risks(
            recipe(), firing(cooling_rate="crash"), ClayBody.STONEWARE)
        assert any(f.defect == "pinholing" and f.risk == 0.4 for f in findings)


class TestEvaluationSemantics:
    def test_triggers_combine_by_max_not_sum(self, predictor):
        """Two crazing triggers both match a high-alkali glaze; the risk
        must be the stronger one, not their total."""
        r = recipe(UMF(SiO2=3.0, Al2O3=0.35, Na2O=0.5, K2O=0.3, CaO=0.2))
        risks, _ = predictor._calculate_defect_risks(r, firing(), ClayBody.STONEWARE)
        assert risks["crazing"] == 0.5

    def test_all_risks_stay_in_range(self, predictor):
        r = recipe(UMF(SiO2=2.0, Al2O3=0.6, B2O3=0.9, Na2O=0.6, K2O=0.3),
                   ingredients=[("Gerstley Borate", 20), ("Custer Feldspar", 80)])
        risks, _ = predictor._calculate_defect_risks(
            r, firing(cooling_rate="crash"), ClayBody.STONEWARE)
        assert all(0.0 <= v <= 1.0 for v in risks.values())

    def test_batch_conditions_skipped_without_materials_db(self):
        """Unanswerable is not the same as false - a predictor with no
        materials database must not silently report zero colemanite."""
        bare = OutcomePredictor(results_database=[], materials_db=None)
        r = recipe(ingredients=[("Gerstley Borate", 20), ("Custer Feldspar", 80)])
        risks, findings = bare._calculate_defect_risks(r, firing(), ClayBody.STONEWARE)
        assert "colemanite_splutter" not in risks
        assert not any(f.defect == "colemanite_splutter" for f in findings)

    def test_findings_are_ordered_by_risk(self, predictor):
        r = recipe(UMF(SiO2=2.0, Al2O3=0.55, Na2O=0.5, K2O=0.3, CaO=0.2),
                   ingredients=[("Gerstley Borate", 15), ("Custer Feldspar", 85)])
        _, findings = predictor._calculate_defect_risks(r, firing(), ClayBody.STONEWARE)
        assert [f.risk for f in findings] == sorted((f.risk for f in findings), reverse=True)


class TestConeParsing:
    @pytest.mark.parametrize("cone,expected", [
        ("06", -6), ("04", -4), ("02", -2), ("1", 1), ("6", 6), ("10", 10),
    ])
    def test_low_fire_cones_are_negative(self, cone, expected):
        """The leading-zero series runs the other way: cone 06 is far
        cooler than cone 6. Treating "06" as 6 would fire mid-fire rules
        on low-fire work."""
        assert OutcomePredictor._cone_number(firing(cone)) == expected

    def test_missing_cone_is_unanswerable_not_zero(self):
        assert OutcomePredictor._cone_number(None) is None
