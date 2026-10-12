"""
analyze_e6x_dpx.py — E6X 与 DPX 在全量数据（216/216、432/432）上的分析。

=====================================================================

两个实验各自补什么洞
--------------------
E6X（臂 K 复杂度轴扩展到 n=14000）
    原E6 网格上界 6500，en 在 mult=2/3 有 4/6 种子的阈值压在 6500 上，
    即**右删失**——阈值不是"大"，是"没测出来"。E6X 把上界推到 14000，
    阈值才可测。本脚本报告三件事：
      1. 删失是否真的解除（阈值脱离网格上界的比例）
      2. 关系种类数mult 的主效应（这是E6 原本的问题）
      3. 两个 null臂在 mult 上是否也免费——即"平坦"是关于结构的，
         还是关于"这些符号系统同样难"

DPX（depth × n 交叉）
    E4 得到的结论是 penalty 不随 depth 上升，但 depth 与 n 在原网格上
    完全纠缠，无法判断这是"与 depth 无关"还是"depth 变化被 n 变化掩盖"。
    DPX 让每个 depth 跑同一组 6 个 n，拆开共变。
    本脚本遵守 2026-10-06 定的四条硬规矩：配对优先、报右删失、
    给无删失读数（n½ / area）、写明网格分辨率。

读法
----
penalty = acc(TT) − acc(变换)，**同 seed 配对**。不用比均值、不用 z 分数。

用法
----
    python analyze_e6x_dpx.py
输出
----
    ../results/e6x_dpx_analysis.json
"""
import argparse
import collections
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
RES = os.path.join(PKG, "results")

# ---- 网格 ----
E6_MULTS = [2, 3, 4]
E6_SURFS = ["en", "relperm", "entperm"]
E6_ORIG_NS = [2000, 3000, 4000, 5000, 6500]
E6_EXT_NS = [6500, 8500, 11000, 14000]
E6_SEEDS = list(range(6))

DC_N = [4000, 5000, 6500, 8500, 11000, 14000]
DC_DEPTHS = [3, 4, 5]
DC_CELLS = ["TT", "TU", "Thighovl", "Tlowovl"]
DC_SEEDS = list(range(6))

TAU = 0.60
N_PERM = 20000
RNG = np.random.default_rng(20261006)

# 天花板阈值：acc >= 此值视为"已学会"，该格点对penalty 无信息量。
# 为什么必须显式剔除而不只看均值：
#   Thighovl 在 depth3/n>=6500 上逐 seed 配对差几乎全是 +0.0000
#   （TT 与 Thighovl 都饱和到 1.0），只有 1/6 个种子非零。
#   把这些0 与少数非零值一起平均，得到的"depth 斜率"完全由
#   少数几个未饱和的格点驱动 —— CI 会不含0 而p 检验给不出显著，
#   两者矛盾正是这个原因。剔除后重算是唯一稳妥的口径。
CEILING = 0.99


# ----------------------------------------------------------------- loading
def load_all(paths):
    recs = []
    for p in paths:
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            a = r.get("acc")
            if a is None or a != a or "error" in r:
                continue
            recs.append(r)
    return recs


def build_e6x(recs):
    """{mult: {surface: {(n, seed): acc}}}"""
    g = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in recs:
        if r.get("arm") != "K_null":
            continue
        n = r.get("n_train")
        m, sf, sd = r.get("mult"), r.get("surface"), r.get("seed")
        if m not in E6_MULTS or sf not in E6_SURFS or sd not in E6_SEEDS:
            continue
        if n not in E6_ORIG_NS and n not in E6_EXT_NS:
            continue
        g[m][sf][(n, sd)] = float(r["acc"])
    return g


def build_dpx(recs):
    """{(cell, depth, n): {seed: acc}}"""
    g = collections.defaultdict(dict)
    for r in recs:
        if r.get("arm") not in ("depth_scan", "depth_cross"):
            continue
        n, d, sd = r.get("n_train"), r.get("depth"), r.get("seed")
        c = r.get("test_kind") or r.get("cell")
        if n not in DC_N or d not in DC_DEPTHS or sd not in DC_SEEDS:
            continue
        if c not in DC_CELLS:
            continue
        g[(c, d, n)][sd] = float(r["acc"])
    return g


