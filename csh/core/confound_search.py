"""
confound_search.py — can the signature-overlap confound be separated?

THE CONFOUND, STATED PRECISELY.  Comparing typed against untyped changes two
things at once:

  (1) the type STRUCTURE      branching 2 -> 3, C(3) 24 -> 57, C_eff 24 -> 9
  (2) the SIGNATURE TABLE     how many of the 6 relation symbols still denote
                              the same type transition they denoted in training

For (2), the two frozen assignments line up like this:

    rel:      0      1      2      3      4      5
    typed:  (0,1)  (0,2)  (1,0)  (1,2)  (2,0)  (2,1)
    untyped:(0,1)  (0,0)  (0,0)  (0,0)  (2,0)  (1,2)
            same   DIFF   DIFF   DIFF   same   DIFF

So 4 of 6 symbols changed meaning.  A model that has merely memorised
"token string -> type transition" loses exactly those 4, with no reference to
difficulty at all.  The transfer penalty and the label-permutation penalty
coming out equal (+0.25 vs +0.27) is what that looks like.

WHAT WOULD SEPARATE THEM.  We need substrates that vary INDEPENDENTLY in the
two quantities.  Define

    overlap(v) = |{i : assign_v[i] == assign_typed[i]}|        0..6
    branching(v)

A substrate with HIGH overlap but branching 3 would have the signature table
mostly intact while the structure is genuinely harder.  If transfer to it is
FREE, the penalty tracks structure, not memorised symbol meaning.  A substrate
with LOW overlap but branching 2 would have the reverse profile.

So this script SEARCHES the space of 6-relation substrates, keeping every
structural requirement the transfer design imposes (3 dom types and 3 ran
types covered, no dead-end relation, every depth-3 problem solvable), and
reports which (overlap, branching) combinations actually EXIST.  Whatever the
search returns determines whether the confound is separable in principle at
this n_rel, or whether it is a genuine property of the design.
"""

import itertools
import random
import sys

from substrate2 import Gen, c_eff

TYPED = [(0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)]
UNTYPED = [(0, 1), (0, 0), (0, 0), (0, 0), (2, 0), (1, 2)]
NR = 6
DEPTH = 3


def m_of(assign):
    n = len(assign)
    m = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if assign[i][1] == assign[j][0]:
                m[i][j] = 1
    return m


def admissible(assign):
    """Every structural constraint the transfer design relies on."""
    m = m_of(assign)
    doms = {a[0] for a in assign}
    rans = {a[1] for a in assign}
    if doms != {0, 1, 2} or rans != {0, 1, 2}:
        return False, "type coverage"
    if any(sum(m[i]) == 0 for i in range(NR)):
        return False, "dead end"
    g = Gen({"assign": assign, "m": m, "n_rel": NR,
             "pools": [list(range(0, 7)), list(range(7, 12)), list(range(12, 18))]},
            seed=0)
    y = sum(1 for _ in range(200) if g.make(DEPTH))
    if y < 200:
        return False, f"yield {y}/200"
    return True, "ok"


def overlap(assign):
    return sum(1 for a, b in zip(assign, TYPED) if a == b)


def branching(assign):
    m = m_of(assign)
    return sum(sum(r) for r in m) / NR


def main():
    print("searching all 6-relation substrates that pass every structural check")
    print(f"typed   = {TYPED}  branching {branching(TYPED):.2f}  overlap 6")
    print(f"untyped = {UNTYPED}  branching {branching(UNTYPED):.2f}  overlap "
          f"{overlap(UNTYPED)}\n")

    seen = {}
    for assign in itertools.product(list(itertools.product(range(3), range(3))),
                                    repeat=NR):
        if len(assign) != NR:
            continue
        ok, why = admissible(list(assign))
        if not ok:
            continue
        a = list(assign)
        key = (overlap(a), branching(a))
        if key not in seen:
            c3, eff = c_eff(a, DEPTH)
            seen[key] = (a, c3, eff)

    print(f"{len(seen)} distinct (overlap, branching) cells exist:\n")
    print(f"{'ovl':>4} {'branch':>7} {'C(3)':>6} {'C_eff':>6}  assign")
    print("-" * 78)
    for (ov, br) in sorted(seen):
        a, c3, eff = seen[(ov, br)]
        mark = ""
        if (ov, br) == (6, 2.0):
            mark = "  <- typed"
        if (ov, br) == (overlap(UNTYPED), branching(UNTYPED)):
            mark = "  <- untyped (current 'other substrate')"
        print(f"{ov:4d} {br:7.2f} {c3:6d} {eff:6d}  {a}{mark}")

    # which cells would actually be informative?
    print("\n" + "=" * 78)
    print("SEPARABILITY")
    print("=" * 78)
    cells = sorted(seen)
    brs = sorted({b for _, b in cells})
    ovs = sorted({o for o, _ in cells})
    print(f"  overlap values present : {ovs}")
    print(f"  branching values present: {brs}")
    if len(brs) >= 2 and len(ovs) >= 2:
        grid = {(o, b) for o, b in cells}
        # want: same branching, different overlap  AND  same overlap,
        # different branching.  Either alone breaks the confound.
        same_br = [(o, b) for o, b in cells
                   if sum(1 for x, _ in cells if x == b) and
                   len({o2 for o2, b2 in cells if b2 == b}) >= 2]
        same_ov = [(o, b) for o, b in cells
                   if len({b2 for o2, b2 in cells if o2 == o}) >= 2]
        if same_br:
            print(f"  SAME branching, different overlap (structure held fixed):")
            for b in brs:
                os_ = sorted(o for o, bb in cells if bb == b)
                if len(os_) >= 2:
                    print(f"    branching {b}: overlaps {os_}")
        if same_ov:
            print(f"  SAME overlap, different branching (signature table held fixed):")
            for o in ovs:
                bs = sorted(b for oo, b in cells if oo == o)
                if len(bs) >= 2:
                    print(f"    overlap {o}: branchings {bs}")
    else:
        print("  Only one value of overlap or branching survives the structural")
        print("  constraints -> the two quantities CANNOT be varied independently")
        print("  at n_rel = 6, and the confound is not separable in this design.")


if __name__ == "__main__":
    main()
