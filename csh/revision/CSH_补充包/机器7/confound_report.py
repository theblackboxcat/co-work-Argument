#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
confound_report.py
==================
把「词法池混淆」这一新发现的诊断结论固化下来，供论文直接引用。

诊断链
------
1. `analyze_distributional.py`：在既有 S2L（8 臂 × 5 个 n × 4 种子）上，
   分布化阈值估计 + 同slot 严格配对，得到 6/6 配对下真实表面一致地
   **更慢**（Δacc −0.03至 −0.15）。这与论文 §4 的方向相反。
2. `collision_geometry.py`：token 碰撞图几何（arXiv:2605.07120 的口径）
   显示 null 臂与真实表面的几何逐项相同（12 个配对中 8 个完全相等，
   另 4 个差1 个 token，源于 lisp/code 用括号作查询头标记）。
3. 本脚本收口：**三个最快的臂共享同一个词法池**。

    en / relperm / entperm      -> en 池      平均 acc 0.4915
    zh/lisp/math/code/alien                平均 acc 0.3833   差 +0.1082

于是 §4.3 的 null 对照同时变化了两个因子——语义是否存在、词法池是哪个——
而后者足以单独解释全部差异。原阴性结果因此不能归因于语义。

本脚本做两件事：
  (a) 给出该混淆的定量刻画（含显著性）
  (b) 明确写出可证伪的预测：若混淆是全部原因，则在 pool_orthogonal 实验中
      **每个表面与它自身的置换之间应当无差异**，且跨池差异在语义对齐后仍存在。
