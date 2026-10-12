"""
e10_ushape.py — E10：结构阈值随 C_eff 的形状（U 形 / 平坦 / 单调）

对应 04_涌现与反涌现_U形与双降.md。判别书未覆盖此轴。
=====================================================================

要测的量
--------
固定模型（论文 A1, d=128, 554K）、固定表面（en）、固定 seed，
只扫结构复杂度：

    n*(C_eff) = 结构复杂度为 C_eff 时的涌现阈值

为什么这条轴可能呈 U 形
------------------------
Mammen & DLCS (1997) 在 JAIR 上刻画 easy-hard-easy：约束少时有很多解，
容易；约束恰到好处时解数接近 1，最难；约束过多时矛盾立刻暴露，
又变容易。困难集中在**可解率的过渡区**。

Wu & Lo (2024, arXiv:2410.01692) 在 LLM 规模轴上发现同构现象：
难题目呈 U 形、容易题目呈倒 U 形（双降），合并后看起来像"突然涌现"。

**但他们的轴是模型规模或题目难度，不是结构复杂度。**
把 U 形搬到"C_eff 维"上是本实验的假设，尚无文献直接支持。

这与判别书的关系
----------------
判别书 §5.4 写「保证 C_eff(3) 不变是**核心不变量**」。
若 C_eff 本身是那条 U 形轴，则该设计原则会**系统性地删掉要测的现象**。
这不是判别书写错了，是它把 C_eff 当成只需保持不变的背景量。
本实验专门去动它。

五档结构（已实测 yield 40/40）
------------------------------
C_eff =  2, 5, 8, 16, 24
类型数     2   2   2    2    3（论文 A1）

论文 §7.2 发现二已指出 N_REL=2 最难（退化类型结构），
本实验把那一点向左扩展成一条完整的轴。

用法
----
    python e10_ushape.py --dry-run        # 打印五档的结构与不变量
    python e10_ushape.py --seeds 6        # 完整 5档 x 5n x 6seed = 150 runs
    python e10_ushape.py --analyze-only   # 只分析

判定
----
    n*(C_eff) 下降  -> 与论文现有 mult 结果一致（结构越复杂越容易）
    n*(C_eff) 平坦  -> 现有"结构不变"结论仅在 C_eff ∈ [8,24] 成立
    U形（先高后低再升）-> 结构相变，对 CSH 友好
    倒U形（中间最低） -> 若 CI 不含零，是新发现
"""

import argparse
import itertools
import json
import multiprocessing as mp
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)

from surfaces import Surface, PermutedSurface      # noqa: E402
from substrate2 import Gen, c_eff, TYPE_SIGS      # noqa: E402
from model import Vocab, Solver, train_model      # noqa: E402

DEPTH = 3
N_TEST = 400
NS = [2000, 3000, 4000, 5000, 6500]
TAUS = [0.45, 0.55, 0.60, 0.65, 0.75]
SURFACES = ["en", "relperm"]          # 承重对照必带（论文 §11 第3条）
D_MODEL = 128                        # 论文 A1，不动


# ============================================================ 五档结构
def _mk(assign):
    n = len(assign)
    m = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if assign[i][1] == assign[j][0]:
                m[i][j] = 1
    return {"assign": list(assign), "m": m, "n_rel": n,
            "pools": [list(range(0, 7)), list(range(7, 12)),
                      list(range(12, 18))],
            "branching": sum(sum(r) for r in m) / n,
            "dead": [i for i in range(n) if sum(m[i]) == 0]}


def _search_assign(target_eff, n_try=20000, seed=0):
    """在 2 类型 × 6 关系、无死端的 assign 空间里找一个 C_eff=target的。"""
    rng = random.Random(seed)
    pairs = [(0, 0), (0, 1), (1, 0), (1, 1)]
    for _ in range(n_try):
        a = [rng.choice(pairs) for _ in range(6)]
        s = _mk(a)
        if s["dead"]:
            continue
        _c3, eff = c_eff(a, 3)
        if eff == target_eff:
            return a
    return None


