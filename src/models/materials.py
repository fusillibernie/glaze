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


class MaterialFunction(Enum):
    """Specific functions a material performs in a glaze."""
    # Glass formers
    GLASS_FORMER = "glass_former"
    SECONDARY_GLASS_FORMER = "secondary_glass_former"

    # Fluxes by temperature
    HIGH_TEMP_FLUX = "high_temp_flux"
    MID_TEMP_FLUX = "mid_temp_flux"
    LOW_TEMP_FLUX = "low_temp_flux"

    # Flux types
    ALKALI_FLUX = "alkali_flux"
    ALKALINE_EARTH_FLUX = "alkaline_earth_flux"
    BORON_FLUX = "boron_flux"

    # Stabilizers
    ALUMINA_SOURCE = "alumina_source"
    VISCOSITY_MODIFIER = "viscosity_modifier"

    # Surface effects
    MATTE_PROMOTER = "matte_promoter"
    OPACITY_SOURCE = "opacity_source"
    CRYSTAL_PROMOTER = "crystal_promoter"
    OPALESCENCE = "opalescence"

    # Colorants
    IRON_COLORANT = "iron_colorant"
    COPPER_COLORANT = "copper_colorant"
    COBALT_COLORANT = "cobalt_colorant"
    MANGANESE_COLORANT = "manganese_colorant"
    CHROME_COLORANT = "chrome_colorant"

    # Physical properties
    THERMAL_EXPANSION_REDUCER = "thermal_expansion_reducer"
    SUSPENSION_AID = "suspension_aid"
    PLASTICITY = "plasticity"


