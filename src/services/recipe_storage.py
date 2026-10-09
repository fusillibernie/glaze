"""Persistent storage for the user's saved recipes (Recipe tab "Save" button).

Previously localStorage-only in the browser - clearing the browser or
switching devices silently lost every saved recipe. Storage shape mirrors
the fix applied to firing results this session: one JSON file, atomic
writes (temp file + os.replace), and dedup by id on load, since that
class of bug (data loss on save/reload) already bit this app once.
"""

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "saved_recipes" / "saved_recipes.json"


class RecipeStorage:
    """CRUD for the user's saved recipes, backed by one JSON file."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or DEFAULT_PATH
        self._recipes: list[dict] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                seen_ids = set()
                deduped = []
                for r in data:
                    rid = r.get("id")
                    if rid and rid in seen_ids:
                        continue
                    if rid:
                        seen_ids.add(rid)
                    deduped.append(r)
                self._recipes = deduped
            except (json.JSONDecodeError, IOError) as e:
                logger.error("Error loading %s: %s", self.path, e)
                self._recipes = []
        self._loaded = True

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._recipes, f, indent=2)
            os.replace(tmp_path, self.path)
        except BaseException:
            os.unlink(tmp_path)
            raise

    def get_all(self) -> list[dict]:
        self._ensure_loaded()
        return list(self._recipes)

    def get(self, recipe_id: str) -> Optional[dict]:
        self._ensure_loaded()
        return next((r for r in self._recipes if r.get("id") == recipe_id), None)

    def save(self, recipe: dict) -> dict:
        """Insert or update a recipe.

        Matches the UI's existing semantics: an explicit id updates that
        record; otherwise a name collision updates the existing record
        (a resave of the same recipe name replaces it, as it always has
        in the localStorage version); otherwise a new record is created.
        """
        self._ensure_loaded()
        recipe = dict(recipe)

        existing_idx = None
        if recipe.get("id"):
            existing_idx = next(
                (i for i, r in enumerate(self._recipes) if r.get("id") == recipe["id"]), None
            )
        if existing_idx is None and recipe.get("name"):
            existing_idx = next(
                (i for i, r in enumerate(self._recipes) if r.get("name") == recipe["name"]), None
            )

        if existing_idx is not None:
            recipe["id"] = self._recipes[existing_idx].get("id") or recipe.get("id") or uuid.uuid4().hex[:12]
            self._recipes[existing_idx] = recipe
        else:
            recipe["id"] = recipe.get("id") or uuid.uuid4().hex[:12]
            self._recipes.insert(0, recipe)

        self._save()
        return recipe

    def delete(self, recipe_id: str) -> bool:
        self._ensure_loaded()
        before = len(self._recipes)
        self._recipes = [r for r in self._recipes if r.get("id") != recipe_id]
        if len(self._recipes) == before:
            return False
        self._save()
        return True
