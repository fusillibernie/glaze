"""Ceramic materials data models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MaterialType(Enum):
    """Types of ceramic materials."""
    FELDSPAR = "feldspar"
    CLAY = "clay"
    SILICA = "silica"
    CALCIUM = "calcium"  # Calcium sources (whiting, wollastonite, etc.)
    MAGNESIUM = "magnesium"  # Magnesium sources (talc, dolomite)
    BORON = "boron"  # Boron sources (Gerstley borate, frits)
    ALUMINA = "alumina"  # Alumina sources
    FLUX = "flux"
    COLORANT = "colorant"
    OPACIFIER = "opacifier"
    FRIT = "frit"
    ASH = "ash"
    STAIN = "stain"
    OTHER = "other"


class MaterialCategory(Enum):
    """Material categories by function."""
    GLASS_FORMER = "glass_former"  # SiO2, B2O3
    FLUX = "flux"  # Na2O, K2O, Li2O, CaO, MgO, etc.
    STABILIZER = "stabilizer"  # Al2O3
    COLORANT = "colorant"  # Fe2O3, CuO, CoO, etc.
    OPACIFIER = "opacifier"  # TiO2, ZrO2, SnO2
    MODIFIER = "modifier"  # Various effects


@dataclass
class OxideAnalysis:
    """Oxide composition of a material (weight %)."""
    SiO2: float = 0.0
    Al2O3: float = 0.0
    B2O3: float = 0.0

    # Fluxes (RO/R2O)
    Na2O: float = 0.0
    K2O: float = 0.0
    Li2O: float = 0.0
    CaO: float = 0.0
    MgO: float = 0.0
    BaO: float = 0.0
    SrO: float = 0.0
    ZnO: float = 0.0
    PbO: float = 0.0  # Lead - avoid in food-safe glazes

    # Colorants/Others
    Fe2O3: float = 0.0
    FeO: float = 0.0
    TiO2: float = 0.0
    MnO: float = 0.0
    MnO2: float = 0.0
    CuO: float = 0.0
    CoO: float = 0.0
    Cr2O3: float = 0.0
    NiO: float = 0.0
    V2O5: float = 0.0
    ZrO2: float = 0.0
    SnO2: float = 0.0
    P2O5: float = 0.0
    F: float = 0.0

    # Loss on ignition
    LOI: float = 0.0

    def total(self) -> float:
        """Calculate total oxide percentage."""
        return (
            self.SiO2 + self.Al2O3 + self.B2O3 +
            self.Na2O + self.K2O + self.Li2O +
            self.CaO + self.MgO + self.BaO + self.SrO + self.ZnO + self.PbO +
            self.Fe2O3 + self.FeO + self.TiO2 + self.MnO + self.MnO2 +
            self.CuO + self.CoO + self.Cr2O3 + self.NiO + self.V2O5 +
            self.ZrO2 + self.SnO2 + self.P2O5 + self.F + self.LOI
        )

    def to_dict(self) -> dict:
        """Convert to dictionary, excluding zero values."""
        result = {}
        for oxide in [
            "SiO2", "Al2O3", "B2O3", "Na2O", "K2O", "Li2O",
            "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO",
            "Fe2O3", "FeO", "TiO2", "MnO", "MnO2",
            "CuO", "CoO", "Cr2O3", "NiO", "V2O5",
            "ZrO2", "SnO2", "P2O5", "F", "LOI"
        ]:
            value = getattr(self, oxide)
            if value > 0:
                result[oxide] = value
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "OxideAnalysis":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


@dataclass
class MaterialAnalysis:
    """Full analysis of a ceramic material."""
    oxide_analysis: OxideAnalysis
    molecular_weight: Optional[float] = None
    ite_ratio: Optional[float] = None  # For feldspars
    source: Optional[str] = None  # Data source (Glazy, supplier, etc.)


@dataclass
class Material:
    """A ceramic raw material."""
    name: str
    material_type: MaterialType
    analysis: MaterialAnalysis

    # Identifiers
    glazy_id: Optional[int] = None
    alternate_names: list[str] = field(default_factory=list)

    # Supplier info
    supplier: Optional[str] = None
    product_code: Optional[str] = None

    # Physical properties
    mesh_size: Optional[int] = None  # Typical mesh
    specific_gravity: Optional[float] = None

    # Usage info
    typical_percentage_min: Optional[float] = None
    typical_percentage_max: Optional[float] = None

    # Notes
    description: Optional[str] = None
    substitutes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "material_type": self.material_type.value,
            "analysis": {
                "oxide_analysis": self.analysis.oxide_analysis.to_dict(),
                "molecular_weight": self.analysis.molecular_weight,
                "source": self.analysis.source,
            },
            "glazy_id": self.glazy_id,
            "alternate_names": self.alternate_names,
            "supplier": self.supplier,
            "product_code": self.product_code,
            "mesh_size": self.mesh_size,
            "specific_gravity": self.specific_gravity,
            "typical_percentage_min": self.typical_percentage_min,
            "typical_percentage_max": self.typical_percentage_max,
            "description": self.description,
            "substitutes": self.substitutes,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Material":
        """Create from dictionary.

        Handles both full format and simplified JSON format:
        - Full: {"material_type": "...", "analysis": {"oxide_analysis": {...}}}
        - Simple: {"type": "...", "analysis": {"SiO2": ..., "Al2O3": ...}}
        """
        # Handle type field (can be "type" or "material_type")
        mat_type_str = data.get("material_type") or data.get("type", "other")
        try:
            mat_type = MaterialType(mat_type_str)
        except ValueError:
            mat_type = MaterialType.OTHER

        # Handle analysis - can be nested or flat
        analysis_data = data.get("analysis", {})
        if "oxide_analysis" in analysis_data:
            # Full format
            oxide_data = analysis_data.get("oxide_analysis", {})
        else:
            # Simple format - analysis IS the oxide data
            oxide_data = analysis_data

        return cls(
            name=data.get("name", ""),
            material_type=mat_type,
            analysis=MaterialAnalysis(
                oxide_analysis=OxideAnalysis.from_dict(oxide_data),
                molecular_weight=analysis_data.get("molecular_weight") if "oxide_analysis" in analysis_data else None,
                source=analysis_data.get("source") if "oxide_analysis" in analysis_data else None,
            ),
            glazy_id=data.get("glazy_id"),
            alternate_names=data.get("alternate_names", []),
            supplier=data.get("supplier"),
            product_code=data.get("product_code"),
            mesh_size=data.get("mesh_size"),
            specific_gravity=data.get("specific_gravity"),
            typical_percentage_min=data.get("typical_percentage_min"),
            typical_percentage_max=data.get("typical_percentage_max"),
            description=data.get("description"),
            substitutes=data.get("substitutes", []),
            warnings=data.get("warnings", []),
        )


# Molecular weights of common oxides
OXIDE_MOLECULAR_WEIGHTS = {
    "SiO2": 60.08,
    "Al2O3": 101.96,
    "B2O3": 69.62,
    "Na2O": 61.98,
    "K2O": 94.20,
    "Li2O": 29.88,
    "CaO": 56.08,
    "MgO": 40.30,
    "BaO": 153.33,
    "SrO": 103.62,
    "ZnO": 81.38,
    "PbO": 223.20,
    "Fe2O3": 159.69,
    "FeO": 71.85,
    "TiO2": 79.87,
    "MnO": 70.94,
    "MnO2": 86.94,
    "CuO": 79.55,
    "CoO": 74.93,
    "Cr2O3": 151.99,
    "NiO": 74.69,
    "V2O5": 181.88,
    "ZrO2": 123.22,
    "SnO2": 150.71,
    "P2O5": 141.94,
}
