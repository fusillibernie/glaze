"""Sanity checks for data/recipes/britt_oil_spot.json (John Britt,
"Secrets of Oil Spot Glazes", 2024). Guards the two things a hand-transcribed
recipe file can get wrong silently: base-ingredient percentages that don't
sum near 100 (found and fixed twice while building this file - a missing
calcined-clay line, and colorant additions that should have been in
`variations` rather than flattened into the base), and load-path
integration with the app's real recipe database.
"""

import json
from pathlib import Path

import pytest

from src.services.recipe_db import RecipeDatabase


DATA_PATH = Path(__file__).parent.parent / "data" / "recipes" / "britt_oil_spot.json"


@pytest.fixture(scope="module")
def recipes():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return data["britt_oil_spot_glazes"]


class TestFileStructure:
    def test_expected_recipe_count(self, recipes):
        assert len(recipes) == 71

    def test_every_recipe_has_required_fields(self, recipes):
        for r in recipes:
            assert r["name"]
            assert r["source"] == "britt-oil-spot-2024"
            assert r["cone"]
            assert r["ingredients"]

    def test_source_ids_are_unique(self, recipes):
        ids = [r["source_id"] for r in recipes]
        assert len(ids) == len(set(ids))


class TestPercentageSanity:
    """Base ingredient percentages should sum close to 100 (a bit over is
    normal - colorants/opacifiers are often listed inline rather than
    split into `variations`). A sum far outside that range means a
    transcription error, not a real recipe - this caught two during
    construction (John's SG-12 Calcined missing its calcined-clay line at
    85.5%, and Old Gold/Pinnell Manganese with 35-50 percentage points of
    manganese dioxide flattened into the base rather than modeled as a
    variation, at 134-150%)."""

    @pytest.mark.parametrize("min_pct,max_pct", [(90, 120)])
    def test_base_ingredients_sum_near_100(self, recipes, min_pct, max_pct):
        offenders = []
        for r in recipes:
            total = sum(i["percentage"] for i in r["ingredients"])
            if not (min_pct <= total <= max_pct):
                offenders.append((r["name"], total))
        assert offenders == [], f"percentage sums out of range: {offenders}"

    def test_no_negative_or_zero_percentages(self, recipes):
        for r in recipes:
            for i in r["ingredients"]:
                assert i["percentage"] > 0, f"{r['name']}: {i['material']} has non-positive percentage"


class TestKnownRecipes:
    """Spot-checks against the source text for a few recipes, including
    the ones that were corrected during construction."""

    def _find(self, recipes, name):
        return next(r for r in recipes if r["name"] == name)

    def test_johns_sg12_calcined_includes_both_redart_portions(self, recipes):
        r = self._find(recipes, "John's SG-12 Calcined")
        redart_lines = [i for i in r["ingredients"] if i["material"] == "Red Art"]
        assert len(redart_lines) == 2
        assert sum(i["percentage"] for i in redart_lines) == pytest.approx(40.12, abs=0.01)

    def test_old_gold_colorants_are_a_variation_not_base(self, recipes):
        r = self._find(recipes, "Old Gold")
        base_materials = {i["material"] for i in r["ingredients"]}
        assert "Manganese Dioxide" not in base_materials
        assert "Copper Carbonate" not in base_materials
        variation = r["variations"][0]
        colorant_pct = {c["material"]: c["percentage"] for c in variation["colorants"]}
        assert colorant_pct["Manganese Dioxide"] == 35.0
        assert colorant_pct["Copper Carbonate"] == 15.0

    def test_button_gold_frit_series_percentages_increase(self, recipes):
        """The GB-10 through GB-35 series should show monotonically
        increasing frit percentage - a transcription swap between two
        entries would break this."""
        series = ["John's GB-10", "John's GB-15", "John's GB-20",
                  "John's GB-25", "John's GB-30", "John's GB-35"]
        frit_pcts = []
        for name in series:
            r = self._find(recipes, name)
            frit = next(i for i in r["ingredients"] if i["material"] == "Ferro Frit 3269")
            frit_pcts.append(frit["percentage"])
        assert frit_pcts == sorted(frit_pcts)


class TestIntegrationWithRecipeDatabase:
    def test_loads_via_real_recipe_database(self):
        db = RecipeDatabase()
        db.load()
        stats = db.statistics()
        assert stats["by_source"].get("britt-oil-spot-2024") == 71

    def test_searchable_by_name(self):
        db = RecipeDatabase()
        db.load()
        results = db.search(query="Candace Black")
        assert any(r["name"] == "Candace Black" for r in results)
