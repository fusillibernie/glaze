"""Invariants across the glaze category profiles.

Added alongside the copper red profile, which the app had no category
for despite 86 copper reds in the corpus. Writing it surfaced a shape
bug worth guarding generally: listing a colorant in both
preferred_materials and required_colorants gets it added twice - once
by the solver as a base ingredient and once by the profile as an
addition - so a copper red came out carrying 1.4% tin plus another
1.25%.
"""

import json
from pathlib import Path

import pytest

from src.models.umf import UMF

PROFILES = Path(__file__).parent.parent / "data" / "reference" / "category_profiles.json"


@pytest.fixture(scope="module")
def categories():
    return json.loads(PROFILES.read_text(encoding="utf-8"))["categories"]


class TestProfileShape:
    def test_colorants_are_never_also_base_materials(self, categories):
        """Colorants are additions on top of the 100% base. A material in
        both lists is added twice by two code paths that cannot see each
        other."""
        for name, profile in categories.items():
            required = {c["source_material"] for c in profile.get("required_colorants", [])}
            preferred = set(profile.get("preferred_materials", []))
            constrained = set(profile.get("material_constraints", {}))
            assert not (required & preferred), f"{name}: {required & preferred} in both lists"
            assert not (required & constrained), f"{name}: {required & constrained} double-constrained"

    def test_umf_overrides_name_real_oxides(self, categories):
        umf = UMF()
        for name, profile in categories.items():
            for oxide in profile.get("umf_overrides", {}):
                assert oxide == "KNaO" or hasattr(umf, oxide), f"{name}: {oxide}"

    def test_ranges_are_ordered(self, categories):
        for name, profile in categories.items():
            for oxide, rng in profile.get("umf_overrides", {}).items():
                assert rng["min"] <= rng["max"], f"{name}/{oxide}"
            ratio = profile.get("si_al_ratio")
            if ratio:
                assert ratio["min"] < ratio["max"], name

    def test_every_profile_documents_itself(self, categories):
        for name, profile in categories.items():
            assert profile.get("description", "").strip(), name
            assert profile.get("surface"), name


class TestCopperRed:
    @pytest.fixture
    def copper_red(self, categories):
        return categories["copper_red"]

    def test_exists(self, categories):
        """86 copper reds in the corpus and no way to target one."""
        assert "copper_red" in categories

    def test_requires_reduction(self, copper_red):
        """Not a preference - the red is colloidal metallic copper and it
        dies on reoxidation."""
        assert copper_red["preferred_atmosphere"] == ["reduction"]

    def test_copper_capped_at_the_colour_ceiling(self, copper_red):
        """Above ~0.5% copper carbonate the colour goes liver, metallic or
        green. The corpus median sits at 0.49%, right against it."""
        copper = next(c for c in copper_red["required_colorants"]
                      if c["source_material"] == "Copper Carbonate")
        assert copper["max_pct"] <= 0.5

    def test_tin_is_required_not_optional(self, copper_red):
        """Tin nucleates the colloid; without it there is no red to
        stabilise. Roughly 1% tin to 0.33% copper, per Pinnell."""
        tin = next(c for c in copper_red["required_colorants"]
                   if c["source_material"] == "Tin Oxide")
        assert tin["min_pct"] >= 1.0

    def test_band_matches_the_measured_corpus(self, copper_red):
        """p10-p90 of 53 cone 9-11 reduction copper reds."""
        ratio = copper_red["si_al_ratio"]
        assert ratio["min"] == pytest.approx(7.0, abs=0.5)
        assert ratio["max"] == pytest.approx(12.5, abs=0.5)


class TestGeneration:
    def test_copper_red_generates_in_band(self, client):
        response = client.post("/api/recipes/formulate", json={
            "cone": "10", "surface": "glossy",
            "atmosphere": "reduction", "category": "copper_red",
        })
        assert response.status_code == 200
        body = response.json()
        umf = body.get("achieved_umf") or {}
        sio2, al2o3 = umf.get("SiO2"), umf.get("Al2O3")
        assert sio2 and al2o3
        assert 7.0 <= sio2 / al2o3 <= 12.5

    def test_generated_copper_red_carries_copper_and_tin_once(self, client):
        response = client.post("/api/recipes/formulate", json={
            "cone": "10", "surface": "glossy",
            "atmosphere": "reduction", "category": "copper_red",
        })
        recipe = response.json().get("recipe") or {}
        names = [i["material"] for i in recipe.get("ingredients", [])]
        names += [c.get("material") for c in recipe.get("colorants", [])]
        assert names.count("Tin Oxide") == 1, "tin added by two paths"
        assert names.count("Copper Carbonate") == 1
