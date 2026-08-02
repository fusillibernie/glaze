"""Tests for material alias resolution and unresolved-ingredient reporting.

Unresolved ingredients are excluded from oxide totals which are then
normalized to unity, so a dropped ingredient produces a plausible-looking but
wrong UMF. These tests pin both halves of the fix: aliases resolve, and
anything that still fails to resolve is reported rather than swallowed.
"""

import json
import glob

import pytest

from src.models.glaze import GlazeRecipe, GlazeIngredient
from src.services.materials_db import MaterialsDatabase
from src.services.formulator import GlazeFormulator


@pytest.fixture
def db():
    database = MaterialsDatabase()
    database.load()
    return database


@pytest.fixture
def formulator(db):
    return GlazeFormulator(db)


class TestAliasResolution:
    @pytest.mark.parametrize("alias,canonical", [
        ("OM4 Ball Clay", "Ball Clay (OM4)"),
        ("Redart Clay", "Red Art"),
        ("Frit 3124", "Ferro Frit 3124"),
        ("Ferro Frit 3134", "Frit 3134"),
        ("Hawthorn Bond Fire Clay", "Hawthorne Bond"),
        ("Wood Ash (Mixed)", "Wood Ash (Mixed Hardwood)"),
        ("EP Kaolin", "EPK Kaolin"),
        ("Neph Sye", "Nepheline Syenite"),
        ("GB", "Gerstley Borate"),
        ("Cobalt Carb", "Cobalt Carbonate"),
    ])
    def test_alias_resolves(self, db, alias, canonical):
        material = db.get(alias)
        assert material is not None, f"{alias!r} did not resolve"
        assert material.name == canonical

    def test_alias_is_case_insensitive(self, db):
        assert db.get("om4 BALL clay").name == "Ball Clay (OM4)"

    def test_alias_tolerates_surrounding_space(self, db):
        assert db.get("  Redart Clay  ").name == "Red Art"

    def test_real_name_beats_alias(self, db):
        """An exact material name must never be shadowed by another's alias."""
        for material in db.get_all():
            assert db.get(material.name).name == material.name

    def test_prefix_match_is_deterministic(self, db):
        """Ambiguous prefixes must not depend on file load order."""
        assert db.get("Frit").name == db.get("Frit").name
        assert db.get("Silica").name == "Silica (Flint)"

    def test_unknown_still_returns_none(self, db):
        assert db.get("Definitely Not A Material") is None


class TestUnresolvedReporting:
    def test_reports_only_the_unknown(self, db):
        missing = db.unresolved(["EPK Kaolin", "Bogus Clay", "OM4 Ball Clay"])
        assert missing == ["Bogus Clay"]

    def test_deduplicates(self, db):
        assert db.unresolved(["Bogus", "bogus", "Bogus"]) == ["Bogus"]

    def test_empty_when_all_known(self, db):
        assert db.unresolved(["Silica (Flint)", "Whiting"]) == []

    def test_formulator_reports_recipe_level(self, formulator):
        recipe = GlazeRecipe(name="t", ingredients=[
            GlazeIngredient(material_name="Custer Feldspar", percentage=50),
            GlazeIngredient(material_name="Nonexistent Clay", percentage=50),
        ])
        assert formulator.unresolved_ingredients(recipe) == ["Nonexistent Clay"]

    def test_logs_when_dropping(self, formulator, caplog):
        recipe = GlazeRecipe(name="t", ingredients=[
            GlazeIngredient(material_name="Silica (Flint)", percentage=80),
            GlazeIngredient(material_name="Nonexistent Clay", percentage=20),
        ])
        with caplog.at_level("WARNING"):
            formulator.calculate_umf(recipe)
        assert "Nonexistent Clay" in caplog.text


