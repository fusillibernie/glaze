"""Service for material substitutions in ceramic glazes."""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class AvailabilityStatus(Enum):
    """Material availability status."""
    AVAILABLE = "available"
    LIMITED = "limited"
    DISCONTINUED = "discontinued"
    RESTRICTED = "restricted"
    EXPENSIVE = "expensive"
    VARIABLE = "variable"


class SubstituteType(Enum):
    """Type of substitution."""
    DIRECT = "direct"  # 1:1 replacement with ratio
    BLEND = "blend"  # Multiple materials combined
    SIMILAR = "similar"  # Similar function, not exact match
    ALTERNATIVE = "alternative"  # Different approach to achieve same result
    PARTIAL = "partial"  # Replaces only part of the function


@dataclass
class BlendComponent:
    """A component of a blend substitution."""
    material: str
    parts: float


@dataclass
class OxideAdjustment:
    """Adjustment needed when using a substitute."""
    oxide: str
    change: str


@dataclass
class Substitute:
    """A substitute for a material."""
    name: str
    sub_type: SubstituteType
    ratio: Optional[float]  # How much substitute per unit original
    notes: str
    components: list[BlendComponent] = field(default_factory=list)
    adjustments: list[OxideAdjustment] = field(default_factory=list)


@dataclass
class MaterialSubstitution:
    """Substitution information for a material."""
    material: str
    alternate_names: list[str]
    status: AvailabilityStatus
    reason: Optional[str]
    substitutes: list[Substitute]


@dataclass
class SubstitutionResult:
    """Result of calculating a substitution."""
    original_material: str
    original_amount: float
    substitute_name: str
    substitute_type: SubstituteType
    components: list[tuple[str, float]]  # (material_name, amount)
    notes: str
    adjustments: list[OxideAdjustment]
    warnings: list[str]


DEFAULT_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "materials" / "substitutions.json"


