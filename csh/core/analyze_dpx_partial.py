"""DPX 已回收部分（198/216）的零算力分析。

要回答的唯一问题：E4 里「penalty 不随 depth 上升」到底是
「与 depth 无关」还是「depth 与 n 完全纠缠」造成的？

T1 的全部意义就是拆开这个纠缠。若已回收的 198runs 里
depth x n 已经有交叉点，就能先读出方向，不必等 216 全满。

读法遵守 2026-10-06 定的四条硬规矩：
1. 配对优先（不用比均值）
2. 报右删失
3. 给无删失读数（n½ / area）
4. 写明网格分辨率
"""
import json
import math
import statistics as st
from collections import defaultdict

SRC = "%DSH_ROOT%/appearent/package/results/DPX_partial.jsonl"

TAU = 0.60


def load():
    g = defaultdict(dict)          # (cell, depth, n) -> {seed: acc}
    for line in open(SRC, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        a = r.get("acc")
        if a is None or (isinstance(a, float) and math.isnan(a)):
            continue
        cell = r.get("test_kind") or r.get("cell")
        g[(cell, r["depth"], r["n_train"])][r["seed"]] = a
    return g


def n_half(seeds):
    """达到 acc=0.5 的最小 n；未达到返回 None。越大越难。"""
    for n in sorted(seeds):
        if seeds[n] >= 0.5:
            return n
    return None


def area(seeds):
    """acc 对 logn 的梯形积分。越小越难。"""
    # 注意：n_half 可能返回 None（未达 0.5），若不过滤会把 None
    # 塞进 math.log() 报 "expected a positive input"。
    ns = sorted(x for x in seeds if isinstance(x, int) and x > 0)
    if len(ns) < 2:
        return None
    xs = [math.log(n) for n in ns]
    ys = [seeds[n] for n in ns]
    s = 0.0
    for i in range(len(xs) - 1):
        s += (ys[i] + ys[i + 1]) / 2 * (xs[i + 1] - xs[i])
    return s / (xs[-1] - xs[0])


def boot_mean(a, B=4000):
    if len(a) < 2:
        return (a[0], a[0]) if a else (float("nan"),) * 2
    rs = []
    for _ in range(B):
        s = [a[int(math.random.random() * len(a))] for _ in range(len(a))]
        rs.append(sum(s) / len(s))
    rs.sort()
    return rs[int(0.025 * B)], rs[int(0.975 * B)]


def sign_perm(diffs):
    """配对差的符号翻转检验（对 0 中心的精确随机化检验）。"""
    n = len(diffs)
    if n == 0:
        return float("nan")
    obs = abs(sum(diffs) / n)
    cnt = 0
    B = 20000
    for _ in range(B):
        s = 0.0
        for d in diffs:
            s += d if math.random.random() < 0.5 else -d
        if abs(s / n) >= obs - 1e-12:
            cnt += 1
    return (cnt + 1) / (B + 1)


def main():
    g = load()
    depths = sorted({k[1] for k in g})
    ns_by_d = {d: sorted({k[2] for k in g if k[1] == d}) for d in depths}
    cells = sorted({k[0] for k in g})

    print("=" * 72)
    print("DPX 已回收部分分析（%d 条）" % sum(len(v) for v in g.values()))
    print("=" * 72)
    print()
    print("每个 depth 实际拿到的 n 网格：")
    for d in depths:
        print("  depth %d: %s" % (d, ns_by_d[d]))
    print()
    overlap = set(ns_by_d[depths[0]])
    for d in depths[1:]:
        overlap &= set(ns_by_d[d])
    print("三档 depth 共同的 n（真正可交叉比较的）：", sorted(overlap) or "无")
    print()

    # ---- 1. TT 基线的跨 depth 曲线：纠缠的直接证据 ----
    print("-" * 72)
    print("1. TT 基线的 acc 随 (depth, n) 变化 —— 纠缠长什么样")
    print("-" * 72)
    print("depth".ljust(8) + "".join(f"{n:>9}" for n in sorted({k[2] for k in g})))
    for d in depths:
        row = ""
        for n in sorted({k[2] for k in g}):
            v = g.get(("TT", d, n))
            row += f"{st.mean(v.values()):>9.3f}" if v else "        ."
        print(f"{d:<8}" + row)
    print()

    # ---- 2. 配对 penalty：TT - cell，按 (depth, n) ----
    print("-" * 72)
    print("2. 配对 penalty = acc(TT) - acc(cell)  逐 (depth, n)")
    print("   同 seed 配对；每格 6/6 为正则标*")
    print("-" * 72)
    alln = sorted({k[2] for k in g})
    for cell in cells:
        if cell == "TT":
            continue
        print(f"\n[{cell}]")
        print("  depth".ljust(8) + "".join(f"{n:>9}" for n in alln))
        for d in depths:
            row = ""
            for n in alln:
                base = g.get(("TT", d, n))
                cur = g.get((cell, d, n))
                if not base or not cur:
                    row += "        ."
                    continue
                seeds = set(base) & set(cur)
                diffs = [base[s] - cur[s] for s in seeds]
                m = sum(diffs) / len(diffs)
                allpos = all(x > 0 for x in diffs)
                row += f"{m:>8.3f}" + ("*" if allpos else " ")
            print(f"  {d:<8}" + row)

    # ---- 3. depth 斜率：penalty 是否随 depth 上升 ----
    print()
    print("-" * 72)
    print("3. penalty 的 depth 斜率（每 depth 一档，报删失与配对数）")
    print("   斜率 > 0 表示 penalty 随 depth 上升")
    print("-" * 72)
    for cell in cells:
        if cell == "TT":
            continue
        # 只用三档共有的 n（真交叉点）
        pts = []
        for d in depths:
            for n in sorted(overlap):
                base = g.get(("TT", d, n))
                cur = g.get((cell, d, n))
                if not base or not cur:
                    continue
                seeds = set(base) & set(cur)
                if not seeds:
                    continue
                pts.append((d, sum(base[s] - cur[s] for s in seeds) / len(seeds)))
        if len(pts) < 3:
            print(f"\n[{cell}] 共同 n 上的 (depth,n) 点只有 {len(pts)} 个，不足以估斜率")
            continue
        k = len(pts)
        mx = sum(p[0] for p in pts) / k
        my = sum(p[1] for p in pts) / k
        den = sum((p[0] - mx) ** 2 for p in pts)
        slope = (sum((p[0] - mx) * (p[1] - my) for p in pts) / den) if den else 0.0
        ys = [p[1] for p in pts]
        # CI：按 depth 分组做 bootstrap
        byd = defaultdict(list)
        for d, v in pts:
            byd[d].append(v)
        ds = sorted(byd)
        if len(ds) >= 2:
            md = st.mean(byd[ds[0]])
            Md = st.mean(byd[ds[-1]])
            diffs = [Md - md]
        else:
            diffs = None
        print(f"\n[{cell}]  slope = {slope:+.4f} / depth   点数 = {k}"
              f"   各 depth 均penalty = "
              + ", ".join(f"d{d}:{st.mean(byd[d]):+.3f}" for d in ds))
        if diffs:
            print(f"        d{ds[-1]} - d{ds[0]} = {diffs[0]:+.3f}"
                  f"   (共同 n = {sorted(overlap)})")

    # ---- 4. 无删失读数：TT 基线的 n½ 与 area ----
    #
    # n½ / area 是**曲线级**读数：要同一 depth 下多个 n 串起来才有意义。
    # 之前误按单格调用（把一个 (depth,n) 的 seed 字典传进去），
    # 既算不出东西，又因为 n_half 返回 None 而让 math.log(None) 崩掉。
    print()
    print("-" * 72)
    print("4. 无删失读数：按 depth 串成曲线（不受 tau 判据影响）")
    print("   n½ 越大越难 / area 越小越难")
    print("-" * 72)
    for d in depths:
        # 逐 n 求均值，再串成该 depth 的曲线
        curve = {}
        for n in ns_by_d[d]:
            v = g.get(("TT", d, n))
            if v:
                curve[n] = st.mean(v.values())
        if len(curve) < 2:
            print(f"\n  depth{d}: 只有 {len(curve)} 个 n 档，曲线级读数不可算"
                  f"（逐格读数如下）")
            for n, m in sorted(curve.items()):
                v = g[("TT", d, n)]
                cross = sum(1 for a in v.values() if a >= TAU)
                print(f"    n={n:>6}  acc={m:.3f}  跨tau={cross}/{len(v)}")
            continue
        nh = n_half(curve)
        ar = area(curve)
        pts = ", ".join(f"n={n}:{m:.3f}" for n, m in sorted(curve.items()))
        print(f"\n  depth{d}  ({len(curve)} 档: {pts})")
        print(f"          n@0.5 = {'未达' if nh is None else nh}"
              f"   area = {'NA' if ar is None else f'{ar:.3f}'}")

    print()
    print("=" * 72)
    print("缺口（还需补跑才能支撑完整结论）：")
    print("=" * 72)
    for cell in cells:
        for d in depths:
            for n in sorted({k[2] for k in g}):
                v = g.get((cell, d, n))
                if not v or len(v) < 6:
                    print(f"  {cell:10s} depth{d} n={n:>6}  现有 {len(v) if v else 0} seeds")


if __name__ == "__main__":
    main()
