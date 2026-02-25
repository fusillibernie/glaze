"""Tests for glaze classifier."""

import pytest

from src.models.glaze import (
    GlazeRecipe,
    GlazeIngredient,
    Colorant,
    ConeTemperature,
    AtmosphereType,
)
from src.models.umf import UMF
from src.services.classifier import (
    GlazeClassifier,
    StullRegion,
    GlazeCategory,
)


@pytest.fixture
def classifier():
    """Create classifier instance."""
    return GlazeClassifier()


@pytest.fixture
def glossy_recipe():
    """Create a typical glossy recipe."""
    return GlazeRecipe(
        name="Test Glossy",
        ingredients=[
            GlazeIngredient(material_name="Feldspar", percentage=50.0),
            GlazeIngredient(material_name="Silica", percentage=30.0),
            GlazeIngredient(material_name="Kaolin", percentage=20.0),
        ],
        target_cone=ConeTemperature.CONE_6,
        suitable_atmospheres=[AtmosphereType.OXIDATION],
        umf=UMF(
            SiO2=3.8,
            Al2O3=0.35,
            Na2O=0.2,
            K2O=0.2,
            CaO=0.5,
            MgO=0.1,
        ),
    )


@pytest.fixture
def matte_recipe():
    """Create a typical matte recipe."""
    return GlazeRecipe(
        name="Test Matte",
        ingredients=[
            GlazeIngredient(material_name="Feldspar", percentage=40.0),
            GlazeIngredient(material_name="Silica", percentage=20.0),
            GlazeIngredient(material_name="Kaolin", percentage=25.0),
            GlazeIngredient(material_name="Dolomite", percentage=15.0),
        ],
        target_cone=ConeTemperature.CONE_10,
        suitable_atmospheres=[AtmosphereType.REDUCTION],
        umf=UMF(
            SiO2=2.8,
            Al2O3=0.5,
            Na2O=0.1,
            K2O=0.2,
            CaO=0.5,
            MgO=0.2,
        ),
    )


class TestClassification:
    """Tests for glaze classification."""

    def test_classify_glossy(self, classifier, glossy_recipe):
        """Test classification of glossy glaze."""
        classification = classifier.classify(glossy_recipe)

        assert classification.stull.region in [StullRegion.GLOSSY, StullRegion.SATIN]
        assert classification.stull.si_al_ratio > 8

    def test_classify_matte(self, classifier, matte_recipe):
        """Test classification of matte glaze."""
        classification = classifier.classify(matte_recipe)

        assert classification.stull.region in [StullRegion.MATTE, StullRegion.SATIN]
        assert classification.stull.si_al_ratio < 8

    def test_classify_no_umf_raises(self, classifier):
        """Test that classification without UMF raises error."""
        recipe = GlazeRecipe(
            name="No UMF",
            ingredients=[],
            target_cone=ConeTemperature.CONE_6,
        )

        with pytest.raises(ValueError):
            classifier.classify(recipe)

    def test_classify_iron_glaze(self, classifier):
        """Test classification of iron glaze."""
        recipe = GlazeRecipe(
            name="Tenmoku",
            ingredients=[],
            colorants=[
                Colorant(material_name="Red Iron Oxide", percentage=8.0),
            ],
            target_cone=ConeTemperature.CONE_10,
            umf=UMF(SiO2=3.5, Al2O3=0.4, CaO=0.7, K2O=0.3, Fe2O3=0.1),
        )

        classification = classifier.classify(recipe)
        assert classification.is_iron_glaze
        assert "tenmoku" in classification.category.value.lower() or classification.colorant_notes

    def test_flux_analysis(self, classifier):
        """Test flux composition analysis."""
        high_alkali_recipe = GlazeRecipe(
            name="High Alkali",
            ingredients=[],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(
                SiO2=3.5,
                Al2O3=0.4,
                Na2O=0.4,
                K2O=0.2,
                CaO=0.3,
                MgO=0.1,
            ),
        )

        classification = classifier.classify(high_alkali_recipe)
        assert classification.alkali_dominant

    def test_food_safety_lead(self, classifier):
        """Test food safety warning for lead."""
        lead_recipe = GlazeRecipe(
            name="Lead Glaze",
            ingredients=[],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(SiO2=3.0, Al2O3=0.3, PbO=0.5, CaO=0.5),
        )

        classification = classifier.classify(lead_recipe)
        assert not classification.food_safe
        assert any("lead" in w.lower() for w in classification.warnings)


class TestSearch:
    """Tests for glaze search."""

    def test_search_by_region(self, classifier, glossy_recipe, matte_recipe):
        """Test search by Stull region."""
        classifier.classify(glossy_recipe)
        classifier.classify(matte_recipe)

        # Should find at least one in each
        stats = classifier.get_statistics()
        assert stats["total_indexed"] == 2

    def test_search_similar(self, classifier, glossy_recipe):
        """Test similar glaze search."""
        classifier.classify(glossy_recipe)

        # Create a similar recipe
        similar_recipe = GlazeRecipe(
            name="Similar Glossy",
            ingredients=[],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(
                SiO2=3.9,  # Very close
                Al2O3=0.36,
                Na2O=0.2,
                K2O=0.2,
                CaO=0.5,
                MgO=0.1,
            ),
        )

        similar = classifier.search_similar(similar_recipe, max_distance=0.5)
        assert len(similar) > 0

    def test_search_by_umf_range(self, classifier, glossy_recipe, matte_recipe):
        """Test UMF range search."""
        classifier.classify(glossy_recipe)
        classifier.classify(matte_recipe)

        # Search for high silica glazes
        results = classifier.search_by_umf_range(
            sio2_min=3.5,
            sio2_max=5.0,
            al2o3_min=0.2,
            al2o3_max=0.5,
        )

        assert len(results) >= 1

    def test_search_by_flux_profile(self, classifier, glossy_recipe):
        """Test flux profile search."""
        classifier.classify(glossy_recipe)

        results = classifier.search_by_flux_profile(barium_allowed=True)
        assert len(results) >= 1


class TestStullCoordinates:
    """Tests for Stull coordinate calculations."""

    def test_distance_calculation(self, classifier, glossy_recipe, matte_recipe):
        """Test distance between Stull coordinates."""
        class1 = classifier.classify(glossy_recipe)
        class2 = classifier.classify(matte_recipe)

        distance = class1.stull.distance_to(class2.stull)
        assert distance > 0

    def test_is_stable(self, classifier, glossy_recipe):
        """Test stability check."""
        classification = classifier.classify(glossy_recipe)
        assert classification.stull.is_stable
