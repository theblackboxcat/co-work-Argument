#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_xs.py
=============
跨表面迁移实验的分析：判决「§6 的符号特化」与「基质结构 + en 绑定」
这两个解释中哪一个成立。

两种解释对跨表面迁移给出相反的预测
----------------------------------
    S（§6 的原结论）：模型学到 token 串 → 类型转移的符号级映射
        预测：跨表面迁移**失败**（测试侧的 token 串训练时从未见过）
    M（替代解释）：模型学到基质结构（类型转移图），但绑定在训练表面
        预测：跨表面迁移**成功**（基质没变，只是符号换了一套）

格点分类
--------
    same    X -> X              行内基线，上界
    ring    X -> next(X)        有向跨表面（环形），判决性
    rev     next(X) -> X        反向跨表面，检验方向不对称
    perm    X -> X_relperm      池内置换，语义层对照

读法
----
    纯表面代价 = acc(X -> X) − acc(X -> next(X))       （基质不变，只换表面）
    纯语义代价 = acc(X -> X) − acc(X -> X_relperm)     （池不变，只换语义对应）

若两者都≈0，则符号系统整体不重要（§4 的结论在此任务上延伸成立）；
若纯表面代价 >> 纯语义代价，则 S 成立、§6 稳固；
若纯表面代价 ≈ 0 而纯语义代价 >> 0，则原§4 的阴性反而支持了一个
「语义重要而实现无关」的读法，与 S 和 M 都不同。

