"""Tests for CommunityRecipeService - the in-memory index behind the
Community tab and Stull chart overlay (10,899 real records in
production). No test coverage existed for this module before.

Uses a small synthetic dataset written to a tmp_path file rather than the
real 7.9MB glazy_recipes.json, so tests are fast and each fixture record's
expected index/UMF behavior is known exactly rather than incidental to
whatever happens to be in the live corpus.
"""

import json

import pytest

from src.services.glazy_bulk import CommunityRecipeService


SAMPLE_RECIPES = [
    {
        "id": 1, "name": "Amber Celadon", "cone": "10", "surface": "Glossy",
        "subtype": "Glaze", "atmospheres": ["Reduction"],
        "description": "A classic amber celadon with iron breaks",
        "ingredients": [{"name": "Custer Feldspar", "pct": 50}],
        # SiO2 65.7% -> 1.0935 mol, Al2O3 11.5% -> 0.1128 mol,
        # flux = CaO 10.0% -> 0.1783 mol. Normalized to flux unity:
        # SiO2 UMF 6.13, Al2O3 UMF 0.633, Si:Al ratio 9.70.
        "analysis": {"SiO2": 65.7, "Al2O3": 11.5, "CaO": 10.0},
    },
    {
        "id": 2, "name": "Matte White", "cone": "6", "surface": "Matte",
        "subtype": "Glaze", "atmospheres": ["Oxidation"],
        "description": "Buttery satin matte",
        "ingredients": [{"name": "Talc", "pct": 20}, {"name": "Custer Feldspar", "pct": 40}],
        "analysis": {"SiO2": 55.0, "Al2O3": 18.0, "MgO": 8.0},
    },
    {
        "id": 3, "name": "Tenmoku Black", "cone": "10", "surface": "Glossy",
        "subtype": "Glaze", "atmospheres": ["Reduction", "Oxidation"],
        "description": "Iron-saturated black breaking to rust at edges",
        "ingredients": [{"name": "Red Iron Oxide", "pct": 8}],
        "analysis": {"SiO2": 60.0, "Al2O3": 10.0, "Fe2O3": 8.0},
    },
    {
        "id": 4, "name": "No Analysis Glaze", "cone": "04", "surface": "Glossy",
        "subtype": "Glaze", "atmospheres": [],
        "description": "",
        "ingredients": [],
        "analysis": {},
    },
]


@pytest.fixture
def data_path(tmp_path):
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps(SAMPLE_RECIPES), encoding="utf-8")
    return path


@pytest.fixture
def service(data_path):
    return CommunityRecipeService(data_path)


class TestLoading:
    def test_total_matches_record_count(self, service):
        assert service.total == 4

    def test_missing_file_loads_empty_without_crashing(self, tmp_path):
        svc = CommunityRecipeService(tmp_path / "does_not_exist.json")
        assert svc.total == 0

    def test_umf_computed_from_analysis(self, service):
        """UMF is normalized to flux unity, so it shares a coordinate space
        with user recipes on the Stull chart.

        These fields used to hold the Si:Al ratio in sio2_umf and raw
        moles-per-100g in al2o3_umf - which put ~70% of the community
        overlay off the right edge of a chart drawn on [0, 6].
        """
        r = service.get_by_id(1)
        assert r["sio2_umf"] == pytest.approx(6.13, abs=0.02)
        assert r["al2o3_umf"] == pytest.approx(0.633, abs=0.002)
        assert r["si_al_ratio"] == pytest.approx(9.70, abs=0.05)

    def test_sio2_umf_is_not_the_ratio(self, service):
        """Guards the specific regression: the two fields were computed by
        identical expressions."""
        r = service.get_by_id(1)
        assert r["sio2_umf"] != r["si_al_ratio"]

    def test_umf_lands_in_chart_range(self, service):
        """Resolvable records should plot inside the Stull chart's drawn
        axes (SiO2 0-6, Al2O3 0-1) rather than off-canvas."""
        for rid in (1, 2):
            r = service.get_by_id(rid)
            assert 0 < r["sio2_umf"] < 6.5, f"recipe {rid} SiO2 off-chart"
            assert 0 < r["al2o3_umf"] < 1.0, f"recipe {rid} Al2O3 off-chart"

    def test_fluxless_recipe_is_excluded_not_plotted(self, service):
        """Recipe 3 is SiO2/Al2O3/Fe2O3 only - no flux oxides, so UMF
        (which normalizes fluxes to unity) is undefined. It must report
        zero and be dropped from the overlay rather than plotted at a
        meaningless coordinate, which is what the old ratio-based
        calculation did.
        """
        r = service.get_by_id(3)
        assert r["sio2_umf"] == 0
        assert r["al2o3_umf"] == 0
        assert all(p["id"] != 3 for p in service.stull_scatter())

    def test_missing_analysis_defaults_umf_to_zero(self, service):
        r = service.get_by_id(4)
        assert r["sio2_umf"] == 0
        assert r["al2o3_umf"] == 0


