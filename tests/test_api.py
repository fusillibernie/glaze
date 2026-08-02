"""Tests for API endpoints."""

import pytest

# `client` fixture lives in conftest.py


class TestMaterialsAPI:
    """Tests for materials endpoints."""

    def test_list_materials(self, client):
        """Test listing materials."""
        response = client.get("/api/materials")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_search_materials(self, client):
        """Test searching materials."""
        response = client.get("/api/materials?search=feldspar")
        assert response.status_code == 200

    def test_get_material_not_found(self, client):
        """Test getting non-existent material."""
        response = client.get("/api/materials/NonExistentMaterial123")
        assert response.status_code == 404

    def test_get_material_returns_boron(self, client):
        """Boron-bearing materials must expose B2O3.

        The detail endpoint used to hand-write a 9-oxide dict that omitted
        B2O3/Li2O/BaO/SrO/P2O5, so every frit and boron material came back
        with its principal oxide missing.
        """
        response = client.get("/api/materials/Colemanite")
        assert response.status_code == 200
        data = response.json()
        assert data["oxide_analysis"]["B2O3"] == pytest.approx(50.8)
        assert data["source"] == "digitalfire"

    def test_get_material_exposes_minor_fluxes(self, client):
        """Li2O must survive the detail response (Spodumene is 7.5% Li2O)."""
        response = client.get("/api/materials/Spodumene")
        assert response.status_code == 200
        assert response.json()["oxide_analysis"]["Li2O"] == pytest.approx(7.5)

    def test_get_material_zero_oxides_omitted(self, client):
        """to_dict() excludes zeros, so absent oxides must not appear as 0.0."""
        data = client.get("/api/materials/Whiting (Calcium Carbonate)").json()
        assert data["oxide_analysis"]["CaO"] == pytest.approx(56.0)
        assert "PbO" not in data["oxide_analysis"]

    def test_discontinued_flag(self, client):
        """Custer Feldspar was discontinued in 2024."""
        assert client.get("/api/materials/Custer Feldspar").json()["discontinued"] is True
        assert client.get("/api/materials/Silica (Flint)").json()["discontinued"] is False


class TestEnumValidation:
    """A typo'd cone/atmosphere/etc used to crash with a raw 500 - bare
    EnumClass(value) raises ValueError, which FastAPI doesn't catch. Every
    endpoint that builds a GlazeRecipe or FiringResult from request strings
    now goes through _enum_from_value, which turns that into a 422. These
    pin the crash-to-clean-error conversion on every site that was fixed.
    """

    def _base_recipe(self, **overrides):
        recipe = {
            "name": "Test Recipe",
            "ingredients": [{"material_name": "Custer Feldspar", "percentage": 100.0}],
            "target_cone": "6",
            "atmospheres": ["oxidation"],
        }
        recipe.update(overrides)
        return recipe

    def test_bad_target_cone_is_422_not_500(self, client):
        response = client.post(
            "/api/recipes/analyze", json=self._base_recipe(target_cone="not-a-cone")
        )
        assert response.status_code == 422
        assert "not-a-cone" in response.json()["detail"]

    def test_bad_atmosphere_is_422_not_500(self, client):
        response = client.post(
            "/api/recipes/calculate-umf", json=self._base_recipe(atmospheres=["bogus"])
        )
        assert response.status_code == 422

    def test_bad_glaze_type_is_422_not_500(self, client):
        response = client.post(
            "/api/recipes/analyze", json=self._base_recipe(glaze_type="not-a-type")
        )
        assert response.status_code == 422

    def test_bad_expected_surface_is_422_not_500(self, client):
        response = client.post(
            "/api/recipes/analyze", json=self._base_recipe(expected_surface="not-a-surface")
        )
        assert response.status_code == 422

    def test_valid_recipe_still_works(self, client):
        """The fix must not have broken the happy path."""
        response = client.post("/api/recipes/analyze", json=self._base_recipe())
        assert response.status_code == 200

    def test_submit_result_bad_cone_is_422_not_500(self, client):
        response = client.post("/api/results", json={
            "recipe_name": "t", "firing_cone": "not-a-cone",
            "firing_atmosphere": "oxidation", "firing_type": "electric",
            "clay_body": "stoneware", "surface_quality": "good",
            "color_description": "x", "defects": [],
        })
        assert response.status_code == 422

    def test_submit_result_bad_defect_is_422_not_500(self, client):
        response = client.post("/api/results", json={
            "recipe_name": "t", "firing_cone": "6",
            "firing_atmosphere": "oxidation", "firing_type": "electric",
            "clay_body": "stoneware", "surface_quality": "good",
            "color_description": "x", "defects": ["not-a-real-defect"],
        })
        assert response.status_code == 422

    def test_predict_bad_clay_body_is_422_not_500(self, client):
        response = client.post("/api/recipes/predict", json={
            "recipe": self._base_recipe(),
            "firing": {"cone": "6", "atmosphere": "oxidation", "firing_type": "electric"},
            "clay_body": "not-a-real-body",
        })
        assert response.status_code == 422

    def test_formulate_bad_cone_is_422_not_500(self, client):
        response = client.post("/api/recipes/formulate", json={
            "cone": "not-a-cone", "surface": "glossy", "atmosphere": "oxidation",
        })
        assert response.status_code == 422


