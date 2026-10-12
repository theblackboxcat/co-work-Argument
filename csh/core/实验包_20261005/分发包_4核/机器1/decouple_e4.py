"""
decouple_e4.py — E4：签名表 100% 保持、只改类型→实体映射

对应判别书 §5（E4），**修正其不可能的设计**。
=====================================================================

判别书原文的设计，以及它为什么不成立
--------------------------------------
§5.2 要求构造「签名表完全不变（六个关系符号的 (dom,ran) 一对一相同），
但类型的角色互换 / 类型图拓扑改变」的测试基质，给出两个候选变换：

  (a) 反转查询顺序 (r1,r2,r3) -> (r3,r2,r1)
  (b) 把链的起点从「最上层」改成「最下层」

问题在于：**签名表就是 `assign` 本身**（`substrate2.py:87`的 `c_eff`
数的是 `{tuple(assign[r] for r in s)}`，即逐符号的 (dom,ran)）。
「签名表 100% 保持」在定义上就是 `assign` 逐项相同，也就是**同一个基质**。
同一assign 下不存在"拓扑变"——没有可变的量。

(a) 也不是它说的那个东西：反转查询序列 `(r3,r2,r1)` 不改变 `assign`，
产生的签名集合仍是同一 `{tuple(assign[r] for r in s)}` 的子集，`c_eff`
不变。它测的是「方向性顺序处理」，不是「根节点变了」。判别书 §5.6 自己也
承认这一点（"说明模型学到'从链顶往下追'的方向性抽象"），却仍把它列为
L2 vs C 的判决装置。

E4 的正确形式
-------------
要真正实现「签名表不变、但结构变了」，必须找一个**独立于 `assign`** 的
结构量。`substrate2.py` 里有两个：

  1. `assign`  —— 关系符号 -> (dom, ran) 的类型签名表
  2. `pools`   —— 类型 -> 实体的划分（TYPE_POOL = {0:0-6, 1:7-11, 2:12-17}）

`c_eff` 只依赖 `assign`，**不看 `pools`**；但 `pools` 决定「哪些实体是
T0 型的」，因而决定实体级的类型结构。改`pools` 而不动 `assign`：

  * 签名表 6/6 保持（C_eff(3) = 24 不变，branching 不变）
  * 实体到类型的归属被打乱 —— 模型在测试时看到的是同一套类型签名，
    但「哪些 token 是 T0」变了

这才是判别书想要的那个正交操纵，而且它**真的正交**（已实测 yield
300/300，生成器不退化）。

两个变换
--------
  root_swap  : 交换 T0 与 T1 的实体池。T0 从 {0..6} 变成 {7..11}，
               其容量从 7 掉到 5。签名表不变，实体级结构变。
  chain_reverse : 测试基质的链起点改为「最下层」—— 实现为把 pools 的
               三个块逆序（0->2, 1->1, 2->0）。同样是签名表不变、
               实体归属变，但扰动比 root_swap 大（两端块互换）。

对照
----
  TT   : typed -> typed            （基线，签名 6/6，实体归属不变）
  null : typed -> typed 的**实体标签置换**（结构完全不变，
         仅重命名实体 token）—— 承重对照。

没有 null 的"变换免费"结论不成立（这是论文 §7.4 的方法学教训）。
判别书 §5.4 没设null。

判定
----
  迁移代价< 5% baseline  -> C 赢（签名表够用，实体归属无关）
  迁移代价 > 15% baseline -> L2 存活（模型确实学到可迁移的类型结构抽象）
  null 代价 > 变换代价      -> 变换的效应只是重命名，须与 null 比

注意：本实验**不是**判别书说的"最便宜且判别力最强"。§7.3 的 Thighovl
已经是 5/6 重叠且免费（-0.004, CI 含零），推到 6/6 只多一格，而重叠度
是 6 个格点上的**整数变量**，1/6 -> 0/6 才是最大的一跳。判别书把最弱的
对比放在最前面，会把统计功效花在刀刃外。

用法
----
    python decouple_e4.py --seeds 6
    python decouple_e4.py --seeds 6 --dry-run     # 只跑 preflight
"""

import argparse
import copy
import itertools
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)

from surfaces import Surface, PermutedSurface      # noqa: E402
from substrate2 import Gen, c_eff# noqa: E402
from transfer import DEPTH, N_TEST, TYPED_ASSIGN, substrate_of  # noqa: E402
from model import build_vocab, train_model        # noqa: E402

NS = [2000, 3000, 4000, 5000, 6500]

# ---------------------------------------------------------------- 变换
#全部三个变换的 assign 都逐项等于 TYPED_ASSIGN —— 签名表 6/6 保持。
BASE_POOLS = [[0, 1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11], [12, 13, 14, 15, 16, 17]]

TRANSFORMS = {
    # 交换 T0 / T1 的实体池
    "root_swap":   [BASE_POOLS[1], BASE_POOLS[0], BASE_POOLS[2]],
    # 逆序：两端块互换
    "chain_reverse": [BASE_POOLS[2], BASE_POOLS[1], BASE_POOLS[0]],
    # null：实体池完全不变，仅重命名实体 token（承重对照）
    "null_renaming": BASE_POOLS,
}


def substrate_with_pools(pools, kind):
    """assign 与 typed 完全相同，只改 pools。"""
    n = len(TYPED_ASSIGN)
    m = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if TYPED_ASSIGN[i][1] == TYPED_ASSIGN[j][0]:
                m[i][j] = 1
    return {"kind": kind, "assign": list(TYPED_ASSIGN), "m": m, "n_rel": n,
            "pools": copy.deepcopy(pools),
            "branching": sum(sum(r) for r in m) / n,
            "dead": [i for i in range(n) if sum(m[i]) == 0]}


