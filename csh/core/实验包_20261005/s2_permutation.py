"""
s2_permutation.py — E5：把 S2 从"集合包含"改成置换检验

对应判别书 §6（E5），但**修正其前提**。
=====================================================================

判别书原文说这是「20 分钟纯分析，零新 run」。这句话在修复前的
`results/final.jsonl` 上是错的：实测

    en / relperm / entperm 三者在 30/30 格点上逐位相同
    zh / math / alien          三者在 30/30 格点上逐位相同

置换检验的统计量是「null 阈值 − mean(6 真实表面) / sd(6 真实表面)」。
当 null 组内部方差为 0（因为 null 与 en 是同一个数），任何重排都
不改变统计量，**p 值恒等于 1.0**。这不是"检验通过"，是"检验无法
进行"。判别书若照跑，会得到一个看起来漂亮、实则空洞的结论。

本脚本的处理策略
----------------
1. **先做退化检测**，逐对报告"逐位相同"的比例。
2. 检测到退化时**拒绝输出 p 值**，并指明需要哪个数据集。
3. 对未退化的配对照常计算。

因此本脚本可以在修复前数据上运行（给出退化诊断），
也可以在 `results/surface_fix.jsonl` 跑满后运行（给出真p 值）。

用法
----
    python s2_permutation.py                              # 默认诊断 final.jsonl
    python s2_permutation.py results/surface_fix.jsonl   # 修复后数据
    python s2_permutation.py results/final.jsonl results/surface_fix.jsonl  # 对比

输出
----
    results/s2_permutation.json     机器可读
    stdout                人读表
"""

import itertools
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

REAL_SURFACES = ["zh", "en", "lisp", "math", "code", "alien"]
NULL_ARMS = ["relperm", "entperm"]
TAUS = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
N_PERM = 10000
SEED = 0


# ----------------------------------------------------------------- loading
def load(paths):
    rows = []
    for p in paths:
        if not os.path.exists(p):
            print(f"  [skip] {p} (not found)")
            continue
        n0 = len(rows)
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("acc") is None or r["acc"] != r["acc"]:
                    continue
                if "error" in r:
                    continue
                # 臂 S 的判据：mult==1 且 n_rel==6
                if r.get("mult") == 1 or r.get("n_rel") == 6:
                    rows.append(r)
        print(f"  [ok]   {p}: +{len(rows)-n0} runs")
    return rows


# ---------------------------------------------------- threshold (同原口径)
def threshold(ns, means, crit):
    """与 analysis.threshold 完全一致：log n 线性插值。"""
    ns = sorted(ns)
    for i, n in enumerate(ns):
        if means[i] >= crit:
            if i == 0:
                return float(n)
            n0, n1 = ns[i - 1], ns[i]
            m0, m1 = means[i - 1], means[i]
            if m1 == m0:
                return float(n)
            t = (crit - m0) / (m1 - m0)
            return float(np.exp(np.log(n0) + t * (np.log(n1) - np.log(n0))))
    return float("nan")


def seed_thresholds(rows, crit):
    """{surface: [每个 seed 的阈值]} —— 与 _seed_thr 同口径。

    只要求最大 n 档跨过判据。逐 seed 跨过的比例另行报告（crossed/N），
    不用来筛掉「低 n 档未涌现」的种子。
    """
    cells = _acc_cells(rows, crit)
    ns = ns_of(rows)
    out = defaultdict(list)
    for s in cells:
        out[s] = [t for _sd, t in _seed_thr(cells, s, crit, ns)]
    return out


def boot_mean(v, n=4000, seed=0):
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def ns_of(rows):
    return sorted({r["n_train"] for r in rows})


# ------------------------------------------------------------ degeneration
def degeneracy_report(rows):
    """逐对报告逐位相同格点数。这是判别书遗漏的前置检查。"""
    cell = {}
    for r in rows:
        cell[(r["surface"], r["n_train"], r["seed"])] = r["acc"]
    ns = sorted({r["n_train"] for r in rows})
    seeds = sorted({r["seed"] for r in rows})
    N = len(ns) * len(seeds)
    names = sorted({r["surface"] for r in rows})

    out = {}
    print()
    print("=" * 74)
    print("STEP 1  DEGENERACY CHECK  （置换检验的前置条件）")
    print("=" * 74)
    print(f"  grid = {len(ns)} n-values x {len(seeds)} seeds = {N} cells")
    print()
    degen = []
    for a, b in itertools.combinations(names, 2):
        same = sum(1 for n in ns for sd in seeds
                   if cell.get((a, n, sd)) is not None
                   and cell.get((b, n, sd)) is not None
                   and cell[(a, n, sd)] == cell[(b, n, sd)])
        frac = same / N
        out[f"{a}|{b}"] = {"identical_cells": same, "total": N, "frac": frac}
        if same == N:
            degen.append((a, b))
    if degen:
        print("  完全退化的配对（全部格点逐位相同）：")
        for a, b in degen:
            print(f"    !! {a:>8} == {b:<8}  {N}/{N}")
        print()
        print("  >> 置换检验在这些配对上无法进行：统计量的重排分布退化为一点，")
        print("     p 值恒等于 1.0。这是**检验无法进行**，不是**检验通过**。")
    else:
        print("  无完全退化的配对 —— 置换检验可以正常进行。")
    print()
    return out, degen, N


