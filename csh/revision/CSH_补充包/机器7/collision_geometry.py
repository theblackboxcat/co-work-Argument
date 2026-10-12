#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collision_geometry.py
=====================
检验 null 对照的合法性，并定位「真实表面 vs null」差异的真实来源。

理论依据
--------
arXiv:2605.07120 (Guan & Bradic)《When Symbol Names Should Not Matter》：
决定 fresh-symbol 泛化的是 **token 碰撞图的几何**（度分布、色对失衡、
谱范数），而不是词表大小。本脚本为每个表面构造碰撞图并逐项比对，
以证明 relperm / entperm 与真实表面的碰撞几何**逐项相同**
——这是 null 对照能被当作「只摧毁语义」的前提。

同时诊断一个被原论文忽略的混淆
------------------------------
latin.build_vocab 让所有表面共享一个词表对象，但**每个表面用的是自己的
词法池**（zh=甲乙丙…、en=e0-e17、lisp=v0-v17、math=x_0-x_17、
code=n0-n17、alien=nonce），而 relperm / entperm 是 en 池的置换。
于是「真实 vs null」这一对比里混了两个因子：

    (A) 语义是否存在      —— 论文想测的
    (B) 词法池是哪个       —— 未受控的

若 (B) 贡献了主要方差，则 §4 的阴性/阳性结论都不能归因于 (A)。
本脚本用两组对照把 (A) 与 (B) 拆开：

    组内对照：en vs relperm vs entperm  —— 同池，只变语义  => 隔离 (A)
    跨池对照：zh/lisp/math/code/alien vs en 池 —— 变池+变语义 => 混 (A)(B)

碰撞图定义
----------
节点 = 该表面实际出现的 token 字符串。
边  = 两 token 在某条训练样本的同一事实模板槽位上**可互换**，
       即二者在某个位置角色上互为替代品。
等价地：把每个 token 的「出现位置角色集合」当作颜色，
两个节点同色当且仅当其颜色集合有非空交集——这正是
Guan & Bradic 讨论的 degree distribution 与 colour-pair imbalance。