# --------------------------------------------------------------- 统计工具
def boot_mean(v, B=4000, seed=0):
    if len(v) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(B)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def sign_flip_p(diffs, n_perm=N_PERM):
    """配对差的符号翻转检验：对 0 中心的精确随机化检验。"""
    a = np.asarray(diffs, dtype=float)
    if a.size == 0:
        return float("nan"), float("nan")
    obs = abs(float(a.mean()))
    rng = np.random.default_rng(7)
    signs = rng.choice([-1.0, 1.0], size=(n_perm, a.size))
    nulls = np.abs((signs * a).mean(axis=1))
    p = (int(np.sum(nulls >= obs - 1e-12)) + 1) / (n_perm + 1)
    return float(a.mean()), p


def threshold(ns, means, crit=TAU):
    """acc 在 log n 上线性插值求越界点；不跨则 nan（右删失）。"""
    ns = sorted(ns)
    for i, n in enumerate(ns):
        if means[i] >= crit:
            if i == 0:
                return float(n)
            n0, n1, m0, m1 = ns[i - 1], ns[i], means[i - 1], means[i]
            if m1 == m0:
                return float(n)
            t = (crit - m0) / (m1 - m0)
            return float(np.exp(np.log(n0) + t * (np.log(n1) - np.log(n0))))
    return float("nan")


def seed_thr(g, mult, sf, crit=TAU):
    """{seed: 阈值}，跨过判据的种子；未跨的seed 不产出条目。"""
    by = collections.defaultdict(dict)
    for (n, sd), a in g[mult][sf].items():
        by[sd][n] = a
    out = {}
    for sd, d in by.items():
        nsl = sorted(d)
        t = threshold(nsl, [d[n] for n in nsl], crit)
        if not np.isnan(t):
            out[sd] = t
    return out


def n_half(curve):
    """达到 acc=0.5 的最小 n；未达返回 None。无删失读数。"""
    for n in sorted(curve):
        if curve[n] >= 0.5:
            return n
    return None


def area(curve):
    """acc 对 log n 的梯形积分（均值化），越小越难。无删失读数。"""
    ns = sorted(n for n in curve if isinstance(n, int) and n > 0)
    if len(ns) < 2:
        return None
    xs, ys = [math_log(n) for n in ns], [curve[n] for n in ns]
    s = 0.0
    for i in range(len(xs) - 1):
        s += (ys[i] + ys[i + 1]) / 2 * (xs[i + 1] - xs[i])
    return s / (xs[-1] - xs[0])


def math_log(x):
    import math
    return math.log(x)


def paired_penalty(g, base_cell, cell, ceiling=None):
    """同 seed 配对的 penalty，按 depth × n。

    ceiling 不为 None 时，只保留**未饱和**的格点：TT 与cell 的
    acc 都< ceiling。饱和格点的配对差恒为 0，是天花板而非"无差异"，
    混进均值会把depth 斜率压向0 或被少数未饱和格点绑架。
    """
    out = {}
    for d in DC_DEPTHS:
        for n in DC_N:
            b = g.get((base_cell, d, n))
            c = g.get((cell, d, n))
            if not b or not c:
                continue
            seeds = sorted(set(b) & set(c))
            if not seeds:
                continue
            if ceiling is not None:
                seeds = [s for s in seeds
                         if b[s] < ceiling and c[s] < ceiling]
                if not seeds:
                    continue
            diffs = [b[s] - c[s] for s in seeds]
            out[(d, n)] = {"diffs": diffs, "seeds": seeds,
                           "mean": float(np.mean(diffs)),
                           "all_pos": all(x > 0 for x in diffs)}
    return out


