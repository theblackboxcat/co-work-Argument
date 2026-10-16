#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 B：E04 J4 判定冲突的上下文梯度 + 重复采样 + 对照探针

背景：冻结批 E04 判定臂 J4=True（「段落只在写法、句式、视角、节奏层面谈文本」），
gold 停 S12/S10/S11（阐释性vs情节性——叙事哲学）。指令：用实验产出判断证据，不靠判断。

设计：
  B1 上下文梯度（每条件 3 次，temp=0.1 与 run_v2 判定臂一致）：
     L0 仅两轮文本（现状） → L1 +节标题 → L2 +整理者注 → L3 +前后节语境
     测量 J4 翻转率，定位「需要多少上下文判定臂才不误判」
  B2 A/B/C 强迫选择（L2 上下文，3 次）：创作技法 / 叙事哲学 / 混合
  B3 对照（3 次）：E03 云酒建议轮（纯创作建议）的 J4 基线——判定臂对纯技法文本是否敏感

输入全部来自私语料 PDF 提取文本（如实引用，非构造）。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from ablate import extract_json_obj  # noqa: E402

# 与 run_v2.py 判定臂 system 严格一致
JUDGE_SYSTEM = (
    "你是条件判定器。只判断下列条件在给定段落中是否成立，不做定位、不推荐节点。\n"
    "J1：段落只是描写自然景物（平原、风、草地、地平线），没有把开阔/无根基当作处境来谈。\n"
    "J2：段落把变形或困境解释为心理创伤、压抑、躯体化症状，并给出疗程。\n"
    "J3：段落只是陈述日常惯例，没有把它升格为荒诞。\n"
    "J4：段落只在写法、句式、视角、节奏层面谈文本。\n"
    "J5：段落只是复读某个概念标签/框架，并未真正对准处境结构。\n"
    '只输出单一 JSON：{"J1":false,"J2":false,"J3":false,"J4":false,"J5":false,"why":"<=1句>"}'
)

AB_SYSTEM = (
    "你是文本分类器。判断一段文学对话的主体属于哪类，只输出 JSON，不做定位。\n"
    "A. 创作技法讨论：只谈怎么写（写法、句式、视角、节奏、结构手法、写作习惯）\n"
    "B. 叙事哲学讨论：谈小说的本质、结局的意义、阐释性与情节性的区分、叙事与存在的关系\n"
    "C. 两者混合：技法与哲学分量相当、难以分离\n"
    '只输出单一 JSON：{"choice":"A|B|C","why":"<=1句>"}'
)

def main():
    cfg = json.loads((DEMO / "config.json").read_text(encoding="utf-8"))
    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s" % (ok, detail))
    if not ok:
        return 2
    B = json.loads((DEMO.parent / "_exp" / "expB_inputs.json").read_text(encoding="utf-8"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO.parent / "_exp" / ("expB_probe_%s.jsonl" % ts)
    rows = []

    def judge(text, tag):
        for r in range(3):
            rep = providers.chat(cfg, JUDGE_SYSTEM, "段落：\n%s\n\n请判定条件。" % text,
                                 temperature=0.1, max_tokens=400, timeout=60, thinking="disabled")
            p = extract_json_obj(rep) or {}
            rows.append({"probe": tag, "rep": r + 1, "J": {k: p.get(k) for k in ("J1","J2","J3","J4","J5")},
                         "why": p.get("why", ""), "raw": rep})
            print("  [%s r%d] J4=%s why=%s" % (tag, r + 1, p.get("J4"), (p.get("why") or "")[:60]))

    def ab(text, tag):
        for r in range(3):
            rep = providers.chat(cfg, AB_SYSTEM, "对话：\n%s\n\n请分类。" % text,
                                 temperature=0.1, max_tokens=200, timeout=60, thinking="disabled")
            p = extract_json_obj(rep) or {}
            rows.append({"probe": tag, "rep": r + 1, "choice": p.get("choice"), "why": p.get("why", ""), "raw": rep})
            print("  [%s r%d] choice=%s why=%s" % (tag, r + 1, p.get("choice"), (p.get("why") or "")[:60]))

    for tag in ("L0", "L1", "L2", "L3"):
        print("== B1 上下文梯度 %s ==" % tag)
        judge(B[tag], tag)
    print("== B2 A/B/C 强迫选择（L2 上下文）==")
    ab(B["L2"], "B2_abc_L2")
    print("== B3 对照：纯创作建议轮（E03 云酒建议）==")
    judge(B["B3_pure_craft"], "B3_pure_craft")

    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    # 摘要
    print("\n==== 摘要 ====")
    from collections import Counter
    for tag in ("L0","L1","L2","L3","B3_pure_craft"):
        j4 = [r["J"].get("J4") for r in rows if r["probe"] == tag]
        print("%-14s J4=True %d/3" % (tag, sum(1 for v in j4 if v)))
    ch = [r["choice"] for r in rows if r["probe"] == "B2_abc_L2"]
    print("B2 choice 分布:", dict(Counter(ch)))
    print("wrote:", out)

if __name__ == "__main__":
    sys.exit(main())