class TestRecipeAPI:
    """Tests for recipe endpoints."""

    def test_calculate_umf(self, client):
        """Test UMF calculation endpoint."""
        recipe_data = {
            "name": "Test Recipe",
            "ingredients": [
                {"material_name": "Custer Feldspar", "percentage": 50.0},
                {"material_name": "Silica (Flint)", "percentage": 30.0},
                {"material_name": "EPK Kaolin", "percentage": 20.0},
            ],
            "target_cone": "6",
        }

        response = client.post("/api/recipes/calculate-umf", json=recipe_data)

        # May fail if materials not in database, but should not error
        assert response.status_code in [200, 422]

    def test_analyze_recipe(self, client):
        """Test recipe analysis endpoint."""
        recipe_data = {
            "name": "Test Recipe",
            "ingredients": [
                {"material_name": "Custer Feldspar", "percentage": 50.0},
                {"material_name": "Silica (Flint)", "percentage": 30.0},
                {"material_name": "EPK Kaolin", "percentage": 20.0},
            ],
            "target_cone": "6",
            "atmospheres": ["oxidation"],
        }

        response = client.post("/api/recipes/analyze", json=recipe_data)
        assert response.status_code in [200, 422]

    def test_analyze_omits_fit_without_clay_body(self, client):
        """No clay body given -> no thermal_expansion block, rather than a
        guessed one."""
        recipe_data = {
            "name": "Test Recipe",
            "ingredients": [
                {"material_name": "Custer Feldspar", "percentage": 50.0},
                {"material_name": "Silica (Flint)", "percentage": 30.0},
                {"material_name": "EPK Kaolin", "percentage": 20.0},
            ],
            "target_cone": "6",
        }
        data = client.post("/api/recipes/analyze", json=recipe_data).json()
        assert data["thermal_expansion"] is None

    def test_analyze_with_named_clay_body_returns_fit(self, client):
        recipe_data = {
            "name": "Test Recipe",
            "ingredients": [
                {"material_name": "Custer Feldspar", "percentage": 50.0},
                {"material_name": "Silica (Flint)", "percentage": 30.0},
                {"material_name": "EPK Kaolin", "percentage": 20.0},
            ],
            "target_cone": "6",
        }
        response = client.post(
            "/api/recipes/analyze?clay_body_name=Standard+Stoneware", json=recipe_data
        )
        assert response.status_code == 200
        fit = response.json()["thermal_expansion"]
        assert fit is not None
        assert fit["clay_body_coe"] == 6.5
        assert fit["crazing_risk"] in ["low", "medium", "high"]

    def test_analyze_with_clay_body_type_uses_average(self, client):
        recipe_data = {
            "name": "Test Recipe",
            "ingredients": [{"material_name": "Custer Feldspar", "percentage": 100.0}],
            "target_cone": "6",
        }
        response = client.post(
            "/api/recipes/analyze?clay_body_type=porcelain", json=recipe_data
        )
        fit = response.json()["thermal_expansion"]
        assert fit is not None
        assert 4.0 < fit["clay_body_coe"] < 7.0

    def test_analyze_unknown_clay_body_name_falls_back_to_type(self, client):
        recipe_data = {
            "name": "Test Recipe",
            "ingredients": [{"material_name": "Custer Feldspar", "percentage": 100.0}],
            "target_cone": "6",
        }
        response = client.post(
            "/api/recipes/analyze?clay_body_name=Not+A+Real+Body&clay_body_type=stoneware",
            json=recipe_data,
        )
        assert response.json()["thermal_expansion"] is not None

    def test_clay_bodies_detailed_endpoint(self, client):
        response = client.get("/api/reference/clay-bodies-detailed")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 15
        assert all("coe" in b for b in data)

    def test_predict_outcome(self, client):
        """Test outcome prediction endpoint."""
        recipe_data = {
            "name": "Test Recipe",
            "ingredients": [
                {"material_name": "Custer Feldspar", "percentage": 50.0},
                {"material_name": "Silica (Flint)", "percentage": 30.0},
                {"material_name": "EPK Kaolin", "percentage": 20.0},
            ],
            "target_cone": "6",
        }

        firing_data = {
            "cone": "6",
            "atmosphere": "oxidation",
            "firing_type": "electric",
        }

        # The endpoint expects both recipe and firing as body params
        response = client.post(
            "/api/recipes/predict",
            json={"recipe": recipe_data, "firing": firing_data},
            params={"clay_body": "stoneware"},
        )
        # May have validation issues, but endpoint should exist
        assert response.status_code in [200, 422]


