#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知音坐标系 v1 · 小子图定位双臂（dots3）

实现 `协议_v1_共享可寻址坐标系_小子图定位.md`：
  §2 停靠 = 小子图；任务输出 {nodes, edges, needs_author_commit, rationale_short}
  §3 双臂同构：bare 只给 id 白名单+label；tree 给完整分层 DAG + 横切边
  §4 计分：node hit(≥1 / Jaccard) + edge hit(无向 + kind)；author confirm 单独留空
  §5 v1 只检验换枝 + 禁枝/contrast，不检验降层
  §7 干扰项 is_ban_sample 单列，不进主命中统计
  附录A 合并 trunk_v1_parent_edges.json 的 26 条 parent 边（加性）

硬纪律：generate≠commit（只提议，绝不写 trunk）；不宣称理解已达成；S3 CLOSED。
不代写锚正文、不填 gold —— 锚与 gold 只来自 anchors*.json。

用法:
  python3 localize_v1.py                                   # 用 anchors.json (demo, 仅 smoke)
  python3 localize_v1.py --anchors anchors_external.json   # 外源冻结锚（作者填）
  python3 localize_v1.py --repeat 3                        # 重复采样，报告稳定性
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_DIR))
try:
    from lib import providers
except Exception as e:  # pragma: no cover
    print("FATAL: cannot import providers from %s: %s" % (DEMO_DIR / "lib", e), file=sys.stderr)
    raise

BARE_SYSTEM = (
    "你是定位助手（对照臂·无边表）。\n"
    "你会拿到一个节点 id 白名单（附可读名）。你不知道节点之间的层级与禁戒关系。\n"
    "任务：为给定段落选择 1-2 个最贴切的停靠节点，并声明你判断成立的关系边。\n"
    "边的 kind 只能从 parent / contrast / ban 中选，但你看不到边表，只能依据语义判断。\n"
    "只输出单一 JSON 对象，不要任何其他文字：\n"
    '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
    '"needs_author_commit":true,"rationale_short":"<=2句>"}\n'
    "硬性：nodes 恰好 1-2 个（不得多于 2）；id 必须全部来自白名单；不得自行造 id。"
)

TREE_SYSTEM = (
    "你是定位助手（结构臂·含层级与横切边）。\n"
    "你会拿到一棵分层坐标系：节点的 parent 层级、layer、释义，以及 parent/contrast/ban 边表。\n"
    "任务：为给定段落选择 1-2 个最贴切的停靠节点，并声明 1-2 条你判断成立的关系边。\n"
    "停靠常是一小块含 contrast/ban（及 parent）的子图，不是一个孤立的点。\n"
    "只输出单一 JSON 对象，不要任何其他文字：\n"
    '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
    '"needs_author_commit":true,"rationale_short":"<=2句>"}\n'
    "硬性：nodes 恰好 1-2 个（不得多于 2）；id 必须全部来自给定坐标系；"
    "edges 的 (from,to,kind) 必须能在给定边表中原样找到，不得推测或编造边；"
    "不得自行造 id。generate≠commit：你只提议，不得写入主干。"
)


# ---------- io ----------
def load_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ---------- trunk ----------
def merge_parent_edges(trunk: dict, extra_path: Path | None) -> tuple[dict, int]:
    """附录 A：把 node.parent 导出的 parent 边加性并入 edges（不替换本体）。"""
    n0 = len(trunk.get("edges", []))
    if not extra_path or not Path(extra_path).is_file():
        return trunk, 0
    extra = load_json(Path(extra_path))
    e = extra.get("edges", extra) if isinstance(extra, dict) else extra
    have = {(x.get("from"), x.get("to"), x.get("kind")) for x in trunk.get("edges", [])}
    add = [x for x in e if (x.get("from"), x.get("to"), x.get("kind")) not in have]
    trunk = dict(trunk)
    trunk["edges"] = list(trunk.get("edges", [])) + add
    return trunk, len(add)


def trunk_ids(trunk: dict) -> list:
    return sorted({n["id"] for n in trunk.get("nodes", [])})


def bare_view(trunk: dict) -> str:
    """bare 臂视图：id + label only（无 parent / layer / gloss / edges）。"""
    lines = ["- %s | %s" % (n["id"], n.get("label", "")) for n in trunk.get("nodes", [])]
    return "\n".join(lines)


