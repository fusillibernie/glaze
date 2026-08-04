"""Tests for the formulator's recipe-manipulation half.

formulator.py sat at 48% coverage - every UMF in the app flows through
it, but only the calculation side was exercised. The untested half is
recipe manipulation: inheritance, dual UMF for soluble materials,
wood-ash accumulation, adjustment and colorant addition. The first thing
writing these turned up was that adjust_recipe silently rewrote its
input, so the gap was hiding a data-corruption bug rather than just
uncovered lines.
"""

import pytest

from src.models.glaze import (
    AtmosphereType,
    Colorant,
    ConeTemperature,
    GlazeIngredient,
    GlazeRecipe,
)
from src.services.formulator import GlazeFormulator
from src.services.materials_db import MaterialsDatabase


@pytest.fixture(scope="module")
def materials_db():
    db = MaterialsDatabase()
    db.load()
    return db


@pytest.fixture
def formulator(materials_db):
    return GlazeFormulator(materials_db)


@pytest.fixture
def base_recipe():
    return GlazeRecipe(
        name="Base Clear",
        ingredients=[
            GlazeIngredient(material_name="Custer Feldspar", percentage=40),
            GlazeIngredient(material_name="Silica (Flint)", percentage=30),
            GlazeIngredient(material_name="Whiting (Calcium Carbonate)", percentage=15),
            GlazeIngredient(material_name="EPK Kaolin", percentage=15),
        ],
        target_cone=ConeTemperature.CONE_6,
        suitable_atmospheres=[AtmosphereType.OXIDATION],
    )


class TestInputIsNotMutated:
    """adjust_recipe built its result with `ingredients=list(recipe.ingredients)`,
    which copies the list but shares the GlazeIngredient objects. It then
    did `ing.percentage += amount` and renormalized, so calling it
    rewrote the caller's recipe: a 40/30/30 recipe came back as
    36.4/36.4/27.3 and the original was gone.
    """

    def _snapshot(self, recipe):
        return [(i.material_name, i.percentage) for i in recipe.ingredients]

    @pytest.mark.parametrize("adjustment", ["more_flux", "more_silica", "more_alumina"])
    def test_adjust_leaves_the_original_alone(self, formulator, base_recipe, adjustment):
        before = self._snapshot(base_recipe)
        formulator.adjust_recipe(base_recipe, adjustment, amount=10)
        assert self._snapshot(base_recipe) == before

    def test_adjust_returns_independent_objects(self, formulator, base_recipe):
        adjusted = formulator.adjust_recipe(base_recipe, "more_silica", amount=10)
        assert all(a is not b for a, b in zip(adjusted.ingredients, base_recipe.ingredients))

    def test_add_colorant_leaves_the_original_alone(self, formulator, base_recipe):
        before = self._snapshot(base_recipe)
        result = formulator.add_colorant(base_recipe, "Cobalt Carbonate", 2.0)
        assert self._snapshot(base_recipe) == before
        assert base_recipe.colorants == []
        assert len(result.colorants) == 1

    def test_repeated_adjustment_does_not_compound(self, formulator, base_recipe):
        """The clearest symptom of the old bug: calling twice with the
        same arguments used to give two different answers, because the
        second call started from the mutated first."""
        first = formulator.adjust_recipe(base_recipe, "more_silica", amount=10)
        second = formulator.adjust_recipe(base_recipe, "more_silica", amount=10)
        assert self._snapshot(first) == self._snapshot(second)


