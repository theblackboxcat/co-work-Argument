"""
depth_cross.py — T1：depth × n 交叉网格，补齐 depth_scan 的混淆格点。

要解决的混淆
------------
`depth_scan.py` 给每个 depth 配了**不同的 n 网格**（依据是实测的
涌现点）：

    depth 3   [2000, 3000, 4000, 5000, 6500]
    depth 4   [5000, 6500, 8500, 11000]
    depth 5   [11000, 14000, 20000]

于是 depth 与训练量在设计上完全共变。§7.3 的判别是
「penalty = acc(TT) − acc(变换) 是否随 depth 上升」，
但每一层的 penalty 是在**不同的 n 范围**上平均的：
d3 的 penalty 来自 n≤6500，d5 来自 n≥11000。

这带来两个方向相反的偏差，无法先验地说哪个占优：
  * 若 penalty 随 n 上升（同分布基线上升得比变换快），
    则深层的 penalty 被 n 抬高 → 真实深度效应被**高估**
  * 若 penalty 随 n 饱和（变换侧追上基线），
    则深层的 penalty 被 n 压低 → 真实深度效应被**低估**

`analyze_e4_paired.py` 实测 TU、Tlowovl 的 depth 斜率 CI 都跨 0，
但那**不能**读成「penalty 与 depth 无关」——混淆没拆开之前，
这个读数没有意义。

本脚本的做法
------------
让**每个 depth 都跑同一组 n**，即
    depth ∈ {3,4,5} × n ∈ COMMON_N × 4 cell × 6 seeds

已有的 (depth, n) 若不在 COMMON_N 里，本脚本不删——它们各自
仍是有用的点估计；本脚本只**补齐** COMMON_N 上缺的格子。
这样四个 cell 在同一 depth 内可配对（TT 基线同层），
在同 n 内也可跨 depth 比较，两个方向都成立。

选哪些 n
--------
共用网格必须让每个 depth 都有格子跨过判据，否则某层又变成
全删失。depth_scan 已实测的跨线位置：

    d3 跨线约 n=4000，TT 在 6500 已到 0.998（饱和）
    d4 跨线约 n=6000
    d5 跨线约 n≈11000+

所以 COMMON_N 取 [4000, 5000, 6500, 8500, 11000, 14000]：
  * 4000/5000/6500 覆盖 d3 的学习区与饱和区
  * 8500/11000/14000 覆盖 d4/d5 的学习区
每个 depth 在这个网格上至少有 2 个格子跨线。

规模：3 depth × 4 cell × 6 n × 6 seeds = 432 runs，
减去 depth_scan 已有的格子（d3 的 4000/5000/6500 共 3 n × 4 cell
× 6 seeds = 72；d4 的 5000/6500/11000 共 3 × 4 × 6 = 72；
d5 的 11000/14000 共 2 × 4 × 6 = 48），实际新跑约 240 runs。

单run 成本参考 surface_fix2 的中位数 303 s（同substrate2 + model，
n 更大时会略贵）。240 runs 在 26 核上约 45–60 分钟。

不变量（复用 depth_scan 的断言，本脚本不重新实现）
  * 训练基质恒为 typed；测试基质由 cell 决定
  * token 数配平：train/test 两侧 token 数集合相等
  * 每个 (cell, depth) 的生成器 yield 必须足够（preflight 检查）
  * 断点续跑：已有 (cell, depth, n, seed) 自动跳过

用法
----
    python depth_cross.py --plan
    python depth_cross.py --preflight
    python depth_cross.py --workers 26 --out ../results/depth_cross.jsonl
"""

import argparse
import itertools
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
if PKG not in sys.path:
    sys.path.insert(0, PKG)

# depth_scan 的核心构件（import 而非复制，避免两处漂移）
from depth_scan import (  # noqa: E402
    TEST_SUBSTRATES, DEPTHS, N_GRID, run_one, job,
)

COMMON_N = [4000, 5000, 6500, 8500, 11000, 14000]
CRITERION = 0.60


def existing_keys(paths):
    """从已有结果里收 (cell, depth, n, seed)，支持 depth_scan_all
    与本脚本自己的输出。"""
    done = set()
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                acc = r.get("acc")
                if acc is None or (isinstance(acc, float) and acc != acc):
                    continue
                cell = r.get("test_kind") or r.get("cell")
                d = r.get("depth")
                if cell is None or d is None:
                    continue
                done.add((cell, int(d), int(r["n_train"]), int(r["seed"])))
    return done


