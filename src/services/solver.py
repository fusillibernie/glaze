"""Glaze recipe solver using scipy SLSQP optimization.

Given target UMF oxide ranges and a set of candidate materials,
finds material percentages (summing to 100) that produce a UMF
within the target ranges.
"""

import numpy as np
from dataclasses import dataclass, field
from scipy.optimize import minimize

from ..models.materials import Material, MaterialType, OXIDE_MOLECULAR_WEIGHTS
from .target_resolver import SolverTarget, OxideRange


# Oxides tracked by the solver (order matters — indices are fixed)
SOLVER_OXIDES = [
    "SiO2", "Al2O3", "B2O3",
    "Na2O", "K2O", "Li2O",
    "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO",
]

FLUX_OXIDES = {"Na2O", "K2O", "Li2O", "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO"}

# Material type to functional role — for candidate selection
ROLE_PRIORITY = {
    MaterialType.FELDSPAR: 1,
    MaterialType.SILICA: 2,
    MaterialType.CLAY: 3,
    MaterialType.CALCIUM: 4,
    MaterialType.MAGNESIUM: 5,
    MaterialType.BORON: 6,
    MaterialType.FRIT: 7,
    MaterialType.FLUX: 8,
    MaterialType.ASH: 9,
    MaterialType.ALUMINA: 10,
}


@dataclass
class SolverResult:
    """Result from the glaze solver."""
    ingredients: list[tuple[str, float]]  # (material_name, percentage)
    achieved_umf: dict[str, float]
    target_fit: dict[str, dict]  # oxide -> {min, max, achieved, in_range}
    deviation_score: float  # 0.0 = perfect
    converged: bool
    warnings: list[str] = field(default_factory=list)


