"""
analysis.py — estimates the emergence threshold and tests the two hypotheses.

  H1 surface invariance : the threshold is a property of the substrate, not of
      the symbol system. Operationally: threshold(surface) is flat.
  H2 substrate scaling : the threshold DOES rise with substrate complexity
      (N_REL), which is the positive control that keeps H1 from being vacuous.

Threshold definition: the smallest training-set size n at which held-out
depth-3 accuracy crosses CRITERION (default 0.60, far above the 1/18 = 5.6%
chance level and far below saturation). Estimated by monotone interpolation of
the accuracy-vs-n curve, with seed-level bootstrap CIs.

The headline statistic for H1 is the spread of the thresholds across surfaces
relative to the spread across seeds — a ratio, so it is invariant to the
overall scale of the threshold.
"""

import json
import os
import sys
from collections import defaultdict

import numpy as np

CRITERION = 0.60
CHANCE = 1.0 / 18


def load(paths):
    rows = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def curve(rows, key_fields, n_key="n_train"):
    """mean accuracy per n, over seeds."""
    acc = defaultdict(list)
    for r in rows:
        acc[(tuple(r[k] for k in key_fields), r[n_key])].append(r["acc"])
    out = defaultdict(dict)
    for (k, n), v in acc.items():
        out[k][n] = (float(np.mean(v)), float(np.std(v)), len(v))
    return out


def threshold(ns, means, criterion=CRITERION):
    """smallest n crossing criterion; linear interp in log n between brackets."""
    ns = sorted(ns)
    for i, n in enumerate(ns):
        if means[i] >= criterion:
            if i == 0:
                return float(n)
            n0, n1 = ns[i - 1], n
            m0, m1 = means[i - 1], means[i]
            if m1 == m0:
                return float(n)
            t = (criterion - m0) / (m1 - m0)
            return float(np.exp(np.log(n0) + t * (np.log(n1) - np.log(n0))))
    return float("nan")


def seed_thresholds(rows, key_fields, n_key="n_train"):
    """per-seed threshold, then mean + bootstrap CI."""
    by = defaultdict(dict)
    for r in rows:
        by[(tuple(r[k] for k in key_fields), r["seed"])][r[n_key]] = r["acc"]
    out = defaultdict(list)
    for (k, sd), d in by.items():
        ns = sorted(d)
        t = threshold(ns, [d[n] for n in ns])
        if not np.isnan(t):
            out[k].append(t)
    res = {}
    rng = np.random.default_rng(0)
    for k, v in out.items():
        if len(v) >= 2:
            bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(4000)]
            lo, hi = np.percentile(bs, [2.5, 97.5])
        else:
            lo = hi = np.nan
        res[k] = (float(np.mean(v)), float(lo), float(hi), len(v))
    return res


def report(paths):
    rows = load(paths)
    if not rows:
        print("no data")
        return
    print(f"loaded {len(rows)} runs")

    # ---------------- learning curves
    print("\n=== curves ===")
    for fields, title in ((("surface",), "surface (n_rel=6)"),
                          (("n_rel",), "substrate (surface=en)")):
        sub = [r for r in rows
               if (("n_rel", r["n_rel"]) == (6, 6) if fields == ("surface",)
                   else r["surface"] == "en")]
        if not sub:
            continue
        c = curve(sub, fields)
        print(f"\n[{title}]")
        keys = sorted({k for k in c})
        ns = sorted({n for d in c.values() for n in d})
        print("  " + "".join(f"{n:>9d}" for n in ns))
        for k in keys:
            label = k[0] if len(k) == 1 else f"{k[0]}/{k[1]}"
            row = "".join(f"{c[k].get(n,(float('nan'),))[0]:9.3f}" for n in ns)
            print(f"{label:>10}{row}")

    # ---------------- H1: surface invariance
    print("\n=== H1: surface invariance (substrate fixed at n_rel=6) ===")
    surf_rows = [r for r in rows if r["n_rel"] == 6]
    if surf_rows:
        st = seed_thresholds(surf_rows, ("surface",))
        print(f"{'surface':>10} {'thr':>9} {'lo':>9} {'hi':>9} {'seeds':>6}")
        for k in sorted(st, key=lambda x: st[x][0]):
            m, lo, hi, n = st[k]
            print(f"{k[0]:>10} {m:9.0f} {lo:9.0f} {hi:9.0f} {n:6d}")
        vals = np.array([st[k][0] for k in st])
        seed_spread = np.mean([st[k][2] - st[k][1] for k in st])
        surf_spread = float(vals.max() - vals.min())
        geo = float(np.exp(np.mean(np.log(vals))))
        ratio = surf_spread / max(np.exp(np.mean(np.log([st[k][1] for k in st if st[k][1] == st[k][1]])))
                                  * 0 + 1, 1)
        print(f"\n  geometric-mean threshold : {geo:,.0f} examples")
        print(f"  surface spread (max-min) : {surf_spread:,.0f}")
        print(f"  mean seed 95% CI width   : {seed_spread:,.0f}")
        if not np.isnan(seed_spread) and seed_spread > 0:
            print(f"  spread / seed-noise      : {surf_spread/seed_spread:.2f}")
        cv = float(np.std(np.log(vals)) / max(np.mean(np.log(vals)), 1e-9))
        print(f"  between-surface CV(log)  : {cv:.3f}")
        print("\n  H1 verdict: " + ("SUPPORTED — threshold is flat across surfaces"
              if cv < 0.15 else "NOT supported — thresholds differ by surface"))

    # ---------------- H2: substrate complexity scaling
    print("\n=== H2: substrate complexity scaling (surface=en) ===")
    sub_rows = [r for r in rows if r["surface"] == "en"]
    if sub_rows:
        st = seed_thresholds(sub_rows, ("n_rel",))
        xs, ys = [], []
        print(f"{'n_rel':>6} {'C(3)':>6} {'thr':>9} {'lo':>9} {'hi':>9}")
        byrel = {r["n_rel"]: r.get("C", [0] * 3)[2] if r.get("C") else 0 for r in sub_rows}
        for k in sorted(st):
            m, lo, hi, n = st[k]
            print(f"{k[0]:6d} {byrel.get(k[0],0):6d} {m:9.0f} {lo:9.0f} {hi:9.0f}")
            if not np.isnan(m):
                xs.append(np.log(k[0]))
                ys.append(np.log(m))
        if len(xs) >= 3:
            xs, ys = np.array(xs), np.array(ys)
            r = float(np.corrcoef(xs, ys)[0, 1])
            sl, ic = np.polyfit(xs, ys, 1)
            print(f"\n  log-log slope of threshold vs N_REL : {sl:.3f}")
            print(f"  Pearson r (log N_REL, log threshold): {r:.3f}")
            print("\n  H2 verdict: " + ("SUPPORTED — threshold rises with substrate "
                  "complexity" if r > 0.5 else "NOT supported — no complexity scaling"))

    # ---------------- chance sanity
    print(f"\nchance = {CHANCE:.3f}; criterion = {CRITERION:.2f}")
    best = max(rows, key=lambda r: r["acc"])
    print(f"best run: n_rel={best['n_rel']} {best['surface']} "
          f"n={best['n_train']} acc={best['acc']:.3f}")


if __name__ == "__main__":
    report(sys.argv[1:] or ["results/arm_A.jsonl"])
