"""Glaze chemistry analysis service."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..models.materials import OxideAnalysis, OXIDE_MOLECULAR_WEIGHTS
from ..models.glaze import (
    GlazeRecipe,
    ConeTemperature,
    AtmosphereType,
    GlazeSurface,
)
from ..models.umf import UMF, StullPoint, get_umf_ranges
from . import surface_model

logger = logging.getLogger(__name__)

_REFERENCE_DIR = Path(__file__).parent.parent.parent / "data" / "reference"


def _load_oxide_properties() -> dict:
    path = _REFERENCE_DIR / "oxide_properties.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("oxides", {})
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Error loading oxide_properties.json: %s", e)
        return {}


def _load_defect_guide() -> dict:
    path = _REFERENCE_DIR / "defect_guide.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("defects", {})
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Error loading defect_guide.json: %s", e)
        return {}


@dataclass
class ChemistryAnalysis:
    """Analysis of glaze chemistry."""
    umf: UMF
    stull_point: StullPoint

    # Ratios
    silica_alumina_ratio: float
    alkali_ratio: float
    alkaline_earth_ratio: float

    # Predictions
    predicted_surface: str
    predicted_cone_range: tuple[int, int]

    # Potential issues
    issues: list[str]
    warnings: list[str]

    # Recommendations
    recommendations: list[str]


@dataclass
class ThermalExpansionAnalysis:
    """Analysis of thermal expansion and fit."""
    calculated_coe: float  # Coefficient of expansion, x10^-6/C
    clay_body_coe: float
    crazing_risk: str  # "low", "medium", "high"
    shivering_risk: str
    recommendations: list[str]


class GlazeAnalyzer:
    """Analyze glaze chemistry and predict properties."""

    def __init__(
        self,
        oxide_properties: Optional[dict] = None,
        defect_guide: Optional[dict] = None,
    ):
        """Args:
            oxide_properties: symbol -> {coe_factor, ...}. Defaults to
                data/reference/oxide_properties.json (Digitalfire-sourced).
            defect_guide: defect key -> {chemistry_remedies, other_remedies,
                ...}. Defaults to data/reference/defect_guide.json.
        """
        self.oxide_properties = (
            oxide_properties if oxide_properties is not None else _load_oxide_properties()
        )
        self.defect_guide = (
            defect_guide if defect_guide is not None else _load_defect_guide()
        )

    def analyze_chemistry(
        self,
        recipe: GlazeRecipe,
        target_cone: Optional[ConeTemperature] = None,
    ) -> ChemistryAnalysis:
        """Perform full chemistry analysis on a recipe.

        Args:
            recipe: Glaze recipe with calculated UMF.
            target_cone: Target firing cone.

        Returns:
            ChemistryAnalysis with predictions and recommendations.
        """
        if not recipe.umf:
            raise ValueError("Recipe must have UMF calculated")

        umf = recipe.umf
        cone = target_cone or recipe.target_cone
        cone_int = int(cone.value) if cone.value.isdigit() else 6

        # Calculate ratios
        si_al_ratio = umf.silica_alumina_ratio
        alkali_ratio = umf.alkali_ratio

        alkaline_earth = umf.CaO + umf.MgO + umf.BaO + umf.SrO
        alkaline_earth_ratio = alkaline_earth / umf.flux_total if umf.flux_total > 0 else 0

        # Get Stull point and prediction
        stull = umf.stull_point
        predicted_surface = stull.surface_prediction

        # Determine cone range based on flux composition
        predicted_cone_range = self._predict_cone_range(umf)

        # Identify issues
        issues = []
        warnings = []
        recommendations = []

        # Check UMF ranges for target cone
        ranges = get_umf_ranges(cone_int)

        # SiO2 check
        if umf.SiO2 < ranges["SiO2"][0]:
            issues.append(f"SiO2 ({umf.SiO2:.2f}) is below typical range for cone {cone.value}")
            recommendations.append("Add silica or high-silica feldspar")
        elif umf.SiO2 > ranges["SiO2"][1]:
            warnings.append(f"SiO2 ({umf.SiO2:.2f}) is high - may be underfired")

        # Al2O3 check
        if umf.Al2O3 < ranges["Al2O3"][0]:
            issues.append(f"Al2O3 ({umf.Al2O3:.2f}) is low - glaze may run")
            recommendations.append("Add kaolin or alumina hydrate")
        elif umf.Al2O3 > ranges["Al2O3"][1]:
            warnings.append(f"Al2O3 ({umf.Al2O3:.2f}) is high - may be matte/dry")

        # Flux balance
        if alkali_ratio > 0.5:
            warnings.append("High alkali ratio may cause crazing")
            recommendations.append("Substitute some alkali flux with calcium or magnesium")

        # Melt stability from the shared calibrated thresholds, rather
        # than the si_al < 5 / > 15 cuts this method used to carry - which
        # disagreed with the 6 / 12 used everywhere else in the codebase.
        for flag in surface_model.predict_surface(umf).stability:
            if flag == "runny":
                issues.append("High Si:Al ratio - glaze may be runny")
            elif flag == "underfired":
                issues.append("Very low alumina - glaze may be underfired and unstable")
            elif flag == "stiff":
                issues.append("Very high alumina - glaze may be stiff and dry")

        # Soluble material warning
        if hasattr(recipe, '_has_soluble') and recipe._has_soluble:
            warnings.append(
                "Contains soluble flux — actual chemistry varies between "
                "body (depleted) and surface (enriched). Use dual UMF analysis "
                "for accurate prediction."
            )

        # Lead warning
        if umf.PbO > 0:
            warnings.append("Contains lead oxide - not food safe")

        # Barium warning
        if recipe.umf.BaO > 0.1:
            warnings.append("High barium content - use caution, not food safe")

        return ChemistryAnalysis(
            umf=umf,
            stull_point=stull,
            silica_alumina_ratio=si_al_ratio,
            alkali_ratio=alkali_ratio,
            alkaline_earth_ratio=alkaline_earth_ratio,
            predicted_surface=predicted_surface,
            predicted_cone_range=predicted_cone_range,
            issues=issues,
            warnings=warnings,
            recommendations=recommendations,
        )

    def analyze_thermal_expansion(
        self,
        recipe: GlazeRecipe,
        clay_body_coe: Optional[float] = None,
    ) -> ThermalExpansionAnalysis:
        """Analyze thermal expansion and glaze fit.

        Args:
            recipe: Glaze recipe with UMF.
            clay_body_coe: Coefficient of expansion of the clay body, x10^-6/C
                (see data/materials/clay_bodies.json for real per-body
                values - callers should resolve one there rather than pass
                nothing). Falls back to 6.0, a generic stoneware midpoint,
                only if the caller has no body information at all.

        Returns:
            ThermalExpansionAnalysis with fit predictions. calculated_coe is
            an estimate from oxide chemistry, not a dilatometer measurement -
            see _calculate_coe for what that does and doesn't capture.
        """
        if not recipe.umf:
            raise ValueError("Recipe must have UMF calculated")

        coe = self._calculate_coe(recipe.umf)
        clay_coe = clay_body_coe if clay_body_coe is not None else 6.0

        # Determine risks. Thresholds unchanged from the previous
        # implementation - they were tuned against the same ~5-8 output
        # scale this real formula also produces (validated against typical
        # cone 6 glossy UMFs during development).
        coe_diff = coe - clay_coe

        if coe_diff > 1.0:
            crazing_risk = "high"
        elif coe_diff > 0.5:
            crazing_risk = "medium"
        else:
            crazing_risk = "low"

        if coe_diff < -1.0:
            shivering_risk = "high"
        elif coe_diff < -0.5:
            shivering_risk = "medium"
        else:
            shivering_risk = "low"

        recommendations = [
            "Calculated from oxide chemistry, not measured - clay bodies in "
            "particular cannot be predicted this way (see the caveat in "
            "data/reference/oxide_properties.json). Confirm with a real fit "
            "test before production use."
        ]
        if crazing_risk in ("medium", "high"):
            recommendations += self._defect_remedies("crazing")
        if shivering_risk in ("medium", "high"):
            recommendations += self._defect_remedies("shivering")

        return ThermalExpansionAnalysis(
            calculated_coe=coe,
            clay_body_coe=clay_coe,
            crazing_risk=crazing_risk,
            shivering_risk=shivering_risk,
            recommendations=recommendations,
        )

    def _defect_remedies(self, defect_key: str) -> list[str]:
        """Chemistry-only remedies for a defect from the archived guide."""
        defect = self.defect_guide.get(defect_key, {})
        return list(defect.get("chemistry_remedies", []))

    def compare_recipes(
        self,
        recipe_a: GlazeRecipe,
        recipe_b: GlazeRecipe,
    ) -> dict:
        """Compare two glaze recipes.

        Args:
            recipe_a: First recipe.
            recipe_b: Second recipe.

        Returns:
            Comparison results.
        """
        if not recipe_a.umf or not recipe_b.umf:
            raise ValueError("Both recipes must have UMF calculated")

        umf_a = recipe_a.umf
        umf_b = recipe_b.umf

        differences = {}
        for oxide in ["SiO2", "Al2O3", "Na2O", "K2O", "CaO", "MgO", "ZnO", "B2O3"]:
            val_a = getattr(umf_a, oxide)
            val_b = getattr(umf_b, oxide)
            if val_a > 0 or val_b > 0:
                differences[oxide] = {
                    "recipe_a": round(val_a, 4),
                    "recipe_b": round(val_b, 4),
                    "difference": round(val_b - val_a, 4),
                }

        return {
            "ingredient_comparison": self._compare_ingredients(recipe_a, recipe_b),
            "umf_differences": differences,
            "surface_prediction_a": umf_a.stull_point.surface_prediction,
            "surface_prediction_b": umf_b.stull_point.surface_prediction,
            "si_al_ratio_a": round(umf_a.silica_alumina_ratio, 2),
            "si_al_ratio_b": round(umf_b.silica_alumina_ratio, 2),
        }

    def _predict_cone_range(self, umf: UMF) -> tuple[int, int]:
        """Predict firing cone range based on flux composition."""
        # High alkali = lower temperature
        # High alkaline earth = higher temperature
        alkali_ratio = umf.alkali_ratio

        if alkali_ratio > 0.5:
            return (4, 8)
        elif alkali_ratio > 0.3:
            return (6, 10)
        else:
            return (8, 12)

    def _calculate_coe(self, umf: UMF) -> float:
        """Estimate glaze coefficient of thermal expansion from its UMF.

        Method: convert each oxide's UMF molar amount to weight percent of
        the fired glass (molar x molecular weight, normalized to 100), then
        sum weight_percent x coe_factor across oxides. coe_factor values are
        archived from Digitalfire (data/reference/oxide_properties.json).
        Validated against typical cone 6 glossy UMFs to land in the ~5-8
        x10^-6/C range that matches the clay body COEs already in
        data/materials/clay_bodies.json, so the two numbers are comparable.

        This estimates a GLAZE's expansion only. Digitalfire is explicit
        that the same approach does not work for clay bodies: fired clay is
        a mix of unreacted mineral grains, melted glass and altered crystal
        phases, not a single oxide-formula glass. Always resolve clay body
        COE from data/materials/clay_bodies.json (or a real measurement),
        never calculate it.
        """
        if not self.oxide_properties:
            return 6.0  # No factor data available - can't estimate.

        weights: dict[str, float] = {}
        for oxide, molecular_weight in OXIDE_MOLECULAR_WEIGHTS.items():
            molar = getattr(umf, oxide, 0.0)
            if molar > 0:
                weights[oxide] = molar * molecular_weight

        total_weight = sum(weights.values())
        if total_weight <= 0:
            return 6.0

        coe = 0.0
        for oxide, weight in weights.items():
            factor = self.oxide_properties.get(oxide, {}).get("coe_factor")
            if factor is not None:
                coe += (weight / total_weight * 100) * factor

        return round(coe, 2)

    def _compare_ingredients(
        self,
        recipe_a: GlazeRecipe,
        recipe_b: GlazeRecipe,
    ) -> dict:
        """Compare ingredients between recipes."""
        a_ings = {i.material_name.lower(): i.percentage for i in recipe_a.ingredients}
        b_ings = {i.material_name.lower(): i.percentage for i in recipe_b.ingredients}

        only_a = set(a_ings.keys()) - set(b_ings.keys())
        only_b = set(b_ings.keys()) - set(a_ings.keys())
        common = set(a_ings.keys()) & set(b_ings.keys())

        return {
            "only_in_a": list(only_a),
            "only_in_b": list(only_b),
            "common": {
                name: {
                    "a": a_ings[name],
                    "b": b_ings[name],
                    "diff": b_ings[name] - a_ings[name],
                }
                for name in common
            },
        }
