#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pool_orthogonal.py
==================
把「语义」与「词法池身份」两个因子正交分离。

诊断依据
--------
`analyze_distributional.py` + `collision_geometry.py` 在既有286 runs 上发现：

    en / relperm / entperm   共用en 词法池   平均 acc 0.4915
    zh / lisp / math / code / alien         平均 acc 0.3833
                                          差          +0.1082

原null 对照（relperm / entperm）都是 **en 池**的置换。于是「真实 vs null」
这一对比同时变化了两个因子：

    (A) 语义是否存在      —— 论文想测的（CSH 的核心）
    (B) 词法池是哪个       —— 未受控的混淆项

6/6 同 slot 严格配对下真实表面一致地**更慢**，这不是 (A) 的效应，
而是 (B) 的效应：模型在 en 池上学得更快，与该表面是否承载人类感官语义无关。
若不分离 (B)，§4 的全部阴性结论都不能归因于语义。

设计
----
为**每一个**真实表面生成它自己的关系标签置换对照：

    12 个臂 = 6 个真实表面 × {原样, rel 置换}

              zh        zh_relperm
              en        en_relperm
              lisp      lisp_relperm
              math      math_relperm
              code      code_relperm
              alien     alien_relperm

`X_relperm` =把表面 X 的关系标签在 X 自己的词法池内部重新洗牌，
**池内的 token 集合逐个不变**，只有「哪个符号对应哪个类型转移」被打乱。

于是：
    (A) 语义  = 原样 vs 自身置换   —— 池不变，只变语义  => 隔离 (A)
    (B) 池    = 跨表面比较         —— 语义条件可对齐

拉丁方：12 个臂=> 种子数须 >= 12 才能完整配平。本实验用 13 个种子
的前12 个…… 实为**恰好 12 个**种子（0..11），使每个臂恰好遍历
12 个 slot 各一次，无重复、无遗漏。这同时修掉既有 S2L 的
slot 奇偶混叠问题（那里 8 臂只用了 4 个奇数种子）。

