#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pairing_audit.py
=================
核验论文 §2.1 的配对结构读法。

起因
----
Sharma（arXiv:2512.24145）的结论是**弱占优**：两运行正相关时配对严格
降方差，相关为零时退化为独立。论文此前报告 ρ_across_cells 在
+0.313…+0.746 之间、据此称「配对把方差压到1−ρ²」。但实测
var_paired / var_unpaired = 1.228 > 1，方向相反。

诊断
----
ρ_across_cells 把全部 (seed, n) 格子混在一起算相关，而两臂都随 n
单调上升，这个**共有形状**会把它抬高，与种子层面的耦合无关。
本脚本分开算两种 ρ：

    ρ_across_cells —— 混算（论文此前报告的量）
    ρ_seed         —— 先对每个 seed 取 n 方向均值，再算相关
                      （剥离共享趋势后的真实种子级相关）

结论
----
ρ_seed 平均 −0.123、12 个条件里 10 个落在 ±0.36 以内，即种子级
耦合基本不存在。按弱占优，ρ→0 时配对应退化为独立、比值趋近 1；
实测 1.228 说明本设置下配对还略微不利。
**方法学结论：ρ 必须在去掉共享趋势之后计算。**

用法：python3.11 pairing_audit.py
"""
import glob
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
EXP = "S2L"
REAL_SURFACES = ["zh", "en", "lisp", "math", "code", "alien"]
NULL_ARMS = ["relperm", "entperm"]
NS = [2000, 3000, 4000, 5000, 6500]
SEEDS = [1, 3, 5, 7]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def var(xs):
    xs = list(xs)
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return sum((v - m) ** 2 for v in xs) / (len(xs) - 1)


def pearson(a, b):
    a, b = list(a), list(b)
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else float("nan")


def load():
    """cell[(surface, seed)][n] = acc"""
    cell = {}
    for f in sorted(glob.glob(os.path.join(RES, "*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("_exp") != EXP:
                continue
            if r.get("acc") is None or r["acc"] != r["acc"]:
                continue
            cell.setdefault((r["surface"], r["seed"]), {})[r["n_train"]] = r["acc"]
    return cell


def main():
    cell = load()
    pv, uv = [], []
    rows = []
    for s in REAL_SURFACES:
        for a in NULL_ARMS:
            if (s, 0) not in cell and (s, SEEDS[0]) not in cell:
                continue
            same, diff = [], []
            for sd in SEEDS:
                for sd2 in SEEDS:
                    for n in NS:
                        k1 = (s, sd) in cell and n in cell[(s, sd)]
                        k2 = (a, sd2) in cell and n in cell[(a, sd2)]
                        if k1 and k2:
                            d = cell[(s, sd)][n] - cell[(a, sd2)][n]
                            (same if sd == sd2 else diff).append(d)
            if len(same) > 1:
                pv.append(var(same))
            if len(diff) > 1:
                uv.append(var(diff))
            # 两种 rho
            A = [cell[(s, sd)][n] for sd in SEEDS for n in NS
                 if (s, sd) in cell and n in cell[(s, sd)]]
            B = [cell[(a, sd)][n] for sd in SEEDS for n in NS
                 if (a, sd) in cell and n in cell[(a, sd)]]
            rho_mixed = pearson(A, B)
            off_s = [mean([cell[(s, sd)][n] for n in NS]) for sd in SEEDS]
            off_a = [mean([cell[(a, sd)][n] for n in NS]) for sd in SEEDS]
            rho_seed = pearson(off_s, off_a)
            rows.append({"surface": s, "null": a,
                         "rho_mixed": rho_mixed, "rho_seed": rho_seed})

    out = {
        "exp": EXP,
        "var_paired": mean(pv),
        "var_unpaired": mean(uv),
        "ratio": mean(pv) / mean(uv) if mean(uv) else None,
        "n_cells": len(pv),
        "rho_mixed_range": [min(r["rho_mixed"] for r in rows),
                            max(r["rho_mixed"] for r in rows)],
        "rho_seed_mean": mean([r["rho_seed"] for r in rows]),
        "rho_seed_range": [min(r["rho_seed"] for r in rows),
                           max(r["rho_seed"] for r in rows)],
        "n_abs_rho_seed_lt_0p36": sum(1 for r in rows if abs(r["rho_seed"]) < 0.36),
        "per_pair": rows,
    }
    with open(os.path.join(RES, "PAIRING_AUDIT.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)

    print("=" * 66)
    print("配对结构审计（论文 §2.1）")
    print("=" * 66)
    print(f"  Var(paired)   = {out['var_paired']:.5f}   ({out['n_cells']} 个条件)")
    print(f"  Var(unpaired) = {out['var_unpaired']:.5f}")
    print(f"  比值          = {out['ratio']:.3f}   "
          f"({'配对降方差' if out['ratio'] < 1 else '配对未降方差'})")
    print()
    print(f"  rho_across_cells（混算，含共享 n 趋势）= "
          f"{out['rho_mixed_range'][0]:+.3f} … {out['rho_mixed_range'][1]:+.3f}")
    print(f"  rho_seed（去趋势后）                   = "
          f"{out['rho_seed_range'][0]:+.3f} … {out['rho_seed_range'][1]:+.3f}"
          f"   平均 {out['rho_seed_mean']:+.3f}")
    print(f"  |rho_seed| < 0.36 的条件数 = "
          f"{out['n_abs_rho_seed_lt_0p36']}/{out['n_cells']}")
    print()
    print("  逐条件：")
    for r in rows:
        print(f"    {r['surface']:6s} vs {r['null']:8s} "
              f"rho_mixed={r['rho_mixed']:+.3f}   rho_seed={r['rho_seed']:+.3f}")
    print()
    print("  结论：rho_across_cells 被两臂共有的 n 上升趋势抬高；")
    print("        去趋势后种子级耦合基本不存在，配对无从移除方差。")
    print("        rho 必须在去掉共享趋势之后计算。")


if __name__ == "__main__":
    main()
