"""Glazy import against the API's current response shape.

The recipe parser had been written against an obsolete Glazy schema -
`components`, `amount`, `cone`, `atmosphere`, `surface_type`, `umf` - of
which only `name` still exists. Every import came back with the right
name and nothing else. The UI then treated the empty ingredient list as
a success (an empty array is truthy in JavaScript), so a cone 9-10
reduction chun "imported" as an empty cone 6 oxidation recipe and the
user saw nothing at all.

The existing tests in test_glazy_client.py did not catch it because they
were written against the same obsolete schema: test and parser agreed
with each other and both disagreed with the real API.

The fixture below is trimmed from a real API response (Glazy recipe 137,
"Blue Chun Glaze") rather than written from a guess at the format, so it
tracks what Glazy actually sends.
"""

import json

import httpx
import pytest
import respx

from src.integrations.glazy_client import (
    GLAZY_API_BASE,
    GlazyClient,
    glazy_recipe_url,
)
from src.models.glaze import AtmosphereType, ConeTemperature, GlazeSurface


def blue_chun():
    """Trimmed from the live response for Glazy recipe 137."""
    def component(name, amount, additional=False, material_id=1):
        return {
            "percentageAmount": f"{amount:.4f}",   # Glazy sends strings
            "isAdditional": additional,
            "material": {"id": material_id, "name": name},
        }

    return {
        "id": 137,
        "name": "Blue Chun Glaze",
        "description": "Fire as you would a copper red.",
        "fromOrtonConeName": "9",
        "toOrtonConeName": "10",
        "surfaceTypeName": "Glossy",
        "atmospheres": [{"id": 3, "name": "Reduction"}],
        "materialComponents": [
            component("Potash Feldspar", 54.8, material_id=11),
            component("Silica", 27.4, material_id=12),
            component("Whiting", 13.7, material_id=13),
            component("Barium Carbonate", 2.7, material_id=14),
            component("Bone Ash", 1.4, material_id=15),
            component("Red Iron Oxide", 1.1, additional=True, material_id=16),
        ],
        "analysis": {
            "umfAnalysis": {
                "SiO2": "3.9781", "Al2O3": "0.3742", "K2O": "0.3741",
                "CaO": "0.5739", "BaO": "0.0520", "P2O5": "0.0159",
                "Fe2O3": "0.0249",
            }
        },
    }


@pytest.fixture
def client(tmp_path):
    return GlazyClient(cache_dir=tmp_path / "glazy_cache")


class TestCurrentSchema:
    def test_ingredients_are_read_from_material_components(self, client):
        recipe = client._parse_recipe(blue_chun())
        names = [i.material_name for i in recipe.ingredients]
        assert names == ["Potash Feldspar", "Silica", "Whiting", "Barium Carbonate", "Bone Ash"]

    def test_string_amounts_become_numbers(self, client):
        recipe = client._parse_recipe(blue_chun())
        assert recipe.ingredients[0].percentage == pytest.approx(54.8)

    def test_additional_components_become_colorants(self, client):
        """Glazy's isAdditional marks additions on top of the base.
        Previously discarded, so this chun imported without its iron."""
        recipe = client._parse_recipe(blue_chun())
        assert [c.material_name for c in recipe.colorants] == ["Red Iron Oxide"]
        assert recipe.colorants[0].percentage == pytest.approx(1.1)
        assert "Red Iron Oxide" not in [i.material_name for i in recipe.ingredients]

    def test_base_sums_to_the_unadditioned_total(self, client):
        recipe = client._parse_recipe(blue_chun())
        assert sum(i.percentage for i in recipe.ingredients) == pytest.approx(100.0)

    def test_cone_is_the_top_of_the_range_not_a_default(self, client):
        """The old parser fell back to cone 6 for every import."""
        assert client._parse_recipe(blue_chun()).target_cone == ConeTemperature.CONE_10

    def test_atmosphere_is_read_not_defaulted(self, client):
        """The old parser fell back to oxidation - wrong for a chun."""
        assert client._parse_recipe(blue_chun()).suitable_atmospheres == [AtmosphereType.REDUCTION]

    def test_surface_is_read(self, client):
        assert client._parse_recipe(blue_chun()).expected_surface == GlazeSurface.GLOSSY

    def test_glazy_umf_is_parsed_including_colorant_oxides(self, client):
        umf = client._parse_recipe(blue_chun()).umf
        assert umf.SiO2 == pytest.approx(3.9781)
        assert umf.Al2O3 == pytest.approx(0.3742)
        assert umf.Fe2O3 == pytest.approx(0.0249)
        assert umf.P2O5 == pytest.approx(0.0159)

    def test_keeps_the_glazy_id(self, client):
        assert client._parse_recipe(blue_chun()).glazy_id == 137


