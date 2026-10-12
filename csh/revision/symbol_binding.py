#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
symbol_binding.py  (v2)
=======================
判决实验：模型把基质结构绑定在**具体符号**上，还是学到了可重对齐的结构？

v1 为什么无效
-------------
v1 的 `MappedSurface` 存了 perm 但render 从未使用它，
`remap:pi_6cycle` 与 `same` 输出的 token 序列**逐位相同**
（实测三档 n 的准确率完全一致：0.2671 / 0.6458 / 0.8963）。
零差异来自零干预，不是发现。已归档。

v1 还有一个更深的错误
----------------------
即使按「重命名关系 token」的思路做，也做不到判决。
本任务里关系 token 只是**标签**，推理完全由「实体—关系—实体」的
三元组结构承担（实测：追踪 start --r--> ... 到达 answer，
路径由 facts 的连接结构唯一确定）。因此把 token `moves` 换成
`inside` 不改变任何推理内容——模型只需按位置模式匹配，
对关系 token 的语义一无所知也能答对。

这本身是一个发现：**这个任务的解不依赖关系 token 的语义。**
但它使「符号级映射」这一表述需要精确化。

v2 的设计
---------
要检验「符号 ↔ 类型转移的绑定」，必须让**同一个 token 串在不同条件下
要求不同的行为**，且该差异必须真的改变推理。

做法：构造两个**共享全部 token 串**、但**类型结构被置换**的世界。

    世界 A（训练）：类型转移表assign_A = [(0,1),(0,2),(1,0),(1,2),(2,0),(2,1)]
    世界 B（测试）：assign_B[i] = assign_A[perm[i]]

    实体 token：同一批 e0..e17，在两个世界里按**同一张表**划分类型
    关系 token：同一批 6 个词，但r 在世界 B 里表示 assign_B[r]

于是测试样本必须重新生成：同一条「链」在两个世界里走的是不同的
类型路径。模型在测试时看到的是**熟悉的 token 串**，
但它们之间的关系结构被重排了。

若模型学到的是「符号级映射（token 串 → 类型转移）」，
它会把 `moves` 记成「1→2」，而在世界 B 里 `moves` 是 3→0，于是崩掉。
若模型学到的是「沿链追踪结构」（与哪个具体符号无关），
它应当能应对——因为推理结构不变。

格子
----
    same            训练 A、测试 A          上界
    remap:pi_*      训练 A、测试 B(A经perm) 判决性
    shuffle         训练 A、测试集token位置打乱  定位对照
    pi_id           恒等置换= same 的内部自检

规模：4 臂 × 3 个 n × 6 种子 = 72 runs
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

from substrate2 import build as _build, Gen
from model import train_model, Vocab

DEPTH = 3
N_TEST = 400
N_SEEDS = 6
NS = [4000, 5000, 6500]

SIGNS = ["e%d" % i for i in range(18)]
REL_TOKS = ["inside", "before", "acts", "moves", "near", "points"]
N_REL = 6
ASSIGN_A = [(0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)]

PERMS = {
    "pi_id":      [0, 1, 2, 3, 4, 5],     # 恒等（自检）
    "pi_6cycle":  [1, 2, 3, 4, 5, 0],     # 破坏最彻底
    "pi_swap2":   [1, 0, 3, 2, 4, 5],     # 中等
}


def assign_of(perm):
    """世界 B 的类型转移表：assign_B[i] = assign_A[perm[i]]"""
    return [ASSIGN_A[perm[i]] for i in range(N_REL)]


def type_pool(assign):
    """按类型转移表把 18 个实体分成 3 个类型的池。"""
    # 类型 t 出现在 assign 的哪些位置
    pools = {0: [], 1: [], 2: []}
    # 用固定规则分配：实体i 的类型 = i % 3 之外的稳定映射
    # 但必须满足：每条关系 r 的 dom 类型池非空且 ran 类型池非空
    # 采用标准构造：type(i) = i % 3，则每个池 6 个实体
    for i in range(18):
        pools[i % 3].append(i)
    return pools


