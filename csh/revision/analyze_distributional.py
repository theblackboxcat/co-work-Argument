#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_distributional.py
=========================
把「每种子 τ 交叉点线性插值」的点估计 n* 换成「跨种子的突破概率分布」。

理论依据
--------
1. arXiv:2502.17356 (Zhao, Qin, Alvarez-Melis, Kakade, Saphra; v5 2026-02)
   《Random Scaling of Emergent Capabilities》——涌现不是阈值的确定性跃迁，
   而是一个概率事件。正确的比较对象是整个分布族
       P(acc >= tau | n)
   而不是每条曲线各自的交叉点。

2. arXiv:2512.24145 (Udit Sharma; v3 2026-01)
   《When Does Pairing Seeds Reduce Variance?》——跨条件配对种子
   （common random numbers）把运行间方差压到 1-rho^2。
   本脚本对同一 surface 的两条曲线在配对种子下求差，把
       Var(a-b) = Var(a)+Var(b)-2 Cov(a,b)
   显式分解为「种子主效应」与「条件交互」两项，并给出 rho。

3. Cliff's delta / Wasserstein-1 作为分布重叠度的效应量，
   取代论文原先只报「15 配对全 n.s.」这种只给 p 不给效应的做法。

输出
----
results/DISTRIB.json     机器可读的完整结果
results/DISTRIB.md       直接可贴进论文的表格（Markdown）
控制台                    人读摘要
"""
import json
import glob
import os
import itertools
import math
import random

TAU = 0.60
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")

REAL_SURFACES = ["zh", "en", "lisp", "math", "code", "alien"]
NULL_ARMS = ["relperm", "entperm"]


# ---------------------------------------------------------------- 载入
def load(exp):
    rows = []
    for f in sorted(glob.glob(os.path.join(RES, "*.jsonl"))):
        for ln in open(f):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("_exp") == exp and r.get("acc") is not None and r["acc"] == r["acc"]:
                rows.append(r)
    return rows


# ---------------------------------------------------------------- 统计工具
def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def var(xs):
    xs = list(xs)
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def pearson(a, b):
    a, b = list(a), list(b)
    if len(a) < 2:
        return float("nan")
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return float("nan")
    return num / (da * db)


def cliffs_delta(a, b):
    """P(a>b) - P(a<b)。无参数、单调、可解释。"""
    a, b = list(a), list(b)
    if not a or not b:
        return float("nan")
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


def wasserstein1(a, b):
    """一维 Wasserstein 距离（等权，按排序后的对应分位数差求和 / n）。"""
    a, b = sorted(a), sorted(b)
    if not a or not b:
        return float("nan")
    if len(a) == len(b):
        return mean([abs(x - y) for x, y in zip(a, b)])
    # 等概率测度下的 1D W1：对合并排序后的 gap 积分
    vals = sorted(set(a) | set(b))
    ca = {v: a.count(v) / len(a) for v in vals}
    cb = {v: b.count(v) / len(b) for v in vals}
    Fa, Fb, G = 0.0, 0.0, 0.0
    for v in vals:
        Fa += ca[v]
        Fb += cb[v]
        G += abs(Fa - Fb) * (v - vals[vals.index(v) - 1] if vals.index(v) > 0 else 0)
    return G


# 双侧 p 值（正态近似，无需 scipy）
def z_two_sided(z):
    if z != z:
        return float("nan")
    return math.erfc(abs(z) / math.sqrt(2))


def paired_t_test(d):
    d = [x for x in d if x == x]
    n = len(d)
    if n < 2:
        return float("nan"), float("nan"), n
    m = mean(d)
    v = var(d)
    if v == 0:
        return float("inf") if m else 0.0, 0.0, n
    t = m / math.sqrt(v / n)
    return t, z_two_sided(t), n


# ---------------------------------------------------------------- 分布化估计
def breakthrough_curve(cell, ns):
    """cell: {(n): [acc per seed]} -> 各 n 的突破概率与 Wilson 区间。"""
    out = []
    for n in ns:
        accs = cell.get(n, [])
        k = sum(1 for a in accs if a >= TAU)
        m = len(accs)
        if m == 0:
            continue
        p = k / m
        # Wilson score 区间：小样本下比正态近似可靠得多
        z = 1.959963985
        den = 1 + z * z / m
        ctr = (p + z * z / (2 * m)) / den
        half = z * math.sqrt(p * (1 - p) / m + z * z / (4 * m * m)) / den
        out.append({"n": n, "k": k, "m": m, "p_hat": p,
                    "lo": max(0.0, ctr - half), "hi": min(1.0, ctr + half)})
    return out


def n_star_interp(cell, ns, tau=TAU):
    """保留旧点估计以对照：每条种子曲线线性插值出 n*。"""
    res = {}
    for key, d in cell.items():
        pairs = [(n, d[n]) for n in ns if n in d]
        pairs.sort()
        prev = None
        for i, (n, a) in enumerate(pairs):
            if a >= tau:
                if prev is None:
                    res[key] = float(n)
                else:
                    n0, a0 = prev
                    res[key] = n0 + (n - n0) * (tau - a0) / (a - a0)
                break
            prev = (n, a)
        else:
            res[key] = None
    return res


def logspread(vals):
    """论文原先报的主结果：n* 的 CV(log)。n*=None 视为未突破（删失）。"""
    v = [math.log(x) for x in vals if x is not None and x > 0]
    if len(v) < 2:
        return float("nan"), 0
    return math.sqrt(var(v)) / mean(v), len(v)


# ---------------------------------------------------------------- 主分析
def main():
    rows = load("S2L")
    if not rows:
        print("!! 没有 S2L 数据")
        return

    ns = sorted(set(r["n_train"] for r in rows))
    surfaces = [s for s in REAL_SURFACES + NULL_ARMS
                if s in set(r["surface"] for r in rows)]
    seeds = sorted(set(r["seed"] for r in rows))

    # cell[(surface, seed)][n] = acc
    cell = {}
    for r in rows:
        cell.setdefault((r["surface"], r["seed"]), {})[r["n_train"]] = r["acc"]

    R = {"tau": TAU, "n_grid": ns, "seeds": seeds, "surfaces": surfaces,
         "n_seeds_per_cell": {}}

    # ---- 1. 每表面突破概率曲线 + Wilson 区间
    R["breakthrough"] = {}
    for s in surfaces:
        seeds_s = [sd for sd in seeds if (s, sd) in cell]
        R["n_seeds_per_cell"][s] = len(seeds_s)
        per_n = {}
        for n in ns:
            accs = [cell[(s, sd)][n] for sd in seeds_s
                    if (s, sd) in cell and n in cell[(s, sd)]]
            per_n[n] = accs
        R["breakthrough"][s] = {
            "curve": breakthrough_curve(per_n, ns),
            "accs": {str(n): per_n[n] for n in ns},
            "mean_acc": {str(n): mean(per_n[n]) for n in ns},
        }

    # ---- 2. 点估计 n*（对照用）
    R["n_star"] = {}
    for s in surfaces:
        seeds_s = [sd for sd in seeds if (s, sd) in cell]
        ns_star = n_star_interp({sd: cell[(s, sd)] for sd in seeds_s}, ns)
        vals = [ns_star[sd] for sd in seeds_s]
        cv, nv = logspread(vals)
        R["n_star"][s] = {
            "per_seed": {str(k): v for k, v in ns_star.items()},
            "cv_log": cv, "n_breached": nv, "n_cells": len(seeds_s),
            "censored": sum(1 for v in vals if v is None),
        }

    real_cv = [R["n_star"][s]["cv_log"] for s in REAL_SURFACES if s in R["n_star"]]
    null_cv = [R["n_star"][s]["cv_log"] for s in NULL_ARMS if s in R["n_star"]]
    R["n_star"]["_pooled"] = {
        "real_cv_mean": mean(real_cv), "null_cv_mean": mean(null_cv),
        "real_cvs": real_cv, "null_cvs": null_cv,
    }

    # ---- 3. 突破概率分布族比较（真实族 vs null 族）
    # 每一臂在每个 n 上给出一个概率；把 8（或 2×5）个值当成分布样本做比较
    def pooled_p(surfs):
        d = []
        for s in surfs:
            for row in R["breakthrough"][s]["curve"]:
                d.append(row["p_hat"])
        return d

    real_p = pooled_p(REAL_SURFACES)
    null_p = pooled_p(NULL_ARMS)
    R["family"] = {
        "real_vs_null": {
            "real": real_p, "null": null_p,
            "cliffs_delta": cliffs_delta(real_p, null_p),
            "wasserstein1": wasserstein1(real_p, null_p),
        }
    }
    # 逐 n 比较：同一 n 上真实表面的 p 与 null 的 p
    per_n_cmp = []
    for n in ns:
        rp = [R["breakthrough"][s]["curve"][ns.index(n)]["p_hat"]
              for s in REAL_SURFACES if s in R["breakthrough"]]
        np_ = [R["breakthrough"][s]["curve"][ns.index(n)]["p_hat"]
               for s in NULL_ARMS if s in R["breakthrough"]]
        if rp and np_:
            per_n_cmp.append({"n": n, "real_p": rp, "null_p": np_,
                              "delta": mean(rp) - mean(np_),
                              "cliffs_delta": cliffs_delta(rp, np_)})
    R["family"]["per_n"] = per_n_cmp

    # ---- 3.5 【关键混淆审计】拉丁方 slot 与表面身份的混叠
    # latin.check_parity 要求 n_seeds >= n_surfaces。本实验 8 表面仅 4 种子
    # (seeds = {1,3,5,7})，配平**不完整**。而 slot = (surface_index + seed) mod 8，
    # seed 全为奇数 => slot 奇偶性 == 表面下标奇偶性的反号，于是：
    #     奇 slot: zh(0) lisp(2) code(4) relperm(6)
    #     偶 slot: en(1) math(3) alien(5) entperm(7)
    # 表面主效应与 slot 奇偶效应**完全混叠**，不可分离。
    # 但正因如此，「同奇偶」的真实-vs-null 配对是 slot 匹配的合法配对，
    # 而跨奇偶配对是无效的。下表据此重排。
    idx = {s: i for i, s in enumerate(surfaces)}
    parity = {s: (idx[s] + min(seeds)) % 2 for s in surfaces}
    groups = {}
    for s in surfaces:
        groups.setdefault(parity[s], []).append(s)
    R["slot_audit"] = {
        "n_surfaces": len(surfaces), "n_seeds": len(seeds), "seeds": seeds,
        "parity_ok": len(seeds) >= len(surfaces),
        "parity_of_surface": parity,
        "groups": {str(k): v for k, v in groups.items()},
        "warning": ("种子数 %d < 表面数 %d：latin.check_parity 不通过，"
                    "slot 配平不完整，表面主效应与 slot 奇偶效应混叠"
                    % (len(seeds), len(surfaces))) if len(seeds) < len(surfaces) else "",
    }

    # 3.6 方差分解：acc ~ surface + slot_parity + n + resid
    def variance_components(rows):
        import itertools as _it
        ys = [r["acc"] for r in rows]
        gm = mean(ys)

        def ss_between(keyfn):
            g = {}
            for r in rows:
                g.setdefault(keyfn(r), []).append(r["acc"])
            return sum(len(v) * (mean(v) - gm) ** 2 for v in g.values())

        s_surf = ss_between(lambda r: r["surface"])
        s_par = ss_between(lambda r: parity.get(r["surface"], 0))
        s_n = ss_between(lambda r: r["n_train"])
        s_tot = sum((y - gm) ** 2 for y in ys)
        resid = s_tot - s_surf - s_par - s_n
        return {"grand_mean": gm, "SS_total": s_tot, "SS_surface": s_surf,
                "SS_slot_parity": s_par, "SS_n": s_n, "SS_resid": resid,
                "pct_surface": 100 * s_surf / s_tot,
                "pct_slot_parity": 100 * s_par / s_tot,
                "pct_n": 100 * s_n / s_tot,
                "pct_resid": 100 * resid / s_tot,
                "eta2_surface_within_parity": (
                    1 - ss_between(lambda r: (parity.get(r["surface"], 0), r["surface"]))
                    / s_tot)}

    R["variance"] = {
        "all": variance_components(rows),
        "real_only": variance_components([r for r in rows if r["surface"] in REAL_SURFACES]),
        "null_only": variance_components([r for r in rows if r["surface"] in NULL_ARMS]),
    }

    # 3.7 只保留 slot 奇偶匹配的配对
    pair_rows_matched = []
    for s in REAL_SURFACES:
        for a in NULL_ARMS:
            if parity.get(s) != parity.get(a):
                continue  # 跨奇偶，slot 不匹配，丢弃
            diffs = []
            for sd in seeds:
                for n in ns:
                    if (s, sd) in cell and (a, sd) in cell \
                       and n in cell[(s, sd)] and n in cell[(a, sd)]:
                        diffs.append(cell[(s, sd)][n] - cell[(a, sd)][n])
            t, p, n_eff = paired_t_test(diffs)
            pair_rows_matched.append({
                "surface": s, "null": a, "slot_parity": parity[s],
                "mean_diff": mean(diffs),
                "cliffs_delta": cliffs_delta(diffs, [0.0] * len(diffs)),
                "paired_t": t, "p": p, "n_pairs": n_eff,
            })
    R["paired_slot_matched"] = pair_rows_matched

    # ---- 4. 每个真实表面 vs 每个 null 臂的逐种子配对差
    pair_rows = []
    for s in REAL_SURFACES:
        for a in NULL_ARMS:
            seeds_sa = sorted(set(seeds) & set(seeds))
            diffs, per_n_diff = [], {}
            for n in ns:
                ds = []
                for sd in seeds:
                    if (s, sd) in cell and (a, sd) in cell \
                       and n in cell[(s, sd)] and n in cell[(a, sd)]:
                        ds.append(cell[(s, sd)][n] - cell[(a, sd)][n])
                if ds:
                    per_n_diff[n] = ds
                    diffs.extend(ds)
            t, p, n_eff = paired_t_test(diffs)
            rho = pearson(
                [cell[(s, sd)][n] for sd in seeds for n in ns if (s, sd) in cell and n in cell[(s, sd)]],
                [cell[(a, sd)][n] for sd in seeds for n in ns if (a, sd) in cell and n in cell[(a, sd)]])
            pair_rows.append({
                "surface": s, "null": a,
                "mean_diff": mean(diffs),
                "cliffs_delta": cliffs_delta(diffs, [0.0] * len(diffs)),
                "paired_t": t, "p": p, "n_pairs": n_eff,
                "rho_across_cells": rho,
                "var_reduction_1_minus_rho2": (1 - rho * rho) if rho == rho else None,
                "per_n": {str(k): mean(v) for k, v in per_n_diff.items()},
            })
    R["paired"] = pair_rows

    # ---- 5. 配对种子 vs 独立种子的方差比较（直接回答 2512.24145）
    # 方式：把 (surface, seed) 看成条件；配对 = 在同 seed 内跨 surface 做差
    #      未配对 = 在不同 seed 内跨 surface 做差
    paired_var, unpaired_var = [], []
    for s in REAL_SURFACES:
        for a in NULL_ARMS:
            same, diff = [], []
            for sd in seeds:
                for sd2 in seeds:
                    for n in ns:
                        k1 = (s, sd) in cell and n in cell[(s, sd)]
                        k2 = (a, sd2) in cell and n in cell[(a, sd2)]
                        if k1 and k2:
                            d = cell[(s, sd)][n] - cell[(a, sd2)][n]
                            (same if sd == sd2 else diff).append(d)
            if len(same) > 1:
                paired_var.append(var(same))
            if len(diff) > 1:
                unpaired_var.append(var(diff))
    R["pairing"] = {
        "var_paired": mean(paired_var),
        "var_unpaired": mean(unpaired_var),
        "ratio": (mean(paired_var) / mean(unpaired_var))
                  if mean(unpaired_var) else None,
        "n_pairs_of_cells": len(paired_var),
    }

    # ---- 6. 判据敏感性：τ 扫描下结论是否翻转
    sweep = []
    for tau in [0.50, 0.55, 0.60, 0.65, 0.70]:
        row = {"tau": tau}
        cvs = []
        for s in surfaces:
            seeds_s = [sd for sd in seeds if (s, sd) in cell]
            nst = n_star_interp({sd: cell[(s, sd)] for sd in seeds_s}, ns, tau)
            cv, _ = logspread(list(nst.values()))
            cvs.append(cv)
            row[s] = cv
        rp, np_ = [], []
        for s in surfaces:
            seeds_s = [sd for sd in seeds if (s, sd) in cell]
            for n in ns:
                accs = [cell[(s, sd)][n] for sd in seeds_s if n in cell[(s, sd)]]
                if accs:
                    (rp if s in REAL_SURFACES else np_).append(
                        sum(1 for a in accs if a >= tau) / len(accs))
        row["real_mean_p"] = mean(rp)
        row["null_mean_p"] = mean(np_)
        row["family_delta"] = mean(rp) - mean(np_)
        sweep.append(row)
    R["tau_sweep"] = sweep

    with open(os.path.join(RES, "DISTRIB.json"), "w") as fh:
        json.dump(R, fh, indent=1, ensure_ascii=False, default=str)

    # ---------------------------------------------------------------- Markdown
    L = []
    L.append("# 分布化阈值估计（替代点估计 n*）\n")
    L.append(f"判据 τ={TAU}；n 网格 {ns}；种子 {seeds}；"
             f"每格 {len(seeds)} 个种子。数据：S2L 拉丁方 id 配平表面轴，{len(rows)} runs。\n")

    L.append("\n## 表 1　各表面的突破概率 P(acc≥τ | n)\n")
    hdr = "| 表面 | " + " | ".join(f"n={n}" for n in ns) + " | n* 的 CV(log) | 未突破种子 |"
    L.append(hdr)
    L.append("|" + "---|" * (len(ns) + 3))
    for s in surfaces:
        c = R["breakthrough"][s]["curve"]
        cells = []
        for row in c:
            cells.append(f"{row['p_hat']:.2f} [{row['lo']:.2f},{row['hi']:.2f}]")
        st = R["n_star"][s]
        L.append(f"| {s} | " + " | ".join(cells) +
                 f" | {st['cv_log']:.4f} | {st['censored']}/{st['n_cells']} |")

    L.append("\nWilson 95% 区间。k/m 与 p̂ 一致（种子数少时区间很宽，这本身是信息）。\n")

    L.append("\n## 表 2　真实表面族 vs null 对照族的分布重叠度\n")
    fv = R["family"]["real_vs_null"]
    L.append(f"- Cliff's δ = **{fv['cliffs_delta']:+.4f}**（0 = 完全重叠，±1 = 完全分离）")
    L.append(f"- Wasserstein-1 = **{fv['wasserstein1']:.4f}**（概率尺度上的族间平均绝对差）")
    L.append("\n| n | 真实 6 面的 p̂ | null 2 臂的 p̂ | Δ(p̂) | Cliff's δ |")
    L.append("|---|---|---|---|---|")
    for row in R["family"]["per_n"]:
        L.append(f"| {row['n']} | {mean(row['real_p']):.3f} | {mean(row['null_p']):.3f} "
                 f"| {row['delta']:+.3f} | {row['cliffs_delta']:+.3f} |")

    L.append("\n## 表 3\u3000逐表面 vs null 的配对种子效应（**含无效配对，仅供对照**）\n")
    L.append("| 表面 | null | slot 奇偶 | 平均配对差 | Cliff's δ | 配对 t | p | 对数 | ρ | 方差缩减 1−ρ² |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for row in pair_rows:
        vr = row["var_reduction_1_minus_rho2"]
        L.append(f"| {row['surface']} | {row['null']} | {parity[row['surface']]} "
                 f"| {row['mean_diff']:+.4f} "
                 f"| {row['cliffs_delta']:+.3f} | {row['paired_t']:+.3f} "
                 f"| {row['p']:.3f} | {row['n_pairs']} "
                 f"| {row['rho_across_cells']:+.3f} "
                 f"| {('%+.3f' % vr) if vr is not None else 'n/a'} |")

    sa = R["slot_audit"]
    L.append(f"\n### 混淆审计：{sa['warning']}\n")
    L.append(f"种子 {sa['seeds']} 全为奇数，而 slot=(surface_index+seed) mod "
             f"{sa['n_surfaces']}，故 slot 奇偶性与表面下标奇偶性锁定：\n")
    for k, v in sorted(sa["groups"].items()):
        L.append(f"- {'奇' if k == '1' else '偶'} slot 组：{', '.join(v)}")
    L.append("\n跨奇偶的 real-vs-null 配对中 slot 效应无法剔除，**不应作解读**。"
             "只保留同奇偶的严格配对（slot 匹配）：\n")
    L.append("| 表面 | null | slot 奇偶 | 平均配对差 | Cliff's δ | 配对 t | p | 对数 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for row in R["paired_slot_matched"]:
        L.append(f"| {row['surface']} | {row['null']} | {row['slot_parity']} "
                 f"| {row['mean_diff']:+.4f} | {row['cliffs_delta']:+.3f} "
                 f"| {row['paired_t']:+.3f} | {row['p']:.3f} | {row['n_pairs']} |")

    L.append("\n### 方差分解（acc 的平方和分解，%）\n")
    L.append("| 子集 | 表面 | slot 奇偶 | n | 残差 | 表面（组内，扣除奇偶后） |")
    L.append("|---|---|---|---|---|---|")
    for k, v in R["variance"].items():
        L.append(f"| {k} | {v['pct_surface']:.2f}% | {v['pct_slot_parity']:.2f}% "
                 f"| {v['pct_n']:.2f}% | {v['pct_resid']:.2f}% "
                 f"| {100*v['eta2_surface_within_parity']:.2f}% |")
    pr = R["pairing"]
    L.append(f"\n配对 vs 非配对的差值方差：配对 **{pr['var_paired']:.5f}**，"
             f"非配对 **{pr['var_unpaired']:.5f}**，比值 **{pr['ratio']:.3f}**"
             f"（{pr['n_pairs_of_cells']} 对条件）。\n")

    L.append("\n## 表 4　判据 τ 扫描下的稳健性\n")
    L.append("| τ | " + " | ".join(surfaces) + " | 真实族平均 p̂ | null 族平均 p̂ | Δ |")
    L.append("|" + "---|" * (len(surfaces) + 4))
    for row in R["tau_sweep"]:
        L.append(f"| {row['tau']:.2f} | "
                 + " | ".join(f"{row[s]:.3f}" if row.get(s) == row.get(s) else "—"
                              for s in surfaces)
                 + f" | {row['real_mean_p']:.3f} | {row['null_mean_p']:.3f} "
                   f"| {row['family_delta']:+.3f} |")

    md = "\n".join(L) + "\n"
    with open(os.path.join(RES, "DISTRIB.md"), "w") as fh:
        fh.write(md)

    # ---------------------------------------------------------------- 控制台
    print("=" * 72)
    print("[1] 突破概率曲线（k/m，Wilson 95%）")
    for s in surfaces:
        c = R["breakthrough"][s]["curve"]
        txt = "  ".join(f"{r['p_hat']:.2f}" for r in c)
        print(f"  {s:9s} p̂(n) = {txt}")
    print("\n[2] n* 的 CV(log)  —— 旧点估计口径，保留对照")
    pool = R["n_star"]["_pooled"]
    for s in surfaces:
        st = R["n_star"][s]
        print(f"  {s:9s} CV(log n*) = {st['cv_log']:.4f}   "
              f"突破 {st['n_breached']}/{st['n_cells']}，删失 {st['censored']}")
    print(f"  真实 6 面均值 = {pool['real_cv_mean']:.4f}")
    print(f"  null 2 臂均值 = {pool['null_cv_mean']:.4f}")
    print(f"  论文原报值（8 面合并 CV(log)）≈ 0.0110 —— 见下方核对说明")

    print("\n[3] 分布族重叠度")
    print(f"  Cliff's δ  = {fv['cliffs_delta']:+.4f}")
    print(f"  W1         = {fv['wasserstein1']:.4f}")

    print("\n[4] 逐表面 vs null 配对差")
    print("\n[3b] ★ 混淆审计（slot 奇偶性）")
    sa = R["slot_audit"]
    print(f"  check_parity 通过? {sa['parity_ok']}  ({sa['n_seeds']} 种子 / "
          f"{sa['n_surfaces']} 表面)")
    if sa["warning"]:
        print(f"  !! {sa['warning']}")
    for k, v in sorted(sa["groups"].items()):
        print(f"     {'奇' if k=='1' else '偶'} slot 组: {', '.join(v)}")
    print("  跨奇偶配对无效，以下仅列同奇偶（slot 匹配）的严格配对：")
    for row in R["paired_slot_matched"]:
        print(f"    {row['surface']:5s} vs {row['null']:8s} "
              f"Δ={row['mean_diff']:+.4f} δ={row['cliffs_delta']:+.3f} "
              f"p={row['p']:.3f} n={row['n_pairs']}")

    print("\n[3c] 方差分解（%）")
    for k, v in R["variance"].items():
        print(f"  {k:10s} 表面 {v['pct_surface']:5.2f}%  奇偶 {v['pct_slot_parity']:5.2f}%"
              f"  n {v['pct_n']:5.2f}%  残差 {v['pct_resid']:5.2f}%"
              f"  表面(组内) {100*v['eta2_surface_within_parity']:5.2f}%")
        print(f"  {row['surface']:5s} vs {row['null']:8s} Δ={row['mean_diff']:+.4f} "
              f"δ={row['cliffs_delta']:+.3f} p={row['p']:.3f} n={row['n_pairs']}")

    print("\n[5] 配对种子方差缩减")
    print(f"  Var(paired)={pr['var_paired']:.5f}  Var(unpaired)={pr['var_unpaired']:.5f}  "
          f"ratio={pr['ratio']:.3f}")

    print("\n[6] τ 扫描")
    for row in R["tau_sweep"]:
        print(f"  τ={row['tau']:.2f}  real p̂={row['real_mean_p']:.3f}  "
              f"null p̂={row['null_mean_p']:.3f}  Δ={row['family_delta']:+.3f}")

    print("\n写出：" + os.path.join(RES, "DISTRIB.json"))
    print("写出：" + os.path.join(RES, "DISTRIB.md"))


if __name__ == "__main__":
    main()