"""Glaze recipe and firing data models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .umf import UMF


class ConeTemperature(Enum):
    """Standard pyrometric cone temperatures."""
    CONE_06 = "06"  # ~999°C / 1830°F (low fire)
    CONE_04 = "04"  # ~1060°C / 1940°F
    CONE_02 = "02"  # ~1120°C / 2048°F
    CONE_1 = "1"    # ~1136°C / 2077°F
    CONE_3 = "3"    # ~1168°C / 2134°F
    CONE_5 = "5"    # ~1196°C / 2185°F
    CONE_6 = "6"    # ~1222°C / 2232°F (mid fire)
    CONE_7 = "7"    # ~1240°C / 2264°F
    CONE_8 = "8"    # ~1263°C / 2305°F
    CONE_9 = "9"    # ~1280°C / 2336°F
    CONE_10 = "10"  # ~1305°C / 2381°F (high fire)
    CONE_11 = "11"  # ~1315°C / 2399°F
    CONE_12 = "12"  # ~1326°C / 2419°F


class AtmosphereType(Enum):
    """Kiln atmosphere during firing."""
    OXIDATION = "oxidation"  # Electric kilns, clean gas firing
    REDUCTION = "reduction"  # Gas/wood with limited oxygen
    NEUTRAL = "neutral"      # Balanced atmosphere
    HEAVY_REDUCTION = "heavy_reduction"  # Strong reduction
    LIGHT_REDUCTION = "light_reduction"
    WOOD = "wood"            # Wood firing with ash
    SALT = "salt"            # Salt glazing atmosphere
    SODA = "soda"            # Soda firing atmosphere


class FiringType(Enum):
    """Type of kiln/fuel source."""
    ELECTRIC = "electric"
    GAS_NATURAL = "gas_natural"
    GAS_PROPANE = "gas_propane"
    WOOD = "wood"
    WOOD_SALT = "wood_salt"
    WOOD_SODA = "wood_soda"
    RAKU = "raku"
    PIT_FIRE = "pit_fire"
    SAGGAR = "saggar"


class ClayBody(Enum):
    """Common clay body types."""
    STONEWARE = "stoneware"
    PORCELAIN = "porcelain"
    EARTHENWARE = "earthenware"
    TERRACOTTA = "terracotta"
    BONE_CHINA = "bone_china"
    PAPERCLAY = "paperclay"
    RAKU_BODY = "raku_body"
    SCULPTURE_BODY = "sculpture_body"


class GlazeSurface(Enum):
    """Glaze surface types."""
    GLOSSY = "glossy"
    SATIN = "satin"
    MATTE = "matte"
    DRY_MATTE = "dry_matte"
    CRYSTALLINE = "crystalline"
    CRAWLING = "crawling"
    TEXTURED = "textured"


class GlazeType(Enum):
    """Classification of glaze types."""
    BASE = "base"  # Foundation glaze
    LINER = "liner"  # Food-safe interior
    CELADON = "celadon"
    SHINO = "shino"
    TENMOKU = "tenmoku"
    ASH = "ash"
    CARBON_TRAP = "carbon_trap"
    CRYSTALLINE = "crystalline"
    MAJOLICA = "majolica"
    SLIP = "slip"
    ENGOBE = "engobe"
    CRAWL = "crawl"
    OTHER = "other"


@dataclass
class GlazeIngredient:
    """A single ingredient in a glaze recipe."""
    material_name: str
    percentage: float  # Weight percentage (batch %)
    material_id: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "material_name": self.material_name,
            "percentage": self.percentage,
            "material_id": self.material_id,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GlazeIngredient":
        """Create from dictionary."""
        return cls(
            material_name=data.get("material_name", ""),
            percentage=data.get("percentage", 0.0),
            material_id=data.get("material_id"),
            notes=data.get("notes"),
        )


@dataclass
class Colorant:
    """Colorant addition to a glaze (added on top of 100% base)."""
    material_name: str
    percentage: float  # Addition percentage
    expected_color: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "material_name": self.material_name,
            "percentage": self.percentage,
            "expected_color": self.expected_color,
            "notes": self.notes,
        }


@dataclass
class FiringSchedule:
    """Kiln firing schedule."""
    name: Optional[str] = None
    cone: ConeTemperature = ConeTemperature.CONE_6
    atmosphere: AtmosphereType = AtmosphereType.OXIDATION
    firing_type: FiringType = FiringType.ELECTRIC

    # Temperature ramps (simplified)
    peak_temp_c: Optional[int] = None
    hold_time_minutes: int = 0
    cooling_rate: Optional[str] = None  # "slow", "normal", "crash"

    # Reduction timing (for gas/wood)
    reduction_start_temp_c: Optional[int] = None
    reduction_end_temp_c: Optional[int] = None

    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "cone": self.cone.value,
            "atmosphere": self.atmosphere.value,
            "firing_type": self.firing_type.value,
            "peak_temp_c": self.peak_temp_c,
            "hold_time_minutes": self.hold_time_minutes,
            "cooling_rate": self.cooling_rate,
            "reduction_start_temp_c": self.reduction_start_temp_c,
            "reduction_end_temp_c": self.reduction_end_temp_c,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FiringSchedule":
        """Create from dictionary."""
        return cls(
            name=data.get("name"),
            cone=ConeTemperature(data.get("cone", "6")),
            atmosphere=AtmosphereType(data.get("atmosphere", "oxidation")),
            firing_type=FiringType(data.get("firing_type", "electric")),
            peak_temp_c=data.get("peak_temp_c"),
            hold_time_minutes=data.get("hold_time_minutes", 0),
            cooling_rate=data.get("cooling_rate"),
            reduction_start_temp_c=data.get("reduction_start_temp_c"),
            reduction_end_temp_c=data.get("reduction_end_temp_c"),
            notes=data.get("notes"),
        )


@dataclass
class GlazeRecipe:
    """A glaze recipe with all components."""
    name: str
    ingredients: list[GlazeIngredient] = field(default_factory=list)
    colorants: list[Colorant] = field(default_factory=list)

    # Target firing
    target_cone: ConeTemperature = ConeTemperature.CONE_6
    suitable_atmospheres: list[AtmosphereType] = field(default_factory=list)
    suitable_clay_bodies: list[ClayBody] = field(default_factory=list)

    # Calculated chemistry
    umf: Optional[UMF] = None

    # Classification
    glaze_type: GlazeType = GlazeType.BASE
    expected_surface: GlazeSurface = GlazeSurface.GLOSSY
    food_safe: bool = False

    # Metadata
    recipe_id: Optional[str] = None
    glazy_id: Optional[int] = None
    source: Optional[str] = None
    author: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    notes: Optional[str] = None

    @property
    def total_percentage(self) -> float:
        """Sum of all ingredient percentages (should be 100)."""
        return sum(ing.percentage for ing in self.ingredients)

    @property
    def colorant_additions(self) -> float:
        """Sum of colorant additions."""
        return sum(c.percentage for c in self.colorants)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "ingredients": [ing.to_dict() for ing in self.ingredients],
            "colorants": [c.to_dict() for c in self.colorants],
            "target_cone": self.target_cone.value,
            "suitable_atmospheres": [a.value for a in self.suitable_atmospheres],
            "suitable_clay_bodies": [c.value for c in self.suitable_clay_bodies],
            "umf": self.umf.to_dict() if self.umf else None,
            "glaze_type": self.glaze_type.value,
            "expected_surface": self.expected_surface.value,
            "food_safe": self.food_safe,
            "recipe_id": self.recipe_id,
            "glazy_id": self.glazy_id,
            "source": self.source,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "notes": self.notes,
        }


@dataclass
class Glaze:
    """A complete glaze with base recipe and variations."""
    name: str
    base_recipe: GlazeRecipe
    variations: list[GlazeRecipe] = field(default_factory=list)

    # Documentation
    description: Optional[str] = None
    application_notes: Optional[str] = None
    thickness_notes: Optional[str] = None

    # Categorization
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "base_recipe": self.base_recipe.to_dict(),
            "variations": [v.to_dict() for v in self.variations],
            "description": self.description,
            "application_notes": self.application_notes,
            "thickness_notes": self.thickness_notes,
            "tags": self.tags,
        }


# Common firing schedules
CONE_6_ELECTRIC = FiringSchedule(
    name="Standard Cone 6 Electric",
    cone=ConeTemperature.CONE_6,
    atmosphere=AtmosphereType.OXIDATION,
    firing_type=FiringType.ELECTRIC,
    peak_temp_c=1222,
    hold_time_minutes=10,
    cooling_rate="normal",
)

CONE_10_REDUCTION = FiringSchedule(
    name="Standard Cone 10 Reduction",
    cone=ConeTemperature.CONE_10,
    atmosphere=AtmosphereType.REDUCTION,
    firing_type=FiringType.GAS_NATURAL,
    peak_temp_c=1305,
    hold_time_minutes=15,
    cooling_rate="slow",
    reduction_start_temp_c=1093,  # ~Cone 06
    reduction_end_temp_c=1305,
)

CONE_10_WOOD = FiringSchedule(
    name="Wood Fire Cone 10",
    cone=ConeTemperature.CONE_10,
    atmosphere=AtmosphereType.REDUCTION,
    firing_type=FiringType.WOOD,
    peak_temp_c=1305,
    hold_time_minutes=30,
    cooling_rate="slow",
    notes="Ash deposits affect surface",
)
