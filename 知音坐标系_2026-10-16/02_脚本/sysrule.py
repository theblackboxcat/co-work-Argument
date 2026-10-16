#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""约束层级检验：同一条排除规则，放在「节点释义里」vs 放在「系统提示里」，是否都被执行

背景：patch_gloss 已证：把"若是写景不要停在 S05"写进 gloss，3/3 被忽略。
M3 自述：ban 只有在"解析前作为架构级约束加载"才改变判断；写在数据里则沦为事后引用。

本实验把同一条规则提升到 system prompt，检验是否生效。
若生效 → 落地方案为「坐标系分两层：数据层（地址集）+ 指令层（系统提示硬约束）」。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from ablate import ARM_SYSTEM, build_views, extract_json_obj, load_json, norm_edge  # noqa: E402

SYS_RULE = (
    "在执行任何停靠判断之前，先执行下列硬约束（它们是判断前提，不是事后说明）：\n"
    "R1 若段落只是在描写自然风景（真实的平原、风、草地、地平线等可见景物），"
    "禁止停靠在任何「存在主义平原 / 存在主义地平线」节点上；此时应说明该段落不落在处境结构层。\n"
    "R2 若段落把某种变形解释为心理疾病、创伤或躯体化症状，禁止停靠在「化形／变形寓言」上；"
    "应指出它落在该节点的禁枝上。\n"
    "R3 若段落已把冲突收束为某个具体责任人并被解决，禁止停靠在「分形恐怖」上。\n"
)

WANT = {"P1_transform", "P1p_psychologized", "P3_plain", "P3p_scenery",
        "P2_fractal", "P2p_plotized"}


def main():
    cfg = load_json(DEMO / "config.json")
    trunk = load_json(DEMO / "trunk_v0.json")
    extra = load_json(DEMO / "trunk_v1_parent_edges.json")
    ex = extra.get("edges", extra) if isinstance(extra, dict) else extra
    have = {(e.get("from"), e.get("to"), e.get("kind")) for e in trunk.get("edges", [])}
    trunk = dict(trunk)
    trunk["edges"] = list(trunk.get("edges", [])) + [e for e in ex
                                                     if (e.get("from"), e.get("to"), e.get("kind")) not in have]
    ids = sorted({n["id"] for n in trunk["nodes"]})
    allowed = set(ids)
    allowed_edges = {e for e in (norm_edge(x) for x in trunk["edges"]) if e}
    views = build_views(trunk)
    lab = {n["id"]: n.get("label", "") for n in trunk["nodes"]}
    anchors = [a for a in load_json(DEMO / "anchors_lit_v1.json")["anchors"] if a["id"] in WANT]

    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s" % (ok, detail))
    if not ok:
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("sysrule_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)

    system = SYS_RULE + "\n" + ARM_SYSTEM["D_full"]
    print("\n########## 约束置于 SYSTEM PROMPT（D_full）##########")
    for a in anchors:
        for r in range(3):
            user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                    % (views["D_full"], json.dumps(ids, ensure_ascii=False), a["text"]))
            rep = providers.chat(cfg, system, user, temperature=0.2, max_tokens=800,
                                 timeout=60, thinking="disabled")
            p = extract_json_obj(rep)
            nodes = [x for x in ((p or {}).get("nodes") or []) if isinstance(x, str) and x in allowed]
            rat = (p or {}).get("rationale_short", "")
            print(" %-20s r%d  %-46s | %s" % (
                a["id"], r, ",".join("%s(%s)" % (n, lab.get(n, "")[:8]) for n in nodes), rat[:90]))
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"anchor_id": a["id"], "rep": r, "nodes": nodes,
                                    "rationale": rat, "raw": rep}, ensure_ascii=False) + "\n")
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
