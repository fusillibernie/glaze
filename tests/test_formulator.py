"""Tests for glaze formulator."""

import pytest
from pathlib import Path

from src.models.glaze import (
    GlazeRecipe,
    GlazeIngredient,
    ConeTemperature,
    GlazeSurface,
    GlazeType,
)
from src.services.materials_db import MaterialsDatabase
from src.services.formulator import GlazeFormulator, FormulationTarget


@pytest.fixture
def materials_db():
    """Create a materials database with test data."""
    db = MaterialsDatabase()
    # Database should auto-load from data/materials if available
    return db


@pytest.fixture
def formulator(materials_db):
    """Create a formulator instance."""
    return GlazeFormulator(materials_db)


class TestRecipeAnalysis:
    """Tests for recipe analysis."""

    def test_calculate_recipe_analysis(self, formulator):
        """Test oxide analysis calculation."""
        recipe = GlazeRecipe(
            name="Test Recipe",
            ingredients=[
                GlazeIngredient(material_name="Custer Feldspar", percentage=40.0),
                GlazeIngredient(material_name="Silica (Flint)", percentage=30.0),
                GlazeIngredient(material_name="Whiting (Calcium Carbonate)", percentage=20.0),
                GlazeIngredient(material_name="EPK Kaolin", percentage=10.0),
            ],
            target_cone=ConeTemperature.CONE_10,
        )

        analysis = formulator.calculate_recipe_analysis(recipe)

        # Should have silica from multiple sources
        assert analysis.SiO2 > 0
        # Should have alumina from feldspar and kaolin
        assert analysis.Al2O3 > 0
        # Should have calcium from whiting
        assert analysis.CaO > 0

    def test_calculate_umf(self, formulator):
        """Test UMF calculation."""
        recipe = GlazeRecipe(
            name="Test Recipe",
            ingredients=[
                GlazeIngredient(material_name="Custer Feldspar", percentage=50.0),
                GlazeIngredient(material_name="Silica (Flint)", percentage=25.0),
                GlazeIngredient(material_name="EPK Kaolin", percentage=15.0),
                GlazeIngredient(material_name="Whiting (Calcium Carbonate)", percentage=10.0),
            ],
            target_cone=ConeTemperature.CONE_6,
        )

        umf = formulator.calculate_umf(recipe)

        # Flux total should be normalized to ~1.0
        assert umf.flux_total > 0
        # Should have reasonable Si:Al ratio
        assert 5 < umf.silica_alumina_ratio < 20


class TestFormulation:
    """Tests for glaze formulation."""

    def test_formulate_base_glaze(self, formulator):
        """Test base glaze formulation."""
        target = FormulationTarget(
            cone=ConeTemperature.CONE_6,
            surface=GlazeSurface.GLOSSY,
            sio2_target=3.5,
            al2o3_target=0.4,
        )

        result = formulator.formulate_base_glaze(target)

        # Should produce a recipe
        assert result.recipe is not None
        assert len(result.recipe.ingredients) > 0

        # Ingredients should sum to ~100%
        total = sum(i.percentage for i in result.recipe.ingredients)
        assert 99 < total < 101

        # Should have achieved UMF
        assert result.achieved_umf is not None

    def test_formulate_matte_glaze(self, formulator):
        """Test matte glaze formulation."""
        target = FormulationTarget(
            cone=ConeTemperature.CONE_10,
            surface=GlazeSurface.MATTE,
            sio2_target=3.0,
            al2o3_target=0.5,
        )

        result = formulator.formulate_base_glaze(target)

        # Should produce a recipe
        assert result.recipe is not None
        assert result.recipe.expected_surface == GlazeSurface.MATTE


class TestRecipeAdjustment:
    """Tests for recipe adjustment."""

    def test_add_colorant(self, formulator):
        """Test adding colorant to recipe."""
        base_recipe = GlazeRecipe(
            name="Test Base",
            ingredients=[
                GlazeIngredient(material_name="Custer Feldspar", percentage=50.0),
                GlazeIngredient(material_name="Silica (Flint)", percentage=30.0),
                GlazeIngredient(material_name="EPK Kaolin", percentage=20.0),
            ],
            target_cone=ConeTemperature.CONE_6,
        )

        new_recipe = formulator.add_colorant(
            base_recipe,
            colorant_name="Cobalt Carbonate",
            percentage=0.5,
            expected_color="blue",
        )

        # Should have colorant added
        assert len(new_recipe.colorants) == 1
        assert new_recipe.colorants[0].material_name == "Cobalt Carbonate"
        assert new_recipe.colorants[0].percentage == 0.5

        # Name should indicate colorant
        assert "Cobalt" in new_recipe.name