def tree_view(trunk: dict) -> str:
    """tree 臂视图：完整分层 DAG + 横切边。"""
    nodes = [{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
              "label": n.get("label"), "gloss": n.get("gloss")} for n in trunk.get("nodes", [])]
    edges = [{"from": e.get("from"), "to": e.get("to"), "kind": e.get("kind")}
             for e in trunk.get("edges", [])]
    return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, separators=(",", ":"))


# ---------- anchors ----------
def norm_gold(a: dict) -> dict:
    """兼容 external(gold.nodes/edges) 与 demo(gold_node_ids)。"""
    g = a.get("gold")
    if isinstance(g, dict):
        nodes = list(g.get("nodes") or [])
        edges = list(g.get("edges") or [])
    else:
        nodes = list(a.get("gold_node_ids") or [])
        edges = []
    return {"nodes": nodes, "edges": edges}


# ---------- parse & score ----------
def extract_json_obj(text: str):
    if not text:
        return None
    s = text.find("{")
    e = text.rfind("}")
    while s != -1 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except Exception:
            s = text.find("{", s + 1)
    return None


def norm_edge(x: dict):
    if not isinstance(x, dict):
        return None
    f, t, k = x.get("from"), x.get("to"), x.get("kind")
    if not (f and t and k):
        return None
    return (frozenset((f, t)), k)


def score_arm(parsed: dict | None, gold: dict, allowed: set, allowed_edges: set) -> dict:
    """协议 §2：nodes 与 edges 均须落在 trunk 白名单（及声明边集合）内。

    off-chart 边（端点越界、或 (pair,kind) 不在声明边表中）= 编造边，
    不计入 edge_recall，单列报告。
    """
    nodes = []
    edges = []
    offchart_edges = []
    dropped = []
    if isinstance(parsed, dict):
        for x in (parsed.get("nodes") or []):
            if isinstance(x, str):
                (nodes if x in allowed else dropped).append(x)
        for x in (parsed.get("edges") or []):
            ne = norm_edge(x)
            if ne is None:
                continue
            if not set(ne[0]) <= allowed:
                dropped.append(x)
                continue
            if ne in allowed_edges:
                edges.append(x)
            else:
                offchart_edges.append(x)
    gn = set(gold["nodes"])
    ge = {norm_edge(x) for x in gold["edges"] if norm_edge(x)}
    pe = {norm_edge(x) for x in edges if norm_edge(x)}
    hits = sorted(set(nodes) & gn)
    union = set(nodes) | gn
    jac = (len(set(nodes) & gn) / len(union)) if union else None
    edge_hits = sorted(pe & ge, key=lambda z: (sorted(z[0]), z[1]))
    edge_recall = (len(pe & ge) / len(ge)) if ge else None  # None = 不可评（gold 无边）
    return {
        "nodes": nodes,
        "edges": edges,
        "offchart_edges": offchart_edges,
        "dropped_offtrunk": dropped,
        "on_trunk": not dropped,
        "node_hit_any": bool(hits),
        "node_hits": hits,
        "jaccard": jac,
        "edge_hits": [{"pair": sorted(x[0]), "kind": x[1]} for x in edge_hits],
        "edge_recall": edge_recall,
        "edge_evaluable": bool(ge),
        "rationale_short": (parsed or {}).get("rationale_short") or (parsed or {}).get("rationale") or "",
    }


# ---------- run ----------
def call_arm(cfg, system: str, view: str, ids: list, text: str, timeout: int):
    user = (
        "白名单/坐标系：\n%s\n\n"
        "允许的 id 集合：%s\n\n"
        "段落（定位锚，非坐标系内容源）：\n%s\n\n"
        "请输出规定 JSON。"
    ) % (view, json.dumps(ids, ensure_ascii=False), text)
    reply = providers.chat(cfg, system, user, temperature=0.2, max_tokens=768,
                           timeout=timeout, thinking="disabled")
    return reply, extract_json_obj(reply)