class GlazeSolver:
    """Solves for material percentages that hit target UMF ranges."""

    def __init__(self):
        # Build oxide index for matrix operations
        self._oxide_idx = {ox: i for i, ox in enumerate(SOLVER_OXIDES)}
        self._n_oxides = len(SOLVER_OXIDES)

        # Molecular weights array
        self._mol_weights = np.array([
            OXIDE_MOLECULAR_WEIGHTS.get(ox, 1.0) for ox in SOLVER_OXIDES
        ])

        # Flux mask (boolean array)
        self._flux_mask = np.array([ox in FLUX_OXIDES for ox in SOLVER_OXIDES])

    def select_candidates(
        self,
        all_materials: list[Material],
        target: SolverTarget,
        max_candidates: int = 8,
    ) -> list[Material]:
        """Select candidate materials for the solver.

        Strategy:
        1. Include all required/preferred materials from the target.
        2. Fill remaining slots with one material per functional role.
        3. Cap at max_candidates to keep solver tractable.
        """
        candidates: dict[str, Material] = {}
        mat_by_name = {m.name.lower(): m for m in all_materials}

        # Add required materials from constraints
        for constraint in target.material_constraints:
            key = constraint.material_name.lower()
            if key in mat_by_name:
                candidates[key] = mat_by_name[key]

        # Add preferred materials
        for name in target.preferred_materials:
            key = name.lower()
            if key in mat_by_name and len(candidates) < max_candidates:
                candidates[key] = mat_by_name[key]

        # Fill remaining slots by functional role
        roles_filled: set[MaterialType] = set()
        for m in candidates.values():
            roles_filled.add(m.material_type)

        # Sort available materials by role priority
        remaining = [
            m for m in all_materials
            if m.name.lower() not in candidates
        ]
        remaining.sort(key=lambda m: ROLE_PRIORITY.get(m.material_type, 99))

        for m in remaining:
            if len(candidates) >= max_candidates:
                break
            # Add if this role isn't filled yet, or if it's a common essential type
            if m.material_type not in roles_filled:
                candidates[m.name.lower()] = m
                roles_filled.add(m.material_type)

        return list(candidates.values())

    def _build_contribution_matrix(self, materials: list[Material]) -> np.ndarray:
        """Build matrix A where A[i][j] = weight% of oxide j in material i.

        Shape: (n_materials, n_oxides)
        """
        n = len(materials)
        A = np.zeros((n, self._n_oxides))

        for i, mat in enumerate(materials):
            analysis = mat.analysis.oxide_analysis
            for j, oxide in enumerate(SOLVER_OXIDES):
                # Handle KNaO split: Na2O and K2O are separate columns
                A[i, j] = getattr(analysis, oxide, 0.0)

        return A

    def _compute_umf(self, x: np.ndarray, A: np.ndarray) -> np.ndarray:
        """Compute UMF from material percentages.

        x: material percentages (sum to 100)
        A: contribution matrix (n_materials x n_oxides), weight %

        Returns UMF array (n_oxides,)
        """
        # Combined oxide weight % = sum of (material_pct / 100) * material_oxide_wt%
        oxide_wt_pct = (x / 100.0) @ A  # shape: (n_oxides,)

        # Convert weight% to moles
        moles = oxide_wt_pct / self._mol_weights

        # Sum flux moles
        flux_sum = np.sum(moles[self._flux_mask])

        if flux_sum < 1e-10:
            return np.zeros(self._n_oxides)

        # Normalize to unity (UMF)
        return moles / flux_sum

    def _build_target_arrays(self, target: SolverTarget) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Convert SolverTarget oxide ranges to arrays aligned with SOLVER_OXIDES.

        Returns (lo, hi, weights) arrays of shape (n_oxides,).
        Oxides not specified in target get very wide ranges (0, 999) and zero weight.
        """
        lo = np.zeros(self._n_oxides)
        hi = np.full(self._n_oxides, 999.0)
        weights = np.zeros(self._n_oxides)

        has_knao = any(r.oxide == "KNaO" for r in target.oxide_ranges)

        for r in target.oxide_ranges:
            # Skip individual Na2O/K2O if KNaO combined constraint is present
            if has_knao and r.oxide in ("Na2O", "K2O"):
                continue

            if r.oxide == "KNaO":
                # Combined alkali target — handled as a combined constraint in the objective
                na_idx = self._oxide_idx["Na2O"]
                # Store in Na2O slot as combined; K2O handled via the combined constraint
                lo[na_idx] = r.min_val
                hi[na_idx] = r.max_val
                weights[na_idx] = r.weight
                continue

            idx = self._oxide_idx.get(r.oxide)
            if idx is not None:
                lo[idx] = r.min_val
                hi[idx] = r.max_val
                weights[idx] = r.weight

        return lo, hi, weights

    def solve(
        self,
        target: SolverTarget,
        candidate_materials: list[Material],
        n_starts: int = 5,
    ) -> SolverResult:
        """Find material percentages that produce UMF within target ranges.

        Args:
            target: Solver target with oxide ranges and constraints.
            candidate_materials: Materials to use in the recipe.
            n_starts: Number of random restarts for the optimizer.

        Returns:
            SolverResult with best recipe found.
        """
        materials = candidate_materials
        n = len(materials)
        if n == 0:
            return SolverResult(
                ingredients=[], achieved_umf={}, target_fit={},
                deviation_score=999.0, converged=False,
                warnings=["No candidate materials available"],
            )

        A = self._build_contribution_matrix(materials)
        lo_target, hi_target, target_weights = self._build_target_arrays(target)

        # Check if KNaO is a combined constraint
        has_knao = any(r.oxide == "KNaO" for r in target.oxide_ranges)
        knao_range = None
        if has_knao:
            knao_r = target.get_oxide_range("KNaO")
            if knao_r:
                knao_range = (knao_r.min_val, knao_r.max_val, knao_r.weight)

        # Material bounds
        bounds = []
        for i, mat in enumerate(materials):
            mat_lo = 0.0
            mat_hi = 100.0

            # Apply material-specific constraints from target
            for constraint in target.material_constraints:
                if constraint.material_name.lower() == mat.name.lower():
                    mat_lo = constraint.min_pct
                    mat_hi = constraint.max_pct
                    break

            bounds.append((mat_lo, mat_hi))

        # Objective: minimize weighted squared deviation from target midpoints
        midpoints = (lo_target + hi_target) / 2.0
        # For unconstrained oxides (weight=0), midpoint is irrelevant

        def objective(x):
            umf = self._compute_umf(x, A)
            cost = 0.0

            for j in range(self._n_oxides):
                w = target_weights[j]
                if w <= 0:
                    continue

                oxide = SOLVER_OXIDES[j]

                if oxide == "Na2O" and has_knao and knao_range:
                    # Combined KNaO objective
                    k_idx = self._oxide_idx["K2O"]
                    knao_val = umf[j] + umf[k_idx]
                    knao_mid = (knao_range[0] + knao_range[1]) / 2.0
                    cost += knao_range[2] * (knao_val - knao_mid) ** 2
                    continue

                if oxide == "K2O" and has_knao:
                    continue  # Handled by KNaO

                cost += w * (umf[j] - midpoints[j]) ** 2

            # Si:Al ratio penalty
            if target.si_al_ratio:
                si_idx = self._oxide_idx["SiO2"]
                al_idx = self._oxide_idx["Al2O3"]
                if umf[al_idx] > 1e-6:
                    ratio = umf[si_idx] / umf[al_idx]
                    ratio_mid = (target.si_al_ratio[0] + target.si_al_ratio[1]) / 2.0
                    cost += 2.0 * ((ratio - ratio_mid) / ratio_mid) ** 2

            return cost

        # Equality constraint: percentages sum to 100
        eq_constraint = {
            "type": "eq",
            "fun": lambda x: np.sum(x) - 100.0,
        }

        # Run multi-start optimization
        best_result = None
        best_cost = float("inf")
        rng = np.random.default_rng(42)

        for start_idx in range(n_starts):
            if start_idx == 0:
                # First start: heuristic initial guess based on typical proportions
                x0 = self._heuristic_init(materials, bounds)
            else:
                # Random starts within bounds
                x0 = np.array([
                    rng.uniform(lo, max(lo, min(hi, lo + 30.0)))
                    for lo, hi in bounds
                ])
                # Normalize to 100
                total = np.sum(x0)
                if total > 0:
                    x0 = x0 / total * 100.0

            result = minimize(
                objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=[eq_constraint],
                options={"maxiter": 500, "ftol": 1e-10},
            )

            if result.fun < best_cost:
                best_cost = result.fun
                best_result = result

        if best_result is None:
            return SolverResult(
                ingredients=[], achieved_umf={}, target_fit={},
                deviation_score=999.0, converged=False,
                warnings=["Solver failed to find any solution"],
            )

        # Post-process: clean up small contributions
        x_final = best_result.x.copy()
        x_final[x_final < 1.0] = 0.0  # Drop materials under 1%
        total = np.sum(x_final)
        if total > 0:
            x_final = x_final / total * 100.0

        # Build result
        ingredients = []
        for i, mat in enumerate(materials):
            if x_final[i] >= 0.5:
                ingredients.append((mat.name, round(x_final[i], 1)))

        # Sort by percentage descending
        ingredients.sort(key=lambda x: x[1], reverse=True)

        # Compute achieved UMF
        umf_array = self._compute_umf(x_final, A)
        achieved_umf = {}
        for j, oxide in enumerate(SOLVER_OXIDES):
            if umf_array[j] > 0.001:
                achieved_umf[oxide] = round(float(umf_array[j]), 4)

        # Build target_fit
        target_fit = self._build_target_fit(umf_array, target, has_knao)

        # Compute deviation score
        in_range_count = sum(1 for v in target_fit.values() if v["in_range"])
        total_targets = len(target_fit)
        deviation_score = round(float(best_cost), 4)

        # Warnings
        warnings = []
        if not best_result.success:
            warnings.append(f"Solver did not fully converge: {best_result.message}")
        for oxide, fit in target_fit.items():
            if not fit["in_range"]:
                warnings.append(
                    f"{oxide}: achieved {fit['achieved']:.3f}, "
                    f"target [{fit['min']:.3f}, {fit['max']:.3f}]"
                )

        return SolverResult(
            ingredients=ingredients,
            achieved_umf=achieved_umf,
            target_fit=target_fit,
            deviation_score=deviation_score,
            converged=bool(best_result.success),
            warnings=warnings,
        )

    def _heuristic_init(
        self,
        materials: list[Material],
        bounds: list[tuple[float, float]],
    ) -> np.ndarray:
        """Generate a heuristic initial guess based on material types."""
        from ..models.materials import MATERIAL_USAGE_GUIDELINES

        n = len(materials)
        x0 = np.zeros(n)

        for i, mat in enumerate(materials):
            lo, hi = bounds[i]
            guidelines = MATERIAL_USAGE_GUIDELINES.get(mat.material_type)
            if guidelines:
                typical = (guidelines["typical_min"] + guidelines["typical_max"]) / 2.0
                x0[i] = max(lo, min(hi, typical))
            elif lo > 0:
                x0[i] = lo
            else:
                x0[i] = 5.0  # Small default

        # Normalize to 100
        total = np.sum(x0)
        if total > 0:
            x0 = x0 / total * 100.0

        return x0

    def _build_target_fit(
        self,
        umf_array: np.ndarray,
        target: SolverTarget,
        has_knao: bool,
    ) -> dict[str, dict]:
        """Build per-oxide target fit diagnostics."""
        fit = {}

        for r in target.oxide_ranges:
            if r.oxide == "KNaO":
                na_idx = self._oxide_idx["Na2O"]
                k_idx = self._oxide_idx["K2O"]
                achieved = umf_array[na_idx] + umf_array[k_idx]
                fit["KNaO"] = {
                    "min": round(r.min_val, 4),
                    "max": round(r.max_val, 4),
                    "achieved": round(float(achieved), 4),
                    "in_range": bool(r.min_val <= achieved <= r.max_val),
                }
                continue

            idx = self._oxide_idx.get(r.oxide)
            if idx is not None:
                achieved = umf_array[idx]
                fit[r.oxide] = {
                    "min": round(r.min_val, 4),
                    "max": round(r.max_val, 4),
                    "achieved": round(float(achieved), 4),
                    "in_range": bool(r.min_val <= achieved <= r.max_val),
                }

        # Add Si:Al ratio if targeted
        if target.si_al_ratio:
            si_idx = self._oxide_idx["SiO2"]
            al_idx = self._oxide_idx["Al2O3"]
            if umf_array[al_idx] > 1e-6:
                ratio = float(umf_array[si_idx] / umf_array[al_idx])
                fit["Si:Al"] = {
                    "min": round(target.si_al_ratio[0], 2),
                    "max": round(target.si_al_ratio[1], 2),
                    "achieved": round(ratio, 2),
                    "in_range": bool(target.si_al_ratio[0] <= ratio <= target.si_al_ratio[1]),
                }

        return fit
