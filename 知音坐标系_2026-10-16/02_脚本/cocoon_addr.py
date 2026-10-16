#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cocoon_addr.py — 茧→枝草稿地址的覆盖效力测试（v2 协议的迷你复刻）

问题（证据链 E6 缺的一环）：demo_cocoon_to_branch 证明了 extraction→draft 可行，
但**没测这些草稿地址在定位协议里是否真的当地址用**。本实验补上这一环。

臂（输出同构 {nodes, edges, needs_author_commit, rationale_short}）：
  bare               : 只给 3 个草稿节点的 id + label（无 gloss、无层级、无边）
  covered            : 完整草稿地址（id + parent + layer + label + gloss）+ 3 条 parent 提示边
  covered_minus_cues : 同上，但 gloss 去掉枚举的表面线索（gloss_nocues，S27 式消融）

锚：12 条 held-out 合成茧风文本（9 直述 + 3 跨族），gold 按构造意图标；
    跨族条目的 stance 由独立判定臂仲裁（A=形式/B=母题/C=叙事/D=复读），
    与 gold 冲突则如实记录、不计入主效应（E12 先例）。

协议常量与 run_v2.py 一致：temperature=0.2, max_tokens=700, thinking=disabled,
nodes 恰好 1-2 个，边必须在给定边表中原样找到。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402

ROOT = DEMO.parent
OUT_SCHEMA = (
    '只输出单一 JSON 对象，不要任何其他文字：'
    '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
    '"needs_author_commit":true,"rationale_short":"<=2句>"}'
)
HARD = "硬性：nodes 恰好 1-2 个；id 必须来自给定集合；edges 的 (from,to,kind) 必须能在给定边表中原样找到，不得推测或编造边；不得自行造 id。"

BARE_SYSTEM = ("你是定位助手。你会拿到一份节点 id 与名字的清单，不知道它们之间的任何关系。"
               "请为段落选择最贴切的 1-2 个停靠节点，并声明你判断成立的关系边。\n"
               + OUT_SCHEMA + "\n" + HARD)
COVERED_SYSTEM = ("你是定位助手。你会拿到一棵坐标系：节点的上下位层级(parent)、层号(layer)、释义，"
                  "以及 parent 边（草稿提示边）。停靠常是一小块子图，不是一个孤立的点。\n"
                  + OUT_SCHEMA + "\n" + HARD)

JUDGE_SYSTEM = (
    "你是立场判定器。下面这段文学讨论文本，主要在哪个层面谈？只判立场，不做定位。\n"
    "A 形式技法：只在怎么写——句式、视角、结构、元叙述等文本制作层面谈。\n"
    "B 存在母题：谈处境本身——开阔/无根基/选择/虚无/特解等，不谈怎么写。\n"
    "C 叙事对照：谈阐释性↔情节性这类叙述方式对照轴。\n"
    "D 概念复读：只是复述概念标签/框架名，没有真正展开。\n"
    '只输出单一 JSON：{"choice":"A|B|C|D","why":"<=1句>"}'
)
CHOICE_TO_NODE = {"A": "BD01_cocoon_form_technique",
                  "B": "BD02_cocoon_existential_motif",
                  "C": "SD03_cocoon_narratology_contrast",
                  "D": None}


