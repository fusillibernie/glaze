"""Tests for the clay body database.

Before this service existed, the 15 named bodies in
data/materials/clay_bodies.json (each with a real COE) were unreachable by
any code path - the only clay-body concept the app could resolve was the
bare ClayBody enum, and every glaze-fit check used one hardcoded COE
default regardless of body.
"""

import pytest

from src.services.clay_body_db import ClayBodyDatabase


@pytest.fixture
def db():
    database = ClayBodyDatabase()
    database.load()
    return database


class TestLoading:
    def test_loads_all_bodies(self, db):
        assert len(db.get_all()) == 15

    def test_every_body_has_a_coe(self, db):
        assert all(b.get("coe") for b in db.get_all())


class TestLookup:
    def test_get_by_exact_name(self, db):
        body = db.get("Standard Stoneware")
        assert body is not None
        assert body["coe"] == 6.5

    def test_get_is_case_insensitive(self, db):
        assert db.get("standard stoneware") is not None

    def test_get_prefix_match(self, db):
        assert db.get("Standard Stone") is not None

    def test_get_unknown_returns_none(self, db):
        assert db.get("Not A Real Body") is None


class TestByType:
    def test_get_by_type_stoneware(self, db):
        bodies = db.get_by_type("stoneware")
        assert len(bodies) >= 2
        assert all(b["type"] == "stoneware" for b in bodies)

    def test_get_by_type_unknown_returns_empty(self, db):
        assert db.get_by_type("nonexistent_type") == []


class TestDefaultCoe:
    def test_average_across_type(self, db):
        stoneware_coes = [b["coe"] for b in db.get_by_type("stoneware")]
        expected = round(sum(stoneware_coes) / len(stoneware_coes), 2)
        assert db.get_default_coe("stoneware") == expected

    def test_unknown_type_returns_none(self, db):
        assert db.get_default_coe("nonexistent_type") is None

    def test_porcelain_lower_than_earthenware(self, db):
        """Sanity check against real ceramics: porcelain bodies run lower
        expansion than earthenware bodies."""
        assert db.get_default_coe("porcelain") < db.get_default_coe("earthenware")
