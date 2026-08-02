"""Sanity checks for data/recipes/wood_chinese_glazes.json (Nigel Wood,
"Chinese Glazes: Their Origins, Chemistry and Re-creation", 1999/2007).
Transcribed from page images rather than the OCR text layer, since the
book's two-column ingredient tables come out scrambled through
pdfplumber's text extraction - these tests pin the numbers actually read
off the page.
"""

import json
from pathlib import Path

import pytest

from src.services.recipe_db import RecipeDatabase


DATA_PATH = Path(__file__).parent.parent / "data" / "recipes" / "wood_chinese_glazes.json"


@pytest.fixture(scope="module")
def recipes():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return data["wood_chinese_glazes"]


class TestFileStructure:
    def test_expected_recipe_count(self, recipes):
        assert len(recipes) == 9

    def test_every_recipe_has_required_fields(self, recipes):
        for r in recipes:
            assert r["name"]
            assert r["source"] == "wood-chinese-glazes-1999"
            assert r["cone"]
            assert r["ingredients"]

    def test_source_ids_are_unique(self, recipes):
        ids = [r["source_id"] for r in recipes]
        assert len(ids) == len(set(ids))


class TestPercentageSanity:
    def test_base_ingredients_sum_near_100(self, recipes):
        offenders = [
            (r["name"], sum(i["percentage"] for i in r["ingredients"]))
            for r in recipes
            if not (90 <= sum(i["percentage"] for i in r["ingredients"]) <= 110)
        ]
        assert offenders == [], f"percentage sums out of range: {offenders}"

    def test_no_negative_or_zero_percentages(self, recipes):
        for r in recipes:
            for i in r["ingredients"]:
                assert i["percentage"] > 0, f"{r['name']}: {i['material']} has non-positive percentage"


class TestKnownRecipes:
    """Spot-checks against the source page images."""

    def _find(self, recipes, source_id):
        return next(r for r in recipes if r["source_id"] == source_id)

    def test_jun_glaze_ingredients(self, recipes):
        r = self._find(recipes, "glaze-9")
        pct = {i["material"]: i["percentage"] for i in r["ingredients"]}
        assert pct["Potash Feldspar"] == 45
        assert pct["Quartz"] == 29
        assert pct["Bone Ash"] == 2.0
        assert r["fired_oxide_analysis"]["SiO2"] == 68.2

    def test_temmoku_has_dual_atmosphere_result(self, recipes):
        r = self._find(recipes, "glaze-4")
        assert "oxidation" in r["atmosphere"].lower()
        assert "reduction" in r["atmosphere"].lower()

    def test_mirror_black_colorant_percentages(self, recipes):
        r = self._find(recipes, "glaze-6")
        pct = {i["material"]: i["percentage"] for i in r["ingredients"]}
        assert pct["Manganese Dioxide"] == 3.2
        assert pct["Cobalt Carbonate"] == 0.5

    def test_all_recipes_have_fired_oxide_analysis(self, recipes):
        """Wood's recipes are unusual in also publishing a fired
        oxide-percentage analysis alongside the batch recipe - every
        recipe in this file should carry both."""
        for r in recipes:
            assert r["fired_oxide_analysis"]["SiO2"] > 0


class TestIntegrationWithRecipeDatabase:
    def test_loads_via_real_recipe_database(self):
        db = RecipeDatabase()
        db.load()
        stats = db.statistics()
        assert stats["by_source"].get("wood-chinese-glazes-1999") == 9

    def test_searchable_by_name(self):
        db = RecipeDatabase()
        db.load()
        results = db.search(query="Jun Glaze")
        assert any("Jun Glaze" in r["name"] for r in results)