def main():
    ap = argparse.ArgumentParser(description="知音坐标系 v1 小子图定位双臂")
    ap.add_argument("--config", default=str(DEMO_DIR / "config.json"))
    ap.add_argument("--trunk", default=str(DEMO_DIR / "trunk_v0.json"))
    ap.add_argument("--parent-edges", default=str(DEMO_DIR / "trunk_v1_parent_edges.json"))
    ap.add_argument("--no-merge-parent", action="store_true")
    ap.add_argument("--anchors", default=str(DEMO_DIR / "anchors.json"))
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--probe-timeout", type=int, default=40)
    ap.add_argument("--repeat", type=int, default=1, help="每锚每臂重复采样次数")
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    trunk = load_json(Path(args.trunk))
    n_add = 0
    if not args.no_merge_parent:
        trunk, n_add = merge_parent_edges(trunk, Path(args.parent_edges))
    ids = trunk_ids(trunk)
    allowed = set(ids)
    allowed_edges = {e for e in (norm_edge(x) for x in trunk.get("edges", [])) if e}
    anchors_doc = load_json(Path(args.anchors))
    anchors = anchors_doc.get("anchors", [])

    print("=== 知音坐标系 v1 · 小子图定位 ===")
    print("trunk: %s  nodes=%d  edges=%d (parent 边并入 %d 条)" %
          (Path(args.trunk).name, len(trunk["nodes"]), len(trunk.get("edges", [])), n_add))
    print("anchors: %s  (%d 条)" % (Path(args.anchors).name, len(anchors)))
    print("provider: %s  model: %s  masked_key: %s" %
          (cfg.get("provider"), cfg.get("model"), providers.mask_key(cfg.get("api_key", ""))))

    ok, detail = providers.probe(cfg, timeout=args.probe_timeout)
    print("probe_ok=%s  %s" % (ok, detail))
    if not ok:
        print("ABORT: probe failed")
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_path = DEMO_DIR / "runs" / ("run_v1_%s.jsonl" % ts)
    run_path.parent.mkdir(exist_ok=True)

    def w(obj):
        with run_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    w({"type": "meta", "timestamp": ts, "protocol": "v1",
       "provider": cfg.get("provider"), "model": cfg.get("model"),
       "masked_key": providers.mask_key(cfg.get("api_key", "")),
       "probe_ok": ok, "trunk": Path(args.trunk).name,
       "parent_edges_merged": n_add, "anchors": Path(args.anchors).name,
       "repeat": args.repeat,
       "theory_lock": "generate!=commit; shared addressability; elicitable!=内含; S3 CLOSED"})

    bview = bare_view(trunk)
    tview = tree_view(trunk)
    records = []
    for a in anchors:
        gold = norm_gold(a)
        text = a.get("text", "")
        rec = {"anchor_id": a.get("id"), "is_ban_sample": bool(a.get("is_ban_sample")),
               "gold": gold, "reps": []}
        for r in range(args.repeat):
            b_raw, b_parsed = call_arm(cfg, BARE_SYSTEM, bview, ids, text, args.timeout)
            t_raw, t_parsed = call_arm(cfg, TREE_SYSTEM, tview, ids, text, args.timeout)
            b = score_arm(b_parsed, gold, allowed, allowed_edges)
            t = score_arm(t_parsed, gold, allowed, allowed_edges)
            b["raw"] = b_raw
            t["raw"] = t_raw
            rec["reps"].append({"rep": r, "bare": b, "tree": t})
            print("[%s rep%d] bare nodes=%s hit=%s edge_recall=%s | tree nodes=%s hit=%s edge_recall=%s%s"
                  % (a.get("id"), r, b["nodes"], b["node_hit_any"],
                     "N/A" if b["edge_recall"] is None else round(b["edge_recall"], 2),
                     t["nodes"], t["node_hit_any"],
                     "N/A" if t["edge_recall"] is None else round(t["edge_recall"], 2),
                     "  <ban-sample>" if rec["is_ban_sample"] else ""))
        records.append(rec)
        w(rec)

    # ---- 汇总 ----
    main_recs = [r for r in records if not r["is_ban_sample"]]
    ban_recs = [r for r in records if r["is_ban_sample"]]

    def agg(rs, arm, key):
        vals = [x[arm][key] for r in rs for x in r["reps"] if x[arm][key] is not None]
        return (sum(vals) / len(vals)) if vals else None

    def anyhit(rs, arm):
        tot = sum(len(r["reps"]) for r in rs)
        hit = sum(1 for r in rs for x in r["reps"] if x[arm]["node_hit_any"])
        return hit, tot

    lines = ["# v1 run summary", "",
             "- timestamp: %s" % ts,
             "- protocol: v1 (shared addressability / 小子图定位)",
             "- provider/model: %s / %s" % (cfg.get("provider"), cfg.get("model")),
             "- trunk: %s (parent edges merged: %d)" % (Path(args.trunk).name, n_add),
             "- anchors: %s  (main=%d, ban/interference=%d)" %
             (Path(args.anchors).name, len(main_recs), len(ban_recs)),
             "- repeat per arm: %d" % args.repeat,
             "- 声明边集合大小: %d" % len(allowed_edges),
             "- theory: generate≠commit; elicitable≠内含; S3 CLOSED; v1 只检验换枝+禁枝/contrast，**不检验降层**",
             ""]
    lines += ["## 主锚（node hit ≥1）", "", "| arm | hit/total | mean Jaccard | mean edge recall | mean 提议节点数 | 编造边总数 |", "|---|---:|---:|---:|---:|---:|"]
    for arm in ("bare", "tree"):
        h, t_ = anyhit(main_recs, arm)
        j = agg(main_recs, arm, "jaccard")
        er = agg(main_recs, arm, "edge_recall")
        nprop = [len(x[arm]["nodes"]) for r in main_recs for x in r["reps"]]
        offc = sum(len(x[arm]["offchart_edges"]) for r in main_recs for x in r["reps"])
        lines.append("| %s | %d/%d | %s | %s | %.2f | %d |" % (
            arm, h, t_, "—" if j is None else "%.3f" % j,
            "—" if er is None else "%.3f" % er,
            (sum(nprop) / len(nprop)) if nprop else 0, offc))
    lines += ["", "## edge 可评性（协议 §6）", ""]
    ne = sum(1 for r in main_recs if r["gold"]["edges"])
    lines.append("- 主锚中有 gold.edges 的：%d/%d；其余 edge_recall 记为 N/A（不可评，非 0）。" % (ne, len(main_recs)))
    if ban_recs:
        lines += ["", "## 干扰项（is_ban_sample）", "",
                  "| anchor | bare 命中 | tree 命中 | 期望 |", "|---|---|---|---|"]
        for r in ban_recs:
            b = any(r["reps"][i]["bare"]["node_hit_any"] for i in range(len(r["reps"])))
            t = any(r["reps"][i]["tree"]["node_hit_any"] for i in range(len(r["reps"])))
            lines.append("| %s | %s | %s | 不命中/作者拒绝 |" % (r["anchor_id"], b, t))
    lines += ["", "## 纪律", "",
              "- generate≠commit：本轮只记录提议，**未写入任何 trunk**。",
              "- 不宣称理解已达成；不把本轮当作 VERIFY 主表证据。",
              "- author confirm 未采集（需作者逐条判读后补）。", ""]
    for r in records:
        g = r["gold"]
        lines += ["### %s%s" % (r["anchor_id"], "  [干扰项]" if r["is_ban_sample"] else ""),
                  "- gold.nodes: %s" % ", ".join(g["nodes"]),
                  "- gold.edges: %s" % ("—" if not g["edges"] else "; ".join(
                      "%s—%s—%s" % (e.get("from"), e.get("kind"), e.get("to")) for e in g["edges"]))]
        for x in r["reps"]:
            for arm in ("bare", "tree"):
                s = x[arm]
                lines.append("- rep%d %s: nodes=%s | edges=%s | 边命中=%s | %s" % (
                    x["rep"], arm, s["nodes"],
                    [("%s—%s—%s" % (e.get("from"), e.get("kind"), e.get("to"))) for e in s["edges"]],
                    [("%s—%s" % ("—".join(e["pair"]), e["kind"])) for e in s["edge_hits"]],
                    (s["rationale_short"] or "")[:120]))
        lines.append("")

    sum_path = DEMO_DIR / "runs" / ("summary_v1_%s.md" % ts)
    sum_path.write_text("\n".join(lines), encoding="utf-8")
    print("\nwrote: %s\nwrote: %s" % (run_path, sum_path))
    print("\n".join(lines[:26]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