# ---------------------------------------------------------- permutation
def _acc_cells(rows, crit):
    """{surface: {(n, seed): acc}}"""
    out = defaultdict(dict)
    for r in rows:
        out[r["surface"]][(r["n_train"], r["seed"])] = r["acc"]
    return out


def _seed_thr(cells, surface, crit, ns):
    """某表面逐 seed 的阈值序列（与 analysis.threshold 同口径）。

    只要求该seed 在**最大 n 档**跨过判据即可估阈值——插值只需要
    越界点与它前一档。若要求全部 n 档都有阈值，会把「低 n 档种子
    尚未涌现」误判成「阈值未定义」，而那恰恰是阈值偏高的表现。
    """
    by = defaultdict(dict)
    for (n, sd), a in cells[surface].items():
        by[sd][n] = a
    vals = []
    nmax = max(ns)
    for sd in sorted(by):
        d = by[sd]
        if nmax not in d:
            continue
        nsl = sorted(d)
        t = threshold(nsl, [d[n] for n in nsl], crit)
        if not np.isnan(t):
            vals.append((sd, t))
    return vals


def paired_diff(rows, crit, null_arm, ns):
    """逐 seed 配对差：null 阈值 − 六真实表面阈值的均值。

    按论文 §11 第 2 条「跨臂比较必须用同 seed 同 n 的逐点差」。
    不用 z分数——六表面阈值几乎相同，sd(log) 极小（0.001 量级），
    z会被分母放大到数百，读起来像"极显著"却是分母伪影。
    """
    cells = _acc_cells(rows, crit)
    if null_arm not in cells:
        return None
    null_t = dict(_seed_thr(cells, null_arm, crit, ns))
    if not null_t:
        return None
    reals = {s: dict(_seed_thr(cells, s, crit, ns))
             for s in REAL_SURFACES if s in cells}
    reals = {s: d for s, d in reals.items() if d}
    if not reals:
        return None
    diffs = []
    for sd in sorted(null_t):
        vals = [d[sd] for d in reals.values() if sd in d]
        if len(vals) < 2:
            # 该 seed 下可用的真实表面不足 2 个——配对语义要求有对照组。
            # （不取全体 seed 交集：低 n 档常有表面未跨判据，交集会
            #   把样本量压到 1。）
            continue
        diffs.append(null_t[sd] - float(np.mean(vals)))
    if not diffs:
        return None
    return diffs


def stat_from_diffs(diffs):
    return float(np.mean(diffs)) if diffs else np.nan


def perm_test_paired(rows, crit, null_arm, ns, rng, n_perm=N_PERM):
    """标签重排置换检验，统计量 = 逐 seed 配对差的均值。

    H0: null臂的阈值与六个真实表面同分布（即符号置换零代价）。
    """
    d = paired_diff(rows, crit, null_arm, ns)
    if not d or len(d) < 2:
        return None
    obs = stat_from_diffs(d)

    # 置换池：六真实表面 + null 的逐 seed 阈值
    cells = _acc_cells(rows, crit)
    pool = {}
    for s in REAL_SURFACES + [null_arm]:
        if s in cells:
            t = dict(_seed_thr(cells, s, crit, ns))
            if t:
                pool[s] = t
    if null_arm not in pool or len(pool) < 3:
        return None
    arms = list(pool)
    nidx = arms.index(null_arm)
    # 逐 seed 配对：null 的每个可用 seed，配上**该 seed 下所有可用的真实表面**。
    # 不能取全体 seed 的交集——zh 在低 n 档常有种子未跨判据，交集会把
    # 样本量压到 1，检验直接失效。real_surfaces_at(seed) 给出该 seed
    # 下可用的真实表面名。
    seed_list = sorted(pool[null_arm])

    def reals_at(sd):
        return [a for a in arms if a != null_arm and sd in pool[a]]

    seed_list = [sd for sd in seed_list if len(reals_at(sd)) >= 2]
    if len(seed_list) < 2:
        return None

    count = 0
    for _ in range(n_perm):
        sh = rng.permutation(arms)
        fake_null = sh[nidx]
        vals = []
        for sd in seed_list:
            if sd not in pool[fake_null]:
                continue          # 该臂在此 seed 上无阈值（未跨判据）
            rs = [pool[a][sd] for a in sh
                  if a != fake_null and sd in pool[a]]
            if rs:
                vals.append(pool[fake_null][sd] - float(np.mean(rs)))
        v = stat_from_diffs(vals)
        if not np.isnan(v) and abs(v) >= abs(obs):
            count += 1
    p = (count + 1) / (n_perm + 1)
    lo, hi = boot_mean(d)
    return {"observed_diff": obs, "p_two_sided": p, "n_perm": n_perm,
            "n_seeds": len(d), "ci_lo": lo, "ci_hi": hi,
            "diffs": d, "degenerate": False}


