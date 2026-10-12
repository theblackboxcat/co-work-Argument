"""
run_all.py — orchestrates the full experiment in parallel across CPU cores.

Runs arm A (surface sweep, substrate fixed) and arm B (substrate complexity
sweep, surface fixed). Each job is independent; results stream to JSONL so
partial progress is never lost.
"""

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed


def job(n_rel, surface, n_train, seed):
    """Runs in a worker process. Calls run_one directly — spawning a
    subprocess from inside the pool deadlocks on fork, which is what an
    earlier version did."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from experiment import run_one
        return run_one(n_rel, surface, n_train, seed)
    except Exception as e:
        import traceback
        return {"n_rel": n_rel, "surface": surface, "n_train": n_train,
                "seed": seed, "acc": float("nan"),
                "error": traceback.format_exc()[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", default="results")
    ap.add_argument("--nmax", type=int, default=32000)
    ap.add_argument("--arms", default="AB")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    NT = [1000, 2000, 4000, 8000, 16000, args.nmax]
    SURF = ["zh", "en", "lisp", "math", "code", "alien", "relperm", "entperm"]
    NREL = [2, 4, 6, 10]

    jobs = []
    if "A" in args.arms:
        for s, nt, sd in itertools.product(SURF, NT, range(args.seeds)):
            jobs.append((6, s, nt, sd))
    if "B" in args.arms:
        for nr, nt, sd in itertools.product(NREL, NT, range(args.seeds)):
            if (nr, "en", nt, sd) not in [(a, b, c, d) for a, b, c, d in jobs]:
                jobs.append((nr, "en", nt, sd))

    print(f"total jobs = {len(jobs)}  workers = {args.workers}  seeds = {args.seeds}")
    fpath = os.path.join(args.out, "main.jsonl")
    done = set()
    if os.path.exists(fpath):
        with open(fpath) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r["n_rel"], r["surface"], r["n_train"], r["seed"]))
                except Exception:
                    pass
        print(f"resuming: {len(done)} already done")
    jobs = [j for j in jobs if j not in done]
    # submit cheap jobs first so results stream in and progress is visible
    jobs.sort(key=lambda j: j[2])

    t0 = time.time()
    n_done = 0
    # spawn method: forkserver-free, but must be 'spawn' to avoid inheriting
    # torch's thread pools from the parent.
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    with open(fpath, "a") as fh, ProcessPoolExecutor(args.workers, mp_context=ctx) as ex:
        futs = {ex.submit(job, *j): j for j in jobs}
        for fut in as_completed(futs):
            j = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"n_rel": j[0], "surface": j[1], "n_train": j[2],
                     "seed": j[3], "acc": float("nan"), "error": str(e)[:300]}
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            n_done += 1
            el = time.time() - t0
            eta = el / n_done * (len(jobs) - n_done)
            print(f"[{n_done}/{len(jobs)}] n_rel={r['n_rel']:2d} {r['surface']:6} "
                  f"n={r['n_train']:6d} s={r['seed']} acc={r['acc']:.3f} "
                  f"| {el/60:.1f}m elapsed, ETA {eta/60:.1f}m", flush=True)
    print("done ->", fpath)


if __name__ == "__main__":
    main()
