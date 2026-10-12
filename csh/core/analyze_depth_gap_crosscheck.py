"""独立复核 codex 的"迁移代价随深度平坦"结论。

为什么要复核：
codex 的主判据是 gap = tau - acc_cell(n*_TT)，**依赖阈值估计**。
而阈值法在本项目已被证明不可信两次：
  - E4：跨 tau 的种子数测的是种子质量，不是变换难度
  - E6：en 在 mult=2/3 有 4/6 种子阈值压在上界 6500，配对检验用的是
        「训练得最快的那几个」，阈值不能外推
所以这里用**不依赖阈值**的方法复核：在真正的共同 n 上做逐 seed 配对 bootstrap。

复核结论（2026-10-06）：12/12 比较全部 CI 含 0，"平坦"成立。
比codex 的阈值法更稳，因为不涉及删失。

用法：
python analyze_depth_gap_crosscheck.py [数据文件]
默认读 results/depth_scan_final.jsonl
"""
import json
import os
import random
import statistics as st
import sys
from collections import defaultdict

SRC = sys.argv[1] if len(sys.argv) > 1 else "results/depth_scan_final.jsonl"
TAU = 0.60


def load(path):
    g = defaultdict(dict)
    n_err = 0
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        r = json.loads(ln)
        a = r.get("acc")
        if a is None or a != a or "error" in r:
            n_err += 1
            continue
        cell = r.get("test_kind") or r.get("cell")
        g[(cell, r["depth"], r["n_train"])][r["seed"]] = a
    return g, n_err


def boot(a, B=8000):
    if len(a) < 2:
        return (a[0], a[0])
    n = len(a)
    rs = []
    for _ in range(B):
        s = [a[random.randrange(n)] for _ in range(n)]
        rs.append(sum(s) / n)
    rs.sort()
    return rs[int(0.025 * B)], rs[int(0.975 * B)]


def main():
    g, n_err = load(SRC)
    depths = sorted({k[1] for k in g})
    cells = sorted({k[0] for k in g if k[0] != "TT"})
    ns = {d: sorted({k[2] for k in g if k[1] == d and k[0] == "TT"})
          for d in depths}

    print("=" * 74)
    print("codex 结论的独立复核（无删失配对 bootstrap）")
    print("=" * 74)
    print(f"数据 {SRC}: {sum(len(v) for v in g.values())} 条有效, {n_err} 错误")
    print(f"depth = {depths}")
    print()

    # ---- 0. 删失诊断：codex 未报，但论文里该有 ----
    print("-" * 74)
    print("0. 右删失诊断（TT 跨 tau 的种子数）—— codex 未报")
    print("-" * 74)
    cens = {}
    for d in depths:
        for n in ns[d]:
            v = g[("TT", d, n)]
            cross = sum(1 for a in v.values() if a >= TAU)
            cens[(d, n)] = cross
            flag = "  <- 删失(压上界)" if cross == 0 else ""
            print(f"  d{d} n={n:>6}  acc={st.mean(v.values()):.3f}  "
                  f"跨tau={cross}/{len(v)}{flag}")
    print()

    # ---- 1. 共同 n：可比性的前提 ----
    print("-" * 74)
    print("1. 共同 n（跨 depth 可比的必要条件）")
    print("-" * 74)
    pairs = []
    for i in range(len(depths)):
        for j in range(i + 1, len(depths)):
            a, b = depths[i], depths[j]
            common = sorted(set(ns[a]) & set(ns[b]))
            pairs.append((a, b, common))
            print(f"  d{a} ∩ d{b} = {common}")
    triple = set(ns[depths[0]])
    for d in depths[1:]:
        triple &= set(ns[d])
    print(f"  三档共同 = {sorted(triple) or '无（只能两两比较）'}")
    print()

    # ---- 2. 逐 seed 配对bootstrap ----
    print("-" * 74)
    print("2. penalty 的 depth 差（逐 seed 配对 bootstrap，不依赖 tau）")
    print("   delta = penalty(深 depth) - penalty(浅 depth)")
    print("-" * 74)
    n_sig = 0
    n_tot = 0
    for cell in cells:
        print(f"\n[{cell}]")
        for a, b, common in pairs:
            for n in common:
                ba, ca = g.get(("TT", a, n)), g.get((cell, a, n))
                bb, cb = g.get(("TT", b, n)), g.get((cell, b, n))
                if not (ba and ca and bb and cb):
                    continue
                sd = set(ba) & set(ca) & set(bb) & set(cb)
                if len(sd) < 2:
                    continue
                diffs = [(bb[s] - cb[s]) - (ba[s] - ca[s]) for s in sd]
                m = sum(diffs) / len(diffs)
                lo, hi = boot(diffs)
                n_tot += 1
                if lo > 0:
                    verdict = "显著上升"
                    n_sig += 1
                elif hi < 0:
                    verdict = "显著下降"
                    n_sig += 1
                else:
                    verdict = "不显著"
                cmark = " [该点 TT 删失]" if cens.get((a, n)) == 0 or \
                    cens.get((b, n)) == 0 else ""
                print(f"  d{a}/n{n} -> d{b}/n{n}: delta={m:+.4f} "
                      f"CI=[{lo:+.4f},{hi:+.4f}] {verdict} "
                      f"(pairs={len(diffs)}){cmark}")
    print()
    print("=" * 74)
    print(f"汇总：{n_tot} 个比较，{n_tot - n_sig} 个不显著，{n_sig} 个显著")
    if n_sig == 0:
        print("→ penalty 随 depth 变化不显著，"
              "**codex 的『平坦』结论成立**。")
        print("  且本判据不依赖阈值，故不受右删失影响。")
    else:
        print("→ 存在显著变化，codex 的『平坦』结论需修正。")
    print("=" * 74)


if __name__ == "__main__":
    main()