class TestAliasFixesChemistry:
    def test_alias_gives_same_umf_as_canonical(self, formulator):
        """The whole point: the aliased spelling must produce identical chemistry."""
        def umf(clay_name):
            return formulator.calculate_umf(GlazeRecipe(name="t", ingredients=[
                GlazeIngredient(material_name="Custer Feldspar", percentage=40),
                GlazeIngredient(material_name="Silica (Flint)", percentage=30),
                GlazeIngredient(material_name="Whiting (Calcium Carbonate)", percentage=15),
                GlazeIngredient(material_name=clay_name, percentage=15),
            ]))

        canonical, aliased = umf("Ball Clay (OM4)"), umf("OM4 Ball Clay")
        assert aliased.Al2O3 == pytest.approx(canonical.Al2O3)
        assert aliased.SiO2 == pytest.approx(canonical.SiO2)

    def test_dropping_would_have_skewed_alumina(self, formulator):
        """Guards the failure mode: a dropped clay understates Al2O3 badly."""
        def umf(clay_name):
            return formulator.calculate_umf(GlazeRecipe(name="t", ingredients=[
                GlazeIngredient(material_name="Custer Feldspar", percentage=40),
                GlazeIngredient(material_name="Silica (Flint)", percentage=30),
                GlazeIngredient(material_name="Whiting (Calcium Carbonate)", percentage=15),
                GlazeIngredient(material_name=clay_name, percentage=15),
            ]))

        good, dropped = umf("Ball Clay (OM4)"), umf("No Such Clay")
        assert dropped.Al2O3 < good.Al2O3 * 0.7
        assert dropped.silica_alumina_ratio > good.silica_alumina_ratio * 1.3


class TestCuratedRecipeIntegrity:
    def test_curated_recipes_mostly_resolve(self, db):
        """Regression guard: alias coverage must not silently rot.

        Baseline (6): names with no published analysis available (Tennessee
        Ball Clay, XX Saggar) or species-specific wood ashes whose chemistry
        genuinely differs from the mixed-hardwood entry - meant to warn
        rather than be aliased to an approximation.

        +10 from data/recipes/britt_oil_spot.json (John Britt, "Secrets of
        Oil Spot Glazes", 2024): Britt's own local/wild materials (Sevier
        Shale, Vulcan Granite, Rotten Stone/Tripoli), unlisted pigments
        (Burnt Umber, Yellow Ochre), one missing common material (Borax),
        and a Mason stain product code not in colorants.json. Same
        reasoning as the baseline - these should warn, not be guessed at.

        +10 from data/recipes/wood_chinese_glazes.json (Nigel Wood,
        "Chinese Glazes", 1999): UK specialty ball-clay brands with no US
        equivalent in this database (Hyplas 71 x5, SMD, BBV) and Molochite
        (a branded calcined china clay) x2 - deliberately left unresolved
        rather than approximated to a generic clay, since their oxide
        analyses (given in the book) differ meaningfully from any US
        ball clay already in the database.
        """
        unresolved = 0
        for path in glob.glob("data/recipes/*.json"):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            recipes = data if isinstance(data, list) else next(
                (v for v in data.values() if isinstance(v, list)), []
            )
            for recipe in recipes:
                for ing in (recipe.get("ingredients") or recipe.get("materials") or []):
                    if not isinstance(ing, dict):
                        continue
                    name = ing.get("material") or ing.get("name")
                    if name and db.get(name) is None:
                        unresolved += 1
        assert unresolved <= 26, f"unresolved ingredient refs rose to {unresolved}"


class TestUnresolvedAPI:
    def test_umf_response_lists_unresolved(self, client):
        response = client.post("/api/recipes/calculate-umf", json={
            "name": "t",
            "ingredients": [
                {"material_name": "Custer Feldspar", "percentage": 60},
                {"material_name": "Bogus Material", "percentage": 40},
            ],
        })
        assert response.status_code == 200
        assert response.json()["unresolved_materials"] == ["Bogus Material"]

    def test_umf_response_empty_when_all_resolve(self, client):
        response = client.post("/api/recipes/calculate-umf", json={
            "name": "t",
            "ingredients": [{"material_name": "OM4 Ball Clay", "percentage": 100}],
        })
        assert response.json()["unresolved_materials"] == []

    def test_analyze_warns_about_unresolved(self, client):
        response = client.post("/api/recipes/analyze", json={
            "name": "t",
            "ingredients": [
                {"material_name": "Custer Feldspar", "percentage": 60},
                {"material_name": "Bogus Material", "percentage": 40},
            ],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["umf"]["unresolved_materials"] == ["Bogus Material"]
        assert "Bogus Material" in data["warnings"][0]
