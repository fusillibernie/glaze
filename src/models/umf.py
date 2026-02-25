"""Unity Molecular Formula (UMF) and Stull Chart models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .materials import OxideAnalysis, OXIDE_MOLECULAR_WEIGHTS


class OxideGroup(Enum):
    """Classification of oxides by function."""
    RO_R2O = "ro_r2o"  # Fluxes (unity in UMF)
    R2O3 = "r2o3"  # Stabilizers (Al2O3, B2O3, Fe2O3)
    RO2 = "ro2"  # Glass formers (SiO2, TiO2, ZrO2)


# Oxides by group
FLUX_OXIDES = ["Na2O", "K2O", "Li2O", "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO"]
STABILIZER_OXIDES = ["Al2O3", "B2O3"]
GLASS_FORMER_OXIDES = ["SiO2"]


@dataclass
class UMF:
    """Unity Molecular Formula - standardized glaze chemistry.

    In UMF, the flux oxides (RO + R2O) sum to 1.0, and all other
    oxides are expressed relative to that unity.
    """
    # Fluxes (RO + R2O = 1.0)
    Na2O: float = 0.0
    K2O: float = 0.0
    Li2O: float = 0.0
    CaO: float = 0.0
    MgO: float = 0.0
    BaO: float = 0.0
    SrO: float = 0.0
    ZnO: float = 0.0
    PbO: float = 0.0

    # Stabilizers (R2O3)
    Al2O3: float = 0.0
    B2O3: float = 0.0

    # Glass formers (RO2)
    SiO2: float = 0.0

    # Other oxides (molar amounts relative to unity)
    Fe2O3: float = 0.0
    TiO2: float = 0.0
    ZrO2: float = 0.0
    P2O5: float = 0.0

    @property
    def flux_total(self) -> float:
        """Sum of all flux oxides (should be ~1.0 for valid UMF)."""
        return (
            self.Na2O + self.K2O + self.Li2O +
            self.CaO + self.MgO + self.BaO +
            self.SrO + self.ZnO + self.PbO
        )

    @property
    def silica_alumina_ratio(self) -> float:
        """SiO2:Al2O3 ratio - key indicator of glaze surface."""
        if self.Al2O3 > 0:
            return self.SiO2 / self.Al2O3
        return float('inf')

    @property
    def alkali_ratio(self) -> float:
        """(Na2O + K2O + Li2O) / total flux - affects thermal expansion."""
        alkalis = self.Na2O + self.K2O + self.Li2O
        if self.flux_total > 0:
            return alkalis / self.flux_total
        return 0.0

    @property
    def stull_point(self) -> "StullPoint":
        """Get position on Stull Chart."""
        return StullPoint(al2o3=self.Al2O3, sio2=self.SiO2)

    def to_dict(self) -> dict:
        """Convert to dictionary, excluding zero values."""
        result = {}
        for oxide in [
            "Na2O", "K2O", "Li2O", "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO",
            "Al2O3", "B2O3", "SiO2", "Fe2O3", "TiO2", "ZrO2", "P2O5"
        ]:
            value = getattr(self, oxide)
            if value > 0:
                result[oxide] = round(value, 4)
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "UMF":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})

    @classmethod
    def from_oxide_analysis(cls, analysis: OxideAnalysis) -> "UMF":
        """Calculate UMF from weight % oxide analysis.

        Steps:
        1. Convert weight % to moles (divide by molecular weight)
        2. Sum the flux moles (RO + R2O)
        3. Divide all moles by flux total to normalize to unity
        """
        # Convert weight % to moles
        moles = {}
        for oxide in [
            "SiO2", "Al2O3", "B2O3",
            "Na2O", "K2O", "Li2O", "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO",
            "Fe2O3", "TiO2", "ZrO2", "P2O5"
        ]:
            wt_pct = getattr(analysis, oxide, 0.0)
            mol_wt = OXIDE_MOLECULAR_WEIGHTS.get(oxide, 1.0)
            moles[oxide] = wt_pct / mol_wt if mol_wt > 0 else 0.0

        # Sum flux moles
        flux_sum = sum(
            moles.get(oxide, 0.0)
            for oxide in FLUX_OXIDES
        )

        if flux_sum == 0:
            # No fluxes - can't create valid UMF
            return cls()

        # Normalize to unity
        return cls(
            Na2O=moles.get("Na2O", 0) / flux_sum,
            K2O=moles.get("K2O", 0) / flux_sum,
            Li2O=moles.get("Li2O", 0) / flux_sum,
            CaO=moles.get("CaO", 0) / flux_sum,
            MgO=moles.get("MgO", 0) / flux_sum,
            BaO=moles.get("BaO", 0) / flux_sum,
            SrO=moles.get("SrO", 0) / flux_sum,
            ZnO=moles.get("ZnO", 0) / flux_sum,
            PbO=moles.get("PbO", 0) / flux_sum,
            Al2O3=moles.get("Al2O3", 0) / flux_sum,
            B2O3=moles.get("B2O3", 0) / flux_sum,
            SiO2=moles.get("SiO2", 0) / flux_sum,
            Fe2O3=moles.get("Fe2O3", 0) / flux_sum,
            TiO2=moles.get("TiO2", 0) / flux_sum,
            ZrO2=moles.get("ZrO2", 0) / flux_sum,
            P2O5=moles.get("P2O5", 0) / flux_sum,
        )


@dataclass
class StullPoint:
    """A point on the Stull Chart (Al2O3 vs SiO2).

    The Stull Chart maps Al2O3 (x-axis) vs SiO2 (y-axis) in UMF
    to predict glaze surface quality.
    """
    al2o3: float
    sio2: float

    @property
    def surface_prediction(self) -> str:
        """Predict surface quality based on position."""
        ratio = self.sio2 / self.al2o3 if self.al2o3 > 0 else float('inf')

        # Rough Stull Chart regions (for cone 6-10)
        if self.al2o3 < 0.15:
            return "underfired_runny"
        elif self.al2o3 > 0.65:
            return "matte_dry"
        elif ratio < 6:
            return "matte"
        elif ratio > 12:
            return "glossy_runny"
        elif 8 <= ratio <= 11:
            return "glossy"
        else:
            return "satin"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "al2o3": round(self.al2o3, 4),
            "sio2": round(self.sio2, 4),
            "surface_prediction": self.surface_prediction,
        }


# Typical UMF ranges by cone
CONE_6_UMF_RANGES = {
    "SiO2": (2.5, 4.5),
    "Al2O3": (0.25, 0.55),
    "B2O3": (0.0, 0.5),
    "flux_alkali": (0.2, 0.6),  # Na2O + K2O + Li2O
    "flux_alkaline_earth": (0.3, 0.7),  # CaO + MgO + BaO + SrO
}

CONE_10_UMF_RANGES = {
    "SiO2": (3.0, 5.5),
    "Al2O3": (0.35, 0.70),
    "B2O3": (0.0, 0.2),  # Less boron needed at high temp
    "flux_alkali": (0.15, 0.45),
    "flux_alkaline_earth": (0.4, 0.8),
}


def get_umf_ranges(cone: int) -> dict:
    """Get typical UMF ranges for a cone temperature."""
    if cone <= 6:
        return CONE_6_UMF_RANGES
    else:
        return CONE_10_UMF_RANGES
