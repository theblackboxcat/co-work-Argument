"""
analyze_s2l.py — S2 在拉丁方配平 + 共享词表下的正式判定。

=====================================================================

这批数据解决什么
----------------
`03_S2置换检验结果.md` 末尾列了两条修正，两条都指向"必须重跑"：

  修正一：结论依赖于配对方式。与均值配对 7/7 不显著，与每个真实表面
         逐对配对则τ=0.55 上 relperm 显著（p=0.019）。=> 统计量形式
         必须预注册，否则结论是欠定的。
  修正二：null臂 vocab=225，真实表面 vocab=169。`Solver(len(vocab))`
         的参数量与随机初始化都由词表规模决定，配对差里混着规模差异。

S2L 重跑同时修掉两条：
  * 8 个表面（6 真实 + 2 null）进**同一个**词表，vocab 恒为 225；
  * `slot = (surface_index + seed) mod 8`，8 seeds 让每个表面恰好
    遍历全部 8 个 id 区间，表面主效应与 slot 噪声可分离。

因此本脚本把上一轮"两种配对方式给出不同结论"当作待检验对象，
而不是缺陷——**两种都报**，并检验它们是否真的不一致。

统计量（预注册，两个都报）
--------------------------
  A. 均值配对：d(seed) = thr(null, seed) − mean_s thr(surface_s, seed)
  B. 逐对配对：对每个真实表面 s 各得d_s(seed)，对 s 做符号置换

B 的多重比较：6 个真实表面 × 7 个 τ = 42 个检验。
按 Bonferroni 校正后的 α' = 0.05/42 = 1.19e-3，
并同时报 Benjamini-Hochberg 的 q 值（42 检验族）。

阈值口径
--------
沿用 `s2_permutation.threshold`：acc 在 log n 上线性插值求 τ 越界点。
只要求最大 n 档跨过 τ（低 n 档未涌现是"阈值偏高"，不是数据缺失）。

用法
----
    python analyze_s2l.py                # 用默认全量合并
    python analyze_s2l.py --files a.jsonl b.jsonl
输出
----
    ../results/s2l_analysis.json
"""
import argparse
import collections
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
RES = os.path.join(PKG, "results")

REAL_SURFACES = ["zh", "en", "lisp", "math", "code", "alien"]
NULL_ARMS = ["relperm", "entperm"]
ALL_SURFACES = REAL_SURFACES + NULL_ARMS
NS = [2000, 3000, 4000, 5000, 6500]
SEEDS = list(range(8))
TAUS = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
N_PERM = 10000
RNG_SEED = 20261006


# ----------------------------------------------------------------- loading
def load(paths):
    """只收arm=S2_latin 且落在网格内的记录，按业务键去重。"""
    cell = {}          # (surface, n, seed) -> acc
    meta = {}          # (surface, n, seed) -> {slot, vocab, tok}
    dup = 0
    nbad = 0
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
                nbad += 1
                continue
            if r.get("arm") != "S2_latin":
                continue
            a = r.get("acc")
            if a is None or a != a or "error" in r:
                nbad += 1
                continue
            sf, n, sd = r.get("surface"), r.get("n_train"), r.get("seed")
            if sf not in ALL_SURFACES or n not in NS or sd not in SEEDS:
                continue
            k = (sf, n, sd)
            if k in cell:
                dup += 1
            cell[k] = float(a)
            meta[k] = {"slot": r.get("block_slot"),
                       "vocab": r.get("vocab"), "tok": r.get("tok")}
    return cell, meta, dup, nbad


# ---------------------------------------------------------------- threshold
def threshold(ns, means, crit):
    """acc 在 log n 上线性插值求首次跨过 crit 的n（与 s2_permutation 同口径）。"""
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


def by_seed(cell, surface):
    """{seed: {n: acc}}"""
    out = collections.defaultdict(dict)
    for (sf, n, sd), a in cell.items():
        if sf == surface:
            out[sd][n] = a
    return out


