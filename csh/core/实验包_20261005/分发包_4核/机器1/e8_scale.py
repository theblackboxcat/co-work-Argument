"""
e8_scale.py — E8：规模轴实验，测 n*(d_model)

对应「如何测出边界一」方案。见 02_如何测出边界一_规模轴实验E8设计.md
=====================================================================

要测的量
--------
论文的涌现阈值 n* 定义在**训练样本数**上；LLM 规模定律定义在**参数量**上。
本脚本固定任务/基质/表面，只扫模型宽度 d，测 n*(d)：

    斜率平坦  -> "需要多少数据"与模型大小无关（对 CSH 最友好）
    斜率下降  -> 大模型需要更少数据，结构效应被容量补偿（CSH 需限定）
    斜率上升  -> 与容量补偿直觉相反，若出现须先查优化问题

为什么只到 d=512
--------------
0.14M -> 8.4M 已跨两个数量级，足够看斜率符号。再往上单 run 从28 min
起，总成本进入"几天"。更关键：在合成任务上训 100M+ **买到的只是更大的
合成模型，不是更接近 LLM** —— 100M 与 175B 之间隔着的不是数量，是训练
数据分布。这一点必须写进论文，见方案 §5。

设计要点（每一条都对应论文自己的教训）
----------------------------------------
* token 46 严格配平（§5.1 陷阱一）
* 共享 id 区间编码，不用 build_vocab（S1 缺陷的教训）
* 固定 relperm null 作承重对照（§6.2 的教训）
* 层数固定 4，只扫宽度（深度与宽度会纠缠）
* C_eff(3) 恒为 24（§5.3 陷阱三）
* preflight 打印参数量与算力比，供配平核对

用法
----
    python e8_scale.py --dry-run
    python e8_scale.py --d 64,128,256 --seeds 4# 快速 pilot
    python e8_scale.py --d 64,128,256,384,512 --seeds 4   # 完整
    python e8_scale.py --d 64,128,256 --seeds 6 --surfaces zh,en,lisp,math,code,alien,relperm
"""

import argparse
import itertools
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)

from surfaces import Surface, PermutedSurface      # noqa: E402
from substrate2 import build, Gen, c_eff# noqa: E402
from model import Vocab                            # noqa: E402
from model import Block, Config as BaseConfig      # noqa: E402

DEPTH = 3
N_TEST = 400
NS = [2000, 3000, 4000, 5000, 6500]
PROBE_SEED = 4242
TAUS = [0.45, 0.55, 0.60, 0.65, 0.75]
D_GRID = [64, 128, 256, 384, 512]
N_LAYER = 4               # 固定层数，只扫宽度


# ============================================================ 共享词表
def make_surface(name, n_rel):
    if name == "relperm":
        return PermutedSurface("en", n_rel, mode="rel")
    return Surface(name, n_rel)


def build_shared_vocab(surfaces):
    """跨表面共享 id 区间（同 surface_fix.py 方案）。

    surface_fix.jsonl 用的是 6 个真实表面；这里若含 relperm，需给它
    独立 slot，否则它会与 en 落到同一区间而逐 token 相同。
    """
    v = Vocab()
    sub = build(1)
    probe = Gen(sub, seed=PROBE_SEED).dataset(400, [DEPTH], seed=PROBE_SEED)
    for slot, name in enumerate(surfaces):
        s = make_surface(name, sub["n_rel"])
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"])
            toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (slot, t))
    return v


# ============================================================ 可配置模型
class Cfg(BaseConfig):
    """继承基类Config，只改宽度。层数固定 N_LAYER。"""

    def __init__(self, d_model):
        self.d_model = d_model
        self.n_layer = N_LAYER
        self.n_head = 4 if d_model % 4 == 0 else 1
        self.d_ff = 2 * d_model
        self.dropout = 0.0
        self.max_len = BaseConfig.max_len
        self.tie_weights = True


