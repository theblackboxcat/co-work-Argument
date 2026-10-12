"""ID-BLOCK CONTROL: does the surface ranking come from the id range?

The fix assigned contiguous id blocks in surface order:
  zh 3..30, en 31..58, lisp 59..85, math 86..113, code 114..140, alien 141..168
and the thresholds came out perfectly monotone in that order
  zh 4143 < en 4146 < lisp 4401 < math 4667 < code 4882 < alien 5659

That is the signature of an ID-RANGE artifact, not a surface effect.

This control runs ONE surface (en) at every block position.  If accuracy
depends on where the block sits, the ranking above is an artifact.
"""
import argparse, itertools, json, multiprocessing as mp, os, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from surfaces import Surface
from substrate2 import Gen, build
from model import Vocab

NAMES = ["zh", "en", "lisp", "math", "code", "alien"]
DEPTH = 3
N_TEST = 400
PROBE_SEED = 4242


def build_vocab_with_slot(surface, slot):
    """Shared vocab where `surface` occupies block `slot` and the others fill
    the remaining slots in order.  Sizes are unchanged; only POSITION moves."""
    order = [n for n in NAMES if n != surface]
    order.insert(slot, surface)
    v = Vocab()
    sub = build(1)
    probe = Gen(sub, seed=PROBE_SEED).dataset(400, [DEPTH], seed=PROBE_SEED)
    for si, n in enumerate(order):
        s = Surface(n, 6)
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"]); toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (si, t))
    return v, order.index(surface)


def run_one(surface, slot, n_train, seed):
    from model import train_model
    sub = build(1)
    g_tr = Gen(sub, seed=1000 + seed); g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    v, si = build_vocab_with_slot(surface, slot)
    s = Surface(surface, sub["n_rel"])
    key = lambda t: "%d\x00%s" % (si, t)
    def enc(ps):
        out = []
        for p in ps:
            r = s.render(p)
            out.append({"tokens": [key(t) for t in r["tokens"]],
                        "target": [key(r["target"][0])]})
        return out
    tr, te = enc(train_p), enc(test_p)
    t0 = time.time()
    _, acc, steps = train_model(v, tr, te, epochs=1, batch=32, lr=3e-4, seed=seed)
    return {"surface": surface, "slot": slot, "n_train": n_train, "seed": seed,
            "acc": acc, "steps": steps, "vocab": len(v),
            "secs": round(time.time() - t0, 1)}


def job(spec):
    try:
        return run_one(*spec)
    except Exception:
        import traceback
        return {"acc": float("nan"), "surface": spec[0], "slot": spec[1],
                "n_train": spec[2], "seed": spec[3],
                "error": traceback.format_exc()[-300:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--surface", default="en")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--ns", default="4000,6500")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", default="results/idblock_control.jsonl")
    args = ap.parse_args()
    ns = [int(x) for x in args.ns.split(",")]

    specs = [(args.surface, slot, n, sd)
             for slot in range(6) for n in ns for sd in range(args.seeds)]
    specs.sort(key=lambda x: (x[2], x[1], x[3]))
    done = set()
    if os.path.exists(args.out):
        for ln in open(args.out):
            try:
                r = json.loads(ln)
                done.add((r["surface"], r["slot"], r["n_train"], r["seed"]))
            except Exception:
                pass
    specs = [s for s in specs if s not in done]
    print(f"surface={args.surface}  jobs={len(specs)}  workers={args.workers}\n",
          flush=True)

    t0 = time.time(); nd = 0
    ctx = mp.get_context("spawn")
    with open(args.out, "a") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n"); fh.flush()
            nd += 1
            print(f"[{nd}/{len(specs)}] slot={r.get('slot')} "
                  f"n={r.get('n_train')} s={r.get('seed')} "
                  f"acc={r['acc']:.3f}", flush=True)
    print("done ->", args.out)


if __name__ == "__main__":
    main()
