"""Tests for defect/safety/material data sourced from Harry Fraser's
"Ceramic Faults and Their Remedies" (2nd ed, 2005): four new
data/reference/defect_guide.json entries, a quantified copper/lead
leaching note on safety_guide.json's PbO entry, and a splutter-tolerance
caveat on the Colemanite material.
"""

import json
from pathlib import Path

import pytest

DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def defect_guide():
    return json.loads((DATA / "reference" / "defect_guide.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def safety_guide():
    return json.loads((DATA / "reference" / "safety_guide.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def common_materials():
    return json.loads((DATA / "materials" / "common_materials.json").read_text(encoding="utf-8"))


class TestNewDefectEntries:
    @pytest.mark.parametrize("key", ["bittiness", "bloating", "blow_out", "colemanite_splutter"])
    def test_entry_exists_with_required_fields(self, defect_guide, key):
        entry = defect_guide["defects"][key]
        assert entry["category"]
        assert entry["summary"]
        assert entry["causes"]
        assert entry.get("remedies") or entry.get("chemistry_remedies")

    @pytest.mark.parametrize("key", ["bittiness", "bloating", "blow_out", "colemanite_splutter"])
    def test_attributed_to_fraser(self, defect_guide, key):
        entry = defect_guide["defects"][key]
        assert entry["cross_reference"]["source"] == "fraser-ceramic-faults-2005"

    def test_colemanite_splutter_has_chemistry(self, defect_guide):
        entry = defect_guide["defects"]["colemanite_splutter"]
        assert "27%" in entry["summary"]
        assert any("frit" in r.lower() for r in entry["chemistry_remedies"])

    def test_did_not_disturb_existing_entries(self, defect_guide):
        for key in ["crazing", "shivering", "crawling", "pinholing_pitting", "blistering", "dunting_cracking"]:
            assert key in defect_guide["defects"]


class TestQuantifiedLeadSafetyNote:
    def test_pbo_note_has_copper_interaction_numbers(self, safety_guide):
        note = safety_guide["concerning_oxides"]["PbO"]["note"]
        assert "12.8ppm" in note
        assert "0.1ppm" in note
        assert "copper" in note.lower()

    def test_original_fda_note_preserved(self, safety_guide):
        note = safety_guide["concerning_oxides"]["PbO"]["note"]
        assert "FDA 1992" in note


class TestColemaniteMaterialNote:
    def _colemanite(self, common_materials):
        return next(m for m in common_materials["materials"] if m["name"] == "Colemanite")

    def test_description_mentions_splutter_ceiling(self, common_materials):
        desc = self._colemanite(common_materials)["description"]
        assert "7-10%" in desc
        assert "splutter" in desc.lower()

    def test_description_mentions_frit_replacement(self, common_materials):
        desc = self._colemanite(common_materials)["description"]
        assert "calcium borate frit" in desc.lower()


class TestJsonStillValid:
    def test_defect_guide_top_level_shape(self, defect_guide):
        assert isinstance(defect_guide["defects"], dict)
        assert defect_guide["source"]

    def test_safety_guide_top_level_shape(self, safety_guide):
        assert "PbO" in safety_guide["concerning_oxides"]

    def test_common_materials_count_unchanged(self, common_materials):
        assert len(common_materials["materials"]) >= 48
