"""
S1_DEFECT_verify.py — 一条命令复现 S1 承重检验的缺陷。

三个证据：
  1. 逐位相同矩阵：6 个"表面"实际只有 4 个独立数字
  2. id 序列比较：zh/math/alien 是逐 token 相同的输入
  3. 权重比较：zh 与 math 训练出的权重逐位相同

用法：
  python S1_DEFECT_verify.py              # 证据 1（秒级）
  python S1_DEFECT_verify.py --weights    # 加跑证据 3（需 torch，约 3 分钟）
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "results", "final_merged.jsonl")
SURF = ["zh", "en", "lisp", "math", "code", "alien", "relperm", "entperm"]


def load():
    rows = [json.loads(l) for l in open(DATA, encoding="utf-8") if l.strip()]
    return [r for r in rows if r["arm"] == "S"]


def evidence1(S):
    ns = sorted({r["n_train"] for r in S})
    seeds = sorted({r["seed"] for r in S})
    cm = lambda s, n: {r["seed"]: r["acc"] for r in S
                       if r["surface"] == s and r["n_train"] == n}
    N = len(ns) * len(seeds)
    print("=" * 74)
    print("EVIDENCE 1  exact-match matrix  (%d cells = %d n x %d seeds)"
          % (N, len(ns), len(seeds)))
    print("=" * 74)
    print("      " + "".join("%9s" % s[:8] for s in SURF))
    for a in SURF:
        row = "".join("%9d" % sum(1 for n in ns for z in seeds
                                  if cm(a, n)[z] == cm(b, n)[z])
                      for b in SURF)
        print("%6s" % a[:6] + row)
    print()
    print("  cells = 180 => bit-identical. Clusters:")
    print("    {zh, math, alien}      one input, computed three times")
    print("    {en, relperm, entperm} one input, computed three times")
    print("  => 6 'surfaces' carry only 4 independent numbers.")


def evidence2():
    import sys as _s
    _s.path.insert(0, HERE)
    from surfaces import Surface, PermutedSurface
    from substrate2 import Gen, build
    from model import build_vocab
    sub = build(1)
    ps = Gen(sub, seed=1000).dataset(30, [3], seed=0)

    def enc(sf):
        tr = [sf.render(p) for p in ps]
        v = build_vocab(tr)
        return [[v.stoi["<bos>"]] + [v.stoi[t] for t in r["tokens"]]
                for r in tr], v
    print()
    print("=" * 74)
    print("EVIDENCE 2  the id sequences the MODEL actually sees")
    print("=" * 74)
    print("  token STRINGS differ:")
    for n in ["zh", "en", "math", "alien"]:
        print("    %-6s fact: %s" % (n, " ".join(Surface(n, 6).fact(0, 0, 1))))
    print()
    z, _ = enc(Surface("zh", 6))
    for n in ["en", "math", "alien", "lisp", "code"]:
        o, _ = enc(Surface(n, 6))
        ident = sum(1 for a, b in zip(z, o) if a == b)
        print("    zh vs %-6s : %2d/30 id-sequences IDENTICAL" % (n, ident))
    rp, _ = enc(PermutedSurface("en", 6, mode="rel"))
    en, _ = enc(Surface("en", 6))
    print("    en vs relperm: %2d/30 id-sequences IDENTICAL"
          % sum(1 for a, b in zip(en, rp) if a == b))
    print()
    print("  => zh/math/alien are different LANGUAGES but the model receives")
    print("     numerically identical input. Equal accuracy is a tautology.")


def evidence3():
    import sys as _s
    _s.path.insert(0, HERE)
    import torch
    from surfaces import Surface
    from substrate2 import Gen, build
    from model import build_vocab, train_model
    sub = build(1)

    def run(sf, seed, n=2000):
        g = Gen(sub, seed=1000 + seed); g2 = Gen(sub, seed=99991)
        tr = g.dataset(n, [3], seed=seed); te = g2.dataset(400, [3], seed=seed + 555)
        s = Surface(sf, 6)
        trr = [s.render(p) for p in tr]; ter = [s.render(p) for p in te]
        v = build_vocab(trr + ter)
        m, a, _ = train_model(v, trr, ter, epochs=1, batch=32, lr=3e-4, seed=seed)
        return m, a, len(v)
    print()
    print("=" * 74)
    print("EVIDENCE 3  trained weights, zh vs math (seed 0, n=2000)")
    print("=" * 74)
    mz, az, _ = run("zh", 0); mm, am, _ = run("math", 0)
    pz = torch.cat([p.detach().flatten() for p in mz.parameters()])
    pm = torch.cat([p.detach().flatten() for p in mm.parameters()])
    print("  zh   acc=%.4f   math acc=%.4f" % (az, am))
    print("  weights BIT-IDENTICAL: %s" % torch.equal(pz, pm))
    print("  max |weight diff|: %.3e" % (pz - pm).abs().max().item())


if __name__ == "__main__":
    evidence1(load())
    evidence2()
    if "--weights" in sys.argv:
        evidence3()
    else:
        print("\n(add --weights to also compare trained weights; needs torch)")