# ==================================================================== E6X
def analyze_e6x(g, out):
    print("=" * 76)
    print("E6X  臂 K 复杂度轴扩展到 n=14000（原上界 6500）")
    print("=" * 76)
    filled = sum(len(sd) for m in g.values() for sd in m.values())
    # E6X 的定义网格只含扩展 n；但 build_e6x 同时收了原网格
    # （判别式按 n 是否属于 E6_EXT_NS 划分，两网格仅在 n=6500 上共享）。
    # 分开报，否则 "432/216" 会被误读成超网格。
    filled_ext = sum(len([k for k in sd if k[0] in E6_EXT_NS])
                     for m in g.values() for sd in m.values())
    grid = len(E6_MULTS) * len(E6_SURFS) * len(E6_EXT_NS) * len(E6_SEEDS)
    print(f"  扩展网格格点 {filled_ext}/{grid}")
    print(f"  （另含原 E6 网格 {filled - filled_ext} 条，两网格仅在 n=6500 共享）")
    ext_accs = [a for m in g.values() for sf in m.values()
                for (n, _sd), a in sf.items() if n in E6_EXT_NS]
    sat = sum(1 for a in ext_accs if a >= CEILING)
    print(f"  扩展网格 acc >= {CEILING}（天花板）：{sat}/{len(ext_accs)}"
          f" = {100 * sat / len(ext_accs):.1f}%")

    # ---- 1. acc 均值表 ----
    print()
    print("-" * 76)
    print("1. acc 均值（mult × surface × n，6 seeds）")
    print("-" * 76)
    alln = sorted({n for m in g for s in g[m] for n, _ in g[m][s]})
    print("  mult".ljust(6) + "surface".ljust(10)
          + "".join(f"{n:>9}" for n in alln))
    for m in E6_MULTS:
        for sf in E6_SURFS:
            row = f"  {m:<6}{sf:<10}"
            for n in alln:
                v = [a for (nn, _sd), a in g[m][sf].items() if nn == n]
                row += f"{np.mean(v):>9.4f}" if v else f"{'.':>9}"
            print(row)

    # ---- 2. 删失诊断：阈值是否脱离网格上界 ----
    print()
    print("-" * 76)
    print(f"2. 右删失诊断（tau={TAU}）：阈值是否越过 n 上界 {max(alln)}")
    print("-" * 76)
    print(f"  {'mult':>5} {'surface':>9} {'可测种子':>9} {'删失种子':>9} "
          f"{'几何均值阈值':>12}  备注")
    censor_tbl = {}
    for m in E6_MULTS:
        for sf in E6_SURFS:
            bs = collections.defaultdict(dict)
            for (n, sd), a in g[m][sf].items():
                bs[sd][n] = a
            nmeas = ncens = 0
            tvals = []
            for sd, d in bs.items():
                nsl = sorted(d)
                if not nsl:
                    continue
                # 判删失：该 seed 在最大 n 档仍未达 tau
                if max(d[nsl[-1]] for n in nsl) < TAU and \
                        max(d.values()) < TAU:
                    ncens += 1
                    continue
                t = threshold(nsl, [d[n] for n in nsl], TAU)
                if not np.isnan(t):
                    tvals.append(t)
                    nmeas += 1
                else:
                    ncens += 1
            gm = float(np.exp(np.mean(np.log(tvals)))) if tvals else float("nan")
            note = ""
            if nmeas == 0:
                note = "全部删失（阈值 > n 上界）"
            elif ncens == 0:
                note = "删失已解除"
            censor_tbl[f"{m}|{sf}"] = {"n_measured": nmeas, "n_censored": ncens,
                                       "geomean_threshold": gm}
            print(f"  {m:>5} {sf:>9} {nmeas:>9} {ncens:>9} "
                  f"{('%.0f' % gm) if tvals else '----':>12}  {note}")
    print()
    print("  「可测种子」= 在 n 网格内跨过 tau 的种子数。删失种子不是 0，")
    print("  是阈值大于网格上界——补上界正是 E6X 存在的理由。")

    # ---- 3. mult 主效应 ----
    print()
    print("-" * 76)
    print("3. mult（关系种类数）的主效应 —— E6 原本要回答的问题")
    print("-" * 76)
    print("  注意：mult 的轴是**关系种类数**，不是 E10 的 C_eff。两者不可混称。")
    for n in alln:
        line = f"  n={n:>6}  "
        vals = {}
        for m in E6_MULTS:
            v = [a for sf in E6_SURFS for (nn, _sd), a in g[m][sf].items()
                 if nn == n]
            if v:
                vals[m] = float(np.mean(v))
        if len(vals) < 2:
            print(line + "数据不足")
            continue
        line += "  ".join(f"mult={m}:{vals[m]:.4f}" for m in sorted(vals))
        # 相邻 mult 的配对差（同 surface 同 n 同 seed）
        ms = sorted(vals)
        for a, b in zip(ms, ms[1:]):
            diffs = []
            for sf in E6_SURFS:
                ka = {(n2, sd): v for (n2, sd), v in g[a][sf].items() if n2 == n}
                kb = {(n2, sd): v for (n2, sd), v in g[b][sf].items() if n2 == n}
                for k in set(ka) & set(kb):
                    diffs.append(ka[k] - kb[k])
            if len(diffs) >= 2:
                dm, p = sign_flip_p(diffs)
                lo, hi = boot_mean(diffs)
                line += f"   Δ({b}-{a})={dm:+.4f} p={p:.3f}"
        print(line)
    print()
    print("  Δ 的符号：mult 越大 acc 越低则Δ>0 反之。p 为配对符号翻转检验。")

    # ---- 4. null 臂在 mult 上是否也免费 ----
    print()
    print("-" * 76)
    print("4. null 臂 vs en：符号置换在复杂度轴上是否零代价")
    print("-" * 76)
    print(f"  {'mult':>5} {'n':>7}  {'relperm-en':>12} {'p':>7}  "
          f"{'entperm-en':>12} {'p':>7}")
    null_tbl = {}
    for m in E6_MULTS:
        for n in alln:
            line = f"  {m:>5} {n:>7} "
            rec = {}
            for na in ("relperm", "entperm"):
                ka = {(nn, sd): v for (nn, sd), v in g[m]["en"].items()
                      if nn == n}
                kb = {(nn, sd): v for (nn, sd), v in g[m][na].items()
                      if nn == n}
                diffs = [ka[k] - kb[k] for k in set(ka) & set(kb)]
                if len(diffs) < 2:
                    line += f"{'----':>12} {'----':>7} "
                    continue
                dm, p = sign_flip_p(diffs)
                rec[na] = {"mean": dm, "p": p, "n": len(diffs)}
                line += f"{dm:>+12.4f} {p:>7.3f} "
            if rec:
                null_tbl[f"{m}|{n}"] = rec
            print(line)
    print()
    print("  这是 §8 边界四的直接检验：若两个置换臂在各mult 上都与 en")
    print("  不可区分，则复杂度轴上的平坦是**关于结构**的陈述。")

    out["e6x"] = {
        "grid_filled_ext": filled_ext, "grid_total_ext": grid,
        "grid_filled_all": filled,
        "ceiling_frac_ext": sat / len(ext_accs) if ext_accs else None,
        "censor": censor_tbl,
        "null_vs_en": null_tbl,
    }
    return censor_tbl, null_tbl


