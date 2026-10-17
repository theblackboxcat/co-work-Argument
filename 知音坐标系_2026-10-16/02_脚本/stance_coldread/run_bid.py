#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""态度层 · 双向出价扫描臂（bid-arm）
条件 full（整场）× 读者 bare（不带结构）× 轮次 r1/r2 × repeat 3 = 6 次调用。

与上一枪（态度层冷读）的关键差别：探针**不预设方向**。
旧探针问「后一位有没有接住前一位」——单向预设；本臂问「有没有人递出需要对方回应的东西」，
谁递的不指定。这样才可能区分「读者看不见双向出价」与「探针没问双向出价」。

禁词：不在探针里出现 共停 / 知音 / 对齐 / 假对齐 / 接住（避免与 gold 节点、
gloss 及上一枪术语同源的引导）。要求标明说话人（上一枪出现过认错说话人）。
"""
from __future__ import annotations

# ---- 公开仓库版（2026-10-17）----
# 私人语料不在仓库内：dialogue/ 下只有 README_私人语料不入库.md 作占位。
# 真实转写（作者本人群聊，A=作者，B=对方）只在作者本地，不入库、不公开。
# 有授权语料者把 R_full.txt / R02.txt / R_mid.txt / R01.txt 放进 dialogue/ 才能复跑。

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from lib import providers  # noqa: E402

DIALOGUE = ROOT / "dialogue" / "R_full.txt"

SYSTEM = (
    "你在读一段两个人（A 和 B）的聊天记录。"
    "按问题如实回答。引用原文时必须逐字照抄，并标明那句话是 A 说的还是 B 说的。"
)

R1 = (
    "下面是一段两个人的聊天。\n\n"
    "请回答两个问题：\n\n"
    "（1）这段话里，有没有哪一句是说话人**递给对方的**——也就是说话人把自己的一个感受、"
    "判断或说法交出去，等着对方回应一下？如果有，请逐字引用那一句，并标明是 A 说的还是 B 说的。"
    "可以不止一处，请把你找到的都列出来。\n\n"
    "（2）对你列出的每一处，对方是怎么回应的？请逐字引用对方回应的那一句。"
    "如果对方没有直接回应它，就引用对方接下来实际说的那一句，"
    "并说明这一句和前面递过来的那件事是不是在同一件事上。"
)

R2 = (
    "在你上面列出的那些地方里，有没有哪一处的回应，和递过来的那件事对不上、或者岔开了？"
    "如果有，指出是哪一处、差在哪。如果你觉得都对得上，就照直说都对得上。"
)

# 第二枪：同一问题**分别点名问 A 和 B**。不提示 A 递了什么，只是把 A 也列为可能的递出方。
# 用来区分：开放扫描下 0/3 认出 A 的递出，究竟是「看不见」还是「没往那边看」。
R1_BOTH = (
    "下面是一段两个人的聊天。\n\n"
    "请分别就两个人回答：\n\n"
    "（1）**A 这边**：A 有没有哪一句是递给 B 的——也就是 A 把自己的一个感受、判断或说法交出去，"
    "等着 B 回应一下？如果有，请逐字引用那一句，并标明是 A 说的。\n\n"
    "（2）**B 这边**：B 有没有哪一句是递给 A 的？同样，如果有，请逐字引用那一句，并标明是 B 说的。\n\n"
    "（3）对你列出的每一处，对方是怎么回应的？请逐字引用对方回应的那一句。"
    "如果对方没有直接回应它，就引用对方接下来实际说的那一句，"
    "并说明这一句和前面递过来的那件事是不是在同一件事上。"
)

PARAMS = dict(temperature=0.2, max_tokens=1600, thinking="disabled")

# 引文提取：中文/英文引号内的内容
QUOTE_RE = re.compile(r"[「『“\"'‘]([^」』”\"'’]{4,80})[」』”\"'’]")

# 方向判定：条目里出现的说话人标记
SPEAKER_RE = re.compile(r"\b([AB])\b")

# 「对不上 / 岔开」类标记，只用于粗筛，不作判定
MISMATCH_HINTS = re.compile(r"(对不上|岔开|不是同一件|不在同一|没接|未接|没有回应|搁|落空|滑过去|错位|跑题)", re.I)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def extract_quotes(text: str):
    return [q.strip() for q in QUOTE_RE.findall(text or "")]


def verbatim_hits(quotes, corpus: str):
    """引文能否在原文里逐字找到（去首尾空白后比对）。"""
    ok, bad = [], []
    for q in quotes:
        if q and q in corpus:
            ok.append(q)
        else:
            bad.append(q)
    return ok, bad


def direction_of(snippet: str):
    """从条目文本里猜说话人标记：返回 'A'/'B'/'?'。"""
    m = SPEAKER_RE.search(snippet or "")
    return m.group(1) if m else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--probe", choices=["open", "both"], default="both")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("DOTS3_API_KEY", "").strip()
    if not key and not args.dry_run:
        print("ERROR: DOTS3_API_KEY 未设置", file=sys.stderr)
        return 2

    if not DIALOGUE.exists():
        sys.exit("私人语料不在公开仓库内（缺 dialogue/R_full.txt）。见 dialogue/README_私人语料不入库.md。")
    corpus = DIALOGUE.read_text(encoding="utf-8")
    cfg = {"provider": "dots3", "api_key": key or "dryrun"}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = ("MOCK_" if args.dry_run else "") + args.probe + "_" + ts

    # preflight：调用预算 = 1 条件 x 1 读者 x 2 轮 x repeat
    planned = 2 * args.repeat
    budget = 6
    if planned > budget:
        print("ERROR: planned_calls=%d > budget=%d" % (planned, budget))
        return 2
    print("preflight_ok probe=%s planned_calls=%d budget=%d dialogue_sha=%s…"
          % (args.probe, planned, budget, sha256(DIALOGUE)[:12]))

    raw_path = ROOT / "out" / ("bid_raw_%s.jsonl" % tag)
    rows = []

    def call(system, user):
        if args.dry_run:
            return "（MOCK）" + user[:40], "end_turn"
        text = providers.chat(cfg, system, user, timeout=args.timeout, **PARAMS)
        return text, providers.last_stop().get("reason", "")

    for rep in range(1, args.repeat + 1):
        R1_USE = R1 if args.probe == "open" else R1_BOTH
        r1, s1 = call(SYSTEM, R1_USE + "\n\n===== 聊天记录 =====\n" + corpus)
        r2, s2 = call(SYSTEM, R1_USE + "\n\n===== 聊天记录 =====\n" + corpus
                      + "\n\n===== 你上一轮的回答 =====\n" + r1 + "\n\n" + R2)
        q1_ok, q1_bad = verbatim_hits(extract_quotes(r1), corpus)
        q2_ok, q2_bad = verbatim_hits(extract_quotes(r2), corpus)
        rows.append({
            "rep": rep,
            "r1": {"text": r1, "stop": s1, "quotes_ok": q1_ok, "quotes_bad": q1_bad},
            "r2": {"text": r2, "stop": s2, "quotes_ok": q2_ok, "quotes_bad": q2_bad},
            "r2_mismatch_hint": bool(MISMATCH_HINTS.search(r2 or "")),
        })
        print("[rep%d] r1 stop=%s len=%d q_ok=%d q_bad=%d | r2 stop=%s len=%d q_ok=%d q_bad=%d"
              % (rep, s1, len(r1), len(q1_ok), len(q1_bad), s2, len(r2), len(q2_ok), len(q2_bad)))

    with raw_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "meta", "ts": ts, "experiment": "attitude_bid_arm_bidirectional",
            "mock": bool(args.dry_run), "repeat": args.repeat,
            "planned_calls": planned, "budget": budget,
            "dialogue_sha256": sha256(DIALOGUE), "params": PARAMS,
            "reader": "bare", "cond": "full",
        }, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # readings（模型原文，原样保存）
    md_path = ROOT / "out" / ("bid_readings_%s.md" % tag)
    out = ["# 态度层 · 双向出价扫描臂 · 读者原文（%s）" % tag, "",
           "> 条件 full（整场）· 读者 bare（不带结构）· repeat=%d · 探针不预设方向" % args.repeat,
           "> 模型输出原样保存，未作任何改写。", ""]
    for r in rows:
        out.append("## rep%d" % r["rep"])
        out.append("")
        out.append("### r1 · stop=%s" % r["r1"]["stop"])
        out.append("")
        out.append(r["r1"]["text"])
        out.append("")
        out.append("### r2（追问） · stop=%s" % r["r2"]["stop"])
        out.append("")
        out.append(r["r2"]["text"])
        out.append("")
    md_path.write_text("\n".join(out), encoding="utf-8")

    # screen（粗筛：只做引文逐字校验与方向计数，不判对错）
    scr = {
        "NOTE": "COARSE SCREEN ONLY · 只做引文逐字校验与说话人方向计数；不判对错、无 pass/fail。"
                "最终判读由作者读 bid_readings 的自由文本完成。",
        "tag": tag,
        "n_calls": planned,
        "budget": budget,
        "reps": [{
            "rep": r["rep"],
            "r1_quotes_verbatim": len(r["r1"]["quotes_ok"]),
            "r1_quotes_not_found": r["r1"]["quotes_bad"],
            "r2_quotes_verbatim": len(r["r2"]["quotes_ok"]),
            "r2_quotes_not_found": r["r2"]["quotes_bad"],
            "r2_mismatch_hint": r["r2_mismatch_hint"],
            "stop": [r["r1"]["stop"], r["r2"]["stop"]],
        } for r in rows],
    }
    scr_path = ROOT / "out" / ("bid_screen_%s.json" % tag)
    scr_path.write_text(json.dumps(scr, ensure_ascii=False, indent=2), encoding="utf-8")

    print("wrote", raw_path.name)
    print("wrote", md_path.name)
    print("wrote", scr_path.name)
    print("zip -j bid_results_%s.zip out/bid_raw_%s.jsonl out/bid_readings_%s.md out/bid_screen_%s.json"
          % (tag, tag, tag, tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
