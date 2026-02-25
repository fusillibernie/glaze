"""Tests for glaze analyzer."""

import pytest

from src.models.glaze import (
    GlazeRecipe,
    GlazeIngredient,
    ConeTemperature,
)
from src.models.umf import UMF
from src.services.analyzer import GlazeAnalyzer


@pytest.fixture
def analyzer():
    """Create analyzer instance."""
    return GlazeAnalyzer()


@pytest.fixture
def test_recipe():
    """Create a test recipe with UMF."""
    recipe = GlazeRecipe(
        name="Test Recipe",
        ingredients=[
            GlazeIngredient(material_name="Custer Feldspar", percentage=40.0),
            GlazeIngredient(material_name="Silica (Flint)", percentage=30.0),
            GlazeIngredient(material_name="Whiting (Calcium Carbonate)", percentage=20.0),
            GlazeIngredient(material_name="EPK Kaolin", percentage=10.0),
        ],
        target_cone=ConeTemperature.CONE_10,
        umf=UMF(
            SiO2=3.8,
            Al2O3=0.38,
            Na2O=0.1,
            K2O=0.2,
            CaO=0.6,
            MgO=0.1,
        ),
    )
    return recipe


class TestChemistryAnalysis:
    """Tests for chemistry analysis."""

    def test_analyze_chemistry(self, analyzer, test_recipe):
        """Test basic chemistry analysis."""
        analysis = analyzer.analyze_chemistry(test_recipe)

        # Should return analysis with UMF
        assert analysis.umf is not None

        # Should have ratios
        assert analysis.silica_alumina_ratio > 0
        assert 0 <= analysis.alkali_ratio <= 1

        # Should have predictions
        assert analysis.predicted_surface is not None
        assert len(analysis.predicted_cone_range) == 2

    def test_analyze_chemistry_issues(self, analyzer):
        """Test that issues are identified."""
        # Create recipe with problematic UMF
        recipe = GlazeRecipe(
            name="Problem Recipe",
            ingredients=[],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(
                SiO2=2.0,  # Low silica
                Al2O3=0.15,  # Low alumina
                Na2O=0.5,  # High alkali
                K2O=0.3,
                CaO=0.2,
            ),
        )

        analysis = analyzer.analyze_chemistry(recipe)

        # Should identify issues
        assert len(analysis.issues) > 0 or len(analysis.warnings) > 0

    def test_analyze_chemistry_no_umf(self, analyzer):
        """Test that error is raised without UMF."""
        recipe = GlazeRecipe(
            name="No UMF",
            ingredients=[],
            target_cone=ConeTemperature.CONE_6,
        )

        with pytest.raises(ValueError):
            analyzer.analyze_chemistry(recipe)


class TestThermalExpansion:
    """Tests for thermal expansion analysis."""

    def test_analyze_thermal_expansion(self, analyzer, test_recipe):
        """Test thermal expansion analysis."""
        analysis = analyzer.analyze_thermal_expansion(test_recipe)

        # Should have COE value
        assert analysis.calculated_coe > 0

        # Should have risk levels
        assert analysis.crazing_risk in ["low", "medium", "high"]
        assert analysis.shivering_risk in ["low", "medium", "high"]

    def test_high_alkali_crazing_risk(self, analyzer):
        """Test that high alkali increases crazing risk."""
        recipe = GlazeRecipe(
            name="High Alkali",
            ingredients=[],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(
                SiO2=3.5,
                Al2O3=0.4,
                Na2O=0.6,  # Very high sodium
                K2O=0.2,
                CaO=0.2,
            ),
        )

        analysis = analyzer.analyze_thermal_expansion(recipe)

        # High alkali should indicate crazing risk
        assert analysis.crazing_risk in ["medium", "high"]


class TestRecipeComparison:
    """Tests for recipe comparison."""

    def test_compare_recipes(self, analyzer):
        """Test comparing two recipes."""
        recipe_a = GlazeRecipe(
            name="Recipe A",
            ingredients=[
                GlazeIngredient(material_name="Feldspar", percentage=50.0),
                GlazeIngredient(material_name="Silica", percentage=30.0),
                GlazeIngredient(material_name="Kaolin", percentage=20.0),
            ],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(SiO2=3.5, Al2O3=0.4, Na2O=0.2, K2O=0.2, CaO=0.6),
        )

        recipe_b = GlazeRecipe(
            name="Recipe B",
            ingredients=[
                GlazeIngredient(material_name="Feldspar", percentage=45.0),
                GlazeIngredient(material_name="Silica", percentage=35.0),
                GlazeIngredient(material_name="Whiting", percentage=20.0),
            ],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(SiO2=4.0, Al2O3=0.35, Na2O=0.15, K2O=0.15, CaO=0.7),
        )

        comparison = analyzer.compare_recipes(recipe_a, recipe_b)

        # Should have UMF differences
        assert "umf_differences" in comparison
        assert "SiO2" in comparison["umf_differences"]

        # Should have ingredient comparison
        assert "ingredient_comparison" in comparison
