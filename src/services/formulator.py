"""Glaze formulation engine."""

from dataclasses import dataclass
from typing import Optional

from ..models.materials import Material, MaterialType, OxideAnalysis, OXIDE_MOLECULAR_WEIGHTS
from ..models.glaze import (
    GlazeRecipe,
    GlazeIngredient,
    Colorant,
    ConeTemperature,
    AtmosphereType,
    GlazeSurface,
    GlazeType,
)
from ..models.umf import UMF, get_umf_ranges
from .materials_db import MaterialsDatabase


@dataclass
class FormulationTarget:
    """Target UMF values for glaze formulation."""
    cone: ConeTemperature
    surface: GlazeSurface

    # Target UMF values
    sio2_target: float = 3.5
    al2o3_target: float = 0.4
    b2o3_target: float = 0.0

    # Flux distribution
    alkali_ratio: float = 0.3  # (Na2O + K2O + Li2O) / total flux
    cao_target: float = 0.4
    mgo_target: float = 0.1

    # Tolerance
    tolerance: float = 0.1  # Allow 10% deviation


@dataclass
class FormulationResult:
    """Result of glaze formulation."""
    recipe: GlazeRecipe
    achieved_umf: UMF
    target_umf: Optional[UMF] = None
    deviation_score: float = 0.0  # Lower is better
    suggestions: list[str] = None

    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


