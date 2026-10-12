"""
surface_fix2.py — 正确版本的 S1 重测：id 分配与表面身份解耦。

前两次尝试为什么都失败
----------------------
原设计 : build_vocab 按出现顺序分配 id -> 表面间输入逐位相同 -> 重言式
surface_fix : id 分块但按表面顺序 -> id 位置与表面共变 -> 混淆
              （控制实验证实：同一表面换 id 块位置，n=4000 准确率
                在 0.1675–1.0000 间波动，与种子噪声同量级）

正确做法
--------
id 分配是**无关参数**，必须被边缘化。本脚本用 **6x6 循环拉丁方**：

    seed s, surface i  ->  id 块 slot = (i + s) mod 6

于是 6 个种子走完后，**每个表面恰好经历全部 6 个 id 区间各一次**。
slot 被完全配平，surface 主效应与 slot 主效应可分离。

判据
----
* surface 主效应 ≈ 0 而 slot 主效应显著 -> 符号身份确实无关，S1 成立
* surface 主效应显著                    -> 符号身份有影响，S1 需下调

用法
    python surface_fix2.py --seeds 6 --workers 8
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


def slot_of(surface, seed):
    """6x6 cyclic Latin square: every surface meets every slot exactly once
    across seeds 0..5."""
    return (NAMES.index(surface) + seed) % 6


def build_shared_vocab(surface, slot):
    """Shared vocab with `surface` placed in block `slot`; other surfaces
    fill the remaining blocks in their natural order."""
    order = [n for n in NAMES if n != surface]
    order.insert(slot, surface)
    v = Vocab()
    sub = build(1)
    probe = Gen(sub, seed=PROBE_SEED).dataset(400, [DEPTH], seed=PROBE_SEED)
    for si, n in enumerate(order):
        s = Surface(n, 6)
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"]); toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (si, t))
    return v, order.index(surface)


def run_one(surface, n_train, seed):
    from model import train_model
    slot = slot_of(surface, seed)
    sub = build(1)
    g_tr = Gen(sub, seed=1000 + seed); g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)

    v, si = build_shared_vocab(surface, slot)
    s = Surface(surface, sub["n_rel"])
    key = lambda t: "%d\x00%s" % (si, t)

    def enc(ps):
        out = []
        for p in ps:
            r = s.render(p)
            out.append({"tokens": [key(t) for t in r["tokens"]],
                        "target": [key(r["target"][0])]})
        return out

    tr, te = enc(train_p), enc(test_p)
    toks = {len(r["tokens"]) for r in tr[:200]}
    toks_te = {len(r["tokens"]) for r in te[:200]}
    assert len(toks) == 1 and toks == toks_te, f"parity: {toks} vs {toks_te}"

    t0 = time.time()
    _, acc, steps = train_model(v, tr, te, epochs=1, batch=32, lr=3e-4, seed=seed)
    return {"arm": "S_fix2", "surface": surface, "block_slot": slot,
            "surface_index": NAMES.index(surface), "n_rel": sub["n_rel"],
            "n_train": n_train, "seed": seed, "acc": acc,
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
    ap.add_argument("--out", default="results/surface_fix2.jsonl")
    args = ap.parse_args()
    if args.ns:
        NS[:] = [int(x) for x in args.ns.split(",")]

    print("design: slot = (surface_index + seed) mod 6   [6x6 Latin square]")
    print(f"{'surface':>8}" + "".join(f"{'s'+str(s):>5}" for s in range(args.seeds)))
    for n in NAMES:
        print(f"{n:>8}" + "".join(f"{slot_of(n,s):>5}" for s in range(args.seeds)))
    print()

    specs = [(s_, n, sd) for s_ in NAMES
             for n, sd in itertools.product(NS, range(args.seeds))]
    specs.sort(key=lambda x: (x[1], x[0], x[2]))
    done = set()
    if os.path.exists(args.out):
        for ln in open(args.out):
            try:
                r = json.loads(ln)
                done.add((r["surface"], r["n_train"], r["seed"]))
            except Exception:
                pass
    specs = [s for s in specs if s not in done]
    total = len(NAMES) * len(NS) * args.seeds
    print(f"jobs = {len(specs)} (of {total})  workers = {args.workers}\n", flush=True)

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
                  f"slot={r.get('block_slot','?')} n={r.get('n_train','?'):>5} "
                  f"s={r.get('seed','?')} acc={r['acc']:.3f} | ETA {eta/60:.1f}m",
                  flush=True)
    print("done ->", args.out)


if __name__ == "__main__":
    main()
