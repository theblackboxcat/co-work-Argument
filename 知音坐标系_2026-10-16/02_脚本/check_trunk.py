#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validator CLI for trunk JSON (+ optional anchors JSON).

Hard integrity failures (dangling parent/edge refs, cycles) → exit 1.
Soft reports (layer counts, gold edge coverage, random baselines) always printed.

Usage:
  python3 check_trunk.py trunk_v0.json
  python3 check_trunk.py trunk_v0.json --anchors anchors.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


EDGE_KINDS = frozenset({"parent", "contrast", "ban"})


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def p_at_least_one_hit(N: int, g: int, k: Optional[int] = None) -> float:
    """P(≥1 gold hit) under uniform draw of k ids from N, gold size g.
    Default k = |gold| = g.
    """
    if k is None:
        k = g
    if N <= 0 or k <= 0 or g <= 0:
        return 0.0
    if k > N:
        return 1.0
    if N - g < k:
        return 1.0
    return 1.0 - comb(N - g, k) / comb(N, k)


def find_cycles(parent_of: Dict[str, Optional[str]]) -> List[List[str]]:
    """Return list of cycle paths (node id chains) among parent pointers."""
    cycles: List[List[str]] = []
    seen_global: Set[str] = set()
    for start in parent_of:
        if start in seen_global:
            continue
        path: List[str] = []
        idx: Dict[str, int] = {}
        cur: Optional[str] = start
        while cur is not None:
            if cur in idx:
                cycles.append(path[idx[cur] :] + [cur])
                break
            if cur in seen_global:
                break
            idx[cur] = len(path)
            path.append(cur)
            cur = parent_of.get(cur)
        seen_global.update(path)
    return cycles


def undirected_edge_index(
    edges: List[dict],
) -> Dict[frozenset, List[dict]]:
    idx: Dict[frozenset, List[dict]] = defaultdict(list)
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a and b:
            idx[frozenset([a, b])].append(e)
    return idx


def gold_nodes_of(anchor: dict) -> List[str]:
    """Support both gold.nodes (schema v1) and gold_node_ids (demo v0)."""
    gold = anchor.get("gold")
    if isinstance(gold, dict) and "nodes" in gold:
        return list(gold.get("nodes") or [])
    if "gold_node_ids" in anchor:
        return list(anchor.get("gold_node_ids") or [])
    return []


def gold_edges_of(anchor: dict) -> List[dict]:
    gold = anchor.get("gold")
    if isinstance(gold, dict):
        return list(gold.get("edges") or [])
    return []


