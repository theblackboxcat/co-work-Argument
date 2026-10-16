#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消融实验 · 分离「白名单效应」与「拓扑效应」

核心问题（决定树理论能否落地）：
  给模型一个坐标系，输出的变化到底来自「闭集 id 约束」还是「拓扑信息（层级 / contrast / ban）」？
  若只来自白名单，则树作为拓扑不成立——它只是一个受控词表。

五臂（同一批锚，输出同构）：
  A_whitelist  : id + label（无 parent / layer / gloss / 无边）
  B_plus_parent: + parent 层级（nodes 含 parent；edges 只含 parent 边）
  C_plus_cross : + contrast / ban（nodes 不含 parent；edges 只含 contrast/ban）
  D_full       : 全部（nodes 含 parent/layer/gloss；edges = parent ∪ contrast ∪ ban）
  E_bare       : 完全裸（不给任何坐标系，自由命名）—— 只作对照，输出不同构，单独看

不依赖 gold：判别依据是「同一锚在臂间输出是否改变」以及「反事实对是否被区分」。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402

OUT_SCHEMA = (
    '只输出单一 JSON 对象，不要任何其他文字：'
    '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
    '"needs_author_commit":true,"rationale_short":"<=2句>"}'
)

ARM_SYSTEM = {
    "A_whitelist": "你是定位助手。你会拿到一份节点 id 与名字的清单，不知道它们之间的任何关系。"
                   "请为段落选择最贴切的 1-2 个停靠节点，并声明你判断成立的关系边。\n" + OUT_SCHEMA +
                   "\n硬性：nodes 恰好 1-2 个；id 必须来自清单；不得自行造 id。",
    "B_plus_parent": "你是定位助手。你会拿到节点 id、名字与它们的上下位层级（parent），以及层级边。"
                     "不知道对照与禁戒关系。请为段落选择最贴切的 1-2 个停靠节点，并声明关系边。\n" + OUT_SCHEMA +
                     "\n硬性：nodes 恰好 1-2 个；edges 的 (from,to,kind) 必须能在给定边表中原样找到；不得自行造 id 或编造边。",
    "C_plus_cross": "你是定位助手。你会拿到节点 id、名字与它们之间的对照(contrast)与禁戒(ban)边表。"
                    "不知道上下位层级。请为段落选择最贴切的 1-2 个停靠节点，并声明关系边。\n" + OUT_SCHEMA +
                    "\n硬性：nodes 恰好 1-2 个；edges 的 (from,to,kind) 必须能在给定边表中原样找到；不得自行造 id 或编造边。",
    "D_full": "你是定位助手。你会拿到一棵完整坐标系：节点的层级(parent)、层号(layer)、释义，"
              "以及 parent / contrast / ban 三类边（ban 表示禁止把某节点还原成另一个）。"
              "停靠常是一小块含 contrast/ban 的子图，不是一个孤立的点。\n" + OUT_SCHEMA +
              "\n硬性：nodes 恰好 1-2 个；edges 的 (from,to,kind) 必须能在给定边表中原样找到；不得自行造 id 或编造边。",
}

BARE_SYSTEM = (
    "你是定位助手（无坐标系）。没有清单，没有层级，没有边表。"
    "任务：为给定段落命名 1-2 个概念停靠点（中文短名即可），并说明你判断这两个停靠点之间是什么关系"
    "（上下位 / 对照 / 禁戒），以及理由。\n"
    '只输出单一 JSON：{"stops":["<中文名>"],"relations":[{"a":"<名>","b":"<名>","kind":"parent|contrast|ban"}],'
    '"rationale_short":"<=2句>"}'
)


def norm_edge(x):
    if not isinstance(x, dict):
        return None
    f, t, k = x.get("from"), x.get("to"), x.get("kind")
    return (frozenset((f, t)), k) if (f and t and k) else None


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def build_views(trunk):
    nodes = trunk["nodes"]
    edges = trunk.get("edges", [])
    P = [e for e in edges if e.get("kind") == "parent"]
    X = [e for e in edges if e.get("kind") in ("contrast", "ban")]
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return {
        "A_whitelist": j([{"id": n["id"], "label": n.get("label", "")} for n in nodes]),
        "B_plus_parent": j({"nodes": [{"id": n["id"], "label": n.get("label", ""), "parent": n.get("parent")}
                                      for n in nodes], "edges": P}),
        "C_plus_cross": j({"nodes": [{"id": n["id"], "label": n.get("label", "")} for n in nodes], "edges": X}),
        "D_full": j({"nodes": [{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                                "label": n.get("label"), "gloss": n.get("gloss")} for n in nodes],
                     "edges": edges}),
    }