# ------------------------------------------------------------------- main
def main():
    paths = sys.argv[1:] or [os.path.join(HERE, "..", "results", "final.jsonl")]
    print("=" * 74)
    print("E5  S2 PERMUTATION TEST  (with degeneracy guard)")
    print("=" * 74)
    print("inputs:")
    rows = load(paths)
    if not rows:
        print("no usable data")
        return

    degen_tbl, degen_pairs, N = degeneracy_report(rows)

    rng = np.random.default_rng(SEED)
    results = {}
    blocked = []

    print("=" * 74)
    print("STEP 2  PER-TEMPLATE THRESHOLDS")
    print("=" * 74)
    for tau in TAUS:
        st = seed_thresholds(rows, tau)
        line = f"  tau={tau:.2f} "
        for s in REAL_SURFACES + NULL_ARMS:
            v = st.get(s)
            if v:
                lo, hi = boot_mean(v)
                line += f"{s}={np.mean(v):6.0f} "
            else:
                line += f"{s}=  ----  "
        print(line)
        results[tau] = {s: (float(np.mean(st[s])) if st.get(s) else None)
                        for s in REAL_SURFACES + NULL_ARMS}
    print()
    print("  '----' = 该表面无seed 跨过判据（阈值未定义），不是 0")
    print()

    print("=" * 74)
    print("STEP 3  PERMUTATION TEST PER NULL ARM")
    print("=" * 74)
    for tau in TAUS:
        for null_arm in NULL_ARMS:
            # 该 null 是否与某个真实表面逐位相同？
            twin = None
            for rs in REAL_SURFACES:
                if f"{rs}|{null_arm}" in degen_tbl and \
                        degen_tbl[f"{rs}|{null_arm}"]["identical_cells"] == N:
                    twin = rs
            key = f"tau={tau:.2f}|{null_arm}"
            if twin:
                blocked.append((tau, null_arm, twin))
                print(f"  tau={tau:.2f}  {null_arm:>8}  SKIPPED — "
                      f"与 {twin} 逐位相同（退化），p 值无意义")
                continue
            r = perm_test_paired(rows, tau, null_arm, ns_of(rows), rng)
            if r is None:
                print(f"  tau={tau:.2f}  {null_arm:>8}  SKIPPED — "
                      f"阈值未定义或种子不足")
                continue
            verdict = "稳健 (p>0.10)" if r["p_two_sided"] > 0.10 else \
                      ("边缘" if r["p_two_sided"] > 0.05 else "显著")
            print(f"  tau={tau:.2f}  {null_arm:>8}  "
                  f"配对差={r['observed_diff']:+8.0f}  "
                  f"CI=[{r['ci_lo']:+.0f},{r['ci_hi']:+.0f}]  "
                  f"p={r['p_two_sided']:.4f}   {verdict}")
            results.setdefault("_perm", {})[key] = r
    print()

    print("=" * 74)
    print("VERDICT")
    print("=" * 74)
    if blocked:
        print(f"  * {len(blocked)} 个(判据, null) 组合因退化被跳过。")
        print("  * 结论：这份数据上S2 的置换检验**无法完成**。")
        print("  * 需要：results/surface_fix.jsonl 跑满 180 runs 后重跑本脚本。")
        print("  * 在那之前，不得把 S2 写成「通过统计检验」——")
        print("    那会是一个p 恒等于 1 的空洞结论。")
    else:
        ps = [v["p_two_sided"] for v in results.get("_perm", {}).values()]
        if ps and min(ps) > 0.10:
            print("  S2 在全部判据上稳健（p > 0.10）。可按判别书 §6.3升级为统计检验。")
        else:
            bad = [f"tau={k.split('|')[0][4:]} {k.split('|')[1]} p={v['p_two_sided']:.3f}"
                   for k, v in results.get("_perm", {}).items()
                   if v["p_two_sided"] <= 0.10]
            print("  S2 在部分判据上不稳健：")
            for b in bad:
                print("    " + b)
            print("  -> §6.2 结论应限定到通过的那些判据。")
    print()

    outp = os.path.join(HERE, "s2_permutation.json")
    with open(outp, "w", encoding="utf-8") as fh:
        json.dump({"inputs": paths, "n_cells": N,
                   "degenerate_pairs": degen_pairs,
                   "degeneracy": degen_tbl,
                   "blocked": blocked,
                   "results": {str(k): v for k, v in results.items()}},
                  fh, ensure_ascii=False, indent=2)
    print(f"  -> {outp}")


if __name__ == "__main__":
    main()