def seed_thresholds(cell, surface, crit):
    """{seed: 阈值}；只要求最大 n 档跨过判据。"""
    bs = by_seed(cell, surface)
    out = {}
    nmax = max(NS)
    for sd, d in bs.items():
        if nmax not in d:
            continue
        nsl = sorted(d)
        t = threshold(nsl, [d[n] for n in nsl], crit)
        if not np.isnan(t):
            out[sd] = t
    return out


def boot_mean(v, n=4000, seed=0):
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


# ------------------------------------------------------- degeneracy check
def degeneracy_report(cell):
    """逐对报告逐位相同格点占比——S1 的教训：退化时 p 恒等于 1。"""
    N = len(NS) * len(SEEDS)
    out = {}
    degen = []
    for a, b in [(x, y) for i, x in enumerate(ALL_SURFACES)
                 for y in ALL_SURFACES[i + 1:]]:
        same = sum(1 for n in NS for sd in SEEDS
                   if (a, n, sd) in cell and (b, n, sd) in cell
                   and cell[(a, n, sd)] == cell[(b, n, sd)])
        frac = same / N
        out[f"{a}|{b}"] = {"identical": same, "total": N, "frac": frac}
        if same == N:
            degen.append((a, b))
    return out, degen, N


# ------------------------------------------------------ latin square check
def parity_report(meta):
    """核对拉丁方：每表面恰好遍历全部 8 个 slot。"""
    tbl = collections.defaultdict(dict)
    for (sf, n, sd), m in meta.items():
        if m.get("slot") is not None:
            tbl[sf][sd] = m["slot"]
    print()
    print("=" * 74)
    print("STEP 1  拉丁方配平核对（每表面是否恰好遍历全部 8 个slot）")
    print("=" * 74)
    print(f"  {'surface':>10}" + "".join(f"{'s' + str(s):>5}" for s in SEEDS))
    ok = True
    for sf in ALL_SURFACES:
        row = tbl.get(sf, {})
        cells = "".join(f"{row.get(sd, -1):>5}" for sd in SEEDS)
        full = sorted(row.values()) == list(range(len(ALL_SURFACES)))
        ok = ok and full
        print(f"  {sf:>10}{cells}   {'OK' if full else '不配平'}")
    print(f"\n  配平成立：{ok}")
    # slot 边际：每个 slot 上8 个表面各出现一次
    cnt = collections.Counter()
    for sf in ALL_SURFACES:
        for sd, sl in tbl.get(sf, {}).items():
            cnt[sl] += 1
    print(f"  slot 边际计数（应各为 8）：{dict(sorted(cnt.items()))}")
    return ok


# ---------------------------------------------------- permutation tests
def perm_mean_paired(pool, null_arm, rng, n_perm=N_PERM):
    """A. 与「真实表面均值」配对：标签重排，统计量 = 逐 seed 配对差均值。"""
    arms = [a for a in ALL_SURFACES if a in pool and pool[a]]
    if null_arm not in arms or len(arms) < 3:
        return None
    reals = [a for a in arms if a != null_arm]
    sds = [sd for sd in sorted(pool[null_arm])
           if sum(1 for a in reals if sd in pool[a]) >= 2]
    if len(sds) < 2:
        return None

    def stat(fake_null, seed_list):
        vals = []
        for sd in seed_list:
            if sd not in pool[fake_null]:
                continue
            rs = [pool[a][sd] for a in reals if sd in pool[a]]
            if rs:
                vals.append(pool[fake_null][sd] - float(np.mean(rs)))
        return float(np.mean(vals)) if vals else float("nan")

    obs = stat(null_arm, sds)
    if np.isnan(obs):
        return None
    count = 0
    for _ in range(n_perm):
        sh = list(rng.permutation(arms))
        v = stat(sh[0], sds)
        if not np.isnan(v) and abs(v) >= abs(obs):
            count += 1
    p = (count + 1) / (n_perm + 1)

    diffs = []
    for sd in sds:
        rs = [pool[a][sd] for a in reals if sd in pool[a]]
        diffs.append(pool[null_arm][sd] - float(np.mean(rs)))
    lo, hi = boot_mean(diffs)
    return {"observed": obs, "p": p, "n_seeds": len(sds),
            "ci": [lo, hi], "diffs": diffs}