# ==================================================================== DPX
def analyze_dpx(g, out):
    print()
    print("=" * 76)
    print("DPX  depth × n 交叉（拆开 E4 里 depth 与 n 的共变）")
    print("=" * 76)
    grid = len(DC_DEPTHS) * len(DC_CELLS) * len(DC_N) * len(DC_SEEDS)
    filled = sum(len(v) for v in g.values())
    print(f"  格点 {filled}/{grid}")
    print(f"  网格分辨率：每个 depth 都跑满同一组 {len(DC_N)} 个 n "
          f"× {len(DC_CELLS)} cells × {len(DC_SEEDS)} seeds")

    # ---- 1. TT 基线曲线 ----
    print()
    print("-" * 76)
    print("1. TT 基线 acc 随 (depth, n) —— 纠缠被拆开后的样子")
    print("-" * 76)
    print("  depth".ljust(8) + "".join(f"{n:>9}" for n in DC_N))
    tt_curve = {}
    for d in DC_DEPTHS:
        row = f"  {d:<6}"
        cur = {}
        for n in DC_N:
            v = g.get(("TT", d, n))
            if v:
                cur[n] = float(np.mean(list(v.values())))
                row += f"{cur[n]:>9.4f}"
            else:
                row += f"{'.':>9}"
        tt_curve[d] = cur
        print(row)
    print()
    print("  无删失读数（不受 tau 判据影响）：")
    for d in DC_DEPTHS:
        cur = tt_curve[d]
        nh = n_half(cur)
        ar = area(cur)
        print(f"    depth{d}: n@0.5 = {'未达' if nh is None else nh}"
              f"   area = {'NA' if ar is None else f'{ar:.4f}'}"
              f"   末档acc = {cur.get(max(DC_N), float('nan')):.4f}")

    # ---- 2. 配对penalty ----
    print()
    print("-" * 76)
    print("2. 配对 penalty = acc(TT) − acc(cell)，逐 (depth, n)")
    print("   同 seed 配对；* 表示该格全部配对差为正")
    print("-" * 76)
    pen_all = {}
    for cell in DC_CELLS:
        if cell == "TT":
            continue
        pen = paired_penalty(g, "TT", cell)
        pen_all[cell] = pen
        print(f"\n  [{cell}]")
        print("    depth".ljust(8) + "".join(f"{n:>11}" for n in DC_N))
        for d in DC_DEPTHS:
            row = f"    {d:<6}"
            for n in DC_N:
                p = pen.get((d, n))
                if not p:
                    row += f"{'.':>11}"
                    continue
                row += f"{p['mean']:>10.4f}" + ("*" if p["all_pos"] else " ")
            print(row)
        # 每 depth 的平均 penalty
        byd = collections.defaultdict(list)
        for (d, n), p in pen.items():
            byd[d].append(p["mean"])
        print("每档 depth 平均 penalty: "
              + "  ".join(f"d{d}:{np.mean(byd[d]):+.4f}(n={len(byd[d])})"
                          for d in sorted(byd)))

    # ---- 2b. 天花板诊断 ----
    print()
    print("-" * 76)
    print(f"2b. 天花板诊断（acc >= {CEILING} 视为已学会，该格 penalty 恒为 0）")
    print("-" * 76)
    print("    每格为「TT 基线饱和种子数 / 该格种子数」")
    print("    depth".ljust(8) + "".join(f"{n:>9}" for n in DC_N))
    tt_sat = {}
    for d in DC_DEPTHS:
        row = f"    {d:<6}"
        c = 0
        for n in DC_N:
            v = g.get(("TT", d, n))
            if v:
                k = sum(1 for a in v.values() if a >= CEILING)
                c += k
                row += f"{k:>4}/{len(v)}  "
            else:
                row += f"{'.':>9}"
        tt_sat[d] = c
        print(row)
    print()
    for cell in DC_CELLS:
        if cell == "TT":
            continue
        pen_nc = paired_penalty(g, "TT", cell, ceiling=CEILING)
        n_all = len(pen_all[cell])
        n_nc = len(pen_nc)
        print(f"    [{cell:>9}] 有效格点：全量 {n_all}/{len(DC_DEPTHS)*len(DC_N)}"
              f" -> 剔除天花板后 {n_nc}")
    print()
    print("    天花板格点的配对差是 0而非\"无差异\"。把它们计入均值会")
    print("    把斜率压向 0；剔除后样本变少，须同时看 p 值与 CI。")

    # ---- 3. depth 斜率：penalty 是否随 depth 上升 ----
    print()
    print("-" * 76)
    print("3. penalty 的 depth 斜率（这是 DPX 的核心问题）")
    print("   两个口径并列：全量 vs 剔除天花板")
    print("   CI 含 0 且 p > 0.10 = 与 depth 无关")
    print("-" * 76)
    slope_tbl = {}
    for cell in DC_CELLS:
        if cell == "TT":
            continue
        for tag, kw in (("全量", {}), ("剔天花板", {"ceiling": CEILING})):
            pen = paired_penalty(g, "TT", cell, **kw)
            byd = collections.defaultdict(dict)
            for (d, n), p in pen.items():
                for sd, dv in zip(p["seeds"], p["diffs"]):
                    byd[d].setdefault(sd, []).append(dv)
            per_seed = {d: {sd: float(np.mean(v)) for sd, v in byd[d].items()}
                        for d in byd}
            ds = sorted(per_seed)
            if len(ds) < 2:
                print(f"\n  [{cell}][{tag}] depth 档不足，无法估斜率")
                continue
            common = [sd for sd in per_seed[ds[0]] if sd in per_seed[ds[-1]]]
            if len(common) < 2:
                print(f"\n  [{cell}][{tag}] 首末档共同种子不足 2")
                continue
            diffs = [per_seed[ds[-1]][sd] - per_seed[ds[0]][sd] for sd in common]
            dm, p = sign_flip_p(diffs)
            lo, hi = boot_mean(diffs)
            nz = sum(1 for x in diffs if x != 0)
            flat = (lo <= 0 <= hi) and p > 0.10
            verdict = ("与 depth 无关（CI 含 0，p>0.10）" if flat else
                       ("随 depth 上升" if lo > 0 else
                        "随 depth 下降" if hi < 0 else
                        "CI 与 p 不一致（见下方说明）"))
            print(f"\n  [{cell}][{tag}]  d{ds[-1]} − d{ds[0]} = {dm:+.4f}  "
                  f"CI=[{lo:+.4f}, {hi:+.4f}]  p={p:.4f}  "
                  f"共同种子 {len(common)}（非零 {nz}）")
            print(f"-> {verdict}")
            slope_tbl[f"{cell}|{tag}"] = {
                "diff_max_minus_min": dm, "ci": [lo, hi], "p": p,
                "n_common_seeds": len(common), "n_nonzero": nz,
                "n_cells": len(pen), "verdict": verdict}
    print()
    print("  「CI 与 p 不一致」的典型形态：CI 由 bootstrap 百分位给出，")
    print("  在配对差大量为 0（天花板）时会偏窄；p 由符号翻转给出，")
    print("  0 值多时功效不足。两者不一致时应以剔天花板口径为准。")

    # ---- 4. n 方向：penalty 是否随 n 变化 ----
    print()
    print("-" * 76)
    print("4. penalty 的 n斜率（同一 depth 内，跨 n 档）")
    print("   这一栏回答：depth 效应是不是被 n 的共变掩盖的")
    print("   同样并列两个口径（末档 n=14000 几乎全饱和，故剔天花板后只剩 n=4000/5000）")
    print("-" * 76)
    nslope_tbl = {}
    for cell in DC_CELLS:
        if cell == "TT":
            continue
        for tag, kw in (("全量", {}), ("剔天花板", {"ceiling": CEILING})):
            pen = paired_penalty(g, "TT", cell, **kw)
            byn = collections.defaultdict(dict)
            for (d, n), p in pen.items():
                for sd, dv in zip(p["seeds"], p["diffs"]):
                    byn[n].setdefault(sd, []).append(dv)
            per_seed = {n: {sd: float(np.mean(v)) for sd, v in byn[n].items()}
                        for n in byn}
            ns_ = sorted(per_seed)
            if len(ns_) < 2:
                continue
            common = [sd for sd in per_seed[ns_[0]] if sd in per_seed[ns_[-1]]]
            if len(common) < 2:
                continue
            diffs = [per_seed[ns_[-1]][sd] - per_seed[ns_[0]][sd]
                     for sd in common]
            dm, p = sign_flip_p(diffs)
            lo, hi = boot_mean(diffs)
            flat = (lo <= 0 <= hi) and p > 0.10
            verdict = ("与 n 无关（CI 含 0，p>0.10）" if flat else
                       ("随 n 上升" if lo > 0 else
                        "随 n 下降" if hi < 0 else "CI 与 p 不一致"))
            print(f"  [{cell:>9}][{tag:>10}]  n={ns_[0]} → n={ns_[-1]}:  "
                  f"Δ={dm:+.4f}  CI=[{lo:+.4f}, {hi:+.4f}]  p={p:.4f}  "
                  f"共同种子 {len(common)}")
            print(f"      -> {verdict}")
            nslope_tbl[f"{cell}|{tag}"] = {
                "diff_max_minus_min": dm, "ci": [lo, hi], "p": p,
                "n_common_seeds": len(common), "verdict": verdict}

    out["dpx"] = {
        "grid_filled": filled, "grid_total": grid,
        "ceiling_threshold": CEILING,
        "tt_curves": {str(d): tt_curve[d] for d in DC_DEPTHS},
        "tt_saturated_cells": {str(d): tt_sat[d] for d in DC_DEPTHS},
        "penalty_by_cell": {c: {f"{d}|{n}": v["mean"]
                                for (d, n), v in p.items()}
                            for c, p in pen_all.items()},
        "depth_slope": slope_tbl,
        "n_slope": nslope_tbl,
    }
    return slope_tbl, nslope_tbl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--out", default=os.path.join(RES, "e6x_dpx_analysis.json"))
    args = ap.parse_args()

    paths = args.files
    if not paths:
        paths = (sorted(glob.glob(os.path.join(RES, "*.jsonl")))
                 + sorted(glob.glob(os.path.join(RES, "from_4core", "*.jsonl")))
                 + sorted(glob.glob(os.path.join(RES, "from_library", "*.jsonl"))))
    recs = load_all(paths)
    print(f"载入 {len(paths)} 文件 / {len(recs)} 条有效记录\n")

    g6 = build_e6x(recs)
    gx = build_dpx(recs)
    out = {"inputs": len(paths), "n_records": len(recs)}

    analyze_e6x(g6, out)
    analyze_dpx(gx, out)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print()
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()