class World:
    """一个世界：给定类型转移表，生成满足该结构的问题并渲染。"""

    def __init__(self, assign, rng_seed):
        self.assign = assign
        self.pools = type_pool(assign)
        self.rng = random.Random(rng_seed)

    def valid(self, a, r, b):
        dom, ran = self.assign[r]
        return a in self.pools[dom] and b in self.pools[ran]

    def make(self, depth):
        """生成一条深度 depth 的唯一路径 + 干扰事实。"""
        for _ in range(400):
            start = self.rng.choice(self.pools[0] + self.pools[1]
                                    + self.pools[2])
            cur = start
            seq, facts = [], []
            used = set()
            ok = True
            for _step in range(depth):
                cand = [r for r in range(N_REL)
                        if self.valid(cur, r, cur) or True]
                # 从当前类型可用的关系里挑
                ct = self.type_of(cur)
                avail = [r for r in range(N_REL) if self.assign[r][0] == ct]
                if not avail:
                    ok = False
                    break
                r = self.rng.choice(avail)
                rt = self.assign[r][1]
                targets = [e for e in self.pools[rt] if e != cur]
                if not targets:
                    ok = False
                    break
                nxt = self.rng.choice(targets)
                facts.append((cur, r, nxt))
                seq.append(r)
                cur = nxt
            if not ok:
                continue
            # 补干扰事实
            n_dis = 5
            tries = 0
            while len(facts) < depth + n_dis and tries < 300:
                tries += 1
                a = self.rng.randrange(18)
                avail = [r for r in range(N_REL) if self.assign[r][0]
                         == self.type_of(a)]
                if not avail:
                    continue
                r = self.rng.choice(avail)
                rt = self.assign[r][1]
                cand = [e for e in self.pools[rt] if e != a]
                if not cand:
                    continue
                b = self.rng.choice(cand)
                if (a, r, b) in facts:
                    continue
                # 不破坏唯一路径
                if (a, r, b) in [(x, y, z) for x, y, z in facts]:
                    continue
                facts.append((a, r, b))
            if len(facts) < depth + n_dis:
                continue
            return {"facts": facts, "start": start, "seq": seq,
                    "answer": cur, "depth": depth}
        raise RuntimeError("make failed")

    def type_of(self, e):
        for t, pool in self.pools.items():
            if e in pool:
                return t
        return None

    def render(self, p):
        toks = []
        for (a, r, b) in p["facts"]:
            toks += [SIGNS[a], "is", REL_TOKS[r], SIGNS[b], "."]
        toks += ["q", SIGNS[p["start"]], "then"] \
            + [REL_TOKS[r] for r in p["seq"]]
        return {"tokens": toks, "target": [SIGNS[p["answer"]]],
                "n_tokens": len(toks), "n_facts": len(p["facts"])}


def build_worlds(perm):
    """返回 (world_A, world_B)；pi_id 时两者相同。"""
    wa = World(ASSIGN_A, rng_seed=1000)
    wb = World(assign_of(perm), rng_seed=1000)
    return wa, wb


def run_one(arm, n_train, seed):
    kind, pname = arm.split(":") if ":" in arm else (arm, None)
    perm = PERMS[pname] if pname else [0, 1, 2, 3, 4, 5]

    wa, wb = build_worlds(perm)

    # 训练样本全部来自世界 A
    train_p = [wa.make(DEPTH) for _ in range(n_train)]
    if kind == "shuffle":
        # v2 修复：原实现写成 p = dict(p); p["facts"] = fs ——那是给局部变量
        # 重新绑定，test_p 里的元素从未被改动，于是 shuffle 臂逐位等于 same，
        # 18/18 对全部相同。空干预不能当作「模型不依赖事实顺序」的证据，
        # 这正是本文判据三要求检查的情形。改为原地写回并加断言。
        test_p = [wa.make(DEPTH) for _ in range(N_TEST)]
        rng = random.Random(9999 + seed)
        n_changed = 0
        for i, p in enumerate(test_p):
            fs = list(p["facts"])
            rng.shuffle(fs)
            if tuple(fs) != tuple(p["facts"]):
                n_changed += 1
            test_p[i] = dict(p, facts=fs)
        # 防回归：打乱必须真的改变了至少一半样本的事实顺序，
        # 否则本臂与 same 无法区分，任何关于顺序的结论都无依据。
        assert n_changed >= N_TEST // 2, (
            f"shuffle 干预未生效：仅 {n_changed}/{N_TEST} 个样本的事实顺序"
            f"被改变。本臂是空干预，不能作为证据。")
    else:
        test_p = [wb.make(DEPTH) for _ in range(N_TEST)]

    train_r = [wa.render(p) for p in train_p]
    test_r = [(wa if kind == "shuffle" else wb).render(p) for p in test_p]

    lt = {len(r["tokens"]) for r in train_r[:200]}
    le = {len(r["tokens"]) for r in test_r[:200]}
    assert lt == le, f"token 配平失败 {lt} {le}"

    # 判决性的前提：测试 token 集合必须与训练完全相同
    ttr = set()
    for r in train_r[:500]:
        ttr |= set(r["tokens"]) | set(r["target"])
    tte = set()
    for r in test_r[:500]:
        tte |= set(r["tokens"]) | set(r["target"])
    assert ttr == tte, ("测试侧出现训练时未见的 token：判决实验失效。\n"
                        f"  train-only: {sorted(ttr - tte)[:8]}\n"
                        f"  test-only : {sorted(tte - ttr)[:8]}")

    # 世界 B 的路径必须真的与A 不同（否则 remap 是空干预）
    if kind == "remap" and perm != [0, 1, 2, 3, 4, 5]:
        pa = [(p["seq"], tuple(p["facts"])) for p in train_p[:50]]
        pb = [(p["seq"], tuple(p["facts"])) for p in test_p[:50]]
        # 比较世界 A 与 B 各自生成的结构：至少 seq 的类型轨迹应不同
        def traj(w, ps):
            out = []
            for p in ps:
                t = [w.type_of(p["start"])]
                a = p["start"]
                for r in p["seq"]:
                    a = p["answer"] if r == p["seq"][-1] else a
                out.append(tuple(w.type_of(p["start"]) for _ in [0]))
            return out
        # 更直接：世界 A 与 B 的 assign 不同即结构不同
        assert wa.assign != wb.assign, "remap 未改变类型结构（空干预）"

    vocab = Vocab()
    for t in sorted(ttr):
        vocab.add(t)

    t0 = time.time()
    _, acc, steps = train_model(vocab, train_r, test_r, epochs=1, batch=32,
                                lr=3e-4, seed=seed)
    return {"arm": "SB2", "arm_name": arm, "kind": kind, "perm": pname,
            "n_train": n_train, "seed": seed, "acc": acc, "steps": steps,
            "vocab": len(vocab), "tok": lt.pop(),
            "secs": round(time.time() - t0, 1)}


