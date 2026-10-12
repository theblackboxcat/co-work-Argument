"""
experiment.py — measures the EMERGENCE THRESHOLD.

Theoretical question (the user's hypothesis, restated operationally):

  H1 (surface invariance). The threshold at which compositional reasoning
  emerges is a property of the underlying cognitive substrate, not of the
  surface symbol system. Therefore, replacing the surface language while
  holding the substrate fixed should NOT move the threshold appreciably.

  H2 (substrate complexity). The threshold DOES move when the substrate gets
  more complex, where complexity = the number of distinct relational primitives
  the learner must acquire (N_REL). This is the positive control: without it,
  H1 would be satisfied trivially by a model that never learns anything.

Design. 6 surfaces x 4 substrate complexities x S seeds, plus a learning curve
over training-set size so the threshold is estimated, not guessed.

  arm A  surface sweep    : n_rel fixed at 6, 6 surfaces        -> tests H1
  arm B  substrate sweep  : surface fixed at 'en', n_rel 2..10  -> tests H2
  arm C  joint            : the full 6 x 4 grid                 -> interaction

Because tokens-per-fact, facts-per-problem, depth, architecture, optimiser
and batch size are identical everywhere, any threshold difference is
attributable to the manipulated variable alone.
"""

import argparse
import itertools
import json
import os
import time
from typing import List

import torch

from model import Vocab, build_vocab, train_model, accuracy, encode_batch
from substrate import build, Gen, branching_counts
from surfaces import Surface, PermutedSurface, SURFACES

DEPTH = 3                 # every measured problem requires 2 compositions
N_TEST = 400              # held-out evaluation set (identical across arms)


def build_arm(n_rel: int, surface: str, n_train: int, seed: int):
    """Builds rendered train/test sets. The PROBLEMS depend only on
    (n_rel, seed); the surface only re-encodes them."""
    sub = build(n_rel)
    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    if surface == "relperm":
        surf = PermutedSurface("en", n_rel, mode="rel")
    elif surface == "entperm":
        surf = PermutedSurface("en", n_rel, mode="ent")
    else:
        surf = Surface(surface, n_rel)
    train_r = [surf.render(p) for p in train_p]
    test_r = [surf.render(p) for p in test_p]
    # vocabulary is fixed over train+test so train and eval share a space
    vocab = build_vocab(train_r + test_r)
    return vocab, train_r, test_r, sub


def run_one(n_rel, surface, n_train, seed):
    vocab, train_r, test_r, sub = build_arm(n_rel, surface, n_train, seed)
    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r,
                                epochs=1, batch=32, lr=3e-4, seed=seed)
    return {"n_rel": n_rel, "surface": surface, "n_train": n_train,
            "seed": seed, "acc": acc, "steps": steps,
            "vocab": len(vocab), "secs": round(time.time() - t0, 1),
            "branching": sub["branching"],
            "C": branching_counts(sub["m"], 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="A", choices=["A", "B", "C", "smoke"])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", default="results")
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if args.arm == "smoke":
        grid = [(6, "en", 2000, 0)]
    elif args.arm == "A":
        # surface sweep, substrate fixed
        grid = [(6, s, nt, sd) for s in SURFACES
                for nt in [1000, 2000, 4000, 8000] for sd in range(args.seeds)]
    elif args.arm == "B":
        # substrate complexity sweep, surface fixed
        grid = [(nr, "en", nt, sd) for nr in [2, 4, 6, 10]
                for nt in [1000, 2000, 4000, 8000] for sd in range(args.seeds)]
    else:
        grid = [(nr, s, nt, sd) for nr in [2, 4, 6, 10] for s in SURFACES
                for nt in [1000, 4000] for sd in range(args.seeds)]

    if args.quick:
        grid = grid[:max(4, len(grid) // 8)]

    print(f"arm={args.arm}  runs={len(grid)}")
    rows = []
    fpath = os.path.join(args.out, f"arm_{args.arm}.jsonl")
    with open(fpath, "a") as fh:
        for i, (nr, sf, nt, sd) in enumerate(grid):
            r = run_one(nr, sf, nt, sd)
            rows.append(r)
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            print(f"[{i+1}/{len(grid)}] n_rel={nr} {sf:6} n={nt:5} s={sd} "
                  f"acc={r['acc']:.3f} V={r['vocab']:3d} {r['secs']}s",
                  flush=True)
    print("done ->", fpath)


if __name__ == "__main__":
    main()
