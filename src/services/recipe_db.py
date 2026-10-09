"""Unified recipe database loading from multiple sources."""

import json
import re
import logging
from pathlib import Path
from typing import Optional

from .surface_model import normalize_surface


logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"


class RecipeDatabase:
    """Unified database of glaze recipes from multiple sources.

    Sources:
    - Local curated recipes (data/recipes/*.json)
    - Glazy bulk data (data/glazy_bulk/glazy_recipes.json)
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
                logger.error("Error loading %s: %s", json_file, e)

    def _load_glazy_bulk(self) -> None:
        """Load bulk Glazy data from data/glazy_bulk/glazy_recipes.json."""
        path = self.data_dir / "glazy_bulk" / "glazy_recipes.json"
        if not path.exists():
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            recipes = data.get("recipes", []) if isinstance(data, dict) else data
            for recipe in recipes:
                recipe.setdefault("source", "glazy-data")
                # Bulk records use `id` and an `atmospheres` list; the search/browse
                # filters expect `glazy_id` and a scalar `atmosphere`.
                if "glazy_id" not in recipe and "id" in recipe:
                    recipe["glazy_id"] = recipe["id"]
                if "atmosphere" not in recipe:
                    atmospheres = recipe.get("atmospheres") or []
                    if atmospheres:
                        recipe["atmosphere"] = ", ".join(str(a) for a in atmospheres)
                self._add_recipe(recipe)

        except (json.JSONDecodeError, IOError) as e:
            logger.error("Error loading glazy bulk: %s", e)

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
            logger.error("Error loading sankey: %s", e)

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

    def get_all(self) -> list[dict]:
        """Every loaded recipe, unfiltered, in raw dict form."""
        self._ensure_loaded()
        return list(self._recipes)

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
            # A canonical class matches on the normalized label; anything
            # else falls back to substring so freeform terms ("carbon
            # trap", "crystalline") still work.
            #
            # Substring alone was wrong in both directions, because the
            # corpus vocabulary overlaps: "matte" returned 2,452 recipes
            # of which 1,092 were Satin-matte or Semi-matte, and "satin"
            # missed 451 genuine satins labelled Semi-matte.
            canonical = normalize_surface(surface)
            surf_lower = surface.lower()
            if canonical:
                results = [
                    r for r in results
                    if normalize_surface(r.get("surface")) == canonical
                ]
            else:
                results = [
                    r for r in results
                    if surf_lower in (r.get("surface", "") or "").lower()
                ]

        if query:
            results = self._rank_by_query(results, query)

        return results[offset:offset + limit]

    #: Relevance weights. A whole-word hit in the name beats a substring
    #: hit in someone's prose, which is the difference between searching
    #: "chun" and getting chun glazes rather than Sam Chung's catalogue.
    _MATCH_WEIGHTS = (
        ("name", 100, 60),
        ("subtype", 40, 30),
        ("description", 20, 10),
        ("notes", 20, 10),
    )

    def _rank_by_query(self, recipes: list[dict], query: str) -> list[dict]:
        """Filter to matches, ordered by how well they match.

        Previously this was an unranked filter - anything containing the
        substring anywhere passed, and the result was then sliced in
        corpus order, so relevance was down to file ordering. Searching
        "chun" returned "Big Sky" and "Bleached Albany" ahead of "Blue
        Chun Glaze", because both mention the potter Sam Chung in their
        descriptions and "chun" is a substring of "Chung".

        Substring matching is kept as a weaker signal so prefix searches
        ("celad", "temmok") still work.
        """
        q = query.lower().strip()
        if not q:
            return recipes

        word = re.compile(rf"\b{re.escape(q)}\b")
        scored: list[tuple[int, dict]] = []

        for recipe in recipes:
            best = 0
            for field, word_score, substring_score in self._MATCH_WEIGHTS:
                haystack = (recipe.get(field) or "")
                if not isinstance(haystack, str):
                    continue
                haystack = haystack.lower()
                if word.search(haystack):
                    best = max(best, word_score)
                elif q in haystack:
                    best = max(best, substring_score)
            if best:
                scored.append((best, recipe))

        # Stable sort: equal scores keep their original corpus order.
        scored.sort(key=lambda pair: -pair[0])
        return [recipe for _, recipe in scored]

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
            # Raw labels collapsed to glossy/satin/matte. The raw counts
            # stay because "satin_carbon_trap" and "glossy_to_satin" carry
            # information a three-class label throws away; this is the
            # view you want for totals, which the raw one cannot give
            # across 40-odd overlapping spellings.
            "by_surface_normalized": {},
            "by_atmosphere": {},
        }

        for r in self._recipes:
            cone = str(r.get("cone", "unknown"))
            surface = r.get("surface", "unknown") or "unknown"
            atm = r.get("atmosphere", "unknown") or "unknown"

            stats["by_cone"][cone] = stats["by_cone"].get(cone, 0) + 1
            stats["by_surface"][surface] = stats["by_surface"].get(surface, 0) + 1
            stats["by_atmosphere"][atm] = stats["by_atmosphere"].get(atm, 0) + 1

            canonical = normalize_surface(r.get("surface")) or "unclassified"
            stats["by_surface_normalized"][canonical] = (
                stats["by_surface_normalized"].get(canonical, 0) + 1
            )

        # Sort by count descending
        for key in ["by_cone", "by_surface", "by_surface_normalized", "by_atmosphere"]:
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
