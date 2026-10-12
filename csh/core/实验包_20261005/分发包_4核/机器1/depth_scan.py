"""
depth_scan.py — the test that can separate MEMORISATION from STRUCTURE.

THE PROBLEM WITH §7.3's VERDICT.  The transfer experiment ended with three
surviving explanations and none selected:

    S1  structural abstraction   the model learned a substrate-independent
                                  algorithm over type transitions
    S2  inductive bias           the model learned nothing substrate-specific;
                                  transfer should be free
    S3  symbol memorisation      the model memorised token -> type-transition
                                  associations and re-derives them at test time

§7.3 measured transfer cost at ONE depth (3) and found the cost tracks
signature damage.  That is consistent with S3 and against S1, but it does not
settle it, because depth was never varied.  Everything in the package holds
depth fixed at 3, so depth is exactly the axis on which S1 and S3 make
DIFFERENT, SHARP PREDICTIONS.

WHY DEPTH SEPARATES THEM.  The signature table maps a relation symbol to a
type transition.  Memorising it (S3) is a fixed, depth-independent cost: six
lookups, learned once.  An algorithm over type transitions (S1) must compose
the chain, and the number of compositions grows with depth.  So:

    S3  memorisation      transfer penalty ~ FLAT in depth.  The signature
                          table is the same 6 entries at depth 3 and depth 5;
                          there is nothing extra to learn.
    S1  structure         transfer penalty GROWS with depth.  More hops means
                          more chances for a wrong type transition, so a
                          substrate whose signature table disagrees with the
                          training substrate compounds its errors along the
                          chain instead of paying a one-off cost.

This is a prediction that can fail.  If the penalty is flat in depth, S1 is
disfavoured and the cheapest explanation (memorisation) wins.  If it grows,
S1 is supported and §7.3's conclusion must be REVISED — because a model that
compounds type errors along a chain is not doing symbol-table lookup.

THE ARMS.  Train on typed at every depth; test on four substrates spanning the
signature-damage range, holding everything else fixed (n_rel = 6, same six
relation symbols, same surface).  We reuse the FROZEN substrates from §7.3 so
the depth-3 numbers are directly comparable:

    TT        overlap 6/6  branching 2.0  baseline (free transfer by definition)
    Thighovl  overlap 5/6  branching 2.0  structure harder, signature nearly
                            intact   -> §7.3: FREE at depth 3
    TU        overlap 2/6  branching 3.0  signature table mostly destroyed
    Tlowovl   overlap 0/6  branching 3.0  signature table fully destroyed
                            -> §7.3: +0.410 at depth 3

All cells at a given depth share the same training substrate (typed), the same
training data size and the same training seed, so the depth comparison is
within-seed and paired.

PER-DEPTH n GRIDS.  The task gets harder with depth, so a single grid would
either miss the transition at depth 5 or waste compute at depth 3.  A probe
(probe_depth.py) measured where the BASELINE arm actually emerges:

    depth 3   crosses criterion ~n=4000     grid 2000-6500
    depth 4   crosses criterion ~n=6000     grid 5000-11000
    depth 5   crosses criterion ~n=12000    grid 11000-20000

Every grid spans from below the baseline's emergence point to comfortably
above it, so a penalty is only ever computed where the baseline has actually
learned the task.  analyze_depth.py prints an explicit sanity line if a
baseline falls below criterion, and flags that depth as uninterpretable.

WHY THIS IS THE RIGHT NEXT STEP.  §8's boundary three says the paper cannot
distinguish A from B.  §7.3 removed A's mechanism but selected nothing.  This
does not settle A versus B either -- nothing at this scale can, since A is a
claim about HUMAN sensory coupling and the substrate is our own construction.
But it CAN settle whether the model is doing symbol lookup or structural
composition, which is the live question §7.3 left open, and it does so on an
axis the package never varied.
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

from surfaces import Surface
from substrate2 import Gen, c_eff
from transfer import TYPED_ASSIGN

# The four test substrates, frozen from §7.3 / decouple.py.
HIGH_OVL_HARD = [(0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (0, 1)]
LOW_OVL_HARD = [(0, 0), (0, 0), (0, 0), (0, 0), (1, 1), (2, 2)]

TEST_SUBSTRATES = {
    "TT": TYPED_ASSIGN,
    "Thighovl": HIGH_OVL_HARD,
    "TU": [(0, 1), (0, 0), (0, 0), (0, 0), (2, 0), (1, 2)],
    "Tlowovl": LOW_OVL_HARD,
}

N_TEST = 400
SURFACE = "en"
DEPTHS = [3, 4, 5]

# Per-depth n grids, set from the measured emergence points (see docstring).
N_GRID = {
    3: [2000, 3000, 4000, 5000, 6500],
    4: [5000, 6500, 8500, 11000],
    5: [11000, 14000, 20000],
}


def substrate_from_assign(assign, kind):
    """Identical construction to transfer.substrate_of (pools, m, branching)."""
    n = len(assign)
    m = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if assign[i][1] == assign[j][0]:
                m[i][j] = 1
    return {"kind": kind, "assign": assign, "m": m, "n_rel": n,
            "pools": [list(range(0, 7)), list(range(7, 12)), list(range(12, 18))],
            "branching": sum(sum(r) for r in m) / n,
            "dead": [i for i in range(n) if sum(m[i]) == 0]}


def overlap(assign):
    return sum(1 for a, b in zip(assign, TYPED_ASSIGN) if a == b)


def run_one(test_kind, depth, n_train, seed):
    from model import build_vocab, train_model
    sub_tr = substrate_from_assign(TYPED_ASSIGN, "typed")
    sub_te = substrate_from_assign(TEST_SUBSTRATES[test_kind], test_kind)
    assert not sub_tr["dead"], f"dead relations in training substrate: {sub_tr['dead']}"
    assert not sub_te["dead"], f"dead relations in test substrate {test_kind}"

    g_tr = Gen(sub_tr, seed=1000 + seed)
    g_te = Gen(sub_te, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [depth], seed=seed)
    test_p = g_te.dataset(N_TEST, [depth], seed=seed + 555)
    assert train_p and test_p

    s_tr = Surface(SURFACE, sub_tr["n_rel"])
    s_te = Surface(SURFACE, sub_te["n_rel"])
    train_r = [s_tr.render(p) for p in train_p]
    test_r = [s_te.render(p) for p in test_p]

    # Token parity WITHIN a depth. Across depths the query grows by one token
    # per hop by construction (46 / 52 / 58), so depth is NOT length-matched --
    # intentional, and discussed in the module docstring. The comparison that
    # matters is across substrates AT a fixed depth, where lengths are equal.
    toks = {len(r["tokens"]) for r in train_r[:200]}
    toks_te = {len(r["tokens"]) for r in test_r[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken at depth {depth}: {toks} vs {toks_te}"

    vocab = build_vocab(train_r + test_r)
    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    c3, eff = c_eff(sub_te["assign"], depth)
    c3_tr, eff_tr = c_eff(sub_tr["assign"], depth)
    return {"cell": test_kind, "arm": "depth_scan", "test_kind": test_kind,
            "train_kind": "typed", "depth": depth,
            "overlap": overlap(sub_te["assign"]),
            "n_rel": sub_tr["n_rel"], "n_train": n_train, "seed": seed,
            "acc": acc, "steps": steps, "vocab": len(vocab), "tok": toks.pop(),
            "branch_tr": round(sub_tr["branching"], 2),
            "branch_te": round(sub_te["branching"], 2),
            "C3_tr": c3_tr, "C3_te": c3, "Ceff_tr": eff_tr, "Ceff_te": eff,
            "secs": round(time.time() - t0, 1)}


def job(spec):
    try:
        return run_one(*spec)
    except Exception:
        import traceback
        return {"acc": float("nan"), "test_kind": spec[0], "depth": spec[1],
                "n_train": spec[2], "seed": spec[3],
                "error": traceback.format_exc()[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--depths", type=str, default=None)
    ap.add_argument("--out", default="results/depth_scan.jsonl")
    args = ap.parse_args()
    if args.depths:
        DEPTHS[:] = [int(x) for x in args.depths.split(",")]

    # Print the structural facts for every (substrate, depth) before spending
    # compute, so an impossible or degenerate cell is caught in seconds.
    print(f"{'cell':>10} {'depth':>5} {'ovl':>4} {'branch':>7} {'C(k)':>7} "
          f"{'C_eff':>7} {'tok':>4}  yield")
    for kind in TEST_SUBSTRATES:
        sub = substrate_from_assign(TEST_SUBSTRATES[kind], kind)
        for d in DEPTHS:
            c3, eff = c_eff(sub["assign"], d)
            g = Gen(sub, seed=0)
            y = sum(1 for _ in range(200) if g.make(d))
            sf = Surface(SURFACE, sub["n_rel"])
            p = Gen(sub, seed=1).dataset(2, [d], seed=1)[0]
            tk = len(sf.render(p)["tokens"])
            flag = "" if y == 200 else "   <-- IMPOSSIBLE CELL"
            print(f"{kind:>10} {d:5d} {overlap(sub['assign']):4d} "
                  f"{sub['branching']:7.2f} {c3:7d} {eff:7d} {tk:4d}  "
                  f"{y}/200{flag}")
    print()

    specs = [(kind, d, n, sd)
             for d in DEPTHS
             for kind in TEST_SUBSTRATES
             for n, sd in itertools.product(N_GRID[d], range(args.seeds))]
    # Cheapest-first ordering so a partial run still covers the low depths.
    specs.sort(key=lambda s: (s[2], s[1], s[0], s[3]))

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("test_kind"), r.get("depth"),
                              r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    total = sum(len(TEST_SUBSTRATES) * len(N_GRID[d]) * args.seeds
                for d in DEPTHS)
    print(f"depth-scan jobs = {len(specs)} (of {total} total)  "
          f"seeds = {args.seeds}  workers = {args.workers}\n", flush=True)

    t0 = time.time()
    n_done = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "a") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            n_done += 1
            el = time.time() - t0
            eta = el / n_done * (len(specs) - n_done)
            print(f"[{n_done}/{len(specs)}] {r.get('cell','?')} "
                  f"d={r.get('depth','?')} n={r.get('n_train','?'):>6} "
                  f"s={r.get('seed','?')} acc={r['acc']:.3f} | "
                  f"ETA {eta/60:.1f}m", flush=True)
    print("done ->", args.out)


if __name__ == "__main__":
    main()
