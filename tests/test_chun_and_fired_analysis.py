"""Tests from validating the app against an independent chun/jun reference.

An outside working document (wood-fire chun reference, cone 10) supplied
recipes and a composition envelope the app had never seen. Three things
it exposed are pinned here: UMF hiding colorant additions, unranked
search relevance, and a chun category profile aimed at ordinary
stoneware chemistry.
"""

import json
from pathlib import Path

import pytest

from src.models.glaze import Colorant, GlazeIngredient, GlazeRecipe
from src.services.formulator import GlazeFormulator
from src.services.materials_db import MaterialsDatabase
from src.services.recipe_db import RecipeDatabase


PROFILES = Path(__file__).parent.parent / "data" / "reference" / "category_profiles.json"


@pytest.fixture(scope="module")
def formulator():
    db = MaterialsDatabase()
    db.load()
    return GlazeFormulator(db)


@pytest.fixture(scope="module")
def chun_profile():
    return json.loads(PROFILES.read_text(encoding="utf-8"))["categories"]["chun"]


@pytest.fixture(scope="module")
def recipe_db():
    db = RecipeDatabase()
    db.load()
    return db


def chun_m1():
    """Chun M1 (Chris Sanders), normalized. 1% red iron oxide as an
    addition on top of the 100% base - the shape that exposed the bug."""
    return GlazeRecipe(
        name="Chun M1",
        ingredients=[
            GlazeIngredient(material_name="Potash Feldspar", percentage=49.05),
            GlazeIngredient(material_name="Silica", percentage=19.42),
            GlazeIngredient(material_name="Whiting", percentage=13.11),
            GlazeIngredient(material_name="Talc", percentage=7.28),
            GlazeIngredient(material_name="Gerstley Borate", percentage=4.86),
            GlazeIngredient(material_name="Dolomite", percentage=3.40),
            GlazeIngredient(material_name="Kaolin", percentage=2.42),
            GlazeIngredient(material_name="Bone Ash", percentage=0.44),
        ],
        colorants=[Colorant(material_name="Red Iron Oxide", percentage=1.0)],
    )


class TestFiredWeightPercent:
    """UMF is molar, flux-unity and base-only. Published composition
    targets are fired weight percent including additions. Reading one as
    the other is off by an order of magnitude on iron."""

    def test_colorant_iron_appears_in_fired_analysis(self, formulator):
        recipe = chun_m1()
        base_umf = formulator.calculate_umf(recipe)
        fired = formulator.fired_weight_percent(recipe)

        assert base_umf.Fe2O3 < 0.01, "base UMF should not contain the addition"
        assert 1.0 <= fired["Fe2O3"] <= 1.5, (
            "1% red iron oxide should land in the 1.0-1.5 wt% band the chun "
            "literature specifies"
        )

    def test_base_only_and_total_differ_by_the_addition(self, formulator):
        recipe = chun_m1()
        base = formulator.fired_weight_percent(recipe, include_colorants=False)
        total = formulator.fired_weight_percent(recipe, include_colorants=True)
        assert total["Fe2O3"] > base.get("Fe2O3", 0) * 5

    def test_normalizes_to_100(self, formulator):
        fired = formulator.fired_weight_percent(chun_m1())
        assert sum(fired.values()) == pytest.approx(100.0, abs=0.01)

    def test_excludes_loi(self, formulator):
        """LOI has left by the time the glaze is fired."""
        assert "LOI" not in formulator.fired_weight_percent(chun_m1())

    def test_empty_recipe_returns_empty_not_nan(self, formulator):
        assert formulator.fired_weight_percent(GlazeRecipe(name="empty", ingredients=[])) == {}

    def test_exposed_through_the_api(self, client):
        response = client.post("/api/recipes/calculate-umf", json={
            "name": "Chun M1",
            "ingredients": [
                {"material_name": "Potash Feldspar", "percentage": 49.05},
                {"material_name": "Silica", "percentage": 19.42},
                {"material_name": "Whiting", "percentage": 13.11},
                {"material_name": "Bone Ash", "percentage": 0.44},
            ],
            "colorants": [{"material_name": "Red Iron Oxide", "percentage": 1.0}],
        })
        fired = response.json()["fired_weight_percent"]
        assert fired["Fe2O3"] > 0.5


