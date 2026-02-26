"""Tests for the material substitution service."""

import pytest
from pathlib import Path
from src.services.substitution_service import (
    SubstitutionService,
    AvailabilityStatus,
    SubstituteType,
)


class TestSubstitutionService:
    """Test the SubstitutionService class."""

    @pytest.fixture
    def service(self):
        """Create a substitution service instance."""
        service = SubstitutionService()
        service.load()
        return service

    def test_load_data(self, service):
        """Test that data loads successfully."""
        assert service._loaded is True
        assert len(service._substitutions) > 0

    def test_get_status_available(self, service):
        """Test getting status of an available material."""
        status = service.get_status("EPK Kaolin")
        assert status == AvailabilityStatus.AVAILABLE

    def test_get_status_discontinued(self, service):
        """Test getting status of a discontinued material."""
        status = service.get_status("Albany Slip")
        assert status == AvailabilityStatus.DISCONTINUED

    def test_get_status_limited(self, service):
        """Test getting status of a limited material."""
        status = service.get_status("Gerstley Borate")
        assert status == AvailabilityStatus.LIMITED

    def test_get_status_restricted(self, service):
        """Test getting status of a restricted material."""
        status = service.get_status("Barium Carbonate")
        assert status == AvailabilityStatus.RESTRICTED

    def test_get_status_unknown(self, service):
        """Test getting status of an unknown material."""
        status = service.get_status("Unknown Material")
        assert status is None

    def test_alternate_names(self, service):
        """Test that alternate names work."""
        status1 = service.get_status("Gerstley Borate")
        status2 = service.get_status("GB")
        assert status1 == status2 == AvailabilityStatus.LIMITED

    def test_get_substitutes(self, service):
        """Test getting substitutes for a material."""
        subs = service.get_substitutes("Gerstley Borate")
        assert len(subs) > 0
        assert subs[0].name == "Gillespie Borate"
        assert subs[0].sub_type == SubstituteType.DIRECT

    def test_calculate_direct_substitution(self, service):
        """Test calculating a direct substitution."""
        result = service.calculate_substitution("Gerstley Borate", 20.0)
        assert result is not None
        assert result.original_material == "Gerstley Borate"
        assert result.original_amount == 20.0
        assert result.substitute_name == "Gillespie Borate"
        assert len(result.components) == 1
        assert result.components[0] == ("Gillespie Borate", 20.0)

    def test_calculate_blend_substitution(self, service):
        """Test calculating a blend substitution."""
        # Get the blend substitute (Frit 3134 + EPK Mix)
        result = service.calculate_substitution("Gerstley Borate", 100.0, substitute_index=2)
        assert result is not None
        assert result.substitute_type == SubstituteType.BLEND
        assert len(result.components) == 2
        # Should be 90 parts Frit 3134 and 10 parts EPK at 0.95 ratio
        # So 100 * 0.95 * 90/100 = 85.5 and 100 * 0.95 * 10/100 = 9.5
        frit_amount = next(amt for name, amt in result.components if "Frit" in name)
        epk_amount = next(amt for name, amt in result.components if "EPK" in name)
        assert frit_amount == pytest.approx(85.5, rel=0.01)
        assert epk_amount == pytest.approx(9.5, rel=0.01)

    def test_calculate_substitution_with_ratio(self, service):
        """Test calculating a substitution with a ratio."""
        result = service.calculate_substitution("Colemanite", 100.0)
        assert result is not None
        assert result.substitute_name == "Frit 3134"
        # Ratio is 0.75, so 100 * 0.75 = 75
        assert result.components[0][1] == 75.0

    def test_check_recipe_availability(self, service):
        """Test checking availability of materials in a recipe."""
        recipe = {
            "Gerstley Borate": 20.0,
            "EPK Kaolin": 10.0,
            "Albany Slip": 15.0,
            "Silica (Flint)": 30.0,
        }
        issues = service.check_recipe_availability(recipe)
        assert "Gerstley Borate" in issues
        assert "Albany Slip" in issues
        assert "EPK Kaolin" not in issues  # Available
        # Silica not in database, so not in issues

    def test_substitute_recipe(self, service):
        """Test substituting materials in a recipe."""
        recipe = {
            "Gerstley Borate": 20.0,
            "EPK Kaolin": 10.0,
            "Silica (Flint)": 30.0,
        }
        new_recipe, results = service.substitute_recipe(recipe)

        # Gerstley Borate should be replaced
        assert "Gerstley Borate" not in new_recipe
        assert "Gillespie Borate" in new_recipe
        assert new_recipe["Gillespie Borate"] == 20.0

        # EPK Kaolin is available, should remain
        assert "EPK Kaolin" in new_recipe
        assert new_recipe["EPK Kaolin"] == 10.0

        # Silica not in database, should remain
        assert "Silica (Flint)" in new_recipe

        # Should have one substitution result
        assert len(results) == 1
        assert results[0].original_material == "Gerstley Borate"

    def test_substitute_specific_materials(self, service):
        """Test substituting specific materials in a recipe."""
        recipe = {
            "Gerstley Borate": 20.0,
            "Colemanite": 10.0,
            "EPK Kaolin": 10.0,
        }
        # Only substitute Colemanite
        new_recipe, results = service.substitute_recipe(recipe, ["Colemanite"])

        # Gerstley Borate should NOT be replaced
        assert "Gerstley Borate" in new_recipe
        assert new_recipe["Gerstley Borate"] == 20.0

        # Colemanite should be replaced
        assert "Colemanite" not in new_recipe
        assert "Frit 3134" in new_recipe
        assert new_recipe["Frit 3134"] == 7.5  # 10 * 0.75 ratio

        assert len(results) == 1
        assert results[0].original_material == "Colemanite"

    def test_get_all_unavailable(self, service):
        """Test getting all unavailable materials."""
        unavailable = service.get_all_unavailable()
        assert len(unavailable) > 0

        # Check that we have materials with different statuses
        statuses = {status for _, status, _ in unavailable}
        assert AvailabilityStatus.DISCONTINUED in statuses
        assert AvailabilityStatus.LIMITED in statuses

        # Albany Slip should be in the list
        names = {name for name, _, _ in unavailable}
        assert "Albany Slip" in names

    def test_warnings_for_restricted_materials(self, service):
        """Test that warnings are generated for restricted materials."""
        result = service.calculate_substitution("Barium Carbonate", 5.0)
        assert result is not None
        assert len(result.warnings) > 0
        assert "restrictions" in result.warnings[0].lower()

    def test_null_ratio_warning(self, service):
        """Test warning for substitutes with no fixed ratio."""
        result = service.calculate_substitution("Lead Oxide", 10.0)
        assert result is not None
        assert len(result.warnings) > 0

    def test_adjustments_included(self, service):
        """Test that oxide adjustments are included in results."""
        result = service.calculate_substitution("Colemanite", 100.0)
        assert result is not None
        assert len(result.adjustments) > 0
        # Should have CaO adjustment
        oxide_adjustments = [adj.oxide for adj in result.adjustments]
        assert "CaO" in oxide_adjustments


class TestSubstitutionServiceEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_data_file(self):
        """Test handling of missing data file."""
        service = SubstitutionService(Path("nonexistent.json"))
        service.load()
        assert service._loaded is True
        assert len(service._substitutions) == 0

    def test_case_insensitive_lookup(self):
        """Test that material name lookup is case insensitive."""
        service = SubstitutionService()
        service.load()
        status1 = service.get_status("Gerstley Borate")
        status2 = service.get_status("gerstley borate")
        status3 = service.get_status("GERSTLEY BORATE")
        assert status1 == status2 == status3

    def test_calculate_substitution_invalid_index(self):
        """Test calculating substitution with invalid index."""
        service = SubstitutionService()
        service.load()
        result = service.calculate_substitution("Gerstley Borate", 20.0, substitute_index=999)
        assert result is None

    def test_substitute_recipe_with_accumulation(self):
        """Test that substitute amounts accumulate if already in recipe."""
        service = SubstitutionService()
        service.load()
        recipe = {
            "Gerstley Borate": 20.0,
            "Gillespie Borate": 10.0,  # Already in recipe
        }
        new_recipe, results = service.substitute_recipe(recipe)

        # Gillespie Borate should accumulate
        assert "Gillespie Borate" in new_recipe
        assert new_recipe["Gillespie Borate"] == 30.0  # 10 + 20 from substitution
