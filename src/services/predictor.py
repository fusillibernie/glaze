"""Outcome prediction based on glaze data and firing results."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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

    def __post_init__(self):
        if self.defect_risks is None:
            self.defect_risks = {}
        if self.application_recommendations is None:
            self.application_recommendations = []
        if self.firing_recommendations is None:
            self.firing_recommendations = []
        if self.similar_results is None:
            self.similar_results = []


_DEFAULT_RESULTS_PATH = Path(__file__).parent.parent.parent / "data" / "results" / "firing_results.json"


class OutcomePredictor:
    """Predict glaze firing outcomes based on historical data."""

    def __init__(
        self,
        results_database: Optional[list[FiringResult]] = None,
        results_path: Optional[Path] = None,
    ):
        """Initialize the predictor.

        Args:
            results_database: Historical firing results for prediction.
            results_path: Path to JSON file for persisting results.
        """
        self.results_path = results_path or _DEFAULT_RESULTS_PATH
        self.results = results_database or self._load_results()

    def _load_results(self) -> list[FiringResult]:
        """Load persisted results from disk."""
        if not self.results_path.exists():
            return []
        try:
            with open(self.results_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Results stored as plain dicts; reconstruct minimal FiringResult objects
            results = []
            for item in data:
                try:
                    results.append(FiringResult.from_dict(item))
                except Exception:
                    pass
            return results
        except Exception:
            return []

    def _save_results(self) -> None:
        """Persist results to disk."""
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = []
        for r in self.results:
            try:
                serializable.append(r.to_dict())
            except Exception:
                pass
        with open(self.results_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, default=str)

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
    ) -> OutcomePrediction:
        """Predict outcome for a glaze firing.

        Args:
            recipe: Glaze recipe to fire.
            firing: Firing schedule.
            clay_body: Clay body type.

        Returns:
            OutcomePrediction with predicted results.
        """
        if not recipe.umf:
            raise ValueError("Recipe must have UMF calculated")

        umf = recipe.umf

        # Predict surface based on Stull chart
        predicted_surface = self._predict_surface(umf, firing)

        # Calculate confidence based on data availability
        similar = self._find_similar_results(recipe, firing, clay_body)
        confidence = min(0.5 + len(similar) * 0.1, 0.95)

        # Predict color
        color_family, color_notes = self._predict_color(recipe, firing)

        # Calculate defect risks
        defect_risks = self._calculate_defect_risks(recipe, firing, clay_body)

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
        )

    def _predict_surface(
        self,
        umf: UMF,
        firing: FiringSchedule,
    ) -> GlazeSurface:
        """Predict glaze surface based on chemistry."""
        stull_prediction = umf.stull_point.surface_prediction

        surface_map = {
            "glossy": GlazeSurface.GLOSSY,
            "glossy_runny": GlazeSurface.GLOSSY,
            "satin": GlazeSurface.SATIN,
            "matte": GlazeSurface.MATTE,
            "matte_dry": GlazeSurface.DRY_MATTE,
            "underfired_runny": GlazeSurface.GLOSSY,
        }

        return surface_map.get(stull_prediction, GlazeSurface.SATIN)

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

    def _calculate_defect_risks(
        self,
        recipe: GlazeRecipe,
        firing: FiringSchedule,
        clay_body: ClayBody,
    ) -> dict[str, float]:
        """Calculate risk of various defects.

        NOTE: These thresholds are heuristic estimates based on general ceramic
        principles, not calibrated against firing data. Treat as rough guidance.
        Ref: Hamer & Hamer "The Potter's Dictionary", Rhodes "Clay and Glazes".
        """
        risks = {}
        umf = recipe.umf

        # Crawling risk — high alumina increases raw glaze stiffness
        # Al2O3 > 0.5 UMF is high for most glazes (typical range 0.2-0.5)
        if umf.Al2O3 > 0.5:
            risks["crawling"] = 0.3
        else:
            risks["crawling"] = 0.1

        # Crazing risk — high alkali (Na2O+K2O) raises thermal expansion
        # Alkali ratio > 0.4 of total flux is considered high expansion risk
        if umf.alkali_ratio > 0.4:
            risks["crazing"] = 0.5
        elif umf.alkali_ratio > 0.3:
            risks["crazing"] = 0.2
        else:
            risks["crazing"] = 0.1

        # Running risk — low alumina reduces melt viscosity
        # Al2O3 < 0.2 is very low (crystalline glaze territory)
        if umf.Al2O3 < 0.2:
            risks["running"] = 0.5
        elif umf.Al2O3 < 0.3:
            risks["running"] = 0.3
        else:
            risks["running"] = 0.1

        # Pinholing risk — fast cooling traps gas bubbles; high boron off-gases
        if firing.cooling_rate == "crash":
            risks["pinholing"] = 0.4
        elif umf.B2O3 > 0.3:
            risks["pinholing"] = 0.3
        else:
            risks["pinholing"] = 0.15

        return risks

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

            if score >= 2:
                similar.append((score, result))

        # Sort by score and return results
        similar.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in similar]
