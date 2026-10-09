"""Tests for the mutation and lookup half of MaterialsDatabase.

The module sat at 55% coverage: alias resolution was well tested, but
add(), save(), search(), find_substitutes() and the load() error paths
were not. Writing these turned up three defects - save() emptying its
target, add() skipping alias indexing, and add() duplicating entries in
the type index - so the gap was hiding bugs rather than merely lines.
"""

import json

import pytest

from src.models.materials import (
    Material,
    MaterialAnalysis,
    MaterialType,
    OxideAnalysis,
)
from src.services.materials_db import MaterialsDatabase


DATA_DIR = "data/materials"


def material(name, material_type=MaterialType.FELDSPAR, aliases=(), **oxides):
    return Material(
        name=name,
        material_type=material_type,
        analysis=MaterialAnalysis(oxide_analysis=OxideAnalysis(**oxides)),
        alternate_names=list(aliases),
    )


@pytest.fixture
def db():
    from pathlib import Path
    database = MaterialsDatabase(Path(DATA_DIR))
    database.load()
    return database


class TestSave:
    def test_save_before_load_does_not_write_an_empty_file(self, tmp_path):
        """save() was the only method not calling _ensure_loaded(), so
        saving from a database nobody had read yet wrote
        {"materials": []} - quietly emptying the target instead of
        failing."""
        from pathlib import Path

        fresh = MaterialsDatabase(Path(DATA_DIR))
        out = tmp_path / "out.json"
        fresh.save(out)
        assert len(json.loads(out.read_text(encoding="utf-8"))["materials"]) > 50

    def test_round_trips_through_disk(self, db, tmp_path):
        out = tmp_path / "round.json"
        db.save(out)
        from pathlib import Path

        reloaded = MaterialsDatabase(tmp_path)
        reloaded.load()
        assert len(reloaded.get_all()) == len(db.get_all())
        assert reloaded.get("Custer Feldspar").analysis.oxide_analysis.SiO2 == pytest.approx(
            db.get("Custer Feldspar").analysis.oxide_analysis.SiO2
        )


class TestAdd:
    def test_added_material_is_findable_by_name(self, db):
        db.add(material("Test Spar", SiO2=68.0, Al2O3=18.0))
        assert db.get("Test Spar") is not None

    def test_added_material_is_findable_by_alias(self, db):
        """load() indexes alternate_names but add() did not, so the same
        material was reachable by alias from disk and not from memory."""
        db.add(material("Test Spar", aliases=["Testspar", "TS-1"], SiO2=68.0))
        assert db.get("Testspar") is not None
        assert db.get("TS-1") is not None

    def test_re_adding_does_not_duplicate_in_the_type_index(self, db):
        """_materials is a dict and overwrote, but _by_type appended
        unconditionally - so the material appeared twice in get_by_type()
        while the database held one copy."""
        before = len(db.get_by_type(MaterialType.FELDSPAR))
        spar = material("Test Spar", SiO2=68.0)
        db.add(spar)
        db.add(spar)
        db.add(spar)
        assert len(db.get_by_type(MaterialType.FELDSPAR)) == before + 1

    def test_replacing_a_material_drops_its_old_aliases(self, db):
        db.add(material("Test Spar", aliases=["OldAlias"], SiO2=68.0))
        assert db.get("OldAlias") is not None
        db.add(material("Test Spar", aliases=["NewAlias"], SiO2=70.0))
        assert db.get("NewAlias") is not None
        assert db.get("OldAlias") is None, "stale alias still resolves"

    def test_added_alias_never_shadows_a_real_material_name(self, db):
        """The invariant the whole alias system rests on."""
        db.add(material("Test Spar", aliases=["Custer Feldspar"], SiO2=68.0))
        assert db.get("Custer Feldspar").name == "Custer Feldspar"

    def test_replacement_updates_the_analysis(self, db):
        db.add(material("Test Spar", SiO2=68.0))
        db.add(material("Test Spar", SiO2=72.0))
        assert db.get("Test Spar").analysis.oxide_analysis.SiO2 == pytest.approx(72.0)


class TestSearch:
    def test_matches_on_name_substring(self, db):
        assert any("feldspar" in m.name.lower() for m in db.search("feldspar"))

    def test_matches_on_alias(self, db):
        """EPK is only an alias of "EPK Kaolin"... but "Redart Clay" is
        purely an alias, so it exercises the alias branch properly."""
        assert any(m.name == "Red Art" for m in db.search("Redart"))

    def test_type_filter_narrows_results(self, db):
        unfiltered = db.search("a")
        clays = db.search("a", material_type=MaterialType.CLAY)
        assert len(clays) < len(unfiltered)
        assert all(m.material_type == MaterialType.CLAY for m in clays)

    def test_is_case_insensitive(self, db):
        assert db.search("CUSTER") and db.search("custer")

    def test_no_match_returns_empty_not_error(self, db):
        assert db.search("definitely not a material") == []