class TestSearch:
    def test_search_by_cone_filters_correctly(self, service):
        result = service.search(cone="10")
        ids = {r["id"] for r in result["recipes"]}
        assert ids == {1, 3}

    def test_search_by_surface_is_case_insensitive(self, service):
        result = service.search(surface="glossy")
        ids = {r["id"] for r in result["recipes"]}
        assert 1 in ids and 3 in ids and 2 not in ids

    def test_search_by_atmosphere(self, service):
        result = service.search(atmosphere="oxidation")
        ids = {r["id"] for r in result["recipes"]}
        assert ids == {2, 3}

    def test_combined_filters_intersect_not_union(self, service):
        """cone=10 alone matches {1,3}; surface=glossy alone matches
        {1,3,4}. Together must be the intersection, not the union."""
        result = service.search(cone="10", surface="glossy")
        ids = {r["id"] for r in result["recipes"]}
        assert ids == {1, 3}

    def test_text_query_matches_name(self, service):
        result = service.search(query="celadon")
        assert any(r["id"] == 1 for r in result["recipes"])

    def test_text_query_matches_description(self, service):
        result = service.search(query="breaking")
        ids = {r["id"] for r in result["recipes"]}
        assert 3 in ids

    def test_text_query_requires_all_terms(self, service):
        """Multi-word query is an AND, not an OR - 'amber rust' matches no
        single recipe even though each word alone matches one."""
        result = service.search(query="amber rust")
        assert result["total"] == 0

    def test_name_match_ranks_above_description_only_match(self, service):
        """'Tenmoku' is in recipe 3's name; make sure name matches sort
        ahead of a hypothetical description-only match for the same term."""
        result = service.search(query="tenmoku")
        assert result["recipes"][0]["id"] == 3

    def test_pagination_page_size_respected(self, service):
        result = service.search(page=1, page_size=2)
        assert len(result["recipes"]) == 2
        assert result["total"] == 4
        assert result["total_pages"] == 2

    def test_pagination_out_of_range_clamps_to_last_page(self, service):
        result = service.search(page=99, page_size=2)
        assert result["page"] == 2

    def test_unknown_cone_returns_empty_not_everything(self, service):
        """A cone filter that matches no index entries must return zero
        results, not silently fall back to the unfiltered set."""
        result = service.search(cone="not-a-real-cone")
        assert result["total"] == 0


class TestGetById:
    def test_known_id_returns_detail_fields(self, service):
        r = service.get_by_id(1)
        assert r["name"] == "Amber Celadon"
        assert "ingredients" in r
        assert "analysis" in r

    def test_unknown_id_returns_none(self, service):
        assert service.get_by_id(99999) is None

    def test_list_format_omits_detail_fields(self, service):
        result = service.search(query="celadon")
        listed = result["recipes"][0]
        assert "ingredients" not in listed
        assert "ingredient_count" in listed


class TestStullNeighbors:
    def test_finds_recipes_within_radius(self, service):
        # Recipe 1 sits at SiO2 UMF 6.13 / Al2O3 UMF 0.633
        neighbors = service.stull_neighbors(sio2=6.13, al2o3=0.633, radius=0.5)
        assert any(n["id"] == 1 for n in neighbors)

    def test_excludes_recipes_with_no_umf_data(self, service):
        neighbors = service.stull_neighbors(sio2=0, al2o3=0, radius=999)
        assert not any(n["id"] == 4 for n in neighbors)

    def test_sorted_by_distance_ascending(self, service):
        neighbors = service.stull_neighbors(sio2=6.13, al2o3=0.633, radius=999)
        distances = [n["distance"] for n in neighbors]
        assert distances == sorted(distances)

    def test_respects_limit(self, service):
        neighbors = service.stull_neighbors(sio2=6.13, al2o3=0.633, radius=999, limit=1)
        assert len(neighbors) <= 1


class TestStats:
    def test_total_recipes_matches_count(self, service):
        stats = service.stats()
        assert stats["total_recipes"] == 4

    def test_cone_counts_correct(self, service):
        stats = service.stats()
        assert stats["cones"]["10"] == 2
        assert stats["cones"]["6"] == 1

    def test_atmosphere_counts_split_multi_atmosphere_recipes(self, service):
        """Recipe 3 lists both Reduction and Oxidation - it must count
        toward both, not just the first."""
        stats = service.stats()
        assert stats["atmospheres"]["Reduction"] == 2
        assert stats["atmospheres"]["Oxidation"] == 2


class TestFilterOptions:
    def test_cones_sorted_numerically_not_lexically(self, service):
        """Lexical sort would put '10' before '6'; cones must sort by
        actual firing temperature order."""
        options = service.get_filter_options()
        assert options["cones"].index("6") < options["cones"].index("10")

    def test_low_fire_cone_with_leading_zero_sorts_correctly(self, service):
        options = service.get_filter_options()
        # "04" (cone 04, low fire) must sort before "6" (mid fire)
        assert options["cones"].index("04") < options["cones"].index("6")
