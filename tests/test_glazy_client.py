"""Tests for GlazyClient - the Glazy.org API integration. No test
coverage existed for this module before.

HTTP calls are mocked with respx rather than hitting the real API: real
network calls in a test suite are slow, flaky, and Glazy.org's API isn't
this project's to keep available. Cache/fallback behavior is tested
against tmp_path directories, never the real data/glazy_cache/.
"""

import json

import httpx
import pytest
import respx

from src.integrations.glazy_client import GlazyClient, GLAZY_API_BASE
from src.models.glaze import ConeTemperature, AtmosphereType, GlazeSurface


@pytest.fixture
def client(tmp_path):
    return GlazyClient(cache_dir=tmp_path / "glazy_cache")


class TestSearchRecipes:
    @respx.mock
    def test_successful_search_parses_results(self, client):
        respx.get(f"{GLAZY_API_BASE}/search").mock(
            return_value=httpx.Response(200, json={
                "data": [{
                    "id": 42, "name": "Test Celadon",
                    "createdByUserName": "potter1",
                    "fromOrtonConeName": "10", "toOrtonConeName": "10",
                    "atmosphereTypeName": "Reduction",
                    "surfaceTypeName": "Glossy",
                    "description": "A test recipe",
                }]
            })
        )
        results = client.search_recipes(query="celadon")
        assert len(results) == 1
        assert results[0].glazy_id == 42
        assert results[0].name == "Test Celadon"
        assert results[0].creator == "potter1"
        assert results[0].cone_range == "10"

    @respx.mock
    def test_cone_range_shows_span_when_different(self, client):
        respx.get(f"{GLAZY_API_BASE}/search").mock(
            return_value=httpx.Response(200, json={
                "data": [{"id": 1, "name": "x", "fromOrtonConeName": "6", "toOrtonConeName": "10"}]
            })
        )
        results = client.search_recipes()
        assert results[0].cone_range == "6 - 10"

    @respx.mock
    def test_image_url_built_from_selected_image(self, client):
        respx.get(f"{GLAZY_API_BASE}/search").mock(
            return_value=httpx.Response(200, json={
                "data": [{
                    "id": 42, "name": "x",
                    "selectedImage": {"filename": "photo.jpg"},
                }]
            })
        )
        results = client.search_recipes()
        assert results[0].image_url.endswith("/uploads/recipes/42/s_photo.jpg")

    @respx.mock
    def test_keywords_combine_all_search_terms(self, client):
        route = respx.get(f"{GLAZY_API_BASE}/search").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client.search_recipes(query="blue", cone="6", atmosphere="oxidation", surface="matte")
        sent_params = dict(httpx.QueryParams(route.calls[0].request.url.params))
        assert "blue" in sent_params["keywords"]
        assert "cone 6" in sent_params["keywords"]
        assert "oxidation" in sent_params["keywords"]
        assert "matte" in sent_params["keywords"]

    @respx.mock
    def test_api_failure_falls_back_to_local_recipes(self, client):
        respx.get(f"{GLAZY_API_BASE}/search").mock(return_value=httpx.Response(500))
        # Should not raise - falls back through cache (empty) to local recipes
        results = client.search_recipes(query="basic")
        assert isinstance(results, list)

    @respx.mock
    def test_network_error_does_not_raise(self, client):
        respx.get(f"{GLAZY_API_BASE}/search").mock(side_effect=httpx.ConnectError("boom"))
        results = client.search_recipes()
        assert isinstance(results, list)

    @respx.mock
    def test_invalid_json_falls_back_gracefully(self, client):
        respx.get(f"{GLAZY_API_BASE}/search").mock(
            return_value=httpx.Response(200, content=b"not json")
        )
        results = client.search_recipes()
        assert isinstance(results, list)

    @respx.mock
    def test_api_failure_uses_cache_before_local_fallback(self, client, tmp_path):
        cache_dir = client.cache_dir / "recipe"
        cache_dir.mkdir(parents=True)
        (cache_dir / "99.json").write_text(json.dumps({
            "id": 99, "name": "Cached Recipe", "cone": "6",
        }), encoding="utf-8")

        respx.get(f"{GLAZY_API_BASE}/search").mock(return_value=httpx.Response(500))
        results = client.search_recipes(query="cached")
        assert any(r.name == "Cached Recipe" for r in results)