class TestCacheShape:
    def test_wrapped_and_unwrapped_parse_identically(self, client):
        """A live fetch is parsed after unwrapping {"data": ...}, but it is
        cached wrapped, so a cache hit used to arrive in a different shape
        from the one the parser saw on the first import."""
        unwrapped = client._parse_recipe(blue_chun())
        wrapped = client._parse_recipe({"data": blue_chun()})
        assert wrapped.name == unwrapped.name
        assert len(wrapped.ingredients) == len(unwrapped.ingredients)
        assert wrapped.target_cone == unwrapped.target_cone

    @respx.mock
    def test_second_import_matches_the_first(self, client):
        """The real-world failure: import once (live), import again (cache)."""
        respx.get(f"{GLAZY_API_BASE}/recipes/137").mock(
            return_value=httpx.Response(200, json={"data": blue_chun()})
        )
        first = client.get_recipe(137)
        second = client.get_recipe(137)   # served from cache, no route needed
        assert len(first.ingredients) == len(second.ingredients) == 5
        assert len(second.colorants) == 1


class TestAtmosphereMapping:
    def _with(self, names):
        data = blue_chun()
        data["atmospheres"] = [{"name": n} for n in names]
        return data

    def test_wood(self, client):
        assert AtmosphereType.WOOD in client._parse_recipe(self._with(["Wood"])).suitable_atmospheres

    def test_salt_and_soda_is_both(self, client):
        atms = client._parse_recipe(self._with(["Salt & Soda"])).suitable_atmospheres
        assert AtmosphereType.SALT in atms and AtmosphereType.SODA in atms

    def test_multiple_are_all_kept(self, client):
        atms = client._parse_recipe(self._with(["Oxidation", "Reduction"])).suitable_atmospheres
        assert AtmosphereType.OXIDATION in atms and AtmosphereType.REDUCTION in atms

    def test_unmappable_ones_are_not_forced_onto_something_else(self, client):
        """Raku has no equivalent here; it should not become reduction."""
        atms = client._parse_recipe(self._with(["Raku", "Oxidation"])).suitable_atmospheres
        assert atms == [AtmosphereType.OXIDATION]


class TestSurfaceMapping:
    @pytest.mark.parametrize("glazy,ours", [
        ("Glossy", GlazeSurface.GLOSSY),
        ("Semi-glossy", GlazeSurface.GLOSSY),
        ("Satin", GlazeSurface.SATIN),
        ("Satin-matte", GlazeSurface.SATIN),   # a satin, not a matte
        ("Semi-matte", GlazeSurface.SATIN),
        ("Matte", GlazeSurface.MATTE),
        ("Dry Matte", GlazeSurface.DRY_MATTE),
        ("Stony Matte", GlazeSurface.DRY_MATTE),
    ])
    def test_maps(self, client, glazy, ours):
        data = blue_chun()
        data["surfaceTypeName"] = glazy
        assert client._parse_recipe(data).expected_surface == ours


