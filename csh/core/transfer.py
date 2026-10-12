"""
transfer.py — the orthogonal test from §8.1.

WHAT THIS DOES.  Arms S and K established that the threshold tracks relational
STRUCTURE (C_eff) rather than symbol count or symbol identity.  That is
consistent with two hypotheses that the existing design cannot separate:

    A  sensory constraint
       the type structure is the constraint because it is the residue of human
       sensorimotor experience; a model must acquire the localisation that
       structure provides, and that acquisition does not transfer to a
       substrate that lacks it

    B  inductive-bias alignment
       the sequence-prediction task's inductive bias happens to match human
       preferences; the structure is neither necessary nor privileged, so
       whatever the model learns transfers freely between substrates

Both predict identical results under symbol substitution (arms S and K).  The
way to separate them is an operation on a DIFFERENT axis: train on one
substrate, test on another, keeping the symbol inventory fixed.

THE 2x2 MATRIX.  Training substrate x test substrate, both at n_rel = 6 and both
using the SAME six relation symbols.  Only the type assignment changes.

                     test: TYPED            test: UNTYPED
    train TYPED      TT  (baseline)          TU  (typed -> untyped)
    train UNTYPED    UT  (untyped -> typed)  UU  (baseline)

    TT and UU are within-substrate baselines.  TU and UT are the transfer
    cells.  What matters is the TRANSFER PENALTY relative to each row's own
    baseline:

        penalty(TU) = acc(TU) - acc(TT)     trained typed, tested untyped
        penalty(UT) = acc(UT) - acc(UU)     trained untyped, tested typed

  A predicts BOTH penalties negative and large: the structural statistics are
  acquired per substrate, so leaving the substrate costs accuracy.
  B predicts both penalties near zero: nothing substrate-specific was acquired.

WHY UNTYPEd IS THE RIGHT "OTHER" SUBSTRATE.  An untyped substrate still has 3
entity pools and 6 relations, so the surface encoding, the token count (46) and
the entity inventory are IDENTICAL to the typed substrate.  What differs is
only that relation types are drawn independently at random: branching 3 instead
of 2, C(3) = 57 instead of 24, and C_eff(3) collapsed to 9 instead of 24.  So
the constraint is genuinely weaker while everything the model can see is
unchanged.

  Nothing is revealed.  The model is never told which structure holds; it only
  sees facts.  So "sensory coupling" here can only enter as the human-designed
  structure of the training distribution, which is exactly the quantity under
  test.

A CAUTION WE STATE UP FRONT.  A negative result (transfer free) does not prove
B.  It only removes the specific mechanism A would need: substrate-specific
acquisition.  B remains one of several explanations.  A positive result (costly
transfer) is much stronger — it would rule out the "structure is irrelevant"
family outright.
"""

import argparse
import itertools
import json
import multiprocessing as mp
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from surfaces import Surface
from substrate2 import Gen, c_eff, N_ENT

DEPTH = 3
N_TEST = 400
NS = [2000, 3000, 4000, 5000, 6500]
SURFACE = "en"

# ---- the typed reference substrate (identical to substrate2.build(1))
TYPED_ASSIGN = [(0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)]

# ---- the untyped substrate: relation types drawn independently, branching 3.
# Searched once, then FROZEN: all 3 dom types and all 3 ran types are covered,
# no dead-end relation, and every depth-3 problem is solvable (200/200 yield).
UNTYPED_ASSIGN = [(0, 1), (0, 0), (0, 0), (0, 0), (2, 0), (1, 2)]

SUBSTRATES = {"typed": TYPED_ASSIGN, "untyped": UNTYPED_ASSIGN}
CELLS = ["TT", "TU", "UT", "UU"]


def substrate_of(kind: str):
    """Same entity pools as substrate2.build(1); only `assign` differs."""
    assign = SUBSTRATES[kind]
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


def run_one(train_kind, test_kind, n_train, seed):
    from model import build_vocab, train_model
    sub_tr = substrate_of(train_kind)
    sub_te = substrate_of(test_kind)
    assert not sub_tr["dead"], f"train substrate has dead ends: {sub_tr['dead']}"
    assert not sub_te["dead"], f"test substrate has dead ends: {sub_te['dead']}"

    g_tr = Gen(sub_tr, seed=1000 + seed)
    g_te = Gen(sub_te, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert train_p and test_p

    # identical surface, identical symbol inventory on both sides
    s_tr = Surface(SURFACE, sub_tr["n_rel"])
    s_te = Surface(SURFACE, sub_te["n_rel"])
    train_r = [s_tr.render(p) for p in train_p]
    test_r = [s_te.render(p) for p in test_p]

    toks = {len(r["tokens"]) for r in train_r[:200]}
    assert len(toks) == 1, f"token parity broken: {toks}"
    tok_test = {len(r["tokens"]) for r in test_r[:200]}
    assert tok_test == toks, f"train/test token mismatch: {toks} vs {tok_test}"

    vocab = build_vocab(train_r + test_r)
    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    c3_tr, eff_tr = c_eff(sub_tr["assign"], 3)
    c3_te, eff_te = c_eff(sub_te["assign"], 3)
    return {"cell": train_kind[0].upper() + test_kind[0].upper(),
            "train_kind": train_kind, "test_kind": test_kind,
            "n_rel": sub_tr["n_rel"], "n_train": n_train, "seed": seed,
            "acc": acc, "steps": steps, "vocab": len(vocab),
            "tok": toks.pop(),
            "branch_tr": round(sub_tr["branching"], 2),
            "branch_te": round(sub_te["branching"], 2),
            "C3_tr": c3_tr, "C3_te": c3_te,
            "Ceff3_tr": eff_tr, "Ceff3_te": eff_te,
            "secs": round(time.time() - t0, 1)}


def job(spec):
    try:
        return run_one(*spec)
    except Exception:
        import traceback
        return {"acc": float("nan"), "train_kind": spec[0], "test_kind": spec[1],
                "n_train": spec[2], "seed": spec[3],
                "error": traceback.format_exc()[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", default="results/transfer.jsonl")
    ap.add_argument("--ns", type=str, default=None,
                    help="comma-separated n grid; overrides NS.  Existing rows "
                         "are skipped, so this can be used to EXTEND the grid "
                         "without redoing earlier points.")
    args = ap.parse_args()
    if args.ns:
        NS[:] = [int(x) for x in args.ns.split(",")]

    for k in ("typed", "untyped"):
        s = substrate_of(k)
        c3, eff = c_eff(s["assign"], 3)
        g = Gen(s, seed=0)
        y = sum(1 for _ in range(200) if g.make(DEPTH))
        print(f"{k:8s} assign={s['assign']} branching={s['branching']:.2f} "
              f"C(3)={c3} C_eff(3)={eff} dead={s['dead']} yield={y}/200")

    specs = [(tr, te, n, sd)
             for tr, te in (("typed", "typed"), ("typed", "untyped"),
                            ("untyped", "typed"), ("untyped", "untyped"))
             for n, sd in itertools.product(NS, range(args.seeds))]

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("train_kind"), r.get("test_kind"),
                              r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    specs.sort(key=lambda s: (s[2], s[0], s[1]))
    print(f"\ntransfer jobs = {len(specs)}  seeds = {args.seeds}  "
          f"workers = {args.workers}\n", flush=True)

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
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | ETA {eta/60:.1f}m", flush=True)
    print("done ->", args.out)


if __name__ == "__main__":
    main()