# 五档：C_eff 升序；24 是论文 A1 本身
# 其余四档一律由 _search_assign 搜出——手写 assign 极易写错
# （曾把 8 与 16 写反，preflight 当场抓到）。不要手写。
_C_EFF_GRID = [24, 16, 8, 5, 2]
SPECS = {24: list(TYPE_SIGS)}
for _t in _C_EFF_GRID:
    if _t != 24:
        SPECS[_t] = _search_assign(_t)


# ============================================================ 编码
def build_shared_vocab(surfaces):
    """跨表面共享 id 区间（surface_fix.py 方案）。"""
    v = Vocab()
    sub = _mk(SPECS[24])
    probe = Gen(sub, seed=4242).dataset(400, [DEPTH], seed=4242)
    for slot, name in enumerate(surfaces):
        s = (PermutedSurface("en", sub["n_rel"], mode="rel")
             if name == "relperm" else Surface(name, sub["n_rel"]))
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"])
            toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (slot, t))
    return v


def make_surface(name, n_rel):
    return (PermutedSurface("en", n_rel, mode="rel")
            if name == "relperm" else Surface(name, n_rel))


# ============================================================ 单 run
def run_one(c_eff_target, surface, n_train, seed, shared):
    assign = SPECS[c_eff_target]
    sub = _mk(assign)
    assert not sub["dead"], "dead-end relation"
    got_c3, got_eff = c_eff(assign, 3)
    assert got_eff == c_eff_target, \
        f"C_eff mismatch: want {c_eff_target}, got {got_eff}"

    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert len(train_p) == n_train, f"train short {len(train_p)}/{n_train}"
    assert len(test_p) == N_TEST, f"test short {len(test_p)}/{N_TEST}"

    slot = shared["slot"][surface]
    s = make_surface(surface, sub["n_rel"])
    key = lambda t: "%d\x00%s" % (slot, t)
    enc = lambda ps: [{"tokens": [key(t) for t in s.render(p)["tokens"]],
                       "target": [key(s.render(p)["target"][0])]}
                      for p in ps]
    tr, te = enc(train_p), enc(test_p)

    # --- 不变量：token 46 配平（与论文同口径）---
    toks = {len(r["tokens"]) for r in tr[:200]}
    toks_te = {len(r["tokens"]) for r in te[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"

    t0 = time.time()
    _, acc, steps = train_model(shared["vocab"], tr, te, epochs=1,
                                batch=32, lr=3e-4, seed=seed)
    return {"arm": "E10", "c_eff_target": c_eff_target, "C_eff3": got_eff,
            "C3": got_c3, "assign": str(assign),
            "n_types": len({a[0] for a in assign}),
            "branching": round(sub["branching"], 2),
            "n_rel": sub["n_rel"], "surface": surface,
            "n_train": n_train, "seed": seed, "acc": acc, "steps": steps,
            "vocab": len(shared["vocab"]), "tok": toks.pop(),
            "d_model": D_MODEL, "depth": DEPTH,
            "secs": round(time.time() - t0, 1)}


_SHARED = None


def _init_pool(surfaces):
    global _SHARED
    _SHARED = {"vocab": build_shared_vocab(surfaces),
               "slot": {s: i for i, s in enumerate(surfaces)}}


def build_shared_vocab(surfaces):
    """兼容包装：真正建词表在 run_one 内按 (surface, seed) 现建，
    因为拉丁方要求每个 (surface, seed) 对应不同 slot，词表不能预先共享。
    """
    return None


def run_one(c_eff_target, surface, n_train, seed, _unused=None):
    import latin
    names = SURFACES                       # ["en", "relperm"]
    slot = latin.slot_of(names, surface, seed)      # 拉丁方：随 seed 轮转
    vocab, si = latin.build_vocab(names, surface, slot, depth=DEPTH,
                                 n_test=N_TEST)

    assign = SPECS[c_eff_target]
    sub = _mk(assign)
    assert not sub["dead"], "dead-end relation"
    got_c3, got_eff = c_eff(assign, 3)
    assert got_eff == c_eff_target, \
        f"C_eff mismatch: want {c_eff_target}, got {got_eff}"

    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert len(train_p) == n_train, f"train short {len(train_p)}/{n_train}"
    assert len(test_p) == N_TEST, f"test short {len(test_p)}/{N_TEST}"

    tr = latin.encode(train_p, surface, sub["n_rel"], vocab, si)
    te = latin.encode(test_p, surface, sub["n_rel"], vocab, si)

    # --- 不变量：token 46 配平（与论文同口径）---
    toks = {len(r["tokens"]) for r in tr[:200]}
    toks_te = {len(r["tokens"]) for r in te[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"

    t0 = time.time()
    _, acc, steps = train_model(vocab, tr, te, epochs=1,
                                batch=32, lr=3e-4, seed=seed)
    return {"arm": "E10", "c_eff_target": c_eff_target, "C_eff3": got_eff,
            "C3": got_c3, "assign": str(assign),
            "n_types": len({a[0] for a in assign}),
            "branching": round(sub["branching"], 2),
            "n_rel": sub["n_rel"], "surface": surface,
            "n_train": n_train, "seed": seed, "acc": acc, "steps": steps,
            "vocab": len(vocab), "tok": toks.pop(), "block_slot": slot,
            "d_model": D_MODEL, "depth": DEPTH,
            "secs": round(time.time() - t0, 1)}


def job(spec):
    eff, surf, n, sd = spec
    try:
        return run_one(eff, surf, n, sd)
    except Exception:
        import traceback
        return {"acc": float("nan"), "c_eff_target": eff, "surface": surf,
                "n_train": n, "seed": sd,
                "error": traceback.format_exc()[-400:]}


_SHARED = None


def _init_pool(surfaces):
    """拉丁方下词表按 (surface, seed) 现建，进程池无需预建。"""
    return None


# ============================================================ 预检
def preflight():
    print("=" * 78)
    print("PREFLIGHT  —  五档结构（已实测 yield 40/40）")
    print("=" * 78)
    print(f"  d_model={D_MODEL}（论文 A1，不动）  depth={DEPTH}  "
          f"surfaces={SURFACES}")
    print()
    print(f"  {'C_eff':>6} {'n_types':>8} {'branch':>7} {'C(3)':>6} "
          f"{'yield':>8}  assign")
    ok = True
    for eff in sorted(SPECS, reverse=True):
        a = SPECS[eff]
        if a is None:
            print(f"  {eff:6d}   !! 搜索失败，跳过")
            ok = False
            continue
        s = _mk(a)
        c3, e = c_eff(a, 3)
        g = Gen(s, seed=0)
        y = sum(1 for _ in range(40) if g.make(DEPTH))
        nt = len({x[0] for x in a})
        flag = "" if (e == eff and not s["dead"] and y >= 30) else "  !!"
        if flag:
            ok = False
        print(f"  {e:6d} {nt:8d} {s['branching']:7.2f} {c3:6d} "
              f"{y:6d}/40  {a}{flag}")
    print()
    print("  要求：C_eff 与目标一致、无死端、yield >= 30/40。")
    print("  这条轴的左侧（C_eff < 24）是论文从未测过的区域——")
    print("  判别书把 C_eff 当作『需保持不变的不变量』，故未覆盖。")
    print()
    print("  " + ("全部通过。" if ok else "有行未通过，见 !!。"))
    print()
    return ok


# ============================================================ 分析
def analyze(path):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r.get("acc") is not None and "error" not in r]
    if not rows:
        print("no data")
        return
    ns = sorted({r["n_train"] for r in rows})
    seeds = sorted({r["seed"] for r in rows})
    effs = sorted({r["C_eff3"] for r in rows}, reverse=True)
    surfs = sorted({r["surface"] for r in rows})
    cell = {(r["C_eff3"], r["surface"], r["n_train"], r["seed"]): r["acc"]
            for r in rows}

    def thr(eff, sf, tau):
        out = []
        for sd in seeds:
            d = {n: cell[(eff, sf, n, sd)] for n in ns
                 if (eff, sf, n, sd) in cell}
            if len(d) < len(ns):
                continue
            nsl = sorted(d)
            v = None
            for i, n in enumerate(nsl):
                if d[n] >= tau:
                    if i == 0:
                        v = float(n)
                    else:
                        n0, n1 = nsl[i - 1], n
                        m0, m1 = d[n0], d[n1]
                        v = float(n) if m1 == m0 else float(
                            np.exp(np.log(n0) + (tau - m0) / (m1 - m0) *
                                   (np.log(n1) - np.log(n0))))
                    break
            if v is not None:
                out.append(v)
        return out

    def boot(v, n=4000, seed=0):
        if len(v) < 2:
            return float("nan"), float("nan")
        rng = np.random.default_rng(seed)
        bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
        return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))

    for tau in TAUS:
        print("=" * 78)
        print(f"tau = {tau:.2f}   n*(C_eff)  —— 涌现阈值随结构复杂度的形状")
        print("=" * 78)
        print(f"  {'C_eff':>6} " + "".join(f"{s:>18}" for s in surfs)
              + f"{'  差值(relperm-en)':>20}")
        series = {}
        prev = {}
        for eff in effs:
            line = f"  {eff:6d} "
            for s in surfs:
                v = thr(eff, s, tau)
                if v:
                    m = float(np.mean(v))
                    lo, hi = boot(v)
                    line += f"  {m:7.0f}[{lo:5.0f},{hi:5.0f}]"
                    series.setdefault(s, []).append((eff, m, lo, hi))
                    prev.setdefault(s, {})[eff] = m
                else:
                    line += f"  {'----':>17}"
            d = (prev.get("relperm", {}).get(eff, float("nan"))
                 - prev.get("en", {}).get(eff, float("nan")))
            line += f"  {d:+20.0f}" if d == d else f"  {'--':>20}"
            print(line)
        print()
        # 形状判定
        for s in surfs:
            pts = series.get(s, [])
            if len(pts) < 3:
                continue
            xs = np.log([p[0] for p in pts])
            ys = np.log([p[1] for p in pts])
            sl = float(np.polyfit(xs, ys, 1)[0])
            r = float(np.corrcoef(xs, ys)[0, 1])
            ms = [p[1] for p in pts]
            print(f"  {s:>8}: n* = {' → '.join('%.0f' % x for x in ms)}")
            print(f"            log-log 斜率={sl:+.3f}  r={r:+.3f}")
        # U 形检测：内部点是否低于两端
        for s in surfs:
            pts = series.get(s, [])
            if len(pts) >= 4:
                ms = [p[1] for p in pts]
                mid = ms[1:-1]
                if min(mid) < min(ms[0], ms[-1]) * 0.97:
                    print(f"  >> {s}: 内部点低于两端 —— 可能 U 形")
                elif max(mid) > max(ms[0], ms[-1]) * 1.03:
                    print(f"  >> {s}: 内部点高于两端 —— 可能倒 U 形")
        print()


# ============================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--out", default="../results/e10_ushape.jsonl")
    args = ap.parse_args()

    out = os.path.abspath(args.out if os.path.isabs(args.out)
                else os.path.join(HERE, args.out))
    if args.analyze_only:
        analyze(out)
        return

    if not preflight():
        print("preflight 未通过，不启动 run。")
        return
    if args.dry_run:
        print("--dry-run：到此为止。")
        return

    specs = [(e, s, n, sd) for e, s, n, sd in
             itertools.product(sorted(SPECS, reverse=True), SURFACES, NS,
                               range(args.seeds))]
    specs.sort(key=lambda x: (x[2], -x[0], x[1]))

    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("C_eff3"), r.get("surface"),
                              r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    total = len(SPECS) * len(SURFACES) * len(NS) * args.seeds
    print(f"  E10 jobs = {len(specs)} (of {total})")
    print(f"  out = {out}\n", flush=True)

    t0 = time.time()
    nd = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", encoding="utf-8") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx, initializer=_init_pool,
            initargs=(SURFACES,)) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            nd += 1
            el = time.time() - t0
            print(f"[{nd}/{len(specs)}] C_eff={r.get('C_eff3','?'):<4} "
                  f"{str(r.get('surface','?')):>8} "
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | "
                  f"ETA {el/nd*(len(specs)-nd)/60:.1f}m", flush=True)
    print("done ->", out)
    print("分析：python e10_ushape.py --analyze-only")


if __name__ == "__main__":
    main()