class TestConeMapping:
    def _cone(self, client, to=None, frm=None):
        data = blue_chun()
        data["toOrtonConeName"], data["fromOrtonConeName"] = to, frm
        return client._parse_recipe(data).target_cone

    def test_exact_cone(self, client):
        assert self._cone(client, to="6") == ConeTemperature.CONE_6

    def test_low_fire_is_not_mistaken_for_mid_fire(self, client):
        """06 is far cooler than 6 - the leading-zero series runs the other way."""
        assert self._cone(client, to="06") == ConeTemperature.CONE_06

    def test_cone_without_an_enum_value_snaps_to_nearest(self, client):
        """Glazy lists cones like 4 and 05 that this app has no value for.
        They should land nearby, not silently become cone 6."""
        assert self._cone(client, to="4") in (ConeTemperature.CONE_3, ConeTemperature.CONE_5)
        assert self._cone(client, to="05") in (ConeTemperature.CONE_06, ConeTemperature.CONE_04)

    def test_falls_back_to_the_bottom_of_the_range(self, client):
        assert self._cone(client, to=None, frm="9") == ConeTemperature.CONE_9


class TestOldSchemaStillParses:
    def test_legacy_fields_are_a_fallback(self, client):
        """Anything cached in the old shape keeps working."""
        recipe = client._parse_recipe({
            "id": 1, "name": "Legacy", "cone": "10", "atmosphere": "reduction",
            "surface_type": "matte",
            "components": [{"material": {"name": "Custer Feldspar"}, "amount": 100}],
        })
        assert recipe.target_cone == ConeTemperature.CONE_10
        assert recipe.suitable_atmospheres == [AtmosphereType.REDUCTION]
        assert recipe.ingredients[0].material_name == "Custer Feldspar"


class TestLink:
    def test_builds_the_public_recipe_page(self):
        assert glazy_recipe_url(137) == "https://glazy.org/recipes/137"

    def test_no_id_no_link(self):
        assert glazy_recipe_url(None) is None


class TestEndpoint:
    @pytest.fixture
    def api(self, client, monkeypatch):
        import api.main as main
        monkeypatch.setattr(main, "glazy_client", client)
        from fastapi.testclient import TestClient
        return TestClient(main.app)

    @respx.mock
    def test_import_returns_ingredients_colorants_and_link(self, api):
        respx.get(f"{GLAZY_API_BASE}/recipes/137").mock(
            return_value=httpx.Response(200, json={"data": blue_chun()})
        )
        body = api.get("/api/glazy/recipe/137").json()
        assert len(body["ingredients"]) == 5
        assert body["colorants"] == [{"material": "Red Iron Oxide", "percentage": 1.1}]
        assert body["glazy_url"] == "https://glazy.org/recipes/137"
        assert body["cone"] == "10"

    @respx.mock
    def test_empty_recipe_is_an_error_not_a_silent_success(self, api):
        """Returning 200 with no ingredients is what let the UI report a
        successful import of nothing."""
        empty = blue_chun()
        empty["materialComponents"] = []
        respx.get(f"{GLAZY_API_BASE}/recipes/138").mock(
            return_value=httpx.Response(200, json={"data": empty})
        )
        response = api.get("/api/glazy/recipe/138")
        assert response.status_code == 422
        assert "glazy.org/recipes/138" in response.json()["detail"]


class TestUI:
    @pytest.fixture(scope="class")
    def html(self):
        from pathlib import Path
        return (Path(__file__).parent.parent / "ui" / "index.html").read_text(encoding="utf-8")

    def test_glazy_import_checks_the_response(self, html):
        body = html.split("async function importGlazyRecipe")[1].split("\n        }\n")[0]
        assert "response.ok" in body
        assert "ingredients.length" in body, "an empty list must not count as success"

    def test_glazy_import_brings_colorants_and_link(self, html):
        body = html.split("async function importGlazyRecipe")[1].split("\n        }\n")[0]
        assert "recipeColorants" in body
        assert "setRecipeSourceLink" in body

    def test_link_is_cleared_when_another_recipe_loads(self, html):
        """Otherwise a stale Glazy link sits next to an unrelated recipe."""
        assert html.count("setRecipeSourceLink(null)") >= 4
