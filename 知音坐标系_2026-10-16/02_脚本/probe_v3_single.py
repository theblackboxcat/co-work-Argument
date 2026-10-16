#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 草案单请求测时 + 试跑：复刻 run_v2.py main() 内 run_arm 逻辑（第 128 行），
绕过 run_arm 非模块级的问题。测 E05b 在 v3 trunk 下的 covered 臂耗时与预测。
"""
import json
import sys
import time
from pathlib import Path

PKG = Path("/workspace/交付_知音坐标系_完整脚本数据结论包_2026-10-15")
sys.path.insert(0, str(PKG / "02_脚本"))
from lib import providers  # noqa: E402

COVERED_SYSTEM = ("你是定位助手。你会拿到一棵坐标系：节点的上下位层级(parent)、层号(layer)、释义，"
                  "以及 parent / contrast / ban 三类边（ban 表示某节点被违规还原为另一节点时的标记地址）。"
                  "停靠常是一小块含 contrast/ban 的子图，不是一个孤立的点。\n"
                  '只输出单一 JSON 对象，不要任何其他文字：'
                  '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
                  '"needs_author_commit":true,"rationale_short":"<=2句>"}'
                  "\n硬性：nodes 恰好 1-2 个；id 必须来自给定集合；edges 的 (from,to,kind) 必须能在给定边表中原样找到，不得推测或编造边；不得自行造 id。")

OUT_SCHEMA_HARD = ""


def norm_edge(x):
    if not isinstance(x, dict):
        return None
    f, t, k = x.get("from"), x.get("to"), x.get("kind")
    return (frozenset((f, t)), k) if (f and t and k) else None


def views(trunk):
    nodes = trunk["nodes"]
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return j({"nodes": [{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                         "label": n.get("label"), "gloss": n.get("gloss")} for n in nodes],
              "edges": trunk.get("edges", [])})


def extract(t):
    if not t:
        return None
    s, e = t.find("{"), t.rfind("}")
    while s != -1 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except Exception:
            s = t.find("{", s + 1)
    return None


def run_arm(cfg, system, view, ids, allowed_edges, text, timeout):
    user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
            % (view, json.dumps(ids, ensure_ascii=False), text))
    rep = providers.chat(cfg, system, user, temperature=0.2, max_tokens=700,
                         timeout=timeout, thinking="disabled")
    p = extract(rep) or {}
    nodes = [x for x in (p.get("nodes") or []) if isinstance(x, str) and x in set(ids)]
    edges, off = [], []
    for x in p.get("edges") or []:
        ne = norm_edge(x)
        if ne is None:
            continue
        (edges if ne in allowed_edges else off).append(x)
    return {"nodes": nodes, "edges": edges, "offchart_edges": off,
            "rationale": p.get("rationale_short", ""), "raw": rep}


def score(rec, gold):
    gn = set(gold["nodes"])
    ge = {norm_edge(e) for e in gold.get("edges", []) if norm_edge(e)}
    pe = {norm_edge(e) for e in rec["edges"] if norm_edge(e)}
    hit = sorted(set(rec["nodes"]) & gn)
    union = set(rec["nodes"]) | gn
    return {
        "node_hit_any": bool(hit),
        "node_hits": hit,
        "exact_set": set(rec["nodes"]) == gn,
        "jaccard": (len(set(rec["nodes"]) & gn) / len(union)) if union else None,
        "edge_recall": (len(pe & ge) / len(ge)) if ge else None,
        "edge_evaluable": bool(ge),
        "offchart": len(rec["offchart_edges"]),
    }


def main():
    cfg = json.loads((PKG / "02_脚本" / "config.json").read_text(encoding="utf-8"))
    trunk = json.loads((PKG / "06_新包核验与续证" / "实验补报_2026-10-15" /
                        "trunk_v3_s14s20_sharpen_DRAFT.json").read_text(encoding="utf-8"))
    anchors = {a["id"]: a for a in json.loads(
        (PKG / "03_锚与主干" / "anchors_external_FROZEN_yunjiu_2026-10-15.json")
        .read_text(encoding="utf-8"))["anchors"]}

    view = views(trunk)
    ids = sorted({n["id"] for n in trunk["nodes"]})
    ae = {e for e in (norm_edge(x) for x in trunk["edges"]) if e}

    target = sys.argv[1] if len(sys.argv) > 1 else "E05b_alignment_confirmation"
    a = anchors[target]
    t0 = time.time()
    try:
        rec = run_arm(cfg, COVERED_SYSTEM, view, ids, ae, a["text"], 120)
        dt = time.time() - t0
        sc = score(rec, a["gold"])
        print("OK %.1fs" % dt)
        print("pred nodes:", rec["nodes"])
        print("gold nodes:", a["gold"]["nodes"])
        print("score:", json.dumps(sc, ensure_ascii=False))
        print("rationale:", rec["rationale"][:200])
    except Exception as e:
        print("FAIL %.1fs %s: %s" % (time.time() - t0, type(e).__name__, e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