输出 results/XS_ANALYSIS.json / .md
"""
import os
import json
import math
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
SRC = os.path.join(RES, "XS.jsonl")

REAL = ["zh", "en", "lisp", "math", "code", "alien"]
RING = ["zh", "en", "lisp", "math", "code", "alien"]
TAU = 0.60


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


def boot_ci(d, iters=20000, seed=0):
    import random
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


def classify(tr, te):
    if tr == te:
        return "same"
    if tr.endswith("_relperm") and tr[:-8] == te:
        return "perm_rev"
    if te.endswith("_relperm") and tr == te[:-8]:
        return "perm"
    if RING[(RING.index(tr) + 1) % len(RING)] == te:
        return "ring"
    if RING[(RING.index(te) + 1) % len(RING)] == tr:
        return "rev"
    return "cross"


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
    print(f"有效 {len(rows)} 行；n={ns}；种子={seeds}")

    # cell[(tr,te,seed)][n] = acc
    cell = {}
    for r in rows:
        cell.setdefault((r["train_surface"], r["test_surface"], r["seed"]), {})[
            r["n_train"]] = r["acc"]

    R = {"n_rows": len(rows), "n_grid": ns, "seeds": seeds, "tau": TAU,
         "n_cell": len(cell)}

    # ---- 逐格点汇总
    def agg(tr, te, n):
        vals = [cell[(tr, te, s)][n] for s in seeds
                if (tr, te, s) in cell and n in cell[(tr, te, s)]]
        return {"mean": mean(vals), "sd": sd(vals), "n": len(vals),
                "vals": vals}

    grid = {}
    for (tr, te, s) in cell:
        k = classify(tr, te)
        grid.setdefault(k, []).append((tr, te))
    R["counts"] = {k: len(set(v)) for k, v in grid.items()}

    # ---- 基线（同表面）
    base = {}
    for b in REAL:
        for n in ns:
            a = agg(b, b, n)
            if a["n"]:
                base[(b, n)] = a

    # ---- 三类迁移代价（按种子配对）
    costs = {"ring": [], "rev": [], "perm": []}
    detail = {"ring": [], "rev": [], "perm": []}
    for n in ns:
        for tr, te in sorted(set(grid.get("ring", []) + grid.get("rev", [])
                                 + grid.get("perm", []))):
            k = classify(tr, te)
            if (tr, n) not in base:
                continue
            b_te = te[:-8] if te.endswith("_relperm") else te
            if (b_te, n) not in base:
                continue
            # 配对：同一 seed 下，基线臂与迁移臂的差
            ds = []
            for s in seeds:
                k1 = (tr, tr, s) in cell and n in cell[(tr, tr, s)]
                k2 = (tr, te, s) in cell and n in cell[(tr, te, s)]
                if k1 and k2:
                    ds.append(cell[(tr, tr, s)][n] - cell[(tr, te, s)][n])
            if not ds:
                continue
            t, p = welch(ds, [0.0] * len(ds))
            lo, hi = boot_ci(ds)
            costs[k].extend(ds)
            detail[k].append({
                "train": tr, "test": te, "n": n, "n_pairs": len(ds),
                "mean_cost": mean(ds), "sd_cost": sd(ds),
                "t": t, "p": p, "boot_lo": lo, "boot_hi": hi,
                "cliff_vs_zero": cliffs(ds, [0.0] * len(ds)),
                "base_mean": base[(b_te, n)]["mean"],
                "transfer_mean": mean(
                    [cell[(tr, te, s)][n] for s in seeds
                     if (tr, te, s) in cell and n in cell[(tr, te, s)]]),
            })

    # ---- 多重比较
    for k in detail:
        ps = [d["p"] for d in detail[k] if d["p"] == d["p"]]
        if len(ps) > 1:
            qs = bh(ps)
            for d, q in zip([d for d in detail[k] if d["p"] == d["p"]], qs):
                d["q_bh"] = q
        else:
            for d in detail[k]:
                d["q_bh"] = None

    # ---- 汇总
    summary = {}
    for k in ("ring", "rev", "perm"):
        ds = costs[k]
        if not ds:
            continue
        t, p = welch(ds, [0.0] * len(ds))
        lo, hi = boot_ci(ds)
        summary[k] = {
            "n_pairs_total": len(ds),
            "mean_cost": mean(ds), "sd_cost": sd(ds),
            "t": t, "p": p, "boot_lo": lo, "boot_hi": hi,
            "cliff_vs_zero": cliffs(ds, [0.0] * len(ds)),
            "n_cells": len(detail[k]),
            "n_sig_raw": sum(1 for d in detail[k]
                             if d["p"] == d["p"] and d["p"] <= 0.05),
            "n_sig_bh": sum(1 for d in detail[k]
                            if d.get("q_bh") is not None
                            and d["q_bh"] <= 0.05),
            "n_positive": sum(1 for x in ds if x > 0),
        }
    R["summary"] = summary
    R["detail"] = detail

    # ---- 判决
    ring = summary.get("ring", {})
    perm = summary.get("perm", {})
    verdict, rationale = None, ""
    if ring and perm:
        rc, pc = ring["mean_cost"], perm["mean_cost"]
        if ring.get("n_sig_bh", 0) == 0 and perm.get("n_sig_bh", 0) == 0:
            verdict = "两者都不可检出"
            rationale = ("跨表面迁移与语义置换都未产生可检出的代价；"
                         "§4 的阴性在本任务上延伸，§6 的符号特化解释"
                         "需要修订（它预测跨表面应失败）")
        elif rc > 0 and rc >= pc:
            verdict = "S 成立（符号特化）"
            rationale = ("跨表面代价显著且不小于语义置换代价；"
                         "模型学到的是符号级映射，§6 稳固")
        elif rc <= 0 < pc:
            verdict = "语义重要，实现无关"
            rationale = ("语义置换有代价而换表面无代价；"
                         "这既不支持 S 也不支持 M，是第三种读法")
        else:
            verdict = "M 或混合"
            rationale = "跨表面代价小于语义置换代价，倾向基质结构绑定于训练表面"
    R["verdict"] = verdict
    R["rationale"] = rationale

    # ---- 突破概率
    bp = {}
    for (tr, te) in sorted(set(grid.get("same", []) + grid.get("ring", [])
                                + grid.get("perm", []))):
        k = classify(tr, te)
        for n in ns:
            vals = [cell[(tr, te, s)][n] for s in seeds
                    if (tr, te, s) in cell and n in cell[(tr, te, s)]]
            if vals:
                bp.setdefault(f"{tr}->{te}", {})[str(n)] = {
                    "p_hat": sum(1 for v in vals if v >= TAU) / len(vals),
                    "mean": mean(vals), "n": len(vals)}
    R["breakthrough"] = bp

    with open(os.path.join(RES, "XS_ANALYSIS.json"), "w") as fh:
        json.dump(R, fh, indent=1, ensure_ascii=False, default=str)

    # ------------------------------------------------------------ Markdown
    L = ["# 跨表面迁移：§6 判决性实验\n",
         f"{len(rows)} runs；{len(cell)} 个 (训练面, 测试面, 种子) 格；"
         f"n={ns}；种子={seeds}。全部表面序列长度 46 token，已配平。\n",
         "\n## 表 1　行内基线（同表面）\n",
         "| 表面 | " + " | ".join(f"n={n}" for n in ns) + " |",
         "|" + "---|" * (len(ns) + 1)]
    for b in REAL:
        cs = []
        for n in ns:
            a = base.get((b, n))
            cs.append(f"{a['mean']:.4f}" if a and a["n"] else "—")
        L.append(f"| {b} | " + " | ".join(cs) + " |")

    L.append("\n## 表 2　迁移代价（正 = 迁移有代价）\n")
    for k, tag in (("ring", "跨表面（环形，判决性）"),
                   ("rev", "跨表面（反向）"),
                   ("perm", "池内置换（语义对照）")):
        if k not in detail or not detail[k]:
            continue
        L.append(f"\n### {tag}\n")
        L.append("| 训练面 | 测试面 | n | 基线 acc | 迁移 acc | 代价 | SD | t | p | q BH |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for d in sorted(detail[k], key=lambda x: (x["train"], x["test"], x["n"])):
            L.append(f"| {d['train']} | {d['test']} | {d['n']} "
                     f"| {d['base_mean']:.4f} | {d['transfer_mean']:.4f} "
                     f"| {d['mean_cost']:+.4f} | {d['sd_cost']:.4f} "
                     f"| {d['t']:+.2f} | {d['p']:.3f} "
                     f"| {('%0.3f' % d['q_bh']) if d.get('q_bh') is not None else '—'} |")
        s = summary[k]
        L.append(f"\n合计：代价 **{s['mean_cost']:+.4f}** ± {s['sd_cost']:.4f}，"
                 f"自助 95% [{s['boot_lo']:+.4f}, {s['boot_hi']:+.4f}]，"
                 f"t = {s['t']:+.2f}，p = {s['p']:.4f}，"
                 f"Cliff's δ(0) = {s['cliff_vs_zero']:+.3f}；"
                 f"{s['n_cells']} 个格点中未校正显著 {s['n_sig_raw']} 个、"
                 f"BH 显著 {s['n_sig_bh']} 个\n")

    L.append("\n## 判决\n")
    L.append(f"**{verdict}**\n")
    L.append(f"{rationale}\n")

    with open(os.path.join(RES, "XS_ANALYSIS.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")

    # ------------------------------------------------------------ 控制台
    print("\n[1] 格点构成", R["counts"])
    print("\n[2] 行内基线")
    for b in REAL:
        print("  %-6s %s" % (b, "  ".join(
            "%.4f" % base[(b, n)]["mean"] if (b, n) in base and base[(b, n)]["n"]
            else "   -   " for n in ns)))
    print("\n[3] 迁移代价汇总")
    for k in ("ring", "rev", "perm"):
        if k not in summary:
            continue
        s = summary[k]
        print("  %-5s 代价 %+.4f ± %.4f  95%%CI [%+.4f, %+.4f]  "
              "t=%+.2f p=%.4f  δ=%+.3f  格点 %d（未校正显著 %d / BH %d）"
              % (k, s["mean_cost"], s["sd_cost"], s["boot_lo"], s["boot_hi"],
                 s["t"], s["p"], s["cliff_vs_zero"], s["n_cells"],
                 s["n_sig_raw"], s["n_sig_bh"]))
    print("\n[4] 判决：%s" % verdict)
    print("    %s" % rationale)
    print("\n写出 results/XS_ANALYSIS.json / .md")


if __name__ == "__main__":
    main()