class TestSearchRelevance:
    """Search was an unranked filter sliced in corpus order, so a query
    for "chun" returned Sam Chung's glazes - "chun" is a substring of
    "Chung" - ahead of any actual chun."""

    def test_chun_query_returns_chun_glazes_first(self, recipe_db):
        results = recipe_db.search(query="chun", cone="10", limit=8)
        assert results
        top_names = [r["name"].lower() for r in results[:5]]
        assert all("chun" in n for n in top_names), top_names

    def test_potter_surname_does_not_outrank_the_glaze(self, recipe_db):
        """Sam Chung's recipes mention him in the description; a chun
        glaze has it in the name. Name must win."""
        results = recipe_db.search(query="chun", limit=10)
        assert "chung" not in results[0]["name"].lower()

    def test_substring_matching_still_works_for_prefixes(self, recipe_db):
        """Ranking must not become strict whole-word matching, or prefix
        searches stop working."""
        assert recipe_db.search(query="celad", limit=5)

    def test_description_matches_still_included(self, recipe_db):
        """Weaker signal, but still a match - just ranked below names."""
        results = recipe_db.search(query="chun", limit=200)
        assert any("chun" not in (r.get("name") or "").lower() for r in results)


class TestChunProfile:
    """The generated chun came out at Si:Al 8.77 with Al2O3 0.425 -
    ordinary stoneware, which by the phase-separation mechanism cannot
    go blue. Anchored now on Wood's Jun (Si:Al 10.97, Al2O3 0.345), the
    same source the app validates its UMF math against."""

    def test_si_al_is_above_ordinary_stoneware(self, chun_profile):
        """A typical stoneware glaze sits near 8:1. A chun target that
        includes 8 is not describing a chun."""
        assert chun_profile["si_al_ratio"]["min"] >= 10.0

    def test_si_al_band_covers_wood_and_the_song_analyses(self, chun_profile):
        band = chun_profile["si_al_ratio"]
        assert band["min"] <= 10.97, "must admit Wood's own Jun recreation"
        assert band["max"] >= 12.43, "must admit the Song violet jun analysis"

    def test_alumina_stays_low_enough_to_separate(self, chun_profile):
        assert chun_profile["umf_overrides"]["Al2O3"]["max"] <= 0.36

    def test_bone_ash_constraint_matches_real_practice(self, chun_profile, recipe_db):
        """The constraint was 5-15%. Across 34 chun/jun recipes in the
        corpus the median is 2% and only two reach 5%."""
        limits = chun_profile["material_constraints"]["Bone Ash"]
        assert limits["max_pct"] <= 3.0

        observed = []
        for record in recipe_db.get_all():
            name = (record.get("name") or "").lower()
            if ("chun" in name or "jun" in name) and "chung" not in name:
                for ingredient in record.get("ingredients") or []:
                    material = (ingredient.get("name") or ingredient.get("material") or "").lower()
                    if "bone ash" in material:
                        observed.append(ingredient.get("pct") or ingredient.get("percentage") or 0)
        if observed:
            observed.sort()
            median = observed[len(observed) // 2]
            assert limits["min_pct"] <= median <= limits["max_pct"]

    def test_iron_is_required(self, chun_profile):
        """The blue is optical, but iron is still needed for it to read."""
        oxides = {c["oxide"] for c in chun_profile["required_colorants"]}
        assert "Fe2O3" in oxides

    def test_notes_do_not_claim_phosphorus_causes_opalescence(self, chun_profile):
        """Current analysis treats phosphate as amplifying the effect via
        bubble-size variation, not causing it."""
        text = (chun_profile["description"] + " " + chun_profile["notes"]).lower()
        assert "phase separation" in text

    def test_generated_chun_lands_in_band(self, client):
        response = client.post("/api/recipes/formulate", json={
            "cone": "10", "surface": "glossy",
            "atmosphere": "reduction", "category": "chun",
        })
        assert response.status_code == 200
        umf = response.json().get("achieved_umf") or {}
        sio2, al2o3 = umf.get("SiO2"), umf.get("Al2O3")
        assert sio2 and al2o3
        assert 10.0 <= sio2 / al2o3 <= 13.5, f"Si:Al {sio2 / al2o3:.2f} outside chun range"
        assert al2o3 <= 0.38


class TestOtherCategoriesStillFormulate:
    """P2O5 joined the solver's oxide set for chun's sake; the other
    categories must be unaffected."""

    @pytest.mark.parametrize("category", ["celadon", "tenmoku", "shino", "clear"])
    def test_category_still_produces_a_recipe(self, client, category):
        response = client.post("/api/recipes/formulate", json={
            "cone": "10", "surface": "glossy",
            "atmosphere": "reduction", "category": category,
        })
        assert response.status_code == 200
        assert (response.json().get("recipe") or {}).get("ingredients")
