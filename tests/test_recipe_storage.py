"""Tests for backend recipe persistence.

Previously the Recipe tab's Save button only wrote to localStorage - this
covers the backend replacement, using the same atomic-write and dedup
guarantees the firing-results storage fix established this session.
"""

import json

import pytest

from src.services.recipe_storage import RecipeStorage


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "saved_recipes.json"


@pytest.fixture
def storage(store_path):
    return RecipeStorage(path=store_path)


class TestSaveAndRetrieve:
    def test_save_assigns_an_id(self, storage):
        saved = storage.save({"name": "Clear Cone 6"})
        assert saved["id"]

    def test_saved_recipe_appears_in_get_all(self, storage):
        storage.save({"name": "Clear Cone 6"})
        names = [r["name"] for r in storage.get_all()]
        assert "Clear Cone 6" in names

    def test_get_by_id(self, storage):
        saved = storage.save({"name": "Celadon"})
        fetched = storage.get(saved["id"])
        assert fetched["name"] == "Celadon"

    def test_get_unknown_id_returns_none(self, storage):
        assert storage.get("nope") is None

    def test_new_recipes_appear_first(self, storage):
        storage.save({"name": "First"})
        storage.save({"name": "Second"})
        assert storage.get_all()[0]["name"] == "Second"


class TestUpsertSemantics:
    """Matches the localStorage version's existing behavior: resaving the
    same name updates that record instead of creating a duplicate."""

    def test_resave_same_name_updates_in_place(self, storage):
        first = storage.save({"name": "Tenmoku", "ingredients": [{"name": "A", "percentage": 100}]})
        storage.save({"name": "Tenmoku", "ingredients": [{"name": "B", "percentage": 100}]})

        all_recipes = storage.get_all()
        assert len(all_recipes) == 1
        assert all_recipes[0]["id"] == first["id"]
        assert all_recipes[0]["ingredients"][0]["name"] == "B"

    def test_explicit_id_updates_even_if_name_changed(self, storage):
        first = storage.save({"name": "Original Name"})
        storage.save({"id": first["id"], "name": "Renamed"})

        all_recipes = storage.get_all()
        assert len(all_recipes) == 1
        assert all_recipes[0]["name"] == "Renamed"

    def test_different_names_do_not_collide(self, storage):
        storage.save({"name": "A"})
        storage.save({"name": "B"})
        assert len(storage.get_all()) == 2


class TestDelete:
    def test_delete_removes_recipe(self, storage):
        saved = storage.save({"name": "Doomed"})
        assert storage.delete(saved["id"]) is True
        assert storage.get(saved["id"]) is None

    def test_delete_unknown_id_returns_false(self, storage):
        assert storage.delete("nope") is False

    def test_delete_only_removes_target(self, storage):
        keep = storage.save({"name": "Keep"})
        gone = storage.save({"name": "Gone"})
        storage.delete(gone["id"])
        assert [r["id"] for r in storage.get_all()] == [keep["id"]]


class TestPersistenceAcrossReload:
    def test_survives_new_instance(self, store_path):
        RecipeStorage(path=store_path).save({"name": "Persisted"})
        reloaded = RecipeStorage(path=store_path)
        assert reloaded.get_all()[0]["name"] == "Persisted"

    def test_deep_fields_round_trip(self, store_path):
        """Nested ingredient/colorant/umf data must survive exactly, not
        just top-level fields."""
        recipe = {
            "name": "Complex",
            "cone": "6",
            "ingredients": [{"name": "Custer Feldspar", "percentage": 50.0}],
            "colorants": [{"name": "Cobalt Carbonate", "percentage": 1.5}],
            "umf": {"SiO2": 3.5, "Al2O3": 0.4, "surface": "glossy"},
        }
        RecipeStorage(path=store_path).save(recipe)
        reloaded = RecipeStorage(path=store_path).get_all()[0]
        assert reloaded["ingredients"] == recipe["ingredients"]
        assert reloaded["colorants"] == recipe["colorants"]
        assert reloaded["umf"] == recipe["umf"]

    def test_duplicate_ids_on_disk_collapse_to_one(self, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps([
            {"id": "dup", "name": "First"},
            {"id": "dup", "name": "Second"},
        ]))
        storage = RecipeStorage(path=store_path)
        assert len(storage.get_all()) == 1
        assert storage.get_all()[0]["name"] == "First"

    def test_save_leaves_no_temp_files_behind(self, store_path, tmp_path):
        RecipeStorage(path=store_path).save({"name": "t"})
        assert list(tmp_path.glob("*.tmp")) == []