def extract_json_obj(t):
    if not t:
        return None
    s, e = t.find("{"), t.rfind("}")
    while s != -1 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except Exception:
            s = t.find("{", s + 1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEMO / "config.json"))
    ap.add_argument("--trunk", default=str(DEMO / "trunk_v0.json"))
    ap.add_argument("--parent-edges", default=str(DEMO / "trunk_v1_parent_edges.json"))
    ap.add_argument("--anchors", default=str(DEMO / "anchors_lit_v1.json"))
    ap.add_argument("--arms", default="A_whitelist,B_plus_parent,C_plus_cross,D_full")
    ap.add_argument("--with-bare", action="store_true")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    cfg = load_json(args.config)
    trunk = load_json(args.trunk)
    extra = load_json(args.parent_edges)
    ex = extra.get("edges", extra) if isinstance(extra, dict) else extra
    have = {(e.get("from"), e.get("to"), e.get("kind")) for e in trunk.get("edges", [])}
    trunk = dict(trunk)
    trunk["edges"] = list(trunk.get("edges", [])) + [e for e in ex
                                                     if (e.get("from"), e.get("to"), e.get("kind")) not in have]
    ids = sorted({n["id"] for n in trunk["nodes"]})
    allowed = set(ids)
    allowed_edges = {e for e in (norm_edge(x) for x in trunk["edges"]) if e}
    views = build_views(trunk)
    anchors = load_json(args.anchors)["anchors"]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if args.with_bare:
        arms.append("E_bare")

    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s | trunk edges=%d | anchors=%d | arms=%s"
          % (ok, detail, len(trunk["edges"]), len(anchors), ",".join(arms)))
    if not ok:
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("ablation_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)

    def call(system, view, text):
        user = "坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。" % (
            view, json.dumps(ids, ensure_ascii=False), text)
        r = providers.chat(cfg, system, user, temperature=0.2, max_tokens=700,
                           timeout=args.timeout, thinking="disabled")
        return r, extract_json_obj(r)

    results = {}
    for a in anchors:
        results[a["id"]] = {}
        for arm in arms:
            if arm == "E_bare":
                user = "段落：\n%s\n\n请命名 1-2 个概念停靠点并说明关系。" % a["text"]
                r = providers.chat(cfg, BARE_SYSTEM, user, temperature=0.2,
                                   max_tokens=700, timeout=args.timeout, thinking="disabled")
                parsed = extract_json_obj(r)
                rec = {"arm": arm, "raw": r, "parsed": parsed, "is_ban_sample": a.get("is_ban_sample", False)}
            else:
                r, parsed = call(ARM_SYSTEM[arm], views[arm], a["text"])
                nodes, edges, off = [], [], []
                if isinstance(parsed, dict):
                    for x in parsed.get("nodes") or []:
                        if isinstance(x, str) and x in allowed:
                            nodes.append(x)
                    for x in parsed.get("edges") or []:
                        ne = norm_edge(x)
                        if ne is None:
                            continue
                        (edges if ne in allowed_edges else off).append(x)
                rec = {"arm": arm, "raw": r, "nodes": nodes, "edges": edges,
                       "offchart_edges": off, "rationale": (parsed or {}).get("rationale_short", ""),
                       "is_ban_sample": a.get("is_ban_sample", False)}
            results[a["id"]][arm] = rec
            if arm == "E_bare":
                print("[%s][%s] stops=%s" % (a["id"], arm,
                                             (rec["parsed"] or {}).get("stops") if isinstance(rec["parsed"], dict) else "?"))
            else:
                print("[%s][%s] nodes=%s edges=%s off=%d" % (
                    a["id"], arm, rec["nodes"],
                    ["%s—%s—%s" % (e.get("from"), e.get("kind"), e.get("to")) for e in rec["edges"]],
                    len(rec["offchart_edges"])))
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"anchor_id": a["id"], "text": a["text"],
                                "construct_note": a.get("construct_note", ""),
                                "is_ban_sample": a.get("is_ban_sample", False),
                                "arms": results[a["id"]]}, ensure_ascii=False) + "\n")
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
