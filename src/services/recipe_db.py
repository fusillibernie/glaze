"""Unified recipe database loading from multiple sources."""

import json
from pathlib import Path
from typing import Optional


DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"


class RecipeDatabase:
    """Unified database of glaze recipes from multiple sources.

    Sources:
    - Local curated recipes (data/recipes/*.json)
    - Glazy bulk data (data/glazy_bulk/recipes.json)
    - Sankey database (data/sankey/recipes.json)
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self._recipes: list[dict] = []
        self._by_source: dict[str, list[dict]] = {}
        self._loaded = False

    def load(self) -> None:
        """Load recipes from all sources."""
        self._recipes = []
        self._by_source = {}

        # 1. Local curated recipes
        self._load_local_recipes()

        # 2. Glazy bulk data
        self._load_glazy_bulk()

        # 3. Sankey database
        self._load_sankey()

        self._loaded = True

    def _load_local_recipes(self) -> None:
        """Load curated recipes from data/recipes/*.json."""
        recipes_dir = self.data_dir / "recipes"
        if not recipes_dir.exists():
            return

        for json_file in recipes_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Handle different JSON structures
                recipes = []
                if isinstance(data, list):
                    recipes = data
                else:
                    # Try common keys
                    for key in data:
                        if isinstance(data[key], list):
                            recipes = data[key]
                            break

                for recipe in recipes:
                    if not isinstance(recipe, dict):
                        continue
                    recipe.setdefault("source", "local")
                    recipe.setdefault("source_file", json_file.stem)
                    self._add_recipe(recipe)

            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading {json_file}: {e}")

    def _load_glazy_bulk(self) -> None:
        """Load bulk Glazy data from data/glazy_bulk/recipes.json."""
        path = self.data_dir / "glazy_bulk" / "recipes.json"
        if not path.exists():
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            recipes = data.get("recipes", []) if isinstance(data, dict) else data
            for recipe in recipes:
                recipe.setdefault("source", "glazy-data")
                self._add_recipe(recipe)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading glazy bulk: {e}")

    def _load_sankey(self) -> None:
        """Load Sankey database from data/sankey/recipes.json."""
        path = self.data_dir / "sankey" / "recipes.json"
        if not path.exists():
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            recipes = data.get("recipes", []) if isinstance(data, dict) else data
            for recipe in recipes:
                recipe.setdefault("source", "sankey_database")
                self._add_recipe(recipe)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading sankey: {e}")

    def _add_recipe(self, recipe: dict) -> None:
        """Add a recipe to the database."""
        self._recipes.append(recipe)
        source = recipe.get("source", "unknown")
        if source not in self._by_source:
            self._by_source[source] = []
        self._by_source[source].append(recipe)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def search(
        self,
        query: Optional[str] = None,
        cone: Optional[str] = None,
        atmosphere: Optional[str] = None,
        surface: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Search recipes across all sources."""
        self._ensure_loaded()

        results = self._recipes

        if source:
            results = [r for r in results if r.get("source") == source]

        if cone:
            results = [r for r in results if self._matches_cone(r, cone)]

        if atmosphere:
            atm_lower = atmosphere.lower()
            results = [
                r for r in results
                if atm_lower in (r.get("atmosphere", "") or "").lower()
            ]

        if surface:
            surf_lower = surface.lower()
            results = [
                r for r in results
                if surf_lower in (r.get("surface", "") or "").lower()
            ]

        if query:
            q = query.lower()
            results = [
                r for r in results
                if q in (r.get("name", "") or "").lower()
                or q in (r.get("description", "") or "").lower()
                or q in (r.get("subtype", "") or "").lower()
                or q in (r.get("notes", "") or "").lower()
            ]

        return results[offset:offset + limit]

    def _matches_cone(self, recipe: dict, target_cone: str) -> bool:
        """Check if recipe matches a cone filter."""
        recipe_cone = recipe.get("cone", "")
        if not recipe_cone:
            return False

        recipe_cone = str(recipe_cone)
        target = str(target_cone)

        # Exact match
        if recipe_cone == target:
            return True

        # Range match: "6-10" contains "8"
        if "-" in recipe_cone:
            try:
                parts = recipe_cone.split("-")
                low = int(parts[0])
                high = int(parts[1])
                t = int(target)
                return low <= t <= high
            except (ValueError, IndexError):
                pass

        return False

    def get_by_id(self, glazy_id: int) -> Optional[dict]:
        """Get recipe by Glazy ID."""
        self._ensure_loaded()
        for r in self._recipes:
            if r.get("glazy_id") == glazy_id:
                return r
        return None

    def browse(
        self,
        cone: Optional[str] = None,
        atmosphere: Optional[str] = None,
        surface: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Browse recipes with pagination and metadata."""
        results = self.search(
            cone=cone,
            atmosphere=atmosphere,
            surface=surface,
            source=source,
            limit=limit,
            offset=offset,
        )

        return {
            "recipes": results,
            "count": len(results),
            "offset": offset,
            "limit": limit,
            "total": self.count(cone=cone, atmosphere=atmosphere, surface=surface, source=source),
        }

    def count(
        self,
        cone: Optional[str] = None,
        atmosphere: Optional[str] = None,
        surface: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        """Count recipes matching filters."""
        # Use a large limit to count all
        return len(self.search(
            cone=cone,
            atmosphere=atmosphere,
            surface=surface,
            source=source,
            limit=999999,
        ))

    def statistics(self) -> dict:
        """Get database statistics."""
        self._ensure_loaded()

        stats = {
            "total_recipes": len(self._recipes),
            "by_source": {k: len(v) for k, v in self._by_source.items()},
            "by_cone": {},
            "by_surface": {},
            "by_atmosphere": {},
        }

        for r in self._recipes:
            cone = str(r.get("cone", "unknown"))
            surface = r.get("surface", "unknown") or "unknown"
            atm = r.get("atmosphere", "unknown") or "unknown"

            stats["by_cone"][cone] = stats["by_cone"].get(cone, 0) + 1
            stats["by_surface"][surface] = stats["by_surface"].get(surface, 0) + 1
            stats["by_atmosphere"][atm] = stats["by_atmosphere"].get(atm, 0) + 1

        # Sort by count descending
        for key in ["by_cone", "by_surface", "by_atmosphere"]:
            stats[key] = dict(sorted(stats[key].items(), key=lambda x: -x[1]))

        return stats

    def get_sources(self) -> list[dict]:
        """Get info about loaded data sources."""
        self._ensure_loaded()
        sources = []

        for source_name, recipes in self._by_source.items():
            sources.append({
                "name": source_name,
                "count": len(recipes),
            })

        # Check for metadata files
        meta_path = self.data_dir / "glazy_bulk" / ".metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                for s in sources:
                    if s["name"] == "glazy-data":
                        s["license"] = meta.get("license")
                        s["attribution"] = meta.get("attribution")
                        s["last_updated"] = meta.get("last_updated")
            except (json.JSONDecodeError, IOError):
                pass

        return sources

    def get_all(self) -> list[dict]:
        """Get all recipes."""
        self._ensure_loaded()
        return self._recipes