# Material function descriptions and usage guidelines
MATERIAL_FUNCTION_INFO = {
    MaterialFunction.GLASS_FORMER: {
        "description": "Primary glass-forming oxide (SiO2). Forms the backbone of the glaze structure.",
        "typical_oxides": ["SiO2"],
        "effect_on_glaze": "Higher amounts increase hardness, durability, and chemical resistance. Too much raises melting temperature.",
    },
    MaterialFunction.SECONDARY_GLASS_FORMER: {
        "description": "Secondary glass former (B2O3). Lowers melting temperature while forming glass.",
        "typical_oxides": ["B2O3"],
        "effect_on_glaze": "Lowers maturing temperature, increases gloss, promotes healing of surface defects.",
    },
    MaterialFunction.HIGH_TEMP_FLUX: {
        "description": "Flux active at high temperatures (cone 8-12). Calcium and magnesium sources.",
        "typical_oxides": ["CaO", "MgO"],
        "effect_on_glaze": "Promotes durability and hardness. CaO is primary high-fire flux.",
    },
    MaterialFunction.MID_TEMP_FLUX: {
        "description": "Flux active at mid-range temperatures (cone 4-7).",
        "typical_oxides": ["CaO", "Na2O", "K2O", "ZnO"],
        "effect_on_glaze": "Balanced melting, good for functional ware.",
    },
    MaterialFunction.LOW_TEMP_FLUX: {
        "description": "Flux active at low temperatures (cone 06-2). Alkalis, boron, lead.",
        "typical_oxides": ["Na2O", "K2O", "Li2O", "B2O3", "PbO"],
        "effect_on_glaze": "Dramatically lowers melting point. Use with care for thermal expansion.",
    },
    MaterialFunction.ALKALI_FLUX: {
        "description": "Alkali oxides (Na2O, K2O, Li2O). Powerful low-temp fluxes with high expansion.",
        "typical_oxides": ["Na2O", "K2O", "Li2O"],
        "effect_on_glaze": "Strong fluxing action but high thermal expansion can cause crazing.",
    },
    MaterialFunction.ALKALINE_EARTH_FLUX: {
        "description": "Alkaline earth oxides (CaO, MgO, BaO, SrO). Moderate fluxes with lower expansion.",
        "typical_oxides": ["CaO", "MgO", "BaO", "SrO"],
        "effect_on_glaze": "CaO promotes durability. MgO promotes matte/buttery surfaces. BaO promotes matte but not food-safe.",
    },
    MaterialFunction.BORON_FLUX: {
        "description": "Boron oxide (B2O3). Acts as both flux and glass former.",
        "typical_oxides": ["B2O3"],
        "effect_on_glaze": "Lowers melting temp, increases gloss, heals crawling. Essential for low-fire glazes.",
    },
    MaterialFunction.ALUMINA_SOURCE: {
        "description": "Alumina (Al2O3) source. Primary stabilizer and viscosity controller.",
        "typical_oxides": ["Al2O3"],
        "effect_on_glaze": "Increases viscosity, prevents running, promotes matte surfaces, increases durability.",
    },
    MaterialFunction.VISCOSITY_MODIFIER: {
        "description": "Modifies melt viscosity to control flow and surface quality.",
        "typical_oxides": ["Al2O3", "SiO2", "MgO"],
        "effect_on_glaze": "Higher alumina = more viscous, less running. Lower alumina = fluid, potential running.",
    },
    MaterialFunction.MATTE_PROMOTER: {
        "description": "Promotes matte or satin surface through crystal formation or high alumina.",
        "typical_oxides": ["Al2O3", "MgO", "BaO", "CaO"],
        "effect_on_glaze": "MgO gives buttery matte. BaO gives dry matte. High Al2O3 gives satin/matte.",
    },
    MaterialFunction.OPACITY_SOURCE: {
        "description": "Creates opacity through crystal formation or light scattering.",
        "typical_oxides": ["TiO2", "ZrO2", "SnO2"],
        "effect_on_glaze": "TiO2 gives cream color. ZrO2 gives white opacity. SnO2 promotes white with less color influence.",
    },
    MaterialFunction.CRYSTAL_PROMOTER: {
        "description": "Promotes crystal growth for visual effects.",
        "typical_oxides": ["ZnO", "TiO2", "MgO"],
        "effect_on_glaze": "ZnO essential for macro crystals. Slow cooling required.",
    },
    MaterialFunction.OPALESCENCE: {
        "description": "Creates opalescent or phosphorescent effects.",
        "typical_oxides": ["P2O5", "CaO"],
        "effect_on_glaze": "Bone ash (calcium phosphate) creates soft opalescent glow.",
    },
    MaterialFunction.THERMAL_EXPANSION_REDUCER: {
        "description": "Reduces thermal expansion coefficient to prevent crazing.",
        "typical_oxides": ["Li2O", "B2O3", "SiO2"],
        "effect_on_glaze": "Lithium has lowest expansion. Boron and silica also help reduce expansion.",
    },
    MaterialFunction.SUSPENSION_AID: {
        "description": "Helps keep glaze materials suspended in water.",
        "typical_oxides": [],
        "effect_on_glaze": "Clay additions (EPK, ball clay) improve suspension and application properties.",
    },
    MaterialFunction.PLASTICITY: {
        "description": "Improves handling and application of raw glaze.",
        "typical_oxides": [],
        "effect_on_glaze": "Bentonite (1-2%) dramatically improves plasticity. Too much causes crawling.",
    },
}


