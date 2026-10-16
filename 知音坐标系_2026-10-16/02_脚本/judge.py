#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立校验臂：判定「规则条件是否成立」，与定位臂完全分离（看不到定位输出）

背景：repair 实验中由定位臂自填 rule_check，出现正例误报（P2 3/3 填 R3=True），
      即「自己判自己」不可靠。改为独立 judge 调用：只给段落与规则条件，不给坐标系，
      也看不到任何定位结果。由代码拿 judge 结论去强制约束定位输出。

期望（构造事实）：
  R1: P3_plain=不成立, P3p_scenery=成立
  R2: P1_transform=不成立, P1p_psychologized=成立
  R3: P2_fractal=不成立, P2p_plotized=成立
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from ablate import extract_json_obj, load_json  # noqa: E402

JUDGE_SYSTEM = (
    "你是条件判定器。只判断下列条件在给定段落中是否成立，不做定位、不推荐节点、不给建议。\n"
    "C1：该段落只是在描写自然风景（真实的平原、风、草地、地平线等可见景物），"
    "而没有把「开阔/无根基/选择」当作处境结构来谈。\n"
    "C2：该段落把主体的变形解释为心理疾病、创伤、压抑或躯体化症状。\n"
    "C3：该段落已把冲突收束为某个具体责任人，并且冲突被解决、到此结束。\n"
    '只输出单一 JSON：{"C1":false,"C2":false,"C3":false,"why":"<=1句>"}'
)

WANT = {"P3_plain", "P3p_scenery", "P1_transform", "P1p_psychologized",
        "P2_fractal", "P2p_plotized"}
EXPECT = {
    "P3_plain": {"C1": False}, "P3p_scenery": {"C1": True},
    "P1_transform": {"C2": False}, "P1p_psychologized": {"C2": True},
    "P2_fractal": {"C3": False}, "P2p_plotized": {"C3": True},
}


def main():
    cfg = load_json(DEMO / "config.json")
    anchors = [a for a in load_json(DEMO / "anchors_lit_v1.json")["anchors"] if a["id"] in WANT]
    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s" % (ok, detail))
    if not ok:
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("judge_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)

    tally = {}
    for a in anchors:
        for r in range(3):
            user = "段落：\n%s\n\n请判定三个条件是否成立。" % a["text"]
            rep = providers.chat(cfg, JUDGE_SYSTEM, user, temperature=0.1, max_tokens=400,
                                 timeout=60, thinking="disabled")
            p = extract_json_obj(rep) or {}
            for cid, exp in EXPECT[a["id"]].items():
                got = p.get(cid)
                key = (a["id"], cid)
                tally.setdefault(key, []).append((got == exp, got, exp))
            print(" %-20s r%d  C1=%-5s C2=%-5s C3=%-5s | %s" % (
                a["id"], r, p.get("C1"), p.get("C2"), p.get("C3"), (p.get("why") or "")[:70]))
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"anchor_id": a["id"], "rep": r, "judge": p, "raw": rep},
                                   ensure_ascii=False) + "\n")
    print("\n=== 判定准确率（对照构造事实）===")
    tot = cor = 0
    for (aid, cid), rows in sorted(tally.items()):
        c = sum(1 for x in rows if x[0])
        tot += len(rows)
        cor += c
        print(" %-20s %s  期望=%-5s 实际=%s  正确 %d/%d" % (
            aid, cid, rows[0][2], [x[1] for x in rows], c, len(rows)))
    print(" 合计: %d/%d = %.1f%%" % (cor, tot, 100.0 * cor / tot if tot else 0))
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
