"""Services for glaze formulation and analysis."""

from .formulator import GlazeFormulator
from .analyzer import GlazeAnalyzer
from .predictor import OutcomePredictor
from .materials_db import MaterialsDatabase
from .classifier import GlazeClassifier, StullRegion, GlazeCategory, GlazeClassification
from .substitution_service import (
    SubstitutionService,
    AvailabilityStatus,
    SubstituteType,
    Substitute,
    MaterialSubstitution,
    SubstitutionResult,
)

__all__ = [
    "GlazeFormulator",
    "GlazeAnalyzer",
    "OutcomePredictor",
    "MaterialsDatabase",
    "GlazeClassifier",
    "StullRegion",
    "GlazeCategory",
    "GlazeClassification",
    "SubstitutionService",
    "AvailabilityStatus",
    "SubstituteType",
    "Substitute",
    "MaterialSubstitution",
    "SubstitutionResult",
]
