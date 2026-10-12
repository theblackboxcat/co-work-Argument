"""probe_depth.py — find the emergence n for each depth BEFORE spending the
depth-scan budget.  A transfer penalty is only interpretable where the baseline
arm has actually crossed the task; below that we would be measuring failure to
learn rather than cost of transfer.
"""
import sys, os, time, itertools, multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_one(depth, n_train, seed):
    from surfaces import Surface
    from substrate2 import Gen, c_eff
    from transfer import TYPED_ASSIGN
    from depth_scan import substrate_from_assign, TEST_SUBSTRATES
    from model import build_vocab, train_model
    sub = substrate_from_assign(TYPED_ASSIGN, "typed")
    g = Gen(sub, seed=1000 + seed); g2 = Gen(sub, seed=99991)
    tr = g.dataset(n_train, [depth], seed=seed)
    te = g2.dataset(300, [depth], seed=seed + 555)
    s = Surface("en", 6)
    trr = [s.render(p) for p in tr]; ter = [s.render(p) for p in te]
    v = build_vocab(trr + ter)
    t0 = time.time()
    _, acc, steps = train_model(v, trr, ter, epochs=1, batch=32, lr=3e-4, seed=seed)
    return {"depth": depth, "n": n_train, "seed": seed, "acc": acc,
            "steps": steps, "secs": round(time.time() - t0, 1)}


def job(spec):
    try:
        return run_one(*spec)
    except Exception:
        import traceback
        return {"depth": spec[0], "n": spec[1], "seed": spec[2],
                "acc": float("nan"), "error": traceback.format_exc()[-300:]}


if __name__ == "__main__":
    specs = [(d, n, s) for d in (4, 5) for n in (10000, 16000, 26000) for s in (0, 1)]
    specs.sort(key=lambda x: (x[0], x[1]))
    print("probe jobs:", len(specs), flush=True)
    ctx = mp.get_context("spawn")
    res = []
    with ProcessPoolExecutor(12, mp_context=ctx) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            res.append(r)
            print(f"d={r['depth']} n={r['n']:>6} s={r['seed']} "
                  f"acc={r['acc']:.3f} ({r['secs']}s)", flush=True)
    print("\n=== mean acc by depth x n (baseline TT, 2 seeds) ===")
    print(f"{'depth':>6}" + "".join(f"{n:>10}" for n in (10000, 16000, 26000)))
    for d in (4, 5):
        row = ""
        for n in (10000, 16000, 26000):
            vals = [r["acc"] for r in res if r["depth"] == d and r["n"] == n]
            row += f"{sum(vals)/len(vals):10.3f}" if vals else f"{'-':>10}"
        print(f"{d:6d}{row}")
