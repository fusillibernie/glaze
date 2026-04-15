"""Glaze formulation engine."""

from dataclasses import dataclass, field
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
from .target_resolver import TargetResolver
from .solver import GlazeSolver


@dataclass
class DualUMFResult:
    """UMF result for recipes containing soluble materials.

    Soluble fluxes (e.g. Soda Ash, Pearl Ash) dissolve in water and migrate
    to the glaze surface during drying. This creates two distinct zones:
    - body_umf: UMF of the insoluble portion (what remains in the glaze body)
    - surface_umf: UMF enriched with soluble flux (what concentrates at the surface)
    - nominal_umf: Standard UMF as if everything were evenly distributed
    """
    nominal_umf: UMF
    body_umf: UMF
    surface_umf: UMF
    soluble_fraction: float  # Fraction of total flux from soluble materials
    soluble_materials: list[str]  # Names of soluble materials in recipe


# Virtual ash accumulation by kiln position
# These multipliers represent relative ash deposit thickness as a fraction
# of total glaze weight. Firebox gets the heaviest deposits, back gets the least.
KILN_POSITION_ASH_MULTIPLIERS = {
    "firebox": 0.15,           # 15% virtual ash addition — heaviest deposits
    "front_to_middle": 0.10,   # 10% — significant ash landing
    "front": 0.10,
    "middle": 0.05,            # 5% — moderate ash
    "middle_to_back": 0.03,    # 3% — lighter deposits
    "back": 0.01,              # 1% — minimal ash, mostly flash effects
    "any": 0.05,               # 5% — default to moderate
}

# Typical mixed hardwood ash composition (weight %) for virtual accumulation
# Based on washed mixed hardwood ash analysis
VIRTUAL_ASH_COMPOSITION = {
    "CaO": 40.0,
    "SiO2": 12.0,
    "K2O": 10.0,
    "MgO": 8.0,
    "P2O5": 5.0,
    "Na2O": 3.0,
    "Al2O3": 3.0,
    "Fe2O3": 1.5,
    "MnO": 1.5,
}


@dataclass
class AshAccumulationResult:
    """Result of applying virtual ash accumulation to a recipe."""
    base_umf: UMF
    ash_modified_umf: UMF
    kiln_position: str
    ash_addition_pct: float  # Virtual ash added as % of recipe weight
    ash_composition: dict[str, float]


@dataclass
class FormulationTarget:
    """Target UMF values for glaze formulation."""
    cone: ConeTemperature
    surface: GlazeSurface

    # Descriptor-based formulation (new)
    atmosphere: Optional[str] = None  # oxidation, reduction, neutral, wood
    category: Optional[str] = None  # celadon, shino, tenmoku, etc.
    colorants: Optional[list[dict]] = None  # [{"material_name": str, "percentage": float}]

    # Legacy target UMF values (used as fallback when category is not specified)
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
    target_fit: dict = None  # Per-oxide: {min, max, achieved, in_range}

    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []
        if self.target_fit is None:
            self.target_fit = {}


@dataclass
class ResolvedInheritance:
    """Result of resolving recipe inheritance."""
    recipe: GlazeRecipe
    parent_name: Optional[str]
    additions: list[GlazeIngredient]
    inherited_ingredients: list[GlazeIngredient]


