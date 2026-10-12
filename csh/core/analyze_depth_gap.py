"""analyze_depth_gap.py — 网格稳健的深度统计量。

为什么不用阈值惩罚
------------------
`n*(cell) - n*(TT)` 要求两个基质的阈值都在网格内被良好估计。实测：
  * d3: TU / Tlowovl 在 [2000,6500] 内多数种子不跨过 -> 阈值缺失
  * d5: Tlowovl 的阈值被钉在网格下沿 6000
两端都不可靠。

本脚本的统计量
--------------
**基线刚跨过判据那一刻，受损基质低多少。**

对每个 (cell, depth, seed)：
  1. 求 TT 的阈值 n_TT（log-n 线性插值）
  2. 在同一 depth 的网格上插值 cell 的准确率 acc_cell(n_TT)
  3. gap = tau - acc_cell(n_TT)

这个量：
  * 只在 TT 确实跨过的地方定义 -> 基线有效性有保证
  * 与 n 的绝对尺度无关 -> 跨深度可比
  * 不受 depth-5 饱和影响（它测的是 TT 刚跨过时的那一刻，不是平均）
"""
import json, os, sys, collections
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analysis as A

TAU = 0.60
CELLS = ["TT", "Thighovl", "TU", "Tlowovl"]
DEPTHS = [3, 4, 5]
GRID = {
    3: [2000, 3000, 4000, 5000, 6500],
    4: [2500, 3500, 5000, 6500, 8500, 11000],
    5: [3000, 4500, 6000, 8000, 11000, 14000, 20000],
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


def interp_log(acc, target):
    """linear interpolation in log n; returns None if target outside range."""
    pts = sorted(acc.items())
    for i in range(len(pts) - 1):
        n0, a0 = pts[i]
        n1, a1 = pts[i + 1]
        if a0 <= target <= a1:
            if a1 == a0:
                return n0
            t = (target - a0) / (a1 - a0)
            return float(np.exp(np.log(n0) + t * (np.log(n1) - np.log(n0))))
    return None


def acc_at(acc, nq):
    """cell accuracy at an arbitrary n (log-linear interp); clamp at edges."""
    pts = sorted(acc.items())
    if nq <= pts[0][0]:
        return pts[0][1]
    if nq >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        n0, a0 = pts[i]
        n1, a1 = pts[i + 1]
        if n0 <= nq <= n1:
            t = (np.log(nq) - np.log(n0)) / (np.log(n1) - np.log(n0))
            return a0 + t * (a1 - a0)
    return pts[-1][1]


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
    d = {}
    for r in rows:
        d.setdefault((r["test_kind"], r["depth"], r["seed"]), {})[r["n_train"]] = r["acc"]

    print(f"{len(rows)} runs   tau = {TAU}")
    print("by depth:", dict(sorted(collections.Counter(r["depth"] for r in rows).items())))

    # per-seed TT threshold
    print()
    print("=" * 80)
    print("A.  TT threshold per depth (must be INSIDE the grid, not pinned)")
    print("=" * 80)
    ntt = {}
    for dep in DEPTHS:
        ns = GRID[dep]
        vals = []
        pinned = 0
        for s in range(6):
            acc = d.get(("TT", dep, s))
            if not acc or len(acc) < len(ns):
                continue
            t = interp_log({n: acc[n] for n in ns}, TAU)
            if t is not None:
                vals.append(t)
                if abs(t - ns[0]) < 1e-6:
                    pinned += 1
        ntt[dep] = vals
        lo, hi = boot(vals)
        print(f"  depth {dep}: TT n* = {np.mean(vals):7.0f} [{lo:.0f},{hi:.0f}]  "
              f"seeds={len(vals)}/6  pinned-at-floor={pinned}")

    print()
    print("=" * 80)
    print("B.  GAP at the moment TT crosses tau   (tau - acc_cell(n_TT))")
    print("=" * 80)
    print(f"{'cell':>10} {'ovl':>4}" + "".join(f"{'d=' + str(x):>20}" for x in DEPTHS)
          + "     slope         95% CI   verdict")
    res = {}
    per_gap = {}
    for c in ["Thighovl", "TU", "Tlowovl"]:
        line = f"{c:>10} {OVL[c]:>4}"
        per = {}
        per_gap[c] = {}
        for dep in DEPTHS:
            ns = GRID[dep]
            gaps = []
            for s in range(6):
                accT = d.get(("TT", dep, s))
                accC = d.get((c, dep, s))
                if not accT or not accC:
                    continue
                if len(accT) < len(ns) or len(accC) < len(ns):
                    continue
                t = interp_log({n: accT[n] for n in ns}, TAU)
                if t is None:
                    continue
                a = acc_at({n: accC[n] for n in ns}, t)
                gaps.append(TAU - a)
            per[dep] = gaps
            per_gap[c][dep] = gaps
            if gaps:
                lo, hi = boot(gaps)
                line += f"{np.mean(gaps):>9.3f}[{lo:>5.3f},{hi:>5.3f}]"
            else:
                line += f"{'-':>20}"
        slopes = []
        for s in range(6):
            xs, ys = [], []
            for dep in DEPTHS:
                accT = d.get(("TT", dep, s)); accC = d.get((c, dep, s))
                if not accT or not accC:
                    continue
                ns = GRID[dep]
                if len(accT) < len(ns) or len(accC) < len(ns):
                    continue
                t = interp_log({n: accT[n] for n in ns}, TAU)
                if t is None:
                    continue
                xs.append(dep); ys.append(TAU - acc_at({n: accC[n] for n in ns}, t))
            if len(xs) >= 2:
                slopes.append(float(np.polyfit(xs, ys, 1)[0]))
        if len(slopes) >= 3:
            rng = np.random.default_rng(0)
            bs = [np.mean(rng.choice(slopes, len(slopes), replace=True)) for _ in range(4000)]
            lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
            v = "RISES" if lo > 0 else ("FLAT" if lo <= 0 <= hi else "FALLS")
            res[c] = (np.mean(slopes), lo, hi, v)
            line += f"  {np.mean(slopes):+8.3f} [{lo:+.3f},{hi:+.3f}]  {v} n={len(slopes)}"
        print(line)

    print()
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    rises = [c for c, v in res.items() if v[3] == "RISES"]
    flats = [c for c, v in res.items() if v[3] == "FLAT"]
    falls = [c for c, v in res.items() if v[3] == "FALLS"]
    print(f"  rises: {rises or 'none'}   flat: {flats or 'none'}   falls: {falls or 'none'}")
    print()
    print("  GAP at the crossing point, per substrate:")
    for c in ["Thighovl", "TU", "Tlowovl"]:
        vals = []
        for dep in DEPTHS:
            g = per_gap[c].get(dep) or []
            vals.append(float(np.mean(g)) if g else float("nan"))
        txt = "  ".join(f"d{DEPTHS[i]}={vals[i]:.3f}" for i in range(len(DEPTHS)))
        print(f"    overlap {OVL[c]}/6  {c:>9}: {txt}")
    print()
    # a substrate "carries a real cost" if its mean gap over depths exceeds 0.15
    def mean_gap(c):
        allv = [x for dep in DEPTHS for x in (per_gap[c].get(dep) or [])]
        return float(np.mean(allv)) if allv else float("nan")
    big = [c for c in res if mean_gap(c) > 0.15]
    if big and all(res[c][3] == "FLAT" for c in big):
        print("  The substrates that ACTUALLY carry a cost (mean gap > 0.15) are")
        print("  FLAT in depth.  A depth-independent cost is what a one-off")
        print("  signature-table lookup predicts.  This favours SYMBOL")
        print("  MEMORISATION over structural composition, and REVERSES the")
        print("  earlier ceiling-confounded reading.")
    elif all(res[c][3] == "RISES" for c in res):
        print("  ALL gaps rise with depth -> the model compounds errors along the")
        print("  chain -> structural composition.  §7.3 must be revised.")
    else:
        print("  Mixed pattern; read the per-substrate rows above.")
    print()
    print("  Caveat: flat is compatible with memorisation but does not prove it;")
    print("  neither outcome settles A vs B.")


if __name__ == "__main__":
    main()