规模
----
13 臂 × 4 个 n × 14 种子 = 728 runs。按既有吞吐（n=6500 约 65 s，
平均约 35 s/run，4 核并行）估计约 2.2 小时。
"""
import os
import sys
import time
import json
import random
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import latin
from surfaces import Surface
from substrate2 import build as _build, Gen
from model import train_model

# ---------------------------------------------------------------- 常量
REAL = ["zh", "en", "lisp", "math", "code", "alien"]

DEPTH = 3
N_TEST = 400
NS = [3000, 4000, 5000, 6500]
N_SEEDS = 12            # == len(ARMS) = 12 的最小完全配平数（多一个即产生重复）
PERM_SEED_BASE = 777# 与既有 PermutedSurface 同源，便于对照

ARMS = []
for _r in REAL:
    ARMS.append(_r)
    ARMS.append(_r + "_relperm")
assert len(ARMS) == 12, len(ARMS)


# ------------------------------------------------------- 表面工厂
def make_surface(name, n_rel):
    """支持 `X_relperm`：把表面 X 的关系标签在 X 池内洗牌。

    与 `surfaces.PermutedSurface` 的差别在于 base 表面：后者固定用en，
    这正是本实验要消除的混淆。
    """
    if name.endswith("_relperm"):
        base = name[:-len("_relperm")]
        s = Surface(base, n_rel)
        rng = random.Random(PERM_SEED_BASE + n_rel * 13 + hash(base) % 997)
        shuffled = list(s.rel)
        rng.shuffle(shuffled)
        s.rel = shuffled
        s.mode = "relperm_of_" + base
        return s
    return Surface(name, n_rel)


def make_vocab(names, surface, slot, depth=DEPTH, n_test=N_TEST, n_rel=6):
    """与 latin.build_vocab 同构，但用本文件的 make_surface。"""
    from model import Vocab
    order = [n for n in names if n != surface]
    order.insert(slot, surface)
    v = Vocab()
    mult = max(1, n_rel // 6)
    probe_sub = _build(mult)
    probe = Gen(probe_sub, seed=latin.PROBE_SEED).dataset(
        n_test, [depth], seed=latin.PROBE_SEED)
    for si, nm in enumerate(order):
        s = make_surface(nm, n_rel)
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"])
            toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (si, t))
    return v, order.index(surface)


def encode(problems, surface_name, n_rel, vocab, slot_index):
    s = make_surface(surface_name, n_rel)
    key = lambda t: "%d\x00%s" % (slot_index, t)
    return [{"tokens": [key(t) for t in s.render(p)["tokens"]],
             "target": [key(s.render(p)["target"][0])]}
            for p in problems]


# ------------------------------------------------------- 单run
def run_one(arm, n_train, seed):
    sub = _build(1)
    n_rel = sub["n_rel"]
    slot = (ARMS.index(arm) + seed) % len(ARMS)

    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert len(train_p) == n_train, f"train short {len(train_p)}/{n_train}"
    assert len(test_p) == N_TEST, f"test short {len(test_p)}/{N_TEST}"

    vocab, si = make_vocab(ARMS, arm, slot, n_rel=n_rel)
    train_r = encode(train_p, arm, n_rel, vocab, si)
    test_r = encode(test_p, arm, n_rel, vocab, si)

    # ---- 不变量 1：token 数配平（序列长度与算力逐臂相同）
    toks = {len(r["tokens"]) for r in train_r[:200]}
    toks_te = {len(r["tokens"]) for r in test_r[:200]}
    assert len(toks) == 1 and toks == toks_te, f"token parity: {toks} {toks_te}"

    # ---- 不变量 2：池内token 集合必须与原表面逐个相同
    # 这是本实验的核心不变式：X_relperm 只改标签->类型的对应，
    # 不增删任何 token。若不等，则 (A)/(B) 分离失败。
    if arm.endswith("_relperm"):
        base = arm[:-len("_relperm")]
        s0, s1 = Surface(base, n_rel), make_surface(arm, n_rel)
        assert sorted(s0.ent) == sorted(s1.ent), "ent pool changed"
        assert sorted(s0.rel) == sorted(s1.rel), "rel token set changed"
        assert s0.rel != s1.rel, "permutation is a no-op"
        # token 字符串整体集合也必须一致
        t0, t1 = set(), set()
        for p in test_p[:120]:
            r0, r1 = s0.render(p), s1.render(p)
            t0 |= set(r0["tokens"]) | set(r0["target"])
            t1 |= set(r1["tokens"]) | set(r1["target"])
        assert t0 == t1, "surface token multiset changed under permutation"

    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    return {
        "arm": "POOL", "surface": arm,
        "base": arm[:-len("_relperm")] if arm.endswith("_relperm") else arm,
        "is_perm": arm.endswith("_relperm"),
        "block_slot": slot, "arm_index": ARMS.index(arm),
        "n_rel": n_rel, "n_train": n_train, "seed": seed,
        "acc": acc, "steps": steps, "vocab": len(vocab),
        "tok": toks.pop(), "secs": round(time.time() - t0, 1),
    }


def job(spec):
    arm, n_train, seed = spec
    try:
        return run_one(arm, n_train, seed)
    except Exception as e:
        import traceback
        return {"arm": "POOL", "surface": arm, "n_train": n_train, "seed": seed,
                "acc": None, "error": "%s: %s" % (type(e).__name__, e),
                "tb": traceback.format_exc()[-800:]}


# ------------------------------------------------------- preflight
def preflight():
    sub = _build(1)
    n_rel = sub["n_rel"]
    probe = Gen(_build(1), seed=latin.PROBE_SEED).dataset(
        N_TEST, [DEPTH], seed=latin.PROBE_SEED)

    print("=" * 74)
    print("preflight：池 × 语义 正交性检查")
    print("=" * 74)

    ok = True
    print("\n[1] 每个 X_relperm 的 token 字符串集合必须与 X 完全相同")
    for base in REAL:
        s0, s1 = Surface(base, n_rel), make_surface(base + "_relperm", n_rel)
        t0, t1 = set(), set()
        for p in probe:
            r0, r1 = s0.render(p), s1.render(p)
            t0 |= set(r0["tokens"]) | set(r0["target"])
            t1 |= set(r1["tokens"]) | set(r1["target"])
        same = t0 == t1
        changed = s0.rel != s1.rel
        print(f"  {base:6s}-> {base+'_relperm':14s} "
              f"token集合相同={same}  标签已洗牌={changed}  "
              f"|tokens|={len(t0)}")
        ok = ok and same and changed

    print("\n[2] 拉丁方配平：12 种子 vs 12 臂")
    tab = {a: [(ARMS.index(a) + s) % len(ARMS) for s in range(N_SEEDS)]
           for a in ARMS}
    for a in ARMS:
        print(f"  {a:14s} slots={tab[a]}")
    full = all(sorted(v) == list(range(len(ARMS))) for v in tab.values())
    print(f"  种子数 {N_SEEDS} == 臂数 {len(ARMS)}: {N_SEEDS == len(ARMS)}")
    print(f"  每臂 slot 恰好遍历全部 {len(ARMS)} 个: {full}")

    print("\n[3] token 数配平（序列长度逐臂相同）")
    for a in ARMS:
        s = make_surface(a, n_rel)
        r = s.render(probe[0])
        print(f"  {a:14s} tokens={r['n_tokens']:3d} facts={r['n_facts']}", end="  ")
        if ARMS.index(a) % 2 == 1:
            print()
    print()

    print(f"\n结论：正交性 {'通过' if ok else '失败'}")
    print(f"规模：{len(ARMS)} 臂 × {len(NS)} 个 n × {N_SEEDS} 种子 = "
          f"{len(ARMS)*len(NS)*N_SEEDS} runs")
    return ok


# ------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ns", type=int, nargs="*", default=None)
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--out", default=os.path.join(HERE, "results", "POOL.jsonl"))
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()

    if args.preflight:
        preflight()
        return

    ns = args.ns or NS
    specs = [(a, n, s) for a in ARMS for n in ns for s in range(args.seeds)]
    if args.plan:
        for sp in specs:
            print(sp)
        print("total", len(specs))
        return

    done = set()
    if os.path.exists(args.out):
        for ln in open(args.out):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("acc") is not None and r["acc"] == r["acc"] \
                    and "error" not in r:
                done.add((r["surface"], r["n_train"], r["seed"]))

    todo = [s for s in specs if (s[0], s[1], s[2]) not in done]
    print(f"总{len(specs)}  已完成 {len(done)}  待跑 {len(todo)}", flush=True)
    if not todo:
        print("全部完成")
        return

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    t_start = time.time()
    n_done = 0
    with open(args.out, "a") as fh, ProcessPoolExecutor(
            max_workers=args.workers) as ex:
        futs = {ex.submit(job, sp): sp for sp in todo}
        for fu in as_completed(futs):
            r = fu.result()
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            n_done += 1
            if r.get("acc") is None:
                print(f"[{n_done}/{len(todo)}] FAIL {r.get('surface')} "
                      f"n={r.get('n_train')} seed={r.get('seed')} "
                      f"{r.get('error')}", flush=True)
            else:
                el = time.time() - t_start
                eta = el / n_done * (len(todo) - n_done)
                print(f"[{n_done}/{len(todo)}] {r['surface']:14s} "
                      f"n={r['n_train']:5d} seed={r['seed']:2d} "
                      f"acc={r['acc']:.4f} slot={r['block_slot']} "
                      f"{r['secs']:5.1f}s  ETA {eta/60:.1f}min", flush=True)
    print(f"完成，耗时 {(time.time()-t_start)/60:.1f} min -> {args.out}")


if __name__ == "__main__":
    main()