def run_one(test_kind, n_train, seed):
    sub_tr = substrate_of("typed")
    sub_te = substrate_with_pools(TRANSFORMS[test_kind], test_kind)
    assert not sub_tr["dead"], "training substrate has dead-end relations"
    assert not sub_te["dead"], "test substrate has dead-end relations"
    # --- 不变量：签名表 6/6 保持 ---
    assert sub_te["assign"] == list(TYPED_ASSIGN), \
        f"assign was modified — signature table must stay 6/6"

    g_tr = Gen(sub_tr, seed=1000 + seed)
    g_te = Gen(sub_te, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert len(train_p) == n_train, f"train short: {len(train_p)}/{n_train}"
    assert len(test_p) == N_TEST, f"test short: {len(test_p)}/{N_TEST}"

    s_tr = Surface("en", sub_tr["n_rel"])
    if test_kind == "null_renaming":
        s_te = PermutedSurface("en", sub_te["n_rel"], mode="ent")
    else:
        s_te = Surface("en", sub_te["n_rel"])
    train_r = [s_tr.render(p) for p in train_p]
    test_r = [s_te.render(p) for p in test_p]

    # --- 不变量：token 数配平 ---
    toks = {len(r["tokens"]) for r in train_r[:200]}
    toks_te = {len(r["tokens"]) for r in test_r[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"

    # --- 不变量：测试基质确有生成器产出（防生成器静默退化）---
    assert sum(1 for _ in range(100) if Gen(sub_te, seed=7).make(DEPTH)) > 50, \
        f"{test_kind}: test substrate yield too low"

    c3_te, eff_te = c_eff(sub_te["assign"], 3)
    c3_tr, eff_tr = c_eff(sub_tr["assign"], 3)

    vocab = build_vocab(train_r + test_r)
    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    return {"arm": "E4", "train_kind": "typed", "test_kind": test_kind,
            "overlap": sum(1 for a, b in zip(sub_te["assign"], TYPED_ASSIGN)
                           if a == b),
            "n_rel": sub_tr["n_rel"], "n_train": n_train, "seed": seed,
            "acc": acc, "steps": steps, "vocab": len(vocab),
            "tok": toks.pop(),
            "branch_tr": round(sub_tr["branching"], 2),
            "branch_te": round(sub_te["branching"], 2),
            "C3_tr": c3_tr, "C3_te": c3_te,
            "Ceff3_tr": eff_tr, "Ceff3_te": eff_te,
            "secs": round(time.time() - t0, 1)}


def job(spec):
    try:
        return run_one(*spec)
    except Exception:
        import traceback
        return {"acc": float("nan"), "test_kind": spec[0],
                "n_train": spec[1], "seed": spec[2],
                "error": traceback.format_exc()[-400:]}


def preflight():
    print("=" * 72)
    print("PREFLIGHT  —  证明「签名表不变」与「结构变」真的解耦")
    print("=" * 72)
    c3t, eft = c_eff(TYPED_ASSIGN, 3)
    print(f"  typed (baseline): C(3)={c3t}  C_eff(3)={eft}  "
          f"branching={2.00}  assign={TYPED_ASSIGN}")
    print()
    print(f"  {'transform':>14} {'ovl':>4} {'C_eff':>6} {'branch':>7} "
          f"{'pool sizes':>14} {'yield':>8}")
    ok = True
    for k, pools in TRANSFORMS.items():
        s = substrate_with_pools(pools, k)
        c3, eff = c_eff(s["assign"], 3)
        y = sum(1 for _ in range(200) if Gen(s, seed=0).make(DEPTH))
        same_assign = s["assign"] == list(TYPED_ASSIGN)
        sizes = [len(p) for p in s["pools"]]
        pools_differ = s["pools"] != BASE_POOLS
        flag = "OK" if (same_assign and eff == eft and y >= 180) else "!!CHECK"
        if flag != "OK":
            ok = False
        print(f"  {k:>14} {6:4d} {eff:6d} {s['branching']:7.2f} "
              f"{str(sizes):>14} {y:5d}/200{flag}")
    print()
    print("  要求：所有行 ovl=6、C_eff=24、assign 逐项相同。")
    print("  root_swap / chain_reverse 的 pool sizes 或块内容应与基线不同")
    print("  —— 这才是「实体级结构变了」。null_renaming 的 pools 应与基线")
    print("  完全相同（它只重命名 token，不动结构）。")
    print()
    print("  " + ("全部通过。" if ok else "有行未通过，见!!CHECK。"))
    print()
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--ns", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="../results/e4_decouple.jsonl")
    args = ap.parse_args()
    NS_ = [int(x) for x in args.ns.split(",")] if args.ns else NS

    if not preflight():
        print("preflight 未通过，不启动 run。")
        return
    if args.dry_run:
        print("--dry-run：到此为止。")
        return

    out = os.path.abspath(args.out if os.path.isabs(args.out)
                         else os.path.join(HERE, args.out))
    specs = [(k, n, sd) for k in TRANSFORMS
             for n, sd in itertools.product(NS_, range(args.seeds))]
    specs.sort(key=lambda x: (x[1], x[0]))

    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("test_kind"), r.get("n_train"),
                              r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    total = len(TRANSFORMS) * len(NS_) * args.seeds
    print(f"E4 jobs = {len(specs)} (of {total})  seeds={args.seeds}")
    print(f"out = {out}\n", flush=True)

    t0 = time.time()
    nd = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", encoding="utf-8") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            nd += 1
            el = time.time() - t0
            print(f"[{nd}/{len(specs)}] {r.get('test_kind','?'):>14} "
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | "
                  f"ETA {el/nd*(len(specs)-nd)/60:.1f}m", flush=True)
    print("done ->", out)


if __name__ == "__main__":
    main()