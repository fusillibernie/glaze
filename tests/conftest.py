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
