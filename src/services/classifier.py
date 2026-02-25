"""Glaze classification and search based on Stull chart regions."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..models.glaze import GlazeRecipe, GlazeSurface, ConeTemperature, AtmosphereType
from ..models.umf import UMF


class StullRegion(Enum):
    """Regions on the Stull Chart based on Al2O3 and SiO2."""
    # Main regions
    GLOSSY = "glossy"
    SATIN = "satin"
    MATTE = "matte"
    DRY_MATTE = "dry_matte"

    # Edge regions
    RUNNY = "runny"  # Low alumina, likely to run
    UNDERFIRED = "underfired"  # Very low alumina
    STIFF = "stiff"  # High alumina, won't melt properly

    # Special regions
    CRYSTALLINE_ZONE = "crystalline_zone"  # Favorable for crystal growth


class GlazeCategory(Enum):
    """Functional categories for glazes."""
    # By surface
    CLEAR_GLOSSY = "clear_glossy"
    COLORED_GLOSSY = "colored_glossy"
    SATIN_MATTE = "satin_matte"
    TRUE_MATTE = "true_matte"
    CRYSTALLINE = "crystalline"

    # By effect
    BREAKING = "breaking"  # Color breaks over texture
    RUTILE_BLUE = "rutile_blue"
    ASH_GLAZE = "ash_glaze"
    CARBON_TRAP = "carbon_trap"
    SHINO = "shino"
    TENMOKU = "tenmoku"
    CELADON = "celadon"
    OILSPOT = "oilspot"
    CHUN = "chun"  # Jun/Chun opalescent

    # By function
    LINER = "liner"  # Food-safe liner
    CRAWL = "crawl"  # Intentional crawling effect

    # Catch-all
    OTHER = "other"


@dataclass
class StullCoordinates:
    """Position on the Stull Chart with region classification."""
    al2o3: float
    sio2: float
    region: StullRegion
    si_al_ratio: float

    @property
    def is_stable(self) -> bool:
        """Check if position is in a stable firing region."""
        return self.region not in [
            StullRegion.RUNNY,
            StullRegion.UNDERFIRED,
            StullRegion.STIFF,
        ]

    def distance_to(self, other: "StullCoordinates") -> float:
        """Calculate Euclidean distance to another point."""
        return ((self.al2o3 - other.al2o3) ** 2 +
                (self.sio2 - other.sio2) ** 2) ** 0.5


@dataclass
class GlazeClassification:
    """Complete classification of a glaze recipe."""
    recipe_name: str
    stull: StullCoordinates
    category: GlazeCategory
    sub_categories: list[str] = field(default_factory=list)

    # Flux analysis
    alkali_dominant: bool = False  # High Na2O/K2O
    alkaline_earth_dominant: bool = False  # High CaO/MgO
    zinc_present: bool = False
    boron_present: bool = False
    barium_present: bool = False

    # Colorant analysis
    is_iron_glaze: bool = False
    is_copper_glaze: bool = False
    is_cobalt_glaze: bool = False
    colorant_notes: Optional[str] = None

    # Safety
    food_safe: bool = True
    warnings: list[str] = field(default_factory=list)

    # Similar glazes (to be filled by search)
    similar_glazes: list[str] = field(default_factory=list)


class GlazeClassifier:
    """Classify and search glazes based on composition."""

    # Stull Chart boundary definitions (for cone 6-10)
    STULL_BOUNDARIES = {
        "al2o3_min_stable": 0.15,
        "al2o3_max_stable": 0.65,
        "al2o3_matte_threshold": 0.45,
        "si_al_glossy_min": 8.0,
        "si_al_glossy_max": 12.0,
        "si_al_satin_min": 6.0,
        "si_al_satin_max": 8.0,
        "si_al_matte_max": 6.0,
    }

    def __init__(self):
        """Initialize classifier."""
        self._recipe_index: dict[str, GlazeClassification] = {}
        self._by_region: dict[StullRegion, list[str]] = {r: [] for r in StullRegion}
        self._by_category: dict[GlazeCategory, list[str]] = {c: [] for c in GlazeCategory}

    def classify(self, recipe: GlazeRecipe) -> GlazeClassification:
        """Classify a glaze recipe.

        Args:
            recipe: Glaze recipe with calculated UMF.

        Returns:
            GlazeClassification with full analysis.
        """
        if not recipe.umf:
            raise ValueError("Recipe must have UMF calculated")

        umf = recipe.umf

        # Determine Stull position and region
        stull = self._get_stull_coordinates(umf)

        # Determine category
        category = self._determine_category(recipe, stull)

        # Analyze flux composition
        alkali_dom = umf.alkali_ratio > 0.4
        ae_dom = (umf.CaO + umf.MgO) / umf.flux_total > 0.5 if umf.flux_total > 0 else False

        # Check for special fluxes
        zinc_present = umf.ZnO > 0.05
        boron_present = umf.B2O3 > 0.1
        barium_present = umf.BaO > 0.05

        # Analyze colorants
        is_iron = umf.Fe2O3 > 0.02 or self._has_iron_colorant(recipe)
        is_copper = self._has_copper_colorant(recipe)
        is_cobalt = self._has_cobalt_colorant(recipe)

        colorant_notes = self._get_colorant_notes(recipe, umf)

        # Safety analysis
        food_safe = True
        warnings = []

        if umf.PbO > 0:
            food_safe = False
            warnings.append("Contains lead - NOT food safe")

        if umf.BaO > 0.1:
            food_safe = False
            warnings.append("High barium content - NOT food safe")

        # Note: CdO (cadmium) is not tracked in the UMF model
        # Cadmium is typically in colorants/stains, not base glaze chemistry

        # Identify sub-categories
        sub_cats = self._get_sub_categories(recipe, umf, stull)

        classification = GlazeClassification(
            recipe_name=recipe.name,
            stull=stull,
            category=category,
            sub_categories=sub_cats,
            alkali_dominant=alkali_dom,
            alkaline_earth_dominant=ae_dom,
            zinc_present=zinc_present,
            boron_present=boron_present,
            barium_present=barium_present,
            is_iron_glaze=is_iron,
            is_copper_glaze=is_copper,
            is_cobalt_glaze=is_cobalt,
            colorant_notes=colorant_notes,
            food_safe=food_safe,
            warnings=warnings,
        )

        # Index for search
        self._index_recipe(recipe.name, classification)

        return classification

    def _get_stull_coordinates(self, umf: UMF) -> StullCoordinates:
        """Get Stull chart coordinates and region."""
        al2o3 = umf.Al2O3
        sio2 = umf.SiO2
        ratio = sio2 / al2o3 if al2o3 > 0 else float('inf')

        # Determine region
        if al2o3 < self.STULL_BOUNDARIES["al2o3_min_stable"]:
            region = StullRegion.UNDERFIRED
        elif al2o3 > self.STULL_BOUNDARIES["al2o3_max_stable"]:
            region = StullRegion.STIFF
        elif ratio > 12:
            region = StullRegion.RUNNY
        elif ratio >= self.STULL_BOUNDARIES["si_al_glossy_min"]:
            region = StullRegion.GLOSSY
        elif ratio >= self.STULL_BOUNDARIES["si_al_satin_min"]:
            region = StullRegion.SATIN
        elif al2o3 > self.STULL_BOUNDARIES["al2o3_matte_threshold"]:
            region = StullRegion.DRY_MATTE
        else:
            region = StullRegion.MATTE

        # Check for crystalline zone (low alumina with zinc/titanium)
        if 0.15 <= al2o3 <= 0.25 and ratio > 10:
            region = StullRegion.CRYSTALLINE_ZONE

        return StullCoordinates(
            al2o3=al2o3,
            sio2=sio2,
            region=region,
            si_al_ratio=ratio if ratio != float('inf') else 99.9,
        )

    def _determine_category(
        self,
        recipe: GlazeRecipe,
        stull: StullCoordinates,
    ) -> GlazeCategory:
        """Determine the primary category for a glaze."""
        name_lower = recipe.name.lower()

        # Check name-based categories first
        if "celadon" in name_lower:
            return GlazeCategory.CELADON
        if "shino" in name_lower:
            return GlazeCategory.SHINO
        if "tenmoku" in name_lower or "temmoku" in name_lower:
            return GlazeCategory.TENMOKU
        if "ash" in name_lower:
            return GlazeCategory.ASH_GLAZE
        if "crystalline" in name_lower:
            return GlazeCategory.CRYSTALLINE
        if "oilspot" in name_lower or "oil spot" in name_lower:
            return GlazeCategory.OILSPOT
        if "chun" in name_lower or "jun" in name_lower:
            return GlazeCategory.CHUN
        if "rutile" in name_lower and "blue" in name_lower:
            return GlazeCategory.RUTILE_BLUE
        if "crawl" in name_lower:
            return GlazeCategory.CRAWL
        if "liner" in name_lower or "clear" in name_lower:
            return GlazeCategory.CLEAR_GLOSSY
        if "breaking" in name_lower or "float" in name_lower:
            return GlazeCategory.BREAKING

        # Otherwise, categorize by surface
        if stull.region == StullRegion.CRYSTALLINE_ZONE:
            return GlazeCategory.CRYSTALLINE
        elif stull.region == StullRegion.GLOSSY:
            if len(recipe.colorants) > 0:
                return GlazeCategory.COLORED_GLOSSY
            return GlazeCategory.CLEAR_GLOSSY
        elif stull.region == StullRegion.SATIN:
            return GlazeCategory.SATIN_MATTE
        elif stull.region in [StullRegion.MATTE, StullRegion.DRY_MATTE]:
            return GlazeCategory.TRUE_MATTE
        else:
            return GlazeCategory.OTHER

    def _has_iron_colorant(self, recipe: GlazeRecipe) -> bool:
        """Check if recipe has iron colorant."""
        for c in recipe.colorants:
            if "iron" in c.material_name.lower() or "fe" in c.material_name.lower():
                return True
        return False

    def _has_copper_colorant(self, recipe: GlazeRecipe) -> bool:
        """Check if recipe has copper colorant."""
        for c in recipe.colorants:
            if "copper" in c.material_name.lower() or "cu" in c.material_name.lower():
                return True
        return False

    def _has_cobalt_colorant(self, recipe: GlazeRecipe) -> bool:
        """Check if recipe has cobalt colorant."""
        for c in recipe.colorants:
            if "cobalt" in c.material_name.lower() or "co" in c.material_name.lower():
                return True
        return False

    def _get_colorant_notes(self, recipe: GlazeRecipe, umf: UMF) -> Optional[str]:
        """Generate notes about colorants."""
        notes = []

        if umf.Fe2O3 > 0.05:
            notes.append(f"Iron content: {umf.Fe2O3:.2f} mol")

        for c in recipe.colorants:
            name = c.material_name.lower()
            pct = c.percentage
            if "cobalt" in name:
                notes.append(f"Cobalt {pct}% - expect strong blue")
            elif "copper" in name:
                notes.append(f"Copper {pct}% - green/turquoise in oxidation, red in reduction")
            elif "iron" in name:
                if pct < 3:
                    notes.append(f"Iron {pct}% - light amber/celadon tones")
                elif pct < 8:
                    notes.append(f"Iron {pct}% - medium brown/amber")
                else:
                    notes.append(f"Iron {pct}% - tenmoku range")
            elif "rutile" in name:
                notes.append(f"Rutile {pct}% - tan/cream with crystalline effects")
            elif "manganese" in name:
                notes.append(f"Manganese {pct}% - purple-brown tones")

        return "; ".join(notes) if notes else None

    def _get_sub_categories(
        self,
        recipe: GlazeRecipe,
        umf: UMF,
        stull: StullCoordinates,
    ) -> list[str]:
        """Get additional sub-categories/tags for the glaze."""
        tags = []

        # Temperature range
        if recipe.target_cone in [ConeTemperature.CONE_9, ConeTemperature.CONE_10,
                                   ConeTemperature.CONE_11, ConeTemperature.CONE_12]:
            tags.append("high_fire")
        elif recipe.target_cone in [ConeTemperature.CONE_5, ConeTemperature.CONE_6,
                                     ConeTemperature.CONE_7]:
            tags.append("mid_fire")
        else:
            tags.append("low_fire")

        # Atmosphere
        for atm in recipe.suitable_atmospheres:
            if atm == AtmosphereType.REDUCTION:
                tags.append("reduction")
            elif atm == AtmosphereType.OXIDATION:
                tags.append("oxidation")
            elif atm == AtmosphereType.WOOD:
                tags.append("wood_fire")

        # Flux characteristics
        if umf.B2O3 > 0.2:
            tags.append("boron_flux")
        if umf.ZnO > 0.1:
            tags.append("zinc_flux")
        if umf.Li2O > 0.05:
            tags.append("lithium_flux")

        # Special effects potential
        if umf.TiO2 > 0.03:
            tags.append("titanium_effects")
        if stull.si_al_ratio > 10 and umf.ZnO > 0.1:
            tags.append("crystalline_potential")

        return tags

    def _index_recipe(self, name: str, classification: GlazeClassification) -> None:
        """Index a recipe for search."""
        self._recipe_index[name.lower()] = classification
        self._by_region[classification.stull.region].append(name)
        self._by_category[classification.category].append(name)

    def search_by_region(self, region: StullRegion) -> list[str]:
        """Find all glazes in a Stull region."""
        return self._by_region.get(region, [])

    def search_by_category(self, category: GlazeCategory) -> list[str]:
        """Find all glazes in a category."""
        return self._by_category.get(category, [])

    def search_similar(
        self,
        recipe: GlazeRecipe,
        max_distance: float = 0.3,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Find glazes with similar Stull coordinates.

        Args:
            recipe: Reference recipe.
            max_distance: Maximum Stull distance to consider similar.
            limit: Maximum results to return.

        Returns:
            List of (recipe_name, distance) tuples sorted by distance.
        """
        if not recipe.umf:
            return []

        ref_stull = self._get_stull_coordinates(recipe.umf)
        similar = []

        for name, classification in self._recipe_index.items():
            if name.lower() == recipe.name.lower():
                continue

            dist = ref_stull.distance_to(classification.stull)
            if dist <= max_distance:
                similar.append((name, dist))

        similar.sort(key=lambda x: x[1])
        return similar[:limit]

    def search_by_umf_range(
        self,
        sio2_min: float = 0,
        sio2_max: float = 10,
        al2o3_min: float = 0,
        al2o3_max: float = 1,
    ) -> list[str]:
        """Find glazes within UMF ranges.

        Args:
            sio2_min: Minimum SiO2 value.
            sio2_max: Maximum SiO2 value.
            al2o3_min: Minimum Al2O3 value.
            al2o3_max: Maximum Al2O3 value.

        Returns:
            List of matching recipe names.
        """
        matches = []

        for name, classification in self._recipe_index.items():
            stull = classification.stull
            if (sio2_min <= stull.sio2 <= sio2_max and
                al2o3_min <= stull.al2o3 <= al2o3_max):
                matches.append(name)

        return matches

    def search_by_flux_profile(
        self,
        alkali_dominant: Optional[bool] = None,
        zinc_required: bool = False,
        boron_required: bool = False,
        barium_allowed: bool = True,
    ) -> list[str]:
        """Find glazes by flux composition.

        Args:
            alkali_dominant: If True, find high-alkali glazes.
            zinc_required: Require zinc in the flux.
            boron_required: Require boron flux.
            barium_allowed: If False, exclude barium glazes.

        Returns:
            List of matching recipe names.
        """
        matches = []

        for name, classification in self._recipe_index.items():
            if alkali_dominant is not None:
                if classification.alkali_dominant != alkali_dominant:
                    continue

            if zinc_required and not classification.zinc_present:
                continue

            if boron_required and not classification.boron_present:
                continue

            if not barium_allowed and classification.barium_present:
                continue

            matches.append(name)

        return matches

    def get_classification(self, recipe_name: str) -> Optional[GlazeClassification]:
        """Get classification for a recipe by name."""
        return self._recipe_index.get(recipe_name.lower())

    def get_statistics(self) -> dict:
        """Get statistics about indexed glazes."""
        return {
            "total_indexed": len(self._recipe_index),
            "by_region": {r.value: len(names) for r, names in self._by_region.items()},
            "by_category": {c.value: len(names) for c, names in self._by_category.items()},
        }
