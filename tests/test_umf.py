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
    """Tests for Stull chart predictions.

    These assert on the probability distribution and on trends, not on a
    single hard label. A chart point carries only SiO2 and Al2O3, and
    against 7,575 labelled community recipes those two features reach
    65.3% - so pinning an exact label would be asserting more certainty
    than the data supports. Trends are what the model can actually be
    held to.
    """

    def test_glossy_at_high_silica_ratio(self):
        stull = StullPoint(sio2=4.0, al2o3=0.3)  # Si:Al 13.3
        assert stull.surface_prediction == "glossy"

    def test_silica_starved_glazes_are_far_mattier(self):
        """Less silica per alumina means a stiffer, less glassy melt. The
        effect is large and unambiguous at the bottom of the range."""
        low = StullPoint(sio2=1.6, al2o3=0.4).prediction    # Si:Al 4.0
        mid = StullPoint(sio2=3.2, al2o3=0.4).prediction    # Si:Al 8.0

        assert low.probabilities["matte"] > 4 * mid.probabilities["matte"]
        assert low.label == "matte"
        assert mid.label == "glossy"

    def test_gloss_does_not_increase_monotonically_with_ratio(self):
        """Real signal that every one of the legacy threshold sets missed.

        All four hardcoded copies assumed gloss rises with Si:Al up to a
        single "runny" cutoff. The corpus says otherwise: the 9-11 band is
        79% glossy but Si:Al >=11 falls back to 68%, and matte ticks up
        again (0.092 vs 0.085 at 7-9). Very high silica ratios go stiff
        and underfired rather than glassier.

        Pinned because a future recalibration that quietly restored
        monotonicity would mean the fit had been over-smoothed.
        """
        band_9_11 = StullPoint(sio2=4.0, al2o3=0.4).prediction   # Si:Al 10.0
        band_11_up = StullPoint(sio2=4.0, al2o3=0.3).prediction  # Si:Al 13.3

        assert band_11_up.probabilities["glossy"] < band_9_11.probabilities["glossy"]
        assert band_11_up.probabilities["matte"] > band_9_11.probabilities["matte"]

    def test_moderate_ratio_is_reported_as_a_weak_call(self):
        """Si:Al 5-7 is genuinely ambiguous - 44% glossy, 28% satin, 28%
        matte across 1,765 community recipes. The old thresholds returned
        a flat "matte" here with no hint of that. The model must report
        the uncertainty rather than pick a side confidently.

        This is where the calibration openly disagrees with the textbook
        expectation that high alumina implies matte: restricted to Si:Al
        5-7 with Al2O3 above 0.45, the corpus is 49% glossy and only 23%
        matte (n=643). Adding an Al2O3 override to force matte here would
        be overriding measurement with belief, and it also measures worse
        (64.9% vs 65.3%).
        """
        prediction = StullPoint(sio2=2.5, al2o3=0.5).prediction  # Si:Al 5.0
        assert not prediction.is_confident
        assert prediction.caveat
        assert prediction.probabilities["matte"] > 0.2

    def test_probabilities_form_a_distribution(self):
        prediction = StullPoint(sio2=3.2, al2o3=0.4).prediction
        assert set(prediction.probabilities) == {"glossy", "satin", "matte"}
        assert sum(prediction.probabilities.values()) == pytest.approx(1.0, abs=0.01)
        assert prediction.confidence == prediction.probabilities[prediction.label]

    def test_stability_is_separate_from_gloss(self):
        """A glaze can be glossy AND running off the pot. The old labels
        ("glossy_runny", "matte_dry", "underfired_runny") fused the two
        axes so callers could not distinguish them."""
        runny = StullPoint(sio2=5.0, al2o3=0.3).prediction  # Si:Al 16.7
        assert "runny" in runny.stability
        assert runny.label in ("glossy", "satin", "matte")

        underfired = StullPoint(sio2=1.0, al2o3=0.1).prediction
        assert "underfired" in underfired.stability

    def test_to_dict_exposes_distribution(self):
        data = StullPoint(sio2=4.0, al2o3=0.3).to_dict()
        assert data["surface_prediction"] == "glossy"
        assert "surface_probabilities" in data
        assert "stability" in data


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
