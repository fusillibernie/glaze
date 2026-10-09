"""Sanity checks for data/recipes/zakin_electric_kiln.json (Richard Zakin,
"Electric Kiln Ceramics: A Guide to Clays and Glazes", 3rd ed, 2004).
Parsed programmatically from the book's two-column dotted-leader tables
(word-position column splitting to avoid pdfplumber's default
interleaved-column text order) - these tests pin the parser's output
against manual spot-checks of the source pages.
"""

import json
from pathlib import Path

import pytest

from src.services.recipe_db import RecipeDatabase


DATA_PATH = Path(__file__).parent.parent / "data" / "recipes" / "zakin_electric_kiln.json"


@pytest.fixture(scope="module")
def recipes():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return data["zakin_electric_kiln_glazes"]


class TestFileStructure:
    def test_expected_recipe_count(self, recipes):
        assert len(recipes) == 60

    def test_every_recipe_has_required_fields(self, recipes):
        for r in recipes:
            assert r["name"]
            assert r["source"] == "zakin-electric-kiln-ceramics-2004"
            assert r["cone"]
            assert r["ingredients"]

    def test_all_oxidation_fired(self, recipes):
        """This chapter is exclusively oxidation - it's an electric kiln book."""
        assert all(r["atmosphere"] == "oxidation" for r in recipes)


class TestPercentageSanity:
    """Base ingredients should sum close to 100. Two named exceptions
    (Dewitt Mills at 88%, Franklin R 92 at 80%) are confirmed against the
    source page text - not a parsing gap, the book prints them this way."""

    KNOWN_EXCEPTIONS = {"Dewitt Mills", "Franklin R 92"}

    def test_base_ingredients_sum_near_100(self, recipes):
        offenders = []
        for r in recipes:
            if r["name"] in self.KNOWN_EXCEPTIONS:
                continue
            total = sum(i["percentage"] for i in r["ingredients"])
            if not (90 <= total <= 110):
                offenders.append((r["name"], total))
        assert offenders == [], f"percentage sums out of range: {offenders}"

    def test_known_exceptions_match_book(self, recipes):
        totals = {r["name"]: sum(i["percentage"] for i in r["ingredients"]) for r in recipes}
        assert totals["Dewitt Mills"] == pytest.approx(88.0)
        assert totals["Franklin R 92"] == pytest.approx(80.0)

    def test_no_negative_or_zero_percentages(self, recipes):
        for r in recipes:
            for i in r["ingredients"]:
                assert i["percentage"] > 0, f"{r['name']}: {i['material']} has non-positive percentage"


class TestKnownRecipes:
    def _find(self, recipes, name):
        return next(r for r in recipes if r["name"] == name)

    def test_estacada_typo_correction_noted(self, recipes):
        """Book prints 'potash'/'spodium' (not 'potash feldspar'/
        'spodumene') for this one recipe - transcribed literally then
        resolved, with the substitution recorded in notes."""
        r = self._find(recipes, "Estacada")
        materials = {i["material"] for i in r["ingredients"]}
        assert "Potash Feldspar" in materials
        assert "Spodumene" in materials
        assert "as printed" in r["notes"]

    def test_canton_brown_colorant_variation(self, recipes):
        r = self._find(recipes, "Canton Brown")
        colorants = {c["material"]: c["percentage"] for c in r["variations"][0]["colorants"]}
        assert colorants["Cobalt Carbonate"] == 1.5

    def test_boron_frit_3124_resolved_not_generic(self, recipes):
        """'boron frit 3124'/'boron frit (3124)' name a specific frit and
        should map to Frit 3124, unlike bare 'boron frit' elsewhere."""
        r = self._find(recipes, "Robin's 1b Clear k2")
        materials = {i["material"] for i in r["ingredients"]}
        assert "Frit 3124" in materials


class TestIntegrationWithRecipeDatabase:
    def test_loads_via_real_recipe_database(self):
        db = RecipeDatabase()
        db.load()
        stats = db.statistics()
        assert stats["by_source"].get("zakin-electric-kiln-ceramics-2004") == 60

    def test_searchable_by_name(self):
        db = RecipeDatabase()
        db.load()
        results = db.search(query="Ridgebury")
        assert any(r["name"] == "Ridgebury" for r in results)


class TestSurfaceLabels:
    """Zakin states the fired surface in prose for nearly every glaze
    ("This glaze has a satin matte surface"), but the extraction kept it
    only as description text, so all 60 recipes arrived with no surface
    field - unfilterable and invisible to surface statistics.

    Backfilled as a one-time data edit rather than a runtime regex: a
    parser would re-derive the same answer on every boot, be fragile
    against rewording, and leave no auditable record of what was inferred.
    """

    def test_most_recipes_are_labelled(self, recipes):
        assert sum(1 for r in recipes if r.get("surface")) == 56

    def test_labels_are_marked_as_inferred(self, recipes):
        """These are read out of prose, not stated by the author as a
        field. The distinction should survive in the data."""
        for r in recipes:
            if r.get("surface"):
                assert r["surface_source"] == "description"

    def test_satin_matte_is_not_filed_as_matte(self, recipes):
        """The commonest label in this book. Matching "matte" first would
        misfile 19 of 60 recipes."""
        from src.services.surface_model import normalize_surface

        r = next(x for x in recipes if x["name"] == "Cadwells Base")
        assert r["surface"] == "dry matte"
        satin_matte = [x for x in recipes if x.get("surface") == "satin matte"]
        assert len(satin_matte) == 19
        assert all(normalize_surface(x["surface"]) == "satin" for x in satin_matte)

    def test_unlabelled_recipes_have_no_surface_claim(self, recipes):
        """Four descriptions state colour or chemistry but never gloss.
        Crawling Vitgobe describes bubbling and wrinkling - a texture, not
        a gloss class - so it stays unlabelled rather than being forced
        into one of three buckets."""
        unlabelled = {r["name"] for r in recipes if not r.get("surface")}
        assert unlabelled == {
            "Opaque 04 k2", "Mohawk Green F k2",
            "02 Millennium MetalBlack", "Crawling Vitgobe",
        }

    #: Zakin labels that describe something other than gloss. "metallic"
    #: is reflectance and "semi-vitreous" is degree of vitrification;
    #: neither is a point on the glossy/satin/matte axis, so the gloss
    #: classifier correctly declines them rather than guessing.
    NON_GLOSS_LABELS = {"metallic", "semi-vitreous"}

    def test_gloss_labels_normalize(self, recipes):
        from src.services.surface_model import normalize_surface

        for r in recipes:
            surface = r.get("surface")
            if not surface or surface in self.NON_GLOSS_LABELS:
                continue
            assert normalize_surface(surface) in ("glossy", "satin", "matte"), surface

    def test_non_gloss_labels_are_declined_not_guessed(self, recipes):
        """Forcing "metallic" into one of three gloss buckets would put a
        fabricated classification into search results. Returning None is
        the honest answer, and the raw label is still there to filter on."""
        from src.services.surface_model import normalize_surface

        present = {r["surface"] for r in recipes if r.get("surface")}
        assert self.NON_GLOSS_LABELS <= present
        for label in self.NON_GLOSS_LABELS:
            assert normalize_surface(label) is None
