"""Client for Glazy.org API integration."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from ..models.materials import Material, MaterialType, MaterialAnalysis, OxideAnalysis
from ..models.glaze import (
    GlazeRecipe,
    GlazeIngredient,
    ConeTemperature,
    AtmosphereType,
    GlazeSurface,
    GlazeType,
)
from ..models.umf import UMF


GLAZY_API_BASE = "https://glazy.org/api"


@dataclass
class GlazySearchResult:
    """A search result from Glazy.org."""
    glazy_id: int
    name: str
    creator: Optional[str]
    cone_range: Optional[str]
    atmosphere: Optional[str]
    surface: Optional[str]
    image_url: Optional[str]
    description: Optional[str]


class GlazyClient:
    """Client for fetching data from Glazy.org.

    Note: Glazy.org's API may require authentication or have rate limits.
    This client provides both API access and local caching.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        api_key: Optional[str] = None,
    ):
        """Initialize the Glazy client.

        Args:
            cache_dir: Directory for caching API responses.
            api_key: Optional API key for Glazy.org.
        """
        self.cache_dir = cache_dir or Path(__file__).parent.parent.parent / "data" / "glazy_cache"
        self.api_key = api_key
        self._client = httpx.Client(timeout=30.0)

    def _get_headers(self) -> dict:
        """Get request headers."""
        headers = {
            "Accept": "application/json",
            "User-Agent": "GlazeFormulator/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def search_recipes(
        self,
        query: Optional[str] = None,
        cone: Optional[str] = None,
        atmosphere: Optional[str] = None,
        surface: Optional[str] = None,
        limit: int = 20,
    ) -> list[GlazySearchResult]:
        """Search for glaze recipes on Glazy.org.

        Args:
            query: Search query string.
            cone: Filter by cone (e.g., "6", "10").
            atmosphere: Filter by atmosphere ("oxidation", "reduction").
            surface: Filter by surface ("glossy", "matte", etc.).
            limit: Maximum results to return.

        Returns:
            List of search results.
        """
        # Build query parameters
        params = {"limit": limit}
        if query:
            params["search"] = query
        if cone:
            params["cone"] = cone
        if atmosphere:
            params["atmosphere"] = atmosphere
        if surface:
            params["surface"] = surface

        # Try API
        try:
            response = self._client.get(
                f"{GLAZY_API_BASE}/recipes",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("data", []):
                results.append(GlazySearchResult(
                    glazy_id=item.get("id"),
                    name=item.get("name", ""),
                    creator=item.get("user", {}).get("name"),
                    cone_range=item.get("cone"),
                    atmosphere=item.get("atmosphere"),
                    surface=item.get("surface_type"),
                    image_url=item.get("image_url"),
                    description=item.get("description"),
                ))
            return results

        except (httpx.HTTPError, json.JSONDecodeError):
            # Return cached results if API fails
            return self._search_cache(query, cone, atmosphere, surface, limit)

    def get_recipe(self, glazy_id: int) -> Optional[GlazeRecipe]:
        """Fetch a complete recipe from Glazy.org.

        Args:
            glazy_id: Glazy recipe ID.

        Returns:
            GlazeRecipe if found, None otherwise.
        """
        # Check cache first
        cached = self._load_from_cache("recipe", glazy_id)
        if cached:
            return self._parse_recipe(cached)

        # Fetch from API
        try:
            response = self._client.get(
                f"{GLAZY_API_BASE}/recipes/{glazy_id}",
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            # Cache the result
            self._save_to_cache("recipe", glazy_id, data)

            return self._parse_recipe(data.get("data", {}))

        except (httpx.HTTPError, json.JSONDecodeError):
            return None

    def get_material(self, glazy_id: int) -> Optional[Material]:
        """Fetch a material from Glazy.org.

        Args:
            glazy_id: Glazy material ID.

        Returns:
            Material if found, None otherwise.
        """
        # Check cache first
        cached = self._load_from_cache("material", glazy_id)
        if cached:
            return self._parse_material(cached)

        # Fetch from API
        try:
            response = self._client.get(
                f"{GLAZY_API_BASE}/materials/{glazy_id}",
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            # Cache the result
            self._save_to_cache("material", glazy_id, data)

            return self._parse_material(data.get("data", {}))

        except (httpx.HTTPError, json.JSONDecodeError):
            return None

    def _parse_recipe(self, data: dict) -> GlazeRecipe:
        """Parse Glazy API response into GlazeRecipe."""
        # Parse ingredients
        ingredients = []
        for comp in data.get("components", []):
            ingredients.append(GlazeIngredient(
                material_name=comp.get("material", {}).get("name", ""),
                percentage=comp.get("amount", 0),
                material_id=str(comp.get("material_id")),
            ))

        # Parse cone
        cone_str = data.get("cone", "6")
        try:
            cone = ConeTemperature(cone_str)
        except ValueError:
            cone = ConeTemperature.CONE_6

        # Parse atmosphere
        atm_str = data.get("atmosphere", "oxidation").lower()
        atmosphere = AtmosphereType.OXIDATION
        if "reduction" in atm_str:
            atmosphere = AtmosphereType.REDUCTION

        # Parse surface
        surface_str = data.get("surface_type", "glossy").lower()
        surface = GlazeSurface.GLOSSY
        if "matte" in surface_str:
            surface = GlazeSurface.MATTE
        elif "satin" in surface_str:
            surface = GlazeSurface.SATIN

        # Parse UMF if available
        umf = None
        if data.get("umf"):
            umf_data = data["umf"]
            umf = UMF(
                SiO2=umf_data.get("SiO2", 0),
                Al2O3=umf_data.get("Al2O3", 0),
                B2O3=umf_data.get("B2O3", 0),
                Na2O=umf_data.get("Na2O", 0),
                K2O=umf_data.get("K2O", 0),
                Li2O=umf_data.get("Li2O", 0),
                CaO=umf_data.get("CaO", 0),
                MgO=umf_data.get("MgO", 0),
                BaO=umf_data.get("BaO", 0),
                SrO=umf_data.get("SrO", 0),
                ZnO=umf_data.get("ZnO", 0),
            )

        return GlazeRecipe(
            name=data.get("name", ""),
            ingredients=ingredients,
            target_cone=cone,
            suitable_atmospheres=[atmosphere],
            umf=umf,
            expected_surface=surface,
            glazy_id=data.get("id"),
            source="Glazy.org",
            author=data.get("user", {}).get("name"),
            notes=data.get("description"),
        )

    def _parse_material(self, data: dict) -> Material:
        """Parse Glazy API response into Material."""
        # Parse oxide analysis
        analysis_data = data.get("analysis", {})
        oxide = OxideAnalysis(
            SiO2=analysis_data.get("SiO2", 0),
            Al2O3=analysis_data.get("Al2O3", 0),
            B2O3=analysis_data.get("B2O3", 0),
            Na2O=analysis_data.get("Na2O", 0),
            K2O=analysis_data.get("K2O", 0),
            Li2O=analysis_data.get("Li2O", 0),
            CaO=analysis_data.get("CaO", 0),
            MgO=analysis_data.get("MgO", 0),
            BaO=analysis_data.get("BaO", 0),
            SrO=analysis_data.get("SrO", 0),
            ZnO=analysis_data.get("ZnO", 0),
            Fe2O3=analysis_data.get("Fe2O3", 0),
            TiO2=analysis_data.get("TiO2", 0),
            LOI=analysis_data.get("LOI", 0),
        )

        # Determine material type
        name_lower = data.get("name", "").lower()
        mat_type = MaterialType.OTHER
        if "feldspar" in name_lower:
            mat_type = MaterialType.FELDSPAR
        elif "kaolin" in name_lower or "clay" in name_lower:
            mat_type = MaterialType.CLAY
        elif "silica" in name_lower or "flint" in name_lower:
            mat_type = MaterialType.SILICA
        elif "frit" in name_lower:
            mat_type = MaterialType.FRIT
        elif "ash" in name_lower:
            mat_type = MaterialType.ASH

        return Material(
            name=data.get("name", ""),
            material_type=mat_type,
            analysis=MaterialAnalysis(
                oxide_analysis=oxide,
                source="Glazy.org",
            ),
            glazy_id=data.get("id"),
            description=data.get("description"),
        )

    def _load_from_cache(self, item_type: str, item_id: int) -> Optional[dict]:
        """Load an item from cache."""
        cache_file = self.cache_dir / item_type / f"{item_id}.json"
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _save_to_cache(self, item_type: str, item_id: int, data: dict) -> None:
        """Save an item to cache."""
        cache_path = self.cache_dir / item_type
        cache_path.mkdir(parents=True, exist_ok=True)

        cache_file = cache_path / f"{item_id}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _search_cache(
        self,
        query: Optional[str],
        cone: Optional[str],
        atmosphere: Optional[str],
        surface: Optional[str],
        limit: int,
    ) -> list[GlazySearchResult]:
        """Search cached recipes."""
        results = []
        cache_path = self.cache_dir / "recipe"
        if not cache_path.exists():
            return results

        for cache_file in cache_path.glob("*.json"):
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Apply filters
            if query and query.lower() not in data.get("name", "").lower():
                continue
            if cone and str(cone) != str(data.get("cone", "")):
                continue

            results.append(GlazySearchResult(
                glazy_id=data.get("id", 0),
                name=data.get("name", ""),
                creator=data.get("user", {}).get("name"),
                cone_range=data.get("cone"),
                atmosphere=data.get("atmosphere"),
                surface=data.get("surface_type"),
                image_url=data.get("image_url"),
                description=data.get("description"),
            ))

            if len(results) >= limit:
                break

        return results
