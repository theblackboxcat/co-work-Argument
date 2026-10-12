"""
substrate2.py — the corrected complexity knob, and a sharper hypothesis.

The confound. In substrate.py the knob N_REL changed two things at once: the
number of relation symbols to acquire, AND the constraining power of the type
structure. diagnose.py showed the second dominates (at N_REL=2 there is a
single type, so r0 and r1 share a type signature, the type structure cannot
separate them, and the small-N_REL levels came out HARDER — inverting the naive
prediction). So the coarse pass cannot test H2.

Can branching and vocabulary be decoupled? No. With `mult` relations realising
each type transition and two outgoing transitions per type, branching = 2*mult
necessarily. Any knob that raises the vocabulary raises branching with it.

So use that. Let `mult` vary with the type structure held FIXED:

    n_types = 3 always, 2 outgoing transitions per type always
    mult    = 1, 2, 3, 4     ->  n_rel = 6*mult

Then, as `mult` grows:
    N_REL      grows        (more concrete relation symbols to acquire)
    branching  grows        (2*mult legal successors)
    C(k)       grows        (N_REL * branching^(k-1))
    C_eff(k)   CONSTANT     (the type-transition signatures never change)

C_eff(k) — the number of distinguishable type-transition patterns — is exactly
the quantity substrate.py's diagnose.py identified as what the learner can
actually share statistics over. Holding it fixed while N_REL and branching
grow separates the two readings of the theory:

    reading A  threshold tracks C_eff  — complexity is the cognitive
              structure (types, relations, nesting, order); extra concrete
              symbols are interchangeable labels and cost nothing
    reading B  threshold tracks N_REL or C(k) — complexity is raw symbolic
              count, and every extra primitive must be learned

This is a sharper question than the original H2, and it is the version the
theory actually needs: the user's claim is that the shared cognitive structure,
not the symbol count, sets the threshold. Reading A is the claim; reading B is
its negation.
"""

import itertools
import random
from dataclasses import dataclass
from typing import List, Tuple

N_ENT = 18
N_TYPES = 3

# 3 types; every type has exactly TWO outgoing transitions.
# Entity ids 0..17 split across the 3 types.
TYPE_POOL = {0: list(range(0, 7)), 1: list(range(7, 12)), 2: list(range(12, 18))}
TYPE_SIGS = [(0, 1), (0, 2),
             (1, 0), (1, 2),
             (2, 0), (2, 1)]


def build(mult: int):
    """mult = number of concrete relations per type transition.
    n_rel = 6 * mult.  Type structure is identical for every mult."""
    assert mult >= 1
    assign = []
    for sig in TYPE_SIGS:
        assign.extend([sig] * mult)
    n = len(assign)
    m = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if assign[i][1] == assign[j][0]:
                m[i][j] = 1
    return {"mult": mult, "n_rel": n, "n_types": N_TYPES, "assign": assign,
            "m": m, "pools": [TYPE_POOL[t] for t in range(N_TYPES)],
            "branching": sum(sum(r) for r in m) / n}


def branching_counts(m, kmax=4):
    n = len(m)
    cur = [1] * n
    out = [sum(cur)]
    for _ in range(2, kmax + 1):
        cur = [sum(cur[j] for j in range(n) if m[i][j]) for i in range(n)]
        out.append(sum(cur))
    return out


def c_eff(assign, depth=3):
    """# legal sequences and # distinct type-transition signatures at `depth`."""
    n = len(assign)
    m = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if assign[i][1] == assign[j][0]:
                m[i][j] = 1
    seqs = [s for s in itertools.product(range(n), repeat=depth)
            if all(m[s[i]][s[i + 1]] for i in range(depth - 1))]
    eff = {tuple(assign[r] for r in s) for s in seqs}
    return len(seqs), len(eff)


@dataclass
class Problem:
    facts: List[Tuple[int, int, int]]
    start: int
    seq: List[int]
    answer: int
    depth: int


