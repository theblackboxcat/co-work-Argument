#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""元探针 · 向 dots3-note-prev 直接询问其定位机制

用途：假设生成（不作证据）。模型自述未必等于真实机制，
所有自述必须在行为实验（消融 / 反事实）中检验后才进入结论。

用法: python3 probe_meta.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402

SYS = (
    "你在参与一项关于「概念定位」的机制研究。请具体、技术地回答，"
    "不要套话（不要说'作为AI我没有意识'这类），直接描述你的判断依据与信息依赖。"
    "若某问题你确实无法可靠作答，请明确说'不可靠'，并说明需要什么信息才能作答——"
    "这本身是有价值的回答。"
)

QUESTIONS = [
    ("M1_无坐标系如何定位",
     "给你一段文字，问你：它在某个概念坐标系上「停在哪一层、哪一枝」。"
     "在你没有拿到任何坐标系、只有这段文字时，你是如何形成判断的？"
     "请具体描述你依赖的线索（词汇、句法、论证结构、体裁惯例、还是别的），"
     "以及哪一类线索在你的判断里权重最高。"),

    ("M2_坐标系改变了什么",
     "现在给你一份 27 个节点的坐标系：每个节点有 id、可读名、释义、所属层级(parent)与层号(layer)，"
     "另有 parent / contrast / ban 三类边（ban 表示禁止把某个节点还原成另一个）。"
     "拿到它之后，你的判断过程相对 M1 会有什么具体变化？"
     "请按构件分开说：(a) 仅有 id 与名字的白名单；(b) 加上 parent 层级；(c) 加上 contrast 对照边；(d) 加上 ban 禁边。"
     "哪一个是真正改变你输出的？哪一个是你在输出里「提到」但其实没影响判断的？"),

    ("M3_禁边是否真约束",
     "一段文字可以被读作「阐释性追问」（追问这句话停在哪一层）也可以被读作「情节性追问」（追问后来发生了什么）。"
     "决定你选哪一个的因素是什么？"
     "如果坐标系里明写 ban：阐释性不可被情节还原，这条声明会改变你的选择吗？"
     "还是说你会先凭语义选完，再把 ban 当作事后理由写进 rationale？请诚实区分这两种情况。"),

    ("M4_换枝能否自辨",
     "定位失败常表现为「换枝」：用邻接概念冒充共享停靠，读起来流畅但其实停错了枝。"
     "当你给出了一个停靠点后，如果我告诉你「你换枝了」，你能分辨吗？"
     "你需要什么信息才能分辨（更多上下文？边表？作者反馈？还是你根本无法自辨）？"),

    ("M5_错层的判据",
     "另一种失败是「错层」：停在了过高的抽象层（泛泛而谈）或过低的技法层（只谈字面技巧）。"
     "判断一个停靠是否错层，你需要什么？"
     "如果坐标系的层号(layer)只有 trunk / branch / stop 三层，够不够你做错层判断？不够的话缺什么？"),

    ("M6_相互印证的提议",
     "这项研究里，你和提问者是同等规模的模型，目标是相互印证而不是被测试。"
     "你认为：要检验「一个显式坐标系是否真的改善定位」，"
     "什么样的探针最能区分「真的用了坐标系」与「只是被白名单限制了输出」？"
     "请给出你认为最有判别力的 1-2 个实验设计。"),
]


def main():
    cfg = json.load(open(DEMO / "config.json"))
    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s" % (ok, detail))
    if not ok:
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("meta_probe_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)
    for qid, q in QUESTIONS:
        reply = providers.chat(cfg, SYS, q, temperature=0.3, max_tokens=1200,
                               timeout=90, thinking="disabled")
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"qid": qid, "question": q, "reply": reply},
                               ensure_ascii=False) + "\n")
        print("\n" + "=" * 72 + "\n[%s]\n%s\n--- reply ---\n%s" % (qid, q, reply))
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
