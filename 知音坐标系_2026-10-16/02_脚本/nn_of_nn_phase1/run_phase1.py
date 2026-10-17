#!/usr/bin/env python3
"""One-command Phase-1 grid: O-H / O-M / D × arms × Pad-⊥ × η × d × α × seeds."""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np

from config import (
    ALPHA_LIST,
    ARMS,
    D_LIST,
    ETA_LEVELS,
    ORGANIZERS,
    PADS,
    RESULTS_DIR,
    SEEDS,
)
from run_cell import run_cell


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    cells = []
    for d in D_LIST:
        for alpha in ALPHA_LIST:
            for eta_name, noise_std in ETA_LEVELS.items():
                for org in ORGANIZERS:
                    for arm in ARMS:
                        for pad in PADS:
                            for seed in SEEDS:
                                cells.append((d, alpha, eta_name, noise_std, org, arm, pad, seed))

    total = len(cells)
    print(f"Phase-1 grid: {total} cells → {RESULTS_DIR}", flush=True)
    t0 = time.time()
    for i, (d, alpha, eta_name, noise_std, org, arm, pad, seed) in enumerate(cells):
        row = run_cell(d, alpha, eta_name, noise_std, org, arm, pad, seed)
        rows.append(row)
        if (i + 1) % 50 == 0 or i == 0 or i + 1 == total:
            elapsed = time.time() - t0
            rate = (i + 1) / max(elapsed, 1e-6)
            eta_s = (total - i - 1) / max(rate, 1e-6)
            print(
                f"[{i+1}/{total}] d={d} α={alpha} {eta_name} {org} {arm} {pad} "
                f"seed={seed} U={row['U']:.4f} m={row['m']}  "
                f"({elapsed:.0f}s elapsed, ~{eta_s:.0f}s left)",
                flush=True,
            )

    # write raw JSONL + CSV
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

    # cell means across seeds
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
        "arms": ARMS,
        "pads": PADS,
        "seeds": SEEDS,
    }
    with open(RESULTS_DIR / "run_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"Done in {meta['elapsed_sec']:.1f}s. Wrote {jsonl_path} and {means_path}", flush=True)


def aggregate_means(rows):
    from collections import defaultdict

    buckets = defaultdict(list)
    for r in rows:
        key = (r["d"], r["alpha"], r["eta"], r["organizer"], r["arm"], r["pad"])
        buckets[key].append(r)
    out = []
    for key, rs in sorted(buckets.items()):
        d, alpha, eta, org, arm, pad = key
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
        })
    return out


if __name__ == "__main__":
    main()
