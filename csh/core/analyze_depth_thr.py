"""analyze_depth_thr.py — 阈值空间的深度分析（主判据）。

判据：迁移惩罚（该基质跨过判据所需的训练样本数 - TT 所需样本数）
是否随深度上升。

  符号记忆（查表） -> 惩罚随深度平坦
  结构复合（递归） -> 惩罚随深度上升

为什么用阈值而不是准确率差：depth 5 的 TT 已饱和到 ~0.99，准确率差
被天花板效应压缩（实测在 depth 4 达峰后回落）。阈值（以训练样本计）
不受此限制。

depth-5 网格已补齐为 [6000, 8000, 11000, 14000, 20000]，覆盖基线交叉区。
"""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analysis as A

CRIT = 0.60
CELLS = ["TT", "Thighovl", "TU", "Tlowovl"]
DEPTHS = [3, 4, 5]
GRID = {
    3: [2000, 3000, 4000, 5000, 6500],
    4: [5000, 6500, 8500, 11000],
    5: [6000, 8000, 11000, 14000, 20000],
}
OVL = {"TT": 6, "Thighovl": 5, "TU": 2, "Tlowovl": 0}


def load(paths):
    rows = []
    for p in paths:
        if not os.path.exists(p):
            continue
        for l in open(p, encoding="utf-8"):
            l = l.strip()
            if l:
                r = json.loads(l)
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
    paths = sys.argv[1:] or [os.path.join(HERE, "results", "depth_scan_full.jsonl")]
    rows = load(paths)
    if not rows:
        print("no data"); return
    print(f"{len(rows)} runs   criterion tau = {CRIT}")
    import collections
    print("by depth:", dict(sorted(collections.Counter(r["depth"] for r in rows).items())))

    d = {}
    for r in rows:
        d.setdefault((r["test_kind"], r["depth"], r["seed"]), {})[r["n_train"]] = r["acc"]

    def thr(cell, depth, seed):
        ns = GRID[depth]
        vals = d.get((cell, depth, seed))
        if not vals or len(vals) < len(ns):
            return None
        t = A.threshold(ns, [vals[n] for n in ns], CRIT)
        return None if t is None or np.isnan(t) else t

    print()
    print("=" * 80)
    print("A.  THRESHOLD n* per (cell, depth)   [not ceiling-bounded]")
    print("=" * 80)
    print(f"{'cell':>10} {'ovl':>4}" + "".join(f"{'d=' + str(x):>22}" for x in DEPTHS))
    for c in CELLS:
        line = f"{c:>10} {OVL[c]:>4}"
        for dep in DEPTHS:
            vals = [v for v in (thr(c, dep, s) for s in range(6)) if v is not None]
            if vals:
                lo, hi = boot(vals)
                line += f"{np.mean(vals):>10.0f}[{lo:>5.0f},{hi:>5.0f}]"
            else:
                line += f"{'-':>22}"
        print(line)

    print()
    print("=" * 80)
    print("B.  SANITY:  does TT itself sit above the criterion inside the grid?")
    print("=" * 80)
    for dep in DEPTHS:
        mx = max(GRID[dep])
        vals = [d.get(("TT", dep, s), {}).get(mx) for s in range(6)]
        vals = [v for v in vals if v is not None]
        if vals:
            print(f"  depth {dep}: TT @ n={mx} mean={np.mean(vals):.3f} "
                  f"({sum(1 for v in vals if v >= CRIT)}/6 crossed)")
    print("  (TT must cross inside the grid, else the threshold is pinned)")

    print()
    print("=" * 80)
    print("C.  THRESHOLD PENALTY = n*(cell) - n*(TT), paired by seed")
    print("=" * 80)
    print(f"{'cell':>10} {'ovl':>4}"
          + "".join(f"{'d=' + str(x):>20}" for x in DEPTHS)
          + "     slope         95% CI   verdict")
    results = {}
    for c in ["Thighovl", "TU", "Tlowovl"]:
        line = f"{c:>10} {OVL[c]:>4}"
        for dep in DEPTHS:
            diffs = []
            for s in range(6):
                a = thr(c, dep, s); b = thr("TT", dep, s)
                if a is not None and b is not None:
                    diffs.append(a - b)
            if diffs:
                lo, hi = boot(diffs)
                line += f"{np.mean(diffs):>9.0f}[{lo:>4.0f},{hi:>5.0f}]"
            else:
                line += f"{'-':>20}"
        slopes = []
        for s in range(6):
            xs, ys = [], []
            for dep in DEPTHS:
                a = thr(c, dep, s); b = thr("TT", dep, s)
                if a is not None and b is not None:
                    xs.append(dep); ys.append(a - b)
            if len(xs) >= 2:
                slopes.append(float(np.polyfit(xs, ys, 1)[0]))
        if len(slopes) >= 3:
            rng = np.random.default_rng(0)
            bs = [np.mean(rng.choice(slopes, len(slopes), replace=True))
                  for _ in range(4000)]
            lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
            verdict = "RISES" if lo > 0 else ("FLAT" if lo <= 0 <= hi else "FALLS")
            results[c] = (np.mean(slopes), lo, hi, verdict)
            line += (f"  {np.mean(slopes):+8.0f}  [{lo:+.0f},{hi:+.0f}]"
                     f"   {verdict}  n={len(slopes)}")
        print(line)

    print()
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    rises = [c for c, v in results.items() if v[3] == "RISES"]
    flats = [c for c, v in results.items() if v[3] == "FLAT"]
    damaged = [c for c in rises if OVL[c] < 6]
    if damaged:
        print(f"  Rises with depth: {', '.join(rises)}")
        if flats:
            print(f"  Flat with depth  : {', '.join(flats)}")
        print("  A depth-dependent cost that appears only where the signature")
        print("  table is damaged is evidence of STRUCTURAL COMPOSITION:")
        print("  the model is compounding type errors along the chain, not")
        print("  doing a one-off table lookup.  §7.3's depth-3-only 'symbol")
        print("  memorisation' reading must be REVISED.")
    elif flats:
        print(f"  All penalties FLAT in depth: {', '.join(flats)}")
        print("  A depth-independent cost is what a memorised signature table")
        print("  predicts.  This favours memorisation over structural")
        print("  abstraction at this model scale.")
    else:
        print("  no usable slopes")
    print()
    print("  Caveat: a flat slope is compatible with memorisation but does not")
    print("  prove it.  Neither outcome bears on A vs B, which are claims about")
    print("  human sensory coupling, not about this synthetic substrate.")


if __name__ == "__main__":
    main()
