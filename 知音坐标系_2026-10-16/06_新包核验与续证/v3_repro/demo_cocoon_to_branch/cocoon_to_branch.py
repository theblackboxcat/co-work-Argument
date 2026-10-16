#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cocoon_to_branch.py — minimal offline feasibility: interest cocoon → branch draft nodes.

stdlib only. No network, no API keys, no sklearn.

Pipeline:
  1. Load cocoon texts
  2. Cue-family soft assignment (coverage surface markers) + bag-of-words Jaccard
     within-family merge → mid-size clusters
  3. Emit branch/stop drafts with form_cues
  4. Write branch_draft_v0.json + 结果_可行性.md

Theory locks:
  generate ≠ commit; S3 CLOSED; extraction → draft only;
  cocoons ≈ unintentional coordinate systems.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

HERE = Path(__file__).resolve().parent
COCOON_PATH = HERE / "sample_cocoon.json"
OUT_BRANCH = HERE / "branch_draft_v0.json"
OUT_RESULT = HERE / "结果_可行性.md"

STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "is", "are", "was",
    "were", "be", "as", "for", "with", "not", "this", "that", "it", "at", "by",
    "from", "into", "than", "vs", "again", "part", "same", "only", "too",
    "many", "like", "just", "不是", "而是", "就是", "这个", "那个", "一个",
    "没有", "可以", "已经", "自己", "他们", "我们", "什么", "如何", "以及",
}

PARENT_HINTS = {
    "form": "B01_form_technique",
    "motif": "B02_motif_cluster",
    "narr": "B03_narratology",
    "unknown": "T01_cn_modern_slice",
}

# Surface markers (coverage-first). Used both as family cues and form_cues pool.
FAMILY_CUES: Dict[str, List[str]] = {
    "form": [
        "碎片", "碎片化", "断裂", "空白", "短句", "fragmentary", "fragment",
        "broken", "paragraphs", "metafiction", "元叙述", "建构", "形式",
        "form", "craft", "技法", "结构母题", "回响", "化形", "变形",
        "transform", "allegorical", "structural", "指代", "压缩",
    ],
    "motif": [
        "平原", "虚无", "存在", "existential", "plain", "void", "horizon",
        "shelter", "选择", "地平线", "分形", "特解", "particular", "solution",
        "motif", "意象", "茧", "收敛", "处境",
    ],
    "narr": [
        "阐释", "情节", "interpretive", "plot-driven", "plot", "narratology",
        "叙述", "对照", "contrast", "genre", "停在", "阐释性", "情节性",
    ],
}


def tokenize(text: str) -> List[str]:
    text_l = text.lower()
    en = re.findall(r"[a-z][a-z\-']+", text_l)
    zh_multi = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    # also single CJK only if in cue lists
    cue_chars = set()
    for cues in FAMILY_CUES.values():
        for c in cues:
            if len(c) == 1 and "\u4e00" <= c <= "\u9fff":
                cue_chars.add(c)
    zh_uni = [ch for ch in re.findall(r"[\u4e00-\u9fff]", text) if ch in cue_chars]
    toks = []
    for t in en + zh_multi + zh_uni:
        if t in STOP:
            continue
        toks.append(t)
    return toks


def bow(text: str) -> Set[str]:
    return set(tokenize(text))


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def family_scores(text: str) -> Dict[str, int]:
    blob = text.lower()
    scores = {}
    for fam, cues in FAMILY_CUES.items():
        s = 0
        for c in cues:
            if c.lower() in blob:
                s += 1
        scores[fam] = s
    return scores


def assign_family(text: str) -> str:
    scores = family_scores(text)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "unknown"
    return best


def agglomerative_jaccard(
    indices: List[int], sets: List[Set[str]], threshold: float
) -> List[List[int]]:
    """Single-linkage on a subset of doc indices."""
    if not indices:
        return []
    clusters: List[List[int]] = [[i] for i in indices]

    def sim(c1: List[int], c2: List[int]) -> float:
        best = 0.0
        for i in c1:
            for j in c2:
                best = max(best, jaccard(sets[i], sets[j]))
        return best

    while len(clusters) > 1:
        best_pair = None
        best_sim = -1.0
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                s = sim(clusters[i], clusters[j])
                if s > best_sim:
                    best_sim = s
                    best_pair = (i, j)
        if best_pair is None or best_sim < threshold:
            break
        i, j = best_pair
        merged = clusters[i] + clusters[j]
        clusters.pop(j)
        clusters.pop(i)
        clusters.append(merged)
    return clusters


