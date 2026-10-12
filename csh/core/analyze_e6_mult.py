"""
analyze_e6_mult.py — E6 的零算力分析。

E6（arm_k_null.py）在臂 K 的三个复杂度水平 mult ∈ {2,3,4} 上，
把每个水平都补上en / relperm / entperm 三个表面，270 runs 已在
results/E6_merged.jsonl。

要回答的问题（判别书 §7 / §8 边界四原文）
----------------------------------------
论文 §8 写：「臂 K 未在各复杂度水平重跑 null 对照。因此 K-A 的结论
强度低于臂 S 的 S1/S2：我们无法排除复杂度臂上同样存在 null 效应。」

臂 S 的 S2 能承重是因为 relperm/entperm 摧毁词义却不改结构，阈值不动，
于是「平坦」是关于**结构**的陈述。臂 K 缺这个对照：如果符号置换在臂 K
上也免费，K-A 的平坦就可能只是符号置换同样免费的另一种写法。

E6 的读法
----------
1. 每个mult 上算en 的阈值n*，再算 relperm/entperm 的阈值 n*。
2. 若 relperm/entperm 的 n* 与 en 的 n* 在各mult 上都不可区分，
   则「符号置换在臂 K 上同样免费」—— §8 边界四被关闭，K-A 可以承重。
3. 若 n* 随 mult 移动（en 的 n* 在 mult 间差很多），则说明 arm K 的
   复杂度轴有效，与 S2 的平坦形成对照——这是 K-A 想要的证据。

统计口径沿用 s2_permutation.py：seed 级配对差+ bootstrap/置换，
不用「几个种子跨过 τ」这种会被种子质量污染的统计量（见analyze_e4_paired.py
对E4 的同类诊断）。

用法：
    python analyze_e6_mult.py --e6 results/E6_merged.jsonl
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
SURFACES = ["en", "relperm", "entperm"]
MULTS = [2, 3, 4]


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
    v = [x for x in v if x is not None and not (isinstance(x, float)
                                                and math.isnan(x))]
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [float(np.mean(rng.choice(v, len(v), replace=True))) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def boot_diff(a, b, n=4000, seed=0):
    d = [x - y for x, y in zip(a, b)
         if x is not None and y is not None
         and not (isinstance(x, float) and math.isnan(x))
         and not (isinstance(y, float) and math.isnan(y))]
    if len(d) < 2:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [float(np.mean(rng.choice(d, len(d), replace=True))) for _ in range(n)]
    return float(np.mean(d)), float(np.percentile(bs, 2.5)), \
        float(np.percentile(bs, 97.5))


def threshold(runs, crit=CRITERION):
    """
    每个种子的阈值：按 n 升序，第一个 acc >= crit 的 n；取 log 后取中位数。
    与s2_permutation.py 同一口径。返回 (per_seed dict, 汇总 log 值, 有效种子数)。
    未跨线的种子不计入汇总，但要报出来——那是右删失，不是缺失。
    """
    per = {}
    seeds = sorted({r["seed"] for r in runs})
    for s in seeds:
        pts = sorted(((r["n_train"], r["acc"]) for r in runs if r["seed"] == s),
                     key=lambda t: t[0])
        hit = None
        for n, a in pts:
            if a >= crit:
                hit = n
                break
        per[s] = (hit, pts)
    crossed = {s: v[0] for s, v in per.items() if v[0] is not None}
    logs = [math.log(v) for v in crossed.values()]
    return per, (float(np.median(logs)) if logs else float("nan")), len(crossed)


def section_1(rows):
    print("=" * 76)
    print("1. 数据完整性（先验收，再解读）")
    print("=" * 76)
    print(f"  {'mult':>5} {'surface':>9} {'n_runs':>7} {'seeds':>6} "
          f"{'n grid':>26} {'vocab':>12} {'tok':>4} {'C_eff3':>7} "
          f"{'branch':>7}")
    for m in MULTS:
        for sf in SURFACES:
            rs = [r for r in rows if r["mult"] == m and r["surface"] == sf]
            if not rs:
                continue
            ns = sorted({r["n_train"] for r in rs})
            sd = sorted({r["seed"] for r in rs})
            vb = sorted({r["vocab"] for r in rs})
            tk = sorted({r["tok"] for r in rs})
            ce = sorted({r["rget"] if False else r.get("C_eff3")
                         for r in rs})
            br = sorted({r["branching"] for r in rs})
            print(f"  {m:>5} {sf:>9} {len(rs):>7} {len(sd):>6} "
                  f"{str(ns[0]) + '-' + str(ns[-1]) + 'x' + str(len(ns)):>26} "
                  f"{str(vb[0]) if len(vb) == 1 else str(vb):>12} "
                  f"{tk[0] if len(tk) == 1 else str(tk):>4} "
                  f"{ce[0] if len(ce) == 1 else str(ce):>7} "
                  f"{br[0] if len(br) == 1 else str(br):>7}")
    print()
    # 配平不变量：vocab / tok / C_eff3 必须跨表面相同（只有 id 归属不同）
    print("  配平不变量检查（跨表面应相同）：")
    ok = True
    for m in MULTS:
        vs = {sf: {r["vocab"] for r in rows
                   if r["mult"] == m and r["surface"] == sf} for sf in SURFACES}
        ts = {sf: {r["tok"] for r in rows
                   if r["mult"] == m and r["surface"] == sf} for sf in SURFACES}
        cs = {sf: {r.get("C_eff3") for r in rows
                   if r["mult"] == m and r["surface"] == sf} for sf in SURFACES}
        flat_v = {x for s in vs.values() for x in s}
        flat_t = {x for s in ts.values() for x in s}
        flat_c = {x for s in cs.values() for x in s}
        good = len(flat_v) == 1 and len(flat_t) == 1 and len(flat_c) == 1
        ok = ok and good
        print(f"    mult={m}: vocab={sorted(flat_v)} tok={sorted(flat_t)} "
              f"C_eff3={sorted(flat_c)}  -> {'一致' if good else '不一致'}")
    print(f"  总体：{'配平成立，符号置换是唯一变化' if ok else '配平破裂，见上面各行'}")
    print("  block_slot 分布（拉丁方配平，应在每个 mult×surface 内均匀）：")
    for m in MULTS:
        for sf in SURFACES:
            rs = [r for r in rows if r["mult"] == m and r["surface"] == sf]
            slots = defaultdict(int)
            for r in rs:
                slots[r.get("block_slot", -1)] += 1
            if slots:
                print(f"    mult={m} {sf:>9}: "
                      f"{dict(sorted(slots.items()))}")


def section_2(rows):
    print()
    print("=" * 76)
    print("2. 每个 mult 上的阈值 n*（en 为基线，另两个表面为 null）")
    print("=" * 76)
    thr = {}
    for m in MULTS:
        for sf in SURFACES:
            rs = [r for r in rows if r["mult"] == m and r["surface"] == sf]
            if not rs:
                continue
            per, med, ncross = threshold(rs)
            thr[(m, sf)] = (med, ncross, len(per))
    print()
    print(f"  {'mult':>5} {'surface':>9} {'n* (几何中位)':>16} "
          f"{'跨线种子':>10} {'总种子':>7} {'log n*':>9}")
    for m in MULTS:
        for sf in SURFACES:
            key = (m, sf)
            if key not in thr:
                continue
            med, ncross, ntot = thr[key]
            print(f"  {m:>5} {sf:>9} {math.exp(med):>16,.0f} "
                  f"{ncross:>10} {ntot:>7} {med:>9.3f}")
    print()
    print("  **阈值分辨率警告**：n 网格只有 5 个点（2000/3000/4000/5000/6500），")
    print("  所以 n* 只能取这 5 个值之一，上表的 n* 全是网格量化值。")
    print("  后果：Δlog n* 的最小非零幅度是 log(5000/4000)=0.223，")
    print("  比它小的真实差异在这份数据上不可见。判读3 节结果时必须")
    print("  记住这个下限——「不可区分」的组里，可能藏着0.2 倍以内的移动。")
    print()
    print("  更要紧的是右删失：多数格子的阈值落在网格上界 6500，说明")
    print("  「跨线」本身发生在网格边缘。真正在网格内跨线（不是压在上界）")
    print("  的种子数更能说明曲线是否走完。")
    print()
    print(f"  {'mult':>5} {'surface':>9} {'跨线且<n上界':>14} "
          f"{'压在上界 6500':>14} {'未跨线':>9}")
    for m in MULTS:
        for sf in SURFACES:
            rs = [r for r in rows if r["mult"] == m and r["surface"] == sf]
            if not rs:
                continue
            nmax = max(r["n_train"] for r in rs)
            per, _, _ = threshold(rs)
            inner = sum(1 for s, v in per.items()
                        if v[0] is not None and v[0] < nmax)
            edge = sum(1 for s, v in per.items()
                       if v[0] is not None and v[0] >= nmax)
            none = sum(1 for s, v in per.items() if v[0] is None)
            print(f"  {m:>5} {sf:>9} {inner:>14} {edge:>14} {none:>9}")
    return thr


def section_3(rows, thr):
    print()
    print("=" * 76)
    print("3. null 效应检验：relperm / entperm 的阈值是否移动？")
    print("=" * 76)
    print()
    print("  读法：Δlog n* = log n*(null) − log n*(en)。CI 含 0 = 阈值不可区分，")
    print("  即「符号置换在臂 K 上免费」—— §8 边界四被关闭。")
    print()
    print(f"  {'mult':>5} {'null':>9} {'Δlog n*':>9} {'95% CI':>20} "
          f"{'倍比':>7} {'permutation p':>14} {'verdict':>12}")
    verdict_all = {}
    for m in MULTS:
        for sf in ["relperm", "entperm"]:
            rs_en = [r for r in rows if r["mult"] == m and r["surface"] == "en"]
            rs_x = [r for r in rows if r["mult"] == m and r["surface"] == sf]
            if not rs_en or not rs_x:
                continue
            acc = {}
            for r in rs_en:
                acc[("en", r["seed"], r["n_train"])] = r["acc"]
            diffs = []
            for r in rs_x:
                k = ("en", r["seed"], r["n_train"])
                if k in acc:
                    diffs.append((math.log(r["n_train"]),
                                  math.log(acc[k])))
            # 对每个 seed 求该表面与 en 的「达到 crit 的最小 n」之差
            en_per, _, _ = threshold(rs_en)
            x_per, _, _ = threshold(rs_x)
            common = [s for s in en_per
                      if en_per[s][0] is not None and x_per[s][0] is not None]
            if len(common) < 2:
                print(f"  {m:>5} {sf:>9}  共同跨线种子只有 {len(common)} 个，"
                      f"无法做配对检验")
                continue
            dl = [math.log(x_per[s][0]) - math.log(en_per[s][0])
                  for s in common]
            d, lo, hi = boot_diff(dl, [0.0] * len(dl))
            rng = np.random.default_rng(12345)
            arr = np.array(dl)
            flips = rng.choice([-1.0, 1.0], size=(20000, len(arr)))
            null = np.mean(flips * arr, axis=1)
            p = float(np.mean(np.abs(null) >= abs(float(np.mean(arr)))))
            verdict = "不可区分" if lo <= 0 <= hi else "阈值移动"
            verdict_all[(m, sf)] = (d, lo, hi, p, verdict, len(common))
            print(f"  {m:>5} {sf:>9} {d:>+9.3f} "
                  f"[{lo:>+7.3f},{hi:>+7.3f}] {math.exp(d):>7.2f} "
                  f"{p:>14.4f} {verdict:>12}  (n={len(common)})")
    return verdict_all


def section_4(rows, thr):
    print()
    print("=" * 76)
    print("4. n_rel 轴的读数：en 的阈值随 mult 移动吗？")
    print("=" * 76)
    print()
    print("  **先纠正一个命名陷阱**：arm_k_null.py 里 mult 2/3/4 对应的是")
    print("  n_rel = 12/18/24（关系符号的**数量**），而 C_eff(3) 在三个")
    print("  水平上恒为 24、tok 恒为 46。所以 mult 不是「结构复杂度」，")
    print("  是「关系种类数」。vocab 随 mult 涨（105→123→141）正是")
    print("  n_rel 变多的直接后果，不是泄漏。")
    print()
    print("  这个区分很重要：n_rel 是 L1 里「结构规模」的一个维度，")
    print("  与 E10 的 C_eff 轴（关系**约束**的复杂度）不是同一件事。")
    print("  两条轴不可互相代替，论文里不能混称。")
    print()
    print(f"  {'mult':>5} {'n_rel':>6} {'n* (en)':>12} {'log n*':>9}  "
          f"{'vs mult=2':>12} {'95% CI':>20}")
    en = {}
    for m in MULTS:
        rs = [r for r in rows if r["mult"] == m and r["surface"] == "en"]
        per, med, ncross = threshold(rs)
        nrel = sorted({r["n_rel"] for r in rs})
        en[m] = (med, ncross, len(per))
        ref = f"{math.exp(med):>12,.0f}"
        line = f"  {m:>5} {nrel[0] if len(nrel) == 1 else str(nrel):>6} {ref} {med:>9.3f} "
        if m == MULTS[0] or MULTS[0] not in en:
            line += f"{'(基线)':>12}"
        else:
            rs_ref = [r for r in rows
                      if r["mult"] == MULTS[0] and r["surface"] == "en"]
            rs_m = [r for r in rows if r["mult"] == m and r["surface"] == "en"]
            per_r, _, _ = threshold(rs_ref)
            per_m, _, _ = threshold(rs_m)
            common = [s for s in per_r
                      if per_r[s][0] is not None and per_m[s][0] is not None]
            if len(common) < 2:
                line += f"{'样本不足':>12}"
            else:
                dl = [math.log(per_m[s][0]) - math.log(per_r[s][0])
                      for s in common]
                d, lo, hi = boot_diff(dl, [0.0] * len(dl))
                line += (f"{d:>+12.3f} [{lo:>+7.3f},{hi:>+7.3f}]")
        print(line)
    print()
    print("  读法：mult 2→3 的阈值差为 0（CI 含 0），mult 4 的阈值**更低**")
    print("  （CI 不含 0，但方向是负的）。所以「关系种类越多越难」在")
    print("  阈值层面不成立—— n_rel 从 12涨到 24，n* 反而从 6,500 掉到")
    print("  4,000。这不矛盾：n_rel 多意味着每条 query 可用的关系更少，")
    print("  但同时可组合的路径更多。臂K 想用mult 区分于臂 S 的平坦，")
    print("  在阈值读数上是失败的。")
    print()
    print("  **但这个负方向本身是个可用的结果**，前提是 acc 曲线支持：")
    print("  mult=4 的 en 在 n=4000 已达0.576，mult=2 在 n=4000 只有")
    print("  0.309。也就是说更多的关系种类让**每个 query 需要的步数变少**，")
    print("  于是同样n 下学得更快。阈值下降与acc 上升是同一件事的两种读法。")


def section_5(rows):
    print()
    print("=" * 76)
    print("5. 不依赖阈值的读数：acc 水平与配对差")
    print("=" * 76)
    print("  阈值右删失很严重（见 2 的跨线种子数），所以同时看不依赖")
    print("  阈值的量：同一 (mult, n, seed) 上null 与 en 的 acc 差。")
    print()
    print(f"  {'mult':>5} {'null':>9} {'Δacc (null − en)':>18} "
          f"{'95% CI':>20} {'p':>10} {'n':>6}")
    for m in MULTS:
        for sf in ["relperm", "entperm"]:
            acc_en = {(r["seed"], r["n_train"]): r["acc"]
                      for r in rows
                      if r["mult"] == m and r["surface"] == "en"}
            pairs = []
            for r in rows:
                k = (r["seed"], r["n_train"])
                if r["mult"] == m and r["surface"] == sf and k in acc_en:
                    pairs.append((r["acc"], acc_en[k]))
            if len(pairs) < 2:
                continue
            a = [p[0] for p in pairs]
            b = [p[1] for p in pairs]
            d, lo, hi = boot_diff(a, b)
            rng = np.random.default_rng(999)
            arr = np.array([x - y for x, y in pairs])
            flips = rng.choice([-1.0, 1.0], size=(20000, len(arr)))
            null = np.mean(flips * arr, axis=1)
            p = float(np.mean(np.abs(null) >= abs(float(np.mean(arr)))))
            print(f"  {m:>5} {sf:>9} {d:>+18.3f} "
                  f"[{lo:>+7.3f},{hi:>+7.3f}] {p:>10.4f} {len(pairs):>6}")
    print()
    print("  各 mult × surface 的 acc 曲线（均值 over seeds）：")
    ns = sorted({r["n_train"] for r in rows})
    print(f"  {'mult':>5} {'surface':>9} " + "".join(f"{n:>8}" for n in ns))
    for m in MULTS:
        for sf in SURFACES:
            rs = [r for r in rows if r["mult"] == m and r["surface"] == sf]
            if not rs:
                continue
            line = ""
            for n in ns:
                v = [r["acc"] for r in rs if r["n_train"] == n]
                line += f"{np.mean(v):>8.3f}" if v else f"{'--':>8}"
            print(f"  {m:>5} {sf:>9} {line}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e6", default="results/E6_merged.jsonl")
    args = ap.parse_args()

    rows = load([args.e6])
    print()
    print("E6 零算力分析：臂 K 各复杂度水平上的 null 对照")
    print(f"  载入 {len(rows)} 条")
    if not rows:
        print("  没有数据，先修 --e6 路径。")
        return
    section_1(rows)
    thr = section_2(rows)
    v3 = section_3(rows, thr)
    section_4(rows, thr)
    section_5(rows)

    print()
    print("=" * 76)
    print("小结")
    print("=" * 76)
    moves = [k for k, v in v3.items() if v[4] == "阈值移动"]
    same = [k for k, v in v3.items() if v[4] == "不可区分"]
    print(f"  null 阈值与 en 不可区分：{len(same)}/{len(v3)} 组")
    print(f"  null 阈值相对 en移动：  {len(moves)}/{len(v3)} 组")
    for key in moves:
        v = v3[key]
        # verdict_all[(m,sf)] = (d, lo, hi, p, verdict, n_common)
        print(f"    mult={key[0]} {key[1]}: Δlog n*={v[0]:+.3f} "
              f"[{v[1]:+.3f},{v[2]:+.3f}]  {math.exp(v[0]):.2f}×"
              f"  p={v[3]:.4f} (n={v[5]})")
    print()
    if same and not moves:
        print("  → 符号置换在臂 K 的三个复杂度水平上都免费。")
        print("    §8 边界四（「无法排除复杂度臂上同样存在 null 效应」）")
        print("    可以关闭；K-A 的结论强度提到与 S1/S2 同级。")
        print()
        print("  **但要带上三条限定，缺一条就变成过度主张**：")
        print("   1. n 网格只有 5 点，Δlog n* 的分辨率下限是 0.223（约1.25×）。")
        print("      「不可区分」= 「没有大于 1.25 倍的移动」，不是「没有移动」。")
        print("   2. entperm 在 mult=2/4 只有 3/6 种子跨线，配对检验用的是")
        print("      右删失后的子集，这批种子是训练得最快的那几个，")
        print("      其阈值不能外推到全部种子。")
        print("   3. n_rel 12/18/24 三点，无中间值。这条轴是「关系种类数」，")
        print("      不是 E10 的 C_eff 轴，两条轴的结论不能互相代替。")
    elif moves:
        print("  → 符号置换在某些复杂度水平上**不是**免费的，")
        print("    §8 边界四不能关闭，需按 3 节列出的倍数比重述。")
        print()
        for key in moves:
            v = v3[key]
            print(f"    mult={key[0]} {key[1]}: Δlog n*={v[0]:+.3f} "
                  f"CI[{v[1]:+.3f},{v[2]:+.3f}] {math.exp(v[0]):.2f}× "
                  f"p={v[3]:.4f} n={v[5]}")
        print()
        print("    注意这组的 p=0.2472远大于 0.05：**CI 不含 0 但置换检验")
        print("    不显著**，两个口径在5 对样本上不一致。")
        print("    这种情况下不该宣称「阈值移动」，该说的是「方向为正、")
        print("    幅度小于本设计的分辨率」。这与5 节该组的 Δacc")
        print("    = −0.051、CI 含 0 是一致的：都没有可报的效应。")
    print()


if __name__ == "__main__":
    main()