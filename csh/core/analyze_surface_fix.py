"""
analyze_surface_fix.py — 修复 id 分配后，S1 还成立吗？

对每个表面按 analysis.threshold 估计涌现阈值，然后：
  * 报告几何均值、极差、CV(log)  —— 与原 S1 同口径，可直接对比
  * 逐对做按种子配对的差 + bootstrap CI —— 检验表面间是否真的可分
  * 明确列出"逐位完全相同"的配对 —— 若修复有效，应无此类配对

用法
    python analyze_surface_fix.py results/surface_fix.jsonl
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analysis as A

CHANCE = 1.0 / 18.0
CRITERION = 0.60
NAMES = ["zh", "en", "lisp", "math", "code", "alien"]


def load(paths):
    rows = []
    for p in paths:
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            if r.get("acc") is not None and r["acc"] == r["acc"] and "error" not in r:
                rows.append(r)
    return rows


def boot(v, n=4000, seed=0):
    v = [x for x in v if x is not None and not np.isnan(x)]
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def main():
    paths = sys.argv[1:] or [os.path.join(HERE, "results", "surface_fix.jsonl")]
    rows = load(paths)
    if not rows:
        print("no data")
        return
    ns = sorted({r["n_train"] for r in rows})
    seeds = sorted({r["seed"] for r in rows})
    print(f"{len(rows)} runs | chance={CHANCE:.3f} | criterion={CRITERION}")
    print(f"n grid = {ns}   seeds = {len(seeds)}")

    cell = {}
    for r in rows:
        cell[(r["surface"], r["n_train"], r["seed"])] = r["acc"]

    print()
    print("=" * 78)
    print("MEAN ACCURACY by surface x n   (fix: ids now surface-specific)")
    print("=" * 78)
    print(f"{'surface':>8}" + "".join(f"{n:>10}" for n in ns))
    for s in NAMES:
        line = f"{s:>8}"
        for n in ns:
            v = [cell[(s, n, sd)] for sd in seeds if (s, n, sd) in cell]
            line += f"{np.mean(v):10.4f}" if v else f"{'-':>10}"
        print(line)

    print()
    print("=" * 78)
    print("EMERGENCE THRESHOLDS  (same estimator as the original S1)")
    print("=" * 78)
    thr = {}
    for s in NAMES:
        vals = []
        for sd in seeds:
            d = {n: cell[(s, n, sd)] for n in ns if (s, n, sd) in cell}
            if len(d) < len(ns):
                continue
            t = A.threshold(ns, [d[n] for n in ns], CRITERION)
            if t is not None and not np.isnan(t):
                vals.append(t)
        thr[s] = vals
        mu = np.mean(vals) if vals else float("nan")
        lo, hi = boot(vals) if vals else (np.nan, np.nan)
        print(f"  {s:>8}  thr={mu:7.0f}  95% CI [{lo:6.0f},{hi:6.0f}]  "
              f"crossed {len(vals)}/{len(seeds)}")

    good = {s: np.mean(v) for s, v in thr.items() if v}
    if len(good) >= 2:
        vals = np.array(list(good.values()))
        logs = np.log(vals)
        gm = float(np.exp(logs.mean()))
        spread = float(vals.max() - vals.min())
        cv = float(logs.std(ddof=1) / logs.mean())
        print()
        print(f"  geometric-mean threshold : {gm:,.0f}")
        print(f"  spread (max-min)         : {spread:,.0f}  "
              f"({100*spread/gm:.0f}% of mean)")
        print(f"  CV of log threshold      : {cv:.4f}")
        print(f"  -> S1 {'CONSISTENT' if cv < 0.15 else 'VIOLATED'} "
              f"under the original criterion (CV < 0.15)")

    print()
    print("=" * 78)
    print("EXACT-IDENTICAL CELLS  (must be ZERO pairs if the fix works)")
    print("=" * 78)
    N = len(ns) * len(seeds)
    hits = 0
    for i in range(len(NAMES)):
        for j in range(i + 1, len(NAMES)):
            a, b = NAMES[i], NAMES[j]
            same = sum(1 for n in ns for sd in seeds
                       if (a, n, sd) in cell and (b, n, sd) in cell
                       and cell[(a, n, sd)] == cell[(b, n, sd)])
            if same == N:
                hits += 1
                print(f"  !! {a} == {b} : {same}/{N} identical  "
                      f"<-- still degenerate")
    if hits == 0:
        print(f"  none — all {len(NAMES)*(len(NAMES)-1)//2} pairs differ")

    print()
    print("=" * 78)
    print("PAIRWISE PAIRED DIFFERENCES  acc(a) - acc(b), pooled over n")
    print("         (significant = surface identity matters)")
    print("=" * 78)
    sig = 0
    for i in range(len(NAMES)):
        for j in range(i + 1, len(NAMES)):
            a, b = NAMES[i], NAMES[j]
            d = []
            for n in ns:
                pa = {sd: cell[(a, n, sd)] for sd in seeds if (a, n, sd) in cell}
                pb = {sd: cell[(b, n, sd)] for sd in seeds if (b, n, sd) in cell}
                for sd in set(pa) & set(pb):
                    d.append(pa[sd] - pb[sd])
            if not d:
                continue
            lo, hi = boot(d)
            is_sig = (lo > 0) or (hi < 0)
            if is_sig:
                sig += 1
            print(f"  {a:>6} - {b:<6} mean={np.mean(d):+.4f} "
                  f"CI=[{lo:+.4f},{hi:+.4f}] {'SIGNIFICANT' if is_sig else 'n.s.'}")
    total_pairs = len(NAMES) * (len(NAMES) - 1) // 2
    print()
    print(f"  {sig}/{total_pairs} surface pairs show a significant difference")
    print()
    print("READING IT")
    print("  * 0 identical pairs + few significant pairs -> S1 holds for real:")
    print("    surface identity reaches the model yet does not move the threshold.")
    print("  * many significant pairs -> symbol identity DOES matter; the")
    print("    original S1 conclusion must be downgraded.")


if __name__ == "__main__":
    main()
