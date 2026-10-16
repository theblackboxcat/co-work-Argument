#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""替代停靠点实验：P3p 停在禁节点，是「不能执行约束」还是「无处可去」？

关键判读修正：
  协议 §2 的停靠 = 小子图 {nodes, edges}。因此 P1p 输出 [S03, S16]（化形 + 禁枝）
  是**协议要求的正确行为**（提议并标注违规，交作者 commit），不是失败。
  真正无反应的只有 P3p（字面风景停在 S05，且未标任何警告）。

新假设：P3p 之所以停在 S05，可能不是执行失败，而是 trunk 里**没有可供它停靠的
「字面景物」节点**——它没别的地方可去。

检验：向 trunk 临时注入一个对照节点 S23_literal_scenery（不改 trunk_v0.json 本体），
      看 P3p 是否会停过去；同时确认 P3（正例）不受影响。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from ablate import ARM_SYSTEM, build_views, extract_json_obj, load_json, norm_edge  # noqa: E402

ALT = {
    "id": "S23_literal_scenery",
    "parent": "B02_motif_cluster",
    "layer": "stop",
    "label": "字面景物描写",
    "gloss": "对自然景物的直接描写（平原、风、草地、地平线），不含处境隐喻；"
             "若段落只是写景而非谈处境结构，停在此处，不要停在存在主义平原。",
}
WANT = {"P3_plain", "P3p_scenery", "P1_transform", "P1p_psychologized"}


def main():
    cfg = load_json(DEMO / "config.json")
    trunk = load_json(DEMO / "trunk_v0.json")
    extra = load_json(DEMO / "trunk_v1_parent_edges.json")
    ex = extra.get("edges", extra) if isinstance(extra, dict) else extra
    have = {(e.get("from"), e.get("to"), e.get("kind")) for e in trunk.get("edges", [])}
    trunk = dict(trunk)
    trunk["edges"] = list(trunk.get("edges", [])) + [e for e in ex
                                                     if (e.get("from"), e.get("to"), e.get("kind")) not in have]
    # 注入替代停靠点 + 其与 S05 的 contrast 边（加性，不改本体文件）
    trunk["nodes"] = list(trunk["nodes"]) + [dict(ALT)]
    trunk["edges"] = list(trunk["edges"]) + [
        {"from": "S23_literal_scenery", "to": "S05_existential_plain", "kind": "contrast",
         "note": "字面景物 vs 处境结构"}]
    ids = sorted({n["id"] for n in trunk["nodes"]})
    allowed = set(ids)
    views = build_views(trunk)
    lab = {n["id"]: n.get("label", "") for n in trunk["nodes"]}
    anchors = [a for a in load_json(DEMO / "anchors_lit_v1.json")["anchors"] if a["id"] in WANT]

    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s | 注入替代节点 %s" % (ok, detail, ALT["id"]))
    if not ok:
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("alt_stop_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)

    print("\n########## 有替代停靠点时，P3p 是否改停 ##########")
    for a in anchors:
        for r in range(3):
            user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                    % (views["D_full"], json.dumps(ids, ensure_ascii=False), a["text"]))
            rep = providers.chat(cfg, ARM_SYSTEM["D_full"], user, temperature=0.2,
                                 max_tokens=800, timeout=60, thinking="disabled")
            p = extract_json_obj(rep) or {}
            nodes = [x for x in (p.get("nodes") or []) if isinstance(x, str) and x in allowed]
            print(" %-20s r%d  %s | %s" % (
                a["id"], r, ",".join("%s(%s)" % (n, lab.get(n, "")[:8]) for n in nodes) or "(空)",
                (p.get("rationale_short") or "")[:80]))
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"anchor_id": a["id"], "rep": r, "nodes": nodes,
                                    "rationale": p.get("rationale_short", ""), "raw": rep},
                                   ensure_ascii=False) + "\n")
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