class GlazeFormulator:
    """Engine for creating and adjusting glaze recipes."""

    def __init__(self, materials_db: MaterialsDatabase):
        """Initialize the formulator.

        Args:
            materials_db: Database of available materials.
        """
        self.materials_db = materials_db

    def calculate_recipe_analysis(
        self,
        recipe: GlazeRecipe,
    ) -> OxideAnalysis:
        """Calculate the combined oxide analysis for a recipe.

        Args:
            recipe: Glaze recipe.

        Returns:
            Combined oxide analysis.
        """
        combined = OxideAnalysis()

        for ingredient in recipe.ingredients:
            material = self.materials_db.get(ingredient.material_name)
            if not material:
                continue

            # Weight the material's analysis by its percentage
            factor = ingredient.percentage / 100.0
            analysis = material.analysis.oxide_analysis

            for oxide in [
                "SiO2", "Al2O3", "B2O3", "Na2O", "K2O", "Li2O",
                "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO",
                "Fe2O3", "FeO", "TiO2", "MnO", "CuO", "CoO",
                "Cr2O3", "NiO", "ZrO2", "SnO2", "P2O5"
            ]:
                current = getattr(combined, oxide)
                addition = getattr(analysis, oxide) * factor
                setattr(combined, oxide, current + addition)

        return combined

    def calculate_umf(self, recipe: GlazeRecipe) -> UMF:
        """Calculate the Unity Molecular Formula for a recipe.

        Args:
            recipe: Glaze recipe.

        Returns:
            Calculated UMF.
        """
        analysis = self.calculate_recipe_analysis(recipe)
        return UMF.from_oxide_analysis(analysis)

    def formulate_base_glaze(
        self,
        target: FormulationTarget,
        available_materials: Optional[list[str]] = None,
    ) -> FormulationResult:
        """Create a base glaze recipe to meet target UMF.

        This is a simplified formulation algorithm. A full implementation
        would use linear algebra or optimization algorithms.

        Args:
            target: Target UMF and properties.
            available_materials: List of material names to use (None = all).

        Returns:
            FormulationResult with generated recipe.
        """
        # Get materials
        if available_materials:
            materials = [
                self.materials_db.get(name)
                for name in available_materials
                if self.materials_db.get(name)
            ]
        else:
            materials = self.materials_db.get_all()

        if not materials:
            raise ValueError("No materials available for formulation")

        # Simple formulation: start with typical proportions
        ingredients = []

        # Find a feldspar (flux + alumina + silica source)
        feldspars = [m for m in materials if "feldspar" in m.name.lower()]
        if feldspars:
            ingredients.append(GlazeIngredient(
                material_name=feldspars[0].name,
                percentage=40.0,
            ))

        # Find silica
        silica_sources = [m for m in materials if "silica" in m.name.lower() or "flint" in m.name.lower()]
        if silica_sources:
            ingredients.append(GlazeIngredient(
                material_name=silica_sources[0].name,
                percentage=25.0,
            ))

        # Find kaolin (alumina source)
        kaolins = [m for m in materials if "kaolin" in m.name.lower() or "epk" in m.name.lower()]
        if kaolins:
            ingredients.append(GlazeIngredient(
                material_name=kaolins[0].name,
                percentage=15.0,
            ))

        # Find calcium source
        ca_sources = [m for m in materials if "whiting" in m.name.lower() or "wollastonite" in m.name.lower()]
        if ca_sources:
            ingredients.append(GlazeIngredient(
                material_name=ca_sources[0].name,
                percentage=15.0,
            ))

        # Find talc or dolomite for MgO
        mg_sources = [m for m in materials if "talc" in m.name.lower() or "dolomite" in m.name.lower()]
        if mg_sources:
            ingredients.append(GlazeIngredient(
                material_name=mg_sources[0].name,
                percentage=5.0,
            ))

        # Normalize to 100%
        total = sum(i.percentage for i in ingredients)
        if total > 0:
            for i in ingredients:
                i.percentage = (i.percentage / total) * 100

        recipe = GlazeRecipe(
            name=f"Generated {target.surface.value.title()} Base",
            ingredients=ingredients,
            target_cone=target.cone,
            glaze_type=GlazeType.BASE,
            expected_surface=target.surface,
        )

        # Calculate achieved UMF
        achieved_umf = self.calculate_umf(recipe)
        recipe.umf = achieved_umf

        # Calculate deviation
        deviation = self._calculate_deviation(achieved_umf, target)

        # Generate suggestions
        suggestions = self._generate_suggestions(achieved_umf, target)

        return FormulationResult(
            recipe=recipe,
            achieved_umf=achieved_umf,
            deviation_score=deviation,
            suggestions=suggestions,
        )

    def adjust_recipe(
        self,
        recipe: GlazeRecipe,
        adjustment: str,
        amount: float = 5.0,
    ) -> GlazeRecipe:
        """Adjust a recipe by adding or changing materials.

        Args:
            recipe: Original recipe.
            adjustment: Type of adjustment (e.g., "more_flux", "more_alumina").
            amount: Amount to adjust by (percentage points).

        Returns:
            Adjusted recipe.
        """
        new_recipe = GlazeRecipe(
            name=f"{recipe.name} (adjusted)",
            ingredients=list(recipe.ingredients),
            colorants=list(recipe.colorants),
            target_cone=recipe.target_cone,
            suitable_atmospheres=list(recipe.suitable_atmospheres),
            suitable_clay_bodies=list(recipe.suitable_clay_bodies),
            glaze_type=recipe.glaze_type,
            expected_surface=recipe.expected_surface,
        )

        if adjustment == "more_flux":
            # Find or add a flux material
            flux_materials = self.materials_db.get_by_type(MaterialType.FLUX)
            if flux_materials:
                new_recipe.ingredients.append(GlazeIngredient(
                    material_name=flux_materials[0].name,
                    percentage=amount,
                    notes="Added for more flux",
                ))

        elif adjustment == "more_silica":
            # Increase silica
            for ing in new_recipe.ingredients:
                if "silica" in ing.material_name.lower():
                    ing.percentage += amount
                    break
            else:
                silica = self.materials_db.get("silica")
                if silica:
                    new_recipe.ingredients.append(GlazeIngredient(
                        material_name=silica.name,
                        percentage=amount,
                    ))

        elif adjustment == "more_alumina":
            # Increase alumina
            for ing in new_recipe.ingredients:
                if "kaolin" in ing.material_name.lower():
                    ing.percentage += amount
                    break

        # Renormalize
        total = sum(i.percentage for i in new_recipe.ingredients)
        for ing in new_recipe.ingredients:
            ing.percentage = (ing.percentage / total) * 100

        new_recipe.umf = self.calculate_umf(new_recipe)
        return new_recipe

    def add_colorant(
        self,
        recipe: GlazeRecipe,
        colorant_name: str,
        percentage: float,
        expected_color: Optional[str] = None,
    ) -> GlazeRecipe:
        """Add a colorant to a glaze recipe.

        Args:
            recipe: Base recipe.
            colorant_name: Name of colorant material.
            percentage: Addition percentage.
            expected_color: Expected color result.

        Returns:
            New recipe with colorant added.
        """
        new_recipe = GlazeRecipe(
            name=f"{recipe.name} + {colorant_name}",
            ingredients=list(recipe.ingredients),
            colorants=list(recipe.colorants),
            target_cone=recipe.target_cone,
            suitable_atmospheres=list(recipe.suitable_atmospheres),
            suitable_clay_bodies=list(recipe.suitable_clay_bodies),
            glaze_type=recipe.glaze_type,
            expected_surface=recipe.expected_surface,
            umf=recipe.umf,
        )

        new_recipe.colorants.append(Colorant(
            material_name=colorant_name,
            percentage=percentage,
            expected_color=expected_color,
        ))

        return new_recipe

    def _calculate_deviation(self, achieved: UMF, target: FormulationTarget) -> float:
        """Calculate how far achieved UMF is from target."""
        deviations = [
            abs(achieved.SiO2 - target.sio2_target) / target.sio2_target,
            abs(achieved.Al2O3 - target.al2o3_target) / target.al2o3_target if target.al2o3_target > 0 else 0,
            abs(achieved.alkali_ratio - target.alkali_ratio) / target.alkali_ratio if target.alkali_ratio > 0 else 0,
        ]
        return sum(deviations) / len(deviations)

    def _generate_suggestions(self, achieved: UMF, target: FormulationTarget) -> list[str]:
        """Generate adjustment suggestions based on deviation."""
        suggestions = []

        if achieved.SiO2 < target.sio2_target * 0.9:
            suggestions.append("Add more silica to increase glass former")
        elif achieved.SiO2 > target.sio2_target * 1.1:
            suggestions.append("Reduce silica or add more flux")

        if achieved.Al2O3 < target.al2o3_target * 0.9:
            suggestions.append("Add kaolin or feldspar for more alumina")
        elif achieved.Al2O3 > target.al2o3_target * 1.1:
            suggestions.append("Reduce kaolin to lower alumina")

        # Check Stull chart position
        stull = achieved.stull_point
        if stull.surface_prediction == "runny":
            suggestions.append("Formula may run - add more alumina")
        elif stull.surface_prediction == "dry_matte":
            suggestions.append("Formula may be dry - reduce alumina or add flux")

        return suggestions