class TestAdjustRecipe:
    def test_more_silica_raises_silica_share(self, formulator, base_recipe):
        adjusted = formulator.adjust_recipe(base_recipe, "more_silica", amount=15)
        original = {i.material_name: i.percentage for i in base_recipe.ingredients}
        result = {i.material_name: i.percentage for i in adjusted.ingredients}
        assert result["Silica (Flint)"] > original["Silica (Flint)"]

    def test_more_alumina_raises_alumina(self, formulator, base_recipe):
        adjusted = formulator.adjust_recipe(base_recipe, "more_alumina", amount=10)
        assert adjusted.umf.Al2O3 > formulator.calculate_umf(base_recipe).Al2O3

    def test_result_is_renormalized_to_100(self, formulator, base_recipe):
        for adjustment in ("more_flux", "more_silica", "more_alumina"):
            adjusted = formulator.adjust_recipe(base_recipe, adjustment, amount=12)
            assert sum(i.percentage for i in adjusted.ingredients) == pytest.approx(100.0)

    def test_unknown_adjustment_is_a_no_op_not_an_error(self, formulator, base_recipe):
        adjusted = formulator.adjust_recipe(base_recipe, "make_it_purple", amount=5)
        assert sum(i.percentage for i in adjusted.ingredients) == pytest.approx(100.0)

    def test_adds_silica_when_the_recipe_has_none(self, formulator):
        recipe = GlazeRecipe(name="no silica", ingredients=[
            GlazeIngredient(material_name="Custer Feldspar", percentage=60),
            GlazeIngredient(material_name="EPK Kaolin", percentage=40),
        ])
        adjusted = formulator.adjust_recipe(recipe, "more_silica", amount=20)
        assert any("silica" in i.material_name.lower() for i in adjusted.ingredients)

    def test_result_carries_a_recalculated_umf(self, formulator, base_recipe):
        adjusted = formulator.adjust_recipe(base_recipe, "more_silica", amount=10)
        assert adjusted.umf is not None
        assert adjusted.umf.SiO2 > 0


class TestAddColorant:
    def test_colorant_is_appended_with_its_details(self, formulator, base_recipe):
        result = formulator.add_colorant(base_recipe, "Cobalt Carbonate", 1.5, "deep blue")
        colorant = result.colorants[0]
        assert (colorant.material_name, colorant.percentage) == ("Cobalt Carbonate", 1.5)
        assert colorant.expected_color == "deep blue"

    def test_existing_colorants_are_preserved(self, formulator, base_recipe):
        base_recipe.colorants.append(Colorant(material_name="Red Iron Oxide", percentage=2))
        result = formulator.add_colorant(base_recipe, "Rutile", 4.0)
        assert {c.material_name for c in result.colorants} == {"Red Iron Oxide", "Rutile"}

    def test_base_ingredients_are_untouched(self, formulator, base_recipe):
        """Colorants are additions on top of a 100% base; adding one must
        not redistribute the base."""
        result = formulator.add_colorant(base_recipe, "Rutile", 4.0)
        assert sum(i.percentage for i in result.ingredients) == pytest.approx(100.0)


class TestRecipeInheritance:
    @pytest.fixture
    def registered(self, formulator, base_recipe):
        formulator.register_recipe(base_recipe)
        return formulator

    def test_child_inherits_parent_ingredients(self, registered):
        resolved = registered.resolve_inheritance({
            "name": "Blue Variation",
            "parent_glaze": "Base Clear",
            "colorants": [{"material": "Cobalt Carbonate", "percentage": 1.0}],
        })
        assert len(resolved.inherited_ingredients) == 4
        assert resolved.parent_name == "Base Clear"
        assert resolved.recipe.name == "Blue Variation"

    def test_additions_layer_on_top_of_the_base(self, registered):
        resolved = registered.resolve_inheritance({
            "parent_glaze": "Base Clear",
            "additions": [{"material": "Tin Oxide", "percentage": 5.0}],
        })
        assert sum(i.percentage for i in resolved.recipe.ingredients) == pytest.approx(105.0)
        assert [a.material_name for a in resolved.additions] == ["Tin Oxide"]

    def test_parent_firing_properties_carry_over(self, registered):
        resolved = registered.resolve_inheritance({"parent_glaze": "Base Clear"})
        assert resolved.recipe.target_cone == ConeTemperature.CONE_6
        assert AtmosphereType.OXIDATION in resolved.recipe.suitable_atmospheres

    def test_lookup_is_case_insensitive(self, registered):
        assert registered.resolve_inheritance({"parent_glaze": "base clear"}).parent_name

    def test_missing_parent_is_an_error_not_a_silent_empty_recipe(self, registered):
        with pytest.raises(ValueError, match="not found"):
            registered.resolve_inheritance({"parent_glaze": "No Such Glaze"})

    def test_absent_parent_key_is_an_error(self, registered):
        with pytest.raises(ValueError, match="parent_glaze"):
            registered.resolve_inheritance({"name": "orphan"})

    def test_child_chemistry_reflects_the_additions(self, registered):
        plain = registered.resolve_inheritance({"parent_glaze": "Base Clear"})
        with_clay = registered.resolve_inheritance({
            "parent_glaze": "Base Clear",
            "additions": [{"material": "EPK Kaolin", "percentage": 15.0}],
        })
        assert (registered.calculate_umf(with_clay.recipe).Al2O3
                > registered.calculate_umf(plain.recipe).Al2O3)