def check_trunk(trunk: dict, anchors: Optional[dict] = None) -> int:
    """Print prereg-ready tables. Return 0 if hard OK, 1 on integrity failure."""
    hard_fail = False
    nodes = trunk.get("nodes") or []
    edges = trunk.get("edges") or []
    id_list = [n["id"] for n in nodes if "id" in n]
    id_set: Set[str] = set(id_list)
    N = len(id_set)

    # --- parent refs ---
    parent_of: Dict[str, Optional[str]] = {}
    dangling_parents: List[Tuple[str, str]] = []
    for n in nodes:
        nid = n.get("id")
        if not nid:
            hard_fail = True
            print("HARD: node missing id")
            continue
        p = n.get("parent")
        parent_of[nid] = p
        if p is not None and p not in id_set:
            dangling_parents.append((nid, p))
            hard_fail = True

    # --- cycles ---
    cycles = find_cycles(parent_of)
    if cycles:
        hard_fail = True

    # --- edges ---
    dangling_edges: List[dict] = []
    bad_kinds: List[dict] = []
    for e in edges:
        frm, to, kind = e.get("from"), e.get("to"), e.get("kind")
        if frm not in id_set or to not in id_set:
            dangling_edges.append(e)
            hard_fail = True
        if kind not in EDGE_KINDS:
            bad_kinds.append(e)
            hard_fail = True

    # ========== REPORT ==========
    print("=" * 64)
    print("check_trunk · integrity + prereg tables")
    print("=" * 64)

    meta = trunk.get("meta") or {}
    print(f"\n## Meta")
    print(f"- trunk id: {meta.get('id', '(none)')}")
    print(f"- N nodes (unique ids): {N}")
    print(f"- edges array length: {len(edges)}")
    print(f"- nodes with parent field set: {sum(1 for p in parent_of.values() if p is not None)}")

    print(f"\n## Hard integrity")
    if dangling_parents:
        print(f"- FAIL dangling parents ({len(dangling_parents)}):")
        for nid, p in dangling_parents:
            print(f"    {nid} → parent={p}")
    else:
        print("- parent refs: OK (all resolve or null)")
    if cycles:
        print(f"- FAIL cycles ({len(cycles)}):")
        for c in cycles:
            print(f"    {' → '.join(c)}")
    else:
        print("- parent cycles: OK (none)")
    if dangling_edges:
        print(f"- FAIL dangling edge endpoints ({len(dangling_edges)}):")
        for e in dangling_edges:
            print(f"    {e}")
    else:
        print("- edge endpoints: OK")
    if bad_kinds:
        print(f"- FAIL edge kind not in parent|contrast|ban ({len(bad_kinds)}):")
        for e in bad_kinds:
            print(f"    {e}")
    else:
        print("- edge kinds: OK")

    # layer counts
    layer_counts = Counter(n.get("layer") for n in nodes)
    print(f"\n## Layer distribution")
    print("| layer | count |")
    print("|-------|------:|")
    for layer in ("trunk", "branch", "stop"):
        print(f"| {layer} | {layer_counts.get(layer, 0)} |")
    other = {k: v for k, v in layer_counts.items() if k not in ("trunk", "branch", "stop")}
    for k, v in sorted(other.items(), key=lambda x: str(x[0])):
        print(f"| {k} | {v} |")
    print(f"| **total** | **{sum(layer_counts.values())}** |")
    print(f"\nCanonical shallow v0 pattern: trunk/branch/stop = 1/4/22 (if N=27).")

    # branch sizes (children of each branch-layer node + trunk)
    children: Dict[Optional[str], List[str]] = defaultdict(list)
    for nid, p in parent_of.items():
        children[p].append(nid)
    print(f"\n## Branch sizes (direct children by parent)")
    print("| parent_id | layer | #children |")
    print("|-----------|-------|----------:|")
    # roots first, then by id
    roots = [n["id"] for n in nodes if n.get("parent") is None]
    ordered_parents = roots + [n["id"] for n in nodes if n.get("parent") is not None]
    shown = set()
    for pid in ordered_parents:
        if pid in shown:
            continue
        if pid not in children and parent_of.get(pid) is not None:
            # leaf — skip unless we want only non-leaves
            pass
        kids = children.get(pid, [])
        if not kids:
            continue
        shown.add(pid)
        layer = next((n.get("layer") for n in nodes if n["id"] == pid), "?")
        print(f"| {pid} | {layer} | {len(kids)} |")

    # edge kind breakdown
    kind_counts = Counter(e.get("kind") for e in edges)
    print(f"\n## Edges array (as stored; may omit hierarchy parents)")
    print("| kind | count |")
    print("|------|------:|")
    for k in ("parent", "contrast", "ban"):
        print(f"| {k} | {kind_counts.get(k, 0)} |")
    print(f"| **total** | **{len(edges)}** |")

    # anchors
    if anchors is not None:
        alist = anchors.get("anchors") or []
        print(f"\n## Anchors gold ⊆ trunk")
        outside: List[Tuple[str, str]] = []
        for a in alist:
            aid = a.get("id", "?")
            for gid in gold_nodes_of(a):
                if gid not in id_set:
                    outside.append((aid, gid))
                    hard_fail = True
        if outside:
            print(f"- FAIL gold nodes not in trunk ({len(outside)}):")
            for aid, gid in outside:
                print(f"    {aid}: {gid}")
        else:
            print(f"- OK: all gold nodes ⊆ trunk ({len(alist)} anchors)")

        edge_idx = undirected_edge_index(edges)
        print(f"\n## Gold edge coverage (any edges-array link between each gold pair)")
        print("| anchor | gold nodes | gold pairs | pairs with ≥1 edge | missing pairs |")
        print("|--------|------------|----------:|-------------------:|---------------|")
        for a in alist:
            aid = a.get("id", "?")
            gnodes = gold_nodes_of(a)
            pairs = []
            hit = 0
            missing = []
            for i in range(len(gnodes)):
                for j in range(i + 1, len(gnodes)):
                    pair = frozenset([gnodes[i], gnodes[j]])
                    pairs.append(pair)
                    if pair in edge_idx:
                        hit += 1
                    else:
                        missing.append(f"{gnodes[i]}↔{gnodes[j]}")
            miss_s = ", ".join(missing) if missing else "—"
            print(
                f"| {aid} | {len(gnodes)} ({', '.join(gnodes) or '∅'}) | "
                f"{len(pairs)} | {hit} | {miss_s} |"
            )
            # also report declared gold.edges if present
            declared = gold_edges_of(a)
            if declared:
                print(f"  · declared gold.edges ({len(declared)}): {declared}")

        print(f"\n## Per-anchor random baseline (uniform draw k=|gold| from N={N})")
        print("| anchor | |gold| | k | P(≥1 hit) | note |")
        print("|--------|------:|--:|----------:|------|")
        joint = 1.0
        for a in alist:
            aid = a.get("id", "?")
            g = len(gold_nodes_of(a))
            p = p_at_least_one_hit(N, g, k=g) if g > 0 else 0.0
            joint *= p if g > 0 else 1.0
            alt = ""
            if g == 1:
                p_k2 = p_at_least_one_hit(N, 1, k=2)
                alt = f"alt if k=2: {p_k2:.6f} (=2/27)"
            print(f"| {aid} | {g} | {g} | {p:.10f} | {alt} |")
        print(f"\nJoint product P(all anchors ≥1 hit | independent) ≈ **{joint:.6e}**")
        print(
            "Definition: for each anchor, draw k=|gold| distinct ids uniformly from N; "
            "success = at least one drawn id ∈ gold."
        )
        # reference numbers
        p_g2 = p_at_least_one_hit(N, 2, 2)
        p_g1 = p_at_least_one_hit(N, 1, 1)
        p_g1_k2 = p_at_least_one_hit(N, 1, 2)
        print(f"\n### Reference (N={N})")
        print(f"| quantity | exact | ≈ |")
        print(f"|----------|------:|--:|")
        print(f"| P(≥1\\|gold=2, k=2) | 1−C(25,2)/C(27,2)=51/351 | {p_g2:.6f} |")
        print(f"| P(≥1\\|gold=1, k=1) | 1/27 | {p_g1:.6f} |")
        print(f"| P(≥1\\|gold=1, k=2) | 2/27 | {p_g1_k2:.6f} |")
        print(
            f"| joint (5-anchor pattern k=\\|gold\\|: 2,1,2,1,2) | "
            f"(51/351)^3·(1/27)^2 | {p_g2**3 * p_g1**2:.6e} |"
        )
        print(
            f"| joint if singleton golds used k=2 (user cite ≈1.7e-5) | "
            f"(51/351)^3·(2/27)^2 | {p_g2**3 * p_g1_k2**2:.6e} |"
        )
        print(
            "\nNote: user-cited «draw 1: 0.074; joint ≈1.7e-5» matches "
            "**k=2 for gold=1**, not protocol k=|gold|. "
            "Prereg should use k=|gold| column unless otherwise declared."
        )
    else:
        print("\n## Anchors: (not provided; skip gold coverage & baselines)")
        print("Tip: pass --anchors anchors.json")

    print()
    if hard_fail:
        print("RESULT: HARD FAIL (exit 1)")
        return 1
    print("RESULT: OK (exit 0)")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate trunk (+ optional anchors) for 知音坐标系 demo")
    ap.add_argument("trunk", type=Path, help="path to trunk JSON")
    ap.add_argument("--anchors", type=Path, default=None, help="optional anchors JSON")
    args = ap.parse_args()
    trunk = load_json(args.trunk)
    anchors = load_json(args.anchors) if args.anchors else None
    code = check_trunk(trunk, anchors)
    sys.exit(code)


if __name__ == "__main__":
    main()