def norm_edge(x):
    if not isinstance(x, dict):
        return None
    f, t, k = x.get("from"), x.get("to"), x.get("kind")
    return (frozenset((f, t)), k) if (f and t and k) else None


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEMO / "config.json"))
    ap.add_argument("--trunk", default=str(ROOT / "06_新包核验与续证" / "cocoon_draft_addresses.json"))
    ap.add_argument("--anchors", default=str(ROOT / "06_新包核验与续证" / "anchors_cocoon_heldout.json"))
    ap.add_argument("--arms", default="bare,covered,covered_minus_cues")
    ap.add_argument("--judge", action="store_true", default=True)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--temp", type=float, default=0.2, help="定位臂温度（判定臂固定 0.1）")
    ap.add_argument("--patch", default="", help="gloss 补全 patch 文件（JSON: {node_id: new_gloss}），只改 covered 臂")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    cfg = load(args.config)
    trunk = load(args.trunk)
    anchors = load(args.anchors)["anchors"]
    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s | draft nodes=%d edges=%d | anchors=%d"
          % (ok, detail, len(trunk["nodes"]), len(trunk["edges"]), len(anchors)))
    if not ok:
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "04_原始数据_runs" / ("cocoon_addr_%s.jsonl" % ts)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "meta", "ts": ts,
                            "trunk": Path(args.trunk).name,
                            "anchors": Path(args.anchors).name,
                            "repeat": args.repeat, "arms": args.arms,
                            "judge": args.judge, "temp": args.temp,
                            "patch": Path(args.patch).name if args.patch else None,
                            "protocol": "v2-compatible: nodes 1-2"},
                           ensure_ascii=False) + "\n")

    # gloss 补全 patch（只改 covered 臂的 gloss；bare 无 gloss，minus_cues 用 gloss_nocues）
    gloss_patch = {}
    if args.patch:
        gloss_patch = load(args.patch)

    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    ids = sorted({n["id"] for n in trunk["nodes"]})
    ae = {e for e in (norm_edge(x) for x in trunk["edges"]) if e}

    V = {
        "bare": j([{"id": n["id"], "label": n["label"]} for n in trunk["nodes"]]),
        "covered": j({"nodes": [{"id": n["id"], "parent": n.get("parent"),
                                 "layer": n.get("layer"), "label": n["label"],
                                 "gloss": gloss_patch.get(n["id"], n["gloss"])} for n in trunk["nodes"]],
                      "edges": trunk["edges"]}),
        "covered_minus_cues": j({"nodes": [{"id": n["id"], "parent": n.get("parent"),
                                            "layer": n.get("layer"), "label": n["label"],
                                            "gloss": n["gloss_nocues"]} for n in trunk["nodes"]],
                                 "edges": trunk["edges"]}),
    }

    def run_arm(system, view, text, timeout):
        user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                % (view, j(ids), text))
        rep = providers.chat(cfg, system, user, temperature=args.temp, max_tokens=700,
                             timeout=timeout, thinking="disabled")
        p = extract(rep) or {}
        nodes = [x for x in (p.get("nodes") or []) if isinstance(x, str) and x in set(ids)]
        edges, off = [], []
        for x in p.get("edges") or []:
            ne = norm_edge(x)
            if ne is None:
                continue
            (edges if ne in ae else off).append(x)
        return {"nodes": nodes, "edges": edges, "offchart_edges": off,
                "rationale": p.get("rationale_short", ""), "raw": rep}

    def score(rec, gold):
        gn = set(gold["nodes"])
        pe = {norm_edge(e) for e in rec["edges"] if norm_edge(e)}
        hit = sorted(set(rec["nodes"]) & gn)
        union = set(rec["nodes"]) | gn
        return {"node_hit_any": bool(hit), "node_hits": hit,
                "exact_set": set(rec["nodes"]) == gn,
                "jaccard": (len(set(rec["nodes"]) & gn) / len(union)) if union else None,
                "offchart": len(rec["offchart_edges"])}

    arms = [a.strip() for a in args.arms.split(",")]
    rows = []
    for a in anchors:
        gold = a["gold"]
        row = {"anchor_id": a["id"], "kind": a.get("kind"), "family": a.get("family"),
               "gold": gold, "arms": {}}
        for arm in arms:
            reps = []
            for r in range(args.repeat):
                rec = run_arm(COVERED_SYSTEM if arm != "bare" else BARE_SYSTEM,
                              V[arm], a["text"], args.timeout)
                reps.append({"rec": rec, "score": score(rec, gold)})
            row["arms"][arm] = reps
            print("[%s][%-18s] %-38s hit=%s exact=%s off=%d" % (
                a["id"], arm, ",".join(reps[0]["rec"]["nodes"]) or "(空)",
                reps[0]["score"]["node_hit_any"], reps[0]["score"]["exact_set"],
                reps[0]["score"]["offchart"]))
        if args.judge and a.get("kind") == "cross":
            jr = providers.chat(cfg, JUDGE_SYSTEM, "段落：\n%s\n\n请判定立场。" % a["text"],
                                temperature=0.1, max_tokens=300, timeout=args.timeout,
                                thinking="disabled")
            jd = extract(jr) or {}
            choice = jd.get("choice")
            row["judge"] = {"choice": choice,
                            "choice_node": CHOICE_TO_NODE.get(choice),
                            "agrees_gold": CHOICE_TO_NODE.get(choice) in set(gold["nodes"]),
                            "why": jd.get("why", ""), "raw": jr}
            print("      judge: choice=%s -> %s (agrees_gold=%s) %s" % (
                choice, row["judge"]["choice_node"], row["judge"]["agrees_gold"],
                row["judge"]["why"][:60]))
        rows.append(row)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def agg(sel, arm, key):
        vals = [x["score"][key] for r in rows if sel(r) for x in r["arms"].get(arm, [])
                if x["score"][key] is not None]
        return (sum(vals) / len(vals)) if vals else None

    def rate(sel, arm):
        tot = sum(len(r["arms"].get(arm, [])) for r in rows if sel(r))
        hit = sum(1 for r in rows if sel(r) for x in r["arms"].get(arm, []) if x["score"]["node_hit_any"])
        ex = sum(1 for r in rows if sel(r) for x in r["arms"].get(arm, []) if x["score"]["exact_set"])
        return hit, ex, tot

    is_straight = lambda r: r.get("kind") == "straight"
    is_cross = lambda r: r.get("kind") == "cross"

    print("\n" + "=" * 78)
    print("直述锚（9 条，应停对应草稿节点）   hit/total   exact/total   meanJaccard")
    for arm in arms:
        h, e, t = rate(is_straight, arm)
        if t:
            jv = agg(is_straight, arm, "jaccard")
            print("  %-20s %5d/%-5d %5d/%-5d %s" % (
                arm, h, t, e, t, "%.3f" % jv if jv is not None else "—"))
    print("\n跨族锚（3 条，stance 仲裁）         hit/total   exact/total   meanJaccard")
    for arm in arms:
        h, e, t = rate(is_cross, arm)
        if t:
            jv = agg(is_cross, arm, "jaccard")
            print("  %-20s %5d/%-5d %5d/%-5d %s" % (
                arm, h, t, e, t, "%.3f" % jv if jv is not None else "—"))
    print("\n判定臂（跨族 stance）")
    for r in rows:
        if is_cross(r) and "judge" in r:
            print("  %-26s gold=%s judge=%s agrees=%s" % (
                r["anchor_id"], r["gold"]["nodes"][0].split("_")[1],
                r["judge"]["choice"], r["judge"]["agrees_gold"]))
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
