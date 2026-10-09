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
    Colorant,
    ConeTemperature,
    AtmosphereType,
    GlazeSurface,
    GlazeType,
)
from ..models.umf import UMF


GLAZY_API_BASE = "https://api.glazy.org/api"
GLAZY_CDN = "https://ddms6z64wp3a6.cloudfront.net"
GLAZY_RECIPE_URL = "https://glazy.org/recipes/{id}"

# Glazy's atmosphere names -> ours. "Salt & Soda" is one Glazy category
# covering both. Raku and Luster have no equivalent here and are left
# unmapped rather than forced onto something they are not.
_GLAZY_ATMOSPHERES = {
    "oxidation": [AtmosphereType.OXIDATION],
    "reduction": [AtmosphereType.REDUCTION],
    "neutral": [AtmosphereType.NEUTRAL],
    "wood": [AtmosphereType.WOOD],
    "salt & soda": [AtmosphereType.SALT, AtmosphereType.SODA],
    "salt": [AtmosphereType.SALT],
    "soda": [AtmosphereType.SODA],
}


def glazy_recipe_url(glazy_id) -> Optional[str]:
    """Public page for a Glazy recipe, or None without an id."""
    return GLAZY_RECIPE_URL.format(id=glazy_id) if glazy_id else None


def _to_float(value, default: float = 0.0) -> float:
    """Glazy sends numbers as strings ("54.8000"); tolerate both."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        # Build query parameters - Glazy API v2 uses 'keywords' for search
        # and ignores separate cone/atmosphere/surface params
        params = {"limit": limit, "base_type_id": 460}  # 460 = glazes

        # Combine all search terms into keywords
        keywords_parts = []
        if query:
            keywords_parts.append(query)
        if cone:
            keywords_parts.append(f"cone {cone}")
        if atmosphere:
            keywords_parts.append(atmosphere.replace("_", " "))
        if surface:
            keywords_parts.append(surface)
        if keywords_parts:
            params["keywords"] = " ".join(keywords_parts)

        # Try API
        try:
            response = self._client.get(
                f"{GLAZY_API_BASE}/search",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("data", []):
                # Build image URL from selectedImage
                image_url = item.get("image_url")
                selected_img = item.get("selectedImage")
                if not image_url and selected_img and selected_img.get("filename"):
                    rid = str(item.get("id", ""))
                    last2 = rid[-2:].zfill(2) if rid else "00"
                    image_url = f"{GLAZY_CDN}/uploads/recipes/{last2}/s_{selected_img['filename']}"

                # Cone range from new API format
                cone = item.get("cone")
                if not cone:
                    from_cone = item.get("fromOrtonConeName", "")
                    to_cone = item.get("toOrtonConeName", "")
                    cone = f"{from_cone} - {to_cone}" if from_cone and to_cone and from_cone != to_cone else from_cone

                results.append(GlazySearchResult(
                    glazy_id=item.get("id"),
                    name=item.get("name", ""),
                    creator=item.get("createdByUserName") or item.get("user", {}).get("name"),
                    cone_range=cone,
                    atmosphere=item.get("atmosphereTypeName") or item.get("atmosphere"),
                    surface=item.get("surfaceTypeName") or item.get("surface_type"),
                    image_url=image_url,
                    description=item.get("description"),
                ))
            return results

        except (httpx.HTTPError, json.JSONDecodeError):
            # Return cached results if API fails
            cached = self._search_cache(query, cone, atmosphere, surface, limit)
            if cached:
                return cached
            # Fall back to local recipe files
            return self._search_local_recipes(query, cone, atmosphere, surface, limit)

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
        """Parse a Glazy recipe payload into a GlazeRecipe.

        Written against Glazy's current API. The previous parser read an
        obsolete schema - `components`, `amount`, `cone`, `atmosphere`,
        `surface_type`, `umf` - of which only `name` still exists. Every
        import therefore came back with the right name and nothing else:
        no ingredients, and cone, atmosphere and surface silently replaced
        by defaults. A cone 9-10 reduction chun imported as an empty cone
        6 oxidation recipe, and the UI reported success.

        The old field names are still read as fallbacks, so anything
        cached in the old shape keeps parsing.
        """
        # A fresh fetch caches the full {"data": {...}} response, so a
        # cache hit arrives wrapped while a live fetch arrives unwrapped.
        # Accept either rather than depend on which path got here.
        if isinstance(data.get("data"), dict):
            data = data["data"]

        # Ingredients. `isAdditional` marks colourant additions on top of
        # the 100% base, which used to be discarded along with everything
        # else.
        ingredients, colorants = [], []
        for comp in data.get("materialComponents") or data.get("components") or []:
            material = comp.get("material") or {}
            name = material.get("name", "")
            pct = _to_float(comp.get("percentageAmount", comp.get("amount")))
            if not name or pct <= 0:
                continue
            if comp.get("isAdditional"):
                colorants.append(Colorant(material_name=name, percentage=pct))
            else:
                ingredients.append(GlazeIngredient(
                    material_name=name,
                    percentage=pct,
                    material_id=str(material.get("id", comp.get("material_id", ""))),
                ))

        cone = self._parse_cone(data)

        # Atmospheres: Glazy lists several, and a recipe can genuinely suit
        # more than one. Keep them all.
        atmospheres: list[AtmosphereType] = []
        names = [a.get("name", "") for a in data.get("atmospheres") or [] if isinstance(a, dict)]
        if not names and data.get("atmosphere"):
            names = [data["atmosphere"]]
        for raw in names:
            key = str(raw).strip().lower()
            mapped = _GLAZY_ATMOSPHERES.get(key)
            if mapped is None:
                # Not a name we map exactly ("Heavy Reduction", say) - fall
                # back to the broad family rather than to the oxidation
                # default, which would silently invert it. Kept to plain
                # REDUCTION rather than HEAVY_REDUCTION because the defect
                # rules key on "reduction" and would otherwise stop firing.
                if "reduction" in key:
                    mapped = [AtmosphereType.REDUCTION]
                elif "oxidation" in key:
                    mapped = [AtmosphereType.OXIDATION]
                else:
                    mapped = []
            for atm in mapped:
                if atm not in atmospheres:
                    atmospheres.append(atm)

        surface = self._parse_surface(data.get("surfaceTypeName") or data.get("surface_type"))

        # Glazy computes its own UMF; numbers arrive as strings.
        umf = None
        umf_data = (data.get("analysis") or {}).get("umfAnalysis") or data.get("umf")
        if umf_data:
            umf = UMF(**{
                oxide: _to_float(umf_data.get(oxide))
                for oxide in ("SiO2", "Al2O3", "B2O3", "Na2O", "K2O", "Li2O",
                              "CaO", "MgO", "BaO", "SrO", "ZnO", "Fe2O3",
                              "TiO2", "P2O5")
            })

        return GlazeRecipe(
            name=data.get("name", ""),
            ingredients=ingredients,
            colorants=colorants,
            target_cone=cone,
            suitable_atmospheres=atmospheres or [AtmosphereType.OXIDATION],
            umf=umf,
            expected_surface=surface,
            glazy_id=data.get("id"),
            source="Glazy.org",
            author=data.get("user", {}).get("name"),
            notes=data.get("description"),
        )

    @staticmethod
    def _parse_cone(data: dict) -> ConeTemperature:
        """Target cone from Glazy's from/to range.

        Prefers the top of the range - the cone a "9-10" glaze is meant to
        mature at. Glazy lists cones this app has no enum value for (05, 4
        and so on), so those snap to the nearest cone that does exist
        rather than silently becoming cone 6. The leading-zero series is
        the low-fire end and runs the other way: 06 is far cooler than 6.
        """
        def signed(text):
            text = str(text).strip()
            try:
                return -int(text[1:]) if len(text) > 1 and text.startswith("0") else int(text)
            except ValueError:
                return None

        available = [(signed(c.value), c) for c in ConeTemperature]
        for raw in (data.get("toOrtonConeName"), data.get("fromOrtonConeName"), data.get("cone")):
            if raw in (None, ""):
                continue
            try:
                return ConeTemperature(str(raw).strip())
            except ValueError:
                value = signed(raw)
                if value is not None:
                    return min(available, key=lambda pair: abs(pair[0] - value))[1]
        return ConeTemperature.CONE_6

    @staticmethod
    def _parse_surface(raw) -> GlazeSurface:
        """Map Glazy's surface vocabulary onto ours.

        Reuses the same normalizer the recipe search uses, so "Satin-matte"
        and "Semi-matte" land on satin rather than matte. Stony and dry
        mattes keep their own class.
        """
        from ..services.surface_model import normalize_surface

        text = str(raw or "").strip().lower()
        if "dry" in text or "stony" in text:
            return GlazeSurface.DRY_MATTE
        canonical = normalize_surface(text)
        return {
            "glossy": GlazeSurface.GLOSSY,
            "satin": GlazeSurface.SATIN,
            "matte": GlazeSurface.MATTE,
        }.get(canonical, GlazeSurface.GLOSSY)

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

    def _search_local_recipes(
        self,
        query: Optional[str],
        cone: Optional[str],
        atmosphere: Optional[str],
        surface: Optional[str],
        limit: int,
    ) -> list[GlazySearchResult]:
        """Search bundled local recipe JSON files as a fallback."""
        results = []
        recipes_dir = Path(__file__).parent.parent.parent / "data" / "recipes"
        if not recipes_dir.exists():
            return results

        recipe_id = 100000  # Local recipe IDs start high to avoid collisions

        for json_file in recipes_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Handle different JSON structures
                recipes = []
                for key in data:
                    if isinstance(data[key], list):
                        recipes = data[key]
                        break

                for recipe in recipes:
                    name = recipe.get("name", "")
                    r_cone = recipe.get("cone", "")
                    r_atm = recipe.get("atmosphere", "")
                    r_surface = recipe.get("surface", "")

                    # Apply filters
                    if query and query.lower() not in name.lower():
                        continue
                    if cone and str(cone) != str(r_cone):
                        continue
                    if atmosphere and atmosphere.lower() != r_atm.lower():
                        continue
                    if surface and surface.lower() != r_surface.lower():
                        continue

                    recipe_id += 1
                    ingredients_desc = ", ".join(
                        f"{i.get('material', '')} {i.get('percentage', '')}%"
                        for i in recipe.get("ingredients", [])
                    )
                    results.append(GlazySearchResult(
                        glazy_id=recipe_id,
                        name=name,
                        creator="Local Recipe",
                        cone_range=str(r_cone),
                        atmosphere=r_atm,
                        surface=r_surface,
                        image_url=None,
                        description=recipe.get("description", ingredients_desc),
                    ))

                    if len(results) >= limit:
                        return results

            except (json.JSONDecodeError, IOError):
                continue

        return results
