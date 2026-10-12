#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Slim public smoke: S1g toy confirm (GRU A2C return-std) + Dx2 seed list + S1h2 ES note.

Usage (from package root):
  python code/toy_confirm.py
  python code/toy_confirm.py --epochs 5 --episodes 2   # shorter smoke
  python code/run_s1g_arm.py --arm G_RL_GRU --seed 200 --smoke

This is NOT a full science re-run. Full S1g/S1h2 used frozen thresholds + Dx2 clean seeds.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def show_dx2_seeds():
    seeds_path = ROOT / "frozen" / "clean_seeds_Dx2.json"
    sha_path = ROOT / "frozen" / "clean_seeds_Dx2.sha256"
    data = json.loads(seeds_path.read_text(encoding="utf-8"))
    got = sha256_file(seeds_path)
    recorded = sha_path.read_text(encoding="utf-8").split()[0]
    print("=== Dx2 clean seed list ===")
    print("seeds:", data["seeds"])
    print("n:", data["n"])
    print("file sha256:", got)
    print("recorded sha:", recorded, "OK" if got == recorded else "MISMATCH")
    print("VOID line unchanged: 0.35; denominator: 8")
    print()


def show_s1h2_es_note():
    thr = ROOT / "frozen" / "thresholds_S1h2.json"
    sha = ROOT / "frozen" / "thresholds_S1h2.sha256"
    res = ROOT / "results" / "summary_S1h2.json"
    print("=== S1h2 ES fixed (note; no full retrain here) ===")
    print("code: code/s1h2_es_gru.py")
    print("  - standard OpenAI-ES step: theta += (lr/sigma) * g")
    print("  - selection fix: save best_vec BEFORE theta update;")
    print("    after training, independent K=16 re-eval center vs best_vec, hand over higher")
    print("thresholds sha:", sha.read_text(encoding="utf-8").split()[0])
    print("verify file   :", sha256_file(thr))
    if res.exists():
        s = json.loads(res.read_text(encoding="utf-8"))
        sci = s.get("science", {})
        for arm in ("ES_easy", "ES_main", "ES_easy_legacy"):
            a = sci.get(arm, {})
            if a:
                print(f"  frozen result {arm}: {a.get('n_pass')}/{a.get('n')} "
                      f"(Wilson {a.get('wilson95')})")
        print("routing:", (s.get("routing") or {}).get("verdict") or s.get("routing"))
    print("FORBID: do not write 'evolution unreachable' (no budget scan).")
    print("ALLOW: 'under matched budget, evolution did not reach'.")
    print()


def smoke_gru_a2c(epochs: int, episodes: int, seed: int):
    import torch
    import s1e_gru_rl as G

    print("=== S1g toy confirm: GRU A2C (fixed return std) smoke ===")
    print(f"seed={seed} epochs={epochs} episodes_per_epoch={episodes}")
    print("fix: per-episode MC return standardization (S1f2 → S1g)")
    t0 = time.time()
    params, info = G.train_gru_rl(
        seed=seed, N=4, T=200, hidden=32, lr=0.001,
        epochs_max=epochs, episodes_per_epoch=episodes,
        smoke=True, log_every_epochs=max(1, epochs // 2),
        eval_every_epochs=max(1, min(5, epochs)),
    )
    wall = time.time() - t0
    print(f"done wall_s={wall:.1f} best_ret_train={info.get('best_ret_train')} "
          f"epochs_ran={info.get('epochs_ran')} keys={sorted(params)[:6]}...")
    print("For full arm+acceptance: python code/run_s1g_arm.py --arm G_RL_GRU --seed 200 --smoke")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--episodes", type=int, default=2)
    ap.add_argument("--seed", type=int, default=200)
    ap.add_argument("--skip-train", action="store_true")
    args = ap.parse_args()

    print("sdia-goal-bearing-repro · toy confirm")
    print("package:", ROOT)
    print()
    show_dx2_seeds()
    show_s1h2_es_note()
    if not args.skip_train:
        smoke_gru_a2c(args.epochs, args.episodes, args.seed)
    else:
        print("(skipped GRU smoke train)")
    print("See README.md / PAPER_STATUS.md. Do not overclaim.")


if __name__ == "__main__":
    main()
