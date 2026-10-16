#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""覆盖节点的设计原则检验：S27_false_alignment 为何从未被选中？

v2 主实验中 S27（假对齐/标签复读）**一次都没被选中**，D 类近义干扰 0/3。
判定臂却把 D01-D03 全部判为 J5=True（标签复读）——又是"判得对、停不对"。

假设：S27 的 gloss 只做了**语义描述**（"借用了共享词但未对准"），
而复读文本在字面上与母题 label 高度重合，语义匹配因此偏向原母题（S05/S06/S03）。
要让覆盖节点真正吸引停靠，它的 gloss 必须包含该类的**可识别形式特征**，
而不只是语义描述。

检验：给 S27 补上形式线索（元语言标记），重跑 D* 与 N05。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
ROOT = DEMO.parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from run_v2 import COVERED_SYSTEM, extract, norm_edge, views  # noqa: E402

S27_OLD = None
S27_NEW = ("假对齐（贴标签复读）：段落**引用**了母题名或框架名，但只是把名称套上去，"
           "没有真正展开处境。识别线索（出现任一条即高度可疑）："
           "「按照…的说法」「这是典型的/标准的…」「我这个框架用得对吧」、直接点名母题术语、"
           "用定义句而非情境句来谈处境。"
           "若段落只是套用名称、在问框架用得对不对，而不是展开处境，停在此处。")

WANT = {"D01_label_paraphrase_plain", "D02_label_paraphrase_fractal",
        "D03_label_paraphrase_transform", "N05_false_alignment"}


def main():
    cfg = json.load(open(DEMO / "config.json"))
    trunk = json.loads((ROOT / "03_锚与主干" / "trunk_v2_covered.json").read_text(encoding="utf-8"))
    anchors = [a for a in json.loads((ROOT / "03_锚与主干" / "anchors_external_v2.json")
                                     .read_text(encoding="utf-8"))["anchors"] if a["id"] in WANT]
    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s" % (ok, detail))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("s27_patch_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)

    for tag, gloss in (("base", None), ("patched", S27_NEW)):
        t = json.loads(json.dumps(trunk))
        if gloss:
            for n in t["nodes"]:
                if n["id"] == "S27_false_alignment":
                    n["gloss"] = gloss
        ids = sorted({n["id"] for n in t["nodes"]})
        allowed = set(ids)
        ae = {e for e in (norm_edge(x) for x in t["edges"]) if e}
        V = views(t)
        print("\n########## S27 gloss = %s ##########" % tag)
        for a in anchors:
            for r in range(3):
                user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                        % (V["covered"], json.dumps(ids, ensure_ascii=False), a["text"]))
                rep = providers.chat(cfg, COVERED_SYSTEM, user, temperature=0.2,
                                     max_tokens=700, timeout=60, thinking="disabled")
                p = extract(rep) or {}
                nodes = [x for x in (p.get("nodes") or []) if isinstance(x, str) and x in allowed]
                gold = set(a["gold"]["nodes"])
                hit = sorted(set(nodes) & gold)
                print(" [%s] %-32s r%d  %-46s hit=%s" % (
                    tag, a["id"], r, ",".join(nodes) or "(空)", hit or "-"))
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"gloss": tag, "anchor_id": a["id"], "rep": r,
                                        "nodes": nodes, "gold": sorted(gold), "hits": hit,
                                        "raw": rep}, ensure_ascii=False) + "\n")
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