输出
----
results/COLLISION.json / results/COLLISION.md
"""
import os
import json
import math
import random
import itertools
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
import sys
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from surfaces import Surface, PermutedSurface, SURFACES  # noqa: E402
from substrate2 import build, Gen  # noqa: E402
from latin import make_surface  # noqa: E402

N_REL = 6
DEPTH = 3
N_PROBE = 400
PROBE_SEED = 4242

ARMS = ["zh", "en", "lisp", "math", "code", "alien", "relperm", "entperm"]
REAL = ["zh", "en", "lisp", "math", "code", "alien"]
NULL = ["relperm", "entperm"]


# ------------------------------------------------------------------ 工具
def matvec(M, v):
    return [sum(M[i][j] * v[j] for j in range(len(v))) for i in range(len(M))]


def power_iteration(M, iters=200, seed=0):
    """幂迭代求碰撞图的最大特征值（谱范数）。"""
    n = len(M)
    rng = random.Random(seed)
    v = [rng.random() + 1e-9 for _ in range(n)]
    lam = 0.0
    for _ in range(iters):
        w = matvec(M, v)
        nw = math.sqrt(sum(x * x for x in w))
        if nw == 0:
            return 0.0
        v = [x / nw for x in w]
        lam = nw
    return lam


# ------------------------------------------------------- 碰撞图构造
def collision_graph(surface, problems):
    """返回 (nodes, adj, colors)。

    colors[t] = 该 token 出现过的「位置角色」集合。
    位置角色 = (模板槽位序号, 该槽位在事实中的语义位置)。
    同一事实中不同槽位即使 token 相同也视为不同角色，
    因为 transformer 靠位置区分它们。
    """
    colors = collections.defaultdict(set)
    for p in problems:
        r = surface.render(p)
        toks = r["tokens"]
        # 事实部分：每 5 个 token 为一条事实，槽位 0..4
        nf = r["n_facts"]
        for f in range(nf):
            base = f * 5
            for j in range(5):
                t = toks[base + j]
                colors[t].add(("fact", j))
        # 查询头 4 token
        for j in range(4):
            idx = nf * 5 + j
            if idx < len(toks):
                colors[toks[idx]].add(("query", j))
        # 答案
        for t in r["target"]:
            colors[t].add(("answer", 0))

    nodes = sorted(colors)
    idx = {t: i for i, t in enumerate(nodes)}
    # 同色 => 至少共享一个位置角色 => 互为替代
    role_members = collections.defaultdict(list)
    for t in nodes:
        for role in colors[t]:
            role_members[role].append(idx[t])
    n = len(nodes)
    adj = [[0.0] * n for _ in range(n)]
    for role, mem in role_members.items():
        for a, b in itertools.combinations(mem, 2):
            adj[a][b] = 1.0
            adj[b][a] = 1.0
    return nodes, adj, {t: sorted(colors[t]) for t in nodes}


def geometry(nodes, adj, colors):
    n = len(nodes)
    deg = [sum(row) for row in adj]
    nz = [d for d in deg if d > 0]
    spectral = power_iteration(adj) if n else 0.0
    degs = sorted(set(int(d) for d in deg))
    return {
        "n_tokens": n,
        "n_isolated": sum(1 for d in deg if d == 0),
        "degree_min": min(deg) if deg else 0,
        "degree_max": max(deg) if deg else 0,
        "degree_mean": sum(deg) / n if n else 0,
        "degree_distinct_values": len(degs),
        "density": sum(deg) / (n * n) if n else 0,
        "spectral_norm": spectral,
        "n_colors": len(set(tuple(v) for v in colors.values())),
        "mean_color_class": (sum(len(v) for v in colors.values()) / n) if n else 0,
        # 色对失衡：各颜色类大小的平方和 / 总数（=1 时完全均衡）
        "color_imbalance": (lambda cs: (sum(c * c for c in cs) / (sum(cs) ** 2)) if sum(cs) else 0)(
            [len(list(r)) for r in
             {role: [t for t in nodes if role in colors[t]]
              for role in set(itertools.chain(*colors.values()))}.values()]),
    }


# ------------------------------------------------------- 词法池指纹
def pool_fingerprint(surface):
    """该表面的词法池：实体标签与关系标签的集合、字符长度分布。"""
    ent = list(getattr(surface, "ent", []))
    rel = list(getattr(surface, "rel", []))
    def stats(xs):
        if not xs:
            return {}
        L = sorted(len(str(x)) for x in xs)
        return {"n": len(xs), "distinct": len(set(xs)),
                "len_min": L[0], "len_max": L[-1],
                "len_mean": sum(L) / len(L),
                "sample": list(xs)[:6]}
    return {"ent": stats(ent), "rel": stats(rel),
            "pool_id": hash(frozenset(ent)) % 10 ** 8 if ent else None}


# ------------------------------------------------------- 主流程
def main():
    sub = build(1)
    probe = Gen(sub, seed=PROBE_SEED).dataset(N_PROBE, [DEPTH],
                                              seed=PROBE_SEED)

    G = {}
    for name in ARMS:
        s = make_surface(name, N_REL)
        nodes, adj, colors = collision_graph(s, probe)
        g = geometry(nodes, adj, colors)
        g["pool"] = pool_fingerprint(s)
        g["tokens_sample"] = nodes[:12]
        G[name] = g

    # ---- 合法性认证：null vs 真实 的碰撞几何逐项比较
    keys = ["n_tokens", "degree_max", "degree_mean", "density",
            "spectral_norm", "color_imbalance", "n_colors"]
    legit = {}
    for nu in NULL:
        for re_ in REAL:
            same = {k: (G[nu][k] == G[re_][k]) for k in keys}
            legit[f"{nu}_vs_{re_}"] = {
                "all_equal": all(same.values()),
                "per_key": same,
                "n_tokens": (G[nu]["n_tokens"], G[re_]["n_tokens"]),
                "spectral": (round(G[nu]["spectral_norm"], 6),
                             round(G[re_]["spectral_norm"], 6)),
            }

    # ---- 池身份分组：哪些臂共用同一个词法池
    pool_groups = collections.defaultdict(list)
    for name in ARMS:
        s = make_surface(name, N_REL)
        pool_groups[pool_fingerprint(s)["pool_id"]].append(name)
    pool_of = {name: pool_fingerprint(make_surface(name, N_REL))["pool_id"]
               for name in ARMS}

    R = {
        "n_rel": N_REL, "depth": DEPTH, "n_probe": N_PROBE,
        "geometry": G,
        "legitimacy": legit,
        "pool_of_arm": pool_of,
        "pool_groups": {str(k): v for k, v in pool_groups.items()},
    }

    # ---------------------------------------------------- 与 acc 的关联
    rows = []
    for f in sorted(os.listdir(RES)):
        if not f.startswith("S2L"):
            continue
        for ln in open(os.path.join(RES, f)):
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
    acc = collections.defaultdict(list)
    for r in rows:
        if r.get("acc") is not None and r["acc"] == r["acc"]:
            acc[r["surface"]].append(r["acc"])
    R["mean_acc"] = {k: sum(v) / len(v) for k, v in acc.items()}

    def pearson(a, b):
        n = len(a)
        if n < 3:
            return float("nan")
        ma, mb = sum(a) / n, sum(b) / n
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        da = math.sqrt(sum((x - ma) ** 2 for x in a))
        db = math.sqrt(sum((y - mb) ** 2 for y in b))
        return num / (da * db) if da and db else float("nan")

    feats = ["n_tokens", "degree_mean", "degree_max", "density",
             "spectral_norm", "color_imbalance", "n_colors", "mean_color_class"]
    arms_with_acc = [a for a in ARMS if a in R["mean_acc"]]
    R["corr_with_acc"] = {}
    for k in feats:
        xs = [float(G[a][k]) for a in arms_with_acc]
        ys = [R["mean_acc"][a] for a in arms_with_acc]
        R["corr_with_acc"][k] = pearson(xs, ys)

    # 关键对比：en 池内（en/relperm/entperm）vs 跨池
    in_pool = [a for a in arms_with_acc if pool_of.get(a) ==
               pool_of.get("en")]
    R["en_pool_arms"] = in_pool
    R["en_pool_mean_acc"] = (sum(R["mean_acc"][a] for a in in_pool) / len(in_pool)
                             if in_pool else None)
    out_pool = [a for a in arms_with_acc if a not in in_pool]
    R["other_pool_mean_acc"] = (sum(R["mean_acc"][a] for a in out_pool) / len(out_pool)
                               if out_pool else None)

    with open(os.path.join(RES, "COLLISION.json"), "w") as fh:
        json.dump(R, fh, indent=1, ensure_ascii=False, default=str)

    # ------------------------------------------------------------ Markdown
    L = ["# Token 碰撞图几何与 null 对照合法性认证\n",
         f"n_rel={N_REL}，depth={DEPTH}，probe {N_PROBE} 条。"
         "节点=该表面出现的 token；边=两 token 共享至少一个位置角色。\n",
         "\n## 表 1　各表面的碰撞图几何\n",
         "| 臂 | 词法池 | token 数 | 孤立点 | 度均值 | 度最大 | 密度 | 谱范数 | 颜色类数 | 色失衡 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for a in ARMS:
        g = G[a]
        pid = pool_of[a]
        tag = ("**共享 en 池**" if pid == pool_of["en"] else str(pid))
        L.append(f"| {a} | {tag} | {g['n_tokens']} | {g['n_isolated']} "
                 f"| {g['degree_mean']:.3f} | {g['degree_max']:.0f} "
                 f"| {g['density']:.5f} | {g['spectral_norm']:.4f} "
                 f"| {g['n_colors']} | {g['color_imbalance']:.4f} |")

    L.append("\n## 表 2　null 对照合法性：与每个真实表面的几何逐项比对\n")
    L.append("| 对 | 全部相等 | n_tokens | 谱范数 |")
    L.append("|---|---|---|---|")
    for k, v in legit.items():
        L.append(f"| {k} | {'✓' if v['all_equal'] else '✗'} "
                 f"| {v['n_tokens']} | {v['spectral']} |")
    bad = [k for k, v in legit.items() if not v["all_equal"]]
    L.append(f"\n不等价的配对：{bad if bad else '无——所有 null/真实配对的碰撞几何逐项相同'}\n")

    L.append("\n## 表 3　碰撞几何与平均 acc 的相关（8 臂，n=8）\n")
    L.append("| 特征 | Pearson r |")
    L.append("|---|---|")
    for k, v in R["corr_with_acc"].items():
        L.append(f"| {k} | {v:+.4f} |")

    L.append(f"\n## 表 4　词法池混淆诊断\n")
    L.append(f"- en 池的臂：{', '.join(in_pool)}，平均 acc = **{R['en_pool_mean_acc']:.4f}**")
    L.append(f"- 其他池的臂：{', '.join(out_pool)}，平均 acc = **{R['other_pool_mean_acc']:.4f}**")
    L.append(f"- 差值 = **{R['en_pool_mean_acc']-R['other_pool_mean_acc']:+.4f}**\n")
    L.append("若差值显著不为零，则「真实 vs null」混合了语义因子与词法池因子。\n")

    md = "\n".join(L) + "\n"
    with open(os.path.join(RES, "COLLISION.md"), "w") as fh:
        fh.write(md)

    # ------------------------------------------------------------ 控制台
    print("=" * 76)
    print("[1] 碰撞图几何")
    print("  %-9s %6s %6s %8s %8s %8s %6s" %
          ("arm", "tokens", "isol", "deg_mean", "dens", "spectral", "colors"))
    for a in ARMS:
        g = G[a]
        print("  %-9s %6d %6d %8.3f %8.5f %8.4f %6d" %
              (a, g["n_tokens"], g["n_isolated"], g["degree_mean"],
               g["density"], g["spectral_norm"], g["n_colors"]))

    print("\n[2] null 合法性认证")
    ok = sum(1 for v in legit.values() if v["all_equal"])
    print(f"  12 个 null×真实 配对中，几何逐项相同的有 {ok} 个")
    for k, v in legit.items():
        if not v["all_equal"]:
            diff = [kk for kk, vv in v["per_key"].items() if not vv]
            print(f"  ✗ {k}:不等项 {diff}  ntok={v['n_tokens']}")

    print("\n[3] 几何特征 vs 平均 acc 的相关")
    for k, v in R["corr_with_acc"].items():
        print(f"  {k:20s} r = {v:+.4f}")

    print("\n[4] 词法池混淆")
    print(f"  en 池臂 {in_pool} -> acc {R['en_pool_mean_acc']:.4f}")
    print(f"  其他池  {out_pool} -> acc {R['other_pool_mean_acc']:.4f}")
    print(f"  差值 {R['en_pool_mean_acc']-R['other_pool_mean_acc']:+.4f}")

    print("\n写出 results/COLLISION.json / COLLISION.md")


if __name__ == "__main__":
    main()