class TestGetRecipe:
    def test_cache_hit_skips_http_call(self, client):
        cache_dir = client.cache_dir / "recipe"
        cache_dir.mkdir(parents=True)
        (cache_dir / "5.json").write_text(json.dumps({
            "id": 5, "name": "From Cache", "cone": "6", "atmosphere": "oxidation",
        }), encoding="utf-8")

        with respx.mock:
            # No route registered - a real HTTP call here would error/fail the test
            recipe = client.get_recipe(5)
        assert recipe.name == "From Cache"

    @respx.mock
    def test_cache_miss_fetches_and_caches(self, client):
        respx.get(f"{GLAZY_API_BASE}/recipes/7").mock(
            return_value=httpx.Response(200, json={
                "data": {"id": 7, "name": "Fresh Recipe", "cone": "6", "atmosphere": "oxidation"}
            })
        )
        recipe = client.get_recipe(7)
        assert recipe.name == "Fresh Recipe"
        assert (client.cache_dir / "recipe" / "7.json").exists()

    @respx.mock
    def test_http_failure_returns_none(self, client):
        respx.get(f"{GLAZY_API_BASE}/recipes/8").mock(return_value=httpx.Response(404))
        assert client.get_recipe(8) is None


class TestGetMaterial:
    @respx.mock
    def test_fetches_and_parses_material(self, client):
        respx.get(f"{GLAZY_API_BASE}/materials/3").mock(
            return_value=httpx.Response(200, json={
                "data": {
                    "id": 3, "name": "Custer Feldspar",
                    "analysis": {"SiO2": 68.5, "Al2O3": 17.0},
                }
            })
        )
        material = client.get_material(3)
        assert material.name == "Custer Feldspar"
        assert material.analysis.oxide_analysis.SiO2 == 68.5
        assert material.analysis.source == "Glazy.org"

    @respx.mock
    def test_http_failure_returns_none(self, client):
        respx.get(f"{GLAZY_API_BASE}/materials/9").mock(return_value=httpx.Response(500))
        assert client.get_material(9) is None


class TestParseRecipe:
    def test_valid_cone_parsed(self, client):
        recipe = client._parse_recipe({"name": "x", "cone": "10", "atmosphere": "oxidation"})
        assert recipe.target_cone == ConeTemperature.CONE_10

    def test_invalid_cone_falls_back_to_cone_6(self, client):
        recipe = client._parse_recipe({"name": "x", "cone": "not-a-cone"})
        assert recipe.target_cone == ConeTemperature.CONE_6

    def test_reduction_atmosphere_detected(self, client):
        recipe = client._parse_recipe({"name": "x", "atmosphere": "Heavy Reduction"})
        assert recipe.suitable_atmospheres == [AtmosphereType.REDUCTION]

    def test_default_atmosphere_is_oxidation(self, client):
        recipe = client._parse_recipe({"name": "x"})
        assert recipe.suitable_atmospheres == [AtmosphereType.OXIDATION]

    def test_matte_surface_detected(self, client):
        recipe = client._parse_recipe({"name": "x", "surface_type": "Matte"})
        assert recipe.expected_surface == GlazeSurface.MATTE

    def test_satin_matte_is_a_satin(self, client):
        """This test used to assert "Satin Matte" -> MATTE, matching the old
        parser's substring check. That is the classification the rest of
        the app measured as wrong: treating satin-matte as matte put 1,092
        non-matte glazes into a "matte" search, and the surface model is
        trained with Satin-matte labelled satin. Glazy import now agrees
        with the rest of the app."""
        recipe = client._parse_recipe({"name": "x", "surface_type": "Satin Matte"})
        assert recipe.expected_surface == GlazeSurface.SATIN

    def test_satin_surface_detected(self, client):
        recipe = client._parse_recipe({"name": "x", "surface_type": "Satin"})
        assert recipe.expected_surface == GlazeSurface.SATIN

    def test_default_surface_is_glossy(self, client):
        recipe = client._parse_recipe({"name": "x"})
        assert recipe.expected_surface == GlazeSurface.GLOSSY

    def test_ingredients_parsed_from_components(self, client):
        recipe = client._parse_recipe({
            "name": "x",
            "components": [{"material": {"name": "Custer Feldspar"}, "amount": 50, "material_id": 1}],
        })
        assert recipe.ingredients[0].material_name == "Custer Feldspar"
        assert recipe.ingredients[0].percentage == 50

    def test_umf_parsed_when_present(self, client):
        recipe = client._parse_recipe({
            "name": "x", "umf": {"SiO2": 3.5, "Al2O3": 0.4},
        })
        assert recipe.umf.SiO2 == 3.5
        assert recipe.umf.Al2O3 == 0.4

    def test_no_umf_key_leaves_umf_none(self, client):
        recipe = client._parse_recipe({"name": "x"})
        assert recipe.umf is None


