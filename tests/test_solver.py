"""Tests for GlazeSolver - SLSQP-based recipe optimization. No test
coverage existed for this module before, despite it backing the entire
Generate tab / /api/recipes/formulate endpoint.

Uses small synthetic materials rather than the real materials_db so
expected UMF values are hand-computable and tests stay fast/deterministic.
"""

import pytest

from src.models.materials import (
    Material, MaterialType, MaterialAnalysis, OxideAnalysis,
)
from src.services.solver import GlazeSolver
from src.services.target_resolver import SolverTarget, OxideRange, MaterialConstraint


def make_material(name, material_type, **oxides):
    return Material(
        name=name,
        material_type=material_type,
        analysis=MaterialAnalysis(oxide_analysis=OxideAnalysis(**oxides)),
    )


# A minimal but chemically plausible set: feldspar (flux+glass former+
# stabilizer), pure silica, and whiting (pure calcium flux).
FELDSPAR = make_material("Test Feldspar", MaterialType.FELDSPAR,
                          SiO2=68.0, Al2O3=18.0, K2O=10.0, Na2O=3.0, CaO=0.3)
SILICA = make_material("Test Silica", MaterialType.SILICA, SiO2=99.5)
WHITING = make_material("Test Whiting", MaterialType.CALCIUM, CaO=56.0)
KAOLIN = make_material("Test Kaolin", MaterialType.CLAY, SiO2=46.0, Al2O3=38.0)


@pytest.fixture
def solver():
    return GlazeSolver()


def wide_open_target():
    """A target with generous ranges every one of the fixture materials
    can satisfy, so solve() has real room to work rather than being
    forced toward one degenerate corner."""
    return SolverTarget(oxide_ranges=[
        OxideRange(oxide="SiO2", min_val=1.0, max_val=6.0, weight=2.0),
        OxideRange(oxide="Al2O3", min_val=0.1, max_val=0.8, weight=2.0),
        OxideRange(oxide="CaO", min_val=0.1, max_val=0.9, weight=1.5),
        OxideRange(oxide="K2O", min_val=0.0, max_val=1.0, weight=1.0),
    ])


class TestSelectCandidates:
    def test_required_material_always_included(self, solver):
        target = SolverTarget(material_constraints=[
            MaterialConstraint(material_name="Test Whiting", min_pct=5.0, required=True)
        ])
        selected = solver.select_candidates(
            [FELDSPAR, SILICA, WHITING, KAOLIN], target, max_candidates=2
        )
        assert any(m.name == "Test Whiting" for m in selected)

    def test_preferred_materials_included(self, solver):
        target = SolverTarget(preferred_materials=["Test Kaolin"])
        selected = solver.select_candidates([FELDSPAR, SILICA, WHITING, KAOLIN], target)
        assert any(m.name == "Test Kaolin" for m in selected)

    def test_respects_max_candidates_cap(self, solver):
        target = SolverTarget()
        selected = solver.select_candidates(
            [FELDSPAR, SILICA, WHITING, KAOLIN], target, max_candidates=2
        )
        assert len(selected) <= 2

    def test_fills_by_functional_role_diversity(self, solver):
        """With no constraints at all, candidate selection should still
        pick a spread across functional roles (feldspar, silica, calcium)
        rather than four materials of the same type."""
        target = SolverTarget()
        selected = solver.select_candidates(
            [FELDSPAR, SILICA, WHITING, KAOLIN], target, max_candidates=4
        )
        roles = {m.material_type for m in selected}
        assert len(roles) > 1


class TestComputeUmf:
    def test_single_material_umf_matches_hand_calculation(self, solver):
        """100% Test Whiting (pure CaO) must normalize to UMF CaO = 1.0 -
        it's the only flux, so it IS the unity flux by definition."""
        import numpy as np
        A = solver._build_contribution_matrix([WHITING])
        umf = solver._compute_umf(np.array([100.0]), A)
        ca_idx = solver._oxide_idx["CaO"]
        assert umf[ca_idx] == pytest.approx(1.0, abs=1e-6)

    def test_no_flux_returns_zero_umf(self, solver):
        """Pure silica has no flux oxide at all - UMF normalization would
        divide by zero, so this must return zeros rather than crash or
        return NaN/inf."""
        import numpy as np
        A = solver._build_contribution_matrix([SILICA])
        umf = solver._compute_umf(np.array([100.0]), A)
        assert np.all(umf == 0.0)
        assert not np.any(np.isnan(umf))


