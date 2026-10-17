#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 主实验：覆盖度能否把停靠钉到可共用地址上

臂（输出同构 {nodes, edges, needs_author_commit, rationale_short}）：
  bare              : 只给 id 白名单 + label（无 parent 层级、无 contrast/ban 边）
  covered           : 完整地址集（parent 显式进表 + contrast/ban 挂载 + 5 个正向替代节点）
  covered_minus_alt : 去掉 5 个正向替代节点（**覆盖消融，主效应应在这里**）

独立判定臂 judge_v2：只判条件成立与否，不兼停靠（不共享定位输出）

评分：node hit（≥1 / 集合相等）+ edge recall + 编造边数；作者确认暂由代理判读（= gold 命中）
      代理判读必须经作者复核，不得直接作为作者确认率。
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
                  "以及 parent / contrast / ban 三类边（ban 表示某节点被违规还原为另一节点时的标记地址）。"
                  "停靠常是一小块含 contrast/ban 的子图，不是一个孤立的点。\n"
                  "【dual-stop 同址摄取加压 · 本杀臂】若段落出现互认／共停摄取语（如「是的」「我刚就想说」、确认对方所指、沿用同一节点词互相呼应），优先在 nodes 中**同时**给出 S14_shared_stop（共享停靠／过程）与 S20_zhiyin_align（知音对齐／结果）——互认应被共址为过程+结果，勿拆到不同轮次只出其一。若只选其中一个，须在 rationale_short 写明为何不能双停；默认偏置双停共现。无互认摄取语时按原坐标常规定位，勿强行双停。\n"
                  + OUT_SCHEMA + "\n" + HARD)

JUDGE_SYSTEM = (
    "你是条件判定器。只判断下列条件在给定段落中是否成立，不做定位、不推荐节点。\n"
    "J1：段落只是描写自然景物（平原、风、草地、地平线），没有把开阔/无根基当作处境来谈。\n"
    "J2：段落把变形或困境解释为心理创伤、压抑、躯体化症状，并给出疗程。\n"
    "J3：段落只是陈述日常惯例，没有把它升格为荒诞。\n"
    "J4：段落只在写法、句式、视角、节奏层面谈文本。\n"
    "J5：段落只是复读某个概念标签/框架，并未真正对准处境结构。\n"
    '只输出单一 JSON：{"J1":false,"J2":false,"J3":false,"J4":false,"J5":false,"why":"<=1句>"}'
)

ALT_IDS = {"S23_literal_scenery", "S24_psychological_explanation", "S25_mundane_routine",
           "S26_craft_discussion", "S27_false_alignment"}


