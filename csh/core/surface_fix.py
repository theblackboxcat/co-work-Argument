"""
surface_fix.py — 重测 S1，但让 token 身份真正进入模型输入。

问题（见 S1_DEFECT.md）
----------------------
原设计用 build_vocab 按"首次出现顺序"分配 id。因每条事实恰 5 token、
query 模板固定，角色结构在所有表面间相同，导致 zh/math/alien 拿到
逐 token 相同的数值输入 —— 实测三者训练权重逐位相同（diff = 0）。
原 S1 的 "6 个表面共享阈值" 因此部分是重言式。

修复
----
建一个**跨全部表面的共享词表**，每个表面的 token 落在互不相交的 id
区间（区间内按 token 字符串排序，与出现顺序无关）。修复后 zh/math/
alien 的 id 序列 0/30 相同（原为 30/30）。

判据
----
* 修复后各表面阈值**仍重合** -> "符号身份不影响阈值"成为真正的经验结论。
* 修复后阈值**分离**       -> 原结论强度需下调。

配平
----
只改 id 分配，不改序列长度、事实条数、深度、实体数、训练步数。

用法
----
    python surface_fix.py --seeds 6 --workers 11
    python surface_fix.py --seeds 6 --workers 11 --ns 3000,4000,5000
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

from surfaces import Surface
from substrate2 import Gen, build
from model import Vocab

NAMES = ["zh", "en", "lisp", "math", "code", "alien"]
DEPTH = 3
N_TEST = 400
NS = [2000, 3000, 4000, 5000, 6500]
PROBE_SEED = 4242


def build_shared_vocab():
    """Deterministic id map shared by ALL surfaces.

    Each surface owns a disjoint contiguous id block; inside a block tokens
    are added in SORTED order, so the assignment never depends on which
    surface is being trained or on first-appearance order.
    """
    v = Vocab()
    sub = build(1)
    probe = Gen(sub, seed=PROBE_SEED).dataset(400, [DEPTH], seed=PROBE_SEED)
    for si, n in enumerate(NAMES):
        s = Surface(n, 6)
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"]); toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (si, t))
    return v


def run_one(surface, n_train, seed):
    from model import train_model

    sub = build(1)
    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)

    n_rel = sub["n_rel"]
    si = NAMES.index(surface)
    s = Surface(surface, n_rel)
    key = lambda t: "%d\x00%s" % (si, t)

    def enc(problems):
        out = []
        for p in problems:
            r = s.render(p)
            out.append({"tokens": [key(t) for t in r["tokens"]],
                        "target": [key(r["target"][0])]})
        return out

    tr = enc(train_p)
    te = enc(test_p)

    toks = {len(r["tokens"]) for r in tr[:200]}
    toks_te = {len(r["tokens"]) for r in te[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"

    v = build_shared_vocab()
    # every token we will encode must exist in the shared vocab
    missing = [t for r in tr[:50] for t in r["tokens"] if t not in v.stoi]
    assert not missing, f"tokens missing from shared vocab: {missing[:5]}"

    t0 = time.time()
    _, acc, steps = train_model(v, tr, te, epochs=1, batch=32, lr=3e-4, seed=seed)
    return {"arm": "S_fix", "surface": surface, "surface_index": si,
            "n_rel": n_rel, "n_train": n_train, "seed": seed, "acc": acc,
            "steps": steps, "vocab": len(v), "tok": toks.pop(),
            "secs": round(time.time() - t0, 1)}


def job(spec):
    try:
        return run_one(*spec)
    except Exception:
        import traceback
        return {"acc": float("nan"), "surface": spec[0], "n_train": spec[1],
                "seed": spec[2], "error": traceback.format_exc()[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--ns", type=str, default=None)
    ap.add_argument("--out", default="results/surface_fix.jsonl")
    args = ap.parse_args()
    if args.ns:
        NS[:] = [int(x) for x in args.ns.split(",")]

    # preflight: prove ids are now disjoint AND that surfaces differ
    sv = build_shared_vocab()
    sub = build(1)
    ps = Gen(sub, seed=1000).dataset(30, [DEPTH], seed=0)

    def enc(n):
        si = NAMES.index(n); s = Surface(n, 6)
        return [[sv.stoi["%d\x00%s" % (si, t)] for t in s.render(p)["tokens"]]
                for p in ps]

    print(f"preflight  shared vocab = {len(sv)}")
    z = enc("zh")
    for n in NAMES[1:]:
        same = sum(1 for a, b in zip(z, enc(n)) if a == b)
        ids = sorted({i for row in enc(n) for i in row})
        print(f"  zh vs {n:6s}: {same:2d}/30 identical ids   "
              f"range {ids[0]}..{ids[-1]}")
    print("  (all must be 0/30 with disjoint ranges)\n")

    specs = [(s_, n, sd) for s_ in NAMES
             for n, sd in itertools.product(NS, range(args.seeds))]
    specs.sort(key=lambda x: (x[1], x[0], x[2]))

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("surface"), r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    total = len(NAMES) * len(NS) * args.seeds
    print(f"surface-fix jobs = {len(specs)} (of {total})  seeds = {args.seeds}  "
          f"workers = {args.workers}\n", flush=True)

    t0 = time.time(); nd = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "a") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n"); fh.flush()
            nd += 1
            el = time.time() - t0
            eta = el / nd * (len(specs) - nd)
            print(f"[{nd}/{len(specs)}] {r.get('surface','?'):6s} "
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | ETA {eta/60:.1f}m", flush=True)
    print("done ->", args.out)


if __name__ == "__main__":
    main()
