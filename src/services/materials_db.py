"""Materials database for ceramic raw materials."""

import json
from pathlib import Path
from typing import Optional

from ..models.materials import Material, MaterialType, MaterialAnalysis, OxideAnalysis


DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "materials"


class MaterialsDatabase:
    """Database of ceramic raw materials."""

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize the database.

        Args:
            data_dir: Directory containing material JSON files.
        """
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self._materials: dict[str, Material] = {}
        self._by_type: dict[MaterialType, list[Material]] = {}
        self._loaded = False

    def load(self) -> None:
        """Load materials from JSON files."""
        if not self.data_dir.exists():
            return

        for json_file in self.data_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Handle different JSON structures
                materials = []
                if isinstance(data, list):
                    materials = data
                elif "materials" in data:
                    materials = data["materials"]
                elif "colorants" in data:
                    materials = data["colorants"]

                for item in materials:
                    material = Material.from_dict(item)
                    self._materials[material.name.lower()] = material

                    # Index by type
                    if material.material_type not in self._by_type:
                        self._by_type[material.material_type] = []
                    self._by_type[material.material_type].append(material)

            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading {json_file}: {e}")
                continue

        self._loaded = True

    def _ensure_loaded(self) -> None:
        """Ensure data is loaded."""
        if not self._loaded:
            self.load()

    def get(self, name: str) -> Optional[Material]:
        """Get material by name.

        Args:
            name: Material name (case-insensitive).

        Returns:
            Material if found, None otherwise.
        """
        self._ensure_loaded()
        return self._materials.get(name.lower())

    def get_by_type(self, material_type: MaterialType) -> list[Material]:
        """Get all materials of a specific type.

        Args:
            material_type: Type of material.

        Returns:
            List of materials of that type.
        """
        self._ensure_loaded()
        return self._by_type.get(material_type, [])

    def search(
        self,
        query: str,
        material_type: Optional[MaterialType] = None,
    ) -> list[Material]:
        """Search materials by name.

        Args:
            query: Search query.
            material_type: Optional type filter.

        Returns:
            List of matching materials.
        """
        self._ensure_loaded()
        query_lower = query.lower()
        results = []

        for name, material in self._materials.items():
            if query_lower in name:
                if material_type is None or material.material_type == material_type:
                    results.append(material)
            elif any(query_lower in alt.lower() for alt in material.alternate_names):
                if material_type is None or material.material_type == material_type:
                    results.append(material)

        return results

    def get_all(self) -> list[Material]:
        """Get all materials.

        Returns:
            List of all materials.
        """
        self._ensure_loaded()
        return list(self._materials.values())

    def add(self, material: Material) -> None:
        """Add a material to the database.

        Args:
            material: Material to add.
        """
        self._ensure_loaded()
        self._materials[material.name.lower()] = material

        if material.material_type not in self._by_type:
            self._by_type[material.material_type] = []
        self._by_type[material.material_type].append(material)

    def save(self, filepath: Path) -> None:
        """Save all materials to a JSON file.

        Args:
            filepath: Output file path.
        """
        data = {
            "materials": [m.to_dict() for m in self._materials.values()]
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def find_substitutes(
        self,
        material: Material,
        limit: int = 10,
    ) -> list[tuple[Material, float]]:
        """Find potential substitutes for a material.

        Args:
            material: Material to find substitutes for.
            limit: Maximum number of substitutes to return.

        Returns:
            List of (Material, similarity_score) tuples sorted by similarity.
        """
        self._ensure_loaded()
        substitutes = []

        # Check listed substitutes first (with 1.0 similarity)
        for sub_name in material.substitutes:
            sub = self.get(sub_name)
            if sub:
                substitutes.append((sub, 1.0))

        # Find similar materials by type
        same_type = self.get_by_type(material.material_type)
        for m in same_type:
            if m.name != material.name and m not in [s[0] for s in substitutes]:
                # Compare oxide analysis
                similarity = self._calculate_similarity(material, m)
                if similarity > 0.5:  # 50% similar threshold
                    substitutes.append((m, similarity))

        # Sort by similarity (highest first) and limit
        substitutes.sort(key=lambda x: x[1], reverse=True)
        return substitutes[:limit]

    def _calculate_similarity(self, m1: Material, m2: Material) -> float:
        """Calculate similarity between two materials based on oxide analysis.

        Args:
            m1: First material.
            m2: Second material.

        Returns:
            Similarity score 0-1.
        """
        a1 = m1.analysis.oxide_analysis
        a2 = m2.analysis.oxide_analysis

        # Compare major oxides
        major_oxides = ["SiO2", "Al2O3", "CaO", "MgO", "Na2O", "K2O"]
        total_diff = 0.0
        count = 0

        for oxide in major_oxides:
            v1 = getattr(a1, oxide, 0.0)
            v2 = getattr(a2, oxide, 0.0)
            if v1 > 0 or v2 > 0:
                max_val = max(v1, v2, 1.0)
                diff = abs(v1 - v2) / max_val
                total_diff += diff
                count += 1

        if count == 0:
            return 0.0

        avg_diff = total_diff / count
        return 1.0 - min(avg_diff, 1.0)
