"""Calibrated glaze-surface prediction.

Single source of truth for "what surface will this chemistry give?".
Before this module the answer was hardcoded in seven places with
conflicting values - a glaze at Si:Al 11.5 was "satin" from
StullPoint.surface_prediction and GLOSSY from GlazeClassifier, and the
Stull chart drew a third geometry again.

The model is data/reference/surface_model.json, fitted by
scripts/calibrate_surface_model.py from 7,575 Glazy community recipes
that carry both an oxide analysis and a human surface label.

Read the accuracy honestly before relying on this:

    majority baseline ("always glossy")  62.8%
    old StullPoint thresholds            52.2%   <- worse than the baseline
    this model, ratio only               65.3%
    this model, full                     66.4%

Chemistry alone does not determine surface. Firing schedule, application
thickness and clay body matter enormously and are not in the data. That
is why the output is a probability distribution with an explicit
confidence rather than a bare label - the caller should be able to tell
the difference between "84% glossy across 1,401 similar recipes" and a
coin toss, and the old code could not express that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

_MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "reference" / "surface_model.json"

CLASSES = ("glossy", "satin", "matte")

#: Difference between the top two probabilities below which a prediction
#: is not meaningfully better than its runner-up.
_CONFIDENT_MARGIN = 0.25


@dataclass(frozen=True)
class SurfacePrediction:
    """A calibrated surface prediction.

    Attributes:
        label: Most likely class - "glossy", "satin" or "matte".
        probabilities: Full distribution over the three classes, sums to 1.
        confidence: Probability of `label`. Not a fixed constant.
        is_confident: Whether `label` clearly beats the runner-up.
        basis: Which backoff tier answered - "cell:...", "ratio:..." or
            "prior". Lets the UI say what the number is based on.
        n_observations: How many community recipes back this cell.
        stability: Melt-stability flags ("runny", "underfired", "stiff").
            A separate axis from gloss - a glaze can be glossy AND runny.
        caveat: Human-readable note when the prediction is weak.
    """

    label: str
    probabilities: dict[str, float]
    confidence: float
    is_confident: bool
    basis: str
    n_observations: int
    stability: list[str] = field(default_factory=list)
    caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "probabilities": self.probabilities,
            "confidence": round(self.confidence, 4),
            "is_confident": self.is_confident,
            "basis": self.basis,
            "n_observations": self.n_observations,
            "stability": list(self.stability),
            "caveat": self.caveat,
        }


@lru_cache(maxsize=1)
def _model() -> dict:
    with open(_MODEL_PATH, encoding="utf-8") as f:
        return json.load(f)


def _si_al_bin(ratio: float) -> str:
    bins = _model()["features"]["si_al_bins"]
    if ratio < bins[0]:
        return f"<{bins[0]:g}"
    for lo, hi in zip(bins, bins[1:]):
        if ratio < hi:
            return f"{lo:g}-{hi:g}"
    return f">={bins[-1]:g}"


def _cell_key(ratio: float, mgo: float, cao: float) -> str:
    feats = _model()["features"]
    return "|".join((
        _si_al_bin(ratio),
        "mgo_hi" if mgo >= feats["mgo_threshold"] else "mgo_lo",
        "cao_hi" if cao >= feats["cao_threshold"] else "cao_lo",
    ))


def _stability(si_al: float, al2o3: float) -> list[str]:
    flags = _model()["stability_flags"]
    out = []
    if al2o3 < flags["al2o3_underfired_max"]:
        out.append("underfired")
    if al2o3 > flags["al2o3_stiff_min"]:
        out.append("stiff")
    if si_al > flags["si_al_runny_min"]:
        out.append("runny")
    return out


def _build(dist: dict, basis: str, si_al: float, al2o3: float) -> SurfacePrediction:
    probabilities = {c: dist[c] for c in CLASSES}
    ordered = sorted(probabilities.values(), reverse=True)
    label = max(CLASSES, key=lambda c: probabilities[c])
    confidence = probabilities[label]
    is_confident = (ordered[0] - ordered[1]) >= _CONFIDENT_MARGIN

    caveat = ""
    if not is_confident:
        runner_up = sorted(CLASSES, key=lambda c: -probabilities[c])[1]
        caveat = (
            f"Weak call - {label} and {runner_up} are close for this "
            f"chemistry. Surface also depends on firing schedule and "
            f"application thickness, which are not modelled."
        )
    elif basis == "prior":
        caveat = "Not enough similar recipes; falling back to the overall distribution."

    return SurfacePrediction(
        label=label,
        probabilities=probabilities,
        confidence=confidence,
        is_confident=is_confident,
        basis=basis,
        n_observations=dist["n"],
        stability=_stability(si_al, al2o3),
        caveat=caveat,
    )


def predict_surface_from_ratio(si_al: float, al2o3: float) -> SurfacePrediction:
    """Predict from a Stull chart point alone.

    Only Si:Al and Al2O3 are known here, so this uses the ratio-only tier
    - it cannot reach the full model's accuracy (65.3% vs 66.4%). Callers
    holding a full UMF should use predict_surface() instead. Passing
    MgO=0 to the full model would assert low magnesia rather than admit
    it is unknown, which is why this path is separate.
    """
    model = _model()
    if al2o3 <= 0 or si_al <= 0:
        return _build(model["prior"], "prior", si_al, al2o3)

    band = model["ratio_only"].get(_si_al_bin(si_al))
    if band and band["n"] >= model["min_cell_n"]:
        return _build(band, f"ratio:{_si_al_bin(si_al)}", si_al, al2o3)
    return _build(model["prior"], "prior", si_al, al2o3)


def predict_surface(umf) -> SurfacePrediction:
    """Predict from a full UMF, using the magnesia/calcia matte cells.

    Backs off cell -> ratio-only -> prior, so a glaze in a sparsely
    populated corner still gets an answer, with `basis` recording which
    tier actually answered.
    """
    model = _model()
    al2o3 = getattr(umf, "Al2O3", 0.0) or 0.0
    if al2o3 <= 0:
        return _build(model["prior"], "prior", 0.0, al2o3)

    si_al = getattr(umf, "silica_alumina_ratio", 0.0) or 0.0
    mgo = getattr(umf, "MgO", 0.0) or 0.0
    cao = getattr(umf, "CaO", 0.0) or 0.0

    key = _cell_key(si_al, mgo, cao)
    cell = model["cells"].get(key)
    if cell:
        return _build(cell, f"cell:{key}", si_al, al2o3)
    return predict_surface_from_ratio(si_al, al2o3)


def region_bands() -> list[dict]:
    """Si:Al bands with their measured probabilities, for the chart.

    Lets the Stull chart label a band "Si:Al 9-11 - 79% glossy (n=1,633)"
    instead of asserting a hard boundary the data does not support.
    """
    model = _model()
    bands = []
    for key, dist in model["ratio_only"].items():
        label = max(CLASSES, key=lambda c: dist[c])
        bands.append({
            "si_al_range": key,
            "dominant": label,
            "probability": dist[label],
            "probabilities": {c: dist[c] for c in CLASSES},
            "n": dist["n"],
        })
    order = {"<5": 0, "5-7": 1, "7-9": 2, "9-11": 3, ">=11": 4}
    bands.sort(key=lambda b: order.get(b["si_al_range"], 99))
    return bands


def model_accuracy() -> dict:
    """Measured accuracy, so callers can show it rather than imply certainty."""
    return dict(_model()["accuracy"])


def model_features() -> dict:
    """Fitted feature definitions (bin edges, MgO/CaO cuts)."""
    return dict(_model()["features"])


def normalize_surface(raw: Optional[str]) -> Optional[str]:
    """Map a freeform surface label onto glossy/satin/matte.

    Returns None when the value carries no surface information. The raw
    value should be kept alongside - "satin_carbon_trap" and
    "glossy_to_satin" say more than a three-class label can.
    """
    if not raw:
        return None
    text = str(raw).strip().lower().replace("_", " ")
    if not text:
        return None
    # Order matters: "satin matte" and "semi-matte" are satin, not matte.
    if "satin" in text or "semi-matte" in text or "semi matte" in text:
        return "satin"
    if "matte" in text or "matt" in text:
        return "matte"
    if "gloss" in text or "shiny" in text or "transparent" in text:
        return "glossy"
    return None