class TestParseMaterial:
    @pytest.mark.parametrize("name,expected_type", [
        ("Custer Feldspar", "feldspar"),
        ("EPK Kaolin", "clay"),
        ("Ball Clay", "clay"),
        ("Silica (Flint)", "silica"),
        ("Frit 3134", "frit"),
        ("Wood Ash", "ash"),
        ("Whiting", "other"),
    ])
    def test_material_type_inferred_from_name(self, client, name, expected_type):
        material = client._parse_material({"name": name, "analysis": {}})
        assert material.material_type.value == expected_type


class TestCaching:
    def test_save_then_load_round_trips(self, client):
        client._save_to_cache("recipe", 123, {"name": "Round Trip"})
        loaded = client._load_from_cache("recipe", 123)
        assert loaded == {"name": "Round Trip"}

    def test_load_missing_cache_returns_none(self, client):
        assert client._load_from_cache("recipe", 999999) is None


class TestSearchLocalRecipes:
    """_search_local_recipes hardcodes its own path
    (Path(__file__).parent.parent.parent / "data" / "recipes") rather than
    taking one as an argument, so - like target_resolver's tests - these
    run against the real bundled data rather than a redirected fixture.
    "Leach 4321" at cone 10 is a known real entry in base_glazes.json.
    """

    def test_finds_a_known_bundled_recipe_by_query(self, client):
        results = client._search_local_recipes(
            query="Leach 4321", cone=None, atmosphere=None, surface=None, limit=10,
        )
        assert any(r.name == "Leach 4321" for r in results)

    def test_cone_filter_excludes_non_matching_recipes(self, client):
        results = client._search_local_recipes(
            query=None, cone="10", atmosphere=None, surface=None, limit=1000,
        )
        assert all(r.cone_range == "10" for r in results)
        assert any(r.name == "Leach 4321" for r in results)

    def test_query_filters_out_non_matching_recipes(self, client):
        results = client._search_local_recipes(
            query="Leach 4321", cone=None, atmosphere=None, surface=None, limit=1000,
        )
        assert all("leach 4321" in r.name.lower() for r in results)

    def test_local_recipe_ids_start_above_100000(self, client):
        """Avoids colliding with real Glazy IDs, which are much smaller."""
        results = client._search_local_recipes(
            query=None, cone=None, atmosphere=None, surface=None, limit=1,
        )
        assert results and results[0].glazy_id > 100000

    def test_local_recipe_marked_with_local_creator(self, client):
        results = client._search_local_recipes(
            query="Leach 4321", cone=None, atmosphere=None, surface=None, limit=10,
        )
        assert results[0].creator == "Local Recipe"
