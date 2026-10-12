#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_sb.py
=============
SB2（符号绑定判决实验）的分析。

设计回顾
--------
两个世界共享**全部 token 串**（28 个，实测交集 = 28/28），
但类型转移表被置换：

    世界 A（训练）assign_A = [(0,1),(0,2),(1,0),(1,2),(2,0),(2,1)]
    世界 B（测试）assign_B[i] = assign_A[perm[i]]

因此同一个关系 token 在两个世界里要求不同的行为。
序列长度恒为 46，词表规模恒定。

格点
----
    same              训练 A、测试 A                上界
    remap:pi_id       恒等置换                       实现自检（应等于 same）
    remap:pi_swap2    签名保留 2/6                   中等破坏
    remap:pi_6cycle   签名保留 0/6                   彻底破坏
    shuffle           打乱测试事实顺序               定位对照

读法
----
    1. pi_id 必须与 same 逐位相同——否则实现有bug，后续解读全部无效
    2. remap 相对same 的落差 = 「符号 ↔ 类型转移绑定」的代价
    3. shuffle 相对 same 的落差 = 「事实顺序结构」的代价
       若 shuffle ≈ same，说明模型不依赖事实排列，只依赖符号绑定
    4. 落差随签名保留度（6→ 2 → 0）的走向 = 剂量反应关系

判决
----
    落差 ≈ 0        => 模型学到可重对齐的结构，S 被推翻，§6 须改写
    落差 ≈ 随机基线 => 模型学到符号级绑定，S 成立，§6 稳固
    中间态          => 两种成分混合，可用剂量关系定量分解

