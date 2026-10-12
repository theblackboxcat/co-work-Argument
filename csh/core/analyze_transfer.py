"""
analyze_transfer.py — does substrate-specific acquisition happen?

THE 2x2 MATRIX (all at n_rel = 6, same six relation symbols, token = 46)

                     test: TYPED            test: UNTYPED
    train TYPED      TT  (baseline)          TU
    train UNTYPED    UT                       UU  (baseline)

Plus the NULL arm, which holds the substrate fixed and permutes only the
relation LABELS:

    TTp = train typed, test typed, test labels permuted
    UUp = train untyped, test untyped, test labels permuted

WHY THE NULL ARM IS LOAD-BEARING.  typed and untyped are different data
distributions, so ANY transfer penalty could in principle be generic
distribution shift rather than anything about type structure.  TTp and UUp
isolate exactly that: same substrate, same token count, same everything, only
the relation names are renamed.  If the null arms are free and the transfer
cells are not, the cost is attributable to type STRUCTURE.  If the null arms
show a penalty of the same size, this design is confounded and no structural
claim is licensed.

------------------------------------------------------------------------------
SIGN CONVENTION (this is the thing that was wrong before)
------------------------------------------------------------------------------
A PENALTY IS POSITIVE WHEN TRANSFER COSTS SOMETHING.  Concretely, in accuracy
space:

    penalty(cell) = acc(baseline of that row) - acc(cell)

so penalty > 0 means the transfer cell is WORSE than its own row's baseline.

The earlier version of this script documented that convention but then computed
the penalty in THRESHOLD space, where the sign flips: a larger threshold means
MORE data is needed, so a cost shows up as a POSITIVE threshold difference.  The
verdict code then tested `penalty < 0`, which classified a real cost of
+746 / +1,105 examples as "transfer is free".  Both quantities are reported
below with explicit names, and neither is allowed to reach the verdict without
its sign convention attached.

------------------------------------------------------------------------------
WHY THE PRIMARY STATISTIC IS A POINTWISE PAIRED DIFFERENCE, NOT A THRESHOLD
------------------------------------------------------------------------------
The threshold requires a cell to cross 0.60 accuracy.  At the top of the n grid
the transfer cells only just touch it (TU 0.605, UT 0.488), so most seeds never
cross and are DISCARDED -- the threshold statistic silently throws away most of
the data precisely in the cells under test.  A threshold computed from 1 or 2
surviving seeds is not evidence of anything.

The pointwise paired difference has neither defect.  For every n and every seed:

    d(n, s) = acc(baseline cell, n, s) - acc(transfer cell, n, s)

All cells and all seeds contribute.  Pairing by seed removes the dominant noise
term (identical conditions have spanned 0.33 -> 1.00 across seeds).  The
bootstrap resamples SEEDS, not individual points, because a seed contributes
several correlated n values.

A positive mean difference that is stable across n is the signature of a real
transfer cost.  The threshold penalty is still reported, as a secondary
quantity expressed in training examples, but only for cells where enough seeds
actually crossed.
"""

import json
import os
import sys
from collections import defaultdict

import numpy as np

from analysis import threshold

CRITERION = 0.60
CHANCE = 1.0 / 18
CELLS = ["TT", "TU", "UT", "UU"]
CELL_DESC = {
    "TT": "train typed   -> test typed    (row baseline)",
    "TU": "train typed   -> test untyped  (TRANSFER)",
    "UT": "train untyped -> test typed    (TRANSFER)",
    "UU": "train untyped -> test untyped  (row baseline)",
}
BASELINE = {"TU": "TT", "UT": "UU"}
NULL_BASELINE = {"TTp": "TT", "UUp": "UU"}
# a cell needs this many crossing seeds before its threshold is quotable
MIN_SEEDS = 4


def load(paths):
    rows = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass
    return [r for r in rows if not np.isnan(r.get("acc", np.nan))]


def curve(rows, key):
    acc = defaultdict(list)
    for r in rows:
        acc[(r[key], r["n_train"])].append(r["acc"])
    out = defaultdict(dict)
    for (c, n), v in acc.items():
        out[c][n] = (float(np.mean(v)), float(np.std(v)), len(v))
    return out


def cell_seed_n(rows):
    """(cell, seed) -> {n: acc}"""
    by = defaultdict(dict)
    for r in rows:
        by[(r["cell"], r["seed"])][r["n_train"]] = r["acc"]
    return by


