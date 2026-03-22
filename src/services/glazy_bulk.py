"""In-memory service for browsing 10k+ community glaze recipes from Glazy open data."""

import json
import math
from pathlib import Path
from typing import Optional


class CommunityRecipeService:
    """Loads Glazy bulk data into memory and provides search/filter/pagination."""

    def __init__(self, data_path: Path):
        self.recipes: list[dict] = []
        self._by_id: dict[int, dict] = {}
        self._cone_index: dict[str, list[int]] = {}
        self._surface_index: dict[str, list[int]] = {}
        self._subtype_index: dict[str, list[int]] = {}
        self._atmosphere_index: dict[str, list[int]] = {}
        self._load(data_path)

    def _load(self, data_path: Path):
        if not data_path.exists():
            return
        with open(data_path, "r", encoding="utf-8") as f:
            self.recipes = json.load(f)

        # Precompute UMF for each recipe from percent analysis
        from src.models.materials import OXIDE_MOLECULAR_WEIGHTS

        for i, r in enumerate(self.recipes):
            r["_idx"] = i
            self._by_id[r["id"]] = r

            # Build indexes
            cone = r.get("cone", "")
            if cone:
                self._cone_index.setdefault(cone, []).append(i)
            surface = (r.get("surface") or "").lower()
            if surface:
                self._surface_index.setdefault(surface, []).append(i)
            subtype = r.get("subtype", "")
            if subtype:
                self._subtype_index.setdefault(subtype, []).append(i)
            for atm in r.get("atmospheres", []):
                self._atmosphere_index.setdefault(atm.lower(), []).append(i)

            # Compute approximate SiO2/Al2O3 UMF values from percent analysis
            analysis = r.get("analysis", {})
            sio2_pct = analysis.get("SiO2", 0)
            al2o3_pct = analysis.get("Al2O3", 0)
            if sio2_pct and al2o3_pct:
                # Convert weight% to moles
                sio2_mol = sio2_pct / 60.08
                al2o3_mol = al2o3_pct / 101.96
                r["_sio2_umf"] = round(sio2_mol / max(al2o3_mol, 0.001), 2)
                r["_al2o3_umf"] = round(al2o3_mol, 4)
                r["_si_al_ratio"] = round(sio2_mol / max(al2o3_mol, 0.001), 1)
            else:
                r["_sio2_umf"] = 0
                r["_al2o3_umf"] = 0
                r["_si_al_ratio"] = 0

    @property
    def total(self) -> int:
        return len(self.recipes)

    def search(
        self,
        query: Optional[str] = None,
        cone: Optional[str] = None,
        surface: Optional[str] = None,
        atmosphere: Optional[str] = None,
        subtype: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict:
        """Search and filter community recipes with pagination."""
        # Start with candidate indexes
        candidates = None

        if cone and cone in self._cone_index:
            candidates = set(self._cone_index[cone])
        if surface:
            surface_lower = surface.lower()
            idx = set(self._surface_index.get(surface_lower, []))
            candidates = idx if candidates is None else candidates & idx
        if atmosphere:
            atm_lower = atmosphere.lower()
            idx = set(self._atmosphere_index.get(atm_lower, []))
            candidates = idx if candidates is None else candidates & idx
        if subtype:
            idx = set(self._subtype_index.get(subtype, []))
            candidates = idx if candidates is None else candidates & idx

        if candidates is not None:
            results = [self.recipes[i] for i in sorted(candidates)]
        else:
            results = self.recipes

        # Text search on name, subtype, and description
        if query:
            query_lower = query.lower()
            terms = query_lower.split()
            results = [
                r for r in results
                if all(
                    t in r.get("name", "").lower()
                    or t in r.get("subtype", "").lower()
                    or t in r.get("description", "").lower()
                    for t in terms
                )
            ]
            # Sort by relevance: name matches first, then subtype, then description
            def _relevance(r):
                name_l = r.get("name", "").lower()
                sub_l = r.get("subtype", "").lower()
                score = 0
                for t in terms:
                    if t in name_l:
                        score += 10
                    if t in sub_l:
                        score += 5
                return -score
            results.sort(key=_relevance)

        total = len(results)
        total_pages = max(1, math.ceil(total / page_size))
        page = max(1, min(page, total_pages))
        start = (page - 1) * page_size
        page_results = results[start : start + page_size]

        return {
            "recipes": [self._format(r) for r in page_results],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_by_id(self, recipe_id: int) -> Optional[dict]:
        r = self._by_id.get(recipe_id)
        if r:
            return self._format(r, detail=True)
        return None

    def stull_neighbors(
        self,
        sio2: float,
        al2o3: float,
        radius: float = 0.5,
        limit: int = 50,
    ) -> list[dict]:
        """Find recipes near a point on the Stull chart (SiO2 vs Al2O3 UMF space)."""
        # Use ratio-based proximity since we have approximate UMF
        neighbors = []
        for r in self.recipes:
            r_sio2 = r.get("_sio2_umf", 0)
            r_al2o3 = r.get("_al2o3_umf", 0)
            if r_sio2 == 0:
                continue
            dist = math.sqrt((r_sio2 - sio2) ** 2 + ((r_al2o3 - al2o3) * 10) ** 2)
            if dist <= radius:
                entry = self._format(r)
                entry["distance"] = round(dist, 3)
                entry["sio2_umf"] = r_sio2
                entry["al2o3_umf"] = r_al2o3
                neighbors.append(entry)

        neighbors.sort(key=lambda x: x["distance"])
        return neighbors[:limit]

    def stull_scatter(self, limit: int = 500) -> list[dict]:
        """Get a sample of recipes for Stull chart overlay (lightweight)."""
        # Sample evenly across the dataset
        step = max(1, len(self.recipes) // limit)
        points = []
        for i in range(0, len(self.recipes), step):
            r = self.recipes[i]
            if r.get("_sio2_umf", 0) > 0:
                points.append({
                    "id": r["id"],
                    "name": r["name"],
                    "sio2": r["_sio2_umf"],
                    "al2o3": r["_al2o3_umf"],
                    "surface": r.get("surface", ""),
                    "cone": r.get("cone", ""),
                })
            if len(points) >= limit:
                break
        return points

    def stats(self) -> dict:
        """Get aggregate statistics about the community recipes."""
        from collections import Counter

        cones = Counter()
        surfaces = Counter()
        subtypes = Counter()
        atmospheres = Counter()

        for r in self.recipes:
            if r.get("cone"):
                cones[r["cone"]] += 1
            if r.get("surface"):
                surfaces[r["surface"]] += 1
            if r.get("subtype"):
                subtypes[r["subtype"]] += 1
            for a in r.get("atmospheres", []):
                atmospheres[a] += 1

        return {
            "total_recipes": len(self.recipes),
            "cones": dict(cones.most_common(20)),
            "surfaces": dict(surfaces.most_common(15)),
            "subtypes": dict(subtypes.most_common(25)),
            "atmospheres": dict(atmospheres.most_common(10)),
        }

    def get_filter_options(self) -> dict:
        """Get unique values for each filter field."""
        return {
            "cones": sorted(self._cone_index.keys(), key=lambda c: self._cone_sort_key(c)),
            "surfaces": sorted(self._surface_index.keys()),
            "subtypes": sorted(self._subtype_index.keys()),
            "atmospheres": sorted(self._atmosphere_index.keys()),
        }

    @staticmethod
    def _cone_sort_key(cone: str) -> tuple:
        """Sort cones numerically."""
        parts = cone.replace(" ", "").split("-")
        try:
            first = int(parts[0]) if not parts[0].startswith("0") else -int(parts[0][1:])
            return (first,)
        except ValueError:
            return (999,)

    @staticmethod
    def _format(r: dict, detail: bool = False) -> dict:
        """Format a recipe for API output."""
        out = {
            "id": r["id"],
            "name": r["name"],
            "cone": r.get("cone", ""),
            "surface": r.get("surface", ""),
            "atmospheres": r.get("atmospheres", []),
            "subtype": r.get("subtype", ""),
        }
        if detail:
            out["description"] = r.get("description", "")
            out["ingredients"] = r.get("ingredients", [])
            out["analysis"] = r.get("analysis", {})
            out["sio2_umf"] = r.get("_sio2_umf", 0)
            out["al2o3_umf"] = r.get("_al2o3_umf", 0)
            out["si_al_ratio"] = r.get("_si_al_ratio", 0)
        else:
            out["description"] = (r.get("description") or "")[:100]
            out["ingredient_count"] = len(r.get("ingredients", []))
        return out
