"""Tests for firing-results persistence.

Guards against the storage bugs found in this session:
- FiringResult.from_dict() silently dropped fired_at and photos, so every
  load-then-save cycle rewrote timestamps to "now" and deleted photo records.
- _save_results() wrote in place with no atomicity.
- Duplicate result_ids on disk (however they got there) were loaded as
  separate entries instead of being deduplicated.
"""

import json
from datetime import datetime, timezone

import pytest

from src.models.results import FiringResult, ResultPhoto, SurfaceQuality
from src.services.predictor import OutcomePredictor


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "results.json"


class TestRoundTrip:
    def test_fired_at_survives_reload(self, store_path):
        original = datetime(2020, 1, 15, 9, 30, tzinfo=timezone.utc)
        predictor = OutcomePredictor(results_path=store_path)
        predictor.add_result(FiringResult(
            result_id="r1", recipe_name="Test", fired_at=original,
        ))

        reloaded = OutcomePredictor(results_path=store_path)
        assert reloaded.results[0].fired_at == original

    def test_photos_survive_reload(self, store_path):
        predictor = OutcomePredictor(results_path=store_path)
        predictor.add_result(FiringResult(
            result_id="r1", recipe_name="Test",
            photos=[ResultPhoto(photo_id="p1", url="/uploads/p1.jpg", caption="front")],
        ))

        reloaded = OutcomePredictor(results_path=store_path)
        assert len(reloaded.results[0].photos) == 1
        assert reloaded.results[0].photos[0].url == "/uploads/p1.jpg"
        assert reloaded.results[0].photos[0].caption == "front"

    def test_repeated_reload_save_does_not_drift(self, store_path):
        """The exact failure mode observed: fired_at reset on every cycle,
        so repeated reload+save silently rewrote history."""
        original = datetime(2020, 1, 15, 9, 30, tzinfo=timezone.utc)
        predictor = OutcomePredictor(results_path=store_path)
        predictor.add_result(FiringResult(result_id="r1", fired_at=original))

        for _ in range(5):
            p = OutcomePredictor(results_path=store_path)
            p._save_results()

        final = OutcomePredictor(results_path=store_path)
        assert final.results[0].fired_at == original


class TestDeduplication:
    def test_duplicate_ids_collapse_to_one(self, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps([
            {"result_id": "dup", "recipe_name": "First"},
            {"result_id": "dup", "recipe_name": "Second"},
            {"result_id": "unique", "recipe_name": "Third"},
        ]))

        predictor = OutcomePredictor(results_path=store_path)
        assert len(predictor.results) == 2
        assert predictor.results[0].recipe_name == "First"


class TestAtomicWrite:
    def test_save_leaves_no_temp_files_behind(self, store_path, tmp_path):
        predictor = OutcomePredictor(results_path=store_path)
        predictor.add_result(FiringResult(result_id="r1"))

        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []

    def test_existing_file_intact_if_save_fails(self, store_path, monkeypatch):
        predictor = OutcomePredictor(results_path=store_path)
        predictor.add_result(FiringResult(result_id="r1"))
        original_content = store_path.read_text()

        def boom(*a, **kw):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(json, "dump", boom)
        with pytest.raises(OSError):
            predictor.results.append(FiringResult(result_id="r2"))
            predictor._save_results()

        assert store_path.read_text() == original_content


class TestAddResult:
    def test_add_persists_immediately(self, store_path):
        predictor = OutcomePredictor(results_path=store_path)
        predictor.add_result(FiringResult(result_id="r1", recipe_name="Persisted"))

        assert store_path.exists()
        on_disk = json.loads(store_path.read_text())
        assert on_disk[0]["recipe_name"] == "Persisted"
