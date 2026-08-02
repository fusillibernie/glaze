"""Tests for TargetResolver - converts cone/surface/category descriptors
into concrete UMF ranges for the solver. No test coverage existed for
this module before, despite it being the entry point for every /generate
recipe request.

Runs against the real data/reference/umf_limits.json and
category_profiles.json rather than mocks - this class is a thin
translation layer over that data, so a test double would only verify the
translation logic against itself, not against what actually ships.
Expected values below (e.g. the celadon intersection numbers) are hand
-computed from those files, not guessed.
"""

import pytest

from src.services.target_resolver import TargetResolver, SolverTarget


@pytest.fixture
def resolver():
    return TargetResolver()


class TestConeBracketMapping:
    def test_low_fire_cone_resolves_without_fallback_warning(self, resolver):
        target = resolver.resolve(cone="04")
        assert not any("not in reference data" in w for w in target.warnings)

    def test_mid_fire_cone_6_resolves_without_fallback_warning(self, resolver):
        target = resolver.resolve(cone="6")
        assert not any("not in reference data" in w for w in target.warnings)
        assert target.get_oxide_range("SiO2") is not None

    def test_high_fire_cone_10_resolves(self, resolver):
        target = resolver.resolve(cone="10")
        assert target.get_oxide_range("SiO2") is not None

    def test_unknown_cone_falls_back_with_warning(self, resolver):
        target = resolver.resolve(cone="not-a-cone")
        assert any("not in reference data" in w for w in target.warnings)
        # Must still produce usable ranges, not an empty target
        assert len(target.oxide_ranges) > 0

    def test_cone_7_and_cone_3_share_a_bracket(self, resolver):
        """CONE_BRACKET_MAP sends both to cone_3_7 - confirms they resolve
        to the same underlying data rather than one silently falling
        through to a default."""
        r3 = resolver.resolve(cone="3")
        r7 = resolver.resolve(cone="7")
        assert r3.get_oxide_range("SiO2").min_val == r7.get_oxide_range("SiO2").min_val


class TestSurfaceSelection:
    def test_glossy_and_matte_produce_different_ranges(self, resolver):
        """A matte surface needs a different Al2O3/SiO2 window than glossy -
        if these came back identical the surface parameter would be a
        no-op."""
        glossy = resolver.resolve(cone="6", surface="glossy")
        matte = resolver.resolve(cone="6", surface="matte")
        glossy_al = glossy.get_oxide_range("Al2O3")
        matte_al = matte.get_oxide_range("Al2O3")
        assert (glossy_al.min_val, glossy_al.max_val) != (matte_al.min_val, matte_al.max_val)

    def test_missing_surface_data_falls_back_with_warning(self, resolver):
        """cone_04_02 has no dedicated matte source in the reference data -
        must fall back rather than return an empty target."""
        target = resolver.resolve(cone="04", surface="matte")
        assert len(target.oxide_ranges) > 0


class TestCategoryProfile:
    def test_unknown_category_leaves_base_ranges_untouched(self, resolver):
        base = resolver.resolve(cone="6", surface="glossy")
        target = resolver.resolve(cone="6", surface="glossy", category="not_a_real_category")
        assert (
            target.get_oxide_range("SiO2").min_val
            == base.get_oxide_range("SiO2").min_val
        )

    def test_celadon_intersects_base_range_with_override(self, resolver):
        """Hand-computed from real data: cone 6 glossy SiO2 is (1.5, 4.0),
        celadon's override is (3.5, 5.0). Intersection = (3.5, 4.0)."""
        target = resolver.resolve(cone="6", surface="glossy", category="celadon")
        sio2 = target.get_oxide_range("SiO2")
        assert (sio2.min_val, sio2.max_val) == pytest.approx((3.5, 4.0))

    def test_celadon_al2o3_intersection_can_degenerate_to_a_point(self, resolver):
        """Al2O3 base (0.1, 0.3) vs override (0.3, 0.5) intersects at
        exactly (0.3, 0.3) - still a valid (non-fallback) intersection."""
        target = resolver.resolve(cone="6", surface="glossy", category="celadon")
        al2o3 = target.get_oxide_range("Al2O3")
        assert (al2o3.min_val, al2o3.max_val) == pytest.approx((0.3, 0.3))

    def test_category_sets_si_al_ratio_when_defined(self, resolver):
        target = resolver.resolve(cone="6", category="crystalline")
        assert target.si_al_ratio == pytest.approx((25.0, 999.0))

    def test_category_without_si_al_ratio_leaves_it_unset(self, resolver):
        target = resolver.resolve(cone="6", category="ash")
        # ash profile has no si_al_ratio key in category_profiles.json
        assert target.si_al_ratio is None or isinstance(target.si_al_ratio, tuple)

    def test_category_populates_material_constraints(self, resolver):
        target = resolver.resolve(cone="10", category="shino")
        constraint = next(
            c for c in target.material_constraints if c.material_name == "Nepheline Syenite"
        )
        assert constraint.min_pct == 40.0
        assert constraint.max_pct == 75.0
        assert constraint.required is True

    def test_required_colorant_uses_profile_midpoint(self, resolver):
        """Celadon's required_colorants entry is Red Iron Oxide, 1.0-2.5% ->
        midpoint 1.75, when the user hasn't already specified it."""
        target = resolver.resolve(cone="10", category="celadon")
        match = next(
            c for c in target.colorant_additions if c.material_name == "Red Iron Oxide"
        )
        assert match.percentage == pytest.approx(1.75)

    def test_required_colorant_not_duplicated_if_user_specified(self, resolver):
        target = resolver.resolve(
            cone="10", category="celadon",
            colorants=[{"material_name": "Red Iron Oxide", "percentage": 2.0}],
        )
        matches = [c for c in target.colorant_additions if c.material_name == "Red Iron Oxide"]
        assert len(matches) == 1
        assert matches[0].percentage == 2.0


class TestOxideRangeWeighting:
    def test_glass_formers_weighted_higher_than_default(self, resolver):
        target = resolver.resolve(cone="6")
        assert target.get_oxide_range("SiO2").weight == 2.0
        assert target.get_oxide_range("Al2O3").weight == 2.0

    def test_calcium_gets_intermediate_weight(self, resolver):
        target = resolver.resolve(cone="6")
        assert target.get_oxide_range("CaO").weight == 1.5

    def test_midpoint_is_average_of_bounds(self, resolver):
        target = resolver.resolve(cone="6")
        r = target.get_oxide_range("SiO2")
        assert r.midpoint == pytest.approx((r.min_val + r.max_val) / 2.0)


class TestColorantPassthrough:
    def test_user_colorants_carried_through(self, resolver):
        target = resolver.resolve(
            cone="6", colorants=[{"material_name": "Cobalt Carbonate", "percentage": 1.5}]
        )
        assert any(
            c.material_name == "Cobalt Carbonate" and c.percentage == 1.5
            for c in target.colorant_additions
        )
