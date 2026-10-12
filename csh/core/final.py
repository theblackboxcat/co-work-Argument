"""
final.py — the consolidated, budget-aware experiment.

Design decisions taken after measuring rather than guessing:

  * The coarse pass (115 runs) put the transition between n=2000 and n=8000.
    The focused pass then showed n=1500 is entirely pre-emergence (mean 0.142
    vs chance 0.056) and n>=6500 is slow without adding information, because
    the threshold bracket closes well before it. So the grid is concentrated
    on [2000, 3000, 4000, 5000, 6500].

  * Seed variance is large (identical conditions spanned 0.33 -> 1.00), so
    6 seeds per cell is the minimum for a usable interval estimate.

  * Two arms, run together because they share the substrate at mult=1:

      arm S  surface question. substrate FIXED (mult=1, n_rel=6), 8 surfaces
              including the two semantic-null controls (relperm, entperm).
              Without those controls a flat result is uninterpretable.

      arm K  complexity question, with the CORRECTED knob from substrate2:
              type structure fixed at 3 types / 2 outgoing transitions, so
              C_eff(3) = 24 for every level, while N_REL goes 6 -> 24 and
              branching 2 -> 8. Flat threshold supports the theory (structure
              sets the threshold); rising threshold refutes it (raw symbol
              count sets the threshold).

  Every condition: 5 tokens per fact, 8 facts, depth 3, 18 entities,
  identical architecture and optimiser.
"""

import argparse
import itertools
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from surfaces import Surface, PermutedSurface
from substrate2 import build, Gen, c_eff

DEPTH = 3
N_TEST = 400
NS = [2000, 3000, 4000, 5000, 6500]
SURFACES = ["zh", "en", "lisp", "math", "code", "alien", "relperm", "entperm"]
MULTS = [1, 2, 3, 4]


def render_surface(problems, surface, n_rel):
    if surface == "relperm":
        s = PermutedSurface("en", n_rel, mode="rel")
    elif surface == "entperm":
        s = PermutedSurface("en", n_rel, mode="ent")
    else:
        s = Surface(surface, n_rel)
    return [s.render(p) for p in problems]


def run_one(mult, surface, n_train, seed):
    from model import build_vocab, train_model
    sub = build(mult)
    n_rel = sub["n_rel"]
    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)

    train_r = render_surface(train_p, surface, n_rel)
    test_r = render_surface(test_p, surface, n_rel)
    toks = {len(r["tokens"]) for r in train_r[:200]}
    assert len(toks) == 1, f"token parity broken: {toks}"

    vocab = build_vocab(train_r + test_r)
    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    c3, eff = c_eff(sub["assign"], 3)
    return {"arm": "S" if mult == 1 else "K", "mult": mult, "n_rel": n_rel,
            "surface": surface, "n_train": n_train, "seed": seed, "acc": acc,
            "branching": sub["branching"], "C3": c3, "C_eff3": eff,
            "vocab": len(vocab), "tok": toks.pop(), "steps": steps,
            "secs": round(time.time() - t0, 1)}


def job(spec):
    try:
        return run_one(*spec)
    except Exception:
        import traceback
        return {"acc": float("nan"), "mult": spec[0],
                "surface": spec[1], "n_train": spec[2], "seed": spec[3],
                "error": traceback.format_exc()[-300:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", default="results/final.jsonl")
    args = ap.parse_args()

    specs = []
    # arm S: surfaces at the reference substrate (mult=1, n_rel=6)
    for s, n, sd in itertools.product(SURFACES, NS, range(args.seeds)):
        specs.append((1, s, n, sd))
    # arm K: corrected complexity knob, surface fixed at en
    #      skip mult=1 (already covered by arm S, surface='en')
    for m, n, sd in itertools.product(MULTS[1:], NS, range(args.seeds)):
        specs.append((m, "en", n, sd))

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("mult"), r.get("surface"),
                              r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    # interleave so that both arms progress together, cheapest first
    specs.sort(key=lambda s: (s[2], s[0]))
    print(f"final jobs = {len(specs)}  seeds = {args.seeds}  "
          f"workers = {args.workers}", flush=True)

    t0 = time.time()
    n_done = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "a") as fh, ProcessPoolExecutor(args.workers,
                                                         mp_context=ctx) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            n_done += 1
            el = time.time() - t0
            eta = el / n_done * (len(specs) - n_done)
            print(f"[{n_done}/{len(specs)}] {r.get('arm','?')} mult={r.get('mult','?')} "
                  f"n_rel={r.get('n_rel','?'):>2} {str(r.get('surface','?')):>8} "
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | ETA {eta/60:.1f}m", flush=True)
    print("done ->", args.out)


if __name__ == "__main__":
    main()
