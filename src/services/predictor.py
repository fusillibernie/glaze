"""Outcome prediction based on glaze data and firing results."""

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from ..models.glaze import (
    GlazeRecipe,
    FiringSchedule,
    ClayBody,
    AtmosphereType,
    GlazeSurface,
    ConeTemperature,
)
from ..models.results import (
    FiringResult,
    SurfaceQuality,
    GlazeDefect,
    ColorDescription,
)
from ..models.umf import UMF
from . import surface_model


@dataclass
class OutcomePrediction:
    """Predicted outcome for a glaze firing."""
    predicted_surface: GlazeSurface
    confidence: float  # 0-1

    # Color prediction
    predicted_color_family: Optional[str] = None
    color_notes: Optional[str] = None

    # Potential issues
    defect_risks: dict[str, float] = None  # defect -> probability

    # Recommendations
    application_recommendations: list[str] = None
    firing_recommendations: list[str] = None

    # Similar results from database
    similar_results: list[FiringResult] = None

    # Calibrated surface detail. `confidence` above is the probability of
    # `predicted_surface`; these expose the rest of the distribution so a
    # caller can tell a strong call from a coin toss.
    surface_probabilities: dict[str, float] = None
    surface_basis: Optional[str] = None
    surface_caveat: str = ""
    stability_flags: list[str] = None

    # Triggered defect risks with their citations. `defect_risks` above
    # keeps its original shape (defect -> probability) for existing
    # callers; this carries the why and the source alongside.
    defect_findings: list = None

    def __post_init__(self):
        if self.defect_risks is None:
            self.defect_risks = {}
        if self.application_recommendations is None:
            self.application_recommendations = []
        if self.firing_recommendations is None:
            self.firing_recommendations = []
        if self.similar_results is None:
            self.similar_results = []
        if self.surface_probabilities is None:
            self.surface_probabilities = {}
        if self.stability_flags is None:
            self.stability_flags = []
        if self.defect_findings is None:
            self.defect_findings = []


_DEFAULT_RESULTS_PATH = Path(__file__).parent.parent.parent / "data" / "results" / "firing_results.json"
_DEFECT_GUIDE_PATH = Path(__file__).parent.parent.parent / "data" / "reference" / "defect_guide.json"


@dataclass(frozen=True)
class DefectRisk:
    """One triggered defect risk, with the evidence behind it.

    `evidence` distinguishes a threshold quoted from a published source
    from one inherited from the predictor's original hardcoded guesses.
    Both used to be presented identically, so a user had no way to tell
    which numbers to trust.
    """

    defect: str
    risk: float
    message: str
    source: str
    evidence: str
    trigger_id: str
    remedies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "defect": self.defect,
            "risk": round(self.risk, 3),
            "message": self.message,
            "source": self.source,
            "evidence": self.evidence,
            "trigger_id": self.trigger_id,
            "remedies": list(self.remedies),
        }


_OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _load_defect_guide() -> dict:
    try:
        with open(_DEFECT_GUIDE_PATH, encoding="utf-8") as f:
            return json.load(f).get("defects", {})
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load defect guide; defect risks will be empty")
        return {}


