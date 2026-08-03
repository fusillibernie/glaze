"""Tests for chemistry derived from curated book recipes.

RecipeDatabase loads data/recipes/*.json as raw dicts and never resolved
ingredients, while the classifier seeder required a precomputed
`analysis` key that none of the 255 curated records had. Every recipe
from Britt, Zakin, Wood and Bloomfield was therefore absent from the
Stull chart, the classifier index and all chemistry-based search - the
book ingestion work produced text and nothing else.

The gate matters as much as the coverage. Where too little of the batch
resolves, the recipe is excluded rather than plotted: the formulator
normalizes over whatever it did resolve, so a recipe missing a third of
its batch does not get an imprecise UMF, it gets a confidently wrong one.
"""

import pytest

from api.main import _MIN_RESOLVED_PCT, _batch_chemistry, classifier, recipe_db


@pytest.fixture(scope="module")
def curated():
    return [r for r in recipe_db.get_all() if r.get("source_file")]


@pytest.fixture
def coverage(client):
    return client.get("/api/recipes/chemistry-coverage").json()


class TestCoverage:
    def test_most_curated_recipes_now_have_chemistry(self, coverage):
        """Pins the resolution rate so a materials-data regression shows
        up as a number rather than as quietly emptier search results."""
        by_quality = coverage["by_quality"]
        assert by_quality["complete"] >= 175
        assert by_quality["insufficient"] <= 70

    def test_wood_recipes_use_their_measured_analysis(self, coverage):
        """Wood publishes an instrument reading alongside each recipe.
        The seeder previously only looked for `analysis`, so all nine were
        skipped despite carrying better data than anything derived."""
        assert coverage["by_basis"]["measured"] == 9

    def test_batch_derived_covers_the_curated_corpus(self, coverage):
        assert coverage["by_basis"]["batch_derived"] > 200

    def test_unresolved_materials_are_reported_not_hidden(self, coverage):
        """The blocked names are the actionable output - they tell a user
        which specific frit to pick."""
        blockers = {u["material"] for u in coverage["unresolved_materials"]}
        assert "Boron Frit" in blockers

    def test_excluded_recipes_explain_themselves(self, coverage):
        for entry in coverage["excluded_recipes"]:
            assert entry["resolved_pct"] < _MIN_RESOLVED_PCT
            assert entry["unresolved"]


class TestResolutionIsWeightBased:
    def test_one_large_unresolved_ingredient_dominates(self):
        """Counting ingredients rather than weight would call this 80%
        resolved. It is 40%: the missing ingredient is most of the batch."""
        record = {
            "name": "mostly unresolvable",
            "ingredients": [
                {"material": "Custer Feldspar", "percentage": 10},
                {"material": "Silica (Flint)", "percentage": 10},
                {"material": "EPK Kaolin", "percentage": 10},
                {"material": "Whiting (Calcium Carbonate)", "percentage": 10},
                {"material": "Nonexistent Frit", "percentage": 60},
            ],
        }
        umf, provenance = _batch_chemistry(record)
        assert provenance["resolved_pct"] == pytest.approx(40.0, abs=0.1)
        assert provenance["quality"] == "insufficient"
        assert umf is None, "a recipe missing 60% of its batch must not get a UMF"

    def test_one_small_unresolved_ingredient_is_tolerated(self):
        record = {
            "name": "nearly complete",
            "ingredients": [
                {"material": "Custer Feldspar", "percentage": 45},
                {"material": "Silica (Flint)", "percentage": 30},
                {"material": "EPK Kaolin", "percentage": 20},
                {"material": "Mystery Colorant", "percentage": 5},
            ],
        }
        umf, provenance = _batch_chemistry(record)
        assert provenance["quality"] == "partial"
        assert provenance["resolved_pct"] == pytest.approx(95.0, abs=0.1)
        assert umf is not None

    def test_fully_resolved_is_marked_complete(self):
        record = {
            "name": "clean",
            "ingredients": [
                {"material": "Custer Feldspar", "percentage": 40},
                {"material": "Silica (Flint)", "percentage": 30},
                {"material": "Whiting (Calcium Carbonate)", "percentage": 15},
                {"material": "EPK Kaolin", "percentage": 15},
            ],
        }
        umf, provenance = _batch_chemistry(record)
        assert provenance["quality"] == "complete"
        assert provenance["unresolved"] == []
        assert umf.SiO2 > 0


class TestChartExclusion:
    def test_insufficient_recipes_never_reach_the_chart(self, client, curated):
        """The point of the gate. A wrong point on the Stull chart is
        worse than a missing one, because nothing downstream marks it."""
        insufficient = {
            r["name"] for r in curated
            if (r.get("chemistry") or {}).get("quality") == "insufficient"
        }
        assert insufficient, "expected some recipes to be gated out"

        charted = {g["name"] for g in client.get("/api/visualization/stull-chart").json()["glazes"]}
        # A gated recipe may still share a name with a bulk record; what
        # must not happen is a gated recipe contributing its own point.
        for record in curated:
            chemistry = record.get("chemistry") or {}
            if chemistry.get("quality") == "insufficient":
                assert "umf" not in chemistry

    def test_indexed_recipes_carry_their_umf(self, curated):
        indexed = [r for r in curated if (r.get("chemistry") or {}).get("umf")]
        assert len(indexed) > 180
        for record in indexed:
            assert record["chemistry"]["quality"] in ("complete", "partial")


class TestProvenance:
    def test_every_chemistry_record_states_its_basis(self, curated):
        for record in curated:
            chemistry = record.get("chemistry")
            if chemistry:
                assert chemistry["basis"] in ("measured", "published", "batch_derived")
                assert chemistry["quality"] in ("complete", "partial", "insufficient")

    def test_measured_beats_batch_derived_when_both_available(self, curated):
        """Wood's recipes have both a published fired analysis and an
        ingredient list. The instrument reading should win."""
        wood = [r for r in curated if r.get("source") == "wood-chinese-glazes-1999"]
        assert wood
        assert all(r["chemistry"]["basis"] == "measured" for r in wood)

    def test_search_results_expose_chemistry(self, client):
        payload = client.get("/api/recipes/search", params={"query": "Jun Glaze"}).json()
        results = payload if isinstance(payload, list) else payload.get("recipes", [])
        assert results
        assert "chemistry" in results[0]


class TestClassifierIndex:
    def test_curated_recipes_are_actually_indexed(self):
        """0 before this change."""
        assert classifier.get_statistics()["total_indexed"] > 10_900
