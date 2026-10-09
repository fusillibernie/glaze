"""External validation of the UMF calculation and materials database
against independently measured data.

Nigel Wood's "Chinese Glazes" (1999) publishes, for each glaze in
Chapter 14, both the batch recipe AND a measured fired oxide analysis.
That makes it the only ground truth in this project: everywhere else we
can check that the arithmetic is self-consistent, but here we can check
it against a number someone obtained from a real fired glaze with an
instrument.

The anchor is the Jun Glaze, which resolves entirely to materials whose
analyses we hold independently - it agrees to 0.22 percentage points on
every oxide. If an edit to Potash Feldspar, Quartz, Whiting, China Clay,
Dolomite, Bone Ash or Red Iron Oxide ever breaks that, it is a
regression in the materials data, not in this test.

Three things have to be reconciled before the two sides are comparable:

1. Wood reports fired weight %, we compute molar UMF. We convert ours
   back to weight % and renormalize.
2. For three glazes Wood prints a single combined alkali column, stored
   under the literal key "K2O+Na2O". Our split K2O/Na2O is summed to
   match.
3. UMF does not model colorant oxides at all - it has no MnO, MnO2, CoO,
   CuO or Cr2O3 field, by convention, since colorants are not fluxes.
   A published fired analysis does include them. Both sides are therefore
   restricted to the oxides UMF can express and renormalized over that
   set; otherwise a manganese glaze looks 3 pp wrong on every oxide
   purely from the missing denominator.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from src.models.glaze import GlazeRecipe, GlazeIngredient
from src.models.umf import UMF
from src.services.formulator import GlazeFormulator
from src.services.materials_db import MaterialsDatabase


DATA_PATH = Path(__file__).parent.parent / "data" / "recipes" / "wood_chinese_glazes.json"

# g/mol for the oxides UMF carries.
MOLECULAR_WEIGHTS = {
    "SiO2": 60.08, "Al2O3": 101.96, "CaO": 56.08, "MgO": 40.30,
    "K2O": 94.20, "Na2O": 61.98, "Fe2O3": 159.69, "P2O5": 141.94,
    "TiO2": 79.87, "B2O3": 69.62, "Li2O": 29.88, "ZnO": 81.38,
    "BaO": 153.33, "SrO": 103.62, "PbO": 223.20, "ZrO2": 123.22,
}
UMF_OXIDES = {f.name for f in dataclasses.fields(UMF)}

# The anchor recipe and its measured agreement.
ANCHOR_ID = "glaze-9"
ANCHOR_TOLERANCE_PP = 0.30          # measured 0.224

# Remaining recipes substitute US materials for Wood's UK ones (Custer for
# his potash feldspar, EPK for his china clay), so they sit further out.
# Glaze 7 is the widest at 1.50 pp on MgO - and that one is likely a
# misprint in the book, since none of its eight ingredients contains a
# meaningful magnesia source.
GENERAL_TOLERANCE_PP = 2.0


@pytest.fixture(scope="module")
def recipes():
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))["wood_chinese_glazes"]


@pytest.fixture(scope="module")
def materials_db():
    db = MaterialsDatabase()
    db.load()
    return db


@pytest.fixture(scope="module")
def formulator(materials_db):
    return GlazeFormulator(materials_db)


def batch_vs_published(recipe_dict, formulator):
    """Return (ours, theirs) as weight % over a common oxide basis."""
    recipe = GlazeRecipe(
        name=recipe_dict["name"],
        ingredients=[
            GlazeIngredient(material_name=i["material"], percentage=i["percentage"])
            for i in recipe_dict["ingredients"]
        ],
    )
    umf = formulator.calculate_umf(recipe)

    ours = {
        ox: getattr(umf, ox) * mw
        for ox, mw in MOLECULAR_WEIGHTS.items()
        if getattr(umf, ox, 0)
    }
    theirs = dict(recipe_dict["fired_oxide_analysis"])

    if "K2O+Na2O" in theirs:
        ours["K2O+Na2O"] = ours.pop("K2O", 0.0) + ours.pop("Na2O", 0.0)

    keep = {
        o for o in set(ours) | set(theirs)
        if o == "K2O+Na2O" or o in UMF_OXIDES
    }
    ours = {k: v for k, v in ours.items() if k in keep}
    theirs = {k: v for k, v in theirs.items() if k in keep}

    total_ours, total_theirs = sum(ours.values()), sum(theirs.values())
    return (
        {k: v / total_ours * 100 for k, v in ours.items()},
        {k: v / total_theirs * 100 for k, v in theirs.items()},
    )


def max_deviation(recipe_dict, formulator):
    ours, theirs = batch_vs_published(recipe_dict, formulator)
    # Compare on the UNION - an oxide we produce but the book omits (or
    # vice versa) is a real disagreement, not something to skip over.
    return max(
        (abs(ours.get(o, 0.0) - theirs.get(o, 0.0)), o)
        for o in set(ours) | set(theirs)
    )


def resolvable(recipes, materials_db):
    return [
        r for r in recipes
        if not materials_db.unresolved([i["material"] for i in r["ingredients"]])
    ]


class TestAnchorRecipe:
    """The Jun Glaze is the tight guard: every one of its materials has an
    independent published analysis in this database."""

    def test_matches_published_fired_analysis(self, recipes, formulator):
        recipe = next(r for r in recipes if r["source_id"] == ANCHOR_ID)
        deviation, oxide = max_deviation(recipe, formulator)
        assert deviation < ANCHOR_TOLERANCE_PP, (
            f"Jun Glaze drifted to {deviation:.3f} pp on {oxide}; this is a "
            f"regression in the materials database, not in the test."
        )

    def test_every_oxide_agrees_not_just_the_total(self, recipes, formulator):
        recipe = next(r for r in recipes if r["source_id"] == ANCHOR_ID)
        ours, theirs = batch_vs_published(recipe, formulator)
        for oxide in ("SiO2", "Al2O3", "CaO", "K2O", "MgO", "Na2O", "P2O5", "Fe2O3"):
            assert ours.get(oxide, 0.0) == pytest.approx(
                theirs.get(oxide, 0.0), abs=ANCHOR_TOLERANCE_PP
            ), f"{oxide} disagrees"


class TestAllResolvableRecipes:
    def test_within_general_tolerance(self, recipes, materials_db, formulator):
        offenders = []
        for r in resolvable(recipes, materials_db):
            deviation, oxide = max_deviation(r, formulator)
            if deviation >= GENERAL_TOLERANCE_PP:
                offenders.append((r["name"], round(deviation, 3), oxide))
        assert offenders == [], f"deviation beyond tolerance: {offenders}"

    def test_expected_number_resolve(self, recipes, materials_db):
        """Eight of the nine resolve. Adding the ECC materials Wood
        publishes took this from 1 to 8; only Glaze 4 remains blocked,
        on BBV Ball Clay, which the book does not analyse."""
        assert len(resolvable(recipes, materials_db)) == 8

    def test_glaze_4_still_unresolved_on_bbv(self, recipes, materials_db):
        """Deliberately unresolved. Inventing an analysis for BBV to close
        the gap would defeat the point of validating against published
        data in the first place."""
        glaze4 = next(r for r in recipes if r["source_id"] == "glaze-4")
        unresolved = materials_db.unresolved([i["material"] for i in glaze4["ingredients"]])
        assert "BBV Ball Clay" in unresolved


class TestPublishedDataIntegrity:
    def test_analyses_sum_near_100(self, recipes):
        """A fired analysis should account for ~all of the glaze. This
        caught three recipes whose combined 'K2O+Na2O' column had been
        dropped during transcription, leaving 3-5.5 wt% missing."""
        for r in recipes:
            total = sum(r["fired_oxide_analysis"].values())
            assert 97.0 <= total <= 103.0, f"{r['name']} sums to {total:.2f}"

    def test_every_recipe_carries_an_analysis(self, recipes):
        for r in recipes:
            assert r["fired_oxide_analysis"]["SiO2"] > 0

    def test_combined_alkali_recipes_have_no_split_alkali(self, recipes):
        """The combined key and the split keys are mutually exclusive -
        holding both would double-count the alkali."""
        for r in recipes:
            fa = r["fired_oxide_analysis"]
            if "K2O+Na2O" in fa:
                assert "K2O" not in fa and "Na2O" not in fa, r["name"]
            else:
                assert "K2O" in fa, f"{r['name']} has no alkali at all"
