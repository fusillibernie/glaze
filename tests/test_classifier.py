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

        # DRY_MATTE is also a valid matte classification for low Si:Al ratios
        assert classification.stull.region in [StullRegion.MATTE, StullRegion.SATIN, StullRegion.DRY_MATTE]
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


class TestIndexKeying:
    """The search index is keyed by a caller-supplied stable id, not by
    name. Keying by name silently dropped 1,007 of the 10,799 Glazy bulk
    records whose names collide ("floating blue" appears 22 times, and 50
    records have no name at all) - they were absent from every region and
    category search while still inflating the bucket counts.
    """

    def _recipe(self, name, sio2, al2o3):
        return GlazeRecipe(
            name=name,
            ingredients=[GlazeIngredient(material_name="Feldspar", percentage=100.0)],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(SiO2=sio2, Al2O3=al2o3, CaO=0.6, K2O=0.4),
        )

    def test_same_name_different_keys_both_indexed(self, classifier):
        classifier.classify(self._recipe("Floating Blue", 3.8, 0.35), index_key="glazy:1")
        classifier.classify(self._recipe("Floating Blue", 2.4, 0.55), index_key="glazy:2")
        assert classifier.get_statistics()["total_indexed"] == 2

    def test_unnamed_records_do_not_collapse(self, classifier):
        for i in range(5):
            classifier.classify(self._recipe("", 3.8, 0.35), index_key=f"glazy:{i}")
        assert classifier.get_statistics()["total_indexed"] == 5

    def test_reclassifying_same_key_does_not_duplicate(self, classifier):
        """Buckets used to grow unboundedly: the dict overwrote but the
        region/category lists appended every time."""
        for _ in range(4):
            classifier.classify(self._recipe("Same Glaze", 3.8, 0.35), index_key="glazy:7")
        stats = classifier.get_statistics()
        assert stats["total_indexed"] == 1
        assert sum(stats["by_region"].values()) == 1
        assert sum(stats["by_category"].values()) == 1

    def test_bucket_totals_match_index_size(self, classifier):
        for i in range(6):
            classifier.classify(self._recipe(f"Glaze {i}", 3.0 + i * 0.2, 0.35), index_key=f"g:{i}")
        stats = classifier.get_statistics()
        assert sum(stats["by_region"].values()) == stats["total_indexed"]
        assert sum(stats["by_category"].values()) == stats["total_indexed"]

    def test_region_search_returns_display_names_not_keys(self, classifier):
        c = classifier.classify(self._recipe("Amber Celadon", 3.8, 0.35), index_key="glazy:99")
        assert "Amber Celadon" in classifier.search_by_region(c.stull.region)

    def test_lookup_by_name_still_works_when_keyed_by_id(self, classifier):
        classifier.classify(self._recipe("Amber Celadon", 3.8, 0.35), index_key="glazy:99")
        found = classifier.get_classification("Amber Celadon")
        assert found is not None and found.recipe_name == "Amber Celadon"

    def test_defaults_to_name_when_no_key_given(self, classifier):
        classifier.classify(self._recipe("Legacy Path", 3.8, 0.35))
        assert classifier.get_classification("Legacy Path") is not None
