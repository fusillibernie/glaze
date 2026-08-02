"""Sanity checks for data/recipes/zakin_electric_kiln.json (Richard Zakin,
"Electric Kiln Ceramics: A Guide to Clays and Glazes", 3rd ed, 2004).
Parsed programmatically from the book's two-column dotted-leader tables
(word-position column splitting to avoid pdfplumber's default
interleaved-column text order) - these tests pin the parser's output
against manual spot-checks of the source pages.
"""

import json
from pathlib import Path

import pytest

from src.services.recipe_db import RecipeDatabase


DATA_PATH = Path(__file__).parent.parent / "data" / "recipes" / "zakin_electric_kiln.json"


@pytest.fixture(scope="module")
def recipes():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return data["zakin_electric_kiln_glazes"]


class TestFileStructure:
    def test_expected_recipe_count(self, recipes):
        assert len(recipes) == 60

    def test_every_recipe_has_required_fields(self, recipes):
        for r in recipes:
            assert r["name"]
            assert r["source"] == "zakin-electric-kiln-ceramics-2004"
            assert r["cone"]
            assert r["ingredients"]

    def test_all_oxidation_fired(self, recipes):
        """This chapter is exclusively oxidation - it's an electric kiln book."""
        assert all(r["atmosphere"] == "oxidation" for r in recipes)


class TestPercentageSanity:
    """Base ingredients should sum close to 100. Two named exceptions
    (Dewitt Mills at 88%, Franklin R 92 at 80%) are confirmed against the
    source page text - not a parsing gap, the book prints them this way."""

    KNOWN_EXCEPTIONS = {"Dewitt Mills", "Franklin R 92"}

    def test_base_ingredients_sum_near_100(self, recipes):
        offenders = []
        for r in recipes:
            if r["name"] in self.KNOWN_EXCEPTIONS:
                continue
            total = sum(i["percentage"] for i in r["ingredients"])
            if not (90 <= total <= 110):
                offenders.append((r["name"], total))
        assert offenders == [], f"percentage sums out of range: {offenders}"

    def test_known_exceptions_match_book(self, recipes):
        totals = {r["name"]: sum(i["percentage"] for i in r["ingredients"]) for r in recipes}
        assert totals["Dewitt Mills"] == pytest.approx(88.0)
        assert totals["Franklin R 92"] == pytest.approx(80.0)

    def test_no_negative_or_zero_percentages(self, recipes):
        for r in recipes:
            for i in r["ingredients"]:
                assert i["percentage"] > 0, f"{r['name']}: {i['material']} has non-positive percentage"


class TestKnownRecipes:
    def _find(self, recipes, name):
        return next(r for r in recipes if r["name"] == name)

    def test_estacada_typo_correction_noted(self, recipes):
        """Book prints 'potash'/'spodium' (not 'potash feldspar'/
        'spodumene') for this one recipe - transcribed literally then
        resolved, with the substitution recorded in notes."""
        r = self._find(recipes, "Estacada")
        materials = {i["material"] for i in r["ingredients"]}
        assert "Potash Feldspar" in materials
        assert "Spodumene" in materials
        assert "as printed" in r["notes"]

    def test_canton_brown_colorant_variation(self, recipes):
        r = self._find(recipes, "Canton Brown")
        colorants = {c["material"]: c["percentage"] for c in r["variations"][0]["colorants"]}
        assert colorants["Cobalt Carbonate"] == 1.5

    def test_boron_frit_3124_resolved_not_generic(self, recipes):
        """'boron frit 3124'/'boron frit (3124)' name a specific frit and
        should map to Frit 3124, unlike bare 'boron frit' elsewhere."""
        r = self._find(recipes, "Robin's 1b Clear k2")
        materials = {i["material"] for i in r["ingredients"]}
        assert "Frit 3124" in materials


class TestIntegrationWithRecipeDatabase:
    def test_loads_via_real_recipe_database(self):
        db = RecipeDatabase()
        db.load()
        stats = db.statistics()
        assert stats["by_source"].get("zakin-electric-kiln-ceramics-2004") == 60

    def test_searchable_by_name(self):
        db = RecipeDatabase()
        db.load()
        results = db.search(query="Ridgebury")
        assert any(r["name"] == "Ridgebury" for r in results)
