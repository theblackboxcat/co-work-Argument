"""
analyze_depth.py — does the transfer penalty GROW with depth?

Reads results/depth_scan.jsonl and tests the one prediction that separates
"symbol memorisation" from "structural abstraction":

    memorisation   penalty FLAT in depth (the signature table is 6 fixed
                   lookups; depth adds nothing to learn)
    structure      penalty GROWS with depth (type errors compound along the
                   chain)

Penalty is acc(TT) - acc(cell) at matched depth, paired by seed, exactly as
in analyze_transfer.py so the numbers are comparable with §7.3.

READING THE OUTPUT.  For each test substrate we print the penalty at each
depth with a bootstrap CI over seeds, then the log-linear slope of penalty
against depth with its own CI.  A slope CI containing zero is a flat penalty.
"""

import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CHANCE = 1.0 / 18.0
CRITERION = 0.60

CELLS = ["TT", "Thighovl", "TU", "Tlowovl"]
BASELINE = "TT"
META = {"TT": (6, 2.0), "Thighovl": (5, 2.0), "TU": (2, 3.0),
        "Tlowovl": (0, 3.0)}


def load(paths):
    rows = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("acc") is not None and not np.isnan(r["acc"]):
                    rows.append(r)
    return rows


def boot(v, n=4000, seed=0):
    v = [x for x in v if x is not None and not np.isnan(x)]
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def slope_ci(per_depth_seed, n=4000, seed=0):
    """Per-seed OLS slope of penalty against depth, bootstrapped over seeds.

    per_depth_seed : {depth: {seed: penalty}}
    Returns (mean_slope, lo, hi, n_seeds).  A CI containing 0 is a flat
    penalty (memorisation); a CI strictly above 0 is a growing penalty
    (structural composition).
    """
    depths = sorted(per_depth_seed)
    if len(depths) < 2:
        return float("nan"), float("nan"), float("nan"), 0
    seeds = sorted(set.intersection(*[set(per_depth_seed[d]) for d in depths]))
    # a slope needs at least 2 distinct depths per seed
    seeds = [s for s in seeds
             if len({d for d in depths if s in per_depth_seed[d]}) >= 2]
    if len(seeds) < 3:
        return float("nan"), float("nan"), float("nan"), len(seeds)
    slopes = []
    for s in seeds:
        xs = np.array([d for d in depths if s in per_depth_seed[d]], dtype=float)
        ys = np.array([per_depth_seed[d][s] for d in depths if s in per_depth_seed[d]],
                      dtype=float)
        if len(set(xs)) < 2:
            continue
        slopes.append(float(np.polyfit(xs, ys, 1)[0]))
    if len(slopes) < 3:
        return float("nan"), float("nan"), float("nan"), len(slopes)
    slopes = np.array(slopes)
    b = float(slopes.mean())
    rng = np.random.default_rng(seed)
    bs = [float(np.mean(rng.choice(slopes, len(slopes), replace=True)))
          for _ in range(n)]
    return b, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), len(slopes)


