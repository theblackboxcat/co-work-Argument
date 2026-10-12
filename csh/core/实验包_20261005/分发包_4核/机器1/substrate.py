"""
substrate.py — the relational substrate: the ONLY thing that varies.

PROBLEM. A problem gives a set of binary facts (a, r, b) and a query
(start, [r_1..r_k]); the answer is the endpoint of the chain obtained by
composing k relational steps. Depth-3 requires 2 compositions, i.e. the
model cannot succeed by copying a single fact.

DESIGN — one clean complexity knob, fully decoupled from compute.

  branching factor  = 2   for EVERY condition (each relation's ran-type is
                           the dom-type of exactly 2 relations)
  facts per problem = fixed
  TOKENS PER FACT   = 5   for EVERY condition and EVERY surface
  entities          = 18   for EVERY condition

  complexity knob   = N_REL, the number of distinct relation symbols the
                      learner must acquire: 2 / 4 / 6 / 10.

This matters. Naively "more legal relation sequences = harder" is wrong:
a high branching factor makes the constraint vacuous and the task solvable
by pattern matching. What actually costs data is having to *distinguish* more
relational primitives. So N_REL is the operationalisation of substrate
complexity, and it is exactly the quantity the theory says sets the
emergence threshold. Reported alongside C(k) = N_REL * 2^(k-1).

SECOND factor — SEMANTICS. Whether the relation symbols are labelled with
human sensory primitives (containment / succession / agent-patient) or with
arbitrary opaque tokens. The transition structure is IDENTICAL across the two
arms; only the labels differ. This separates lexical semantics from structure.
"""

import random
from dataclasses import dataclass
from typing import List, Tuple

N_ENT = 18

# ------------------------------------------------------- human sensory labels
# 4 sensory primitives; each level uses the first N_REL//2 of them.
SENSORY = [
    ("IN",     "OBJ", "CON"),   # containment
    ("BEFORE", "EVT", "EVT"),   # succession
    ("ACT",    "AGT", "OBJ"),   # agent-patient
    ("MOVE",   "CON", "EVT"),   # transfer of contents
    ("NEAR",   "OBJ", "EVT"),
]
N_TYPE_MAX = len(SENSORY)


def _sizes(n_types):
    """Split 18 entities as evenly as possible over n_types pools."""
    base = N_ENT // n_types
    rem = N_ENT % n_types
    pools, cur = [], 0
    for i in range(n_types):
        n = base + (1 if i < rem else 0)
        pools.append(list(range(cur, cur + n)))
        cur += n
    return pools


def build(n_rel: int):
    """Transition structure: n_rel/2 types, 2 relations leaving each type."""
    assert n_rel % 2 == 0 and 2 <= n_rel <= 2 * N_TYPE_MAX
    n_types = n_rel // 2
    pools = _sizes(n_types)
    assign = []
    for t in range(n_types):
        for d, r in ((t, t), (t, (t + 1) % n_types)):
            assign.append((d, r))
    m = [[0] * n_rel for _ in range(n_rel)]
    for i in range(n_rel):
        for j in range(n_rel):
            if assign[i][1] == assign[j][0]:
                m[i][j] = 1
    return {"n_rel": n_rel, "n_types": n_types, "assign": assign, "m": m,
            "pools": pools, "branching": sum(sum(r) for r in m) / n_rel}


def branching_counts(m, kmax=4):
    """C(k) = # legal relation sequences of length k."""
    n = len(m)
    cur = [1] * n
    out = [sum(cur)]
    for _ in range(2, kmax + 1):
        cur = [sum(cur[j] for j in range(n) if m[i][j]) for i in range(n)]
        out.append(sum(cur))
    return out


@dataclass
class Problem:
    facts: List[Tuple[int, int, int]]
    start: int
    seq: List[int]
    answer: int
    depth: int


class Gen:
    """Identical problems for identical (n_rel, seed), independent of surface,
    so surface conditions are compared on exactly the same data."""

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
        cnt, frontier = 0, [(start, 0)]
        while frontier:
            node, d = frontier.pop()
            if d == len(seq):
                cnt += 1
                continue
            for b in adj.get((node, seq[d]), ()):
                frontier.append((b, d + 1))
        return cnt

    def make(self, k, tries=80):
        nr, pools = self.n_rel, self.pools
        for _ in range(tries):
            seq = self.legal_seq(k)
            if seq is None:
                continue
            start = self.rng.choice(pools[self.assign[seq[0]][0]])
            chain, used, ok = [], {start}, True
            prev = start
            for r in seq:
                cand = [e for e in pools[self.assign[r][1]] if e not in used]
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

            off = [e for p in pools for e in p if e not in used]
            self.rng.shuffle(off)
            pairs = {(a, r) for a, r, _ in facts}
            added = 0
            for a in off:
                if added >= self.n_distract:
                    break
                r = self.rng.randrange(nr)
                cand = [e for e in pools[self.assign[r][1]] if e not in used]
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
    print(f"{'n_rel':6} {'types':6} {'branch':7} {'C(k) k=1..4':26} "
          f"{'fact tokens':12} yield")
    for nr in (2, 4, 6, 10):
        s = build(nr)
        g = Gen(s, seed=0)
        ys = []
        for k in (1, 2, 3):
            got = sum(1 for _ in range(120) if g.make(k))
            ys.append(f"k{k}:{got}/120")
        print(f"{nr:<6} {s['n_types']:<6} {s['branching']:<7.2f} "
              f"{str(branching_counts(s['m'],4)):26} {'5':12} {' '.join(ys)}")
