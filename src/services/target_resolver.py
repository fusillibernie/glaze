"""Resolve glaze descriptors into concrete solver targets."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


REFERENCE_DIR = Path(__file__).parent.parent.parent / "data" / "reference"


@dataclass
class OxideRange:
    """Target range for a single oxide in UMF."""
    oxide: str
    min_val: float
    max_val: float
    weight: float = 1.0  # Priority weight for solver objective

    @property
    def midpoint(self) -> float:
        return (self.min_val + self.max_val) / 2.0


@dataclass
class MaterialConstraint:
    """Percentage constraint for a specific material."""
    material_name: str
    min_pct: float = 0.0
    max_pct: float = 100.0
    required: bool = False


@dataclass
class ColorantAddition:
    """Colorant to add on top of base recipe (beyond 100%)."""
    material_name: str
    percentage: float
    oxide: str = ""


@dataclass
class SolverTarget:
    """Complete target specification for the glaze solver."""
    oxide_ranges: list[OxideRange] = field(default_factory=list)
    material_constraints: list[MaterialConstraint] = field(default_factory=list)
    colorant_additions: list[ColorantAddition] = field(default_factory=list)
    si_al_ratio: Optional[tuple[float, float]] = None
    preferred_materials: list[str] = field(default_factory=list)
    category: Optional[str] = None
    notes: str = ""
    warnings: list[str] = field(default_factory=list)

    def get_oxide_range(self, oxide: str) -> Optional[OxideRange]:
        for r in self.oxide_ranges:
            if r.oxide == oxide:
                return r
        return None


# Map cone values to umf_limits.json bracket keys
CONE_BRACKET_MAP = {
    "04": "cone_04_02", "03": "cone_04_02", "02": "cone_04_02",
    "01": "cone_04_02", "1": "cone_04_02", "2": "cone_04_02",
    "3": "cone_3_7", "4": "cone_3_7", "5": "cone_5_6",
    "6": "cone_5_6", "7": "cone_3_7",
    "8": "cone_8_10", "9": "cone_8_10", "10": "cone_8_10",
    "11": "cone_8_10", "12": "cone_8_10", "13": "cone_8_10",
}

# Map surface names to cushing source keys
SURFACE_SOURCE_MAP = {
    "glossy": "cushing_glossy",
    "satin": "cushing_satin",
    "matte": "cushing_matte",
    "dry_matte": "cushing_matte",
}

# Oxides tracked in UMF limits (KNaO is combined K2O+Na2O)
UMF_LIMIT_OXIDES = ["SiO2", "Al2O3", "B2O3", "KNaO", "CaO", "MgO", "ZnO", "BaO", "SrO", "Li2O"]


class TargetResolver:
    """Converts user descriptors (cone, atmosphere, surface, category)
    into concrete SolverTarget with oxide ranges and material constraints."""

    def __init__(self):
        self._umf_limits: Optional[dict] = None
        self._category_profiles: Optional[dict] = None

    def _load_umf_limits(self) -> dict:
        if self._umf_limits is None:
            path = REFERENCE_DIR / "umf_limits.json"
            with open(path, "r", encoding="utf-8") as f:
                self._umf_limits = json.load(f)
        return self._umf_limits

    def _load_category_profiles(self) -> dict:
        if self._category_profiles is None:
            path = REFERENCE_DIR / "category_profiles.json"
            with open(path, "r", encoding="utf-8") as f:
                self._category_profiles = json.load(f)
        return self._category_profiles

    def resolve(
        self,
        cone: str,
        surface: str = "glossy",
        atmosphere: str = "oxidation",
        category: Optional[str] = None,
        colorants: Optional[list[dict]] = None,
    ) -> SolverTarget:
        """Resolve descriptors into a SolverTarget.

        Args:
            cone: Firing cone (e.g., "6", "10", "04").
            surface: Surface type (glossy, satin, matte, dry_matte).
            atmosphere: Firing atmosphere (oxidation, reduction, neutral, wood).
            category: Glaze category (celadon, shino, tenmoku, etc.) or None.
            colorants: List of {"material_name": str, "percentage": float}.

        Returns:
            SolverTarget with oxide ranges, material constraints, and colorants.
        """
        target = SolverTarget(category=category)

        # Step 1: Get base UMF ranges from cone bracket + surface
        base_ranges = self._get_base_ranges(cone, surface, target)

        # Step 2: If category is specified, overlay category profile
        if category:
            base_ranges = self._apply_category_profile(base_ranges, category, target)

        # Step 3: Convert to OxideRange objects
        for oxide, (lo, hi) in base_ranges.items():
            # KNaO gets split into K2O and Na2O later by the solver;
            # store as combined for now
            weight = 1.0
            if oxide in ("SiO2", "Al2O3"):
                weight = 2.0  # Higher priority for glass formers/stabilizers
            elif oxide == "CaO":
                weight = 1.5
            target.oxide_ranges.append(OxideRange(
                oxide=oxide, min_val=lo, max_val=hi, weight=weight,
            ))

        # Step 4: Add colorant additions
        if colorants:
            for c in colorants:
                target.colorant_additions.append(ColorantAddition(
                    material_name=c.get("material_name", ""),
                    percentage=c.get("percentage", 0.0),
                ))

        return target

    def _get_base_ranges(self, cone: str, surface: str, target: SolverTarget) -> dict[str, tuple[float, float]]:
        """Get base oxide ranges from umf_limits.json for cone + surface."""
        limits = self._load_umf_limits()
        bracket_key = CONE_BRACKET_MAP.get(str(cone))
        if not bracket_key:
            bracket_key = "cone_8_10"
            target.warnings.append(f"Cone {cone} not in reference data, using cone 8-10 limits")
        bracket = limits.get("limits", {}).get(bracket_key, {})

        if not bracket:
            bracket = limits.get("limits", {}).get("cone_8_10", {})
            target.warnings.append(f"No UMF limits for {bracket_key}, falling back to cone 8-10")

        # Try surface-specific source first, then fall back to general sources
        source_key = SURFACE_SOURCE_MAP.get(surface)
        source = bracket.get(source_key) if source_key else None

        if not source:
            used_fallback = None
            for fallback in ["cushing_glossy", "uk_traditional", "green_cooper"]:
                source = bracket.get(fallback)
                if source:
                    used_fallback = fallback
                    break
            if used_fallback and source_key:
                target.warnings.append(f"No {surface} limits for this cone, using {used_fallback.replace('_', ' ')}")

        if not source:
            for key, val in bracket.items():
                if isinstance(val, dict) and "SiO2" in val:
                    source = val
                    break

        if not source:
            target.warnings.append("No matching UMF limits found, using generic cone 6 glossy defaults")
            return {
                "SiO2": (2.5, 4.5),
                "Al2O3": (0.2, 0.5),
                "CaO": (0.2, 0.6),
                "KNaO": (0.1, 0.5),
                "MgO": (0.0, 0.3),
            }

        ranges = {}
        for oxide in UMF_LIMIT_OXIDES:
            if oxide in source and isinstance(source[oxide], dict):
                ranges[oxide] = (source[oxide]["min"], source[oxide]["max"])

        return ranges

    def _apply_category_profile(
        self,
        base_ranges: dict[str, tuple[float, float]],
        category: str,
        target: SolverTarget,
    ) -> dict[str, tuple[float, float]]:
        """Overlay category-specific UMF overrides and constraints."""
        profiles = self._load_category_profiles()
        profile = profiles.get("categories", {}).get(category)

        if not profile:
            return base_ranges

        # Apply UMF overrides: intersect ranges (tighten, never widen)
        overrides = profile.get("umf_overrides", {})
        for oxide, override in overrides.items():
            if oxide in base_ranges:
                base_lo, base_hi = base_ranges[oxide]
                new_lo = max(base_lo, override["min"])
                new_hi = min(base_hi, override["max"])
                # Only apply if the intersection is valid
                if new_lo <= new_hi:
                    base_ranges[oxide] = (new_lo, new_hi)
                else:
                    # Category demands a range outside base — trust the category
                    base_ranges[oxide] = (override["min"], override["max"])
            else:
                base_ranges[oxide] = (override["min"], override["max"])

        # Apply Si:Al ratio
        si_al = profile.get("si_al_ratio")
        if si_al:
            target.si_al_ratio = (si_al["min"], si_al["max"])

        # Apply material constraints
        for mat_name, constraint in profile.get("material_constraints", {}).items():
            target.material_constraints.append(MaterialConstraint(
                material_name=mat_name,
                min_pct=constraint.get("min_pct", 0.0),
                max_pct=constraint.get("max_pct", 100.0),
                required=constraint.get("min_pct", 0.0) > 0,
            ))

        # Set preferred materials
        target.preferred_materials = profile.get("preferred_materials", [])

        # Add required colorants from category
        for colorant in profile.get("required_colorants", []):
            # Only add if user didn't already specify this oxide
            already_specified = any(
                c.material_name == colorant.get("source_material", "")
                for c in target.colorant_additions
            )
            if not already_specified:
                mid_pct = (colorant["min_pct"] + colorant["max_pct"]) / 2.0
                target.colorant_additions.append(ColorantAddition(
                    material_name=colorant.get("source_material", ""),
                    percentage=mid_pct,
                    oxide=colorant.get("oxide", ""),
                ))

        target.notes = profile.get("notes", "")
        return base_ranges
