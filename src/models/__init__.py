"""Data models for ceramic glaze formulation."""

from .materials import (
    Material,
    MaterialType,
    MaterialCategory,
    MaterialFunction,
    MaterialAnalysis,
    OxideAnalysis,
    OXIDE_MOLECULAR_WEIGHTS,
    MATERIAL_FUNCTION_INFO,
    MATERIAL_USAGE_GUIDELINES,
)
from .glaze import (
    Glaze,
    GlazeRecipe,
    GlazeIngredient,
    Colorant,
    FiringSchedule,
    ConeTemperature,
    AtmosphereType,
    FiringType,
    ClayBody,
    GlazeSurface,
    GlazeType,
)
from .umf import UMF, OxideGroup, StullPoint, get_umf_ranges
from .results import (
    FiringResult,
    ResultPhoto,
    SurfaceQuality,
    GlazeDefect,
    ColorDescription,
)

__all__ = [
    # Materials
    "Material",
    "MaterialType",
    "MaterialAnalysis",
    "OxideAnalysis",
    "OXIDE_MOLECULAR_WEIGHTS",
    # Glaze
    "Glaze",
    "GlazeRecipe",
    "GlazeIngredient",
    "Colorant",
    "FiringSchedule",
    "ConeTemperature",
    "AtmosphereType",
    "FiringType",
    "ClayBody",
    "GlazeSurface",
    "GlazeType",
    # UMF
    "UMF",
    "OxideGroup",
    "StullPoint",
    "get_umf_ranges",
    # Results
    "FiringResult",
    "ResultPhoto",
    "SurfaceQuality",
    "GlazeDefect",
    "ColorDescription",
]