def perm_pairwise(pool, null_arm, real, rng, n_perm=N_PERM):
    """B. 与「单个真实表面」逐对配对：置换池限于 {null_arm, real}。"""
    if null_arm not in pool or real not in pool:
        return None
    if not pool[null_arm] or not pool[real]:
        return None
    sds = sorted(set(pool[null_arm]) & set(pool[real]))
    if len(sds) < 2:
        return None
    d = [pool[null_arm][sd] - pool[real][sd] for sd in sds]
    obs = float(np.mean(d))
    # 双样本符号翻转：H0 是"差值分布关于 0 对称"，翻转任一符号即重排
    arr = np.array(d)
    count = 0
    signs = rng.choice([-1.0, 1.0], size=(n_perm, len(arr)))
    nulls = (signs * arr).mean(axis=1)
    count = int(np.sum(np.abs(nulls) >= abs(obs)))
    p = (count + 1) / (n_perm + 1)
    lo, hi = boot_mean(d)
    return {"observed": obs, "p": p, "n_seeds": len(sds),
            "ci": [lo, hi], "diffs": d}


def bh_q(pvals):
    """Benjamini-Hochberg q 值（升序 p 对应降序 q）。"""
    m = len(pvals)
    if m == 0:
        return []
    idx = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank, i in enumerate(reversed(idx), 0):
        k = m - rank# 第 k 大
        val = min(prev, pvals[i] * m / k)
        q[i] = val
        prev = val
    return q


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--out", default=os.path.join(RES, "s2l_analysis.json"))
    args = ap.parse_args()

    paths = args.files
    if not paths:
        paths = (sorted(glob.glob(os.path.join(RES, "*.jsonl")))
                 + sorted(glob.glob(os.path.join(RES, "from_4core", "*.jsonl")))
                 + sorted(glob.glob(os.path.join(RES, "from_library", "*.jsonl"))))

    cell, meta, dup, nbad = load(paths)
    print("=" * 74)
    print("S2L 正式分析：拉丁方配平 + 共享词表")
    print("=" * 74)
    grid = len(ALL_SURFACES) * len(NS) * len(SEEDS)
    print(f"  输入 {len(paths)} 个文件，收 {len(cell)}/{grid} 格点"
          f"（重复 {dup}，丢弃无效 {nbad}）")

    vocabs = {m["vocab"] for m in meta.values() if m.get("vocab")}
    toks = {m["tok"] for m in meta.values() if m.get("tok")}
    print(f"  vocab 取值集合 = {vocabs}   token 数集合 = {toks}")
    if len(vocabs) == 1:
        print("  -> 共享词表成立：修正二（vocab 169 vs 225）已消除")
    else:
        print("  -> 警告：vocab 不唯一，修正二未完全消除")

    parity = parity_report(meta)

    degen_tbl, degen, N = degeneracy_report(cell)
    print()
    print("=" * 74)
    print("STEP 2  退化检查（置换检验的前置条件）")
    print("=" * 74)
    worst = sorted(degen_tbl.items(), key=lambda kv: -kv[1]["frac"])[:6]
    print("  逐位相同比例最高的 6 对：")
    for k, v in worst:
        mark = "  <-- 完全退化" if v["identical"] == v["total"] else ""
        print(f"    {k:>18}  {v['identical']:>2}/{v['total']}"
              f"  = {v['frac']:.3f}{mark}")
    print(f"\n  完全退化的配对：{len(degen)} 对"
          f"{'（' + ', '.join(f'{a}/{b}' for a, b in degen) + '）' if degen else ''}")

    # ---- 描述统计 ----
    print()
    print("=" * 74)
    print("STEP 3  acc 均值（表面 × n，8 seeds 配平）")
    print("=" * 74)
    print(f"  {'surface':>10}" + "".join(f"{n:>9}" for n in NS))
    means = {}
    for sf in ALL_SURFACES:
        bs = by_seed(cell, sf)
        row = f"  {sf:>10}"
        for n in NS:
            v = [d[n] for d in bs.values() if n in d]
            m = float(np.mean(v)) if v else float("nan")
            means[(sf, n)] = m
            row += f"{m:>9.4f}"
        print(row)
    print()
    print("  真实表面均值 / null 臂：")
    for grp, names in (("真实 6 表面", REAL_SURFACES),
                       ("null 臂", NULL_ARMS)):
        row = f"  {grp:>12}"
        for n in NS:
            v = [means[(s, n)] for s in names if not np.isnan(means[(s, n)])]
            row += f"{np.mean(v):>9.4f}" if v else f"{'----':>9}"
        print(row)

    # ---- 阈值表 ----
    print()
    print("=" * 74)
    print("STEP 4  逐 seed 阈值（几何平均 n）")
    print("=" * 74)
    thr = {}
    for tau in TAUS:
        thr[tau] = {s: seed_thresholds(cell, s, tau) for s in ALL_SURFACES}
        line = f"  tau={tau:.2f} "
        for s in ALL_SURFACES:
            v = list(thr[tau][s].values())
            line += f"{s}={np.exp(np.mean(np.log(v))):6.0f}({len(v)}) " \
                if v else f"{s}=  ----  "
        print(line)
    print("\n  括号内为跨过判据的种子数；'----' 是阈值未定义（该表面在")
    print("  最大 n 档仍未达τ），不是 0。")

    # ---- 统计量 A ----
    rng = np.random.default_rng(RNG_SEED)
    print()
    print("=" * 74)
    print("STEP 5  统计量 A：null 阈值 − 真实表面阈值均值（标签重排置换）")
    print("=" * 74)
    A = {}
    for tau in TAUS:
        pool = {s: thr[tau][s] for s in ALL_SURFACES if thr[tau][s]}
        for na in NULL_ARMS:
            r = perm_mean_paired(pool, na, rng)
            A[f"{tau}|{na}"] = r
            if r is None:
                print(f"  tau={tau:.2f}  {na:>8}  SKIPPED（阈值/种子不足）")
                continue
            v = ("稳健" if r["p"] > 0.10
                 else "边缘" if r["p"] > 0.05 else "显著")
            print(f"  tau={tau:.2f}  {na:>8}  配对差={r['observed']:+8.0f}  "
                  f"CI=[{r['ci'][0]:+.0f},{r['ci'][1]:+.0f}]  "
                  f"p={r['p']:.4f}  seeds={r['n_seeds']}  {v}")

    # ---- 统计量 B ----
    print()
    print("=" * 74)
    print("STEP 6  统计量 B：null 与每个真实表面逐对配对（符号翻转置换）")
    print("=" * 74)
    B = {}
    for tau in TAUS:
        for na in NULL_ARMS:
            for rs in REAL_SURFACES:
                r = perm_pairwise(thr[tau], na, rs, rng)
                B[f"{tau}|{na}|{rs}"] = r
    # 汇总显著的
    hits = [(k, v) for k, v in B.items() if v and v["p"] <= 0.05]
    m_tests = sum(1 for v in B.values() if v)
    print(f"  检验族：{m_tests} 个（2 null × 6 真实表面 × 7 τ）")
    print(f"  Bonferroni α' = 0.05/{m_tests} = "
          f"{0.05 / m_tests:.2e}")
    if hits:
        print(f"  未校正 p ≤ 0.05 的组合：{len(hits)}")
        for k, v in sorted(hits, key=lambda kv: kv[1]["p"]):
            tau, na, rs = k.split("|")
            print(f"    tau={tau}  {na:>8} vs {rs:<8}  "
                  f"diff={v['observed']:+8.0f}  p={v['p']:.4f}")
    else:
        print("  未校正 p ≤ 0.05 的组合：无")

    # BH 校正
    valid = [(k, v["p"]) for k, v in B.items() if v]
    qs = bh_q([p for _k, p in valid])
    qmap = {k: q for (k, _p), q in zip(valid, qs)}
    sig_bh = [(k, q) for k, q in qmap.items() if q <= 0.05]
    print(f"  BH q ≤ 0.05 的组合：{len(sig_bh)}"
          + ("" if sig_bh else "（多重比较后无一存活）"))
    for k, q in sorted(sig_bh, key=lambda kv: kv[1])[:10]:
        print(f"    {k}  q={q:.4f}")

    # ---- 一致性：修正一是否仍成立 ----
    print()
    print("=" * 74)
    print("STEP 7  修正一复核：两种配对方式是否给出不同结论")
    print("=" * 74)
    disagree = []
    for tau in TAUS:
        for na in NULL_ARMS:
            a = A.get(f"{tau}|{na}")
            if not a:
                continue
            bs = [v["p"] for k, v in B.items()
                  if k.startswith(f"{tau}|{na}|") and v]
            if not bs:
                continue
            sig_b = min(bs) <= 0.05
            sig_a = a["p"] <= 0.05
            if sig_a != sig_b:
                disagree.append((tau, na, a["p"], min(bs)))
    if disagree:
        print(f"  两种统计量在{len(disagree)} 个 (τ, null) 上结论不一致：")
        for tau, na, pa, pb in disagree:
            print(f"    tau={tau}  {na:>8}  A:p={pa:.4f}  "
                  f"B 最小 p={pb:.4f}")
    else:
        print("  两种统计量在全部 (τ, null) 上结论一致。")
        print("  -> 上一轮的\"欠定\"问题在本设计下不复现。")

    # ---- 结论 ----
    print()
    print("=" * 74)
    print("VERDICT")
    print("=" * 74)
    pa_all = [v["p"] for v in A.values() if v]
    if not pa_all:
        print("  A 统计量无可用检验。")
    else:
        print(f"  统计量A：{len(pa_all)} 个检验，"
              f"最小 p = {min(pa_all):.4f}，"
              f"{'全部 > 0.10' if min(pa_all) > 0.10 else '存在 ≤ 0.10 的组合'}")
    print(f"  统计量 B：{m_tests} 个检验，"
          f"{'BH q ≤ 0.05 有 ' + str(len(sig_bh)) + ' 个' if sig_bh else 'BH 校正后无存活'}")
    if min(pa_all) > 0.10 and not sig_bh:
        print("\n  S2 判定：**两个 null 臂与六个真实表面的涌现阈值在统计上")
        print("  不可区分**，且该结论对配对方式、判据阈值、词表规模三项")
        print("  都不敏感。这是从\"未获干净判定\"升级为**稳健阴性**。")
    else:
        print("\n  S2 判定：部分判据上可区分，结论需限定到通过的那些判据。")

    out = {"grid": {"surfaces": ALL_SURFACES, "ns": NS, "seeds": SEEDS,
                    "total": grid, "filled": len(cell)},
           "vocab_values": sorted(vocabs), "token_values": sorted(toks),
           "latin_parity": parity,
           "degeneracy": degen_tbl, "fully_degenerate_pairs": degen,
           "means": {f"{k[0]}|{k[1]}": v for k, v in means.items()},
           "thresholds": {str(t): {s: thr[t][s] for s in ALL_SURFACES}
                          for t in TAUS},
           "stat_A_mean_paired": {k: v for k, v in A.items() if v},
           "stat_B_pairwise": {k: v for k, v in B.items() if v},
           "stat_B_bh_q": qmap,
           "A_B_disagree": disagree,
           "n_tests_B": m_tests, "bonferroni_alpha": 0.05 / m_tests}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n  -> {args.out}")


if __name__ == "__main__":
    main()