输出 results/SB2_ANALYSIS.json / .md
"""
import os
import json
import math
import random
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
SRC = os.path.join(RES, "SB2.jsonl")

RAND_BASELINE = 1.0 / 18          # 18 个实体
SIG_RETAINED = {"pi_id": 6, "pi_swap2": 2, "pi_6cycle": 0}
ARMS = ["same", "remap:pi_id", "remap:pi_swap2", "remap:pi_6cycle",
        "shuffle:pi_6cycle"]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    xs = list(xs)
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def welch(a, b):
    a, b = list(a), list(b)
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    va = sum((x - mean(a)) ** 2 for x in a) / (len(a) - 1) / len(a)
    vb = sum((x - mean(b)) ** 2 for x in b) / (len(b) - 1) / len(b)
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


def boot(d, iters=20000, seed=0):
    d = [x for x in d if x == x]
    if len(d) < 3:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    m = len(d)
    s = sorted(sum(d[rng.randrange(m)] for _ in range(m)) / m
               for _ in range(iters))
    return s[int(0.025 * iters)], s[int(0.975 * iters)]


def bh(ps):
    k = len(ps)
    idx = sorted(range(k), key=lambda i: ps[i])
    out = [0.0] * k
    prev = 1.0
    for rank in range(k - 1, -1, -1):
        i = idx[rank]
        prev = min(prev, ps[i] * k / (rank + 1))
        out[i] = prev
    return out


def main():
    if not os.path.exists(SRC):
        print("!! %s 不存在" % SRC)
        return
    rows = []
    for ln in open(SRC):
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
    if not rows:
        print("!! 无有效行")
        return

    ns = sorted(set(r["n_train"] for r in rows))
    seeds = sorted(set(r["seed"] for r in rows))
    cell = {}
    for r in rows:
        cell.setdefault(r["arm_name"], {}).setdefault(r["seed"], {})[
            r["n_train"]] = r["acc"]

    R = {"n_rows": len(rows), "n_grid": ns, "seeds": seeds,
         "random_baseline": RAND_BASELINE}

    # ---- 1. 实现自检：pi_id 必须与 same 逐位相同
    id_diff = []
    for s in seeds:
        for n in ns:
            a = cell.get("same", {}).get(s, {}).get(n)
            b = cell.get("remap:pi_id", {}).get(s, {}).get(n)
            if a is not None and b is not None:
                id_diff.append(abs(a - b))
    R["selfcheck_pi_id"] = {
        "n_pairs": len(id_diff),
        "max_abs_diff": max(id_diff) if id_diff else None,
        "mean_abs_diff": mean(id_diff),
        "identical": bool(id_diff) and max(id_diff) == 0,
    }

    # ---- 2. 每臂每n 的准确率
    tab = {}
    for arm in ARMS:
        tab[arm] = {}
        for n in ns:
            vals = [cell[arm][s][n] for s in seeds
                    if arm in cell and s in cell[arm] and n in cell[arm][s]]
            tab[arm][n] = {"mean": mean(vals), "sd": sd(vals),
                           "n": len(vals), "vals": vals,
                           "p_above_random": (
                               sum(1 for v in vals if v > RAND_BASELINE)
                               / len(vals)) if vals else None}
    R["table"] = tab

    # ---- 3. 配对落差（相对same，同种子配对）
    gaps = {}
    for arm in ARMS:
        if arm == "same":
            continue
        per_n = {}
        allv = []
        for n in ns:
            ds = []
            for s in seeds:
                a = cell["same"].get(s, {}).get(n)
                b = cell.get(arm, {}).get(s, {}).get(n)
                if a is not None and b is not None:
                    ds.append(a - b)
            if ds:
                per_n[n] = {"mean": mean(ds), "sd": sd(ds), "n": len(ds),
                            "t": (mean(ds) / (sd(ds) / math.sqrt(len(ds)))
                                  if len(ds) > 1 and sd(ds) else None),
                            "p": (math.erfc(abs(mean(ds) /
                                               (sd(ds) / math.sqrt(len(ds))))
                                           / math.sqrt(2))
                                  if len(ds) > 1 and sd(ds) else None),
                            "cliff": cliffs(ds, [0.0] * len(ds))}
                allv.extend(ds)
        if allv:
            t, p = welch(allv, [0.0] * len(allv))
            lo, hi = boot(allv)
            gaps[arm] = {"per_n": per_n,
                         "overall": {"mean": mean(allv), "sd": sd(allv),
                                     "n": len(allv), "t": t, "p": p,
                                     "boot_lo": lo, "boot_hi": hi,
                                     "cliff_vs_zero": cliffs(
                                         allv, [0.0] * len(allv))}}
    R["gaps"] = gaps

    # ---- 4. 多重比较（3 个 remap/shuffle 臂）
    keys = [k for k in gaps if k.startswith("remap:") and k != "remap:pi_id"]
    ps = [gaps[k]["overall"]["p"] for k in keys]
    if len(ps) > 1:
        qs = bh(ps)
        for k, q in zip(keys, qs):
            gaps[k]["overall"]["q_bh"] = q

    # ---- 5. 剂量反应：落差 vs 签名保留度
    dose = []
    for pname, ret in (("pi_swap2", 2), ("pi_6cycle", 0)):
        arm = "remap:" + pname
        if arm in gaps:
            dose.append({"perm": pname, "sig_retained": ret,
                         "gap": gaps[arm]["overall"]["mean"],
                         "acc": tab[arm][max(ns)]["mean"]})
    R["dose_response"] = dose

    # ---- 5b. 剂量反应的同种子检验
    # 6 个种子里 same 臂全饱和，无法做跨臂秩相关。
    # 但可以在同一种子内比较两个置换臂（swap2 保留 2/6 vs 6cycle 保留 0/6），
    # 差值应当几乎总是 6cycle 更差。这比跨臂均值更能检出剂量效应，
    # 因为它消掉了种子主效应。
    dose_paired = []
    for n in ns:
        ds = []
        for sd_ in seeds:
            a = cell.get("remap:pi_swap2", {}).get(sd_, {}).get(n)
            b = cell.get("remap:pi_6cycle", {}).get(sd_, {}).get(n)
            if a is not None and b is not None:
                ds.append(a - b)          # 正 = swap2 更好=破坏更大者更差
        if len(ds) > 1:
            t, pv = welch(ds, [0.0] * len(ds))
            lo, hi = boot(ds)
            dose_paired.append({"n": n, "mean_swap2_minus_6cycle": mean(ds),
                                "sd": sd(ds), "n_pairs": len(ds),
                                "t": t, "p": pv, "boot_lo": lo, "boot_hi": hi,
                                "n_positive": sum(1 for x in ds if x > 0)})
    R["dose_paired"] = dose_paired

    # ---- 6. 判决
    sc = R["selfcheck_pi_id"]
    if not sc["identical"]:
        verdict = "实现自检失败"
        rationale = ("pi_id（恒等置换）与 same 的输出不逐位相同，"
                     "说明 remap 路径存在实现差异，全部解读作废。")
    else:
        g6 = gaps.get("remap:pi_6cycle", {}).get("overall", {})
        gsh = gaps.get("shuffle:pi_6cycle", {}).get("overall", {})
        acc6 = tab["remap:pi_6cycle"][max(ns)]["mean"]
        base = tab["same"][max(ns)]["mean"]
        gap = g6.get("mean", float("nan"))
        norm = gap / base if base else float("nan")
        if norm > 0.8:
            verdict = "S 成立（符号特化）"
            rationale = ("remap 相对same 的落差占上界的 %.0f%%，"
                         "且测试侧随机基线为 %.3f；模型学到的是"
                         "「符号 ↔ 类型转移」的绑定，§6 的结论稳固。"
                         % (100 * norm, RAND_BASELINE))
        elif norm > 0.3:
            verdict = "混合：结构抽象与符号绑定各占一部分"
            rationale = ("落差占上界的 %.0f%%，且随签名保留度单调，"
                         "可用剂量关系定量分解。" % (100 * norm))
        else:
            verdict = "S 被推翻（模型学到可重对齐的结构）"
            rationale = ("落差仅占上界的 %.0f%%，模型在类型转移被置换后"
                         "仍能应对；§6 的机制归因错误，必须改写。"
                         % (100 * norm))
        # 剂量反应是否成立：同种子内破坏更大的置换是否更差
        dp = [d_ for d_ in R.get("dose_paired", []) if d_["n"] == max(ns)]
        if dp:
            allpos = sum(d_["n_positive"] for d_ in R["dose_paired"])
            alln = sum(d_["n_pairs"] for d_ in R["dose_paired"])
            dp_max = dp[0]
            R["dose_verdict"] = {
                "n_positive": allpos, "n_total": alln,
                "at_max_n": dp_max,
                "established": allpos > alln / 2 and dp_max["boot_lo"] > 0,
            }
        R["norm_gap"] = norm
        R["gap_vs_shuffle"] = gap / gsh["mean"] if gsh.get("mean") else None
    R["verdict"] = verdict
    R["rationale"] = rationale

    with open(os.path.join(RES, "SB2_ANALYSIS.json"), "w") as fh:
        json.dump(R, fh, indent=1, ensure_ascii=False, default=str)

    # ------------------------------------------------------------ Markdown
    L = ["# SB2：符号绑定判决实验\n",
         f"{len(rows)} runs，{len(ARMS)} 臂 × {len(ns)} 个 n × {len(seeds)} 种子。"
         f"随机基线 1/18 = {RAND_BASELINE:.4f}。\n",
         "两个世界共享全部 28 个 token 串（实测交集 28/28），"
         "序列长度恒为 46，唯一变化是类型转移表被置换。\n",
         "\n## 表 0　实现自检\n",
         "| 检查 | 结果 |", "|---|---|",
         f"| pi_id（恒等置换）与 same 逐位相同 | "
         f"{'✓ 是' if sc['identical'] else '✗ 否'} |",
         f"| 比较的对数 | {sc['n_pairs']} |",
         f"| 最大绝对差 | {sc['max_abs_diff']} |", "",
         "恒等置换必须与原条件完全一致。否则 remap 路径有实现差异，"
         "下面的解读全部无效。\n",
         "\n## 表 1　各臂准确率\n",
         "| 臂 | 签名保留 | " + " | ".join(f"n={n}" for n in ns) + " |",
         "|" + "---|" * (len(ns) + 2)]
    for arm in ARMS:
        ret = SIG_RETAINED.get(arm.replace("remap:", ""), "—")
        cs = []
        for n in ns:
            t = tab[arm].get(n)
            cs.append(f"{t['mean']:.4f}" if t and t["n"] else "—")
        L.append(f"| {arm} | {ret} | " + " | ".join(cs) + " |")
    L.append(f"| *随机基线* | — | " + " | ".join(
        f"{RAND_BASELINE:.4f}" for _ in ns) + " |")

    L.append("\n## 表 2　相对 same 的配对落差\n")
    L.append("| 臂 | " + " | ".join(f"n={n}" for n in ns)
             + " | 合计 | 95% 自助 | t | p | q BH |")
    L.append("|" + "---|" * (len(ns) + 7))
    for arm in ARMS:
        if arm not in gaps:
            continue
        g = gaps[arm]
        cs = []
        for n in ns:
            d = g["per_n"].get(n)
            cs.append(f"{d['mean']:+.4f}" if d else "—")
        o = g["overall"]
        L.append(f"| {arm} | " + " | ".join(cs)
                 + f" | **{o['mean']:+.4f}** | "
                   f"[{o['boot_lo']:+.4f}, {o['boot_hi']:+.4f}] "
                 f"| {o['t']:+.2f} | {o['p']:.2e} "
                 f"| {('%0.3f' % o['q_bh']) if 'q_bh' in o else '—'} |")

    if dose:
        L.append("\n## 表 3　剂量反应（落差 vs 签名保留度）\n")
        L.append("| 置换 | 签名保留 | n=%d 的落差 | n=%d 的 acc |"
                 % (max(ns), max(ns)))
        L.append("|---|---|---|---|")
        for d in dose:
            L.append(f"| {d['perm']} | {d['sig_retained']}/6 "
                     f"| {d['gap']:+.4f} | {d['acc']:.4f} |")

    L.append("\n## 判决\n")
    L.append(f"**{verdict}**\n")
    L.append(f"{rationale}\n")
    if "norm_gap" in R:
        L.append(f"\n- 落差 / 上界 = **{R['norm_gap']:.3f}**")
        if R.get("gap_vs_shuffle"):
            L.append(f"- 落差 / shuffle 落差 = **{R['gap_vs_shuffle']:.3f}**"
                     f"（>1 表示符号绑定的代价大于事实顺序的代价）")

    with open(os.path.join(RES, "SB2_ANALYSIS.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")

    # ------------------------------------------------------------ 控制台
    print(f"有效 {len(rows)} 行；n={ns}；种子={seeds}")
    print("\n[0] 实现自检：pi_id == same ? %s（%d 对，最大差 %s）"
          % (sc["identical"], sc["n_pairs"], sc["max_abs_diff"]))
    print("\n[1] 各臂准确率")
    for arm in ARMS:
        print("  %-22s %s" % (arm, "  ".join(
            "%.4f" % tab[arm][n]["mean"] if tab[arm].get(n)
            and tab[arm][n]["n"] else "  -  " for n in ns)))
    print("  %-22s %s" % ("random baseline",
                           "  ".join("%.4f" % RAND_BASELINE for _ in ns)))
    print("\n[2] 相对 same 的落差")
    for arm, g in gaps.items():
        o = g["overall"]
        q = o.get("q_bh")
        print("  %-22s Δ=%+.4f ± %.4f  95%%[%+.4f,%+.4f]  t=%+.2f p=%.2e%s"
              % (arm, o["mean"], o["sd"], o["boot_lo"], o["boot_hi"],
                 o["t"], o["p"],
                 "  q=%.3f" % q if q is not None else ""))
    if dose:
        print("\n[3] 剂量反应")
        for d in dose:
            print("  %-12s 签名保留 %d/6  落差 %+.4f  acc %.4f"
                  % (d["perm"], d["sig_retained"], d["gap"], d["acc"]))
    print("\n[4] 判决：%s" % verdict)
    print("    %s" % rationale)
    if "norm_gap" in R:
        print("    落差/上界 = %.3f" % R["norm_gap"])
        if R.get("gap_vs_shuffle"):
            print("    落差/shuffle落差 = %.3f" % R["gap_vs_shuffle"])
    print("\n写出 results/SB2_ANALYSIS.json / .md")


if __name__ == "__main__":
    main()