class OutcomePredictor:
    """Predict glaze firing outcomes based on historical data."""

    def __init__(
        self,
        results_database: Optional[list[FiringResult]] = None,
        results_path: Optional[Path] = None,
        materials_db=None,
        defect_guide: Optional[dict] = None,
    ):
        """Initialize the predictor.

        Args:
            results_database: Historical firing results for prediction.
            results_path: Path to JSON file for persisting results.
            materials_db: Needed to evaluate raw-batch conditions. Without
                it those conditions are skipped and reported as skipped -
                never silently treated as false.
            defect_guide: Defect definitions; defaults to the shipped
                data/reference/defect_guide.json.
        """
        self.results_path = results_path or _DEFAULT_RESULTS_PATH
        self.results = results_database or self._load_results()
        self.materials_db = materials_db
        self.defect_guide = defect_guide if defect_guide is not None else _load_defect_guide()

    def _load_results(self) -> list[FiringResult]:
        """Load persisted results from disk, deduplicated by result_id.

        A duplicate can only reach the file through a bug (this class used to
        lose fired_at and photos on every reload-then-save cycle, silently
        rewriting history). Keep the first occurrence of each id rather than
        fail to load.
        """
        if not self.results_path.exists():
            return []
        try:
            with open(self.results_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            results = []
            seen_ids = set()
            for item in data:
                try:
                    result = FiringResult.from_dict(item)
                except Exception:
                    continue
                if result.result_id in seen_ids:
                    continue
                seen_ids.add(result.result_id)
                results.append(result)
            return results
        except Exception:
            return []

    def _save_results(self) -> None:
        """Persist results to disk atomically.

        Writes to a temp file in the same directory and replaces the target
        in one step, so a crash or concurrent write mid-save cannot truncate
        or corrupt the existing file.
        """
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = []
        for r in self.results:
            try:
                serializable.append(r.to_dict())
            except Exception:
                pass

        fd, tmp_path = tempfile.mkstemp(
            dir=self.results_path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2, default=str)
            os.replace(tmp_path, self.results_path)
        except BaseException:
            os.unlink(tmp_path)
            raise

    def add_result(self, result: FiringResult) -> None:
        """Add a firing result to the database and persist.

        Args:
            result: Firing result to add.
        """
        self.results.append(result)
        self._save_results()

    def predict_outcome(
        self,
        recipe: GlazeRecipe,
        firing: FiringSchedule,
        clay_body: ClayBody,
        clay_body_record: Optional[dict] = None,
    ) -> OutcomePrediction:
        """Predict outcome for a glaze firing.

        Args:
            recipe: Glaze recipe to fire.
            firing: Firing schedule.
            clay_body: Clay body type.
            clay_body_record: Full clay-body record from ClayBodyDatabase.
                Needed for defect conditions that depend on body chemistry
                (bloating keys off the body's iron content). Omitted means
                those conditions are skipped, not evaluated as false.

        Returns:
            OutcomePrediction with predicted results.
        """
        if not recipe.umf:
            raise ValueError("Recipe must have UMF calculated")

        umf = recipe.umf

        # Predict surface from the calibrated model
        surface = surface_model.predict_surface(umf)
        predicted_surface = self._predict_surface(umf, firing)

        # Confidence is the model's own probability for the predicted
        # class. It used to be min(0.5 + len(similar) * 0.1, 0.95) - and
        # since _find_similar_results kept anything matching on cone OR
        # atmosphere, and every stored firing result is cone 6 oxidation,
        # that saturated at 0.95 for essentially every recipe. It carried
        # no information at all.
        similar = self._find_similar_results(recipe, firing, clay_body)
        confidence = surface.confidence

        # Predict color
        color_family, color_notes = self._predict_color(recipe, firing)

        # Calculate defect risks from the defect guide's triggers
        defect_risks, defect_findings = self._calculate_defect_risks(
            recipe, firing, clay_body, clay_body_record
        )

        # Generate recommendations
        app_recs = self._application_recommendations(recipe, firing)
        firing_recs = self._firing_recommendations(recipe, firing, clay_body)

        return OutcomePrediction(
            predicted_surface=predicted_surface,
            confidence=confidence,
            predicted_color_family=color_family,
            color_notes=color_notes,
            defect_risks=defect_risks,
            application_recommendations=app_recs,
            firing_recommendations=firing_recs,
            similar_results=similar[:5],  # Top 5 similar
            surface_probabilities=dict(surface.probabilities),
            surface_basis=surface.basis,
            surface_caveat=surface.caveat,
            stability_flags=list(surface.stability),
            defect_findings=defect_findings,
        )

    def _predict_surface(
        self,
        umf: UMF,
        firing: FiringSchedule,
    ) -> GlazeSurface:
        """Predict glaze surface from the calibrated model.

        `firing` is accepted but unused: cone, atmosphere, hold and
        cooling rate all affect the real outcome, but none of them are in
        the training data, so claiming to use them would be false
        precision. See surface_model for the ~67% ceiling this implies.
        """
        prediction = surface_model.predict_surface(umf)

        surface_map = {
            "glossy": GlazeSurface.GLOSSY,
            "satin": GlazeSurface.SATIN,
            "matte": GlazeSurface.MATTE,
        }
        # High alumina distinguishes a dry matte from a smooth one - a
        # melt-stiffness effect, applied only once the model has already
        # concluded matte.
        if prediction.label == "matte" and "stiff" in prediction.stability:
            return GlazeSurface.DRY_MATTE
        return surface_map.get(prediction.label, GlazeSurface.SATIN)

    def _predict_color(
        self,
        recipe: GlazeRecipe,
        firing: FiringSchedule,
    ) -> tuple[Optional[str], Optional[str]]:
        """Predict color based on colorants and atmosphere."""
        if not recipe.colorants:
            # Base glaze color from iron content
            if recipe.umf and recipe.umf.Fe2O3 > 0.05:
                if firing.atmosphere == AtmosphereType.REDUCTION:
                    return "green/celadon", "Iron in reduction produces celadon tones"
                else:
                    return "amber/brown", "Iron in oxidation produces warm tones"
            return "clear/white", "No colorants - expect clear or white"

        # Analyze colorants
        color_family = None
        color_notes = []

        for colorant in recipe.colorants:
            name_lower = colorant.material_name.lower()

            if "cobalt" in name_lower or "coo" in name_lower:
                color_family = "blue"
                color_notes.append(f"{colorant.percentage}% cobalt = strong blue")

            elif "copper" in name_lower or "cuo" in name_lower:
                if firing.atmosphere == AtmosphereType.REDUCTION:
                    color_family = "red/copper"
                    color_notes.append(f"Copper in reduction = red/copper flash")
                else:
                    color_family = "green/turquoise"
                    color_notes.append(f"Copper in oxidation = green/turquoise")

            elif "iron" in name_lower or "fe2o3" in name_lower:
                pct = colorant.percentage
                if firing.atmosphere == AtmosphereType.REDUCTION:
                    if pct < 2:
                        color_family = "celadon"
                    else:
                        color_family = "tenmoku/brown"
                else:
                    color_family = "amber/rust"

            elif "rutile" in name_lower or "titanium" in name_lower:
                color_notes.append("Rutile adds tan/cream tones and crystalline effects")

            elif "manganese" in name_lower:
                color_family = "purple/brown"
                color_notes.append("Manganese produces purple-brown tones")

        return color_family, "; ".join(color_notes) if color_notes else None

    # Keys the UI has always rendered as a fixed grid. They are emitted
    # even at baseline so the layout does not jump; everything else in the
    # guide appears only when something actually triggers it.
    _ALWAYS_REPORTED = ("crawling", "crazing", "running", "pinholing")

    def _batch_percentage(self, recipe: GlazeRecipe, names: list[str]) -> Optional[float]:
        """Summed batch % of ingredients resolving to any of `names`.

        Returns None when there is no materials database to resolve
        against, so the caller can skip the condition rather than treat an
        unanswerable question as False.
        """
        if self.materials_db is None:
            return None
        wanted = {n.strip().lower() for n in names}
        total = 0.0
        for ingredient in recipe.ingredients:
            if ingredient.percentage <= 0:
                continue
            material = self.materials_db.get(ingredient.material_name)
            if material and material.name.strip().lower() in wanted:
                total += ingredient.percentage
        return total

    @staticmethod
    def _cone_number(firing) -> Optional[int]:
        """Firing cone as a signed integer, or None if unavailable.

        The leading-zero cones are the low-fire series and run the other
        way: 06 is much cooler than 6, not the same. They map to negative
        numbers so that ordering comparisons ("cone <= 6") behave. Note
        firing.cone is an enum, so its .value is what carries the digits.
        """
        raw = getattr(firing, "cone", None) if firing else None
        raw = getattr(raw, "value", raw)
        if raw is None:
            return None
        text = str(raw).strip()
        try:
            # "06", "04", "02" -> -6, -4, -2; "6", "10" -> 6, 10
            return -int(text[1:]) if len(text) > 1 and text.startswith("0") else int(text)
        except ValueError:
            return None

    @staticmethod
    def _dotted(record, path: str):
        for part in path.split("."):
            if record is None:
                return None
            record = record.get(part) if isinstance(record, dict) else getattr(record, part, None)
        return record

    def _evaluate_condition(self, condition, recipe, firing, clay_body_record):
        """Return (matched, bindings) — or (None, {}) if unanswerable."""
        kind = condition.get("kind")
        op = _OPS.get(condition.get("op"))
        if op is None:
            return None, {}
        value = condition.get("value")

        if kind == "umf":
            actual = getattr(recipe.umf, condition["oxide"], None)
            if actual is None:
                return None, {}
            return op(actual, value), {"oxide_value": actual}

        if kind == "umf_ratio":
            actual = getattr(recipe.umf, condition["ratio"], None)
            if actual is None:
                return None, {}
            return op(actual, value), {"ratio_value": actual}

        if kind == "batch_pct":
            actual = self._batch_percentage(recipe, condition.get("materials", []))
            if actual is None:
                return None, {}
            return op(actual, value), {"batch_pct": actual}

        if kind == "cone":
            cone = self._cone_number(firing)
            if cone is None:
                return None, {}
            return op(cone, value), {"cone": cone}

        if kind == "firing":
            actual = getattr(firing, condition["field"], None) if firing else None
            if actual is None:
                return None, {}
            actual = getattr(actual, "value", actual)  # unwrap enums
            return op(str(actual).lower(), str(value).lower()), {"firing_value": actual}

        if kind == "clay_body":
            actual = self._dotted(clay_body_record, condition["field"])
            if actual is None:
                return None, {}
            return op(actual, value), {"clay_body_value": actual}

        return None, {}

    def _calculate_defect_risks(
        self,
        recipe: GlazeRecipe,
        firing: FiringSchedule,
        clay_body: ClayBody,
        clay_body_record: Optional[dict] = None,
    ) -> tuple[dict[str, float], list[DefectRisk]]:
        """Evaluate the defect guide's triggers against this recipe.

        Replaces four hardcoded rules whose own docstring conceded they
        were "heuristic estimates ... not calibrated against firing data".
        Those four are preserved verbatim as triggers, but now tagged as
        uncalibrated so they are distinguishable from thresholds quoted
        from a book - and the guide's other defects, including all four
        from Fraser that no code path could previously reach, can fire.

        Triggers within a defect combine by max, never by sum: risks stay
        in 0-1 and a defect with several conditions does not inflate past
        one with a single strong one.
        """
        risks: dict[str, float] = {}
        findings: list[DefectRisk] = []

        for defect_name, entry in self.defect_guide.items():
            triggers = entry.get("triggers")
            if not triggers:
                continue

            key = entry.get("risk_key", defect_name)
            baseline = entry.get("baseline_risk", 0.0)
            best: Optional[tuple[float, dict, dict]] = None

            for trigger in triggers:
                bindings: dict = {}
                matched = True
                for condition in trigger.get("when", []):
                    result, bound = self._evaluate_condition(
                        condition, recipe, firing, clay_body_record
                    )
                    if result is not True:
                        matched = False
                        break
                    bindings.update(bound)
                if matched and (best is None or trigger["risk"] > best[0]):
                    best = (trigger["risk"], trigger, bindings)

            if best is None:
                if key in self._ALWAYS_REPORTED:
                    risks[key] = baseline
                continue

            risk, trigger, bindings = best
            risks[key] = risk
            try:
                message = trigger["message"].format(**bindings)
            except (KeyError, IndexError, ValueError):
                message = trigger["message"]
            findings.append(DefectRisk(
                defect=key,
                risk=risk,
                message=message,
                source=trigger.get("source", "unknown"),
                evidence=trigger.get("evidence", "uncalibrated_heuristic"),
                trigger_id=trigger.get("id", ""),
                remedies=entry.get("chemistry_remedies") or entry.get("remedies") or [],
            ))

        findings.sort(key=lambda f: f.risk, reverse=True)
        return risks, findings

    def _application_recommendations(
        self,
        recipe: GlazeRecipe,
        firing: FiringSchedule,
    ) -> list[str]:
        """Generate application recommendations."""
        recs = []
        umf = recipe.umf

        if umf.Al2O3 > 0.5:
            recs.append("Apply thicker coats - high alumina glaze can be dry if thin")

        if umf.Al2O3 < 0.25:
            recs.append("Apply thin coats - this glaze may run if thick")

        if recipe.colorant_additions > 5:
            recs.append("Multiple thin coats recommended for even colorant distribution")

        # High-fire
        cone_int = int(firing.cone.value) if firing.cone.value.isdigit() else 6
        if cone_int >= 10:
            recs.append("Allow adequate drying time before firing at high temperatures")

        return recs

    def _firing_recommendations(
        self,
        recipe: GlazeRecipe,
        firing: FiringSchedule,
        clay_body: ClayBody,
    ) -> list[str]:
        """Generate firing recommendations."""
        recs = []
        umf = recipe.umf

        # Soaking
        if umf.Al2O3 > 0.4:
            recs.append("Consider soaking at peak temperature for better melt")

        # Cooling
        if umf.ZnO > 0.1 or umf.TiO2 > 0.05:
            recs.append("Slow cool for crystal development")

        # Reduction
        if firing.atmosphere == AtmosphereType.REDUCTION:
            recs.append("Start reduction around cone 010-08 for best results")
            if umf.Fe2O3 > 0.02:
                recs.append("Maintain steady reduction for consistent iron effects")

        return recs

    def _find_similar_results(
        self,
        recipe: GlazeRecipe,
        firing: FiringSchedule,
        clay_body: ClayBody,
    ) -> list[FiringResult]:
        """Find similar firing results in database."""
        similar = []

        for result in self.results:
            score = 0

            # Same glaze
            if result.glazy_id and recipe.glazy_id == result.glazy_id:
                score += 5

            # Same cone
            if result.firing_schedule and result.firing_schedule.cone == firing.cone:
                score += 2

            # Same atmosphere
            if result.firing_schedule and result.firing_schedule.atmosphere == firing.atmosphere:
                score += 2

            # Same clay body
            if result.clay_body == clay_body:
                score += 1

            # Requires cone AND atmosphere (or a direct glaze match), not
            # either alone. At >= 2 a single shared attribute qualified,
            # and since every stored result is cone 6 oxidation, every
            # cone-6-or-oxidation query matched the entire table - which
            # is what made the old confidence formula saturate.
            if score >= 4:
                similar.append((score, result))

        # Sort by score and return results
        similar.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in similar]