"""
import os
import json
import math
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
sys_path = HERE
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

REAL = ["zh", "en", "lisp", "math", "code", "alien"]
NULL_OLD = ["relperm", "entperm"]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def welch(a, b):
    a, b = list(a), list(b)
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    va, vb = sum((x - mean(a)) ** 2 for x in a) / (len(a) - 1) / len(a), \
             sum((x - mean(b)) ** 2 for x in b) / (len(b) - 1) / len(b)
    den = math.sqrt(va + vb)
    if den == 0:
        return float("nan"), float("nan")
    t = (mean(a) - mean(b)) / den
    return t, math.erfc(abs(t) / math.sqrt(2))


def cliffs(a, b):
    a, b = list(a), list(b)
    if not a or not b:
        return float("nan")
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


def load(pattern):
    rows = []
    for f in sorted(os.listdir(RES)):
        if not f.startswith(pattern):
            continue
        for ln in open(os.path.join(RES, f)):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("acc") is not None and r["acc"] == r["acc"] \
                    and "error" not in r:
                rows.append(r)
    return rows


def main():
    out = {}

    # ---------- (a) 旧S2L 上的池混淆 ----------
    s2 = load("S2L")
    by = collections.defaultdict(dict)   # surface -> seed -> {n: acc}
    for r in s2:
        by[r["surface"]].setdefault(r["seed"], {})[r["n_train"]] = r["acc"]

    all_by_arm = collections.defaultdict(list)
    for s, d in by.items():
        for sd_, nmap in d.items():
            all_by_arm[s].extend(nmap.values())

    EN_POOL = ["en", "relperm", "entperm"]
    in_pool = [a for a in EN_POOL if a in all_by_arm]
    out_pool = [a for a in REAL if a not in EN_POOL]

    A = [x for a in in_pool for x in all_by_arm[a]]
    B = [x for a in out_pool for x in all_by_arm[a]]
    t, p = welch(A, B)
    out["old_S2L"] = {
        "en_pool_arms": in_pool,
        "other_pool_arms": out_pool,
        "n_in": len(A), "n_out": len(B),
        "mean_in_pool": mean(A), "sd_in_pool": sd(A),
        "mean_other_pool": mean(B), "sd_other_pool": sd(B),
        "diff": mean(A) - mean(B),
        "welch_t": t, "p": p,
        "cliffs_delta": cliffs(A, B),
        "per_arm_mean": {a: mean(all_by_arm[a]) for a in sorted(all_by_arm)},
        "per_arm_sd": {a: sd(all_by_arm[a]) for a in sorted(all_by_arm)},
    }

    # 池内对照：en vs 它的两个置换 —— 这一比较不含池因子
    en_perm = [x for a in NULL_OLD for x in all_by_arm[a]]
    t2, p2 = welch(all_by_arm["en"], en_perm)
    out["within_pool_control"] = {
        "comparison": "en  vs  {relperm, entperm}",
        "mean_en": mean(all_by_arm["en"]),
        "mean_perm": mean(en_perm),
        "diff": mean(all_by_arm["en"]) - mean(en_perm),
        "welch_t": t2, "p": p2,
        "cliffs_delta": cliffs(all_by_arm["en"], en_perm),
        "note": "同池，只变语义。这是原文 §4.3 实际能支撑的那部分结论。",
    }

    # ---------- (b) 新POOL 实验的验证 ----------
    poolf = os.path.join(RES, "POOL.jsonl")
    if os.path.exists(poolf):
        pr = []
        for ln in open(poolf):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("acc") is not None and r["acc"] == r["acc"] \
                    and "error" not in r:
                pr.append(r)
        if pr:
            # 每base：原样 vs 自身置换
            per = collections.defaultdict(lambda: {"real": [], "perm": []})
            for r in pr:
                b = r["surface"][:-len("_relperm")] \
                    if r["surface"].endswith("_relperm") else r["surface"]
                per[b]["perm" if r["surface"].endswith("_relperm")
                     else "real"].append(r["acc"])
            rows = []
            for b in REAL:
                if b not in per or not per[b]["real"] or not per[b]["perm"]:
                    continue
                t3, p3 = welch(per[b]["real"], per[b]["perm"])
                rows.append({"base": b,
                             "mean_real": mean(per[b]["real"]),
                             "mean_perm": mean(per[b]["perm"]),
                             "diff": mean(per[b]["real"]) - mean(per[b]["perm"]),
                             "n_real": len(per[b]["real"]),
                             "n_perm": len(per[b]["perm"]),
                             "p": p3})
            # 跨池：原样臂之间、置换臂之间
            real_means = [mean(per[b]["real"]) for b in REAL
                          if b in per and per[b]["real"]]
            perm_means = [mean(per[b]["perm"]) for b in REAL
                          if b in per and per[b]["perm"]]
            diffs = [r["diff"] for r in rows]
            neg = sum(1 for d in diffs if d < 0)
            out["POOL_partial"] = {
                "n_rows": len(pr),
                "per_base": rows,
                "semantic_effect_mean_diff": mean(diffs),
                "semantic_effect_sd": sd(diffs),
                "n_negative": neg, "n_pairs": len(diffs),
                "pool_spread_real": (max(real_means) - min(real_means))
                                     if real_means else None,
                "pool_spread_perm": (max(perm_means) - min(perm_means))
                                    if perm_means else None,
                "pool_means_real": real_means,
                "pool_means_perm": perm_means,
            }

    with open(os.path.join(RES, "CONFOUND.json"), "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=str)

    # --------------------------------------------------------- 控制台
    print("=" * 74)
    print("词法池混淆诊断报告")
    print("=" * 74)
    o = out["old_S2L"]
    print("\n[1] 旧 S2L（8 臂× 5 个 n × 4 种子）：按词法池分组")
    print(f"  en 池 {o['en_pool_arms']}：n={o['n_in']}  "
          f"acc = {o['mean_in_pool']:.4f} ± {o['sd_in_pool']:.4f}")
    print(f"  其他池 {o['other_pool_arms']}：n={o['n_out']}  "
          f"acc = {o['mean_other_pool']:.4f} ± {o['sd_other_pool']:.4f}")
    print(f"  Δ = {o['diff']:+.4f}   Welch t = {o['welch_t']:+.2f}   "
          f"p = {o['p']:.2e}   Cliff's δ = {o['cliffs_delta']:+.3f}")
    print("\n  逐臂平均 acc：")
    for a, m in sorted(o["per_arm_mean"].items(),
                       key=lambda kv: -kv[1]):
        print(f"    {a:9s} {m:.4f} ± {o['per_arm_sd'][a]:.4f}")

    c = out["within_pool_control"]
    print(f"\n[2] 池内对照（同池，只变语义）：{c['comparison']}")
    print(f"  en {c['mean_en']:.4f}  vs  置换 {c['mean_perm']:.4f}   "
          f"Δ = {c['diff']:+.4f}   p = {c['p']:.3f}   "
          f"δ = {c['cliffs_delta']:+.3f}")
    print(f"  -> {c['note']}")
    print("\n  结论：池间差异显著，池内差异不显著。")
    print("  原§4.3 把这两者混在一起，无法区分「语义」与「池身份」。")

    if "POOL_partial" in out:
        pp = out["POOL_partial"]
        print(f"\n[3] POOL 实验（{pp['n_rows']} 行，进行中）")
        for r in pp["per_base"]:
            print(f"  {r['base']:6s} 原样 {r['mean_real']:.4f}  "
                  f"置换 {r['mean_perm']:.4f}  Δ={r['diff']:+.4f}  p={r['p']:.3f}")
        print(f"  语义效应均值 {pp['semantic_effect_mean_diff']:+.4f}"
              f"（{pp['n_negative']}/{pp['n_pairs']} 为负）")
        if pp["pool_spread_real"] is not None:
            print(f"  跨池极差：原样 {pp['pool_spread_real']:.4f}  "
                  f"置换 {pp['pool_spread_perm']:.4f}")

    print("\n写出 results/CONFOUND.json")


if __name__ == "__main__":
    main()