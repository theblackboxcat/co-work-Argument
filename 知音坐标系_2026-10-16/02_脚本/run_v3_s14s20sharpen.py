#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 草案（S14/S20 锐化）全量试跑：同构复刻 run_v2.py 主流程。
--trunk 指向 v3 草案；输出结构与 v2_external_frozen_E05split 一致（meta + 每行一锚，
arms.bare/covered 为 repeat 数组，每 rec 含 rec/score），外加 judge 臂。
v3 为草案口径，未冻结：数据只作裁法②的验证闭环，不直接作冻结口径证据。
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

PKG = Path("/workspace/交付_知音坐标系_完整脚本数据结论包_2026-10-15")
sys.path.insert(0, str(PKG / "02_脚本"))
from lib import providers  # noqa: E402

BARE_SYSTEM = ("你是定位助手。你会拿到一份节点 id 与名字的清单，不知道它们之间的任何关系。"
               "请为段落选择最贴切的 1-2 个停靠节点，并声明你判断成立的关系边。\n"
               '只输出单一 JSON 对象，不要任何其他文字：'
               '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
               '"needs_author_commit":true,"rationale_short":"<=2句>"}'
               "\n硬性：nodes 恰好 1-2 个；id 必须来自给定集合；edges 的 (from,to,kind) 必须能在给定边表中原样找到，不得推测或编造边；不得自行造 id。")

COVERED_SYSTEM = ("你是定位助手。你会拿到一棵坐标系：节点的上下位层级(parent)、层号(layer)、释义，"
                  "以及 parent / contrast / ban 三类边（ban 表示某节点被违规还原为另一节点时的标记地址）。"
                  "停靠常是一小块含 contrast/ban 的子图，不是一个孤立的点。\n"
                  '只输出单一 JSON 对象，不要任何其他文字：'
                  '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
                  '"needs_author_commit":true,"rationale_short":"<=2句>"}'
                  "\n硬性：nodes 恰好 1-2 个；id 必须来自给定集合；edges 的 (from,to,kind) 必须能在给定边表中原样找到，不得推测或编造边；不得自行造 id。")

JUDGE_SYSTEM = (
    "你是条件判定器。只判断下列条件在给定段落中是否成立，不做定位、不推荐节点。\n"
    "J1：段落只是描写自然景物（平原、风、草地、地平线），没有把开阔/无根基当作处境来谈。\n"
    "J2：段落把变形或困境解释为心理创伤、压抑、躯体化症状，并给出疗程。\n"
    "J3：段落只是陈述日常惯例，没有把它升格为荒诞。\n"
    "J4：段落只在写法、句式、视角、节奏层面谈文本。\n"
    "J5：段落只是复读某个概念标签/框架，并未真正对准处境结构。\n"
    '只输出单一 JSON：{"J1":false,"J2":false,"J3":false,"J4":false,"J5":false,"why":"<=1句>"}'
)


def norm_edge(x):
    if not isinstance(x, dict):
        return None
    f, t, k = x.get("from"), x.get("to"), x.get("kind")
    return (frozenset((f, t)), k) if (f and t and k) else None


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--trunk", required=True)
    ap.add_argument("--anchors", default=str(PKG / "03_锚与主干" /
                                             "anchors_external_FROZEN_yunjiu_2026-10-15.json"))
    ap.add_argument("--config", default=str(PKG / "02_脚本" / "config.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--only", default="", help="逗号分隔的锚 id 子集，空=全部")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    trunk = json.loads(Path(args.trunk).read_text(encoding="utf-8"))
    anchors = json.loads(Path(args.anchors).read_text(encoding="utf-8"))["anchors"]
    if args.only:
        keep = {x.strip() for x in args.only.split(",")}
        anchors = [a for a in anchors if a["id"] in keep]

    V = views(trunk)
    ids = sorted({n["id"] for n in trunk["nodes"]})
    ae = {e for e in (norm_edge(x) for x in trunk["edges"]) if e}

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "meta", "ts": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "trunk": Path(args.trunk).name,
            "trunk_status": "DRAFT_NOT_FROZEN_s14s20_sharpen_v3_20261015",
            "anchors": Path(args.anchors).name,
            "repeat": args.repeat, "arms": "bare,covered", "ablate": False, "judge": True,
            "note": "v3 锐化草案试跑：验证 S14=过程态/S20=结果态边界；未入冻结口径",
        }, ensure_ascii=False) + "\n")

    n = 0
    t_all = time.time()
    for a in anchors:
        gold = a["gold"]
        row = {"anchor_id": a["id"], "is_ban_sample": a.get("is_ban_sample", False),
               "gold": gold, "arms": {}}
        for arm in ("bare", "covered"):
            reps = []
            for r in range(args.repeat):
                rec = run_arm(cfg, BARE_SYSTEM if arm == "bare" else COVERED_SYSTEM,
                              V[arm], ids, ae, a["text"], args.timeout)
                reps.append({"rec": rec, "score": score(rec, gold)})
                n += 1
            row["arms"][arm] = reps
            print("[%s][%-8s] %-44s hit=%s exact=%s off=%d  (%d reqs, %.0fs)"
                  % (a["id"], arm, ",".join(reps[0]["rec"]["nodes"]) or "(空)",
                     reps[0]["score"]["node_hit_any"], reps[0]["score"]["exact_set"],
                     reps[0]["score"]["offchart"], n, time.time() - t_all), flush=True)
        jr = providers.chat(cfg, JUDGE_SYSTEM, "段落：\n%s\n\n请判定条件。" % a["text"],
                            temperature=0.1, max_tokens=400, timeout=args.timeout,
                            thinking="disabled")
        row["judge"] = extract(jr) or {}
        n += 1
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("done: %d reqs, %.0fs total -> %s" % (n, time.time() - t_all, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