class TestDualUMF:
    """Soluble fluxes dissolve and migrate to the surface as the glaze
    dries, so body and surface fire to different chemistry. A single UMF
    describes neither."""

    @pytest.fixture
    def soluble_recipe(self, materials_db):
        soluble = next((m for m in materials_db.get_all() if m.soluble), None)
        if soluble is None:
            pytest.skip("no soluble material in the database")
        return GlazeRecipe(name="soluble test", ingredients=[
            GlazeIngredient(material_name="Custer Feldspar", percentage=50),
            GlazeIngredient(material_name="Silica (Flint)", percentage=30),
            GlazeIngredient(material_name=soluble.name, percentage=20),
        ])

    def test_returns_none_when_nothing_is_soluble(self, formulator, base_recipe):
        assert formulator.calculate_dual_umf(base_recipe) is None

    def test_splits_body_and_surface(self, formulator, soluble_recipe):
        result = formulator.calculate_dual_umf(soluble_recipe)
        assert result is not None
        assert result.body_umf is not None and result.surface_umf is not None

    def test_surface_is_richer_in_flux_than_body(self, formulator, soluble_recipe):
        """The whole point of the split - if these matched, the model
        would not be telling the user anything."""
        result = formulator.calculate_dual_umf(soluble_recipe, surface_concentration=0.9)
        assert result.surface_umf.to_dict() != result.body_umf.to_dict()

    def test_concentration_controls_the_split(self, formulator, soluble_recipe):
        mild = formulator.calculate_dual_umf(soluble_recipe, surface_concentration=0.2)
        strong = formulator.calculate_dual_umf(soluble_recipe, surface_concentration=0.95)
        assert mild.surface_umf.to_dict() != strong.surface_umf.to_dict()


class TestAshAccumulation:
    """Wood-kiln ash travels from the firebox and deposits as extra flux,
    so identical recipes fire differently by shelf position."""

    def test_firebox_receives_more_ash_than_the_back(self, formulator, base_recipe):
        firebox = formulator.calculate_ash_accumulation(base_recipe, "firebox")
        back = formulator.calculate_ash_accumulation(base_recipe, "back")
        assert firebox.ash_addition_pct > back.ash_addition_pct

    def test_ash_raises_the_flux_load(self, formulator, base_recipe):
        result = formulator.calculate_ash_accumulation(base_recipe, "firebox")
        assert result.ash_modified_umf.flux_total >= result.base_umf.flux_total
        assert result.ash_modified_umf.to_dict() != result.base_umf.to_dict()

    def test_base_umf_is_the_unmodified_chemistry(self, formulator, base_recipe):
        result = formulator.calculate_ash_accumulation(base_recipe, "middle")
        assert result.base_umf.to_dict() == formulator.calculate_umf(base_recipe).to_dict()

    def test_unknown_position_falls_back_quietly(self, formulator, base_recipe):
        result = formulator.calculate_ash_accumulation(base_recipe, "on the roof")
        assert result.ash_addition_pct > 0
        assert result.kiln_position == "on the roof"

    def test_custom_ash_composition_is_used(self, formulator, base_recipe):
        default = formulator.calculate_ash_accumulation(base_recipe, "firebox")
        custom = formulator.calculate_ash_accumulation(
            base_recipe, "firebox", ash_composition={"CaO": 60.0, "SiO2": 20.0})
        assert custom.ash_modified_umf.to_dict() != default.ash_modified_umf.to_dict()
        assert custom.ash_composition == {"CaO": 60.0, "SiO2": 20.0}
