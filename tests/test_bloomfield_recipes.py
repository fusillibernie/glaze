"""Sanity checks for data/recipes/bloomfield_special_effects.json (Linda &
Henry Bloomfield, "New Ceramics: Special Effect Glazes", 2020).
"""

import json
from pathlib import Path

import pytest

from src.services.recipe_db import RecipeDatabase


DATA_PATH = Path(__file__).parent.parent / "data" / "recipes" / "bloomfield_special_effects.json"


@pytest.fixture(scope="module")
def recipes():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return data["bloomfield_special_effect_glazes"]


class TestFileStructure:
    def test_expected_recipe_count(self, recipes):
        assert len(recipes) == 13

    def test_every_recipe_has_required_fields(self, recipes):
        for r in recipes:
            assert r["name"]
            assert r["source"] == "bloomfield-special-effect-glazes-2020"
            assert r["cone"]
            assert r["ingredients"]


class TestPercentageSanity:
    def test_base_ingredients_sum_near_100(self, recipes):
        offenders = [
            (r["name"], sum(i["percentage"] for i in r["ingredients"]))
            for r in recipes
            if not (90 <= sum(i["percentage"] for i in r["ingredients"]) <= 116)
        ]
        assert offenders == [], f"percentage sums out of range: {offenders}"


class TestKnownRecipes:
    def test_blue_celadon_has_two_copper_variants(self, recipes):
        r = next(x for x in recipes if x["name"] == "Blue Celadon (Porcelain, Copper)")
        assert len(r["variations"]) == 2
        percents = {v["colorants"][0]["percentage"] for v in r["variations"]}
        assert percents == {0.1, 0.5}


class TestIntegrationWithRecipeDatabase:
    def test_loads_via_real_recipe_database(self):
        db = RecipeDatabase()
        db.load()
        stats = db.statistics()
        assert stats["by_source"].get("bloomfield-special-effect-glazes-2020") == 13