class GlazeFormulator:
    """Engine for creating and adjusting glaze recipes."""

    def __init__(self, materials_db: MaterialsDatabase, substitution_service=None):
        """Initialize the formulator.

        Args:
            materials_db: Database of available materials.
            substitution_service: Optional SubstitutionService for availability filtering.
        """
        self.materials_db = materials_db
        self.substitution_service = substitution_service
        self._recipe_registry: dict[str, GlazeRecipe] = {}
        self._target_resolver = TargetResolver()
        self._solver = GlazeSolver()

    def register_recipe(self, recipe: GlazeRecipe) -> None:
        """Register a recipe so it can be used as a parent for inheritance."""
        self._recipe_registry[recipe.name.lower()] = recipe

    def resolve_inheritance(
        self,
        recipe_data: dict,
    ) -> ResolvedInheritance:
        """Resolve recipe inheritance from a parent_glaze + additions pattern.

        A recipe can specify:
          - "parent_glaze": name of registered base recipe
          - "additions": list of extra ingredients added on top
          - "colorants": colorant additions (standard field)

        The parent's base ingredients sum to 100%. Additions are layered on top
        (like colorants) as extra percentages beyond the base 100%.

        Args:
            recipe_data: Dict with parent_glaze, additions, and optional overrides.

        Returns:
            ResolvedInheritance with the fully resolved recipe.
        """
        parent_name = recipe_data.get("parent_glaze")

        if not parent_name:
            raise ValueError("recipe_data must include 'parent_glaze'")

        parent = self._recipe_registry.get(parent_name.lower())
        if not parent:
            raise ValueError(f"Parent recipe '{parent_name}' not found in registry")

        # Inherit parent's ingredients
        inherited = [
            GlazeIngredient(
                material_name=ing.material_name,
                percentage=ing.percentage,
                notes=ing.notes,
            )
            for ing in parent.ingredients
        ]

        # Parse additions
        additions = []
        for add_data in recipe_data.get("additions", []):
            additions.append(GlazeIngredient(
                material_name=add_data.get("material_name", add_data.get("material", "")),
                percentage=add_data.get("percentage", 0.0),
                notes=add_data.get("notes"),
            ))

        # Parse colorants
        colorants = []
        for col_data in recipe_data.get("colorants", []):
            colorants.append(Colorant(
                material_name=col_data.get("material_name", col_data.get("material", "")),
                percentage=col_data.get("percentage", 0.0),
                expected_color=col_data.get("expected_color"),
            ))

        # Build resolved recipe — base ingredients + additions in ingredients list
        all_ingredients = inherited + additions

        recipe = GlazeRecipe(
            name=recipe_data.get("name", f"{parent_name} variation"),
            ingredients=all_ingredients,
            colorants=colorants + list(parent.colorants),
            target_cone=parent.target_cone,
            suitable_atmospheres=list(parent.suitable_atmospheres),
            suitable_clay_bodies=list(parent.suitable_clay_bodies),
            glaze_type=parent.glaze_type,
            expected_surface=parent.expected_surface,
            source=recipe_data.get("source"),
            notes=recipe_data.get("notes"),
        )

        return ResolvedInheritance(
            recipe=recipe,
            parent_name=parent_name,
            additions=additions,
            inherited_ingredients=inherited,
        )

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

    def calculate_dual_umf(
        self,
        recipe: GlazeRecipe,
        surface_concentration: float = 0.8,
    ) -> Optional[DualUMFResult]:
        """Calculate dual UMF for recipes with soluble materials.

        Soluble materials (Soda Ash, Pearl Ash) dissolve in water and migrate
        to the surface during drying. This models the resulting body vs surface
        chemistry split.

        Args:
            recipe: Glaze recipe.
            surface_concentration: Fraction of soluble flux that migrates to
                surface (0.0-1.0). Default 0.8 — most migrates but not all.

        Returns:
            DualUMFResult if recipe contains soluble materials, None otherwise.
        """
        # Identify soluble ingredients
        soluble_ingredients = []
        insoluble_ingredients = []

        for ingredient in recipe.ingredients:
            material = self.materials_db.get(ingredient.material_name)
            if not material:
                insoluble_ingredients.append(ingredient)
                continue

            if material.soluble:
                soluble_ingredients.append((ingredient, material))
            else:
                insoluble_ingredients.append(ingredient)

        if not soluble_ingredients:
            return None

        # Calculate nominal (standard) UMF — everything mixed evenly
        nominal_analysis = self.calculate_recipe_analysis(recipe)
        nominal_umf = UMF.from_oxide_analysis(nominal_analysis)

        # Build body analysis: insoluble materials + reduced soluble contribution
        body_analysis = OxideAnalysis()
        surface_analysis = OxideAnalysis()

        oxides = [
            "SiO2", "Al2O3", "B2O3", "Na2O", "K2O", "Li2O",
            "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO",
            "Fe2O3", "FeO", "TiO2", "MnO", "CuO", "CoO",
            "Cr2O3", "NiO", "ZrO2", "SnO2", "P2O5"
        ]

        # Add insoluble materials fully to both body and surface
        for ingredient in insoluble_ingredients:
            material = self.materials_db.get(ingredient.material_name)
            if not material:
                continue
            factor = ingredient.percentage / 100.0
            analysis = material.analysis.oxide_analysis
            for oxide in oxides:
                val = getattr(analysis, oxide) * factor
                setattr(body_analysis, oxide, getattr(body_analysis, oxide) + val)
                setattr(surface_analysis, oxide, getattr(surface_analysis, oxide) + val)

        # Split soluble materials between body and surface
        soluble_names = []
        for ingredient, material in soluble_ingredients:
            soluble_names.append(material.name)
            factor = ingredient.percentage / 100.0
            analysis = material.analysis.oxide_analysis

            body_fraction = 1.0 - surface_concentration
            for oxide in oxides:
                val = getattr(analysis, oxide) * factor
                # Body gets the non-migrated portion
                setattr(body_analysis, oxide,
                        getattr(body_analysis, oxide) + val * body_fraction)
                # Surface gets the concentrated portion
                setattr(surface_analysis, oxide,
                        getattr(surface_analysis, oxide) + val * surface_concentration)

        body_umf = UMF.from_oxide_analysis(body_analysis)
        surface_umf = UMF.from_oxide_analysis(surface_analysis)

        # Calculate soluble fraction of total flux
        total_flux_moles = 0.0
        soluble_flux_moles = 0.0
        flux_oxides = ["Na2O", "K2O", "Li2O", "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO"]

        for ingredient in recipe.ingredients:
            material = self.materials_db.get(ingredient.material_name)
            if not material:
                continue
            factor = ingredient.percentage / 100.0
            for oxide in flux_oxides:
                wt_pct = getattr(material.analysis.oxide_analysis, oxide) * factor
                mol_wt = OXIDE_MOLECULAR_WEIGHTS.get(oxide, 1.0)
                moles = wt_pct / mol_wt
                total_flux_moles += moles
                if material.soluble:
                    soluble_flux_moles += moles

        soluble_fraction = soluble_flux_moles / total_flux_moles if total_flux_moles > 0 else 0.0

        return DualUMFResult(
            nominal_umf=nominal_umf,
            body_umf=body_umf,
            surface_umf=surface_umf,
            soluble_fraction=soluble_fraction,
            soluble_materials=soluble_names,
        )

    def calculate_ash_accumulation(
        self,
        recipe: GlazeRecipe,
        kiln_position: str,
        ash_composition: Optional[dict[str, float]] = None,
    ) -> AshAccumulationResult:
        """Calculate UMF with virtual ash accumulation based on kiln position.

        In a wood kiln, ash from the firebox travels through the kiln and
        deposits on ware. Pieces near the firebox receive heavy ash deposits
        that act as additional flux, while pieces in the back receive minimal
        ash. This method models that effect by adding virtual ash to the recipe.

        Args:
            recipe: Glaze recipe.
            kiln_position: Position in kiln (firebox, front_to_middle, middle,
                middle_to_back, back, any).
            ash_composition: Custom ash oxide analysis (weight %). Defaults to
                mixed hardwood ash.

        Returns:
            AshAccumulationResult with base and ash-modified UMF.
        """
        ash_comp = ash_composition or VIRTUAL_ASH_COMPOSITION
        multiplier = KILN_POSITION_ASH_MULTIPLIERS.get(kiln_position, 0.05)

        # Calculate base analysis (no ash)
        base_analysis = self.calculate_recipe_analysis(recipe)
        base_umf = UMF.from_oxide_analysis(base_analysis)

        # Add virtual ash: multiply ash composition by position multiplier
        # and add to the base analysis
        modified_analysis = OxideAnalysis()
        oxides = [
            "SiO2", "Al2O3", "B2O3", "Na2O", "K2O", "Li2O",
            "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO",
            "Fe2O3", "FeO", "TiO2", "MnO", "CuO", "CoO",
            "Cr2O3", "NiO", "ZrO2", "SnO2", "P2O5"
        ]

        for oxide in oxides:
            base_val = getattr(base_analysis, oxide)
            ash_val = ash_comp.get(oxide, 0.0) * multiplier
            setattr(modified_analysis, oxide, base_val + ash_val)

        ash_modified_umf = UMF.from_oxide_analysis(modified_analysis)

        return AshAccumulationResult(
            base_umf=base_umf,
            ash_modified_umf=ash_modified_umf,
            kiln_position=kiln_position,
            ash_addition_pct=round(multiplier * 100, 1),
            ash_composition=ash_comp,
        )

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

        Uses scipy SLSQP optimization to find material percentages
        that produce a UMF within the target ranges derived from
        cone, surface, atmosphere, and category descriptors.

        Args:
            target: Target UMF and properties.
            available_materials: List of material names to use (None = all).

        Returns:
            FormulationResult with generated recipe.
        """
        # Resolve descriptors into solver targets
        cone_str = target.cone.value if isinstance(target.cone, ConeTemperature) else str(target.cone)
        surface_str = target.surface.value if isinstance(target.surface, GlazeSurface) else str(target.surface)
        atmosphere_str = target.atmosphere or "oxidation"

        solver_target = self._target_resolver.resolve(
            cone=cone_str,
            surface=surface_str,
            atmosphere=atmosphere_str,
            category=target.category,
            colorants=target.colorants,
        )

        # Get candidate materials
        if available_materials:
            all_materials = [
                self.materials_db.get(name)
                for name in available_materials
                if self.materials_db.get(name)
            ]
        else:
            all_materials = self.materials_db.get_all()

        # Filter out discontinued/restricted materials
        if self.substitution_service:
            from .substitution_service import AvailabilityStatus
            filtered = []
            for m in all_materials:
                status = self.substitution_service.get_status(m.name)
                if status in (None, AvailabilityStatus.AVAILABLE,
                              AvailabilityStatus.LIMITED, AvailabilityStatus.EXPENSIVE,
                              AvailabilityStatus.VARIABLE):
                    filtered.append(m)
            all_materials = filtered

        if not all_materials:
            raise ValueError("No materials available for formulation")

        # Select candidates and solve
        candidates = self._solver.select_candidates(all_materials, solver_target)
        result = self._solver.solve(solver_target, candidates)

        # Build recipe from solver result
        ingredients = [
            GlazeIngredient(material_name=name, percentage=pct)
            for name, pct in result.ingredients
        ]

        colorants = [
            Colorant(
                material_name=c.material_name,
                percentage=c.percentage,
            )
            for c in solver_target.colorant_additions
        ]

        # Build recipe name
        category_label = target.category.replace("_", " ").title() if target.category else ""
        surface_label = surface_str.replace("_", " ").title()
        name = f"Generated {category_label} {surface_label} Base — Cone {cone_str}".strip()
        name = " ".join(name.split())  # collapse double spaces

        recipe = GlazeRecipe(
            name=name,
            ingredients=ingredients,
            colorants=colorants,
            target_cone=target.cone,
            glaze_type=GlazeType.BASE,
            expected_surface=target.surface,
        )

        # Calculate achieved UMF using our own analysis (authoritative)
        achieved_umf = self.calculate_umf(recipe)
        recipe.umf = achieved_umf

        # Generate suggestions: resolver warnings first, then out-of-range oxides
        suggestions = list(solver_target.warnings)
        for oxide, fit in result.target_fit.items():
            if not fit["in_range"]:
                suggestions.append(
                    f"{oxide} is {fit['achieved']:.3f}, target [{fit['min']:.3f}-{fit['max']:.3f}]"
                )
        if solver_target.notes:
            suggestions.append(solver_target.notes)

        return FormulationResult(
            recipe=recipe,
            achieved_umf=achieved_umf,
            deviation_score=result.deviation_score,
            suggestions=suggestions,
            target_fit=result.target_fit,
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