class SubstitutionService:
    """Service for finding and calculating material substitutions."""

    def __init__(self, data_path: Optional[Path] = None):
        """Initialize the service.

        Args:
            data_path: Path to substitutions JSON file.
        """
        self.data_path = data_path or DEFAULT_DATA_PATH
        self._substitutions: dict[str, MaterialSubstitution] = {}
        self._name_index: dict[str, str] = {}  # alternate name -> primary name
        self._loaded = False

    def load(self) -> None:
        """Load substitution data from JSON file."""
        if not self.data_path.exists():
            self._loaded = True
            return

        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data.get("substitutions", []):
                material_name = item["material"]
                status_str = item.get("status", "available")
                try:
                    status = AvailabilityStatus(status_str)
                except ValueError:
                    status = AvailabilityStatus.AVAILABLE

                substitutes = []
                for sub_data in item.get("substitutes", []):
                    sub_type_str = sub_data.get("type", "direct")
                    try:
                        sub_type = SubstituteType(sub_type_str)
                    except ValueError:
                        sub_type = SubstituteType.DIRECT

                    components = [
                        BlendComponent(c["material"], c["parts"])
                        for c in sub_data.get("components", [])
                    ]

                    adjustments = [
                        OxideAdjustment(a["oxide"], a["change"])
                        for a in sub_data.get("adjustments", [])
                    ]

                    substitutes.append(Substitute(
                        name=sub_data["name"],
                        sub_type=sub_type,
                        ratio=sub_data.get("ratio"),
                        notes=sub_data.get("notes", ""),
                        components=components,
                        adjustments=adjustments,
                    ))

                material_sub = MaterialSubstitution(
                    material=material_name,
                    alternate_names=item.get("alternate_names", []),
                    status=status,
                    reason=item.get("reason"),
                    substitutes=substitutes,
                )

                # Index by primary name
                self._substitutions[material_name.lower()] = material_sub

                # Index by alternate names
                for alt_name in material_sub.alternate_names:
                    self._name_index[alt_name.lower()] = material_name.lower()

        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading substitutions: {e}")

        self._loaded = True

    def _ensure_loaded(self) -> None:
        """Ensure data is loaded."""
        if not self._loaded:
            self.load()

    def _normalize_name(self, name: str) -> str:
        """Normalize material name to primary form."""
        name_lower = name.lower()
        if name_lower in self._name_index:
            return self._name_index[name_lower]
        return name_lower

    def get_status(self, material_name: str) -> Optional[AvailabilityStatus]:
        """Get availability status of a material.

        Args:
            material_name: Name of the material.

        Returns:
            AvailabilityStatus if found, None otherwise.
        """
        self._ensure_loaded()
        name = self._normalize_name(material_name)
        sub_info = self._substitutions.get(name)
        return sub_info.status if sub_info else None

    def get_substitution_info(self, material_name: str) -> Optional[MaterialSubstitution]:
        """Get full substitution information for a material.

        Args:
            material_name: Name of the material.

        Returns:
            MaterialSubstitution if found, None otherwise.
        """
        self._ensure_loaded()
        name = self._normalize_name(material_name)
        return self._substitutions.get(name)

    def get_substitutes(self, material_name: str) -> list[Substitute]:
        """Get list of substitutes for a material.

        Args:
            material_name: Name of the material.

        Returns:
            List of Substitute objects.
        """
        self._ensure_loaded()
        sub_info = self.get_substitution_info(material_name)
        return sub_info.substitutes if sub_info else []

    def calculate_substitution(
        self,
        material_name: str,
        original_amount: float,
        substitute_index: int = 0,
    ) -> Optional[SubstitutionResult]:
        """Calculate amounts for a specific substitution.

        Args:
            material_name: Name of the material to substitute.
            original_amount: Amount of original material (in recipe units).
            substitute_index: Index of substitute to use (0 = first/best).

        Returns:
            SubstitutionResult with calculated amounts, or None if no substitute found.
        """
        self._ensure_loaded()
        substitutes = self.get_substitutes(material_name)

        if not substitutes or substitute_index >= len(substitutes):
            return None

        sub = substitutes[substitute_index]
        warnings = []

        if sub.sub_type == SubstituteType.BLEND:
            # Calculate amounts for each component
            total_parts = sum(c.parts for c in sub.components)
            components = []

            for comp in sub.components:
                # Apply overall ratio and proportional amount
                ratio = sub.ratio or 1.0
                amount = (original_amount * ratio * comp.parts) / total_parts
                components.append((comp.material, round(amount, 2)))

        else:
            # Direct substitution
            if sub.ratio is None:
                warnings.append(
                    f"No fixed ratio for {sub.name}. Reformulation may be needed."
                )
                components = [(sub.name, original_amount)]
            else:
                amount = original_amount * sub.ratio
                components = [(sub.name, round(amount, 2))]

        # Add warnings based on status
        sub_info = self.get_substitution_info(material_name)
        if sub_info and sub_info.status == AvailabilityStatus.RESTRICTED:
            warnings.append(f"Original material ({material_name}) has restrictions: {sub_info.reason}")

        return SubstitutionResult(
            original_material=material_name,
            original_amount=original_amount,
            substitute_name=sub.name,
            substitute_type=sub.sub_type,
            components=components,
            notes=sub.notes,
            adjustments=sub.adjustments,
            warnings=warnings,
        )

    def check_recipe_availability(
        self,
        recipe: dict[str, float],
    ) -> dict[str, tuple[AvailabilityStatus, Optional[str]]]:
        """Check availability of all materials in a recipe.

        Args:
            recipe: Dictionary of material_name -> amount.

        Returns:
            Dictionary of material_name -> (status, reason) for unavailable materials.
        """
        self._ensure_loaded()
        issues = {}

        for material_name in recipe.keys():
            status = self.get_status(material_name)
            if status and status != AvailabilityStatus.AVAILABLE:
                sub_info = self.get_substitution_info(material_name)
                reason = sub_info.reason if sub_info else None
                issues[material_name] = (status, reason)

        return issues

    def substitute_recipe(
        self,
        recipe: dict[str, float],
        materials_to_substitute: Optional[list[str]] = None,
    ) -> tuple[dict[str, float], list[SubstitutionResult]]:
        """Substitute materials in a recipe.

        Args:
            recipe: Original recipe dictionary (material_name -> amount).
            materials_to_substitute: Specific materials to substitute. If None,
                substitutes all unavailable materials.

        Returns:
            Tuple of (new_recipe, list of SubstitutionResults).
        """
        self._ensure_loaded()
        new_recipe = dict(recipe)
        results = []

        if materials_to_substitute is None:
            # Auto-detect unavailable materials
            issues = self.check_recipe_availability(recipe)
            materials_to_substitute = list(issues.keys())

        for material_name in materials_to_substitute:
            if material_name not in recipe:
                continue

            original_amount = recipe[material_name]
            result = self.calculate_substitution(material_name, original_amount)

            if result:
                # Remove original material
                del new_recipe[material_name]

                # Add substitute components
                for comp_name, comp_amount in result.components:
                    if comp_name in new_recipe:
                        new_recipe[comp_name] += comp_amount
                    else:
                        new_recipe[comp_name] = comp_amount

                results.append(result)

        return new_recipe, results

    def get_all_unavailable(self) -> list[tuple[str, AvailabilityStatus, str]]:
        """Get all materials with availability issues.

        Returns:
            List of (material_name, status, reason) tuples.
        """
        self._ensure_loaded()
        unavailable = []

        for name, info in self._substitutions.items():
            if info.status != AvailabilityStatus.AVAILABLE:
                unavailable.append((
                    info.material,
                    info.status,
                    info.reason or "No reason provided"
                ))

        return unavailable
