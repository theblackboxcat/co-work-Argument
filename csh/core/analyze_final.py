"""
analyze_final.py — the two hypothesis tests, properly.

ARM S (surface). Substrate fixed. Question: does the emergence threshold depend
on the surface symbol system?

  S1  The six real surfaces (zh, en, lisp, math, code, alien) share a common
      threshold.
  S2  The two semantic-null controls (relperm, entperm) sit INSIDE that same
      interval. This is the load-bearing test. If a shuffled-symbol surface
      learned markedly slower, then "all surfaces share a threshold" would be
      a statement about all surfaces being equally hard, not about structure
      being what matters. S2 is what separates those two readings.

  Reported: geometric-mean threshold, spread, between-surface CV of log
  threshold, and the position of each null control relative to the real-surface
  band. Non-overlap with the real band is stated explicitly rather than buried
  in a p-value.

ARM K (complexity, corrected knob). Type structure FIXED at 3 types with two
outgoing transitions each, so C_eff(3) = 24 for every level. What grows is the
number of concrete relation symbols and the branching factor:

    mult  1  2  3  4
    N_REL 6 12 18 24
    branch 2  4  6  8
    C(3)  24 192 648 1536

  K-A (supports the theory) : threshold flat in mult -> the shared cognitive
        structure sets the threshold, extra symbols are interchangeable labels
  K-B (refutes the theory) : threshold rising in mult -> raw symbolic count
        sets the threshold, structure is irrelevant

The distinction matters because it is exactly the user's claim: structure, not
symbol count.
"""

import json
import os
import sys
from collections import defaultdict

import numpy as np

from analysis import load, curve, threshold, CHANCE

CRITERION = 0.60
REAL = ["zh", "en", "lisp", "math", "code", "alien"]
NULLS = ["relperm", "entperm"]
LABEL = {"zh": "中文", "en": "English", "lisp": "Lisp", "math": "math",
         "code": "code", "alien": "alien", "relperm": "relperm (null)",
         "entperm": "entperm (null)"}


def per_seed_thresh(rows, keys):
    """keys = tuple of field names identifying a cell (excluding n_train)."""
    by = defaultdict(dict)
    for r in rows:
        by[(tuple(r[k] for k in keys), r["seed"])][r["n_train"]] = r["acc"]
    out = defaultdict(list)
    for (k, sd), d in by.items():
        ns = sorted(d)
        t = threshold(ns, [d[n] for n in ns], CRITERION)
        if not np.isnan(t):
            out[k].append(t)
    return out


def boot_ci(vals, n=4000, seed=0):
    if len(vals) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(vals, len(vals), replace=True)) for _ in range(n)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(lo), float(hi)


def table(out, title, keys_order, field, rows, extra=None):
    st = per_seed_thresh(rows, (field,))
    lines = [f"\n{title}", "-" * 62,
             f"{'level':>12} {'thr':>9} {'95% CI':>18} {'seeds':>6}  {'C(3)':>6}"]
    lines.append("-" * 62)
    for lv in keys_order:
        if (lv,) not in st:
            lines.append(f"{LABEL.get(lv,lv):>12}   (never crossed criterion)")
            continue
        v = st[(lv,)]
        m = float(np.mean(v))
        lo, hi = boot_ci(v)
        c3 = extra(lv) if extra else ""
        lines.append(f"{LABEL.get(lv,lv):>12} {m:9.0f} "
                     f"[{lo:7.0f},{hi:7.0f}] {len(v):6d}  {str(c3):>6}")
    print("\n".join(lines))
    return st


