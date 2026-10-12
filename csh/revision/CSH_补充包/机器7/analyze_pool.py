#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_pool.py
===============
在POOL 实验（12 臂 × 4 个n × 12 种子 = 576 runs）上做因子分解：

    acc = μ + α_pool(池) + β_sem(语义有无) + (αβ)_pool×sem + f(n) + ε

核心问题：**符号置换是否产生可检出的代价？**
原论文用en 池的两个置换臂作对照，无法排除「池身份」这一混淆。
本实验让每个表面与**它自己的**置换配对，从差分中干净地取出语义项。

估计量
------
1. 突破概率 P(acc ≥ τ | n, arm)  —— 分布化阈值（arXiv:2502.17356）
2. 配对差 Δ(pool) = acc(X, seed) − acc(X_relperm, seed)
   —— 同臂同种子，池与slot 都对齐，只剩语义这一个自由度
3. 两因素方差分解：池解释多少、语义解释多少、交互多少

输出 results/POOL_ANALYSIS.json / .md
"""
import os
import sys
import json
import math
import itertools
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
SRC = os.path.join(RES, "POOL.jsonl")

TAU = 0.60
REAL = ["zh", "en", "lisp", "math", "code", "alien"]


# ----------------------------------------------------------------统计
def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def var(xs):
    xs = list(xs)
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def sd(xs):
    v = var(xs)
    return math.sqrt(v) if v == v else float("nan")


def welch_t(a, b):
    """Welch t 检验，不假设等方差。"""
    a, b = list(a), list(b)
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    va, vb = var(a) / len(a), var(b) / len(b)
    den = math.sqrt(va + vb)
    if den == 0:
        return float("nan"), float("nan")
    t = (mean(a) - mean(b)) / den
    df_num = (va + vb) ** 2
    df_den = va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1)
    df = df_num / df_den if df_den else float("inf")
    # t 分布双侧 p：用正态近似（df>=5 时误差可接受），并标注
    p = math.erfc(abs(t) / math.sqrt(2))
    return t, p


def cliffs_delta(a, b):
    a, b = list(a), list(b)
    if not a or not b:
        return float("nan")
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


def paired_boot(diffs, iters=20000, seed=0):
    """配对差的自助法 95% 区间（BCa 略复杂，用 percentile + 端点修正）。"""
    import random
    diffs = [d for d in diffs if d == d]
    if len(diffs) < 3:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    m = len(diffs)
    means = []
    for _ in range(iters):
        means.append(sum(diffs[rng.randrange(m)] for _ in range(m)) / m)
    means.sort()
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def n_star_interp(accs_by_n, ns, tau=TAU):
    prev = None
    for n in sorted(ns):
        a = accs_by_n.get(n)
        if a is None:
            continue
        if a >= tau:
            if prev is None:
                return float(n)
            n0, a0 = prev
            return n0 + (n - n0) * (tau - a0) / (a - a0)
        prev = (n, a)
    return None


def wilson(k, m):
    if m == 0:
        return (float("nan"), float("nan"))
    z = 1.959963985
    p = k / m
    den = 1 + z * z / m
    ctr = (p + z * z / (2 * m)) / den
    half = z * math.sqrt(p * (1 - p) / m + z * z / (4 * m * m)) / den
    return (max(0.0, ctr - half), min(1.0, ctr + half))


# ----------------------------------------------------------------主
def main():
    if not os.path.exists(SRC):
        print("!! %s 不存在" % SRC)
        return
    rows = []
    bad = 0
    for ln in open(SRC):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            bad += 1
            continue
        if r.get("acc") is None or r["acc"] != r["acc"] or "error" in r:
            continue
        rows.append(r)
    if not rows:
        print("!! 无有效行")
        return

    arms = sorted(set(r["surface"] for r in rows))
    ns = sorted(set(r["n_train"] for r in rows))
    seeds = sorted(set(r["seed"] for r in rows))
    print(f"有效 {len(rows)} 行（坏行 {bad}）；{len(arms)} 臂 × "
          f"{len(ns)} 个 n × {len(seeds)} 种子")

    # cell[(arm, seed)][n] = acc
    cell = {}
    for r in rows:
        cell.setdefault((r["surface"], r["seed"]), {})[r["n_train"]] = r["acc"]

    R = {"tau": TAU, "n_rows": len(rows), "n_bad": bad,
         "arms": arms, "n_grid": ns, "seeds": seeds}

    # ---- 1. 每臂的突破概率曲线
    R["breakthrough"] = {}
    for a in arms:
        seeds_a = [s for s in seeds if (a, s) in cell]
        curve = []
        for n in ns:
            accs = [cell[(a, s)][n] for s in seeds_a if n in cell[(a, s)]]
            k = sum(1 for x in accs if x >= TAU)
            lo, hi = wilson(k, len(accs))
            curve.append({"n": n, "k": k, "m": len(accs),
                          "p_hat": k / len(accs) if accs else None,
                          "lo": lo, "hi": hi,
                          "mean_acc": mean(accs), "sd_acc": sd(accs)})
        R["breakthrough"][a] = {
            "curve": curve,
            "n_star": {str(s): n_star_interp(
                cell[(a, s)], ns) for s in seeds_a},
        }

    # ---- 2. 配对差：同臂同种子 X vs X_relperm
    pairs = []
    for base in REAL:
        perm = base + "_relperm"
        if perm not in arms:
            continue
        seeds_b = sorted(set(s for (a, s) in cell if a == base)
                         & set(s for (a, s) in cell if a == perm))
        per_n = {}
        alld = []
        for n in ns:
            d = [cell[(base, s)][n] - cell[(perm, s)][n]
                 for s in seeds_b if n in cell[(base, s)] and n in cell[(perm, s)]]
            if d:
                per_n[n] = d
                alld.extend(d)
        t, p = welch_t(per_n.get(max(ns), alld), per_n.get(max(ns), alld))
        # 正确的配对检验：对「每种子在最大 n 上的差」做单样本 t
        dmax = per_n.get(max(ns), [])
        mt = (mean(dmax) / (sd(dmax) / math.sqrt(len(dmax)))
              if len(dmax) > 1 and sd(dmax) else float("nan"))
        mp = math.erfc(abs(mt) / math.sqrt(2)) if mt == mt else float("nan")
        lo, hi = paired_boot(dmax)
        # n* 配对差
        nsd = []
        for s in seeds_b:
            a1 = R["breakthrough"][base]["n_star"].get(str(s))
            a2 = R["breakthrough"][perm]["n_star"].get(str(s))
            if a1 and a2:
                nsd.append(a1 - a2)
        pairs.append({
            "base": base, "perm": perm, "n_seeds": len(seeds_b),
            "mean_diff_overall": mean(alld),
            "per_n": {str(n): {"mean": mean(v), "sd": sd(v), "n": len(v),
                               "cliff_vs_zero": cliffs_delta(v, [0.0] * len(v)),
                               "t": (mean(v) / (sd(v) / math.sqrt(len(v)))
                                     if len(v) > 1 and sd(v) else None),
                               "p": (math.erfc(abs(mean(v) /
                                                   (sd(v) / math.sqrt(len(v)))) / math.sqrt(2))
                                     if len(v) > 1 and sd(v) else None)}
                       for n, v in sorted(per_n.items())},
            "at_max_n": {"mean": mean(dmax), "sd": sd(dmax), "n": len(dmax),
                         "t": mt, "p": mp, "boot_lo": lo, "boot_hi": hi,
                         "cliff_vs_zero": cliffs_delta(dmax, [0.0] * len(dmax))},
            "n_star_diff": {"mean": mean(nsd), "sd": sd(nsd), "n": len(nsd)},
        })
    # 多重比较校正：6 个配对 × 单侧/双侧
    ps = [p["at_max_n"]["p"] for p in pairs]
    ps_ok = [x for x in ps if x == x]
    m = len(ps_ok)
    def bonferroni(ps_):
        return {i: min(1.0, x * len(ps_)) for i, x in enumerate(ps_) if x == x}
    def bh(ps_):
        idx = sorted(range(len(ps_)), key=lambda i: ps_[i])
        k = len(ps_)
        out = {}
        prev = 1.0
        for rank in range(k - 1, -1, -1):
            i = idx[rank]
            val = min(prev, ps_[i] * k / (rank + 1))
            out[i] = val
            prev = val
        return out
    bon, bhq = bonferroni(ps_ok), bh(ps_ok)
    R["multiplicity"] = {
        "n_tests": m,
        "alpha_bonferroni": 0.05 / m if m else None,
        "p_raw": ps,
        "p_bonferroni": [bon.get(i) for i in range(m)],
        "q_bh": [bhq.get(i) for i in range(m)],
        "n_sig_raw": sum(1 for x in ps_ok if x <= 0.05),
        "n_sig_bonferroni": sum(1 for v in bon.values() if v <= 0.05),
        "n_sig_bh": sum(1 for v in bhq.values() if v <= 0.05),
    }

    R["paired"] = pairs

    # 汇总：6 个配对的差值是否一致为负/正
    dm = [p["at_max_n"]["mean"] for p in pairs
          if p["at_max_n"]["mean"] == p["at_max_n"]["mean"]]
    signs = [1 if x > 0 else (-1 if x < 0 else 0) for x in dm]
    # 符号检验（2/6 方向一侧）
    from math import comb
    k = sum(1 for s in signs if s > 0)
    npos = len(signs)
    p_sign = (sum(comb(npos, i) for i in range(k, npos + 1))
              / 2 ** npos) if npos else None
    R["aggregate"] = {
        "per_pair_mean_diff_at_max_n": dm,
        "mean_of_diffs": mean(dm), "sd_of_diffs": sd(dm),
        "n_positive": k, "n_pairs": npos,
        "sign_test_one_sided_p": p_sign,
        "pooled_sd_within_pair": math.sqrt(
            mean([p["at_max_n"]["sd"] ** 2 for p in pairs
                  if p["at_max_n"]["sd"] == p["at_max_n"]["sd"]])),
    }

    # ---- 3. 两因素方差分解：acc ~ pool + sem + pool:sem + n
    def ss_between(rows, keyfn):
        g = {}
        for r in rows:
            g.setdefault(keyfn(r), []).append(r["acc"])
        gm = mean([r["acc"] for r in rows])
        return sum(len(v) * (mean(v) - gm) ** 2 for v in g.values())

    base_of = lambda r: r["surface"][:-len("_relperm")] \
        if r["surface"].endswith("_relperm") else r["surface"]
    is_perm = lambda r: r["surface"].endswith("_relperm")
    gm = mean([r["acc"] for r in rows])
    s_tot = sum((r["acc"] - gm) ** 2 for r in rows)
    s_pool = ss_between(rows, base_of)
    s_sem = ss_between(rows, is_perm)
    s_int = ss_between(rows, lambda r: (base_of(r), is_perm(r)))
    s_n = ss_between(rows, lambda r: r["n_train"])
    R["variance"] = {
        "grand_mean": gm, "SS_total": s_tot,
        "SS_pool": s_pool, "SS_semantics": s_sem, "SS_pool_x_sem": s_int,
        "SS_n": s_n,
        "SS_resid": s_tot - s_pool - s_sem - s_n,
        "pct_pool": 100 * s_pool / s_tot,
        "pct_semantics": 100 * s_sem / s_tot,
        "pct_pool_x_sem": 100 * s_int / s_tot,
        "pct_n": 100 * s_n / s_tot,
        "pct_resid": 100 * (s_tot - s_pool - s_sem - s_n) / s_tot,
        # 语义项在扣除池与n 之后的剩余可解释量
        "pct_semantics_residual": 100 * max(
            0.0, s_tot - s_pool - s_n - (s_tot - s_pool - s_sem - s_n)) / s_tot,
    }

    # ---- 4. 池身份是否仍然重要（在语义对齐后）
    # 取每个 base 的原样臂与置换臂，分别算跨base 的方差
    by_base = collections.defaultdict(lambda: {"real": [], "perm": []})
    for a in arms:
        for s in seeds:
            for n in ns:
                if (a, s) in cell and n in cell[(a, s)]:
                    b = base_of({"surface": a})
                    k = "perm" if a.endswith("_relperm") else "real"
                    by_base[b][k].append(cell[(a, s)][n])
    pool_effect = {}
    for k in ("real", "perm"):
        means = [mean(by_base[b][k]) for b in REAL if by_base[b][k]]
        if len(means) > 1:
            gm2 = mean(means)
            ss = sum((x - gm2) ** 2 for x in means)
            pool_effect[k] = {"means": means, "sd_across_pool": sd(means),
                              "range": max(means) - min(means),
                              "cv": sd(means) / gm2 if gm2 else None}
    # 在每个 base 内部做差后，跨 base 的方差应当只剩噪声
    R["pool_effect"] = pool_effect

    # ---- 5. τ 扫描：语义效应是否依赖判据
    sweep = []
    for tau in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
        row = {"tau": tau}
        diffs = []
        for base in REAL:
            perm = base + "_relperm"
            if perm not in arms:
                continue
            sb = sorted(set(s for (a, s) in cell if a == base)
                        & set(s for (a, s) in cell if a == perm))
            pr = []
            for s in sb:
                # 该种子下：原样臂的 n* 与置换臂的 n*
                def ns_of(a):
                    prev = None
                    for n in ns:
                        v = cell[(a, s)].get(n)
                        if v is None:
                            continue
                        if v >= tau:
                            if prev is None:
                                return float(n)
                            n0, v0 = prev
                            return n0 + (n - n0) * (tau - v0) / (v - v0)
                        prev = (n, v)
                    return None
                a1, a2 = ns_of(base), ns_of(perm)
                if a1 and a2:
                    pr.append(a1 - a2)
            if pr:
                row[base] = {"mean_n_star_diff": mean(pr), "n": len(pr)}
                diffs.append(mean(pr))
        row["diffs"] = diffs
        row["mean_diff"] = mean(diffs)
        row["n_neg"] = sum(1 for x in diffs if x < 0)
        sweep.append(row)
    R["tau_sweep"] = sweep

    with open(os.path.join(RES, "POOL_ANALYSIS.json"), "w") as fh:
        json.dump(R, fh, indent=1, ensure_ascii=False, default=str)

    # ------------------------------------------------------------ Markdown
    L = ["# 池 × 语义 正交实验：符号置换是否产生可检出的代价\n",
         f"12 臂（6 真实表面 × {{原样, 自身关系标签置换}}）× {len(ns)} 个 n × "
         f"{len(seeds)} 种子 = {len(rows)} runs。判据 τ={TAU}。\n",
         "每个 `X_relperm` 与 `X` 共享**同一词法池**（token 字符串集合逐个相同），"
         "只把关系标签相对类型转移的对应洗牌。因此配对差内的唯一自由度是语义。\n",
         "\n## 表 1　各臂突破概率 P(acc≥τ | n)\n",
         "| 臂 | " + " | ".join(f"n={n}" for n in ns) + " |",
         "|" + "---|" * (len(ns) + 1)]
    for a in arms:
        cs = R["breakthrough"][a]["curve"]
        L.append(f"| {a} | " + " | ".join(
            f"{c['p_hat']:.2f} [{c['lo']:.2f},{c['hi']:.2f}]" if c["p_hat"] is not None
            else "—" for c in cs) + " |")

    L.append("\n## 表 2　配对差 Δ = acc(X) − acc(X_relperm)\n")
    L.append("| 表面 | " + " | ".join(f"Δ(n={n})" for n in ns)
             + " | Δ 均值 | SD | t | p | 自助 95% | Cliff's δ(0) | Δ(n★) |")
    L.append("|" + "---|" * (len(ns) + 8))
    for p in pairs:
        am = p["at_max_n"]
        cells = []
        for n in ns:
            d = p["per_n"].get(str(n))
            cells.append(f"{d['mean']:+.3f}" if d else "—")
        L.append(f"| {p['base']} | " + " | ".join(cells)
                 + f" | **{am['mean']:+.4f}** | {am['sd']:.4f} "
                 f"| {am['t']:+.2f} | {am['p']:.3f} "
                 f"| [{am['boot_lo']:+.3f}, {am['boot_hi']:+.3f}] "
                 f"| {am['cliff_vs_zero']:+.3f} "
                 f"| {p['n_star_diff']['mean']:+.0f} |")

    ag = R["aggregate"]
    L.append(f"\n6 个配对在最大 n 上的Δ：{['%+.4f' % x for x in ag['per_pair_mean_diff_at_max_n']]}")
    L.append(f"- 均值 **{ag['mean_of_diffs']:+.4f}**，配对间 SD **{ag['sd_of_diffs']:.4f}**")
    L.append(f"- 配对内合并 SD **{ag['pooled_sd_within_pair']:.4f}**")
    L.append(f"- 方向：{ag['n_positive']}/{ag['n_pairs']} 为正，"
             f"单侧符号检验 p = {ag['sign_test_one_sided_p']:.4f}")
    verdict = ("语义置换**没有**产生可检出的代价"
               if ag["mean_of_diffs"] < 0.02 and ag["mean_of_diffs"] > -0.02
               else ("语义置换产生**可检出**的代价"
                     if ag["mean_of_diffs"] > 0 else "语义置换反而降低了代价"))
    L.append(f"\n**判决：{verdict}**（Δ>0 表示原样表面更易学，即语义有帮助）\n")

    L.append("\n## 表 3　方差分解\n")
    v = R["variance"]
    L.append("| 成分 | 平方和占比 |")
    L.append("|---|---|")
    L.append(f"| 池身份 pool | {v['pct_pool']:.2f}% |")
    L.append(f"| 语义 semantics | {v['pct_semantics']:.2f}% |")
    L.append(f"| 池 × 语义 交互 | {v['pct_pool_x_sem']:.2f}% |")
    L.append(f"| 训练规模 n | {v['pct_n']:.2f}% |")
    L.append(f"| 残差 | {v['pct_resid']:.2f}% |")

    L.append("\n## 表 4　池身份效应（语义条件对齐后）\n")
    L.append("| 语义条件 | 跨 6 池的均值 | SD | 极差 | CV |")
    L.append("|---|---|---|---|---|")
    for k, pe in pool_effect.items():
        tag = "原样" if k == "real" else "自身置换"
        L.append(f"| {tag} | " + ", ".join("%.3f" % x for x in pe["means"])
                 + f" | {pe['sd_across_pool']:.4f} | {pe['range']:.4f} "
                 f"| {pe['cv']:.4f} |")

    L.append("\n## 表 5　τ 扫描下的语义效应（以 n* 差衡量）\n")
    L.append("| τ | " + " | ".join(REAL) + " | 均值 | 为负的配对数 |")
    L.append("|" + "---|" * (len(REAL) + 3))
    for row in sweep:
        L.append(f"| {row['tau']:.2f} | "
                 + " | ".join(f"{row[b]['mean_n_star_diff']:+.0f}"
                              if b in row else "—" for b in REAL)
                 + f" | {row['mean_diff']:+.1f} | {row['n_neg']}/{len(row['diffs'])} |")

    with open(os.path.join(RES, "POOL_ANALYSIS.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")

    # ------------------------------------------------------------ 控制台
    print("\n[1] 突破概率")
    for a in arms:
        cs = R["breakthrough"][a]["curve"]
        print("  %-14s %s" % (a, "  ".join(
            f"{c['p_hat']:.2f}" if c["p_hat"] is not None else " - "
            for c in cs)))
    print("\n[2] 配对差 Δ = X − X_relperm")
    for p in pairs:
        am = p["at_max_n"]
        print("  %-6s Δ(n_max)=%+.4f  SD=%.4f  t=%+.2f  p=%.3f  δ0=%+.3f  "
              "n*差=%+.1f"
              % (p["base"], am["mean"], am["sd"], am["t"], am["p"],
                 am["cliff_vs_zero"], p["n_star_diff"]["mean"]))
    print(f"\n[3] 汇总：均值 {ag['mean_of_diffs']:+.4f}，"
          f"{ag['n_positive']}/{ag['n_pairs']} 为正，符号检验 p={ag['sign_test_one_sided_p']:.4f}")
    mp = R["multiplicity"]
    print(f"    多重比较：{mp['n_tests']} 个配对，未校正显著 {mp['n_sig_raw']} 个，"
          f"Bonferroni α'={mp['alpha_bonferroni']:.4f} 显著 {mp['n_sig_bonferroni']} 个，"
          f"BH q≤0.05 显著 {mp['n_sig_bh']} 个")
    for i, base in enumerate(REAL):
        if i < len(mp["p_raw"]):
            print(f"      {base:6s} p={mp['p_raw'][i]:.4f} "
                  f"p_bon={mp['p_bonferroni'][i]:.4f} q_bh={mp['q_bh'][i]:.4f}")
    print(f"    判决：{verdict}")
    print("\n[4] 方差分解")
    print(f"    池 {v['pct_pool']:.2f}%  语义 {v['pct_semantics']:.2f}%  "
          f"交互 {v['pct_pool_x_sem']:.2f}%  n {v['pct_n']:.2f}%  "
          f"残差 {v['pct_resid']:.2f}%")
    print("\n[5] 跨池效应")
    for k, pe in pool_effect.items():
        print(f"    {k:5s} SD={pe['sd_across_pool']:.4f} range={pe['range']:.4f} "
              f"CV={pe['cv']:.4f}")
    print("\n写出 results/POOL_ANALYSIS.json / .md")


if __name__ == "__main__":
    main()