class TestSolve:
    def test_percentages_sum_to_100(self, solver):
        result = solver.solve(
            wide_open_target(), [FELDSPAR, SILICA, WHITING, KAOLIN], n_starts=2
        )
        total = sum(pct for _, pct in result.ingredients)
        assert total == pytest.approx(100.0, abs=0.5)

    def test_empty_candidates_does_not_crash(self, solver):
        result = solver.solve(wide_open_target(), [], n_starts=2)
        assert result.converged is False
        assert result.ingredients == []
        assert len(result.warnings) > 0

    def test_converges_on_a_satisfiable_wide_open_target(self, solver):
        result = solver.solve(
            wide_open_target(), [FELDSPAR, SILICA, WHITING, KAOLIN], n_starts=3
        )
        assert result.converged is True
        assert len(result.ingredients) > 0

    def test_achieved_umf_reported_for_nonzero_oxides(self, solver):
        result = solver.solve(
            wide_open_target(), [FELDSPAR, SILICA, WHITING, KAOLIN], n_starts=3
        )
        assert "SiO2" in result.achieved_umf
        assert result.achieved_umf["SiO2"] > 0

    def test_small_contributions_dropped(self, solver):
        """Materials under 1% are zeroed and not returned as ingredients -
        avoids nonsensical "add 0.03% of X" recipe lines."""
        result = solver.solve(
            wide_open_target(), [FELDSPAR, SILICA, WHITING, KAOLIN], n_starts=3
        )
        assert all(pct >= 0.5 for _, pct in result.ingredients)

    def test_material_bounds_respected(self, solver):
        """A material capped at max_pct=0 should never appear in the
        solved recipe."""
        target = wide_open_target()
        target.material_constraints = [
            MaterialConstraint(material_name="Test Kaolin", min_pct=0.0, max_pct=0.0)
        ]
        result = solver.solve(
            target, [FELDSPAR, SILICA, WHITING, KAOLIN], n_starts=3
        )
        assert not any(name == "Test Kaolin" for name, _ in result.ingredients)

    def test_deviation_score_is_finite(self, solver):
        result = solver.solve(
            wide_open_target(), [FELDSPAR, SILICA, WHITING, KAOLIN], n_starts=3
        )
        assert result.deviation_score < 999.0


class TestBuildTargetFit:
    def test_in_range_flag_true_when_within_bounds(self, solver):
        import numpy as np
        target = SolverTarget(oxide_ranges=[
            OxideRange(oxide="SiO2", min_val=2.0, max_val=4.0),
        ])
        umf_array = np.zeros(solver._n_oxides)
        umf_array[solver._oxide_idx["SiO2"]] = 3.0
        fit = solver._build_target_fit(umf_array, target, has_knao=False)
        assert fit["SiO2"]["in_range"] is True
        assert fit["SiO2"]["achieved"] == pytest.approx(3.0)

    def test_in_range_flag_false_outside_bounds(self, solver):
        import numpy as np
        target = SolverTarget(oxide_ranges=[
            OxideRange(oxide="SiO2", min_val=2.0, max_val=4.0),
        ])
        umf_array = np.zeros(solver._n_oxides)
        umf_array[solver._oxide_idx["SiO2"]] = 5.0
        fit = solver._build_target_fit(umf_array, target, has_knao=False)
        assert fit["SiO2"]["in_range"] is False

    def test_knao_combines_na2o_and_k2o(self, solver):
        import numpy as np
        target = SolverTarget(oxide_ranges=[
            OxideRange(oxide="KNaO", min_val=0.2, max_val=0.6),
        ])
        umf_array = np.zeros(solver._n_oxides)
        umf_array[solver._oxide_idx["Na2O"]] = 0.2
        umf_array[solver._oxide_idx["K2O"]] = 0.2
        fit = solver._build_target_fit(umf_array, target, has_knao=True)
        assert fit["KNaO"]["achieved"] == pytest.approx(0.4)
        assert fit["KNaO"]["in_range"] is True

    def test_si_al_ratio_included_when_targeted(self, solver):
        import numpy as np
        target = SolverTarget(si_al_ratio=(8.0, 12.0))
        umf_array = np.zeros(solver._n_oxides)
        umf_array[solver._oxide_idx["SiO2"]] = 4.0
        umf_array[solver._oxide_idx["Al2O3"]] = 0.4
        fit = solver._build_target_fit(umf_array, target, has_knao=False)
        assert fit["Si:Al"]["achieved"] == pytest.approx(10.0)
        assert fit["Si:Al"]["in_range"] is True
