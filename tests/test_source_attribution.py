"""The Glazy corpus is CC BY-NC-SA 4.0, so crediting it is a licence
condition rather than a courtesy - and it covers 10,799 of the 11,054
recipes in the app.

get_sources() always had a code path to surface licence and attribution,
but it read data/glazy_bulk/.metadata.json, which had never existed. It
therefore returned name and count only, and the credit appeared nowhere
in the app or the API. These tests keep that path alive.
"""

import json
from pathlib import Path

import pytest

from src.services.recipe_db import RecipeDatabase


REPO = Path(__file__).parent.parent
METADATA = REPO / "data" / "glazy_bulk" / ".metadata.json"


@pytest.fixture(scope="module")
def sources():
    db = RecipeDatabase()
    db.load()
    return {s["name"]: s for s in db.get_sources()}


class TestMetadataFile:
    def test_exists(self):
        assert METADATA.exists(), (
            "attribution metadata is missing; the licence credit has no source"
        )

    def test_states_licence_and_credit(self):
        data = json.loads(METADATA.read_text(encoding="utf-8"))
        assert data["license"] == "CC BY-NC-SA 4.0"
        assert data["attribution"].strip()
        assert data["source_url"].startswith("https://")

    def test_is_not_gitignored(self):
        """The rest of data/glazy_bulk/ is excluded because the corpus is
        7.5MB. This file has to be the exception, or the credit exists
        only on the machine that ran the download and never reaches the
        deployed app.
        """
        gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        assert "!data/glazy_bulk/.metadata.json" in gitignore
        # Excluding the directory itself would make the negation
        # unreachable - git prunes an excluded directory without
        # evaluating negations inside it.
        assert "data/glazy_bulk/*" in gitignore


class TestSourcesEndpointSurfacesIt:
    def test_glazy_source_carries_attribution(self, sources):
        glazy = sources.get("glazy-data")
        if glazy is None:
            pytest.skip("bulk corpus not present in this checkout")
        assert glazy.get("attribution"), "licence credit is not being surfaced"
        assert glazy.get("license") == "CC BY-NC-SA 4.0"

    def test_attribution_names_the_source(self, sources):
        glazy = sources.get("glazy-data")
        if glazy is None:
            pytest.skip("bulk corpus not present in this checkout")
        assert "Glazy" in glazy["attribution"]

    def test_every_source_still_reports_a_count(self, sources):
        for name, source in sources.items():
            assert source["count"] > 0, name


class TestUISurfacesIt:
    def test_library_renders_attribution(self):
        """A credit returned by the API but never rendered is the same as
        no credit."""
        ui = (REPO / "ui" / "index.html").read_text(encoding="utf-8")
        assert "renderSourceAttribution" in ui
        assert 'id="library-attribution"' in ui
