#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cross_surface.py
================
§6 的镜像检验：原文只测了**跨基质**迁移（变类型结构、同表面 en），
没有测**跨表面**迁移（同基质、变符号系统）。后者才是「符号特化」读法的
直接判决性检验。

为什么要补这个实验
------------------
§6 的结论是「模型学到的是 token 串到类型转移的符号级映射」。
该结论是从跨基质迁移的证据推出的，但那些证据里始终有一个恒定的因子——
表面（en）。存在一个同样与该结论相容的替代解释：

    替代解释M：模型学到的是**基质结构**（类型转移图），
              但绑定在 en 这一具体 token 串上。
              => 跨基质迁移失败是因为基质变了，与表面无关。
              => 跨表面迁移应当**成功**（基质没变）。

而 §6 的原解释S：
    模型学到的是**符号级**映射（token 串 → 类型转移）。
              => 跨表面迁移也应当失败（token 串全变了）。

于是跨表面迁移是一个真正的判决性实验：
    跨表面迁移失败 =>  支持 S（符号特化），§6 结论稳固
    跨表面迁移成功 =>  支持 M，原§6 的机制归因错误，需改写

设计
----
训练臂与测试臂各自独立指定表面，底层问题（substrate + 样本索引）完全相同：

    train surface σ_tr, test surface σ_te, 基质固定 mult=1

四类格点：
    (a) 行内基线   σ_tr → σ_tr    上界参照
    (b) 跨表面     σ_tr → σ_te    ★ 判决性
    (c) 自置换     σ_tr → σ_tr_relperm   语义层对照（只换标签对应）
    (d) 跨表面对照σ_tr_relperm → σ_te_relperm  语义与表面同时变

其中 (b) 与 (a) 的差 = 纯表面迁移代价；
(c) 与 (a) 的差 = 纯语义置换代价（池不变）；
(d)−(c) 与 (b)−(a) 的比较回答「表面代价是否被语义置换放大」。

编码约束
--------
跨表面时两侧 token 串不同，因此**词表必须联合建立**。
这引入一个新的自由度（两个表面各自的 id 区间），故：
    - 训练侧表面固定落在 slot 0，测试侧表面按拉丁方轮转
    - 训练/测试的序列长度严格配平（都是 46 token）
    - 报告时同时给出「同表面」格点作为配平的上界参照
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

from surfaces import Surface
from substrate2 import build as _build, Gen
from model import train_model, Vocab

DEPTH = 3
N_TEST = 400
N_SEEDS = 6
REAL = ["zh", "en", "lisp", "math", "code", "alien"]


# ------------------------------------------------------- 表面工厂
def base_of(name):
    if name.endswith("_relperm"):
        return name[:-len("_relperm")]
    return name


def make_surface(name, n_rel):
    """X_relperm = X 池内洗牌关系标签（token 集合不变）。"""
    if name.endswith("_relperm"):
        b = base_of(name)
        s = Surface(b, n_rel)
        rng = random.Random(777 + n_rel * 13 + hash(b) % 997)
        sh = list(s.rel)
        rng.shuffle(sh)
        s.rel = sh
        return s
    return Surface(name, n_rel)


# 格点定义：(训练表面, 测试表面)
#
# 只保留判决性格点。全部 6×6 = 36 个跨表面对虽然信息最全，但
# 648 次运行在 CPU 上约需 6.5 小时。这里按「判决一个二选一」的原则裁剪：
#
#   判决问题：跨表面迁移是否失败？
#     失败=> 支持 §6 的「符号特化」，原结论稳固
#     成功 => 支持「基质结构 + en 绑定」这一替代解释，§6 需改写
#
#   为此只需要：
#     (a) 行内基线 6 个          —— 上界参照
#     (b) 有向跨表面 6 个         —— 环形：zh->en->lisp->math->code->alien->zh
#         环形设计使每个表面恰好当一次训练面与一次测试面，
#         且训练面与测试面总是不同表面，避免同池泄漏。
#     (c) 池内置换 6 个（X -> X_relperm）—— 语义层对照，用于把
#         「换符号系统」与「换语义对应」两种代价分开
#     (d) 反向跨表面 3 个         —— 检验方向不对称
PAIRS = []
for _t in REAL:
    PAIRS.append((_t, _t))# (a)
_RING = ["zh", "en", "lisp", "math", "code", "alien"]
for _i, _t in enumerate(_RING):
    PAIRS.append((_t, _RING[(_i + 1) % len(_RING)]))     # (b) 环形
for _t in REAL:
    PAIRS.append((_t, _t + "_relperm"))                   # (c)
for _i, _t in enumerate(_RING[:3]):
    PAIRS.append((_RING[(_i + 1) % len(_RING)], _t))     # (d) 反向
PAIRS = sorted(set(PAIRS))
ALL_ARMS = sorted(set([a for p in PAIRS for a in p]))