class Gen:
    def __init__(self, sub, seed=0, n_distract=5):
        self.sub = sub
        self.n_rel = sub["n_rel"]
        self.assign = sub["assign"]
        self.pools = sub["pools"]
        self.m = sub["m"]
        self.rng = random.Random(seed)
        self.n_distract = n_distract

    def legal_seq(self, k):
        seq = []
        for _ in range(k):
            legal = ([j for j in range(self.n_rel) if self.m[seq[-1]][j]]
                     if seq else list(range(self.n_rel)))
            if not legal:
                return None
            seq.append(self.rng.choice(legal))
        return seq

    def _npaths(self, adj, start, seq):
        cnt, fr = 0, [(start, 0)]
        while fr:
            node, d = fr.pop()
            if d == len(seq):
                cnt += 1
                continue
            for b in adj.get((node, seq[d]), ()):
                fr.append((b, d + 1))
        return cnt

    def make(self, k, tries=80):
        nr = self.n_rel
        for _ in range(tries):
            seq = self.legal_seq(k)
            if seq is None:
                continue
            start = self.rng.choice(self.pools[self.assign[seq[0]][0]])
            chain, used, ok = [], {start}, True
            prev = start
            for r in seq:
                cand = [e for e in self.pools[self.assign[r][1]] if e not in used]
                if not cand:
                    ok = False
                    break
                e = self.rng.choice(cand)
                chain.append((prev, r, e))
                used.add(e)
                prev = e
            if not ok:
                continue
            facts, adj = [], {}
            for a, r, b in chain:
                facts.append((a, r, b))
                adj.setdefault((a, r), []).append(b)
            answer = chain[-1][2]

            off = [e for p in self.pools for e in p if e not in used]
            self.rng.shuffle(off)
            pairs = {(a, r) for a, r, _ in facts}
            added = 0
            for a in off:
                if added >= self.n_distract:
                    break
                r = self.rng.randrange(nr)
                cand = [e for e in self.pools[self.assign[r][1]] if e not in used]
                if not cand:
                    continue
                b = self.rng.choice(cand)
                if (a, r) in pairs or b == answer:
                    continue
                facts.append((a, r, b))
                adj.setdefault((a, r), []).append(b)
                pairs.add((a, r))
                used.add(b)
                added += 1

            # Top up to exactly n_distract. Substrates with higher branching
            # exhaust the first pass sooner, which would otherwise leak a
            # substrate-dependent fact count (and hence token count) into the
            # comparison. Retry remaining (a, r) pairs with fresh draws.
            if added < self.n_distract:
                order = [(a, r) for a in off for r in range(nr)]
                self.rng.shuffle(order)
                for (a, r) in order:
                    if added >= self.n_distract:
                        break
                    if (a, r) in pairs:
                        continue
                    cand = [e for e in self.pools[self.assign[r][1]]
                            if e not in used and e != answer]
                    if not cand:
                        continue
                    b = self.rng.choice(cand)
                    facts.append((a, r, b))
                    adj.setdefault((a, r), []).append(b)
                    pairs.add((a, r))
                    used.add(b)
                    added += 1

            if added < self.n_distract:
                continue
            if self._npaths(adj, start, seq) != 1:
                continue
            return Problem(facts, start, seq, answer, k)
        return None

    def dataset(self, n, depths, seed):
        rng = random.Random(seed * 7919 + 13)
        ks = list(depths)
        out, guard = [], 0
        while len(out) < n and guard < 80 * n:
            guard += 1
            p = self.make(rng.choice(ks))
            if p is not None:
                out.append(p)
        return out


if __name__ == "__main__":
    print("corrected knob: type structure FIXED (3 types, 2 outgoing each)\n")
    print(f"{'mult':>5} {'n_rel':>6} {'branch':>7} {'C(3)':>7} {'C_eff(3)':>9} "
          f"{'fixed?':>7}  yield")
    base = None
    for mult in (1, 2, 3, 4):
        s = build(mult)
        c3, eff = c_eff(s["assign"], 3)
        if base is None:
            base = eff
        g = Gen(s, seed=0)
        ys = [sum(1 for _ in range(100) if g.make(k)) for k in (1, 2, 3)]
        print(f"{mult:5d} {s['n_rel']:6d} {s['branching']:7.2f} {c3:7d} {eff:9d} "
              f"{'YES' if eff == base else 'NO':>7}  "
              f"k1={ys[0]}/100 k2={ys[1]}/100 k3={ys[2]}/100")
    print("\nC_eff(3) is constant while N_REL and branching grow.")
    print("  threshold flat  in mult  ->  supports reading A (cognitive structure")
    print("                                      sets the threshold)")
    print("  threshold rising in mult  ->  supports reading B (raw symbolic count")
    print("                                      sets the threshold)")
