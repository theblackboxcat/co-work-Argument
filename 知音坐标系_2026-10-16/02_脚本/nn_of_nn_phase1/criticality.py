"""Single change-point piecewise-constant least squares + seed bootstrap CI."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


def piecewise_constant_sse(y: np.ndarray, t: int) -> float:
    """SSE with change after index t (left = 0..t inclusive, right = t+1..)."""
    left, right = y[: t + 1], y[t + 1 :]
    if left.size == 0 or right.size == 0:
        return np.inf
    return float(((left - left.mean()) ** 2).sum() + ((right - right.mean()) ** 2).sum())


def best_changepoint(
    alphas: Sequence[float],
    values: Sequence[float],
    min_side: int = 2,
) -> Optional[Dict[str, Any]]:
    """
    Single change-point piecewise-constant LS.
    Critical candidate if both sides ≥ min_side points.
    Returns dict with alpha_c (right-edge of left segment), gap, levels, idx.
    """
    a = np.asarray(alphas, dtype=float)
    y = np.asarray(values, dtype=float)
    n = len(y)
    if n < 2 * min_side:
        return None
    best_t, best_sse = None, np.inf
    for t in range(min_side - 1, n - min_side):
        sse = piecewise_constant_sse(y, t)
        if sse < best_sse:
            best_sse, best_t = sse, t
    if best_t is None:
        return None
    left, right = y[: best_t + 1], y[best_t + 1 :]
    mu_l, mu_r = float(left.mean()), float(right.mean())
    gap = mu_r - mu_l
    # alpha_c: midpoint between a[best_t] and a[best_t+1]
    alpha_c = float(0.5 * (a[best_t] + a[best_t + 1]))
    null_sse = float(((y - y.mean()) ** 2).sum())
    return {
        "alpha_c": alpha_c,
        "idx": int(best_t),
        "mu_left": mu_l,
        "mu_right": mu_r,
        "gap": gap,
        "sse": best_sse,
        "null_sse": null_sse,
        "improved": best_sse < null_sse - 1e-15,
    }


def bootstrap_gap_ci(
    seed_matrix: np.ndarray,
    alphas: Sequence[float],
    min_side: int,
    n_boot: int,
    ci_level: float,
    rng: np.random.Generator,
) -> Dict[str, Any]:
    """
    seed_matrix: shape [n_seeds, n_alpha] raw U or m per seed.
    For each bootstrap: resample seeds, mean across seeds, refit changepoint, collect gap.
    Critical if 95% CI of gap excludes 0 AND both sides ≥ min_side on the mean curve.
    """
    n_seeds, n_a = seed_matrix.shape
    mean_curve = seed_matrix.mean(axis=0)
    base = best_changepoint(alphas, mean_curve, min_side=min_side)
    if base is None:
        return {
            "critical": False,
            "reason": "grid_too_coarse_or_short",
            "alpha_c": None,
            "gap": None,
            "ci_low": None,
            "ci_high": None,
            "mu_left": None,
            "mu_right": None,
        }
    gaps = []
    alpha_cs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n_seeds, size=n_seeds)
        curve = seed_matrix[idx].mean(axis=0)
        cp = best_changepoint(alphas, curve, min_side=min_side)
        if cp is None:
            continue
        gaps.append(cp["gap"])
        alpha_cs.append(cp["alpha_c"])
    if len(gaps) < max(20, n_boot // 5):
        return {
            "critical": False,
            "reason": "bootstrap_unstable",
            "alpha_c": base["alpha_c"],
            "gap": base["gap"],
            "ci_low": None,
            "ci_high": None,
            "mu_left": base["mu_left"],
            "mu_right": base["mu_right"],
        }
    gaps_a = np.asarray(gaps)
    lo = float(np.quantile(gaps_a, (1 - ci_level) / 2))
    hi = float(np.quantile(gaps_a, 1 - (1 - ci_level) / 2))
    excludes_0 = (lo > 0 and hi > 0) or (lo < 0 and hi < 0)
    # also require improvement over flat
    critical = bool(excludes_0 and base["improved"])
    return {
        "critical": critical,
        "reason": "ok" if critical else ("ci_includes_0" if not excludes_0 else "no_sse_improve"),
        "alpha_c": base["alpha_c"],
        "gap": base["gap"],
        "ci_low": lo,
        "ci_high": hi,
        "mu_left": base["mu_left"],
        "mu_right": base["mu_right"],
        "alpha_c_boot_mean": float(np.mean(alpha_cs)) if alpha_cs else None,
    }


def same_morphology(
    cp_a: Dict[str, Any],
    cp_b: Dict[str, Any],
    rel_alpha: float = 0.20,
    gap_ratio_bounds: Tuple[float, float] = (0.5, 2.0),
) -> bool:
    """O-H vs O-M/D same morphology: α_c within 20% and gap same sign, ratio in [0.5,2]."""
    if not cp_a.get("critical") or not cp_b.get("critical"):
        return False
    aa, ab = cp_a["alpha_c"], cp_b["alpha_c"]
    if aa is None or ab is None or aa <= 0:
        return False
    if abs(aa - ab) / aa >= rel_alpha:
        return False
    ga, gb = cp_a["gap"], cp_b["gap"]
    if ga == 0 or gb == 0:
        return False
    if np.sign(ga) != np.sign(gb):
        return False
    ratio = abs(gb) / abs(ga)
    return gap_ratio_bounds[0] <= ratio <= gap_ratio_bounds[1]
