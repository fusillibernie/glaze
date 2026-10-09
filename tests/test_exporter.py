"""Tests for CSV reference export."""

import csv
import io
import zipfile

import pytest

from src.services import exporter
from src.services.materials_db import MaterialsDatabase


@pytest.fixture
def db():
    database = MaterialsDatabase()
    database.load()
    return database


def parse(csv_text):
    return list(csv.DictReader(io.StringIO(csv_text)))


class TestMaterialsExport:
    def test_row_per_material(self, db):
        rows = parse(exporter.export_materials(db))
        assert len(rows) == len(db.get_all())

    def test_includes_colorants(self, db):
        """materials_db spans common_materials.json *and* colorants.json, so the
        materials sheet is the full material universe. Colorants deliberately
        appear here too (for their oxide chemistry) and again in colorants.csv
        (for dosage and fired colour)."""
        rows = parse(exporter.export_materials(db))
        assert any(r["name"] == "Cobalt Carbonate" for r in rows)

    def test_boron_column_populated(self, db):
        """The oxide union must include B2O3, not just the common nine."""
        rows = parse(exporter.export_materials(db))
        colemanite = next(r for r in rows if r["name"] == "Colemanite")
        assert float(colemanite["B2O3"]) == pytest.approx(50.8)

    def test_minor_oxides_get_columns(self, db):
        rows = parse(exporter.export_materials(db))
        assert float(next(r for r in rows if r["name"] == "Spodumene")["Li2O"]) == pytest.approx(7.5)
        assert float(next(r for r in rows if r["name"] == "Barium Carbonate")["BaO"]) == pytest.approx(77.7)

    def test_absent_oxides_are_blank_not_zero(self, db):
        """A material without an oxide should export "" so it is distinguishable
        from a measured zero."""
        rows = parse(exporter.export_materials(db))
        assert next(r for r in rows if r["name"] == "Colemanite")["SiO2"] == ""

    def test_provenance_columns(self, db):
        rows = parse(exporter.export_materials(db))
        custer = next(r for r in rows if r["name"] == "Custer Feldspar")
        assert custer["source"] == "digitalfire"
        assert custer["discontinued"] == "yes"
        assert next(r for r in rows if r["name"] == "Soda Ash")["soluble"] == "yes"

    def test_oxide_columns_ordered(self, db):
        header = parse(exporter.export_materials(db))[0].keys()
        cols = list(header)
        assert cols.index("SiO2") < cols.index("Al2O3") < cols.index("CaO")
        assert cols.index("LOI") == len(cols) - 1


class TestOtherDatasets:
    def test_colorants(self, db):
        rows = parse(exporter.export_dataset("colorants", db))
        assert len(rows) == 20
        cobalt = next(r for r in rows if r["name"] == "Cobalt Carbonate")
        assert cobalt["typical_min_pct"] == "0.25"
        assert cobalt["color_reduction"] == "blue"

    def test_umf_limits_long_format(self, db):
        rows = parse(exporter.export_dataset("umf-limits", db))
        assert rows, "expected at least one limit row"
        # Metadata keys such as label/surface/notes must not become oxide rows.
        assert not any(r["oxide"] in {"label", "surface", "color", "notes"} for r in rows)
        sio2 = next(r for r in rows if r["oxide"] == "SiO2")
        assert float(sio2["min"]) <= float(sio2["max"])

    def test_umf_limits_skips_non_range_sources(self, db):
        """`practical_target` holds no min/max ranges and must be skipped."""
        rows = parse(exporter.export_dataset("umf-limits", db))
        assert not any(r["limit_source"] == "practical_target" for r in rows)

    def test_substitutions_expand_blends(self, db):
        rows = parse(exporter.export_dataset("substitutions", db))
        gb = [r for r in rows if r["material"] == "Gerstley Borate"]
        assert len(gb) > 1, "each substitute should get its own row"
        blend = next(r for r in gb if r["substitute_type"] == "blend")
        assert "Frit 3134" in blend["blend_components"]

    def test_unknown_dataset_raises(self, db):
        with pytest.raises(ValueError):
            exporter.export_dataset("nope", db)


class TestZipBundle:
    def test_contains_every_dataset(self, db):
        with zipfile.ZipFile(io.BytesIO(exporter.export_all_zip(db))) as zf:
            names = zf.namelist()
            assert len(names) == len(exporter.DATASETS)
            for dataset in exporter.DATASETS:
                assert f"glaze-reference-{dataset}.csv" in names

    def test_members_are_readable_csv(self, db):
        with zipfile.ZipFile(io.BytesIO(exporter.export_all_zip(db))) as zf:
            content = zf.read("glaze-reference-materials.csv").decode("utf-8")
        assert parse(content)[0]["name"]


class TestExportEndpoints:
    def test_csv_download_headers(self, client):
        response = client.get("/api/export/materials.csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "glaze-reference-materials.csv" in response.headers["content-disposition"]

    def test_every_dataset_downloads(self, client):
        for dataset in exporter.DATASETS:
            assert client.get(f"/api/export/{dataset}.csv").status_code == 200

    def test_unknown_dataset_404s(self, client):
        assert client.get("/api/export/bogus.csv").status_code == 404

    def test_zip_download(self, client):
        response = client.get("/api/export/reference.zip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert zf.testzip() is None
