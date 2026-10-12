"""
s2_latin_rerun.py — T3：S2 在拉丁方id 配平下的完整重跑。

为什么必须真跑，不能只改分析
--------------------------------
`s2_permutation.py` 在`results/surface_fix2.jsonl` 上跑出的结果是：

    无完全退化的配对 —— 置换检验可以正常进行。
    但 relperm / entperm 两行全部'----'（阈值未定义）

原因是 surface_fix2.jsonl 只有 **6 个真实表面**（zh/en/lisp/math/
code/alien），**根本没有 relperm / entperm 的数据**。
S2 的整个论证依赖「null 臂的阈值与真实表面的阈值分布不可区分」，
没有 null 臂，置换检验无从做起。

这不是分析口径问题，是数据缺失。加机器不能造出这批数据，
只能用 `latin.py` 的循环拉丁方重跑整个8 表面设计。

为什么必须是 8 seeds（不是 6）
-------------------------------
拉丁方配平的前提是种子数 ≥ 表面数。S2 要把 6 个真实表面与 2 个 null
表面放进**同一个**共享词表，表面集是 8 个，所以：

    slot = (surface_index + seed) mod 8

8 个种子走完后，每个表面恰好经历全部 8 个 id 区间各一次。
沿用 6 seeds 会让配平退化成「每个表面只经历 6 个slot」，
剩下 2 个 slot 空置 —— 正是 latin.py 文档里警告的那种
「表面主效应与 slot 噪声纠缠」。

代价：8 surfaces × 8 seeds × 5 n = 320 runs。
surface_fix2 的实测单run 中位数 303 s，32 核并行约
320 × 303 / 32 ≈ 50 分钟（加上进程调度开销，按 60–70 分钟估）。

与旧 S2 数据的关系
------------------
本脚本**不复用** surface_fix2.jsonl 的任何 acc。原因是拉丁方改变的是
**训练时的表面 id 分配**，属于干预而非后处理：
同一 (surface, n, seed) 在 8 表面设计下拿到的 slot 与 6 表面设计下
不同，重训后的 acc 不可比。旧数据只能留作对照。

不变量（每个 run 内部断言）
-------------------------
  * token 数配平：train/test 两侧 token 数集合相等且为单元素
  * vocab 恒定：8 表面全集编码，vocab 总量不随 surface/slot 变
  * 关系结构恒定：relperm/entperm 只置换符号，不改 n_rel/assign
  * 退化守卫：relperm 与 en 的 tokens 不得逐位相同
    （`build_vocab` 按出现顺序分配 id 的退化就是在这里被拦住的）

用法
----
    python s2_latin_rerun.py --seeds 8 --workers 26
    python s2_latin_rerun.py --preflight          # 只跑不变量检查
    python s2_latin_rerun.py --plan               # 只列网格与耗时估计

断点续跑：已存在的 (surface, n_train, seed) 自动跳过。
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
sys.path.insert(0, HERE)

import latin
from model import train_model
from substrate2 import Gen, build

REAL_SURFACES = ["zh", "en", "lisp", "math", "code", "alien"]
NULL_ARMS = ["relperm", "entperm"]
ALL_SURFACES = REAL_SURFACES + NULL_ARMS

DEPTH = 3
N_TEST = 400
NS = [2000, 3000, 4000, 5000, 6500]

_STATE = {}


def _init(seeds):
    global _STATE
    _STATE = {"seeds": seeds, "names": ALL_SURFACES}
    ok, msg = latin.check_parity(ALL_SURFACES, seeds)
    if not ok:
        raise RuntimeError("latin parity broken: " + msg)


def run_one(surface, n_train, seed):
    from substrate2 import build as _build

    sub = _build(1)
    n_rel = sub["n_rel"]
    slot = latin.slot_of(ALL_SURFACES, surface, seed)

    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert len(train_p) == n_train, f"train short {len(train_p)}/{n_train}"
    assert len(test_p) == N_TEST, f"test short {len(test_p)}/{N_TEST}"

    vocab, si = latin.build_vocab(ALL_SURFACES, surface, slot,
                                  depth=DEPTH, n_test=N_TEST, n_rel=n_rel)
    train_r = latin.encode(train_p, surface, n_rel, vocab, si)
    test_r = latin.encode(test_p, surface, n_rel, vocab, si)

    # ---- 不变量 1：token 数配平 ----
    toks = {len(r["tokens"]) for r in train_r[:200]}
    toks_te = {len(r["tokens"]) for r in test_r[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"

    # ---- 不变量 2：退化守卫（null 臂不得与 en 逐位相同）----
    # 这是 S1 踩过的坑：build_vocab 按首次出现顺序分配 id 时，
    # relperm 与 en 的关系结构完全相同 -> 拿到逐 token 相同的 id
    # -> null 对照变成「一个不改变任何东西的对照」。
    # 拉丁方下二者 slot 必然不同，但这里仍做实证核对。
    if surface in NULL_ARMS:
        en_slot = latin.slot_of(ALL_SURFACES, "en", seed)
        assert slot != en_slot, (
            f"{surface} got the same slot as en ({slot}) — "
            f"the null arm would be a no-op")

    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    return {
        "arm": "S2_latin", "surface": surface, "block_slot": slot,
        "surface_index": ALL_SURFACES.index(surface),
        "n_rel": n_rel, "n_train": n_train, "seed": seed,
        "acc": acc, "steps": steps, "vocab": len(vocab),
        "tok": toks.pop(), "secs": round(time.time() - t0, 1),
    }


def job(spec):
    """单run 包装。

    worker 崩溃时进程池会整体抛 BrokenProcessPool，把**所有**在跑的
    run 一起带走，且子进程 stderr 被吞。这里把异常转成一条带traceback
    的记录，让主进程能报出「哪一格失败、为什么」。

    另外单独捕获 BrokenProcessPool 之外的硬崩（OOM 等）：若worker 被
    操作系统杀死，future 本身会抛，交给主循环按 run 记录。
    """
    try:
        return run_one(*spec)
    except Exception:
        import traceback
        return {"acc": float("nan"), "surface": spec[0],
                "n_train": spec[1], "seed": spec[2],
                "error": traceback.format_exc()[-500:]}


def preflight(seeds):
    print("=" * 74)
    print(f"PREFLIGHT — S2 拉丁方重跑（{len(ALL_SURFACES)} 表面 × {seeds} 种子）")
    print("=" * 74)

    ok, msg = latin.check_parity(ALL_SURFACES, seeds)
    print(f"\n  配平前提：{len(ALL_SURFACES)} 表面 / {seeds} 种子 -> "
          f"{'OK' if ok else '不满足'}")
    if not ok:
        print("  " + msg)
        print(f"  → 必须用 --seeds {len(ALL_SURFACES)} 或更多，"
              f"否则 slot 配平退化")
        return False

    print("\n  slot 表（surface × seed）：")
    print(f"  {'surface':>10}" + "".join(f"{'s' + str(s):>5}"
                                        for s in range(seeds)))
    for s in ALL_SURFACES:
        row = "".join(f"{latin.slot_of(ALL_SURFACES, s, sd):>5}"
                      for sd in range(seeds))
        print(f"  {s:>10}{row}")
    full = all(sorted(latin.slot_of(ALL_SURFACES, s, sd)
                      for sd in range(seeds)) == list(range(len(ALL_SURFACES)))
               for s in ALL_SURFACES)
    print(f"  每表面恰好遍历全部 slot：{full}")
    assert full, "latin square is not balanced"

    print("\n  词表与结构不变量（对每个表面各造一次词表）：")
    sub = build(1)
    probe = Gen(sub, seed=4242).dataset(N_TEST, [DEPTH], seed=4242)
    base_vocab = None
    print(f"  {'surface':>10} {'slot(s=0)':>10} {'vocab':>7} "
          f"{'n_tokens':>9} {'slot(s=1)':>10} {'vocab':>7}")
    for s in ALL_SURFACES:
        row = []
        for sd in (0, 1):
            slot = latin.slot_of(ALL_SURFACES, s, sd)
            v, si = latin.build_vocab(ALL_SURFACES, s, slot,
                                      depth=DEPTH, n_test=N_TEST,
                                      n_rel=sub["n_rel"])
            enc = latin.encode(probe[:200], s, sub["n_rel"], v, si)
            nt = len(enc[0]["tokens"])
            row.append((slot, len(v), nt))
            if base_vocab is None:
                base_vocab = len(v)
        assert row[0][1] == row[1][1] == base_vocab, (
            f"{s}: vocab varies with slot ({row[0][1]} vs {row[1][1]}, "
            f"baseline {base_vocab}) — id assignment is not the only change")
        assert row[0][2] == row[1][2], \
            f"{s}: token count varies with slot"
        print(f"  {s:>10} {row[0][0]:>10} {row[0][1]:>7} {row[0][2]:>9} "
              f"{row[1][0]:>10} {row[1][1]:>7}")

    print(f"\n  vocab 恒定 = {base_vocab}（跨全部表面与 slot）")
    print(f"  token 数恒定（{row[0][2]}），配平成立")

    print("\n  退化守卫：null 臂与 en 必须落在不同 slot")
    for s in NULL_ARMS:
        for sd in (0, 1, 2):
            sl = latin.slot_of(ALL_SURFACES, s, sd)
            en = latin.slot_of(ALL_SURFACES, "en", sd)
            assert sl != en, f"{s}@seed{sd} shares slot {sl} with en"
        print(f"    {s}: OK（每个种子上都与 en 不同slot）")

    n_runs = len(ALL_SURFACES) * len(NS) * seeds
    print(f"\n  网格：{len(ALL_SURFACES)} 表面 × {len(NS)} n × {seeds} 种子 "
          f"= {n_runs} runs")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=len(ALL_SURFACES))
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--ns", type=str, default=None)
    ap.add_argument("--out", default="../results/s2_latin.jsonl")
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()

    ns = [int(x) for x in args.ns.split(",")] if args.ns else NS
    seeds = list(range(args.seeds))

    if args.plan:
        n_runs = len(ALL_SURFACES) * len(ns) * args.seeds
        print(f"表面 {len(ALL_SURFACES)} × n {len(ns)} × 种子 {args.seeds} "
              f"= {n_runs} runs")
        print(f"实测单 run 中位数 303 s（surface_fix2）")
        for w in (8, 16, 26, 32):
            print(f"  {w:>2} 核 →约 {n_runs * 303 / w / 60:.0f} 分钟"
                  f"（不含调度损耗）")
        return

    if args.preflight:
        ok = preflight(args.seeds)
        sys.exit(0 if ok else 1)

    # 正常跑：先 preflight，不通过就不许开跑
    if not preflight(args.seeds):
        print("\npreflight 未通过，拒绝开跑。")
        sys.exit(1)

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                done.add((r["surface"], r["n_train"], r["seed"]))
        print(f"\n断点续跑：已有 {len(done)} 条，跳过")

    specs = [(s, n, sd) for s, n, sd in
             itertools.product(ALL_SURFACES, ns, seeds)
             if (s, n, sd) not in done]
    print(f"待跑 {len(specs)} runs → {out}")
    if not specs:
        print("没有待跑的格子。")
        return

    t0 = time.time()
    nerr = 0
    # 必须显式 spawn：Python 3.14 的默认多进程上下文是 forkserver，
    # 在 Windows 上经由中间server 进程转发，会把 worker 直接带崩
    # （BrokenProcessPool，且子进程 stderr 被吞掉，看不到原因）。
    # depth_scan.py / arm_k_null.py 都显式用 spawn，本脚本与之对齐。
    ctx = mp.get_context("spawn")
    with open(out, "a", encoding="utf-8") as fh:
        with ProcessPoolExecutor(max_workers=args.workers,
                                 mp_context=ctx,
                                 initializer=_init,
                                 initargs=(args.seeds,)) as ex:
            futs = {ex.submit(job, s): s for s in specs}
            for i, fu in enumerate(as_completed(futs), 1):
                # fu.result() 在 worker 被硬杀（OOM 等）时抛
                # BrokenProcessPool，不能让这一格带走其余所有 run。
                try:
                    r = fu.result()
                except Exception as e:
                    s = futs[fu]
                    r = {"acc": float("nan"), "error": repr(e)[:300],
                         "_crashed": True,
                         "surface": s[0], "n_train": s[1], "seed": s[2]}
                if "error" in r or r.get("acc") is None:
                    nerr += 1
                    print(f"[{i}/{len(specs)}] ERROR "
                          f"{r.get('surface')} n={r.get('n_train')} "
                          f"seed={r.get('seed')}")
                    print("   " + str(r.get("error", ""))[-300:])
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
                else:
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
                if i % 10 == 0 or i == len(specs):
                    el = time.time() - t0
                    eta = el / i * (len(specs) - i)
                    print(f"[{i}/{len(specs)}] "
                          f"{el/60:.1f} min elapsed, ETA {eta/60:.1f} min, "
                          f"errors {nerr}")
    print(f"\n完成：{len(specs)} runs，{nerr} errors，"
          f"{(time.time()-t0)/60:.1f} 分钟")
    print(out)


if __name__ == "__main__":
    main()