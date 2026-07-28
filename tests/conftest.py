"""Pytest configuration and fixtures."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI test client."""
    from api.main import app
    return TestClient(app)


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
