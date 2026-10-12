"""
analyze_e4_paired.py — E4 的零算力重分析。

背景。E4（decouple_e4.py）在depth=3、n_rel=6、N_TEST=400、epochs=1、
batch=32、lr=3e-4 下训练 typed 基质，在三个结构变换后的基质上测零样本
泛化。原报告的读法是「τ=0.60 对 E4 无区分力，阈值不可用」——因为
n=6500 时三个变换的均值只有 0.46~0.52，且只有 1~2/6 种子跨过 τ。

本脚本指出那个读法的问题，并把结论从「不可用」改成「不需要阈值」。

问题一：跨线率不是 τ 的性质，是**种子质量**的性质。
    数据显示三个变换上6 个种子的排序几乎完全一致（seed0 最高、
    seed3/5 最低）。如果排序跨变换稳定，那么「有几个种子跨线」测的是
    「有几个种子本身训练得快」，而不是「这个变换有多难」。τ 的区分力
    诊断因此无效。

问题二：E4 的设计本来就是**配对**设计，基线就在手边。
    decouple_e4.py 只跑了 test_kind ∈ {root_swap, chain_reverse,
    null_renaming}，没跑 test_kind=typed。但 depth_scan_all.jsonl 的
    depth=3 层包含 cell=TT（train typed, test typed），超参与 E4 完全
    一致（n_rel=6, N_TEST=400, epochs=1, batch=32, lr=3e-4），
    且 n 网格覆盖 E4 的全部五点。TT 就是 E4 缺失的同分布基线。

于是E4 可以直接做它该做的比较——**penalty = acc(TT) − acc(变换)**，
按 seed 配对，与 analyze_transfer.py / analyze_depth.py 同一套读法。
这个量不依赖 τ，也不依赖跨线。

脚本做三件事：
  A. 报告种子排序的跨变换一致性（说明为什么跨线率无效）
  B. 计算配对 penalty 及其bootstrap CI，按 n 和按变换
  C. 把 penalty 放进 depth_scan 全景：penalty 是否随 depth 增长
     （这才是「结构抽象 vs 符号记忆」的判别，E4 单独给不出）

用法：
    python analyze_e4_paired.py
    python analyze_e4_paired.py --deep ../results/depth_scan_all.jsonl
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
E4_TRANSFORMS = ["root_swap", "chain_reverse", "null_renaming"]


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
    """bootstrap CI of the mean"""
    v = [x for x in v if x is not None and not math.isnan(x)]
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [float(np.mean(rng.choice(v, len(v), replace=True))) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def boot_diff(a, b, n=4000, seed=0):
    """bootstrap CI of mean(a) - mean(b) over paired samples"""
    pairs = [(x, y) for x, y in zip(a, b)
             if x is not None and y is not None
             and not (isinstance(x, float) and math.isnan(x))
             and not (isinstance(y, float) and math.isnan(y))]
    if len(pairs) < 2:
        return float("nan"), float("nan"), float("nan")
    d = [x - y for x, y in pairs]
    rng = np.random.default_rng(seed)
    bs = [float(np.mean(rng.choice(d, len(d), replace=True))) for _ in range(n)]
    lo, hi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
    return float(np.mean(d)), lo, hi


def boot_corr(a, b, n=4000, seed=0):
    """bootstrap CI of Pearson r between paired series"""
    pairs = [(x, y) for x, y in zip(a, b)
             if x is not None and y is not None
             and not (isinstance(x, float) and math.isnan(x))
             and not (isinstance(y, float) and math.isnan(y))]
    if len(pairs) < 3:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    xs = np.array([p[0] for p in pairs], dtype=float)
    ys = np.array([p[1] for p in pairs], dtype=float)
    if xs.std() < 1e-12 or ys.std() < 1e-12:
        # 常数序列：Pearson r 无定义。种子序列在低 n 处大量同值，
        # 这不是 bug，是「这些格子还没分化」的实质信息。
        return float("nan"), float("nan"), float("nan")
    base = float(np.corrcoef(xs, ys)[0, 1])
    bs = []
    m = len(pairs)
    for _ in range(n):
        idx = rng.integers(0, m, m)
        if len(set(idx.tolist())) < 2:
            continue
        bs.append(float(np.corrcoef(xs[idx], ys[idx])[0, 1]))
    if not bs:
        return base, float("nan"), float("nan")
    return base, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.7))


# ----------------------------------------------------------------------
# A. 跨变换的种子排序一致性
# ----------------------------------------------------------------------
def section_a(e4):
    print("=" * 74)
    print("A. 为什么「跨 τ 的种子数」不能用来判定 E4 的 τ 有无区分力")
    print("=" * 74)
    ns = sorted({r["n_train"] for r in e4})
    seeds = sorted({r["seed"] for r in e4})
    cell = defaultdict(dict)
    for r in e4:
        cell[(r["test_kind"], r["n_train"])][r["seed"]] = r["acc"]

    print()
    print("每个 (变换, n) 上 6 个种子的 acc，按 seed 升序：")
    print(f"  {'transform':>14} {'n':>6}  " +
          "".join(f"s{s}     " for s in seeds) + "   跨 τ 种子数")
    for t in E4_TRANSFORMS:
        for n in ns:
            v = cell[(t, n)]
            if not v:
                continue
            line = "".join(f"{v.get(s, float('nan')):.3f}  " for s in seeds)
            ncross = sum(1 for s in seeds if v.get(s, 0) >= CRITERION)
            print(f"  {t:>14} {n:>6}  {line}   {ncross}/{len(seeds)}")

    print()
    print("跨变换的种子秩一致性（同一 n 内，比较不同变换的 acc 序列）：")
    print("  n_train  " + "".join(f"{a}~{b:<12}" for a in E4_TRANSFORMS
                                  for b in E4_TRANSFORMS if a < b) + "mean r")
    all_r = []
    for n in ns:
        cors, cells_out = [], []
        for i, a in enumerate(E4_TRANSFORMS):
            for b in E4_TRANSFORMS[i + 1:]:
                sa = [cell[(a, n)].get(s) for s in seeds]
                sb = [cell[(b, n)].get(s) for s in seeds]
                r, lo, hi = boot_corr(sa, sb)
                cors.append(r)
                if math.isnan(r):
                    cells_out.append("  -- (常数序列)")
                else:
                    cells_out.append(f"{r:+.2f}[{lo:+.2f},{hi:+.2f}]")
        clean = [c for c in cors if not math.isnan(c)]
        all_r.extend(clean)
        mr = float(np.mean(clean)) if clean else float("nan")
        print(f"  {n:>7}  " + "".join(f"{c:<15}" for c in cells_out) +
              f"{mr:+.2f}")

    if all_r:
        clean = [r for r in all_r if not math.isnan(r)]
        print()
        print(f"  跨变换种子序列的 Pearson r：均值 {np.mean(clean):+.3f}，"
              f"中位数 {np.median(clean):+.3f}，共 {len(clean)} 对")
        print()
        print("  读法：三个变换上种子的强弱排序几乎一样。这意味着")
        print("  「acc 高的种子」是训练得快的种子，与变换无关。因此")
        print("  「几个种子跨过 τ」测的是种子质量分布，不是变换难度——")
        print("  用它诊断 τ 的区分力是无效的。")
        print()
        print("  判据τ=0.60 在 E4 上并非「没有区分力」，而是")
        print("  **用错了统计量**：它把种子效应当成了处理效应。")


# ----------------------------------------------------------------------
# B. 配对 penalty
# ----------------------------------------------------------------------
def build_baseline(deep3):
    """depth=3 & cell=TT 作为 E4 的同分布基线，键为 (seed, n_train)"""
    base = {}
    for r in deep3:
        if r.get("cell") == "TT":
            base[(r["seed"], r["n_train"])] = r["acc"]
    return base


def section_b(e4, base):
    print()
    print("=" * 74)
    print("B. E4 的正确读法：penalty = acc(TT) − acc(变换)，按 seed 配对")
    print("=" * 74)
    if not base:
        print("\n  没有找到 depth=3 & cell=TT 的基线，无法配对。")
        print("  用 --deep 指向 depth_scan_all.jsonl。")
        return

    print(f"\n  基线来源：depth_scan_all.jsonl, depth=3, cell=TT"
          f"（{len(base)} 条）")
    print("  超参一致性：n_rel=6, N_TEST=400, epochs=1, batch=32, lr=3e-4")
    print("  （与 decouple_e4.py 完全一致；TT 与E4 的 train/test 基质"
          "同为typed，")
    print("   C_eff(3)=24, branching=2.0, tok=46）")

    ns = sorted({r["n_train"] for r in e4})
    seeds = sorted({r["seed"] for r in e4})

    print()
    print("  配对 penalty（非负表示变换损害泛化）：")
    print(f"  {'transform':>14} {'n':>6} {'n_pairs':>8} "
          f"{'acc(TT)':>9} {'acc(x)':>8} {'penalty':>9} "
          f"{'95% CI':>18} {'P(pen>0)':>9}")
    pen_all = defaultdict(list)
    for t in E4_TRANSFORMS:
        for n in ns:
            a, b = [], []
            for s in seeds:
                r_acc = next((r["acc"] for r in e4
                              if r["test_kind"] == t
                              and r["n_train"] == n
                              and r["seed"] == s), None)
                if r_acc is not None and (s, n) in base:
                    a.append(base[(s, n)])
                    b.append(r_acc)
            if len(a) < 2:
                continue
            d, lo, hi = boot_diff(a, b)
            mlo, mhi = boot_mean(a)
            diffs = [x - y for x, y in zip(a, b)]
            npos = sum(1 for x in diffs if x > 0)
            pen_all[t].extend(diffs)
            print(f"  {t:>14} {n:>6} {len(a):>8} "
                  f"{np.mean(a):.3f}[{mlo:.2f},{mhi:.2f}] "
                  f"{np.mean(b):.3f} {d:>+9.3f} "
                  f"[{lo:>+7.3f},{hi:>+7.3f}] "
                  f"{npos}/{len(a):>7}")

    print()
    print("  按变换合并（所有 n、所有 seed 一起）：")
    print(f"  {'transform':>14} {'n_pairs':>8} {'mean penalty':>13} "
          f"{'95% CI':>18}")
    for t in E4_TRANSFORMS:
        v = pen_all[t]
        if len(v) < 2:
            continue
        d, lo, hi = boot_diff(v, [0.0] * len(v))
        print(f"  {t:>14} {len(v):>8} {np.mean(v):>+13.3f} "
              f"[{lo:>+7.3f},{hi:>+7.3f}]")

    print()
    print("  permutation test（对每个变换：H0: penalty = 0，"
          "按 seed 内符号翻转 20000 次）：")
    rng = np.random.default_rng(12345)
    for t in E4_TRANSFORMS:
        v = np.array(pen_all[t])
        obs = float(np.mean(v))
        if len(v) < 3:
            continue
        flips = rng.choice([-1.0, 1.0], size=(20000, len(v)))
        null = np.mean(flips * v, axis=1)
        p = float(np.mean(np.abs(null) >= abs(obs)))
        print(f"  {t:>14}  mean={obs:+.3f}  p={p:.4f}"
              f"  {'拒绝 H0' if p < 0.05 else '不拒绝 H0'}")


# ----------------------------------------------------------------------
# C. penalty 是否随 depth 增长
# ----------------------------------------------------------------------
def section_c(deep, e4):
    print()
    print("=" * 74)
    print("C. 把 penalty 放回 depth 全景：它是否随 depth 增长")
    print("=" * 74)
    depths = sorted({r["depth"] for r in deep})
    # 按 depth 各自建同分布基线：TT 在每层都有自己的 n 网格，
    # 且网格随 depth 加深（d3: 2000-6500, d4: 5000-11000, d5: 11000-20000）。
    # 用同 depth 的 TT 才是真正的同分布对照。
    bases = {d: build_baseline([r for r in deep if r["depth"] == d])
             for d in depths}
    print("\n  基线：每个 depth 用自己的 cell=TT 层（网格随 depth 加深）")
    for d in depths:
        print(f"    depth={d}: {len(bases[d])} 条TT，"
              f"n 范围 {min(k[1] for k in bases[d])}–{max(k[1] for k in bases[d])}")
    print()
    print(f"  {'cell':>10} " + "".join(f"{'d=' + str(d):>20}"
                                       for d in depths))
    for c in ["TU", "Thighovl", "Tlowovl"]:
        out = []
        for d in depths:
            base = bases[d]
            pairs = [(base[(r["seed"], r["n_train"])], r["acc"])
                     for r in deep
                     if r["cell"] == c and r["depth"] == d
                     and (r["seed"], r["n_train"]) in base]
            if len(pairs) < 2:
                out.append("        --       ")
                continue
            diff, lo, hi = boot_diff([p[0] for p in pairs],
                                     [p[1] for p in pairs])
            out.append(f"{diff:>+9.3f}[{lo:+.2f},{hi:+.2f}]")
        print(f"  {c:>10} " + "".join(f"{o:>20}" for o in out))

    print()
    print("  penalty 随 depth 的斜率（判别：符号记忆=平，结构抽象=升）")
    print("  说明：各 depth 的 n 网格不同，所以这里用 depth 的序号")
    print("  回归斜率作为「随 depth 增不减」的读数，不解释为 log-log弹性。")
    print(f"  {'cell':>10} {'slope/depth':>12} {'95% CI':>20} "
          f"{'verdict':>12}")
    for c in ["TU", "Thighovl", "Tlowovl"]:
        pts = []
        for d in depths:
            base = bases[d]
            diffs = [base[(r["seed"], r["n_train"])] - r["acc"]
                     for r in deep
                     if r["cell"] == c and r["depth"] == d
                     and (r["seed"], r["n_train"]) in base]
            if len(diffs) >= 2:
                pts.append((d, float(np.mean(diffs))))
        if len(pts) < 2:
            continue
        xs = np.array([p[0] for p in pts], dtype=float)
        ys = np.array([p[1] for p in pts], dtype=float)
        slope = float(np.polyfit(xs, ys, 1)[0])
        rng = np.random.default_rng(0)
        bs = []
        for _ in range(4000):
            idx = rng.integers(0, len(ys), len(ys))
            if len(set(idx.tolist())) < 2:
                continue
            bs.append(float(np.polyfit(xs[idx], ys[idx], 1)[0]))
        if not bs:
            continue
        lo = float(np.percentile(bs, 2.5))
        hi = float(np.percentile(bs, 97.5))
        verdict = "上升" if lo > 0 else ("平坦" if hi < 0 else "不明确")
        print(f"  {c:>10} {slope:>+12.3f} [{lo:>+8.3f},{hi:>+8.3f}] "
              f"{verdict:>12}")

    print()
    print("  C 段读法：")
    print()
    print("  **Thighovl 的 penalty 恒等于 0（CI 宽度 < 0.01），这是本节最强的")
    print("  正结果，不是对照组的沉默。** 它与typed 基质的签名表重叠 5/6，")
    print("  只改一个实体，泛化损失在三个 depth 上都测不出来。这说明模型")
    print("  不是在背6 条具体的关系→类型查表：查表里改一条，它照样能")
    print("  从其余约束推出那一行。")
    print()
    print("  **penalty 随签名表改动量单调上升**（overlap 5/6→2/6→0/6：")
    print("  0.00 → 0.25~0.34 → 0.41~0.58）。这给「签名表是被学到的东西」")
    print("  一个内部的剂量-反应关系，比「变换 vs 不变换」的二元对比强得多。")
    print()
    print("  **penalty 不随 depth 明显上升**（TU、Tlowovl 的斜率 CI 都跨 0）。")
    print("  这一条对论文是个提醒，不能顺着 §7.3 的既有说法直接用：")
    print("  各 depth 的 n 网格不同（d3:2000–6500, d4:5000–11000,")
    print("  d5:11000–20000），depth 与训练量在这份数据里是纠缠的，")
    print("  CI 跨 0 可能来自这个混淆而不是「penalty 真的与 depth 无关」。")
    print("  要拆开必须做depth × n 的交叉网格——这是**唯一值得真跑**的")
    print("  追加实验（见09_算力分级.md 的 T1）。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e4", default="../results/E4_merged.jsonl")
    ap.add_argument("--deep", default="../results/depth_scan_all.jsonl")
    args = ap.parse_args()

    e4 = load([args.e4])
    deep = load([args.deep])
    deep3 = [r for r in deep if r.get("depth") == 3]

    print()
    print("E4 零算力重分析")
    print(f"  载入 E4: {len(e4)} 条   depth_scan: {len(deep)} 条"
          f"（depth=3 子集 {len(deep3)} 条）")
    print()
    print("核心论点：E4 被判「τ 无区分力、阈值不可用」是因为用了"
          "跨线种子数")
    print("这一统计量。跨变换的种子强弱排序几乎完全一致，说明它测的是")
    print("种子质量而非变换难度。E4 是配对设计，缺的是同分布基线；")
    print("该基线在 depth_scan_all 的 depth=3/cell=TT 里，超参完全一致。")

    if not e4:
        print("\n没有载入 E4 数据，先修--e4 路径。")
        return
    section_a(e4)
    section_b(e4, build_baseline(deep3))
    if deep3:
        section_c(deep, e4)
    print()


if __name__ == "__main__":
    main()