def main():
    paths = sys.argv[1:] or ["results/final.jsonl"]
    rows = [r for r in load(paths) if not np.isnan(r.get("acc", np.nan))]
    if not rows:
        print("no data")
        return
    print(f"{len(rows)} runs | chance = {CHANCE:.3f} | criterion = {CRITERION}")

    # ---------------- ARM S
    print("\n" + "=" * 62)
    print("ARM S — surface invariance (substrate fixed: 3 types, N_REL=6)")
    print("=" * 62)
    srows = [r for r in rows if r.get("mult") == 1]
    c = curve(srows, ("surface",))
    ns = sorted({r["n_train"] for r in srows})
    print(f"\n{'surface':>14}" + "".join(f"{n:>9d}" for n in ns))
    for s in REAL + NULLS:
        if (s,) not in c:
            continue
        d = c[(s,)]
        row = "".join(f"{d.get(n,(float('nan'),))[0]:9.3f}" for n in ns)
        tag = LABEL[s] + ("  (null)" if s in NULLS else "")
        print(f"{tag:>14}{row}")

    def c3of(s):
        v = [r.get("C3") for r in srows if r["surface"] == s and r.get("C3")]
        return v[0] if v else ""
    st = table(srows, "emergence thresholds by surface", REAL + NULLS,
               "surface", srows, extra=c3of)

    real_v = [np.mean(st[(s,)]) for s in REAL if (s,) in st]
    null_v = [np.mean(st[(s,)]) for s in NULLS if (s,) in st]
    if len(real_v) >= 2:
        g = float(np.exp(np.mean(np.log(real_v))))
        cv = float(np.std(np.log(real_v)) / np.mean(np.log(real_v)))
        spread = max(real_v) - min(real_v)
        print(f"\n  S1  geometric-mean threshold over real surfaces : {g:,.0f}")
        print(f"      spread (max-min)                            : {spread:,.0f}"
              f"  ({spread/g*100:.0f}% of mean)")
        print(f"      between-surface CV of log threshold        : {cv:.3f}")
        s1 = "CONSISTENT with a common threshold" if cv < 0.15 else \
             "SURFACES DIFFER beyond a common threshold"
        print(f"      -> S1 {s1}")
        if null_v:
            lo_r, hi_r = min(real_v), max(real_v)
            inside = [v for v in null_v if lo_r <= v <= hi_r]
            out = [v for v in null_v if v < lo_r or v > hi_r]
            print(f"\n  S2  real-surface band : [{lo_r:,.0f}, {hi_r:,.0f}]")
            for s in NULLS:
                if (s,) not in st:
                    continue
                v = np.mean(st[(s,)])
                pos = "INSIDE" if lo_r <= v <= hi_r else f"OUTSIDE (by {min(abs(v-lo_r),abs(v-hi_r)):,.0f})"
                print(f"      {LABEL[s]:>16} : {v:,.0f}  {pos}")
            if len(inside) == len(null_v):
                print("      -> S2 the null controls sit inside the real-surface band,")
                print("         so symbol IDENTITY does not move the threshold.")
            elif out:
                print("      -> S2 at least one null control falls OUTSIDE the band.")
                print("         The common threshold is then a statement about all")
                print("         these symbol systems being equally hard, NOT evidence")
                print("         that structure alone sets the threshold.")
            else:
                print("      -> S2 inconclusive.")

    # ---------------- ARM K
    print("\n" + "=" * 62)
    print("ARM K — complexity, CORRECTED knob (type structure fixed)")
    print("=" * 62)
    krows = [r for r in rows if r.get("surface") == "en"]
    mults = sorted({r["mult"] for r in krows if r.get("mult")})
    print(f"\n{'mult':>5} {'N_REL':>6} {'branch':>7} {'C(3)':>7} {'C_eff(3)':>9} "
          + "".join(f"{n:>9d}" for n in ns))
    for m in mults:
        sub = [r for r in krows if r["mult"] == m]
        if not sub:
            continue
        d = curve(sub, ("mult",))
        dd = d.get((m,), {})
        ex = sub[0]
        print(f"{m:5d} {ex['n_rel']:6d} {ex['branching']:7.0f} {ex['C3']:7d} "
              f"{ex['C_eff3']:9d} "
              + "".join(f"{dd.get(n,(float('nan'),))[0]:9.3f}" for n in ns))

    stk = per_seed_thresh(krows, ("mult",))
    if len(stk) >= 3:
        print(f"\n{'mult':>5} {'N_REL':>6} {'C(3)':>7} {'thr':>9} {'95% CI':>18}")
        xs, ys = [], []
        for m in mults:
            if (m,) not in stk:
                print(f"{m:5d} {'':6} {'':7}   never crossed criterion")
                continue
            v = stk[(m,)]
            mu = float(np.mean(v))
            lo, hi = boot_ci(v)
            ex = [r for r in krows if r["mult"] == m][0]
            print(f"{m:5d} {ex['n_rel']:6d} {ex['C3']:7d} {mu:9.0f} "
                  f"[{lo:7.0f},{hi:7.0f}]")
            xs.append(np.log(ex["n_rel"]))
            ys.append(np.log(mu))
        xs, ys = np.array(xs), np.array(ys)
        sl, ic = np.polyfit(xs, ys, 1)
        r = float(np.corrcoef(xs, ys)[0, 1])
        print(f"\n  log-log slope of threshold vs N_REL : {sl:+.3f}")
        print(f"  Pearson r                            : {r:+.3f}")
        print(f"  C_eff(3) across levels                : "
              f"{sorted({x['C_eff3'] for x in krows})}")
        if r > 0.5 and sl > 0.15:
            print("\n  K-B  threshold RISES with symbolic count while the type")
            print("       structure is held fixed. This REFUTES the reading that")
            print("       the shared cognitive structure alone sets the threshold.")
        elif r < 0.5 and sl < 0.15:
            print("\n  K-A  threshold is FLAT in symbolic count while C_eff(3) is")
            print("       constant. This SUPPORTS the theory: the shared relational")
            print("       structure, not the number of surface symbols, is what the")
            print("       threshold tracks.")
        else:
            print("\n  K   mixed / weak trend; not decisive at this sample size.")

    print("\n" + "=" * 62)


if __name__ == "__main__":
    main()