class TestFindSubstitutes:
    def test_listed_substitutes_rank_first(self, db):
        """An explicitly declared substitute outranks anything found by
        chemistry similarity.

        Constructed rather than taken from the shipped data, because no
        material in data/materials currently populates `substitutes` -
        cross-material substitution is expressed in substitutions.json
        and handled by SubstitutionService instead, so this branch has no
        live data to exercise it.
        """
        subject = material("Subject Spar", aliases=[], SiO2=68.0, Al2O3=18.0)
        subject.substitutes = ["Custer Feldspar"]
        db.add(subject)

        results = db.find_substitutes(subject)
        assert results
        assert results[0][0].name == "Custer Feldspar"
        assert results[0][1] == 1.0

    def test_unknown_listed_substitute_is_skipped_quietly(self, db):
        subject = material("Subject Spar", SiO2=68.0, Al2O3=18.0)
        subject.substitutes = ["No Such Material"]
        db.add(subject)
        assert all(m.name != "No Such Material" for m, _ in db.find_substitutes(subject))

    def test_never_suggests_the_material_itself(self, db):
        subject = db.get("Custer Feldspar")
        assert all(m.name != subject.name for m, _ in db.find_substitutes(subject))

    def test_results_are_sorted_by_similarity(self, db):
        scores = [s for _, s in db.find_substitutes(db.get("Custer Feldspar"))]
        assert scores == sorted(scores, reverse=True)

    def test_respects_the_limit(self, db):
        assert len(db.find_substitutes(db.get("Custer Feldspar"), limit=3)) <= 3

    def test_feldspar_substitutes_are_feldspars(self, db):
        """Similarity is computed within a material type, so a feldspar
        must not come back suggesting a colorant."""
        subject = db.get("Custer Feldspar")
        for sub, score in db.find_substitutes(subject):
            if score < 1.0:  # listed substitutes may legitimately cross types
                assert sub.material_type == subject.material_type


class TestSimilarity:
    def test_identical_analyses_score_1(self, db):
        a = material("A", SiO2=68.0, Al2O3=18.0, K2O=10.0)
        assert db._calculate_similarity(a, material("B", SiO2=68.0, Al2O3=18.0, K2O=10.0)) == pytest.approx(1.0)

    def test_wildly_different_analyses_score_low(self, db):
        feldspar = material("A", SiO2=68.0, Al2O3=18.0, K2O=10.0)
        whiting = material("B", CaO=56.0)
        assert db._calculate_similarity(feldspar, whiting) < 0.5

    def test_similar_beats_dissimilar(self, db):
        subject = material("subject", SiO2=68.0, Al2O3=18.0, K2O=10.0)
        close = material("close", SiO2=66.0, Al2O3=19.0, K2O=9.0)
        far = material("far", SiO2=30.0, Al2O3=50.0)
        assert db._calculate_similarity(subject, close) > db._calculate_similarity(subject, far)

    def test_two_empty_analyses_score_0_not_1(self, db):
        """No shared oxides is no evidence of similarity, not perfect
        similarity - the difference matters because find_substitutes
        thresholds on this."""
        assert db._calculate_similarity(material("A"), material("B")) == 0.0


class TestLoadRobustness:
    def test_missing_directory_loads_empty_without_raising(self, tmp_path):
        database = MaterialsDatabase(tmp_path / "does_not_exist")
        database.load()
        assert database.get_all() == []

    def test_malformed_json_is_skipped_not_fatal(self, tmp_path, caplog):
        """One corrupt file must not take the whole materials database
        down at import time."""
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
        (tmp_path / "good.json").write_text(json.dumps({"materials": [
            {"name": "Good Spar", "type": "feldspar", "analysis": {"SiO2": 68.0}}
        ]}), encoding="utf-8")

        database = MaterialsDatabase(tmp_path)
        with caplog.at_level("ERROR"):
            database.load()
        assert database.get("Good Spar") is not None
        assert "broken.json" in caplog.text

    def test_accepts_a_bare_list_file(self, tmp_path):
        (tmp_path / "list.json").write_text(json.dumps([
            {"name": "Listed Spar", "type": "feldspar", "analysis": {"SiO2": 68.0}}
        ]), encoding="utf-8")
        database = MaterialsDatabase(tmp_path)
        database.load()
        assert database.get("Listed Spar") is not None

    def test_accepts_a_colorants_keyed_file(self, tmp_path):
        (tmp_path / "colorants.json").write_text(json.dumps({"colorants": [
            {"name": "Test Oxide", "type": "colorant", "analysis": {"Fe2O3": 90.0}}
        ]}), encoding="utf-8")
        database = MaterialsDatabase(tmp_path)
        database.load()
        assert database.get("Test Oxide") is not None
