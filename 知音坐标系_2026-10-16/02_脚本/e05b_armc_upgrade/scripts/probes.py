# -*- coding: utf-8 -*-
"""Arm-C Turn2 中性探针（设计 §2 · 三问合一轮）。不得含节点名／gold 同源词。"""
import re

PROBE_SYSTEM = (
    "你是对话阅读助手。你只读下面这段文字本身，回答三个问题。"
    "不要使用任何外部分类体系或编号。\n"
    "(a) 接话：后一位说话人有没有接住前一位指的东西？有的话，原文逐字引用接话那一句；没有就填「无」。\n"
    "(b) 同一处：两人（如果有两人）指的是不是同一件事／同一处？用自由文本说是什么；不是就说明各指什么。\n"
    "(c) 性质：这段是 1=双方确实认出了对方所指，2=只是重复同一个标签／术语，还是 3=单方独白？只选一个数字，给一句理由。\n"
    '只输出单一 JSON，不要任何其他文字：'
    '{"a_uptake_quote":"<原文逐字或无>","b_same_thing":"yes|no","b_free_text":"<自由文本>",'
    '"c_kind":1,"c_reason":"<一句>"}'
)

def probe_user(text):
    return "段落：\n%s\n\n请回答三个问题并输出规定 JSON。" % text

BANNED_WORDS = ["共停", "知音", "对齐", "假对齐", "S14", "S20", "shared_stop", "zhiyin"]
BANNED_ID_RE = re.compile(r"S\d{2}")

def assert_neutral():
    blob = PROBE_SYSTEM + probe_user("")
    hits = [w for w in BANNED_WORDS if w in blob]
    if hits or BANNED_ID_RE.search(blob):
        raise SystemExit("FATAL: probe not neutral, banned=%s id=%s" % (hits, bool(BANNED_ID_RE.search(blob))))
    return True
