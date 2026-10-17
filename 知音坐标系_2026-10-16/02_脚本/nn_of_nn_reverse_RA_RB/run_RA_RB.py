#!/usr/bin/env python3
"""R-A + R-B grid runner — writes ONLY to nn_of_nn_reverse_RA_RB_2026-10-17/."""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np

from config import (
    ALPHA_LIST,
    BETA_DEFAULT,
    BETA_ORG_LEVELS,
    D_LIST,
    ETA_LEVELS,
    EXEC_PAD_DIMS,
    ORGANIZERS,
    PARENT_PHASE1,
    PARENT_RETEST,
    RESULTS_DIR,
    SEEDS,
    SWEEP_RA,
    SWEEP_RB_I,
    SWEEP_RB_II,
)
from run_cell import run_cell


def _configs():
    """Unique (beta_org, exec_pad_dim, sweep_tag) for R-A + both R-B knives.

    Overlap at (BETA_DEFAULT, 0) shared by R-A baseline and both knives.
    """
    cfgs = []
    # R-A / shared baseline
    cfgs.append((BETA_DEFAULT, 0, SWEEP_RA))
    # R-B knife (i): other β, exec_pad locked 0
    for b in BETA_ORG_LEVELS:
        if abs(b - BETA_DEFAULT) > 1e-12:
            cfgs.append((float(b), 0, SWEEP_RB_I))
    # R-B knife (ii): other exec pads, β locked default
    for ep in EXEC_PAD_DIMS:
        if int(ep) != 0:
            cfgs.append((BETA_DEFAULT, int(ep), SWEEP_RB_II))
    return cfgs


def main():
    assert RESULTS_DIR.resolve() != PARENT_PHASE1.resolve()
    assert RESULTS_DIR.resolve() != PARENT_RETEST.resolve()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    cfgs = _configs()
    cells = []
    for d in D_LIST:
        for alpha in ALPHA_LIST:
            for eta_name, noise_std in ETA_LEVELS.items():
                for org in ORGANIZERS:
                    for seed in SEEDS:
                        for beta_org, exec_pad_dim, sweep in cfgs:
                            cells.append(
                                (d, alpha, eta_name, noise_std, org, "main", "none",
                                 seed, beta_org, exec_pad_dim, sweep)
                            )

    total = len(cells)
    print(f"R-A+R-B grid: {total} cells → {RESULTS_DIR}", flush=True)
    print(f"configs={cfgs}", flush=True)
    print(f"(parents untouched: {PARENT_PHASE1.name}, {PARENT_RETEST.name})", flush=True)
    t0 = time.time()
    rows = []
    for i, cell in enumerate(cells):
        (d, alpha, eta_name, noise_std, org, arm, pad,
         seed, beta_org, exec_pad_dim, sweep) = cell
        row = run_cell(
            d, alpha, eta_name, noise_std, org, arm, pad, seed,
            beta_org=beta_org, exec_pad_dim=exec_pad_dim, sweep=sweep,
        )
        rows.append(row)
        if (i + 1) % 40 == 0 or i == 0 or i + 1 == total:
            elapsed = time.time() - t0
            rate = (i + 1) / max(elapsed, 1e-6)
            eta_s = (total - i - 1) / max(rate, 1e-6)
            print(
                f"[{i+1}/{total}] d={d} α={alpha} {org} β={beta_org} ep={exec_pad_dim} "
                f"seed={seed} U={row['U']:.4f} m={row['m']}  "
                f"({elapsed:.0f}s, ~{eta_s:.0f}s left)",
                flush=True,
            )

    jsonl_path = RESULTS_DIR / "cells_raw.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    csv_path = RESULTS_DIR / "cells_raw.csv"
    keys = list(rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    means = aggregate_means(rows)
    means_path = RESULTS_DIR / "cell_means.csv"
    if means:
        with open(means_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(means[0].keys()))
            w.writeheader()
            w.writerows(means)
    with open(RESULTS_DIR / "cell_means.json", "w", encoding="utf-8") as f:
        json.dump(means, f, ensure_ascii=False, indent=2)

    meta = {
        "n_cells": total,
        "elapsed_sec": time.time() - t0,
        "d_list": D_LIST,
        "alpha_list": ALPHA_LIST,
        "eta_levels": ETA_LEVELS,
        "organizers": ORGANIZERS,
        "seeds": SEEDS,
        "beta_org_levels": BETA_ORG_LEVELS,
        "exec_pad_dims": EXEC_PAD_DIMS,
        "configs": [{"beta_org": b, "exec_pad_dim": e, "sweep": s} for b, e, s in cfgs],
        "package": "nn_of_nn_reverse_RA_RB",
        "prereg": "prereg_反向共形_RA_RB_2026-10-17.md",
        "author_auth": "开跑 2026-10-17",
        "no_E_pass_redeem": True,
        "Fail_Bind_H2_authority": True,
        "parents_untouched": [str(PARENT_PHASE1), str(PARENT_RETEST)],
    }
    with open(RESULTS_DIR / "run_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"Done in {meta['elapsed_sec']:.1f}s. Wrote {jsonl_path}", flush=True)


def aggregate_means(rows):
    from collections import defaultdict

    buckets = defaultdict(list)
    for r in rows:
        key = (r["d"], r["alpha"], r["eta"], r["organizer"], r["arm"], r["pad"],
               r["beta_org"], r["exec_pad_dim"])
        buckets[key].append(r)
    out = []
    for key, rs in sorted(buckets.items()):
        d, alpha, eta, org, arm, pad, beta_org, exec_pad_dim = key
        ms = np.array([r["m"] for r in rs], dtype=float)
        Us = np.array([r["U"] for r in rs], dtype=float)
        ents = np.array([r["entropy"] for r in rs], dtype=float)
        mses = np.array([r["mse"] for r in rs], dtype=float)
        out.append({
            "d": d,
            "alpha": alpha,
            "eta": eta,
            "organizer": org,
            "arm": arm,
            "pad": pad,
            "beta_org": beta_org,
            "exec_pad_dim": exec_pad_dim,
            "n_priv": rs[0]["n_priv"],
            "n": rs[0]["n"],
            "m_mean": float(np.nanmean(ms)),
            "m_std": float(np.nanstd(ms)),
            "U_mean": float(np.nanmean(Us)),
            "U_std": float(np.nanstd(Us)),
            "entropy_mean": float(np.nanmean(ents)),
            "entropy_std": float(np.nanstd(ents)),
            "mse_mean": float(np.nanmean(mses)),
            "mse_std": float(np.nanstd(mses)),
            "n_seeds": len(rs),
            "n_params_mean": float(np.nanmean([r["n_params"] for r in rs])),
            "sweep": rs[0].get("sweep"),
        })
    return out


if __name__ == "__main__":
    main()
