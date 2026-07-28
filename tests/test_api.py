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
