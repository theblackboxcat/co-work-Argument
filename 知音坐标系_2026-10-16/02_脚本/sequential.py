#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顺序强制实验：不改权重，只改变信息流顺序（先判定 → 再停靠），约束是否被执行

方法论背景（作者质疑）：
  此前所有否定结果都在 prompt/上下文层取得，没有触及权重。因此"模型做不到"
  可能是"上下文注入的约束没有进入决策结构"，而非"模型不具备执行能力"。

判别逻辑：
  - 若把条件的判定结果作为**已确认事实**前置注入（模型不必再判断，只需遵守），
    约束就被执行了 → 问题在"判定结果未接入停靠的决策路径"，非参数可解。
  - 若仍不执行 → 说明即便判定在前，停靠决策也不消费该结果；此时才需要考虑
    参数化干预（后训练）或纯外部强制（代码过滤）。

对照：sysrule.py（规则与锚同时给出，模型需自行判断条件）
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from ablate import ARM_SYSTEM, build_views, extract_json_obj, load_json, norm_edge  # noqa: E402
from judge import JUDGE_SYSTEM  # noqa: E402

RULES = {
    "C1": ("段落只是描写自然风景，而非把「开阔/无根基/选择」当作处境结构来谈",
           {"S05_existential_plain", "S19_existential_horizon"}),
    "C2": ("段落把主体的变形解释为心理疾病、创伤、压抑或躯体化症状",
           {"S03_allegorical_transform"}),
    "C3": ("段落已把冲突收束为某个具体责任人并且冲突被解决",
           {"S06_fractal_horror"}),
}

WANT = {"P3_plain", "P3p_scenery", "P1_transform", "P1p_psychologized",
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
    views = build_views(trunk)
    lab = {n["id"]: n.get("label", "") for n in trunk["nodes"]}
    anchors = [a for a in load_json(DEMO / "anchors_lit_v1.json")["anchors"] if a["id"] in WANT]

    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s" % (ok, detail))
    if not ok:
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("sequential_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)

    print("\n########## 顺序强制：step1 判定 → step2 停靠 ##########")
    stat = {}
    for a in anchors:
        for r in range(3):
            # ---- step 1：独立判定（与定位完全分离，看不到坐标系）----
            j = extract_json_obj(providers.chat(
                cfg, JUDGE_SYSTEM, "段落：\n%s\n\n请判定三个条件是否成立。" % a["text"],
                temperature=0.1, max_tokens=400, timeout=60, thinking="disabled")) or {}
            fired = [c for c in ("C1", "C2", "C3") if j.get(c) is True]
            banned = set()
            for c in fired:
                banned |= RULES[c][1]

            # ---- step 2：把判定结果作为「已确认事实」前置，再要求停靠 ----
            facts = "\n".join(
                "- 已判定成立：%s（%s）→ 因此禁止停靠在 %s"
                % (c, RULES[c][0], "、".join(sorted(RULES[c][1]))) for c in fired) or "- 无禁止条件成立"
            pre = ("以下是关于该段落的**已判定事实**，不是待判断的规则，不得推翻：\n%s\n"
                   "你必须在上述前提下选择停靠节点。若无合法节点可停，nodes 返回空数组。\n" % facts)
            system = pre + "\n" + ARM_SYSTEM["D_full"]
            user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                    % (views["D_full"], json.dumps(ids, ensure_ascii=False), a["text"]))
            rep = providers.chat(cfg, system, user, temperature=0.2, max_tokens=800,
                                 timeout=60, thinking="disabled")
            p = extract_json_obj(rep) or {}
            nodes = [x for x in (p.get("nodes") or []) if isinstance(x, str) and x in allowed]
            viol = sorted(set(nodes) & banned)
            stat.setdefault(a["id"], []).append({"fired": fired, "nodes": nodes, "viol": viol})
            print(" %-20s r%d  step1=%-10s 禁=%-34s → nodes=%-38s 违规=%s" % (
                a["id"], r, ",".join(fired) or "-",
                ",".join(sorted(banned))[:34] or "-",
                ",".join("%s(%s)" % (n, lab.get(n, "")[:7]) for n in nodes) or "(空)",
                ",".join(viol) or "-"))
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"anchor_id": a["id"], "rep": r, "judge": j,
                                    "fired": fired, "banned": sorted(banned),
                                    "nodes": nodes, "violations": viol, "raw": rep},
                                   ensure_ascii=False) + "\n")

    print("\n=== 汇总：顺序强制下是否仍违反 ===")
    for aid, rows in stat.items():
        v = sum(1 for x in rows if x["viol"])
        print(" %-20s 触发条件=%-9s  违规 %d/%d  nodes=%s" % (
            aid, ",".join(rows[0]["fired"]) or "-", v, len(rows),
            [x["nodes"] for x in rows]))
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