def cluster_docs(texts: List[str], sets: List[Set[str]]) -> List[Tuple[str, List[int]]]:
    """
    Strategy (minimal but coherent):
      A. Soft-assign each doc to a cue family (form / motif / narr).
      B. Each family with ≥2 docs → one branch-level cluster.
      C. If a family has ≥5 docs, try Jaccard sub-split (threshold 0.08)
         into ≤3 subclusters; keep parent family as branch + subs as stops
         OR if sub-split yields ≥2 non-trivial groups, emit those as separate
         drafts under same parent_hint.
      D. Guarantee ≥3 drafts by emitting family branches + one stop per
         largest family's top sub-theme if needed.
    """
    by_fam: Dict[str, List[int]] = defaultdict(list)
    for i, t in enumerate(texts):
        by_fam[assign_family(t)].append(i)

    # Drop unknown into largest family
    if "unknown" in by_fam and len(by_fam) > 1:
        unk = by_fam.pop("unknown")
        largest = max(by_fam, key=lambda k: len(by_fam[k]))
        by_fam[largest].extend(unk)

    refined: List[Tuple[str, List[int], str]] = []  # fam, members, role

    for fam, idxs in sorted(by_fam.items(), key=lambda x: -len(x[1])):
        if len(idxs) >= 5:
            subs = agglomerative_jaccard(idxs, sets, threshold=0.08)
            # keep only subs with size>=2; merge leftovers into largest sub
            big = [s for s in subs if len(s) >= 2]
            small = [s for s in subs if len(s) < 2]
            if big and small:
                big[0].extend([i for s in small for i in s])
            elif not big:
                big = [idxs]
            # Cap at 3 subs; merge extras into largest
            while len(big) > 3:
                big.sort(key=len)
                a = big.pop(0)
                big[0].extend(a)
            if len(big) == 1:
                refined.append((fam, big[0], "branch"))
            else:
                # family umbrella as branch + each sub as stop-oriented draft
                # For schema simplicity: emit each sub as its own draft node;
                # layer chosen by size later. Tag fam for parent_hint.
                for s in big:
                    role = "branch" if len(s) >= 4 else "stop"
                    refined.append((fam, s, role))
        else:
            role = "branch" if len(idxs) >= 3 else "stop"
            refined.append((fam, idxs, role))

    # Ensure ≥3 draft nodes
    if len(refined) < 3:
        # split largest family by secondary cue groups
        fam, members, _ = max(refined, key=lambda x: len(x[1]))
        refined = [r for r in refined if r[0] != fam or r[1] != members]
        # bipartition by presence of distinct cue subsets
        cue_groups = _secondary_split(fam, members, texts)
        for g in cue_groups:
            role = "branch" if len(g) >= 3 else "stop"
            refined.append((fam, g, role))

    # Still <3? emit one node per family + forced sub-splits
    if len(refined) < 3:
        forced = []
        for fam, idxs in by_fam.items():
            mid = max(1, len(idxs) // 2)
            forced.append((fam, idxs[:mid], "stop"))
            forced.append((fam, idxs[mid:], "stop"))
        refined = forced

    # Collapse pure duplicates / empty
    out: List[Tuple[str, List[int]]] = []
    for fam, members, _role in refined:
        members = sorted(set(members))
        if members:
            out.append((fam, members))

    # Prefer 3–6 nodes: if >6, merge smallest same-family
    while len(out) > 6:
        # find two smallest with same fam
        out.sort(key=lambda x: len(x[1]))
        merged = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                if out[i][0] == out[j][0]:
                    fam = out[i][0]
                    mem = sorted(set(out[i][1] + out[j][1]))
                    out.pop(j)
                    out.pop(i)
                    out.append((fam, mem))
                    merged = True
                    break
            if merged:
                break
        if not merged:
            # merge two smallest regardless
            a = out.pop(0)
            b = out.pop(0)
            out.append((a[0], sorted(set(a[1] + b[1]))))

    return out


def _secondary_split(fam: str, members: List[int], texts: List[str]) -> List[List[int]]:
    cues = FAMILY_CUES.get(fam, [])
    if len(cues) < 4 or len(members) < 2:
        mid = len(members) // 2 or 1
        return [members[:mid], members[mid:]] or [members]
    half = len(cues) // 2
    g1, g2 = set(c.lower() for c in cues[:half]), set(c.lower() for c in cues[half:])
    a, b = [], []
    for i in members:
        blob = texts[i].lower()
        s1 = sum(1 for c in g1 if c in blob)
        s2 = sum(1 for c in g2 if c in blob)
        (a if s1 >= s2 else b).append(i)
    groups = [g for g in (a, b) if g]
    return groups if len(groups) >= 2 else [members]


def top_cues(texts: List[str], fam: str, k: int = 8) -> List[str]:
    blob = "\n".join(texts).lower()
    found = []
    for c in FAMILY_CUES.get(fam, []):
        if c.lower() in blob and c not in found:
            found.append(c)
    # add frequent EN words / ZH multi from tokens
    cnt = Counter()
    for t in texts:
        for tok in tokenize(t):
            if tok in STOP or len(tok) < 2:
                continue
            if tok in {x.lower() for x in found}:
                continue
            cnt[tok] += 1
    for tok, _ in cnt.most_common(12):
        if tok not in found:
            found.append(tok)
        if len(found) >= k:
            break
    return found[:k]


def propose_label(family: str, cues: List[str], size: int, sub_idx: int) -> Tuple[str, str, str]:
    cue_show = "、".join(cues[:4]) if cues else "（弱线索）"
    suffix = f"·子簇{sub_idx}" if sub_idx > 1 else ""
    if family == "form":
        label = f"形式技法簇（茧内草稿）{suffix}"
        gloss = (
            f"从茧内 {size} 条抽出的形式表面簇：{cue_show}。"
            "覆盖规则：用可识别形式标记作地址线索，不作禁令。"
        )
        slug = "form_technique"
    elif family == "motif":
        label = f"存在母题簇（茧内草稿）{suffix}"
        gloss = (
            f"从茧内 {size} 条抽出的母题表面簇：{cue_show}。"
            "收敛于平原/虚无/特解等可复现意象；草稿待作者 commit。"
        )
        slug = "existential_motif"
    elif family == "narr":
        label = f"叙事对照簇（茧内草稿）{suffix}"
        gloss = (
            f"从茧内 {size} 条抽出的叙述对照表面簇：{cue_show}。"
            "阐释性↔情节性为对照轴，非体裁打分。"
        )
        slug = "narratology_contrast"
    else:
        label = f"未归族兴趣簇（茧内草稿）{suffix}"
        gloss = (
            f"从茧内 {size} 条抽出的弱归族簇：{cue_show}。需作者手标 parent/layer。"
        )
        slug = "misc_interest"
    return slug, label, gloss


def layer_for(size: int) -> str:
    return "branch" if size >= 3 else "stop"


def main() -> int:
    with open(COCOON_PATH, "r", encoding="utf-8") as f:
        cocoon = json.load(f)

    items = cocoon["items"]
    texts = [it["text"] for it in items]
    sets = [bow(t) for t in texts]

    clusters = cluster_docs(texts, sets)

    # Number sub-clusters per family for label suffix
    fam_counts: Dict[str, int] = defaultdict(int)
    nodes = []
    cluster_rows = []

    ordered = sorted(clusters, key=lambda x: (-len(x[1]), x[0]))
    for rank, (fam, members) in enumerate(ordered, start=1):
        fam_counts[fam] += 1
        sub_idx = fam_counts[fam]
        member_texts = [texts[i] for i in members]
        cues = top_cues(member_texts, fam, k=8)
        slug, label, gloss = propose_label(fam, cues, len(members), sub_idx)
        # if multiple subs in same fam, later ones lean stop
        layer = layer_for(len(members))
        if sub_idx > 1 and layer == "branch" and len(members) < 5:
            layer = "stop"
        prefix = "B" if layer == "branch" else "S"
        node_id = f"{prefix}D{rank:02d}_cocoon_{slug}"
        if sub_idx > 1:
            node_id = f"{node_id}_s{sub_idx}"
        parent_hint = PARENT_HINTS.get(fam, PARENT_HINTS["unknown"])
        node = {
            "id": node_id,
            "label": label,
            "gloss": gloss,
            "layer": layer,
            "parent_hint": parent_hint,
            "form_cues": cues,
            "status": "draft",
            "needs_author_commit": True,
            "source_cluster": {
                "size": len(members),
                "item_ids": [items[i]["id"] for i in members],
                "family_guess": fam,
            },
        }
        nodes.append(node)
        cluster_rows.append(
            {
                "rank": rank,
                "id": node_id,
                "size": len(members),
                "family": fam,
                "layer": layer,
                "cues": cues,
                "item_ids": [items[i]["id"] for i in members],
            }
        )

    draft = {
        "meta": {
            "id": "branch_draft_v0_from_cocoon",
            "title": "Cocoon → branch/stop draft (feasibility v0)",
            "compatible_with": (
                "trunk node spirit: id/label/gloss/layer + parent_hint; "
                "form_cues for coverage (v2 surface markers)"
            ),
            "theory_lock": (
                "generate≠commit; S3 CLOSED; extraction→draft addresses only; "
                "not proof of full cognitive tree; cocoons are unintentional coordinate systems"
            ),
            "method": (
                "cue-family soft assign + bag-of-words Jaccard within-family "
                "(stdlib only; no sklearn/network)"
            ),
            "source_cocoon": cocoon["meta"]["id"],
            "n_source_items": len(items),
            "n_draft_nodes": len(nodes),
            "needs_author_commit": True,
        },
        "nodes": nodes,
        "edges_suggested": [
            {
                "from": n["parent_hint"],
                "to": n["id"],
                "kind": "parent",
                "status": "draft_hint",
            }
            for n in nodes
        ],
    }

    with open(OUT_BRANCH, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
        f.write("\n")

    lines = []
    lines.append("# 结果 · 茧→枝 可行性（offline）\n\n")
    lines.append(f"- 源茧：`{cocoon['meta']['id']}`（{len(items)} 条）\n")
    lines.append(
        "- 方法：家族表面线索软分配 + 词袋 Jaccard 族内凝聚（纯 stdlib）\n"
    )
    lines.append(f"- 产出草稿节点数：**{len(nodes)}**\n")
    lines.append(
        "- **主张边界**：仅证明 *extraction → draft addresses* 可行；"
        "不是完整认知树；作者必须 commit；茧是无意收敛的坐标系。\n"
        "- generate≠commit；S3 CLOSED；不宣称理解已达成。\n"
    )
    lines.append("\n## 簇规模\n\n")
    lines.append("| # | draft id | size | family_guess | layer | form_cues (top) |\n")
    lines.append("|---|----------|------|--------------|-------|-----------------|\n")
    for row in cluster_rows:
        cues = ", ".join(row["cues"][:5])
        lines.append(
            f"| {row['rank']} | `{row['id']}` | {row['size']} | {row['family']} | "
            f"{row['layer']} | {cues} |\n"
        )

    lines.append("\n## 提议节点（摘要）\n\n")
    for n in nodes:
        lines.append(
            f"- **{n['id']}** [{n['layer']}] `{n['label']}`\n"
            f"  - parent_hint: `{n['parent_hint']}`\n"
            f"  - form_cues: {n['form_cues']}\n"
            f"  - items: {n['source_cluster']['item_ids']}\n"
            f"  - gloss: {n['gloss']}\n"
        )

    lines.append("\n## 人工检查清单（author must commit）\n\n")
    lines.append("- [ ] 每个 draft 的 `label`/`gloss` 是否可被第三人指认（共享可寻址）？\n")
    lines.append("- [ ] `form_cues` 是否为**表面可覆盖**标记（非否定禁令）？\n")
    lines.append(
        "- [ ] `parent_hint` 是否挂到正确 culture×era 枝？错则手改，勿自动写入 trunk。\n"
    )
    lines.append("- [ ] 过粗簇是否应拆 stop？过碎簇是否应并 branch？\n")
    lines.append("- [ ] 是否混入私人对话内容？（本样本应为合成公共讨论风）\n")
    lines.append(
        "- [ ] commit 前确认：generate≠commit；S3 CLOSED；不宣称理解已达成。\n"
    )
    lines.append("\n## 输出文件\n\n")
    lines.append(f"- `{OUT_BRANCH.name}`\n")
    lines.append(f"- `{OUT_RESULT.name}`（本页）\n")
    lines.append("\n---\n*offline run; no API keys; feasibility sample only.*\n")

    with open(OUT_RESULT, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"loaded {len(items)} cocoon items")
    print(f"clusters/draft nodes: {len(nodes)}")
    for n in nodes:
        print(
            f"  - {n['id']} layer={n['layer']} size={n['source_cluster']['size']} "
            f"fam={n['source_cluster']['family_guess']} cues={n['form_cues'][:4]}"
        )
    print(f"wrote {OUT_BRANCH}")
    print(f"wrote {OUT_RESULT}")
    return 0 if len(nodes) >= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
