"""
latin.py — 拉丁方 id 配平（codex `surface_fix2.py` 的设计，移植为公共模块）

=====================================================================

为什么必须用这个而不是"固定 slot"
-----------------------------------
`S1_FINAL.md` 结论三的实测证据：

固定同一表面（en）、同一数据、同一种子，只改 id 块位置：

    slot     n=4000   n=6500
      0      0.5858   1.0000
      1      0.3225   0.7358
      2      0.7258   0.7700
      3      0.9833   1.0000
      4      0.2467   0.7208
      5      0.4042   0.9358

    n=4000 极差 0.1675–1.0000
    方差分解: between-slot 0.06414 / within-slot 0.06184，比值 1.04

机制：`torch.manual_seed(seed)` 后 `Solver(vocab_size)` 按固定顺序初始化
embedding，token 落在哪个 id 区间决定它分到哪一行随机初始化。
**这是初始化运气，不是符号身份效应。**

我最初给E4/E6/E8/E10 写的共享词表是**固定 slot**（每个表面一个固定区间），
正是这个被证伪的设计。若不换，下游实验的表面间差异会混入 slot噪声。

正确设计：6x6 循环拉丁方
-------------------------
    seed s, surface i  ->  id 块 slot = (i + s) mod 6

每个表面在 6 个种子上恰好经历全部 6 个 id 区间各一次，slot 完全配平，
surface 主效应与 slot 主效应可分离。

对下游实验的适配
----------------
本模块与 `surface_fix2.py` 的差别：后者 `NAMES` 是固定的 6 个真实表面；
下游实验里"表面"集合不同（E4 是变换，E6 含 relperm/entperm，E8/E1 有 7 个）。
故本模块把 NAMES 变成参数，并保持同一配平原理：

    slot = (surface_index + seed) mod n_surfaces

要求：种子数 ≥ n_surfaces，否则配平不完全（会退化回固定 slot 的问题）。
E4 只有 3 个变换 × 6 seeds，E6 有 3 表面 × 6 seeds —— 都满足。
E8 用 4 seeds × 7 表面 —— **不满足**，见下方 warnings()。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
if PKG not in sys.path:
    sys.path.insert(0, PKG)

from surfaces import Surface, PermutedSurface  # noqa: E402
from substrate2 import build, Gen             # noqa: E402
from model import Vocab                       # noqa: E402

PROBE_SEED = 4242
DEPTH = 3


def make_surface(name, n_rel):
    """relperm / entperm 是 en 的置换版本，其余走 Surface。"""
    if name == "relperm":
        return PermutedSurface("en", n_rel, mode="rel")
    if name == "entperm":
        return PermutedSurface("en", n_rel, mode="ent")
    return Surface(name, n_rel)


def slot_of(names, surface, seed):
    """6x6 循环拉丁方：seed s, surface i -> slot (i + s) mod len(names)。"""
    return (names.index(surface) + seed) % len(names)


def build_vocab(names, surface, slot, depth=DEPTH, n_test=400, n_rel=6):
    """构造共享词表：`surface` 落在 block `slot`，其余按 names 顺序填剩余块。

    返回 (vocab, index_of_surface)。

    与 surface_fix2.py 同一设计：vocab 总量固定（所有表面都被编码），
    但当前训练表面的 id 区间随种子轮转，从而与 slot 噪声解耦。

    n_rel 必须与调用方的实际关系数一致。E6 的 mult=2/3/4 对应
    n_rel = 12/18/24；若沿用默认 6，词表会缺 rel6..rel23 等标签，
    编码时抛 "tokens missing"。这个坑已实测踩过。
    """
    order = [n for n in names if n != surface]
    order.insert(slot, surface)
    v = Vocab()
    # probe 也必须按 n_rel 造，否则 n_rel>6 时 rel6..relN 这些标签采不到，
    # 词表会缺项（实测报 tokens missing: rel1/faces/covers）。
    sub = build(1)
    mult = max(1, n_rel // 6)
    probe_sub = build(mult)
    probe = Gen(probe_sub, seed=PROBE_SEED).dataset(n_test, [depth],
                                                    seed=PROBE_SEED)
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
    """把Problem 渲染成带 id 前缀的 tokens/target。"""
    s = make_surface(surface_name, n_rel)
    key = lambda t: "%d\x00%s" % (slot_index, t)
    return [{"tokens": [key(t) for t in s.render(p)["tokens"]],
             "target": [key(s.render(p)["target"][0])]}
            for p in problems]


def check_parity(names, n_seeds):
    """配平前提检查：种子数必须 ≥ 表面数，否则配平不完全。"""
    ns = len(names)
    ok = n_seeds >= ns
    return ok, (f"表面数 {ns} > 种子数 {n_seeds}："
                f"slot 配平不完全，表面主效应会与 slot 噪声纠缠。"
                f"建议把 seeds 提到 {ns}。")


if __name__ == "__main__":
    import itertools
    print("拉丁方配平自检")
    print("=" * 60)
    for names, seeds in ((["zh", "en", "lisp", "math", "code", "alien"], 6),
                         (["en", "relperm", "entperm"], 6),
                         (["root_swap", "chain_reverse", "null_renaming"], 6),
                         (["zh", "en", "lisp", "math", "code", "alien",
                           "relperm"], 4)):
        ok, msg = check_parity(names, seeds)
        print(f"\n表面 {len(names)} 个 / 种子 {seeds} 个 -> "
              f"{'OK' if ok else '不满足'}")
        if not ok:
            print("  " + msg)
        if ok:
            tbl = {s: [slot_of(names, s, sd) for sd in range(seeds)]
                   for s in names}
            for s, v in tbl.items():
                print(f"  {s:>16}: {v}")
            # 验证：每个表面是否恰好遍历全部 slot
            full = all(sorted(v) == list(range(len(names))) for v in tbl.values())
            print(f"  每表面恰好遍历全部 slot: {full}")
