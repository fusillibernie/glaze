"""Tests for the calibrated surface model.

The model replaced seven copies of hardcoded Stull thresholds that
disagreed with each other - a glaze at Si:Al 11.5 was "satin" from
StullPoint and GLOSSY from GlazeClassifier, and the chart drew a third
geometry again. The old thresholds scored 52.2% against 7,575 labelled
community recipes, worse than always answering "glossy" (60.5%).

The golden test is the important one: it re-runs the fit and asserts the
shipped JSON reproduces exactly, so the numbers in the data file cannot
drift away from the script that claims to produce them.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.models.umf import UMF
from src.services import surface_model
from tests.conftest import requires_glazy_corpus


REPO = Path(__file__).parent.parent
MODEL_PATH = REPO / "data" / "reference" / "surface_model.json"


@pytest.fixture(scope="module")
def model():
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


class TestModelFile:
    def test_every_cell_is_a_distribution(self, model):
        for key, cell in model["cells"].items():
            total = sum(cell[c] for c in ("glossy", "satin", "matte"))
            assert total == pytest.approx(1.0, abs=0.005), f"{key} sums to {total}"

    def test_every_ratio_band_is_a_distribution(self, model):
        for key, band in model["ratio_only"].items():
            total = sum(band[c] for c in ("glossy", "satin", "matte"))
            assert total == pytest.approx(1.0, abs=0.005), f"{key} sums to {total}"

    def test_cells_respect_min_sample_size(self, model):
        for key, cell in model["cells"].items():
            assert cell["n"] >= model["min_cell_n"], f"{key} kept with only n={cell['n']}"

    def test_ships_its_own_accuracy(self, model):
        """The caveat has to travel with the data - a consumer reading the
        file should not have to go looking for how good it is."""
        acc = model["accuracy"]
        for field in ("majority_baseline", "full_model", "ratio_only_model", "n_test"):
            assert field in acc


class TestAccuracyGuard:
    def test_beats_majority_baseline(self, model):
        """A future data refresh that degrades the model should fail loudly
        rather than quietly ship a model no better than a constant."""
        acc = model["accuracy"]
        assert acc["full_model"] > acc["majority_baseline"] + 0.02

    def test_full_model_beats_ratio_only(self, model):
        acc = model["accuracy"]
        assert acc["full_model"] >= acc["ratio_only_model"]

    def test_beats_the_thresholds_it_replaced(self, model):
        """The old hardcoded StullPoint cuts measured 52.2% on this data."""
        assert model["accuracy"]["full_model"] > 0.60


class TestPrediction:
    def test_returns_normalized_distribution(self):
        prediction = surface_model.predict_surface(UMF(SiO2=3.5, Al2O3=0.4, CaO=0.6, K2O=0.4))
        assert set(prediction.probabilities) == {"glossy", "satin", "matte"}
        assert sum(prediction.probabilities.values()) == pytest.approx(1.0, abs=0.01)

    def test_confidence_is_probability_of_label(self):
        prediction = surface_model.predict_surface(UMF(SiO2=3.5, Al2O3=0.4, CaO=0.6, K2O=0.4))
        assert prediction.confidence == prediction.probabilities[prediction.label]

    def test_confidence_is_not_a_constant(self):
        """It used to be, for every recipe: min(0.5 + n*0.1, 0.95) always
        saturated at 0.95 because every stored firing result is cone 6
        oxidation and the similarity threshold accepted either match."""
        confidences = {
            surface_model.predict_surface(u).confidence
            for u in (
                UMF(SiO2=4.0, Al2O3=0.4, CaO=0.6, K2O=0.4),
                UMF(SiO2=2.0, Al2O3=0.5, CaO=0.7, MgO=0.4),
                UMF(SiO2=3.0, Al2O3=0.4, MgO=0.5, K2O=0.4),
            )
        }
        assert len(confidences) > 1
        assert 0.95 not in confidences

    def test_magnesia_matte_is_detected(self):
        """The classic magnesia matte. Invisible to a Si:Al chart point,
        which is why the ratio-only tier cannot see it and none of the
        seven legacy threshold copies referenced MgO at all."""
        high_mgo = surface_model.predict_surface(
            UMF(SiO2=2.4, Al2O3=0.4, MgO=0.5, CaO=0.1, K2O=0.4))
        low_mgo = surface_model.predict_surface(
            UMF(SiO2=2.4, Al2O3=0.4, MgO=0.0, CaO=0.1, K2O=0.4))
        assert high_mgo.probabilities["glossy"] < low_mgo.probabilities["glossy"]

    def test_stability_is_a_separate_axis(self):
        runny = surface_model.predict_surface(UMF(SiO2=6.0, Al2O3=0.35, CaO=0.6, K2O=0.4))
        assert "runny" in runny.stability
        assert runny.label in ("glossy", "satin", "matte")

    def test_weak_calls_are_flagged(self):
        """A near-tie must not present as a confident answer.

        Si:Al 4.0 with high calcium sits in a cell the corpus splits
        50/36/14 - the top two are 14 points apart. The old thresholds
        returned a flat "matte" here with no indication it was close.
        """
        prediction = surface_model.predict_surface(
            UMF(SiO2=1.6, Al2O3=0.4, CaO=0.6, K2O=0.4))
        assert not prediction.is_confident
        assert prediction.caveat

    def test_clear_calls_are_not_flagged(self):
        """The flag has to discriminate, or it is noise."""
        prediction = surface_model.predict_surface(
            UMF(SiO2=4.0, Al2O3=0.4, CaO=0.6, K2O=0.4))
        assert prediction.is_confident
        assert prediction.caveat == ""


class TestBackoff:
    def test_basis_records_which_tier_answered(self):
        prediction = surface_model.predict_surface(UMF(SiO2=3.5, Al2O3=0.4, CaO=0.6, K2O=0.4))
        assert prediction.basis.startswith(("cell:", "ratio:", "prior"))

    def test_ratio_only_path_does_not_claim_low_magnesia(self):
        """A chart point has no MgO information. Feeding 0 into the full
        model would assert low magnesia rather than admit it is unknown,
        so the 2-D path uses the ratio tier instead."""
        prediction = surface_model.predict_surface_from_ratio(8.0, 0.4)
        assert prediction.basis.startswith(("ratio:", "prior"))

    def test_degenerate_input_falls_back_to_prior(self):
        prediction = surface_model.predict_surface(UMF(SiO2=0.0, Al2O3=0.0))
        assert prediction.basis == "prior"
        assert sum(prediction.probabilities.values()) == pytest.approx(1.0, abs=0.01)


class TestRegionBands:
    def test_bands_are_ordered_and_carry_evidence(self):
        bands = surface_model.region_bands()
        assert [b["si_al_range"] for b in bands] == ["<5", "5-7", "7-9", "9-11", ">=11"]
        for band in bands:
            assert band["n"] > 0
            assert 0 < band["probability"] <= 1

    def test_gloss_is_non_monotonic_at_the_top(self):
        """Real signal the legacy thresholds all assumed away: the 9-11
        band is glossier than >=11. Very high silica ratios go stiff and
        underfired rather than glassier."""
        bands = {b["si_al_range"]: b for b in surface_model.region_bands()}
        assert bands[">=11"]["probabilities"]["glossy"] < bands["9-11"]["probabilities"]["glossy"]


class TestNormalizeSurface:
    @pytest.mark.parametrize("raw,expected", [
        ("Glossy", "glossy"),
        ("Semi-glossy", "glossy"),
        ("shiny", "glossy"),
        ("Satin", "satin"),
        ("Satin-matte", "satin"),
        ("Semi-matte", "satin"),
        ("satin_carbon_trap", "satin"),
        ("Matte", "matte"),
        ("Stony Matte", "matte"),
        ("Dry Matte", "matte"),
        (None, None),
        ("", None),
        ("wood ash flashing", None),
    ])
    def test_maps_freeform_labels(self, raw, expected):
        assert surface_model.normalize_surface(raw) == expected

    def test_satin_matte_is_satin_not_matte(self):
        """Order matters - a substring check that tested 'matte' first
        would misfile every satin-matte in the corpus."""
        assert surface_model.normalize_surface("Satin-matte") == "satin"


class TestReproducibility:
    @requires_glazy_corpus
    def test_shipped_model_reproduces_from_the_script(self):
        """Golden test: re-fit and diff. Without this the accuracy figures
        in the data file are just assertions nobody checks."""
        result = subprocess.run(
            [sys.executable, "scripts/calibrate_surface_model.py", "--check"],
            cwd=REPO, capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"shipped model does not reproduce:\n{result.stdout}\n{result.stderr}"
        )
