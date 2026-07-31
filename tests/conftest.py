"""Pytest configuration and fixtures."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """FastAPI test client with an isolated firing-results store.

    api.main.predictor is a module-level singleton backed by the real
    data/results/firing_results.json. Without this override, any test that
    posts to /api/results (e.g. test_submit_result) permanently mutates that
    tracked file - every pytest run added one more "Test Recipe" entry to
    production data. Point the singleton at a per-test tmp_path instead.
    """
    import api.main as main_module
    from src.services.predictor import OutcomePredictor

    monkeypatch.setattr(
        main_module, "predictor",
        OutcomePredictor(results_path=tmp_path / "test_firing_results.json"),
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
