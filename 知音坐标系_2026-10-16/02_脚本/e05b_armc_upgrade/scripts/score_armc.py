#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arm-C 升级评分。判定只看 Turn2；Turn1 定位数字另列、不进判定。
mutual = c_kind==1 且 (a) 引文在锚原文中逐字可找到（规范化：去首尾引号/空白，比较时去除所有空白）。
预登记（设计 §4）：
  PASS: E05b mutual ≥2/3 且 X01 c_kind==2 ≥2/3 且 E05a mutual ≤1/3
  FAIL: E05b mutual ≤1/3，或无判别（任一负样本 mutual 次数 ≥ E05b mutual 次数）
  INC : 其他
不编造数字；不冻任何东西；不关 E7。"""
import argparse, json, re
from pathlib import Path

S14, S20 = "S14_shared_stop", "S20_zhiyin_align"
IDS = {"E05b": "E05b_alignment_confirmation", "E05a": "E05a_huaxing_theory_monologue",
       "X01": "X01_dialogue_register_label_paraphrase_s07"}
QUOTE_STRIP = "「」『』“”\"'‘’《》 \t\r\n"
WS = re.compile(r"\s+")


def quote_valid(q, text):
    q = str(q or "").strip().strip(QUOTE_STRIP)
    if not q or q in ("无", "none", "None", "无。"):
        return False, "none"
    if WS.sub("", q) in WS.sub("", text):
        return True, "verbatim"
    return False, "not_found"


def c_kind(p):
    try:
        return int(str(p.get("c_kind")).strip()[0])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--out-scores", required=True)
    ap.add_argument("--out-summary", required=True)
    a = ap.parse_args()
    texts = {x["id"]: x["text"] for x in json.loads(Path(a.anchors).read_text(encoding="utf-8"))["anchors"]}
    gold = {}
    reps = {k: [] for k in IDS}
    meta, n_calls = {}, None
    for line in Path(a.raw).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get("type") == "meta":
            meta = o; continue
        if o.get("type") == "end":
            n_calls = o.get("n_calls"); continue
        short = next((k for k, v in IDS.items() if v == o["anchor_id"]), None)
        if short:
            reps[short].append(o); gold[short] = set(o.get("gold_nodes") or [])

    per, t1 = {}, {}
    for k, rs in reps.items():
        n = len(rs); mutual = kind1 = kind2 = kind3 = qv = 0; rows = []
        s14 = s20 = dual = 0; js = []
        for o in rs:
            p = o["turn2"].get("parsed") or {}
            ck = c_kind(p)
            ok, why = quote_valid(p.get("a_uptake_quote"), texts.get(o["anchor_id"], ""))
            m = (ck == 1 and ok)
            mutual += m; qv += ok
            kind1 += ck == 1; kind2 += ck == 2; kind3 += ck == 3
            rows.append({"rep": o["rep"], "c_kind": ck, "c_reason": p.get("c_reason"),
                         "a_uptake_quote": p.get("a_uptake_quote"), "quote_valid": ok, "quote_check": why,
                         "mutual": m, "b_same_thing": p.get("b_same_thing"),
                         "b_free_text_FOR_AUTHOR_MAPPING": p.get("b_free_text"),
                         "parse_ok": bool(p)})
            ns = set(o["turn1"].get("nodes") or [])
            s14 += S14 in ns; s20 += S20 in ns; dual += (S14 in ns and S20 in ns)
            u = ns | gold.get(k, set())
            js.append(len(ns & gold.get(k, set())) / len(u) if u else 0.0)
        per[k] = {"n": n, "mutual_n": mutual, "quote_valid_n": qv,
                  "c_kind_counts": {"1_mutual_recognition": kind1, "2_label_repeat": kind2, "3_monologue": kind3},
                  "reps": rows}
        t1[k] = {"S14": "%d/%d" % (s14, n), "S20": "%d/%d" % (s20, n), "dual": "%d/%d" % (dual, n),
                 "any_S14_or_S20": "%d/%d" % (sum(1 for o in rs if {S14, S20} & set(o["turn1"].get("nodes") or [])), n),
                 "meanJ_HARD": round(sum(js) / len(js), 3) if js else None}

    complete = all(per[k]["n"] == 3 for k in IDS) and all(r["parse_ok"] for k in IDS for r in per[k]["reps"])
    b, x, e = per["E05b"]["mutual_n"], per["X01"]["c_kind_counts"]["2_label_repeat"], per["E05a"]["mutual_n"]
    neg_max = max(per["E05a"]["mutual_n"], per["X01"]["mutual_n"])
    if not complete:
        verdict, reason = "INC", "样本不全或 Turn2 解析失败；不编造。"
    elif b >= 2 and x >= 2 and e <= 1:
        verdict, reason = "PASS", "E05b mutual %d/3 · X01 标签复读 %d/3 · E05a mutual %d/3 → 引出且可判别。" % (b, x, e)
    elif b <= 1 or neg_max >= b:
        verdict, reason = "FAIL", "E05b mutual %d/3；负样本 mutual 最高 %d/3 → 引不出或判别不出。" % (b, neg_max)
    else:
        verdict, reason = "INC", "E05b mutual %d/3 · X01 标签复读 %d/3 · E05a mutual %d/3 → 部分判别。" % (b, x, e)

    scores = {"schema": "E05b_ArmC_upgrade_scores_v1", "meta": meta, "n_calls_logged": n_calls,
              "verdict": verdict, "verdict_reason": reason,
              "rule": {"PASS": "E05b mutual>=2/3 AND X01 c_kind==2 >=2/3 AND E05a mutual<=1/3",
                       "FAIL": "E05b mutual<=1/3 OR max(neg mutual)>=E05b mutual",
                       "INC": "otherwise", "mutual_def": "c_kind==1 AND quote verbatim in anchor"},
              "turn2_elicitation": per,
              "turn1_locate_NOT_IN_VERDICT": t1,
              "locks": {"E05b_locate_dual": "待补 regardless", "freeze": False, "close_E7": False,
                        "claim_zhiyin_proven": False}}
    Path(a.out_scores).write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")

    L = ["# 摘要 · E05b Arm-C 升级 · elicitation 判别", "",
         "> verdict **%s** · mock=%s · calls=%s" % (verdict, meta.get("mock"), n_calls), "", reason, "",
         "## Turn2（判定）", "", "| 锚 | mutual（①+引文有效） | ①/②/③ | 引文有效 |", "|--|--|--|--|"]
    for k in IDS:
        c = per[k]["c_kind_counts"]
        L.append("| %s | %d/%d | %d/%d/%d | %d/%d |" % (k, per[k]["mutual_n"], per[k]["n"], c["1_mutual_recognition"],
                 c["2_label_repeat"], c["3_monologue"], per[k]["quote_valid_n"], per[k]["n"]))
    L += ["", "## (b) 自由文本（待作者映射地址）", ""]
    for k in IDS:
        for r in per[k]["reps"]:
            L.append("- %s rep%d [same=%s] %s" % (k, r["rep"], r["b_same_thing"], r["b_free_text_FOR_AUTHOR_MAPPING"]))
    L += ["", "## Turn1 定位（不进判定）", "", "| 锚 | S14 | S20 | dual | S14∨S20 | meanJ |", "|--|--|--|--|--|--|"]
    for k in IDS:
        t = t1[k]; L.append("| %s | %s | %s | %s | %s | %s |" % (k, t["S14"], t["S20"], t["dual"], t["any_S14_or_S20"], t["meanJ_HARD"]))
    L += ["", "E05b 定位 dual 仍待补 · 不冻 · 不关 E7 · 不宣称知音已证", ""]
    Path(a.out_summary).write_text("\n".join(L), encoding="utf-8")
    print("verdict=%s %s" % (verdict, reason))


if __name__ == "__main__":
    main()