def build_joint_vocab(train_arm, test_arm, n_rel, n_test=N_TEST):
    """联合词表：训练侧落slot 0，测试侧落 slot 1，其余表面填2..。"""
    order = [train_arm, test_arm] + [a for a in ALL_ARMS
                                     if a not in (train_arm, test_arm)]
    order = list(dict.fromkeys(order))
    v = Vocab()
    probe_sub = _build(max(1, n_rel // 6))
    probe = Gen(probe_sub, seed=4242).dataset(n_test, [DEPTH], seed=4242)
    for si, nm in enumerate(order):
        s = make_surface(nm, n_rel)
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"])
            toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (si, t))
    return v, order.index(train_arm), order.index(test_arm)


def enc(problems, arm, n_rel, vocab, slot_index):
    s = make_surface(arm, n_rel)
    key = lambda t: "%d\x00%s" % (slot_index, t)
    return [{"tokens": [key(t) for t in s.render(p)["tokens"]],
             "target": [key(s.render(p)["target"][0])]}
            for p in problems]


def run_one(train_arm, test_arm, n_train, seed):
    sub = _build(1)
    n_rel = sub["n_rel"]
    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert len(train_p) == n_train
    assert len(test_p) == N_TEST

    vocab, si_tr, si_te = build_joint_vocab(train_arm, test_arm, n_rel)
    train_r = enc(train_p, train_arm, n_rel, vocab, si_tr)
    test_r = enc(test_p, test_arm, n_rel, vocab, si_te)

    # token 数配平：两侧序列长度必须一致，否则算力不可比
    lt = {len(r["tokens"]) for r in train_r[:200]}
    le = {len(r["tokens"]) for r in test_r[:200]}
    assert lt == le, f"train/test length mismatch {lt} {le}"

    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    return {
        "arm": "XS", "train_surface": train_arm, "test_surface": test_arm,
        "train_base": base_of(train_arm), "test_base": base_of(test_arm),
        "kind": ("same" if train_arm == test_arm else
                 ("perm_only" if train_arm == test_arm.replace("_relperm", "_relperm")
                  and base_of(train_arm) == base_of(test_arm) else
                  ("cross_perm" if train_arm.endswith("_relperm")
                   and test_arm.endswith("_relperm") else "cross"))),
        "n_rel": n_rel, "n_train": n_train, "seed": seed,
        "acc": acc, "steps": steps, "vocab": len(vocab),
        "tok": lt.pop(), "secs": round(time.time() - t0, 1),
    }


def job(spec):
    tr, te, n, s = spec
    try:
        return run_one(tr, te, n, s)
    except Exception as e:
        import traceback
        return {"arm": "XS", "train_surface": tr, "test_surface": te,
                "n_train": n, "seed": s, "acc": None,
                "error": "%s: %s" % (type(e).__name__, e),
                "tb": traceback.format_exc()[-600:]}


def preflight():
    sub = _build(1)
    n_rel = sub["n_rel"]
    probe = Gen(sub, seed=4242).dataset(50, [DEPTH], seed=4242)
    print("=" * 72)
    print("cross_surface preflight")
    print("=" * 72)
    print(f"\n格点数：{len(PAIRS)} 对 (train, test) × n × 种子")
    kinds = {}
    for p in PAIRS:
        k = ("same" if p[0] == p[1] else
             ("perm_only" if base_of(p[0]) == base_of(p[1]) else "cross"))
        kinds[k] = kinds.get(k, 0) + 1
    print(f"  同表面 {kinds.get('same',0)}  池内置换 {kinds.get('perm_only',0)}  "
          f"跨表面 {kinds.get('cross',0)}")
    print("\n跨表面对（判据性）：")
    for p in PAIRS:
        if p[0] != p[1] and base_of(p[0]) == base_of(p[1]):
            print(f"  {p[0]:14s} -> {p[1]:14s}  (池不变，只换语义对应)")
    print("\n跨表面池对（判据性）：共 %d 个"
          % sum(1 for p in PAIRS
                if p[0] != p[1] and base_of(p[0]) != base_of(p[1])))
    print("\n序列长度配平：")
    for nm in sorted(ALL_ARMS):
        s = make_surface(nm, n_rel)
        r = s.render(probe[0])
        print(f"  {nm:16s} tokens={r['n_tokens']:3d}", end="")
        if sorted(ALL_ARMS).index(nm) % 3 == 2:
            print()
    print()
    print("所有表面 token 数必须一致，否则迁移代价混入算力差异。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ns", type=int, nargs="*", default=[5000, 6500])
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--quick", action="store_true",
                    help="只跑同表面 + 环形跨表面，跳过置换对照")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "XS.jsonl"))
    ap.add_argument("--preflight", action="store_true")
    args = ap.parse_args()

    if args.preflight:
        preflight()
        return

    specs = [(tr, te, n, s) for (tr, te) in PAIRS
             for n in args.ns for s in range(args.seeds)]
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
                done.add((r["train_surface"], r["test_surface"],
                          r["n_train"], r["seed"]))
    todo = [s for s in specs
            if (s[0], s[1], s[2], s[3]) not in done]
    print(f"总 {len(specs)}  已完成 {len(done)}  待跑 {len(todo)}", flush=True)
    if not todo:
        print("全部完成")
        return

    t0 = time.time()
    n = 0
    with open(args.out, "a") as fh, ProcessPoolExecutor(
            max_workers=args.workers) as ex:
        futs = {ex.submit(job, sp): sp for sp in todo}
        for fu in as_completed(futs):
            r = fu.result()
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if r.get("acc") is None:
                print(f"[{n}/{len(todo)}] FAIL {r['train_surface']}->"
                      f"{r['test_surface']} {r.get('error')}", flush=True)
            else:
                el = time.time() - t0
                eta = el / n * (len(todo) - n)
                print(f"[{n}/{len(todo)}] {r['train_surface']:12s}->"
                      f"{r['test_surface']:12s} n={r['n_train']} s={r['seed']} "
                      f"acc={r['acc']:.4f} {r['secs']:5.1f}s "
                      f"ETA {eta/60:.1f}min", flush=True)


if __name__ == "__main__":
    main()