def preflight(common_n, seeds, depths):
    print("=" * 76)
    print(f"PREFLIGHT — depth × n 交叉（{len(depths)} depth × "
          f"{len(common_n)} n × {len(TEST_SUBSTRATES)} cell × {seeds} 种子）")
    print("=" * 76)
    print("\n  共用 n 网格：", common_n)
    print("  各 depth 的原网格（不删，只补齐）：")
    for d in depths:
        print(f"    depth={d}: {N_GRID.get(d, [])}")

    # 结构事实：沿用 depth_scan 的生成器与渲染器做一次实检
    from depth_scan import Gen, Surface, c_eff, overlap, substrate_from_assign
    print(f"\n  {'cell':>10} {'depth':>5} {'ovl':>4} {'branch':>7} "
          f"{'C(k)':>7} {'C_eff':>7} {'tok':>4} {'yield/200':>11} "
          f"{'n=4000':>8} {'n=6500':>8}")
    bad = []
    for kind in TEST_SUBSTRATES:
        sub = substrate_from_assign(TEST_SUBSTRATES[kind], kind)
        for d in depths:
            c3, eff = c_eff(sub["assign"], d)
            g = Gen(sub, seed=0)
            y = sum(1 for _ in range(200) if g.make(d))
            sf = Surface("en", sub["n_rel"])
            p = Gen(sub, seed=1).dataset(2, [d], seed=1)[0]
            tk = len(sf.render(p)["tokens"])
            if y < 150:
                bad.append((kind, d, y))
            print(f"  {kind:>10} {d:5d} {overlap(sub['assign']):4d} "
                  f"{sub['branching']:7.2f} {c3:7d} {eff:7d} {tk:4d} "
                  f"{y:>11}" + f"{'':>8}{'':>8}")
    if bad:
        print("\n  **以下格子生成器 yield 不足，必须先修结构再跑：**")
        for kind, d, y in bad:
            print(f"    cell={kind} depth={d} yield={y}/200")
        return False

    # 生成器静默退化守卫：同一 cell 在不同 depth 必须给出不同
    # 的 token 数或至少不同的样本数，否则 depth 轴本身没生效
    print("\n  depth 轴生效检查（同一 cell，跨 depth 的 token 数）：")
    for kind in TEST_SUBSTRATES:
        sub = substrate_from_assign(TEST_SUBSTRATES[kind], kind)
        tks = []
        for d in depths:
            p = Gen(sub, seed=1).dataset(2, [d], seed=1)[0]
            tks.append(len(Surface("en", sub["n_rel"]).render(p)["tokens"]))
        flat = len(set(tks)) == 1
        print(f"    {kind:>10} tokens by depth {depths} = {tks}"
              f"{'   <-- 恒定，depth 轴可疑' if flat else '  （逐层变化）'}")
    print()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--depths", type=str, default="3,4,5")
    ap.add_argument("--ns", type=str, default=None)
    ap.add_argument("--out", default="../results/depth_cross.jsonl")
    ap.add_argument("--reuse", type=str, default=None,
                    help="额外复用的已有文件，逗号分隔")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--preflight", action="store_true")
    args = ap.parse_args()

    depths = [int(x) for x in args.depths.split(",")]
    common_n = [int(x) for x in args.ns.split(",")] if args.ns \
        else COMMON_N
    out = os.path.abspath(args.out)
    reuse = [os.path.abspath(x) for x in (args.reuse or "").split(",")
             if x.strip()]

    # 默认可复用的既有数据
    defaults = ["../results/depth_scan_all.jsonl",
                "../results/depth_scan.jsonl",
                "../results/depth5_ext.jsonl"]
    for d in defaults:
        p = os.path.abspath(os.path.join(HERE, d))
        if os.path.exists(p) and p not in reuse:
            reuse.append(p)

    specs = [(kind, d, n, sd)
             for d, n, kind, sd in
             itertools.product(depths, common_n, TEST_SUBSTRATES,
                               range(args.seeds))]
    done = existing_keys([out] + reuse)
    specs = [s for s in specs if s not in done]

    if args.plan:
        total = len(depths) * len(common_n) * len(TEST_SUBSTRATES) * args.seeds
        # 注意元组顺序必须与 done 一致： (cell, depth, n, seed)
        all_specs = [(kind, d, n, sd)
                     for d, n, kind, sd in
                     itertools.product(depths, common_n, TEST_SUBSTRATES,
                                       range(args.seeds))]
        n_have = sum(1 for s in all_specs if s in done)
        print(f"共用 n 网格：{common_n}")
        print(f"depth {depths}")
        print(f"cell: {sorted(TEST_SUBSTRATES)}")
        print(f"完整网格 = {len(depths)}×{len(common_n)}×"
              f"{len(TEST_SUBSTRATES)}×{args.seeds} = {total} runs")
        print(f"已有可复用 = {n_have}")
        print(f"待跑 = {len(specs)} runs")
        print("\n复用来源：")
        for p in reuse:
            print(f"  {os.path.basename(p)}")
        print("\n实测单 run 中位数 303 s（surface_fix2 同模型，n 更大略贵）")
        for w in (8, 16, 26, 32):
            print(f"  {w:>2} 核 → 约 {len(specs) * 303 / w / 60:.0f} 分钟"
                  f"（不含调度损耗）")
        return

    if args.preflight:
        sys.exit(0 if preflight(common_n, args.seeds, depths) else 1)

    if not preflight(common_n, args.seeds, depths):
        print("\npreflight 未通过，拒绝开跑。")
        sys.exit(1)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    print(f"复用文件：")
    for p in reuse:
        print(f"  {p}")
    print(f"\n待跑 {len(specs)} runs → {out}")
    if not specs:
        print("没有待跑的格子。")
        return

    t0 = time.time()
    nerr = 0
    ctx = mp.get_context("spawn")
    with open(out, "a", encoding="utf-8") as fh, \
            ProcessPoolExecutor(args.workers, mp_context=ctx) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            if r.get("error") or r.get("acc") is None:
                nerr += 1
                print(f"[{i}/{len(specs)}] ERROR {r.get('test_kind')} "
                      f"d={r.get('depth')} n={r.get('n_train')} "
                      f"seed={r.get('seed')}")
                print("   " + str(r.get("error", ""))[-300:])
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            if i % 10 == 0 or i == len(specs):
                el = time.time() - t0
                eta = el / i * (len(specs) - i)
                print(f"[{i}/{len(specs)}] {el/60:.1f} min elapsed, "
                      f"ETA {eta/60:.1f} min, errors {nerr}", flush=True)
    print(f"\n完成：{len(specs)} runs，{nerr} errors，"
          f"{(time.time()-t0)/60:.1f} 分钟")
    print(out)


if __name__ == "__main__":
    main()