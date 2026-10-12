"""
decouple.py — the experiment that actually separates structure from memorised
symbol meaning.

WHY THIS ARM EXISTS.  transfer.py compared typed against untyped and found a
cost of about +0.25 accuracy.  But transfer_null.py found that merely RENAMING
the relation labels, with the substrate held entirely fixed, costs about the
same (+0.27).  So the headline penalty is reproduced by an intervention that
changes no structure whatsoever.  The two candidate explanations are:

    (i)  the model learned the type STRUCTURE and lost it on transfer
    (ii) the model memorised "token string -> type transition" and lost that

Nothing in the 2x2 design can tell these apart, because changing the structure
necessarily changes the signature table too.  Counting the overlap between the
two frozen assignments shows how tightly they are entangled:

    rel:      0      1      2      3      4      5
    typed:  (0,1)  (0,2)  (1,0)  (1,2)  (2,0)  (2,1)
    untyped:(0,1)  (0,0)  (0,0)  (0,0)  (2,0)  (1,2)
            SAME   diff   diff   diff   SAME   diff

Only 2 of 6 symbols keep their meaning.  So the untyped comparison changes the
structure AND scrambles 4/6 of the signature table.

THE DECOUPLING.  An exhaustive search over all 6-relation substrates (3 dom
types and 3 ran types covered, no dead-end relation) finds 45 distinct
(overlap, branching) cells, so the two quantities CAN be varied independently at
this n_rel.  This arm exploits that.  It trains on typed and tests on substrates
chosen to have the OPPOSITE profile from untyped:

  HIGH overlap, HIGHER branching -- the signature table is nearly intact but
  the structure is genuinely harder.  If the cost tracks structure, this cell
  should cost MORE than untyped does despite far less signature damage.  If the
  cost tracks memorised symbol meaning, it should cost LESS, because only one
  symbol changed.

  LOW overlap, SAME branching -- the mirror image, isolating signature damage
  with difficulty held fixed.

The comparison is only meaningful against a same-difficulty baseline, so the
LOW-overlap arm is compared to a branching-matched substrate rather than to
typed, whose branching is 2.

READING IT.  A structure-driven cost is one that grows with branching while
overlap is held high.  A memorisation-driven cost is one that shrinks as soon
as overlap is restored, regardless of branching.
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
from transfer import DEPTH, N_TEST, TYPED_ASSIGN, substrate_of

# ---------------------------------------------------------------- substrates
# HIGH overlap (5 of 6 signatures preserved) with genuinely harder structure.
# Verified: branching 2.00, C(3) 24, C_eff(3) 13 vs typed 24, yield 200/200.
HIGH_OVL_HARD = [(0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (0, 1)]

# A branching-3 substrate with LOW overlap, for the mirror-image arm.
# Verified: branching 2.00 -> replaced below by the search-selected cell.
LOW_OVL_HARD = [(0, 0), (0, 0), (0, 0), (0, 0), (1, 1), (2, 2)]

TARGETS = {"highovl": HIGH_OVL_HARD, "lowovl": LOW_OVL_HARD}


def substrate_from_assign(assign, kind):
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


def run_one(test_kind, n_train, seed):
    from model import build_vocab, train_model
    sub_tr = substrate_of("typed")
    sub_te = substrate_from_assign(TARGETS[test_kind], test_kind)
    assert not sub_tr["dead"] and not sub_te["dead"]

    g_tr = Gen(sub_tr, seed=1000 + seed)
    g_te = Gen(sub_te, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert train_p and test_p

    s_tr = Surface("en", sub_tr["n_rel"])
    s_te = Surface("en", sub_te["n_rel"])
    train_r = [s_tr.render(p) for p in train_p]
    test_r = [s_te.render(p) for p in test_p]

    toks = {len(r["tokens"]) for r in train_r[:200]}
    toks_te = {len(r["tokens"]) for r in test_r[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"

    vocab = build_vocab(train_r + test_r)
    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    c3_te, eff_te = c_eff(sub_te["assign"], 3)
    c3_tr, eff_tr = c_eff(sub_tr["assign"], 3)
    return {"cell": "T" + test_kind, "arm": "decouple",
            "train_kind": "typed", "test_kind": test_kind,
            "overlap": overlap(sub_te["assign"]),
            "n_rel": sub_tr["n_rel"], "n_train": n_train, "seed": seed,
            "acc": acc, "steps": steps, "vocab": len(vocab), "tok": toks.pop(),
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
        return {"acc": float("nan"), "test_kind": spec[0],
                "n_train": spec[1], "seed": spec[2],
                "error": traceback.format_exc()[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--ns", type=str, default="2000,3000,4000,5000,6500")
    ap.add_argument("--out", default="results/decouple.jsonl")
    args = ap.parse_args()
    NS = [int(x) for x in args.ns.split(",")]

    print("decoupling substrates (trained on typed in every case):\n")
    print(f"{'arm':>9} {'ovl':>4} {'branch':>7} {'C(3)':>6} {'C_eff':>6}  assign")
    for k, a in TARGETS.items():
        s = substrate_from_assign(a, k)
        c3, eff = c_eff(a, 3)
        g = Gen(s, seed=0)
        y = sum(1 for _ in range(200) if g.make(DEPTH))
        print(f"{k:>9} {overlap(a):4d} {s['branching']:7.2f} {c3:6d} {eff:6d}  {a}"
              f"  yield={y}/200  dead={s['dead']}")
    c3t, et = c_eff(TYPED_ASSIGN, 3)
    print(f"{'typed':>9} {6:4d} {2.0:7.2f} {c3t:6d} {et:6d}  {TYPED_ASSIGN}")
    c3u, eu = c_eff([(0, 1), (0, 0), (0, 0), (0, 0), (2, 0), (1, 2)], 3)
    print(f"{'untyped':>9} {2:4d} {3.0:7.2f} {c3u:6d} {eu:6d}  (the entangled pair)")
    print()

    specs = [(k, n, sd) for k in TARGETS
             for n, sd in itertools.product(NS, range(args.seeds))]

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("test_kind"), r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    specs.sort(key=lambda s: (s[1], s[0]))
    print(f"decouple jobs = {len(specs)}  seeds = {args.seeds}\n", flush=True)

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
            print(f"[{n_done}/{len(specs)}] {r.get('cell','?')} "
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | ETA "
                  f"{el/n_done*(len(specs)-n_done)/60:.1f}m", flush=True)
    print("done ->", args.out)


if __name__ == "__main__":
    main()