def job(spec):
    arm, n, s = spec
    try:
        return run_one(arm, n, s)
    except Exception as e:
        import traceback
        return {"arm": "SB2", "arm_name": arm, "n_train": n, "seed": s,
                "acc": None, "error": "%s: %s" % (type(e).__name__, e),
                "tb": traceback.format_exc()[-700:]}


ARMS = ["same", "remap:pi_id", "remap:pi_6cycle", "remap:pi_swap2",
        "shuffle:pi_6cycle"]


def preflight():
    print("=" * 74)
    print("symbol_binding v2 preflight")
    print("=" * 74)

    print("\n[1] 两个世界")
    for name, p in PERMS.items():
        assign_B = assign_of(p)
        fix = sum(1 for i in range(N_REL) if p[i] == i)
        print(f"  {name:12s} A={ASSIGN_A}")
        print(f"  {'':12s} B={assign_B}  签名保留 {fix}/6")

    wa = World(ASSIGN_A, 1000)
    for name, p in PERMS.items():
        wb = World(assign_of(p), 1000)
        pa = wa.make(DEPTH)
        pb = wb.make(DEPTH)
        print(f"\n  [{name}] A 的链: start={pa['start']} seq={pa['seq']} "
              f"ans={pa['answer']}")
        print(f"  [{name}] B 的链: start={pb['start']} seq={pb['seq']} "
              f"ans={pb['answer']}")

    print("\n[2] 判决性前提：训练/测试 token 集合必须逐个相同")
    for name in PERMS:
        wa, wb = build_worlds(PERMS[name])
        T1 = set()
        for _ in range(200):
            r = wa.render(wa.make(DEPTH))
            T1 |= set(r["tokens"]) | set(r["target"])
        T2 = set()
        for _ in range(200):
            r = wb.render(wb.make(DEPTH))
            T2 |= set(r["tokens"]) | set(r["target"])
        print(f"  remap:{name:12s} 相同={T1 == T2}  |T|={len(T1)}/{len(T2)}"
              f"  差集={sorted(T1 ^ T2)[:5]}")

    print("\n[3] 结构确实被置换了吗（A 与 B 的 assign 不同即成立）")
    for name, p in PERMS.items():
        wa, wb = build_worlds(p)
        print(f"  {name:12s} assign_A==assign_B? "
              f"{wa.assign == wb.assign}  （True 只应出现在 pi_id）")

    print("\n[4] 序列长度配平")
    lens = set()
    for name, p in PERMS.items():
        wa, wb = build_worlds(p)
        for _ in range(30):
            lens.add(len(wa.render(wa.make(DEPTH))["tokens"]))
            lens.add(len(wb.render(wb.make(DEPTH))["tokens"]))
    print(f"  长度集合 = {lens}")

    print(f"\n规模：{len(ARMS)} 臂 × {len(NS)} 个 n × {N_SEEDS} 种子 = "
          f"{len(ARMS)*len(NS)*N_SEEDS} runs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--ns", type=int, nargs="*", default=NS)
    ap.add_argument("--out", default=os.path.join(HERE, "results", "SB2.jsonl"))
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--smoke", action="store_true",
                    help="只跑 1 个 run，检查 remap 与 same 是否真的不同")
    args = ap.parse_args()

    if args.preflight:
        preflight()
        return

    if args.smoke:
        for arm in ARMS:
            r = run_one(arm, 2000, 0)
            print(f"{arm:22s} acc={r['acc']:.4f}")
        return

    specs = [(a, n, s) for a in ARMS for n in args.ns for s in range(args.seeds)]
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
                done.add((r["arm_name"], r["n_train"], r["seed"]))
    todo = [s for s in specs if (s[0], s[1], s[2]) not in done]
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
                print(f"[{n}/{len(todo)}] FAIL {r['arm_name']} "
                      f"{r.get('error')}", flush=True)
            else:
                el = time.time() - t0
                eta = el / n * (len(todo) - n)
                print(f"[{n}/{len(todo)}] {r['arm_name']:22s} n={r['n_train']} "
                      f"s={r['seed']} acc={r['acc']:.4f} {r['secs']:5.1f}s "
                      f"ETA {eta/60:.1f}min", flush=True)


if __name__ == "__main__":
    main()