# Usage guidelines by material type
MATERIAL_USAGE_GUIDELINES = {
    MaterialType.FELDSPAR: {
        "typical_min": 15.0,
        "typical_max": 50.0,
        "primary_functions": [MaterialFunction.MID_TEMP_FLUX, MaterialFunction.GLASS_FORMER, MaterialFunction.ALKALI_FLUX],
        "description": "Feldspars are the backbone of most glazes, providing silica, alumina, and fluxes in one material.",
        "notes": "Potash feldspars (K2O-rich) are more refractory than soda feldspars (Na2O-rich).",
    },
    MaterialType.CLAY: {
        "typical_min": 5.0,
        "typical_max": 25.0,
        "primary_functions": [MaterialFunction.ALUMINA_SOURCE, MaterialFunction.SUSPENSION_AID, MaterialFunction.PLASTICITY],
        "description": "Clays provide alumina and help with suspension. Essential for glaze application.",
        "notes": "Kaolins are primary source. Ball clays add plasticity but can darken color. Bentonite 1-2% max.",
    },
    MaterialType.SILICA: {
        "typical_min": 5.0,
        "typical_max": 30.0,
        "primary_functions": [MaterialFunction.GLASS_FORMER],
        "description": "Pure silica (flint/quartz) is the primary glass former. Raises melting point.",
        "notes": "Too much silica raises melting temperature and can cause crawling. Essential for durability.",
    },
    MaterialType.CALCIUM: {
        "typical_min": 5.0,
        "typical_max": 25.0,
        "primary_functions": [MaterialFunction.HIGH_TEMP_FLUX, MaterialFunction.ALKALINE_EARTH_FLUX],
        "description": "Calcium sources (whiting, wollastonite) are primary high-fire fluxes.",
        "notes": "Whiting has high LOI (44%). Wollastonite has no LOI and adds silica, reducing crazing.",
    },
    MaterialType.MAGNESIUM: {
        "typical_min": 2.0,
        "typical_max": 15.0,
        "primary_functions": [MaterialFunction.MATTE_PROMOTER, MaterialFunction.HIGH_TEMP_FLUX],
        "description": "Magnesium sources (talc, dolomite) promote buttery matte surfaces.",
        "notes": "Dolomite provides both CaO and MgO. Talc also adds silica. Best in reduction for buttery surfaces.",
    },
    MaterialType.BORON: {
        "typical_min": 5.0,
        "typical_max": 25.0,
        "primary_functions": [MaterialFunction.BORON_FLUX, MaterialFunction.SECONDARY_GLASS_FORMER],
        "description": "Boron sources (frits, Gerstley borate) are essential for low/mid-fire glazes.",
        "notes": "Gerstley borate is variable - consider frit substitutes. Boron promotes gloss and heals defects.",
    },
    MaterialType.ALUMINA: {
        "typical_min": 1.0,
        "typical_max": 10.0,
        "primary_functions": [MaterialFunction.ALUMINA_SOURCE, MaterialFunction.VISCOSITY_MODIFIER, MaterialFunction.MATTE_PROMOTER],
        "description": "Pure alumina sources adjust viscosity and surface texture.",
        "notes": "Alumina hydrate has 35% LOI. Calcined alumina has none. Use to stiffen runny glazes.",
    },
    MaterialType.FLUX: {
        "typical_min": 2.0,
        "typical_max": 15.0,
        "primary_functions": [MaterialFunction.ALKALI_FLUX, MaterialFunction.ALKALINE_EARTH_FLUX, MaterialFunction.CRYSTAL_PROMOTER],
        "description": "Secondary fluxes modify melting behavior and special effects.",
        "notes": "Zinc promotes crystals. Lithium lowers expansion. Barium promotes matte (not food-safe).",
    },
    MaterialType.FRIT: {
        "typical_min": 10.0,
        "typical_max": 80.0,
        "primary_functions": [MaterialFunction.BORON_FLUX, MaterialFunction.LOW_TEMP_FLUX, MaterialFunction.GLASS_FORMER],
        "description": "Frits are pre-melted materials that provide consistent, insoluble chemistry.",
        "notes": "Essential for low-fire. 3134 is calcium-boron. 3110 is sodium silicate (high expansion).",
    },
    MaterialType.COLORANT: {
        "typical_min": 0.5,
        "typical_max": 10.0,
        "primary_functions": [MaterialFunction.IRON_COLORANT, MaterialFunction.COPPER_COLORANT, MaterialFunction.COBALT_COLORANT],
        "description": "Metal oxides and stains that provide color.",
        "notes": "Cobalt is strongest (0.5-2%). Iron varies by atmosphere (1-10%). Copper gives green/red (1-5%).",
    },
    MaterialType.OPACIFIER: {
        "typical_min": 3.0,
        "typical_max": 15.0,
        "primary_functions": [MaterialFunction.OPACITY_SOURCE],
        "description": "Materials that create opacity through crystal formation.",
        "notes": "Zircopax (zirconia) 8-12% for white. Tin oxide 3-8% for softer white. Titanium 3-8% for cream.",
    },
}


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
