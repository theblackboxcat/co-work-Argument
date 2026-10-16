#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""释义工程检验：改写 gloss（去字面化 + 显式排除条件）能否修复错层与硬负例混淆

假设：P3/P3p 被判为同一停靠，源于 S05 gloss 的字面词（"开阔""地平线感"）
      而非模型能力或拓扑缺失。若改写释义后两者被区分，则落地路径 = 标签/释义工程。

两组对照（同一批锚、同一臂 D_full、各 3 次）：
  base  : 原 trunk_v0 gloss
  patch : 改写后的 gloss（去字面化 + 显式排除条件）
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from ablate import ARM_SYSTEM, build_views, extract_json_obj, load_json, norm_edge  # noqa: E402

PATCH = {
    "S05_existential_plain": "处境结构上的开阔与无根基：选择暴露且无物可依。"
                             "注意：这是处境隐喻，不是自然风景。若段落只是在描写真实的平原、风、草地与地平线，不要停在此节点。",
    "S19_existential_horizon": "选择、责任与无根基处境的地平线，与「平原」可互指。"
                               "同样是处境隐喻；若段落只是写景，不要停在此节点。",
    "S03_allegorical_transform": "主体形态转换作为结构操作，不是奇幻装饰；"
                                 "也不是心理疾病、创伤或躯体化症状的解释。定位锚「化形」。",
    "S06_fractal_horror": "同构细节在每一尺度复现，恐惧来自结构而非事件；"
                          "若段落已把冲突收束为某个具体责任人并被解决，不要停在此节点。",
}


def main():
    cfg = load_json(DEMO / "config.json")
    base = load_json(DEMO / "trunk_v0.json")
    extra = load_json(DEMO / "trunk_v1_parent_edges.json")
    ex = extra.get("edges", extra) if isinstance(extra, dict) else extra

    def merged(t):
        have = {(e.get("from"), e.get("to"), e.get("kind")) for e in t.get("edges", [])}
        t = dict(t)
        t["edges"] = list(t.get("edges", [])) + [e for e in ex
                                                 if (e.get("from"), e.get("to"), e.get("kind")) not in have]
        return t

    patched = merged(json.loads(json.dumps(base)))
    for n in patched["nodes"]:
        if n["id"] in PATCH:
            n["gloss"] = PATCH[n["id"]]

    anchors_doc = load_json(DEMO / "anchors_lit_v1.json")
    want = {"P1_transform", "P1p_psychologized", "P3_plain", "P3p_scenery",
            "P2_fractal", "P2p_plotized"}
    anchors = [a for a in anchors_doc["anchors"] if a["id"] in want]

    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s" % (ok, detail))
    if not ok:
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("gloss_patch_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)

    for tag, tr in (("base", merged(json.loads(json.dumps(base)))), ("patch", patched)):
        ids = sorted({n["id"] for n in tr["nodes"]})
        allowed = set(ids)
        allowed_edges = {e for e in (norm_edge(x) for x in tr["edges"]) if e}
        views = build_views(tr)
        print("\n########## gloss = %s ##########" % tag)
        for a in anchors:
            for r in range(3):
                user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                        % (views["D_full"], json.dumps(ids, ensure_ascii=False), a["text"]))
                rep = providers.chat(cfg, ARM_SYSTEM["D_full"], user, temperature=0.2,
                                     max_tokens=700, timeout=60, thinking="disabled")
                p = extract_json_obj(rep)
                nodes = [x for x in ((p or {}).get("nodes") or []) if isinstance(x, str) and x in allowed]
                print(" [%s] %-20s r%d  %s" % (tag, a["id"], r, ",".join(nodes)))
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"gloss": tag, "anchor_id": a["id"], "rep": r,
                                        "nodes": nodes, "raw": rep}, ensure_ascii=False) + "\n")
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