def per_seed_threshold(rows, key="cell"):
    by = cell_seed_n(rows)
    out = defaultdict(dict)
    for (c, sd), d in by.items():
        ns = sorted(d)
        t = threshold(ns, [d[n] for n in ns], CRITERION)
        out[c][sd] = None if (t is None or np.isnan(t)) else t
    return out


def boot(v, n=4000, seed=0):
    v = [x for x in v if x is not None and not np.isnan(x)]
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def paired_by_seed(rows, cell, base):
    """Pointwise paired difference  acc(base) - acc(cell),  POSITIVE = COST.

    Returns (per-n means, per-seed means over all n, n_common, seeds).
    Resampling is over seeds, so the within-seed correlation across n is kept.
    """
    by = cell_seed_n(rows)
    cells = {c: {s: d for (cc, s), d in by.items() if cc == c}
             for c in (base, cell)}
    common_seeds = sorted(set(cells[base]) & set(cells[cell]))
    per_n = {}
    per_seed_means = {}
    for s in common_seeds:
        db, dc = cells[base][s], cells[cell][s]
        ns = sorted(set(db) & set(dc))
        for n in ns:
            per_n.setdefault(n, []).append(db[n] - dc[n])
        if ns:
            per_seed_means[s] = float(np.mean([db[n] - dc[n] for n in ns]))
    per_n_mean = {n: float(np.mean(v)) for n, v in sorted(per_n.items())}
    return (per_n_mean, per_seed_means, len(common_seeds), sorted(per_n_mean))


def threshold_penalty(ps, cell):
    """Threshold-space penalty, in TRAINING EXAMPLES NEEDED.

    thr(cell) - thr(baseline):  POSITIVE = the transfer cell needed MORE data,
    i.e. a cost.  Same sign meaning as the accuracy-space penalty (positive =
    cost), but a different unit, so the two must never be pooled.
    """
    base = BASELINE[cell]
    common = sorted(set(ps[cell]) & set(ps[base]))
    d = [ps[cell][s] - ps[base][s] for s in common
         if ps[cell][s] is not None and ps[base][s] is not None]
    return d, len(common)


def null_penalty(ps, cell):
    """Same, for the label-permutation controls.  Baseline is the SAME substrate."""
    base = NULL_BASELINE[cell]
    common = sorted(set(ps[cell]) & set(ps[base]))
    d = [ps[cell][s] - ps[base][s] for s in common
         if ps[cell][s] is not None and ps[base][s] is not None]
    return d, len(common)