def main():
    paths = sys.argv[1:] or [os.path.join(HERE, "results", "depth_scan.jsonl")]
    rows = load(paths)
    if not rows:
        print("no data")
        return
    depths = sorted({r["depth"] for r in rows})
    ns = sorted({r["n_train"] for r in rows})
    print(f"{len(rows)} depth-scan runs  |  chance = {CHANCE:.3f}  "
          f"| criterion = {CRITERION}")
    print(f"depths = {depths}   n grid = {ns}")

    cell_seed = defaultdict(dict)
    for r in rows:
        cell_seed[(r["test_kind"], r["depth"], r["seed"])][r["n_train"]] = r["acc"]

    print("\n" + "=" * 78)
    print("MEAN ACCURACY on the test substrate (n averaged over grid & seeds)")
    print("=" * 78)
    print(f"{'cell':>10}" + "".join(f"{'d=' + str(d):>10}" for d in depths))
    for c in CELLS:
        row = ""
        for d in depths:
            vals = [r["acc"] for r in rows if r["test_kind"] == c and r["depth"] == d]
            row += f"{np.mean(vals):10.3f}" if vals else f"{'-':>10}"
        print(f"{c:>10}{row}")

    print("\n" + "=" * 78)
    print("SANITY  is the baseline above the criterion at each depth?")
    print("=" * 78)
    for d in depths:
        vals = [r["acc"] for r in rows if r["test_kind"] == BASELINE and r["depth"] == d]
        mx = max(vals) if vals else float("nan")
        ok = "OK" if (vals and np.mean(vals) > CRITERION) else \
             "BASELINE BELOW CRITERION -- penalty not interpretable here"
        print(f"  depth {d}: mean {np.mean(vals):.3f}  max {mx:.3f}   {ok}"
              if vals else f"  depth {d}: no data")

    print("\n" + "=" * 78)
    print("PRIMARY  penalty = acc(TT) - acc(cell), paired by seed")
    print("         POSITIVE = transfer costs accuracy")
    print("=" * 78)
    print(f"{'cell':>10} {'ovl':>4}" + "".join(f"{'d=' + str(d):>18}" for d in depths))
    per_depth_pen = defaultdict(dict)
    for c in CELLS:
        if c == BASELINE:
            continue
        line = f"{c:>10} {META[c][0]:4d}"
        for d in depths:
            per_seed = {}
            for s in range(64):
                db = cell_seed.get((BASELINE, d, s), {})
                dc = cell_seed.get((c, d, s), {})
                common = sorted(set(db) & set(dc))
                if common:
                    per_seed[s] = float(np.mean([db[n] - dc[n] for n in common]))
            if not per_seed:
                line += f"{'-':>18}"
                continue
            vals = list(per_seed.values())
            m = float(np.mean(vals))
            lo, hi = boot(vals)
            per_depth_pen[c][d] = per_seed
            line += f"{m:>10.3f}[{lo:+.3f},{hi:+.3f}]"
        print(line)

    print("\n" + "=" * 78)
    print("THE DECISIVE TEST  slope of penalty against depth")
    print("         memorisation predicts ~0 ; structure predicts > 0")
    print("=" * 78)
    print(f"{'cell':>10} {'ovl':>4} {'slope':>9} {'95% CI':>22} {'seeds':>6}")
    verdicts = {}
    for c in CELLS:
        if c == BASELINE:
            continue
        if len(per_depth_pen[c]) < 2:
            print(f"{c:>10} {META[c][0]:4d}   insufficient depths")
            continue
        b, lo, hi, k = slope_ci(per_depth_pen[c])
        flat = (np.isnan(lo) or lo <= 0 <= hi)
        verdicts[c] = (b, lo, hi, flat)
        tag = "FLAT -> memorisation favoured" if flat else "RISES -> structure favoured"
        print(f"{c:>10} {META[c][0]:4d} {b:9.3f} [{lo:+.3f}, {hi:+.3f}] {k:6d}   {tag}")

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    flat_cells = [c for c, v in verdicts.items() if v[3]]
    rise_cells = [c for c, v in verdicts.items() if not v[3]]
    if rise_cells and flat_cells:
        print(f"  Mixed. {', '.join(rise_cells)} rise with depth while "
              f"{', '.join(flat_cells)} stay flat.")
        print("  A single depth-independent cost cannot produce both, so the")
        print("  flat cells are the ones whose penalty is pure symbol lookup")
        print("  and the rising cells are the ones where type composition is")
        print("  doing work.  §7.3's depth-3-only reading was under-determined.")
    elif rise_cells:
        print("  ALL damaged substrates rise with depth.  The penalty is NOT a")
        print("  one-off memorisation cost: the model is compounding type")
        print("  errors along the chain, which is evidence of composition.")
        print("  §7.3's 'symbol memorisation' reading must be REVISED.")
    elif flat_cells:
        print("  All penalties are FLAT in depth.  A depth-independent cost is")
        print("  what a memorised signature table predicts, and depth is the")
        print("  axis on which composition would have shown up.  This favours")
        print("  memorisation over structural abstraction.")
    else:
        print("  no usable slopes")
    print("\n  Standing caveat: a flat slope is compatible with memorisation but")
    print("  does not prove it; a model could fail to compose for reasons")
    print("  unrelated to memorisation.  And none of this bears on A vs B,")
    print("  since both are claims about human sensory coupling.")


if __name__ == "__main__":
    main()