class TestSavedRecipesAPI:
    """Tests for the user's saved recipes (backend replacement for what was
    previously localStorage-only in the browser)."""

    def _sample(self, **overrides):
        recipe = {
            "name": "My Test Glaze",
            "cone": "6",
            "ingredients": [{"name": "Custer Feldspar", "percentage": 100}],
            "colorants": [],
            "umf": None,
        }
        recipe.update(overrides)
        return recipe

    def test_list_starts_empty(self, client):
        response = client.get("/api/recipes/saved")
        assert response.status_code == 200
        assert response.json() == []

    def test_save_then_appears_in_list(self, client):
        client.post("/api/recipes/saved", json=self._sample())
        response = client.get("/api/recipes/saved")
        names = [r["name"] for r in response.json()]
        assert "My Test Glaze" in names

    def test_save_returns_assigned_id(self, client):
        response = client.post("/api/recipes/saved", json=self._sample())
        assert response.status_code == 200
        assert response.json()["id"]

    def test_save_without_name_is_422(self, client):
        response = client.post("/api/recipes/saved", json={"ingredients": []})
        assert response.status_code == 422

    def test_resave_same_name_updates_not_duplicates(self, client):
        client.post("/api/recipes/saved", json=self._sample(cone="6"))
        client.post("/api/recipes/saved", json=self._sample(cone="10"))

        recipes = client.get("/api/recipes/saved").json()
        matching = [r for r in recipes if r["name"] == "My Test Glaze"]
        assert len(matching) == 1
        assert matching[0]["cone"] == "10"

    def test_delete_removes_it(self, client):
        saved = client.post("/api/recipes/saved", json=self._sample()).json()
        response = client.delete(f"/api/recipes/saved/{saved['id']}")
        assert response.status_code == 200
        assert client.get("/api/recipes/saved").json() == []

    def test_delete_unknown_id_is_404(self, client):
        response = client.delete("/api/recipes/saved/not-a-real-id")
        assert response.status_code == 404

    def test_deep_fields_round_trip_through_the_api(self, client):
        """Ingredients/colorants/umf must survive a save+list cycle intact,
        not just the top-level name/cone fields."""
        recipe = self._sample(
            ingredients=[{"name": "Custer Feldspar", "percentage": 60},
                         {"name": "Silica (Flint)", "percentage": 40}],
            colorants=[{"name": "Cobalt Carbonate", "percentage": 1.5}],
            umf={"SiO2": 3.5, "Al2O3": 0.4, "surface": "glossy"},
        )
        client.post("/api/recipes/saved", json=recipe)
        fetched = client.get("/api/recipes/saved").json()[0]
        assert fetched["ingredients"] == recipe["ingredients"]
        assert fetched["colorants"] == recipe["colorants"]
        assert fetched["umf"] == recipe["umf"]


