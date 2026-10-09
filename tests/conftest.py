"""Pytest configuration and fixtures."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """FastAPI test client with isolated on-disk stores.

    api.main.predictor and api.main.recipe_storage are module-level
    singletons backed by real files under data/. Without overriding both,
    any test that writes through them (submitting a firing result, saving a
    recipe) would mutate real app data - exactly the bug that made every
    pytest run permanently add a "Test Recipe" entry to the tracked
    firing_results.json before predictor was isolated here. Point both at
    per-test tmp_path files instead.
    """
    import api.main as main_module
    from src.services.predictor import OutcomePredictor
    from src.services.recipe_storage import RecipeStorage

    monkeypatch.setattr(
        main_module, "predictor",
        OutcomePredictor(results_path=tmp_path / "test_firing_results.json"),
    )
    monkeypatch.setattr(
        main_module, "recipe_storage",
        RecipeStorage(path=tmp_path / "test_saved_recipes.json"),
    )
    return TestClient(main_module.app)


GLAZY_CORPUS = Path(__file__).parent.parent / "data" / "glazy_bulk" / "glazy_recipes.json"

#: The 7.5MB Glazy corpus is gitignored, so it exists on a developer
#: machine and not in CI. Tests that genuinely need the full corpus use
#: this marker and skip cleanly without it; tests that only exercise logic
#: should use `synthetic_recipe_db` instead, so they run everywhere. Six
#: tests had silently depended on the local file and passed only because
#: it happened to be present.
requires_glazy_corpus = pytest.mark.skipif(
    not GLAZY_CORPUS.exists(),
    reason="needs the gitignored Glazy corpus (run scripts/download_glazy_data.py)",
)


@pytest.fixture
def synthetic_recipe_db(tmp_path):
    """A RecipeDatabase over a small, known corpus that ships with the tests.

    Built to exercise search behaviour that the real corpus only happened
    to demonstrate: a potter's surname that contains a glaze name ("Sam
    Chung" vs "chun"), and surface labels whose words overlap
    ("Satin-matte", "Semi-matte").
    """
    import json
    from src.services.recipe_db import RecipeDatabase

    corpus = [
        {"id": 1, "name": "Blue Chun Glaze", "cone": "10", "surface": "Glossy",
         "atmospheres": ["Reduction"], "description": "A classic chun."},
        {"id": 2, "name": "Chun Clear", "cone": "10", "surface": "Glossy",
         "atmospheres": ["Reduction"], "description": ""},
        {"id": 3, "name": "Purple Chun", "cone": "10", "surface": "Glossy",
         "atmospheres": ["Reduction"], "description": ""},
        # Matches "chun" only as a substring of the potter's name.
        {"id": 4, "name": "Big Sky", "cone": "10", "surface": "Glossy",
         "atmospheres": ["Reduction"], "description": "From Sam Chung."},
        {"id": 5, "name": "Brown Steel - Chung", "cone": "10", "surface": "Glossy",
         "atmospheres": ["Reduction"], "description": "From Sam Chung."},
        # Mentions chun only in prose: a weaker, but real, match.
        {"id": 6, "name": "Opal Blue", "cone": "10", "surface": "Glossy",
         "atmospheres": ["Reduction"], "description": "A chun-like opalescent glaze."},
        {"id": 7, "name": "Buttery Matte", "cone": "6", "surface": "Matte",
         "atmospheres": ["Oxidation"]},
        {"id": 8, "name": "Soft Satin", "cone": "6", "surface": "Semi-matte",
         "atmospheres": ["Oxidation"]},
        {"id": 9, "name": "Silk", "cone": "6", "surface": "Satin-matte",
         "atmospheres": ["Oxidation"]},
        {"id": 10, "name": "Celadon Green", "cone": "10", "surface": "Glossy",
         "atmospheres": ["Reduction"]},
        # A freeform surface label with no canonical class - search must
        # still find it by substring.
        {"id": 11, "name": "Shino Smoke", "cone": "10", "surface": "satin_carbon_trap",
         "atmospheres": ["Reduction"]},
    ]
    bulk = tmp_path / "glazy_bulk"
    bulk.mkdir()
    (bulk / "glazy_recipes.json").write_text(json.dumps(corpus), encoding="utf-8")
    db = RecipeDatabase(tmp_path)
    db.load()
    return db


@pytest.fixture
def data_dir():
    """Get path to data directory."""
    return Path(__file__).parent.parent / "data"


@pytest.fixture
def materials_dir(data_dir):
    """Get path to materials data directory."""
    return data_dir / "materials"


@pytest.fixture
def recipes_dir(data_dir):
    """Get path to recipes data directory."""
    return data_dir / "recipes"