def main():
    paths = sys.argv[1:] or ["results/transfer.jsonl"]
    rows = load(paths)
    if not rows:
        print("no data")
        return
    null_rows = [r for r in load(["results/transfer_null.jsonl"])]

    print(f"{len(rows)} transfer runs" + (f" + {len(null_rows)} null runs" if null_rows else ""))
    print(f"chance = {CHANCE:.3f} | criterion = {CRITERION}")

    meta = rows[0]
    print(f"n_rel={meta['n_rel']}  tokens={meta['tok']}  vocab={meta['vocab']}  "
          f"branching typed {meta['branch_tr']} / untyped {meta['branch_te']}  "
          f"C_eff(3) typed {meta['Ceff3_tr']} / untyped {meta['Ceff3_te']}")

    ns = sorted({r["n_train"] for r in rows})

    # ---------------------------------------------------------------- curves
    c = curve(rows, "cell")
    print("\n" + "=" * 74)
    print("accuracy on the TEST substrate")
    print("=" * 74)
    print(f"{'cell':>6}" + "".join(f"{n:>9d}" for n in ns) + "   seeds")
    for cell in CELLS:
        d = c.get(cell, {})
        if not d:
            continue
        print(f"{cell:>6}" + "".join(f"{d.get(n,(float('nan'),))[0]:9.3f}" for n in ns)
              + f"   {d[ns[0]][2] if ns[0] in d else 0}")

    # ------------------------------------------- PRIMARY: pointwise paired diff
    print("\n" + "=" * 74)
    print("PRIMARY  pointwise paired accuracy difference   acc(baseline) - acc(cell)")
    print("         POSITIVE = transfer COSTS accuracy")
    print("=" * 74)
    print(f"{'cell':>6} {'base':>6}" + "".join(f"{n:>9d}" for n in ns)
          + f"{'mean':>9} {'95% CI':>18} {'seeds':>6}")
    print("-" * 74)
    primary = {}
    for cell in ("TU", "UT"):
        base = BASELINE[cell]
        per_n, per_seed, nseed, used = paired_by_seed(rows, cell, base)
        if not per_n:
            print(f"{cell:>6}   (no paired data)")
            continue
        line = f"{cell:>6} {base:>6}"
        for n in ns:
            line += f"{per_n.get(n, float('nan')):9.3f}"
        vals = list(per_seed.values())
        mu = float(np.mean(vals))
        lo, hi = boot(vals)
        line += f"{mu:9.3f} [{lo:8.3f},{hi:8.3f}] {nseed:6d}"
        print(line)
        primary[cell] = dict(mean=mu, lo=lo, hi=hi, n_seeds=nseed,
                             per_n=per_n, per_seed=per_seed)
    print("\n  Seed-level resampling (a seed contributes all of its n points,")
    print("  so the within-seed correlation is preserved).")

    # ------------------------------------------- SECONDARY: thresholds
    ps = per_seed_threshold(rows)
    print("\n" + "=" * 74)
    print("SECONDARY  emergence thresholds (per-seed, then bootstrap)")
    print("=" * 74)
    thr = {}
    print(f"{'cell':>6} {'thr':>9} {'95% CI':>20} {'seeds':>6}  note")
    for cell in CELLS:
        vals = [v for v in ps[cell].values() if v is not None]
        if not vals:
            print(f"{cell:>6}   (no seed crossed {CRITERION})")
            continue
        mu = float(np.mean(vals))
        lo, hi = boot(vals)
        thr[cell] = mu
        note = "" if len(vals) >= MIN_SEEDS else f"UNDERPOWERED (<{MIN_SEEDS} crossing seeds)"
        print(f"{cell:>6} {mu:9,.0f} [{lo:9,.0f},{hi:9,.0f}] {len(vals):6d}  {note}")

    print("\n  Threshold-space penalty  thr(cell) - thr(baseline),  in examples")
    print("  POSITIVE = the transfer cell needed MORE data = a cost.")
    print("-" * 74)
    for cell in ("TU", "UT"):
        d, n = threshold_penalty(ps, cell)
        if not d:
            print(f"{cell:>6}   (insufficient crossing seeds -- not quotable)")
            continue
        mu = float(np.mean(d))
        lo, hi = boot(d)
        flag = "" if n >= MIN_SEEDS else f"  UNDERPOWERED ({n} seeds)"
        print(f"{cell:>6} {BASELINE[cell]:>9} {mu:+10,.0f} [{lo:+9,.0f},{hi:+9,.0f}] {n:6d}{flag}")

    # ------------------------------------------- NULL arm
    if null_rows:
        print("\n" + "=" * 74)
        print("NULL ARM  same substrate, permuted relation LABELS")
        print("         If these are free, a transfer penalty is about STRUCTURE.")
        print("=" * 74)
        cn = curve(null_rows, "cell")
        print(f"{'cell':>6}" + "".join(f"{n:>9d}" for n in ns) + "   seeds")
        for cell in ("TTp", "UUp"):
            d = cn.get(cell, {})
            if not d:
                continue
            print(f"{cell:>6}" + "".join(f"{d.get(n,(float('nan'),))[0]:9.3f}" for n in ns)
                  + f"   {d[ns[0]][2] if ns[0] in d else 0}")

        allrows = rows + null_rows
        psn = per_seed_threshold(allrows)
        print(f"\n{'cell':>6} {'base':>6} {'mean diff':>10} {'95% CI':>18} "
              f"{'seeds':>6}   {'thr penalty':>14}")
        print("-" * 74)
        nullres = {}
        for cell in ("TTp", "UUp"):
            base = NULL_BASELINE[cell]
            per_n, per_seed, nseed, used = paired_by_seed(allrows, cell, base)
            if not per_n:
                continue
            vals = list(per_seed.values())
            mu = float(np.mean(vals))
            lo, hi = boot(vals)
            d, nc = null_penalty(psn, cell)
            tp = (f"{np.mean(d):+,.0f} [{n} seeds]" if d else "n/a")
            print(f"{cell:>6} {base:>6} {mu:10.3f} [{lo:8.3f},{hi:8.3f}] {nseed:6d}   {tp:>14}")
            nullres[cell] = dict(mean=mu, lo=lo, hi=hi)
    else:
        nullres = {}
        print("\n(null arm not yet available)")

    # ------------------------------------------- DECOUPLING arm
    dec = load(["results/decouple.jsonl"])
    if dec:
        print("\n" + "=" * 74)
        print("DECOUPLING ARM  does the cost track STRUCTURE or MEMORISED SYMBOLS?")
        print("=" * 74)
        print("  Trained on typed in every case.  The two test substrates were")
        print("  chosen to have OPPOSITE profiles from untyped:")
        print("    highovl  overlap 5/6, branching 2.0  -- signature table nearly")
        print("             intact, structure genuinely harder (C_eff 13 vs 24)")
        print("    lowovl   overlap 0/6, branching 3.0  -- signature table fully")
        print("             destroyed, same difficulty as untyped")
        print("  Structure-driven cost -> highovl costs MORE than untyped (little")
        print("                            signature damage, harder structure)")
        print("  Memorisation-driven   -> highovl is FREE (nothing to unlearn)")

        alld = rows + dec
        cd = curve(alld, "cell")
        print(f"\n{'cell':>9}" + "".join(f"{n:>9d}" for n in ns) + "   seeds")
        for cell in ("TT", "Thighovl", "TU", "UU", "Tlowovl"):
            d = cd.get(cell, {})
            if not d:
                continue
            print(f"{cell:>9}" + "".join(f"{d.get(n,(float('nan'),))[0]:9.3f}" for n in ns)
                  + f"   {d[ns[0]][2] if ns[0] in d else 0}")

        print(f"\n{'arm':>10} {'ovl':>4} {'branch':>7} {'C_eff':>6} "
              f"{'mean diff':>10} {'95% CI':>18} {'seeds':>6}")
        print("-" * 74)
        decorr = {}
        # the untyped arm's overlap is a property of the frozen assignment, not
        # of decouple.jsonl, so fall back to the known value
        KNOWN_OVL = {"TU": (2, 3.0, 9), "UU": (2, 3.0, 9), "TT": (6, 2.0, 24)}
        for cell in ("TU", "Thighovl", "Tlowovl"):
            base = "TT"
            per_n, per_seed, nseed, used = paired_by_seed(alld, cell, base)
            if not per_n:
                continue
            vals = list(per_seed.values())
            mu = float(np.mean(vals))
            lo, hi = boot(vals)
            r0 = next((x for x in dec if x["cell"] == cell), None)
            if r0:
                ovl, br, ce = r0["overlap"], r0["branch_te"], r0["Ceff3_te"]
            else:
                ovl, br, ce = KNOWN_OVL.get(cell, ("?", "?", "?"))
            print(f"{cell:>10} {ovl:>4} {br:>7} {ce:>6} "
                  f"{mu:10.3f} [{lo:8.3f},{hi:8.3f}] {nseed:6d}")
            decorr[cell] = dict(mean=mu, lo=lo, hi=hi, overlap=ovl,
                                branch=br, ceff=ce)
    else:
        decorr = {}

    # ------------------------------------------- sanity
    print("\n" + "=" * 74)
    print("SANITY  are the two substrates equally hard?")
    print("=" * 74)
    if "TT" in thr and "UU" in thr:
        print(f"  thr(TT) - thr(UU) = {thr['TT']-thr['UU']:+,.0f} examples")
        print("  They are not equally hard, which is exactly why the penalty is")
        print("  read WITHIN a row.  A cross-row comparison of absolute accuracy")
        print("  would be meaningless.")

    # ------------------------------------------- verdict
    print("\n" + "=" * 74)
    print("VERDICT")
    print("=" * 74)
    if not primary:
        print("  not enough paired data to decide.")
        return

    print("  Primary evidence, accuracy units (positive = cost):")
    for cell, v in primary.items():
        print(f"    {cell}: {v['mean']:+.3f}  95% CI [{v['lo']:+.3f}, {v['hi']:+.3f}]"
              f"   ({v['n_seeds']} seeds)")
    if nullres:
        print("  Null control, same substrate, labels permuted:")
        for cell, v in nullres.items():
            print(f"    {cell}: {v['mean']:+.3f}  95% CI [{v['lo']:+.3f}, {v['hi']:+.3f}]")
    if decorr:
        print("  Decoupling arms (trained on typed; overlap x branching varied):")
        for cell, v in decorr.items():
            print(f"    {cell}: {v['mean']:+.3f}  95% CI [{v['lo']:+.3f}, {v['hi']:+.3f}]"
                  f"   overlap {v['overlap']}/6, branching {v['branch']}, C_eff {v['ceff']}")

    # a cell is "costly" only if the CI excludes zero on the positive side
    costly, free, murky = [], [], []
    for cell, v in primary.items():
        if np.isnan(v["lo"]):
            murky.append(cell)
        elif v["lo"] > 0:
            costly.append(cell)
        elif v["hi"] < 0:
            free.append(cell)
        else:
            murky.append(cell)

    print()
    null_clean = all(v["lo"] <= 0 for v in nullres.values()) if nullres else None

    # the decoupling arm is what actually decides ATTRIBUTION
    attribution = None
    t = decorr.get("TU")
    h = decorr.get("Thighovl")
    if t is not None and h is not None:
        if h["lo"] <= 0 < t["lo"]:
            attribution = "memorisation"
        elif h["lo"] > 0 and t["lo"] > 0:
            attribution = "structure"

    if attribution == "memorisation":
        print("  -> A  NOT SUPPORTED as stated.  The cost tracks MEMORISED SYMBOL")
        print("     MEANING, not type structure.  The decisive comparison:")
        print()
        print(f"       TU      overlap 2/6, branching 3.0   {t['mean']:+.3f}"
              f"  CI [{t['lo']:+.3f}, {t['hi']:+.3f}]")
        print(f"       Thighovl  overlap 5/6, branching 2.0   {h['mean']:+.3f}"
              f"  CI [{h['lo']:+.3f}, {h['hi']:+.3f}]")
        print()
        print("     Transfer to a substrate that destroys 4 of 6 signature")
        print("     assignments costs a large, significant amount.  Transfer to a")
        print("     substrate that destroys ONE signature assignment, while making")
        print("     the structure HARDER (C_eff 13 vs 24), is free.  A cost that")
        print("     tracks how much of the signature table was scrambled rather")
        print("     than how hard the target structure is cannot be the")
        print("     substrate-specific type acquisition that A claims.  What the")
        print("     2x2 design actually measured was symbol-table memorisation.")
        print("     This does not establish B either.")
    elif attribution == "structure":
        print("  -> A  SUPPORTED.  The cost tracks type STRUCTURE rather than symbol")
        print("     memorisation: transferring to a substrate with an almost intact")
        print("     signature table but a harder structure still costs accuracy,")
        print("     and costs at least as much as the entangled untyped comparison.")
    elif len(costly) == 2 and null_clean:
        print("  -> A  SUPPORTED.  Both transfer cells are significantly below their")
        print("     own row's baseline, while the label-permutation controls are not.")
        print("     What the model acquires is tied to the training substrate's type")
        print("     STRUCTURE rather than to the surface encoding: renaming the")
        print("     relations costs nothing, changing the structure does.")
        if murky:
            print(f"  (note: {', '.join(murky)} did not meet the criterion cleanly)")
    elif len(costly) == 2 and null_clean is False:
        print("  -> CONFOUNDED, and this is the honest reading.  Both transfer cells")
        print("     show a cost, but so do the label-permutation controls, so the")
        print("     cost cannot be attributed to type structure.  This design, at")
        print("     this scale, does not separate A from generic distribution shift.")
    elif costly or free:
        print("  -> MIXED / ASYMMETRIC.  The two directions do not agree.")
        print("     Report both numbers with their CIs; do not collapse to one")
        print("     verdict.  An asymmetry would itself be informative -- it would")
        print("     say the structure is learned in one direction more than the other.")
    else:
        print("  -> NOT RESOLVED.  Every paired CI includes zero.  On this evidence")
        print("     transfer is not distinguishable from free, which removes A's")
        print("     specific mechanism but does NOT establish B: B remains one of")
        print("     several surviving explanations.")
    print()
    print("  Standing caveat, in both directions: a free-transfer result is weak")
    print("  evidence (it removes one mechanism, it does not select B); a costly-")
    print("  transfer result is strong (it excludes a whole family).")


if __name__ == "__main__":
    main()