class TestReferenceAPI:
    """Tests for reference data endpoints."""

    def test_list_cones(self, client):
        """Test listing cones."""
        response = client.get("/api/reference/cones")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "value" in data[0]

    def test_list_atmospheres(self, client):
        """Test listing atmospheres."""
        response = client.get("/api/reference/atmospheres")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_clay_bodies(self, client):
        """Test listing clay bodies."""
        response = client.get("/api/reference/clay-bodies")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_umf_ranges(self, client):
        """Test getting UMF ranges for a cone."""
        response = client.get("/api/reference/umf-ranges/6")
        assert response.status_code == 200
        data = response.json()
        assert "SiO2" in data
        assert "Al2O3" in data


class TestSearchAPI:
    """Tests for classifier-backed search endpoints.

    These returned an empty index on every fresh boot until something
    happened to POST /api/classify first - classifier._recipe_index was
    never seeded from the 10,899-recipe corpus at startup. Real counts (not
    just 200 OK) are the actual regression guard here.
    """

    def test_by_region_returns_indexed_recipes(self, client):
        response = client.get("/api/search/by-region/glossy")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0
        assert len(data["recipes"]) == data["count"]

    def test_by_category_returns_indexed_recipes(self, client):
        response = client.get("/api/search/by-category/clear_glossy")
        assert response.status_code == 200
        assert response.json()["count"] > 0

    def test_invalid_region_is_400_not_500(self, client):
        response = client.get("/api/search/by-region/not-a-region")
        assert response.status_code == 400


class TestGlazyAPI:
    """Tests for Glazy integration endpoints."""

    def test_search_glazy(self, client):
        """Test Glazy search endpoint exists."""
        response = client.get("/api/glazy/search?query=celadon&cone=10")
        # May fail due to API limits, but endpoint should exist
        assert response.status_code in [200, 500]


class TestResultsAPI:
    """Tests for results endpoints."""

    def test_list_results(self, client):
        """Test listing results."""
        response = client.get("/api/results")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_submit_result(self, client):
        """Test submitting a result."""
        result_data = {
            "recipe_name": "Test Recipe",
            "firing_cone": "6",
            "firing_atmosphere": "oxidation",
            "firing_type": "electric",
            "clay_body": "stoneware",
            "surface_quality": "good",
            "color_description": "Blue with tan breaks",
            "defects": [],
        }

        response = client.post("/api/results", json=result_data)
        assert response.status_code == 200
        data = response.json()
        assert "result_id" in data

    def test_submitted_result_appears_exactly_once(self, client):
        """A single submission must read back as a single entry.

        Storage used to double-write each submission (a per-result file and
        an aggregate array), so GET /api/results returned it twice.
        """
        result_data = {
            "recipe_name": "Duplicate Check Glaze",
            "firing_cone": "6",
            "firing_atmosphere": "oxidation",
            "firing_type": "electric",
            "clay_body": "stoneware",
            "surface_quality": "good",
            "color_description": "Blue",
            "defects": [],
        }
        submitted_id = client.post("/api/results", json=result_data).json()["result_id"]

        results = client.get("/api/results").json()
        matches = [r for r in results if r["result_id"] == submitted_id]
        assert len(matches) == 1
        assert matches[0]["recipe_name"] == "Duplicate Check Glaze"
        assert matches[0]["cone"] == "6"

    def test_results_filter_by_cone(self, client):
        base = {
            "firing_atmosphere": "oxidation", "firing_type": "electric",
            "clay_body": "stoneware", "surface_quality": "good",
            "color_description": "x", "defects": [],
        }
        client.post("/api/results", json={**base, "recipe_name": "A", "firing_cone": "6"})
        client.post("/api/results", json={**base, "recipe_name": "B", "firing_cone": "10"})

        results = client.get("/api/results?cone=6").json()
        assert all(r["cone"] == "6" for r in results)
        assert any(r["recipe_name"] == "A" for r in results)
        assert not any(r["recipe_name"] == "B" for r in results)
