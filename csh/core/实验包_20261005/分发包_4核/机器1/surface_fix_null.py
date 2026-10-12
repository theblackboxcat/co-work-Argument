"""
surface_fix_null.py — 补跑 relperm / entperm（修复后编码）

为什么需要这个
--------------
`surface_fix.py` 的 `NAMES = ["zh","en","lisp","math","code","alien"]`——
**只有 6 个真实表面，没有 null 臂**。所以 180 runs 跑满后：

  * S1（表面不变性）可以判定  ->  已得：CV(log)=0.0141，7/15 配对显著
  * S2（null 落位）**无法判定** -> relperm/entperm 不在数据里

而 S2 恰恰是论文 §6.2 称为「承重检验」的那一条。没有它，修复后的
数据只能支撑 S1，不能支撑 S2。

本脚本用**完全相同的共享 id 区间方案**（`surface_fix.py` 的做法），
把 relperm / entperm 补进来。因为 relperm/entperm 是 PermutedSurface，
与 en 共享实体标签空间但关系标签被置换，用同一个 surface_index 机制
即可保持"token 身份真正进入模型"这个前提。

网格：2 null × 5 n × 6 seeds = 60 runs，与已有 180 runs 同口径
（tok=46、depth 3、18 实体、n_test=400、batch=32、lr=3e-4、epochs=1）。

用法
----
    python surface_fix_null.py --seeds 6 --workers 10
    python surface_fix_null.py --seeds 6 --workers 10 --dry-run
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

from surfaces import Surface, PermutedSurface      # noqa: E402
from substrate2 import build, Gen                   # noqa: E402
from model import Vocab, train_model                # noqa: E402

DEPTH = 3
N_TEST = 400
NS = [2000, 3000, 4000, 5000, 6500]
NULL_ARMS = ["relperm", "entperm"]
PROBE_SEED = 4242

# 与 surface_fix.py 完全一致的 id 区间分配：按SURFACES 全表的下标。
# relperm / entperm 复用 en 的区间号（它们就是 en 的置换版本），
# 这样 8 个表面在 id 空间上互不重叠。
ALL_SURFACES = ["zh", "en", "lisp", "math", "code", "alien"]
SURF_SLOT = {s: i for i, s in enumerate(ALL_SURFACES)}
SURF_SLOT["relperm"] = SURF_SLOT["en"] + 100
SURF_SLOT["entperm"] = SURF_SLOT["en"] + 200


def make_surface(name, n_rel):
    if name == "relperm":
        return PermutedSurface("en", n_rel, mode="rel")
    if name == "entperm":
        return PermutedSurface("en", n_rel, mode="ent")
    return Surface(name, n_rel)


def build_shared_vocab():
    """与 surface_fix.py 同法：按 (slot, token字符串) 排序分配 id。

    8 个表面各占一段互不相交的 id 区间（slot 0..5, 100, 200）。
    """
    v = Vocab()
    sub = build(1)
    probe = Gen(sub, seed=PROBE_SEED).dataset(400, [DEPTH], seed=PROBE_SEED)
    for name in ALL_SURFACES + NULL_ARMS:
        slot = SURF_SLOT[name]
        s = make_surface(name, sub["n_rel"])
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"])
            toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (slot, t))
    return v


def run_one(surface, n_train, seed, shared):
    sub = build(1)
    n_rel = sub["n_rel"]
    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert len(train_p) == n_train and len(test_p) == N_TEST

    slot = SURF_SLOT[surface]
    s = make_surface(surface, n_rel)
    key = lambda t: "%d\x00%s" % (slot, t)

    def enc(problems):
        return [{"tokens": [key(t) for t in s.render(p)["tokens"]],
                 "target": [key(s.render(p)["target"][0])]}
                for p in problems]

    tr, te = enc(train_p), enc(test_p)

    toks = {len(r["tokens"]) for r in tr[:200]}
    toks_te = {len(r["tokens"]) for r in te[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"

    missing = [t for r in tr[:50] for t in r["tokens"] if t not in shared.stoi]
    assert not missing, f"tokens missing: {missing[:5]}"

    t0 = time.time()
    _, acc, steps = train_model(shared, tr, te, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    return {"arm": "S_fix_null", "surface": surface, "slot": slot,
            "n_rel": n_rel, "n_train": n_train, "seed": seed, "acc": acc,
            "steps": steps, "vocab": len(shared), "tok": toks.pop(),
            "secs": round(time.time() - t0, 1)}


_V = None


def _init():
    global _V
    _V = build_shared_vocab()


def job(spec):
    try:
        return run_one(*spec, _V)
    except Exception:
        import traceback
        return {"acc": float("nan"), "surface": spec[0], "n_train": spec[1],
                "seed": spec[2], "error": traceback.format_exc()[-400:]}


def preflight(v):
    """证明 null干预真的进了模型，且与 en 逐位不同。"""
    print("=" * 70)
    print("PREFLIGHT")
    print("=" * 70)
    print(f"  shared vocab = {len(v)}")
    sub = build(1)
    ps = Gen(sub, seed=1000).dataset(30, [DEPTH], seed=0)

    def enc(name):
        slot = SURF_SLOT[name]
        s = make_surface(name, sub["n_rel"])
        return [[v.stoi["%d\x00%s" % (slot, t)] for t in s.render(p)["tokens"]]
                for p in ps]

    e = enc("en")
    for name in NULL_ARMS:
        same = sum(1 for a, b in zip(e, enc(name)) if a == b)
        ids = sorted({i for row in enc(name) for i in row})
        flag = "OK" if same == 0 else f"!! {same}/30"
        print(f"  en vs {name:8s}: {same:2d}/30 identical  "
              f"range {ids[0]}..{ids[-1]}  [{flag}]")
    print()
    print("  要求：0/30。若非 0，null 未真正进入模型，本实验无效。")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="../results/surface_fix_null.jsonl")
    args = ap.parse_args()

    out = os.path.abspath(args.out if os.path.isabs(args.out)
                         else os.path.join(HERE, args.out))
    v = build_shared_vocab()
    preflight(v)
    if args.dry_run:
        print("--dry-run：到此为止。")
        return

    specs = [(s, n, sd) for s, n, sd in
             itertools.product(NULL_ARMS, NS, range(args.seeds))]
    specs.sort(key=lambda x: (x[1], x[0]))

    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("surface"), r.get("n_train"),
                              r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    total = len(NULL_ARMS) * len(NS) * args.seeds
    print(f"  jobs = {len(specs)} (of {total})")
    print(f"  out= {out}\n", flush=True)

    t0 = time.time()
    nd = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", encoding="utf-8") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx, initializer=_init) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            nd += 1
            el = time.time() - t0
            print(f"[{nd}/{len(specs)}] {r.get('surface','?'):>8} "
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | "
                  f"ETA {el/nd*(len(specs)-nd)/60:.1f}m", flush=True)
    print("done ->", out)


if __name__ == "__main__":
    main()