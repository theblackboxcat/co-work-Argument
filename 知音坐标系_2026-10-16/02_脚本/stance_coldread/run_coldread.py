#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""态度层 · 真实对话冷读 · 外传 runner。

条件 × 读者 × 轮次（设计 §4、§6）：
  条件：full（主条件，整场 R02→R_mid→R01）；seg_R02 / seg_R_mid / seg_R01（备选，分段各读一次）
  读者：bare（只有对话）；struct（同一读者、同一问题，先给 auth B 结构 trunk 作上下文）
  轮次：r1 = 开放问题；r2 = 同一会话追问一句「请指出你说的是哪几句。」
  2 读者 × (1 整场 + 3 分段) × 2 轮 = 16 次调用；--main-only = 只跑整场 = 4 次。
  每格 1 次（设计未写 rep，按 16 次预算即 rep=1）。不重试；API 失败就停，不补数字。

key 只从环境变量 DOTS3_API_KEY 读；本包不含 key，也不写 config.json。
--dry-run（或 COLDREAD_MOCK=1）：不联网，mock 回复，校验预算、渲染全部 prompt、写 out/ 三件。
"""
import argparse, hashlib, json, os, re, sys

# ---- 公开仓库版（2026-10-17）----
# 私人语料不在仓库内：dialogue/ 下只有 README_私人语料不入库.md 作占位。
# 真实转写（作者本人群聊，A=作者，B=对方）只在作者本地，不入库、不公开。
# 有授权语料者把 R_full.txt / R02.txt / R_mid.txt / R01.txt 放进 dialogue/ 才能复跑。
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from lib import providers  # 与 E05b 系列外传包相同的 API client（逐字节拷贝）

CFG_BASE = {"provider": "dots3", "base_url": "http://note3-prev-api.askdiandian.com",
            "model": "dots3-note-prev"}
PARAMS = dict(temperature=0.2, max_tokens=1600, thinking="disabled")
BUDGET_ALL, BUDGET_MAIN = 16, 4

# ---------------------------------------------------------------- prompts（两种读者完全相同，唯一差别是 struct 多一段结构上下文）
SYSTEM = "你在读一段真实的聊天记录。用中文自由作答。"
QUESTION = "读这场对话，说说两个人在哪些地方真的接住了对方、哪些地方没有，尽量指到具体的句子。"  # 设计 §4 原句
FOLLOWUP = "请指出你说的是哪几句。"  # 设计 §4 可选第二轮原句
STRUCT_INTRO = "先给你一份坐标系（节点、层级、释义和边）作上下文：\n"

CONDITIONS = [("full", "R_full.txt"), ("seg_R02", "R02.txt"), ("seg_R_mid", "R_mid.txt"), ("seg_R01", "R01.txt")]
READERS = ["bare", "struct"]

# prompt 框架（不含对话本身与 trunk 内容）里不许出现的词（设计 §4 禁提词等）。
# 全部用 \u 转义写：本包不以字面形式携带这些词，避免向跑包的一方透露要看什么。
BANNED_IN_FRAME = ["\u786e\u8ba4", "\u5bf9\u554a", "\u6ce8\u610f\u529b", "\u5957\u8bdd", "\u9644\u548c", "\u9644\u548c\u8bcd", "\u540c\u610f", "\u8d5e\u540c", "\u5927\u8bcd", "\u4f5c\u8005", "\u5047\u8bbe", "\u77e5\u97f3", "\u5171\u5740", "\u5171\u5728", "\u7c7b\u6bd4", "\u843d\u5730", "attention", "clich\u00e9", "cliche", "\u6401\u7f6e", "\u534f\u53d8", "\u5bc6\u5c01", "\u9884\u8bfb", "\u4f5c\u8005\u5224\u65ad"]


def _require_private_dialogue(names):
    missing = [n for n in sorted(set(names)) if not (ROOT / "dialogue" / n).exists()]
    if missing:
        sys.exit("私人语料不在公开仓库内（缺 dialogue/%s）。见 dialogue/README_私人语料不入库.md。" % ", dialogue/".join(missing))


def struct_context(trunk):
    """auth B 结构视图：与 E05b 系列 run_v2.views()['covered'] 同一序列化方式。"""
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return j({"nodes": [{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                         "label": n.get("label"), "gloss": n.get("gloss")} for n in trunk["nodes"]],
              "edges": trunk.get("edges", [])})


def user_r1(reader, dialogue, ctx):
    pre = (STRUCT_INTRO + ctx + "\n\n——\n\n") if reader == "struct" else ""
    return "%s对话：\n%s\n%s" % (pre, dialogue, QUESTION)


def plan(main_only):
    conds = CONDITIONS[:1] if main_only else CONDITIONS
    return [(c, f, r) for c, f in conds for r in READERS]


def preflight(main_only, trunk_text):
    # 1) 无硬编码 key
    for p in [Path(__file__).resolve()] + list((ROOT / "lib").rglob("*.py")):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"sk-[A-Za-z0-9]{16,}", t) or re.search(r"Bearer [A-Za-z0-9._\-]{16,}", t):
            sys.exit("FATAL: key-like string in %s" % p)
    if (ROOT / "config.json").exists():
        sys.exit("FATAL: config.json 不应存在（key 只走 DOTS3_API_KEY）")
    # 2) 包内无 sealed 文件
    bad = [str(p) for p in ROOT.rglob("*") if "\u5bc6\u5c01" in p.name]
    if bad:
        sys.exit("FATAL: sealed file in pack: %s" % bad)
    # 3) prompt 框架中性
    frame = SYSTEM + QUESTION + FOLLOWUP + STRUCT_INTRO + "对话：\n"
    hits = [w for w in BANNED_IN_FRAME if w.lower() in frame.lower()]
    if hits:
        sys.exit("FATAL: prompt frame not neutral: %s" % hits)
    # 4) 预算
    n = len(plan(main_only)) * 2
    cap = BUDGET_MAIN if main_only else BUDGET_ALL
    if n != cap:
        sys.exit("FATAL: planned calls %d != budget %d" % (n, cap))
    print("preflight_ok no_hardcoded_key no_sealed_files frame_neutral planned_calls=%d budget=%d trunk_sha=%s…"
          % (n, cap, hashlib.sha256(trunk_text.encode("utf-8")).hexdigest()[:12]))
    return n, cap


def mock_reply(cond, reader, rnd):
    return ("[MOCK %s/%s/%s] 这是 dry-run 的假回复，不含任何判断。示例引用：「下午」。" % (cond, reader, rnd))


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 粗筛（只做“引用了哪几行”，不判对错、不出 verdict）
QUOTE_RE = re.compile(r"[「“\"『]([^」”\"』]{2,80})[」”\"』]")
WS = re.compile(r"\s+")


def msg_lines(dialogue):
    out = []
    for i, x in enumerate(dialogue.splitlines(), 1):
        m = re.match(r"^([AB]) (下午\d+:\d+(?:\[\?\])?)?\s*(.*)$", x)
        if m:
            content = re.sub(r"^\[引用回复[^\]]*\]\s*[:：]?\s*", "", m.group(3)).strip()
            out.append({"line": i, "speaker": m.group(1), "time": (m.group(2) or ""), "text": x, "content": content})
    return out


def cited_lines(reply, lines):
    hits = set()
    quotes = [WS.sub("", q).strip("。，、…") for q in QUOTE_RE.findall(reply or "")]
    for q in quotes:
        if len(q) < 2:
            continue
        for L in lines:
            c = WS.sub("", L["content"])
            if c and (q in c or (len(c) >= 2 and c in q)):
                hits.add(L["line"])
    return sorted(hits), len(quotes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-only", action="store_true", help="只跑主条件（整场 × 2 读者 × 2 轮 = 4 次）")
    ap.add_argument("--dry-run", action="store_true", help="不联网，mock 回复")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()
    mock = args.dry_run or os.environ.get("COLDREAD_MOCK") == "1"

    trunk_path = ROOT / "trunk" / "trunk_v2_covered_gloss_s14_s27.json"
    trunk_text = trunk_path.read_text(encoding="utf-8")
    n_plan, cap = preflight(args.main_only, trunk_text)
    _require_private_dialogue([f for _, f, _ in plan(args.main_only)])
    ctx = struct_context(json.loads(trunk_text))

    cfg = dict(CFG_BASE)
    if not mock:
        key = os.environ.get("DOTS3_API_KEY", "").strip()
        if not key:
            print("ERROR: 请先 export DOTS3_API_KEY=...")
            return 2
        cfg["api_key"] = key  # 只在内存里，不落盘
    budget_chars = providers.input_budget(dict(cfg, api_key="x"))

    ts = os.environ.get("TS") or datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "out"; out.mkdir(exist_ok=True)
    tag = ("main_" if args.main_only else "all_") + ("MOCK_" if mock else "") + ts
    f_raw = out / ("coldread_raw_%s.jsonl" % tag)
    f_read = out / ("coldread_readings_%s.md" % tag)
    f_screen = out / ("coldread_screen_%s.json" % tag)
    rend = ROOT / "rendered_prompts"; rend.mkdir(exist_ok=True)

    n_calls, stopped, recs = 0, None, []
    with f_raw.open("w", encoding="utf-8") as fr:
        fr.write(json.dumps({"type": "meta", "ts": ts, "experiment": "态度层_真实对话冷读", "mock": mock,
                             "main_only": args.main_only, "planned_calls": n_plan, "budget": cap,
                             "model": cfg["model"], "provider": cfg["provider"], "params": PARAMS,
                             "system": SYSTEM, "question": QUESTION, "followup": FOLLOWUP,
                             "trunk": trunk_path.name, "trunk_sha256": sha(trunk_text),
                             "reps_per_cell": 1, "retries": 0}, ensure_ascii=False) + "\n")
        for cond, fname, reader in plan(args.main_only):
            dialogue = (ROOT / "dialogue" / fname).read_text(encoding="utf-8")
            u1 = user_r1(reader, dialogue, ctx)
            (rend / ("%s__%s__r1.txt" % (cond, reader))).write_text(
                "=== SYSTEM ===\n%s\n\n=== USER ===\n%s\n" % (SYSTEM, u1), encoding="utf-8")
            (rend / ("%s__%s__r2.txt" % (cond, reader))).write_text(
                "=== SYSTEM ===\n%s\n\n=== USER (r1, 同上文件) ===\n…\n\n=== ASSISTANT ===\n<第一轮回复原样>\n\n=== USER ===\n%s\n"
                % (SYSTEM, FOLLOWUP), encoding="utf-8")
            rec = {"type": "cell", "condition": cond, "reader": reader, "dialogue_file": fname,
                   "dialogue_sha256": sha(dialogue), "r1_user_sha256": sha(u1), "r1_user_chars": len(u1),
                   "input_budget_chars": budget_chars}
            if stopped:
                rec["skipped"] = "前面调用失败，整轮停止：" + stopped
                recs.append(rec); fr.write(json.dumps(rec, ensure_ascii=False) + "\n"); continue
            msgs = [{"role": "user", "content": u1}]
            for rnd in ("r1", "r2"):
                if n_calls >= cap:
                    sys.exit("FATAL: budget exceeded")
                if rnd == "r2":
                    msgs = msgs + [{"role": "assistant", "content": rec["r1"]["reply"]},
                                   {"role": "user", "content": FOLLOWUP}]
                chars = sum(len(m["content"]) for m in msgs) + len(SYSTEM)
                n_calls += 1
                try:
                    if mock:
                        reply, stop = mock_reply(cond, reader, rnd), "mock"
                    else:
                        reply = providers.chat_messages(cfg, msgs, system=SYSTEM, timeout=args.timeout, **PARAMS)
                        stop = providers.last_stop().get("reason", "")
                    rec[rnd] = {"reply": reply, "stop_reason": stop, "input_chars": chars,
                                "over_input_budget": chars > budget_chars}
                except providers.ProviderError as e:
                    rec[rnd] = {"error": "%s: %s" % (type(e).__name__, e), "input_chars": chars}
                    stopped = "%s/%s/%s %s" % (cond, reader, rnd, type(e).__name__)
                    break
                print("[%s/%s/%s] chars_in=%d%s stop=%s reply_len=%d" % (cond, reader, rnd, chars,
                      (" (>%d 输入预算，记录在案)" % budget_chars) if chars > budget_chars else "", stop, len(reply)))
            recs.append(rec); fr.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fr.write(json.dumps({"type": "end", "n_calls": n_calls, "stopped": stopped}, ensure_ascii=False) + "\n")

    # readings.md：自由文本原样，给作者读（这是判读的主材料）
    md = ["# 态度层冷读 · 读者原文（%s）" % tag, "",
          "判读由作者读这里的自由文本完成；本文件不含任何评分。", "",
          "问题（r1）：%s" % QUESTION, "追问（r2）：%s" % FOLLOWUP, "",
          "n_calls=%d / budget=%d%s" % (n_calls, cap, ("  · 中途停止：" + stopped) if stopped else ""), ""]
    for r in recs:
        md.append("## %s · %s" % (r["condition"], r["reader"]))
        if r.get("skipped"):
            md += ["", "（跳过：%s）" % r["skipped"], ""]; continue
        for rnd in ("r1", "r2"):
            x = r.get(rnd)
            if not x:
                continue
            md += ["", "### %s%s" % (rnd, ("  · stop=" + x.get("stop_reason", "")) if "reply" in x else ""), ""]
            md.append(x.get("reply") if "reply" in x else "**调用失败**：" + x["error"])
        md.append("")
    f_read.write_text("\n".join(md) + "\n", encoding="utf-8")

    # screen.json：粗筛 only —— 读者用「」引号引到了哪几行。不是判定，不代表接住/没接住的对错。
    screen = {"NOTE": "COARSE SCREEN ONLY · 只统计读者用引号引到了原文哪几行（引文与原文逐字匹配）；不判对错、无 pass/fail，最终判读是作者读 readings.md 的自由文本。",
              "tag": tag, "n_calls": n_calls, "budget": cap, "stopped": stopped, "cells": []}
    for r in recs:
        fname = r["dialogue_file"]
        lines = msg_lines((ROOT / "dialogue" / fname).read_text(encoding="utf-8"))
        cell = {"condition": r["condition"], "reader": r["reader"]}
        for rnd in ("r1", "r2"):
            x = r.get(rnd) or {}
            if "reply" in x:
                hit, nq = cited_lines(x["reply"], lines)
                cell[rnd] = {"n_quotes": nq, "cited_lines": hit,
                             "cited_text": [L["text"] for L in lines if L["line"] in hit]}
        screen["cells"].append(cell)
    f_screen.write_text(json.dumps(screen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("wrote %s\nwrote %s\nwrote %s\nn_calls=%d budget=%d%s" % (f_raw, f_read, f_screen, n_calls, cap,
          (" STOPPED: " + stopped) if stopped else ""))
    print("回传（只回这三件）：\nzip -j coldread_results_%s.zip %s %s %s" % (tag, f_raw.relative_to(ROOT), f_read.relative_to(ROOT), f_screen.relative_to(ROOT)))
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
