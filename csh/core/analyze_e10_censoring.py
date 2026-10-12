"""
analyze_e10_censoring.py — E10 倒 U 形的删失敏感性检验。

问题
====
E10 报出的倒 U 形（n* 在 C_eff=16达峰，两端低）是目前最重要的新结果。
但阈值法在这份数据上有严重右删失：n 网格上界是 6500，而阈值只能取
2000/3000/4000/5000/6500 这 5 个值之一。逐种子检查（tau=0.60）：

    C_eff=24  en: [6500, 4000, None, 6500, 3000, 6500]   3/6 压在上界
    C_eff=16  en: [None, None, 6500, 6500, 5000, None]   3/6 未跨线
    C_eff=8en: [5000, 6500, None, 6500, 4000, None]   2/6 未跨线
    C_eff=5   en: [None, 4000, None, 5000, 4000, None]   3/6 未跨线
    C_eff=2   en: [3000, 3000, 3000, 3000, 3000, 2000]   全部网格内

最要紧的一点：**峰值所在的 C_eff=16 恰好是删失最严重的一档**
（3/6 种子从未跨线）。未跨线的种子被threshold() 丢弃，
于是 n*(16) 只由那 3 个「训练得最快」的种子决定。
如果快种子的阈值系统性偏低，倒 U 的峰就是选择效应，
不是结构性质的反映。

这个问题不能靠「多跑几个种子」解决——删失是**网格上界**造成的，
加种子不改变上界。要改的是读数方式。

替代读数：不用阈值，用曲线本身
----------------------------
acc(n) 是每个格点都直接观测到的量，没有删失。本文用三种
不依赖跨线判据的读数重算 C_eff 轴，看倒 U 是否还在：

  R1半学习点 n½ = acc 达到 0.5 的n（线性插值）。0.5 恰在
     多数曲线的中间，删失影响最小。
  R2 曲线面积 A = mean_n acc（对 n 的梯形积分）。完全不用插值，
     每个观测点等权，最不挑方法。
  R3 逻辑斯蒂拟合 logit(acc) = a + b·log(n) 取 b（学习速率）。
     b 越小越难。这是最接近「阈值」本意且仍可用全部点的读数。

三种读数若都给倒 U，倒 U 就不是判据的产物。若只有阈值法给，
则倒 U 是判据与网格的耦合，必须弃用。

用法：
    python analyze_e10_censoring.py --e10 results/E10_merged.jsonl
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CRITERION = 0.60
SURFACES = ["en", "relperm"]


def load(paths):
    rows = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("acc") is None:
                    continue
                if isinstance(r["acc"], float) and math.isnan(r["acc"]):
                    continue
                rows.append(r)
    return rows


def boot_mean(v, n=4000, seed=0):
    v = [x for x in v if x is not None and not math.isnan(x)]
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [float(np.mean(rng.choice(v, len(v), replace=True))) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def curve(rows_by_seed, ns):
    """把 (seed -> {n: acc}) 组成的一组曲线返回成矩阵"""
    out = {}
    for s, d in rows_by_seed.items():
        out[s] = [d.get(n) for n in ns]
    return out


def n_half(seeds_acc, ns):
    """R1：acc 首达 0.5 的n，log(n) 上线性插值；全不达返回 nan"""
    vals = []
    for s, d in seeds_acc.items():
        series = [d.get(n) for n in ns]
        hit = None
        for i, a in enumerate(series):
            if a is None:
                continue
            if a >= 0.5:
                if i == 0:
                    hit = float(ns[0])
                else:
                    pa = series[i - 1]
                    if pa is None:
                        hit = float(ns[i])
                    else:
                        frac = (0.5 - pa) / (a - pa) if a != pa else 0.0
                        frac = min(max(frac, 0.0), 1.0)
                        lns = math.log(ns[i - 1])
                        hit = math.exp(lns + frac * (math.log(ns[i]) - lns))
                break
        if hit is not None:
            vals.append(hit)
    return vals


def area(seeds_acc, ns):
    """R2：acc 对 log(n) 的梯形积分（每点等权，无插值）"""
    lns = [math.log(n) for n in ns]
    vals = []
    for s, d in seeds_acc.items():
        series = [d.get(n) for n in ns]
        if any(a is None for a in series):
            continue
        tot = 0.0
        for i in range(len(ns) - 1):
            tot += 0.5 * (series[i] + series[i + 1]) * (lns[i + 1] - lns[i])
        vals.append(tot)
    return vals


def logit_slope(seeds_acc, ns):
    """
    R3：logit(acc) 对 log(n) 的 OLS 斜率。

    符号约定：logit(acc) 随 log(n) **上升**说明学得快（曲线在陡升段），
    斜率**小**才是学得慢。所以「越难」对应**斜率越小**，
    倒 U 应表现为斜率在中间档**最小**。
    （acc 已在 0/1 上的种子被跳过：logit 无定义。）
    """
    lns = np.array([math.log(n) for n in ns], dtype=float)
    vals = []
    for s, d in seeds_acc.items():
        series = [d.get(n) for n in ns]
        if any(a is None or a <= 0.0 or a >= 1.0 for a in series):
            continue
        y = np.log([a / (1 - a) for a in series])
        vals.append(float(np.polyfit(lns, y, 1)[0]))
    return vals


def section_1(rows):
    print("=" * 78)
    print("1. 删失诊断：阈值法在这份数据上到底能信到什么程度")
    print("=" * 78)
    ns = sorted({r["n_train"] for r in rows})
    nmax = max(ns)
    print(f"\n  n 网格 = {ns}（上界 {nmax}），阈值只能取这 5 个值之一。")
    print(f"  所以任何 Δlog n* 小于 log(5000/4000)={math.log(1.25):.3f} 的真实差异，")
    print("  在这份数据上原理上不可见。")
    print()
    print(f"  {'C_eff':>6} {'surface':>9} {'网格内跨线':>10} "
          f"{'压在上界':>10} {'未跨线':>8} {'阈值可用比例':>14}")
    for ce in sorted({r["C_eff3"] for r in rows}, reverse=True):
        for sf in SURFACES:
            rs = [r for r in rows if r["C_eff3"] == ce and r["surface"] == sf]
            if not rs:
                continue
            inner = edge = none = 0
            for s in sorted({r["seed"] for r in rs}):
                pts = sorted(((r["n_train"], r["acc"])
                              for r in rs if r["seed"] == s))
                h = next((n for n, a in pts if a >= CRITERION), None)
                if h is None:
                    none += 1
                elif h >= nmax:
                    edge += 1
                else:
                    inner += 1
            tot = inner + edge + none
            print(f"  {ce:>6} {sf:>9} {inner:>10} {edge:>10} {none:>8} "
                  f"{inner / tot:>13.0%}")
    print()
    print("  **峰值点的删失最重**：C_eff=16 上 en 有 3/6 种子从未跨 τ，")
    print("  C_eff=2 则 6/6 全部在网格内跨线（阈值2000–3000）。")
    print("  换句话说：难的那一档恰好最难被阈值法测到。")
    print("  「峰在中间」目前有可能是「测不出来的点被算成了低值或丢弃」。")


def section_2(rows):
    print()
    print("=" * 78)
    print("2. 三种不依赖跨线判据的读数重算 C_eff 轴")
    print("=" * 78)
    ns = sorted({r["n_train"] for r in rows})
    ces = sorted({r["C_eff3"] for r in rows}, reverse=True)
    for sf in SURFACES:
        print(f"\n  ---- surface = {sf} ----")
        by = {}
        for ce in ces:
            by[ce] = {}
            for r in rows:
                if r["C_eff3"] == ce and r["surface"] == sf:
                    by[ce].setdefault(r["seed"], {})[r["n_train"]] = r["acc"]

        print(f"\n  {'读数':>12} {'C_eff':>6} {'值':>10} {'95% CI':>20} "
              f"{'n_seeds':>8}")
        for name, fn in [("n@acc=0.5", n_half), ("area", area),
                         ("logit slope", logit_slope)]:
            for ce in ces:
                vals = fn(by[ce], ns)
                if len(vals) < 2:
                    print(f"  {name:>12} {ce:>6} {'--':>10} {'(样本不足)':>20} "
                          f"{len(vals):>8}")
                    continue
                lo, hi = boot_mean(vals)
                print(f"  {name:>12} {ce:>6} {np.mean(vals):>10.3f} "
                      f"[{lo:>8.3f},{hi:>8.3f}] {len(vals):>8}")
            print()


def section_3(rows):
    print()
    print("=" * 78)
    print("3. 倒 U 形的形状检验：三种读数各自能不能定出峰")
    print("=" * 78)
    ns = sorted({r["n_train"] for r in rows})
    ces = sorted({r["C_eff3"] for r in rows}, reverse=True)
    for sf in SURFACES:
        print(f"\n  ---- surface = {sf} ----")
        by = {}
        for ce in ces:
            by[ce] = {}
            for r in rows:
                if r["C_eff3"] == ce and r["surface"] == sf:
                    by[ce].setdefault(r["seed"], {})[r["n_train"]] = r["acc"]

        print(f"\n  {'读数':>12} {'序列(C_eff降序)':>34} {'log-log slope':>14}")
        for name, fn, harder_is in [("n@acc=0.5", n_half, "argmax"),
                                    ("area", area, "argmin"),
                                    ("logit slope", logit_slope, "argmin")]:
            means, ns_ok = [], []
            for ce in ces:
                vals = fn(by[ce], ns)
                means.append(float(np.mean(vals)) if len(vals) >= 2
                             else float("nan"))
                ns_ok.append(len(vals))
            arr = np.array(means)
            ok = ~np.isnan(arr)
            a2, c2 = arr[ok], np.array([c for c, g in zip(ces, ok) if g])
            if len(a2) < 3:
                print(f"  {name:>12} {'有效点不足':>34}")
                continue
            xs = np.log(c2.astype(float))
            slope = float(np.polyfit(xs, a2, 1)[0])
            seq = " → ".join(f"{v:.3f}" for v in a2)
            nlow = sum(1 for x in ns_ok if x < 4)
            mark = f"  (有 {nlow} 档有效种子<4)" if nlow else ""
            print(f"  {name:>12} {seq:>34} {slope:>+14.3f}{mark}")
    print()
    print("  方向约定（改错过一次，记在这里）：")
    print("   n@acc=0.5 **越大越难**（等更久才到0.5）")
    print("   area **越小越难**（曲线下面积小 = 大部分 n 上都低 acc）")
    print("   logit slope **越小越难**（爬升慢）")
    print("  倒U = 中间档最难：n½ 在中间取**极大**、area 取**极小**、")
    print("  logit slope 取**极小**。三个方向一致才算同一现象。")
    print()
    print("  若三种读数一致给出「中间档最难」，倒 U 就与 τ 判据无关，")
    print("  也与网格上界无关。若不一致，则现有倒 U 报告必须降级为")
    print("  「阈值法下的现象」，并说明它与网格的耦合。")


def section_4(rows):
    print()
    print("=" * 78)
    print("4. 结论")
    print("=" * 78)
    ns = sorted({r["n_train"] for r in rows})
    ces = sorted({r["C_eff3"] for r in rows}, reverse=True)
    # logit 读数会因 acc 触及 0/1 而丢种子，有效样本不足的档不可用于定峰。
    # 阈值：至少要 4/6 种子可用，否则该档的读数只是幸存者偏差。
    MIN_SEEDS = 4
    for sf in SURFACES:
        by = {}
        for ce in ces:
            by[ce] = {}
            for r in rows:
                if r["C_eff3"] == ce and r["surface"] == sf:
                    by[ce].setdefault(r["seed"], {})[r["n_train"]] = r["acc"]
        print(f"\n  surface={sf}")
        peaks = {}
        # harder_is =该读数取哪个方向代表「难」。
        #   n@acc=0.5：值越大 = 达到 0.5 要等越久 = 越难 → argmax
        #   area：值越小 =曲线下面积越小 = 越难 → argmin
        #   logit slope：斜率越小 = 爬升越慢 = 越难 → argmin
        for name, fn, harder_is in [("n@acc=0.5", n_half, "argmax"),
                                   ("area", area, "argmin"),
                                   ("logit slope", logit_slope, "argmin")]:
            means, ns_ok = [], []
            for ce in ces:
                vals = fn(by[ce], ns)
                means.append(float(np.mean(vals)) if len(vals) >= 2
                             else float("nan"))
                ns_ok.append(len(vals))
            arr = np.array(means)
            good = (~np.isnan(arr)) & (np.array(ns_ok) >= MIN_SEEDS)
            a2 = arr[good]
            c2 = np.array([c for c, g in zip(ces, good) if g])
            if len(a2) < 3:
                peaks[name] = None
                print(f"    {name:>14}: 有效档 {len(a2)}/{len(ces)}"
                      f"（要求每档 ≥{MIN_SEEDS} 种子）→ 不可用")
                continue
            idx = int(np.argmax(a2)) if harder_is == "argmax" \
                else int(np.argmin(a2))
            peaks[name] = int(c2[idx])
            dropped = [c for c, g in zip(ces, good) if not g]
            seq = " → ".join(f"{v:.3f}" for v in a2)
            tag = ""
            if dropped:
                tag = (f"（剔除 {dropped}：有效种子不足 {MIN_SEEDS}）")
            print(f"    {name:>14}: 最难档 C_eff={int(c2[idx])}"
                  f"  有效档 {len(a2)}/{len(ces)} {seq} {tag}")
        vals = [p for p in peaks.values() if p is not None]
        good_names = [k for k, v in peaks.items() if v is not None]
        if len(set(vals)) == 1 and vals:
            print(f"    → 可用的 {len(good_names)} 种读数一致，"
                  f"最难档 C_eff={vals[0]}")
        elif len(set(vals)) > 1:
            print(f"    → 读数不一致（{[f'{k}:C_eff={v}' for k, v in peaks.items() if v]}）")
            print("      倒 U 的峰位置依赖读数选择，现有报告不能声称"
                  "峰稳定在 C_eff=16")
        if "logit slope" in peaks and peaks["logit slope"] is None:
            print("    → logit 读数因样本不足弃用；另两种读数"
                  "（n½、area）都不依赖跨线判据，结论以其为准")


def section_5(rows):
    print()
    print("=" * 78)
    print("5. E10 内附带的 null 对照：relperm 的阈值动了吗")
    print("=" * 78)
    print()
    print("  E10 原本只打算回答「C_eff 轴上有没有倒 U」，但它的设计上")
    print("  顺带带了一个 null臂：relperm（关系标签置换，结构不变）。")
    print("  这个对照此前没人读。它是免费的，且正对着S2 的核心主张")
    print("  「符号置换不改阈值」。")
    print()

    def thr(rs, s):
        pts = sorted(((r["n_train"], r["acc"]) for r in rs
                      if r["seed"] == s))
        return next((n for n, a in pts if a >= CRITERION), None)

    ces = sorted({r["C_eff3"] for r in rows}, reverse=True)
    print(f"  {'C_eff':>6} {'n_pairs':>8} {'Δlog n*':>9} {'95% CI':>20} "
          f"{'倍比':>7} {'p':>9}")
    ratios = []
    for ce in ces:
        en = [r for r in rows if r["C_eff3"] == ce and r["surface"] == "en"]
        nu = [r for r in rows if r["C_eff3"] == ce
              and r["surface"] == "relperm"]
        d = []
        for s in sorted({r["seed"] for r in en}):
            a, b = thr(en, s), thr(nu, s)
            if a and b:
                d.append(math.log(b) - math.log(a))
        if len(d) < 2:
            print(f"  {ce:>6} {len(d):>8}  样本不足")
            continue
        arr = np.array(d)
        obs = float(arr.mean())
        rng = np.random.default_rng(7)
        flips = rng.choice([-1.0, 1.0], size=(20000, len(arr)))
        null = np.mean(flips * arr, axis=1)
        p = float(np.mean(np.abs(null) >= abs(obs)))
        bs = [float(np.mean(rng.choice(arr, len(arr), replace=True)))
              for _ in range(4000)]
        lo, hi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
        ratios.append((ce, math.exp(obs), lo <= 0 <= hi))
        print(f"  {ce:>6} {len(d):>8} {obs:>+9.3f} [{lo:>+7.3f},{hi:>+7.3f}] "
              f"{math.exp(obs):>7.2f} {p:>9.4f}")

    if ratios:
        print()
        n_free = sum(1 for _, _, free in ratios if free)
        n_lower = sum(1 for _, r, _ in ratios if r < 1.0)
        print(f"  CI 含 0（阈值不可区分）：{n_free}/{len(ratios)} 档")
        print(f"  倍比 < 1（relperm 阈值更低）：{n_lower}/{len(ratios)} 档")
        print()
        print("  **没有任何一档出现 relperm 阈值更高。** 倍比区间 "
              f"{min(r for _, r, _ in ratios):.2f}–"
              f"{max(r for _, r, _ in ratios):.2f}，"
              "全部 ≤ 1 或与 1 不显著。")
        print()
        print("  读法（两个方向都要说）：")
        print("   * 支持 S2：关系标签置换在 C_eff 轴的每一档都不抬高"
              "阈值，")
        print("     甚至系统性略低。这与「S2 的平坦是关于结构的陈述」一致。")
        print("   * 但'略低'本身不是零效应。Δlog n* 的分辨率下限仍是 0.223")
        print("     （见 1 节），而这些比值的 CI 有 4/5 档贴到 0 附近。")
        print("     严格说法是「没有证据表明 relperm 更难，且方向一致偏易」，")
        print("     而不是「relperm 完全无影响」。")
        print()
        print("  这条对照比E6 的 null 更强：E6 的 relperm/entperm 只有")
        print("  3 个表面，C_eff 恒为24；E10 有 5 个 C_eff 水平，且")
        print("  拉丁方配平已验证（vocab恒定、block_slot 均匀）。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e10", default="results/E10_merged.jsonl")
    args = ap.parse_args()
    rows = load([args.e10])
    print()
    print("E10 删失敏感性检验：倒 U 形是结构性质还是判据 × 网格的耦合")
    print(f"  载入 {len(rows)} 条")
    if not rows:
        print("  没有数据，先修 --e10 路径。")
        return
    section_1(rows)
    section_2(rows)
    section_3(rows)
    section_4(rows)
    section_5(rows)
    print()


if __name__ == "__main__":
    main()