def norm_edge(x):
    if not isinstance(x, dict):
        return None
    f, t, k = x.get("from"), x.get("to"), x.get("kind")
    return (frozenset((f, t)), k) if (f and t and k) else None


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def views(trunk):
    nodes = trunk["nodes"]
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return {
        "bare": j([{"id": n["id"], "label": n.get("label", "")} for n in nodes]),
        "covered": j({"nodes": [{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                                 "label": n.get("label"), "gloss": n.get("gloss")} for n in nodes],
                      "edges": trunk.get("edges", [])}),
    }


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
    ap.add_argument("--trunk", default=str(ROOT / "03_锚与主干" / "trunk_v2_covered.json"))
    ap.add_argument("--anchors", default=str(ROOT / "03_锚与主干" / "anchors_external_v2.json"))
    ap.add_argument("--arms", default="bare,covered")
    ap.add_argument("--ablate", action="store_true", help="额外跑覆盖消融臂（去掉替代节点）")
    ap.add_argument("--judge", action="store_true", help="额外跑独立判定臂")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    cfg = load(args.config)
    trunk = load(args.trunk)
    anchors = load(args.anchors)["anchors"]
    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s | trunk nodes=%d edges=%d | anchors=%d"
          % (ok, detail, len(trunk["nodes"]), len(trunk["edges"]), len(anchors)))
    if not ok:
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("v2_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "meta", "ts": ts, "trunk": Path(args.trunk).name,
                            "anchors": Path(args.anchors).name, "repeat": args.repeat,
                            "arms": args.arms, "ablate": args.ablate, "judge": args.judge},
                           ensure_ascii=False) + "\n")

    # 覆盖消融用的 trunk：去掉 5 个替代节点及其相关边
    ablate_trunk = None
    if args.ablate:
        at = json.loads(json.dumps(trunk))
        at["nodes"] = [n for n in at["nodes"] if n["id"] not in ALT_IDS]
        at["edges"] = [e for e in at["edges"]
                       if e.get("from") not in ALT_IDS and e.get("to") not in ALT_IDS]
        ablate_trunk = at

    def run_arm(system, view, ids, allowed_edges, text, timeout):
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

    V = views(trunk)
    ids = sorted({n["id"] for n in trunk["nodes"]})
    ae = {e for e in (norm_edge(x) for x in trunk["edges"]) if e}
    V_A = A_ids = A_ae = None
    if ablate_trunk:
        V_A = views(ablate_trunk)
        A_ids = sorted({n["id"] for n in ablate_trunk["nodes"]})
        A_ae = {e for e in (norm_edge(x) for x in ablate_trunk["edges"]) if e}

    arms = [a.strip() for a in args.arms.split(",")]
    rows = []
    for a in anchors:
        gold = a["gold"]
        row = {"anchor_id": a["id"], "is_ban_sample": a.get("is_ban_sample", False),
               "gold": gold, "arms": {}}
        for arm in arms:
            reps = []
            for r in range(args.repeat):
                if arm == "bare":
                    rec = run_arm(BARE_SYSTEM, V["bare"], ids, ae, a["text"], args.timeout)
                else:
                    rec = run_arm(COVERED_SYSTEM, V["covered"], ids, ae, a["text"], args.timeout)
                reps.append({"rec": rec, "score": score(rec, gold)})
            row["arms"][arm] = reps
            print("[%s][%-8s] %-44s hit=%s exact=%s off=%d" % (
                a["id"], arm, ",".join(reps[0]["rec"]["nodes"]) or "(空)",
                reps[0]["score"]["node_hit_any"], reps[0]["score"]["exact_set"],
                reps[0]["score"]["offchart"]))
        if args.ablate and a.get("is_ban_sample"):
            reps = []
            for r in range(args.repeat):
                rec = run_arm(COVERED_SYSTEM, V_A["covered"], A_ids, A_ae, a["text"], args.timeout)
                reps.append({"rec": rec, "score": score(rec, gold)})
            row["arms"]["covered_minus_alt"] = reps
            print("[%s][%-8s] %-44s hit=%s exact=%s  <- 覆盖消融" % (
                a["id"], "no-alt", ",".join(reps[0]["rec"]["nodes"]) or "(空)",
                reps[0]["score"]["node_hit_any"], reps[0]["score"]["exact_set"]))
        if args.judge:
            jr = providers.chat(cfg, JUDGE_SYSTEM, "段落：\n%s\n\n请判定条件。" % a["text"],
                                temperature=0.1, max_tokens=400, timeout=args.timeout,
                                thinking="disabled")
            row["judge"] = extract(jr) or {}
            print("      judge: %s" % ",".join(
                "%s=%s" % (k, row["judge"].get(k)) for k in ("J1", "J2", "J3", "J4", "J5")))
        rows.append(row)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 汇总
    def agg(sel, arm, key):
        vals = [x["score"][key] for r in rows if sel(r) for x in r["arms"].get(arm, [])
                if x["score"][key] is not None]
        return (sum(vals) / len(vals)) if vals else None

    def rate(sel, arm):
        tot = sum(len(r["arms"].get(arm, [])) for r in rows if sel(r))
        hit = sum(1 for r in rows if sel(r) for x in r["arms"].get(arm, []) if x["score"]["node_hit_any"])
        ex = sum(1 for r in rows if sel(r) for x in r["arms"].get(arm, []) if x["score"]["exact_set"])
        return hit, ex, tot

    isE = lambda r: not r["is_ban_sample"]
    isN = lambda r: r["is_ban_sample"] and r["anchor_id"].startswith("N")
    isD = lambda r: r["anchor_id"].startswith("D")

    print("\n" + "=" * 78)
    print("主锚 E*（应停在对应母题）       hit/total   exact/total   meanJaccard")
    for arm in arms + (["covered_minus_alt"] if args.ablate else []):
        h, e, t = rate(isE, arm)
        if t:
            print("  %-20s %5d/%-5d %5d/%-5d %s" % (
                arm, h, t, e, t, "%.3f" % agg(isE, arm, "jaccard") if agg(isE, arm, "jaccard") is not None else "—"))
    print("\n硬负例 N*（应停在替代节点）     hit/total   exact/total   meanJaccard")
    for arm in arms + (["covered_minus_alt"] if args.ablate else []):
        h, e, t = rate(isN, arm)
        if t:
            print("  %-20s %5d/%-5d %5d/%-5d %s" % (
                arm, h, t, e, t, "%.3f" % agg(isN, arm, "jaccard") if agg(isN, arm, "jaccard") is not None else "—"))
    print("\n近义干扰 D*（应识别为标签复读） hit/total   exact/total")
    for arm in arms:
        h, e, t = rate(isD, arm)
        if t:
            print("  %-20s %5d/%-5d %5d/%-5d" % (arm, h, t, e, t))
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
