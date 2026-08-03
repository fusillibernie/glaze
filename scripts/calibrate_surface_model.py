"""Fit the surface-probability model from labelled Glazy community data.

Writes data/reference/surface_model.json. Run with --check to re-fit and
diff against the shipped file without writing (exits non-zero on
mismatch), which is how the golden test keeps the shipped numbers
honest.

Why a lookup table rather than a fitted classifier: the whole value of
this project is citable provenance. A JSON table can be read, diffed and
handed to a potter; a pickled tree cannot, and costs a runtime
scikit-learn dependency. Measured on a held-out quarter of the data the
table reaches 66.4% against a depth-6 14-feature decision tree's 67.4% -
one percentage point, which is not worth the opacity.

Deliberately NOT a claim that surface is predictable from chemistry. It
mostly is not: the majority-class baseline is 62.8% and the ceiling for
any model over these features is around 67%, because firing schedule,
application thickness and clay body are not in this dataset and matter
enormously. The point of the model is to replace four disagreeing
hardcoded threshold sets (one of which scored 52.2%, worse than guessing
"glossy" every time) with one calibrated distribution that reports its
own uncertainty.

Pure stdlib. Runs in a few seconds.
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.models.materials import OxideAnalysis  # noqa: E402
from src.models.umf import UMF  # noqa: E402

BULK_PATH = REPO / "data" / "glazy_bulk" / "glazy_recipes.json"
OUT_PATH = REPO / "data" / "reference" / "surface_model.json"

# Glazy's freeform surface vocabulary collapsed to three classes.
LABEL_MAP = {
    "glossy": ["Glossy", "Semi-glossy"],
    "satin": ["Satin", "Satin-matte", "Semi-matte"],
    "matte": ["Matte", "Smooth Matte", "Stony Matte", "Dry Matte"],
}
RAW_TO_CLASS = {raw: cls for cls, raws in LABEL_MAP.items() for raw in raws}
CLASSES = ("glossy", "satin", "matte")

# Si:Al bin edges. Chosen to bracket the region boundaries the four legacy
# threshold sets all disagreed about (5/6 for matte, 8/9 for glossy).
SI_AL_BINS = [5.0, 7.0, 9.0, 11.0]

# MgO and CaO cuts. A depth-3 decision tree over 14 features picked these
# two out on its own at 0.31 and 0.22 - they are the classic magnesia and
# calcia mattes. None of the legacy threshold sets referenced either.
MGO_THRESHOLD = 0.31
CAO_THRESHOLD = 0.22

MIN_CELL_N = 40
HOLDOUT = 0.25
SEED = 0

# Melt stability is a SEPARATE axis from gloss. The legacy strings
# "underfired_runny", "glossy_runny" and "matte_dry" conflated the two,
# which is why a runny glaze and a glossy one returned the same label.
# Inherited from the legacy thresholds, not fitted.
STABILITY_FLAGS = {
    "al2o3_underfired_max": 0.15,
    "al2o3_stiff_min": 0.65,
    "si_al_runny_min": 12.0,
}


def si_al_bin(ratio: float) -> str:
    if ratio < SI_AL_BINS[0]:
        return "<5"
    for lo, hi in zip(SI_AL_BINS, SI_AL_BINS[1:]):
        if ratio < hi:
            return f"{lo:g}-{hi:g}"
    return f">={SI_AL_BINS[-1]:g}"


def cell_key(ratio: float, mgo: float, cao: float) -> str:
    return "|".join((
        si_al_bin(ratio),
        "mgo_hi" if mgo >= MGO_THRESHOLD else "mgo_lo",
        "cao_hi" if cao >= CAO_THRESHOLD else "cao_lo",
    ))


def load_samples() -> list[tuple[float, float, float, str]]:
    """(si_al, MgO, CaO, label) for every usable labelled record."""
    records = json.loads(BULK_PATH.read_text(encoding="utf-8"))
    if isinstance(records, dict):
        records = next(v for v in records.values() if isinstance(v, list))

    samples = []
    for r in records:
        analysis, surface = r.get("analysis"), r.get("surface")
        label = RAW_TO_CLASS.get(surface)
        if not analysis or label is None:
            continue
        try:
            umf = UMF.from_oxide_analysis(OxideAnalysis.from_dict(analysis))
        except Exception:
            continue
        if umf.flux_total <= 0 or umf.Al2O3 <= 0:
            continue
        samples.append((umf.silica_alumina_ratio, umf.MgO, umf.CaO, label))
    return samples


def distribution(labels: list[str]) -> dict:
    total = len(labels)
    counts = Counter(labels)
    out = {"n": total}
    out.update({c: round(counts[c] / total, 4) for c in CLASSES})
    return out


def fit(samples) -> tuple[dict, dict, dict]:
    """Return (cells, ratio_only, prior)."""
    by_cell, by_ratio = defaultdict(list), defaultdict(list)
    for ratio, mgo, cao, label in samples:
        by_cell[cell_key(ratio, mgo, cao)].append(label)
        by_ratio[si_al_bin(ratio)].append(label)

    cells = {k: distribution(v) for k, v in sorted(by_cell.items()) if len(v) >= MIN_CELL_N}
    ratio_only = {k: distribution(v) for k, v in sorted(by_ratio.items())}
    prior = distribution([s[3] for s in samples])
    return cells, ratio_only, prior


def predict(cells, ratio_only, prior, ratio, mgo, cao) -> tuple[dict, str]:
    """Backoff: full cell -> ratio-only -> prior."""
    key = cell_key(ratio, mgo, cao)
    if key in cells:
        return cells[key], f"cell:{key}"
    rkey = si_al_bin(ratio)
    if rkey in ratio_only and ratio_only[rkey]["n"] >= MIN_CELL_N:
        return ratio_only[rkey], f"ratio:{rkey}"
    return prior, "prior"


def evaluate(samples) -> dict:
    """Fit on a seeded 75% and score the held-out remainder."""
    idx = list(range(len(samples)))
    random.Random(SEED).shuffle(idx)
    split = int(len(idx) * (1 - HOLDOUT))
    train = [samples[i] for i in idx[:split]]
    test = [samples[i] for i in idx[split:]]

    cells, ratio_only, prior = fit(train)
    _, ratio_only_solo, prior_solo = fit(train)

    full_hits = ratio_hits = 0
    prob_of_true = 0.0
    for ratio, mgo, cao, truth in test:
        dist, _ = predict(cells, ratio_only, prior, ratio, mgo, cao)
        if max(CLASSES, key=lambda c: dist[c]) == truth:
            full_hits += 1
        prob_of_true += dist[truth]
        # ratio-only comparison: what a 2-D chart point alone can reach
        rdist, _ = predict({}, ratio_only_solo, prior_solo, ratio, mgo, cao)
        if max(CLASSES, key=lambda c: rdist[c]) == truth:
            ratio_hits += 1

    majority = Counter(s[3] for s in test).most_common(1)[0][1]
    n = len(test)
    return {
        "holdout_split": HOLDOUT,
        "seed": SEED,
        "n_test": n,
        "majority_baseline": round(majority / n, 4),
        "full_model": round(full_hits / n, 4),
        "ratio_only_model": round(ratio_hits / n, 4),
        "mean_prob_of_true_class": round(prob_of_true / n, 4),
        "ceiling_note": (
            "A 14-feature decision tree over the same data reaches ~0.674 on "
            "this split. Chemistry alone does not determine surface - firing "
            "schedule, application thickness and clay body are not in this "
            "dataset. Treat the distribution, not the argmax, as the output."
        ),
    }


def build() -> dict:
    samples = load_samples()
    cells, ratio_only, prior = fit(samples)
    accuracy = evaluate(samples)
    return {
        "description": (
            "Empirical surface-probability model fitted to Glazy community "
            "recipes carrying both an oxide analysis and a human surface "
            "label. Replaces four disagreeing hardcoded threshold sets. "
            "Predicts a DISTRIBUTION, not a label - chemistry alone tops out "
            "near 67% on this task."
        ),
        "generated_by": "scripts/calibrate_surface_model.py",
        "training_data": {
            "path": "data/glazy_bulk/glazy_recipes.json",
            "n_labeled": len(samples),
            "label_map": LABEL_MAP,
        },
        "accuracy": accuracy,
        "features": {
            "si_al_bins": SI_AL_BINS,
            "mgo_threshold": MGO_THRESHOLD,
            "cao_threshold": CAO_THRESHOLD,
            "threshold_provenance": (
                "MgO 0.31 and CaO 0.22 were selected independently by a "
                "depth-3 decision tree over this data; they correspond to "
                "the classic magnesia and calcia mattes. On aggregate they "
                "add only ~1 point over the ratio alone because those cells "
                "are rare - they matter for per-glaze calibration, not for "
                "the headline number."
            ),
        },
        "min_cell_n": MIN_CELL_N,
        "stability_flags": {
            **STABILITY_FLAGS,
            "note": (
                "Melt stability is a separate axis from gloss. The legacy "
                "labels 'underfired_runny', 'glossy_runny' and 'matte_dry' "
                "conflated the two. Inherited from the legacy thresholds, "
                "not fitted."
            ),
        },
        "prior": prior,
        "ratio_only": ratio_only,
        "cells": cells,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="re-fit and diff against the shipped file; do not write")
    args = ap.parse_args()

    model = build()
    acc = model["accuracy"]
    print(f"labelled samples : {model['training_data']['n_labeled']}")
    print(f"cells kept       : {len(model['cells'])} (min n={MIN_CELL_N})")
    print(f"majority baseline: {acc['majority_baseline']:.1%}")
    print(f"ratio-only model : {acc['ratio_only_model']:.1%}")
    print(f"full model       : {acc['full_model']:.1%}")
    print(f"mean P(true)     : {acc['mean_prob_of_true_class']:.3f}")

    serialized = json.dumps(model, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        if not OUT_PATH.exists():
            print(f"\nFAIL: {OUT_PATH} does not exist", file=sys.stderr)
            return 1
        if OUT_PATH.read_text(encoding="utf-8") != serialized:
            print(f"\nFAIL: {OUT_PATH} is stale - re-run without --check",
                  file=sys.stderr)
            return 1
        print("\nOK: shipped model reproduces exactly")
        return 0

    OUT_PATH.write_text(serialized, encoding="utf-8")
    print(f"\nwrote {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
