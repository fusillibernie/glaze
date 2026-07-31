"""Clay body database - loads data/materials/clay_bodies.json.

Previously unused: the JSON has real per-body COE, shrinkage and firing
data, but every caller that needed a clay body only had the ClayBody enum
(name only, no chemistry). This gives the glaze-fit calculation somewhere
to resolve an actual coefficient of expansion instead of a single hardcoded
default of 6.0 for every body.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "materials"


class ClayBodyDatabase:
    """Database of named clay bodies with fit-relevant properties."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self._bodies: list[dict] = []
        self._by_name: dict[str, dict] = {}
        self._loaded = False

    def load(self) -> None:
        path = self.data_dir / "clay_bodies.json"
        if not path.exists():
            self._loaded = True
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = next((k for k, v in data.items() if isinstance(v, list)), None)
            self._bodies = data.get(key, []) if key else []
            self._by_name = {b["name"].lower(): b for b in self._bodies if b.get("name")}
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Error loading clay_bodies.json: %s", e)
            self._bodies = []
            self._by_name = {}
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get_all(self) -> list[dict]:
        self._ensure_loaded()
        return list(self._bodies)

    def get(self, name: str) -> Optional[dict]:
        """Look up a named clay body (e.g. 'Standard Stoneware')."""
        self._ensure_loaded()
        result = self._by_name.get(name.lower())
        if result:
            return result
        name_lower = name.lower()
        candidates = sorted(k for k in self._by_name if k.startswith(name_lower))
        return self._by_name[candidates[0]] if candidates else None

    def get_by_type(self, clay_body_type: str) -> list[dict]:
        """All named bodies matching a ClayBody enum type (e.g. 'stoneware')."""
        self._ensure_loaded()
        return [b for b in self._bodies if b.get("type") == clay_body_type]

    def get_default_coe(self, clay_body_type: str) -> Optional[float]:
        """Average COE across named bodies of a given type.

        Used when the caller only has a broad ClayBody enum value (e.g.
        "stoneware") rather than a specific named body - still far better
        than one fixed number for every body of that type.
        """
        matches = [b["coe"] for b in self.get_by_type(clay_body_type) if b.get("coe")]
        return round(sum(matches) / len(matches), 2) if matches else None
