"""Tests for UMF calculations."""

import pytest
from src.models.umf import UMF, StullPoint, get_umf_ranges
from src.models.materials import OxideAnalysis


class TestUMF:
    """Tests for UMF calculations."""

    def test_flux_total(self):
        """Test flux total calculation."""
        umf = UMF(
            SiO2=3.5,
            Al2O3=0.4,
            Na2O=0.3,
            K2O=0.2,
            CaO=0.4,
            MgO=0.1,
        )
        # Flux total should be sum of all fluxes
        assert umf.flux_total == pytest.approx(1.0, rel=0.01)

    def test_silica_alumina_ratio(self):
        """Test Si:Al ratio calculation."""
        umf = UMF(SiO2=3.5, Al2O3=0.35)
        assert umf.silica_alumina_ratio == pytest.approx(10.0, rel=0.01)

    def test_silica_alumina_ratio_zero_alumina(self):
        """Test Si:Al ratio with zero alumina returns infinity."""
        umf = UMF(SiO2=3.5, Al2O3=0.0)
        assert umf.silica_alumina_ratio == float('inf')

    def test_alkali_ratio(self):
        """Test alkali ratio calculation."""
        umf = UMF(
            Na2O=0.2,
            K2O=0.1,
            Li2O=0.0,
            CaO=0.5,
            MgO=0.2,
        )
        # Alkali = 0.3, Flux total = 1.0
        assert umf.alkali_ratio == pytest.approx(0.3, rel=0.01)

    def test_from_oxide_analysis(self):
        """Test UMF creation from oxide analysis."""
        # Simplified feldspar-like analysis
        analysis = OxideAnalysis(
            SiO2=68.5,
            Al2O3=17.0,
            K2O=10.0,
            Na2O=3.0,
        )
        umf = UMF.from_oxide_analysis(analysis)

        # Should have reasonable values
        assert umf.SiO2 > 0
        assert umf.Al2O3 > 0
        assert umf.K2O > 0
        assert umf.flux_total > 0


class TestStullPoint:
    """Tests for Stull chart predictions."""

    def test_glossy_prediction(self):
        """Test glossy surface prediction."""
        # High silica, low alumina = glossy
        stull = StullPoint(sio2=4.0, al2o3=0.3)
        assert "glossy" in stull.surface_prediction

    def test_matte_prediction(self):
        """Test matte surface prediction."""
        # Low silica, high alumina = matte
        stull = StullPoint(sio2=2.5, al2o3=0.5)
        assert "matte" in stull.surface_prediction

    def test_satin_prediction(self):
        """Test satin surface prediction."""
        # Balanced = satin
        stull = StullPoint(sio2=3.2, al2o3=0.4)
        prediction = stull.surface_prediction
        assert prediction in ["satin", "matte", "glossy"]


class TestUMFRanges:
    """Tests for UMF ranges by cone."""

    def test_cone_6_ranges(self):
        """Test cone 6 UMF ranges."""
        ranges = get_umf_ranges(6)

        assert "SiO2" in ranges
        assert "Al2O3" in ranges
        assert len(ranges["SiO2"]) == 2
        assert ranges["SiO2"][0] < ranges["SiO2"][1]

    def test_cone_10_ranges(self):
        """Test cone 10 UMF ranges."""
        ranges = get_umf_ranges(10)

        assert "SiO2" in ranges
        assert "Al2O3" in ranges
        # Cone 10 typically has higher silica range
        assert ranges["SiO2"][1] >= 4.0

    def test_default_ranges(self):
        """Test default ranges for unknown cone."""
        ranges = get_umf_ranges(99)
        # Should return some default ranges
        assert "SiO2" in ranges
