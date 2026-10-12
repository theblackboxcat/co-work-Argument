"""
transfer_null.py — the control that makes transfer.py interpretable.

THE PROBLEM WITH transfer.py ALONE.  The typed and untyped substrates are
different distributions.  So if transfer costs accuracy, the naive reading is
"the model had to acquire this substrate's type structure specifically".  But a
weaker explanation fits the same data: ANY mismatch between training and test
distribution costs accuracy, no structure required.  Under that reading a
transfer penalty says nothing about type structure at all.

WHAT THIS RUNS.  The minimal mismatch that is NOT a structure change: train on
a substrate, test on the SAME substrate with relation labels renamed.

    T->T    train typed, normal labels    -> test typed, normal labels
    T->Tp   train typed, normal labels    -> test typed, PERMUTED labels
    U->U    train untyped, normal labels  -> test untyped, normal labels
    U->Up   train untyped, normal labels  -> test untyped, PERMUTED labels

Relabelling changes which token string denotes which relation.  The type
structure, the branching factor, C(3), C_eff(3), the legal-sequence set and the
token count are all UNCHANGED.  So this is pure surface renaming.

THE LOGIC.

    if T->Tp and U->Up are free (at their own baselines)
       then a train/test mismatch per se is harmless in this setup, and any
       penalty seen in the typed<->untyped transfer cells is attributable to the
       type STRUCTURE, not to the mismatch as such.

    if T->Tp costs accuracy
       then the transfer design is confounded and no structural conclusion can
       be drawn from it.

This is the same role the semantic-null controls played in arm S: without them,
a flat result is uninterpretable.  Here, without them, a POSITIVE result is
uninterpretable.
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

from surfaces import PermutedSurface, Surface
from substrate2 import Gen, c_eff
from transfer import DEPTH, N_TEST, NS, substrate_of


def run_one(train_kind, test_kind, n_train, seed, test_perm):
    from model import build_vocab, train_model
    sub_tr = substrate_of(train_kind)
    sub_te = substrate_of(test_kind)
    assert not sub_tr["dead"] and not sub_te["dead"]

    g_tr = Gen(sub_tr, seed=1000 + seed)
    g_te = Gen(sub_te, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert train_p and test_p

    s_tr = Surface("en", sub_tr["n_rel"])
    s_te = (PermutedSurface("en", sub_te["n_rel"], mode="rel") if test_perm
            else Surface("en", sub_te["n_rel"]))
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
    c3_tr, eff_tr = c_eff(sub_tr["assign"], 3)
    c3_te, eff_te = c_eff(sub_te["assign"], 3)
    return {"cell": f"{train_kind[0].upper()}{test_kind[0].upper()}"
                     + ("p" if test_perm else ""),
            "arm": "null", "train_kind": train_kind, "test_kind": test_kind,
            "test_perm": bool(test_perm),
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
        return {"acc": float("nan"), "train_kind": spec[0], "test_kind": spec[1],
                "n_train": spec[2], "seed": spec[3], "test_perm": spec[4],
                "error": traceback.format_exc()[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", default="results/transfer_null.jsonl")
    args = ap.parse_args()

    specs = [(tr, tr, n, sd, True)
             for tr in ("typed", "untyped")
             for n, sd in itertools.product(NS, range(args.seeds))]

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("train_kind"), r.get("test_kind"),
                              r.get("n_train"), r.get("seed"),
                              r.get("test_perm")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    specs.sort(key=lambda s: (s[2], s[0]))
    print(f"null-arm jobs = {len(specs)}  seeds = {args.seeds}  "
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
