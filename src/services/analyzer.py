"""Glaze chemistry analysis service."""

from dataclasses import dataclass
from typing import Optional

from ..models.materials import OxideAnalysis
from ..models.glaze import (
    GlazeRecipe,
    ConeTemperature,
    AtmosphereType,
    GlazeSurface,
)
from ..models.umf import UMF, StullPoint, get_umf_ranges


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
    calculated_coe: float  # Coefficient of expansion
    crazing_risk: str  # "low", "medium", "high"
    shivering_risk: str
    recommendations: list[str]


class GlazeAnalyzer:
    """Analyze glaze chemistry and predict properties."""

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

        # Si:Al ratio
        if si_al_ratio < 5:
            issues.append("Low Si:Al ratio - glaze will be very matte/dry")
        elif si_al_ratio > 15:
            issues.append("High Si:Al ratio - glaze may be runny")

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
            clay_body_coe: Coefficient of expansion of clay body.

        Returns:
            ThermalExpansionAnalysis with fit predictions.
        """
        if not recipe.umf:
            raise ValueError("Recipe must have UMF calculated")

        umf = recipe.umf

        # Calculate approximate COE using Appen factors
        # This is simplified - real calculation would use full Appen method
        coe = self._calculate_approximate_coe(umf)

        # Typical clay body COE ranges
        # Stoneware: ~5.5-6.5 x 10^-6
        # Porcelain: ~4.5-5.5 x 10^-6
        default_clay_coe = 6.0
        clay_coe = clay_body_coe or default_clay_coe

        # Determine risks
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

        recommendations = ["COE is approximate (+/- 1.0) — test with dilatometer for production use"]
        if crazing_risk in ("medium", "high"):
            recommendations.append("Reduce alkali flux (Na2O, K2O) to lower expansion")
            recommendations.append("Add more silica or boron")
        if shivering_risk in ("medium", "high"):
            recommendations.append("Increase alkali flux to raise expansion")
            recommendations.append("Reduce silica slightly")

        return ThermalExpansionAnalysis(
            calculated_coe=coe,
            crazing_risk=crazing_risk,
            shivering_risk=shivering_risk,
            recommendations=recommendations,
        )

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

    def _calculate_approximate_coe(self, umf: UMF) -> float:
        """Calculate approximate coefficient of expansion.

        Uses simplified Appen factors. Values are x 10^-6.

        DISCLAIMER: This is a rough approximation using weighted averages of
        simplified Appen factors. Real COE depends on oxide interactions,
        cooling rate, and crystallization. Accuracy is estimated at +/- 1.0.
        For food-safe or production work, test with a dilatometer.
        """
        # Appen factors (simplified)
        factors = {
            "SiO2": 0.5,
            "Al2O3": 1.0,
            "B2O3": -1.5,  # Reduces expansion
            "Na2O": 7.0,
            "K2O": 6.5,
            "Li2O": 5.0,
            "CaO": 3.0,
            "MgO": 0.5,
            "BaO": 3.5,
            "ZnO": 1.5,
        }

        total = 0.0
        weight_sum = 0.0

        for oxide, factor in factors.items():
            value = getattr(umf, oxide, 0.0)
            if value > 0:
                total += value * factor
                weight_sum += value

        if weight_sum > 0:
            return total / weight_sum * 10  # Scale to typical range
        return 6.0  # Default

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
