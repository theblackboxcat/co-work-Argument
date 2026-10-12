"""
arm_k_null.py — E6：臂 K 各复杂度水平补null 对照

对应判别书 §7（E6），修正其编码前提。
=====================================================================

要堵的洞
--------
论文 §8 边界四原文：

  「臂 K 未在各复杂度水平重跑 null 对照。因此 K-A 的结论强度低于
    臂 S 的 S1/S2：我们无法排除复杂度臂上同样存在 null 效应。」

为什么必须有null
----------------
臂 S 的 S2 之所以能承重，是因为 relperm/entperm 摧毁词义却不改变结构，
阈值不动，于是"平坦"是关于**结构**的陈述而非关于"这些符号系统同样难"。
臂 K 缺了这个对照——如果符号置换在臂 K 上也免费，我们无法判断 K-A 的
平坦是不是同一回事。

**但直接照判别书§7.2 跑会得到零信息量。**
`final.py` 用 `build_vocab`（按首次出现顺序分配 id）。在臂 K 的每个
mult 水平上，en 与 relperm 的关系结构完全相同、事实数相同、query模板
相同，故二者拿到逐 token 相同的 id。实测在 mult=1（臂 S）上：

    en == relperm == entperm    30/30 格点逐位相同

`final_knull.py` 若沿用 `build_vocab`，产出的 null 会与 en 逐位相同——
**一个不改变任何东西的对照，且连数值都不改变**。

本脚本的处置
------------
沿用 `surface_fix.py` 的**跨表面共享词表**：每个表面占一段互不相交的
id 区间，区间内按 token 字符串排序。这样 token 身份真正进入模型输入，
relperm 才是真正的干预。

配平
----
- 与 final.py 完全一致：5 tok/fact、8 facts、depth 3、18 实体、
  n_test=400、batch=32、lr=3e-4、epochs=1、n_grid=[2000..6500]。
- 唯一变化：vocab 构造方式（共享 id 区间）+ 增加 relperm/entperm 两臂。
- **vocab 大小会变**（共享词表 ~169 vs 臂 S 的 31）。这是允许的，且必须
  在论文里显式说明：本实验允许 vocab 变化，因为要测的正是"符号身份
  进入模型后阈值是否移动"，不改变 id 分配就无法构造这个干预。

网格
----
mult ∈ {2,3,4} × {en, relperm, entperm} × 5 n × 6 seeds = 270 runs

mult=1 不跑——它就是 `surface_fix.jsonl` 里的 en/relperm/entperm，
已由 E0 覆盖。避免重复计算。

用法
----
    python arm_k_null.py --seeds 6 --workers 10
    python arm_k_null.py --seeds 6 --workers 10 --mults 2,3,4

断点续跑：已存在的 (mult, surface, n_train, seed) 自动跳过。
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
sys.path.insert(0, PKG)

from surfaces import Surface, PermutedSurface          # noqa: E402
from substrate2 import build, Gen, c_eff               # noqa: E402
from model import Vocab, train_model                   # noqa: E402

DEPTH = 3
N_TEST = 400
NS = [2000, 3000, 4000, 5000, 6500]
SURFACES = ["en", "relperm", "entperm"]
PROBE_SEED = 4242

# 共享词表按**表面名**分配 id 区间，与 mult 无关 —— 保证同一表面在
# 不同 mult 下拿到同一段id 区间，避免 id 分配随复杂度漂移。
SURF_INDEX = {s: i for i, s in enumerate(SURFACES)}


def make_surface(name, n_rel):
    if name == "relperm":
        return PermutedSurface("en", n_rel, mode="rel")
    if name == "entperm":
        return PermutedSurface("en", n_rel, mode="ent")
    return Surface(name, n_rel)


def build_shared_vocab(mults):
    """跨表面共享词表。每个表面一段互不相交的 id 区间。

    与 surface_fix.py 同法，但**对所有 mult 取并集**，使同一表面的
    token 在任何复杂度水平下都落在同一区间。
    """
    v = Vocab()
    for mult in mults:
        sub = build(mult)
        probe = Gen(sub, seed=PROBE_SEED).dataset(400, [DEPTH], seed=PROBE_SEED)
        for name in SURFACES:
            si = SURF_INDEX[name]
            s = make_surface(name, sub["n_rel"])
            toks = set()
            for p in probe:
                r = s.render(p)
                toks.update(r["tokens"])
                toks.update(r["target"])
            for t in sorted(toks):
                v.add("%d\x00%s" % (si, t))
    return v


def run_one(mult, surface, n_train, seed, _unused=None):
    import latin
    sub = build(mult)
    n_rel = sub["n_rel"]
    names = SURFACES                        # ["en","relperm","entperm"]
    slot = latin.slot_of(names, surface, seed)        # 拉丁方：随 seed 轮转
    # n_rel 必须传实际值（mult=2/3/4 -> 12/18/24），否则词表缺 rel6..relN
    vocab, si = latin.build_vocab(names, surface, slot, depth=DEPTH,
                                 n_test=N_TEST, n_rel=n_rel)
    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)

    tr = latin.encode(train_p, surface, n_rel, vocab, si)
    te = latin.encode(test_p, surface, n_rel, vocab, si)

    # --- 不变量 1：token 数配平（跨表面必须一致）---
    toks = {len(r["tokens"]) for r in tr[:200]}
    toks_te = {len(r["tokens"]) for r in te[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"

    # --- 不变量 2：训练/测试集大小足量（防生成器静默退化）---
    assert len(tr) == n_train, f"train set short: {len(tr)} < {n_train}"
    assert len(te) == N_TEST, f"test set short: {len(te)} < {N_TEST}"

    # --- 不变量 3：所有 token 在词表内 ---
    missing = [t for r in tr[:50] for t in r["tokens"] if t not in vocab.stoi]
    assert not missing, f"tokens missing: {missing[:5]}"

    c3, eff = c_eff(sub["assign"], 3)

    # --- 不变量 4：C_eff(3) 恒为 24（臂 K 的核心不变量）---
    assert eff == 24, f"C_eff(3)={eff}, expected 24"

    t0 = time.time()
    _, acc, steps = train_model(vocab, tr, te, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    return {"arm": "K_null", "mult": mult, "surface": surface,
            "block_slot": slot,
            "n_rel": n_rel, "n_train": n_train, "seed": seed, "acc": acc,
            "steps": steps, "vocab": len(vocab), "tok": toks.pop(),
            "branching": sub["branching"], "C3": c3, "C_eff3": eff,
            "secs": round(time.time() - t0, 1)}


_VOCAB = None
_MULTS = None


def _init(mults):
    global _VOCAB, _MULTS
    _MULTS = mults
    _VOCAB = build_shared_vocab(mults)


def job(spec):
    mult, surface, n_train, seed = spec
    try:
        return run_one(mult, surface, n_train, seed, _VOCAB)
    except Exception:
        import traceback
        return {"acc": float("nan"), "mult": mult, "surface": surface,
                "n_train": n_train, "seed": seed,
                "error": traceback.format_exc()[-400:]}


def preflight(mults):
    """跑之前先证明 null 干预真的进入了模型输入。"""
    print("=" * 70)
    print("PREFLIGHT")
    print("=" * 70)
    v = build_shared_vocab(mults)
    print(f"  shared vocab = {len(v)}")

    for mult in mults:
        sub = build(mult)
        ps = Gen(sub, seed=1000).dataset(30, [DEPTH], seed=0)

        def enc(name):
            si = SURF_INDEX[name]
            s = make_surface(name, sub["n_rel"])
            return [[v.stoi["%d\x00%s" % (si, t)] for t in s.render(p)["tokens"]]
                    for p in ps]

        e = enc("en")
        line = f"  mult={mult} (n_rel={sub['n_rel']}):"
        for name in ("relperm", "entperm"):
            same = sum(1 for a, b in zip(e, enc(name)) if a == b)
            flag = "OK" if same == 0 else f"!! {same}/30 identical"
            line += f"  en vs {name}: {same}/30 [{flag}]"
        print(line)

    print()
    print("  要求：所有 null 对与 en 的 identical 必须为 0/30。")
    print("  若非 0，说明 id 分配退化了，本实验退化为'同一输入算两次'。")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--mults", type=str, default="2,3,4")
    ap.add_argument("--ns", type=str, default=None,
                    help="覆盖 n 网格，逗号分隔。T2 用它扩展上界："
                         "原网格 [2000..6500] 有 4/6 种子的阈值压在 6500 "
                         "（右删失），扩展后阈值才可测。")
    ap.add_argument("--out", default="../results/arm_k_null.jsonl")
    args = ap.parse_args()

    mults = [int(x) for x in args.mults.split(",")]
    global NS
    if args.ns:
        NS = [int(x) for x in args.ns.split(",")]
    out = args.out if os.path.isabs(args.out) else os.path.join(HERE, args.out)
    out = os.path.abspath(out)

    preflight(mults)

    specs = [(m, s, n, sd)
             for m, s, n, sd in itertools.product(mults, SURFACES, NS,
                                                  range(args.seeds))]
    specs.sort(key=lambda x: (x[2], x[0], x[1], x[3]))

    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("mult"), r.get("surface"),
                              r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    total = len(mults) * len(SURFACES) * len(NS) * args.seeds
    print(f"  jobs = {len(specs)} (of {total})   seeds={args.seeds}  "
          f"workers={args.workers}")
    print(f"  out  = {out}\n", flush=True)

    t0 = time.time()
    nd = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", encoding="utf-8") as fh, \
            ProcessPoolExecutor(args.workers, mp_context=ctx,
                                 initializer=_init, initargs=(mults,)) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            nd += 1
            el = time.time() - t0
            eta = el / nd * (len(specs) - nd)
            print(f"[{nd}/{len(specs)}] mult={r.get('mult','?')} "
                  f"{str(r.get('surface','?')):>8} n={r.get('n_train','?'):>5} "
                  f"s={r.get('seed','?')} acc={r['acc']:.3f} | "
                  f"ETA {eta/60:.1f}m", flush=True)
    print("done ->", out)


if __name__ == "__main__":
    main()