class ScaledSolver(nn.Module):
    """与论文 model.Solver 同构，唯一差别是 d_model 可变。"""

    def __init__(self, vocab_size, cfg):
        super().__init__()
        self.cfg = cfg
        self.emb = nn.Embedding(vocab_size, cfg.d_model)
        self.pos = nn.Embedding(cfg.max_len, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList([Block(cfg) for _ in range(cfg.n_layer)])
        self.lnf = nn.LayerNorm(cfg.d_model)
        self.head = nn.Linear(cfg.d_model, vocab_size, bias=False)
        if cfg.tie_weights:
            self.head.weight = self.emb.weight
        self.apply(_init_weights)

    def forward(self, ids, pad_mask):
        L = ids.shape[1]
        assert L <= self.cfg.max_len, f"seq {L} > {self.cfg.max_len}"
        pos = torch.arange(L, device=ids.device)
        x = self.drop(self.emb(ids) + self.pos(pos)[None])
        for b in self.blocks:
            x = b(x, pad_mask)
        return self.head(self.lnf(x))


def _init_weights(m):
    if isinstance(m, nn.Linear):
        nn.init.normal_(m.weight, std=0.02)
        if m.bias is not None:
            nn.init.zeros_(m.bias)
    elif isinstance(m, nn.Embedding):
        nn.init.normal_(m.weight, std=0.02)


def count_params(model):
    tot = sum(p.numel() for p in model.parameters())
    emb = sum(p.numel() for n, p in model.named_parameters() if "emb" in n)
    return tot, emb, tot - emb


# ============================================================ 训练
def train_at_width(vocab, train_r, test_r, d_model, seed,
                   epochs=1, batch=32, lr=3e-4):
    torch.manual_seed(seed)
    cfg = Cfg(d_model)
    model = ScaledSolver(len(vocab), cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    n = len(train_r)
    total_steps = max(1, (n // batch) * epochs)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=lr, total_steps=total_steps, pct_start=0.1)

    from model import encode_batch, loss_fn, accuracy
    step = 0
    model.train()
    while step < total_steps:
        perm = torch.randperm(n)
        for bi in range(n // batch):
            idx = perm[bi * batch:(bi + 1) * batch]
            batch_r = [train_r[i] for i in idx.tolist()]
            inp, pad, y = encode_batch(batch_r, vocab)
            loss, _ = loss_fn(model, inp, pad, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            if step < total_steps - 1:
                sched.step()
            step += 1
            if step >= total_steps:
                break

    inp, pad, y = encode_batch(test_r, vocab)
    acc = accuracy(model, inp, pad, y)
    return model, acc, step


# ============================================================ 单 run
def run_one(d_model, surface, n_train, seed, _unused=None):
    import latin
    names = SURFACES                        # 7 个表面
    blk = latin.slot_of(names, surface, seed)       # 拉丁方：随 seed 轮转
    vocab, si = latin.build_vocab(names, surface, blk, depth=DEPTH,
                                 n_test=N_TEST)

    sub = build(1)
    n_rel = sub["n_rel"]
    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)

    # --- 不变量 1：数据集足量（防生成器静默退化）---
    assert len(train_p) == n_train, f"train short {len(train_p)}/{n_train}"
    assert len(test_p) == N_TEST, f"test short {len(test_p)}/{N_TEST}"

    tr = latin.encode(train_p, surface, n_rel, vocab, si)
    te = latin.encode(test_p, surface, n_rel, vocab, si)

    # --- 不变量 2：token 46 配平 ---
    toks = {len(r["tokens"]) for r in tr[:200]}
    toks_te = {len(r["tokens"]) for r in te[:200]}
    assert len(toks) == 1 and toks == toks_te, \
        f"token parity broken: {toks} vs {toks_te}"
    assert toks.pop() == 46, f"token count != 46"

    # --- 不变量 3：C_eff(3) 恒 24 ---
    _, eff = c_eff(sub["assign"], 3)
    assert eff == 24, f"C_eff(3)={eff}"

    t0 = time.time()
    model, acc, steps = train_at_width(vocab, tr, te, d_model, seed)
    tot, emb, body = count_params(model)
    return {"arm": "E8", "d_model": d_model, "n_layer": N_LAYER,
            "surface": surface, "block_slot": blk,
            "n_train": n_train, "seed": seed,
            "acc": acc, "steps": steps, "vocab": len(vocab),
            "tok": 46, "C_eff3": eff, "params_total": tot,
            "params_emb": emb, "params_body": body,
            "secs": round(time.time() - t0, 1)}


_SHARED = None


def _init_pool(surfaces):
    """进程池 initializer：每worker 建一次共享词表。"""
    global _SHARED
    _SHARED = {"vocab": build_shared_vocab(surfaces),
               "slot": {s: i for i, s in enumerate(surfaces)}}


def job(spec):
    d, surf, n, sd = spec
    try:
        return run_one(d, surf, n, sd, _SHARED)
    except Exception:
        import traceback
        return {"acc": float("nan"), "d_model": d, "surface": surf,
                "n_train": n, "seed": sd,
                "error": traceback.format_exc()[-400:]}


# ============================================================ preflight
def preflight(surfaces, ds, vocab):
    print("=" * 76)
    print("PREFLIGHT  —  参数量、算力比、与论文基线的对位")
    print("=" * 76)
    print(f"  shared vocab = {len(vocab)}   surfaces = {surfaces}")
    print(f"  n_layer = {N_LAYER} (固定)   token = 46 (固定)   "
          f"C_eff(3) = 24 (固定)")
    print()
    print(f"  {'d_model':>8} {'params_total':>13} {'body':>12} "
          f"{'vs 论文A1':>11} {'d^2 比':>8}")
    for d in ds:
        m = ScaledSolver(len(vocab), Cfg(d))
        tot, emb, body = count_params(m)
        ref = count_params(ScaledSolver(len(vocab), Cfg(128)))[2]
        print(f"  {d:8d} {tot:13,} {body:12,} "
              f"{body/ref:10.2f}x {d/128:8.2f}")
    print()
    print("  论文 A1 = d_model 128 / 554,624 total(vocab=31) / 550,656 body")
    print("  本表 vocab=197，故 total 略大（575,872 vs 554,624）——")
    print("  body 必须精确等于 550,656，否则实现有偏。")
    print()

    # null 干预是否真的进了模型
    sub = build(1)
    ps = Gen(sub, seed=1000).dataset(30, [DEPTH], seed=0)

    def enc(name):
        slot = {s: i for i, s in enumerate(surfaces)}[name]
        s = make_surface(name, sub["n_rel"])
        return [[vocab.stoi["%d\x00%s" % (slot, t)]
                 for t in s.render(p)["tokens"]] for p in ps]

    print("  null 干预检查（承重对照，必须真的不同于en）:")
    if "relperm" in surfaces:
        e = enc("en")
        for nm in ("relperm",):
            same = sum(1 for a, b in zip(e, enc(nm)) if a == b)
            flag = "OK" if same == 0 else f"!! {same}/30 identical"
            print(f"    en vs {nm:8s}: {same:2d}/30 identical[{flag}]")
        if same != 0:
            print("    >> relperm 未真正进入模型，本实验的 null 臂无效。")
    else:
        print("    !! 未包含 relperm —— E8 必须带 null 作承重对照。")
    print()


# ============================================================ 分析
def analyze(path):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r.get("acc") is not None and "error" not in r]
    if not rows:
        print("no data")
        return
    ns = sorted({r["n_train"] for r in rows})
    seeds = sorted({r["seed"] for r in rows})
    ds = sorted({r["d_model"] for r in rows})
    surfaces = sorted({r["surface"] for r in rows})
    cell = {(r["d_model"], r["surface"], r["n_train"], r["seed"]): r["acc"]
            for r in rows}

    def thr(d, s, tau):
        out = []
        for sd in seeds:
            dd = {n: cell[(d, s, n, sd)] for n in ns
                  if (d, s, n, sd) in cell}
            if len(dd) < len(ns):
                continue
            nsl = sorted(dd)
            v = None
            for i, n in enumerate(nsl):
                if dd[n] >= tau:
                    if i == 0:
                        v = float(n)
                    else:
                        n0, n1 = nsl[i - 1], n
                        m0, m1 = dd[n0], dd[n1]
                        if m1 == m0:
                            v = float(n)
                        else:
                            t = (tau - m0) / (m1 - m0)
                            v = float(np.exp(np.log(n0) +
                                             t * (np.log(n1) - np.log(n0))))
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
        print("=" * 76)
        print(f"tau = {tau:.2f}")
        print("=" * 76)
        print(f"  {'d_model':>8} " + "".join(f"{s:>11}" for s in surfaces))
        series = {}
        for d in ds:
            line = f"  {d:8d} "
            for s in surfaces:
                v = thr(d, s, tau)
                if v:
                    lo, hi = boot(v)
                    line += f"{np.mean(v):7.0f}    "
                    series.setdefault(s, []).append((d, np.mean(v), lo, hi))
                else:
                    line += f"{'----':>11}"
            print(line)
        print()

        #斜率
        print("  n*(d) 的 log-log 斜率（>0 越大模型需要越多数据）:")
        for s in surfaces:
            pts = series.get(s, [])
            if len(pts) < 3:
                print(f"    {s:>8}: 数据不足（{len(pts)} 档）")
                continue
            xs = np.log([p[0] for p in pts])
            ys = np.log([p[1] for p in pts])
            sl, ic = np.polyfit(xs, ys, 1)
            r = float(np.corrcoef(xs, ys)[0, 1])
            verdict = ("平坦" if abs(sl) < 0.10 else
                       "下降(容量补偿)" if sl < 0 else "上升(反直觉)")
            print(f"    {s:>8}: slope={sl:+.3f}  r={r:+.3f}  {verdict}")
        print()
        print("  '----' = 该档无足够种子跨过判据，不是 0")
        print()


# ============================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--d", type=str, default="64,128,256,384,512")
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--surfaces", type=str,
                    default="zh,en,lisp,math,code,alien,relperm")
    ap.add_argument("--ns", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--out", default="../results/e8_scale.jsonl")
    args = ap.parse_args()

    ds = [int(x) for x in args.d.split(",")]
    surfaces = args.surfaces.split(",")
    NS_ = [int(x) for x in args.ns.split(",")] if args.ns else NS
    out = os.path.abspath(args.out if os.path.isabs(args.out)
                         else os.path.join(HERE, args.out))

    if args.analyze_only:
        analyze(out)
        return

    vocab = build_shared_vocab(surfaces)
    preflight(surfaces, ds, vocab)
    if args.dry_run:
        print("--dry-run：到此为止。")
        return

    specs = [(d, s, n, sd) for d, s, n, sd in
             itertools.product(ds, surfaces, NS_, range(args.seeds))]
    specs.sort(key=lambda x: (x[2], x[0], x[1], x[3]))

    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("d_model"), r.get("surface"),
                              r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    total = len(ds) * len(surfaces) * len(NS_) * args.seeds
    print(f"  E8 jobs = {len(specs)} (of {total})  seeds={args.seeds}")
    print(f"  out = {out}\n", flush=True)

    t0 = time.time()
    nd = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", encoding="utf-8") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx, initializer=_init_pool,
            initargs=(surfaces,)) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            nd += 1
            el = time.time() - t0
            print(f"[{nd}/{len(specs)}] d={r.get('d_model','?'):<5} "
                  f"{str(r.get('surface','?')):>7} "
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | "
                  f"ETA {el/nd*(len(specs)-nd)/60:.1f}m", flush=True)
    print("done ->", out)
    print("分析：python e8_scale.py --analyze-only")


if __name__ == "__main__":
    main()
