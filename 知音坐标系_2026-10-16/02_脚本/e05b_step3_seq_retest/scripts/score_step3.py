#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E05b Step3 post-score: HARD capped + instrument-honest + DRAFT same-address uptake.

Reads a run_v2 jsonl. Writes summary.md + decision.json.
Never invents hits when rows are missing / API failed.
Does NOT freeze Arm-B, claim 知音 proven, or close E7.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

S14 = "S14_shared_stop"
S20 = "S20_zhiyin_align"
S13 = "S13_compressed_deixis"

UPTAKE_HINTS = re.compile(
    r"(互认|同址|共停|内外|融合|说到一块儿|确认对方|同一停|共享地址|mutual|same.?address)",
    re.I,
)


def load_rows(path: Path):
    rows, meta = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        if o.get("type") == "meta":
            meta = o
            continue
        if "anchor_id" in o:
            rows.append(o)
    return meta, rows


def frac(k, n):
    return "%d/%d" % (k, n) if n else "0/0"


def score_anchor(row, arm="covered"):
    reps = row.get("arms", {}).get(arm, [])
    n = len(reps)
    s14 = s20 = s13 = dual = exact_any = 0
    js = []
    uptake_votes = []
    details = []
    for i, rep in enumerate(reps):
        rec = rep.get("rec") or {}
        sc = rep.get("score") or {}
        nodes = list(rec.get("nodes") or [])
        ns = set(nodes)
        rat = str(rec.get("rationale") or "")
        has14, has20, has13 = S14 in ns, S20 in ns, S13 in ns
        if has14:
            s14 += 1
        if has20:
            s20 += 1
        if has13:
            s13 += 1
        if has14 and has20:
            dual += 1
        if sc.get("exact_set"):
            exact_any += 1
        j = sc.get("jaccard")
        if isinstance(j, (int, float)):
            js.append(j)
        # DRAFT same-address uptake heuristic (scoring caliber only; not auth freeze)
        if has14 and has20:
            u = "yes"
        elif has14 or has20:
            u = "unclear" if UPTAKE_HINTS.search(rat) else "no"
        else:
            u = "unclear" if UPTAKE_HINTS.search(rat) else "no"
        uptake_votes.append(u)
        details.append({
            "rep": i + 1,
            "nodes": nodes,
            "jaccard": j,
            "exact_set": bool(sc.get("exact_set")),
            "rationale": rat[:240],
            "same_address_uptake_rep": u,
        })
    # aggregate uptake
    if uptake_votes.count("yes") >= 2:
        uptake = "yes"
    elif uptake_votes.count("no") == n and n > 0:
        uptake = "no"
    else:
        uptake = "unclear"
    mean_j = (sum(js) / len(js)) if js else None
    return {
        "n_reps": n,
        "S14_hits": frac(s14, n),
        "S20_hits": frac(s20, n),
        "S13_hits": frac(s13, n),
        "dual_stop_S14_S20": frac(dual, n),
        "S14_n": s14, "S20_n": s20, "S13_n": s13, "dual_n": dual,
        "exact_set_any": bool(exact_any),
        "exact_set_count": exact_any,
        "mean_jaccard_HARD": mean_j,
        "same_address_uptake": uptake,
        "reps": details,
    }


def sentry_s14(row, arm="covered"):
    reps = row.get("arms", {}).get(arm, [])
    n = len(reps)
    k = sum(1 for rep in reps if S14 in set((rep.get("rec") or {}).get("nodes") or []))
    return k, n, frac(k, n)


def decide(e05b, e05a_ot, x01_ot, api_ok):
    """PASS/FAIL/INC per DRAFT; never FAIL on exact=0 alone."""
    if not api_ok or e05b["n_reps"] < 1:
        return "INC", "API/样本不足，无实跑数字；禁止编造。", "待补"
    dual_n, n = e05b["dual_n"], e05b["n_reps"]
    uptake = e05b["same_address_uptake"]
    # overtrigger note does not alone veto PASS, but can force INC if bad
    ot_bad = (e05a_ot[0] >= 2 and e05a_ot[1] >= 3) or (x01_ot[0] >= 2 and x01_ot[1] >= 3)

    channel_alive = (dual_n >= 2) or (uptake == "yes") or (
        e05b["S14_n"] >= 2 and e05b["S20_n"] >= 2
    )
    channel_dead = (dual_n == 0 and uptake == "no"
                    and e05b["S14_n"] <= 1 and e05b["S20_n"] >= 1
                    and e05b["S13_n"] == 0)

    if channel_alive and not ot_bad:
        return ("PASS",
                "同址摄取/双停通道可见（仪器诚实）；HARD exact 不单独否证。"
                "副作用栏可接受或未恶化到 INC。仍不冻 Arm-B；不宣称知音整体已证；不关 E7。",
                "补全")
    if channel_alive and ot_bad:
        return ("INC",
                "通道迹象存在，但 E05a/X01 的 S14 过触发恶化 → 记 INC／副作用；仍不冻。",
                "待补")
    if channel_dead:
        return ("FAIL",
                "持续 S20 吸收／无法点到共享停层；非仅凭 exact=0。"
                "仍不宣称知音否证整体；E7 仍开。",
                "待补")
    return ("INC",
            "通道迹象与吸收并存，或同址摄取 unclear；不足以 PASS/FAIL。",
            "待补")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--ts", default="")
    ap.add_argument("--host-note", default="")
    ap.add_argument("--api-ok", choices=["true", "false", "auto"], default="auto")
    args = ap.parse_args()

    jsonl = Path(args.jsonl)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = args.ts or datetime.now().strftime("%Y%m%d_%H%M%S")

    if not jsonl.exists():
        decision = {
            "schema": "E05b_Step3_decision_v1",
            "ts": ts,
            "verdict": "INC",
            "verdict_reason": "jsonl missing; API likely failed. DO NOT invent numbers.",
            "api_ok": False,
            "gates": {
                "exact0_alone_is_not_channel_fail": True,
                "freeze_ArmB": False,
                "claim_zhiyin_proven": False,
                "close_E7": False,
                "E05b_status": "待补",
            },
        }
        (out_dir / ("decision_E05b_Step3_%s.json" % ts)).write_text(
            json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / ("summary_E05b_Step3_%s.md" % ts)).write_text(
            "# E05b Step3 · API/文件缺失 · INC\n\n无 jsonl。**禁止编造数字。**\n",
            encoding="utf-8")
        print("INC: missing jsonl")
        return 2

    meta, rows = load_rows(jsonl)
    by = {r["anchor_id"]: r for r in rows}
    e05b_row = by.get("E05b_alignment_confirmation")
    e05a_row = by.get("E05a_huaxing_theory_monologue")
    x01_row = by.get("X01_dialogue_register_label_paraphrase_s07")

    api_ok = True
    if args.api_ok == "false":
        api_ok = False
    elif args.api_ok == "auto":
        api_ok = bool(e05b_row) and bool((e05b_row.get("arms") or {}).get("covered"))

    e05b = score_anchor(e05b_row) if e05b_row else {
        "n_reps": 0, "S14_hits": "0/0", "S20_hits": "0/0", "S13_hits": "0/0",
        "dual_stop_S14_S20": "0/0", "S14_n": 0, "S20_n": 0, "S13_n": 0, "dual_n": 0,
        "exact_set_any": False, "exact_set_count": 0, "mean_jaccard_HARD": None,
        "same_address_uptake": "unclear", "reps": [],
    }
    e05a_ot = sentry_s14(e05a_row) if e05a_row else (0, 0, "0/0")
    x01_ot = sentry_s14(x01_row) if x01_row else (0, 0, "0/0")

    verdict, reason, e05b_status = decide(e05b, e05a_ot, x01_ot, api_ok)

    decision = {
        "schema": "E05b_Step3_decision_v1",
        "experiment": "E05b_mutual_recognition_retest_sequential_Steps1-2",
        "ts": ts,
        "host_note": args.host_note,
        "trunk_used": (meta or {}).get("trunk", "trunk_v2_covered_gloss_s14_s27.json"),
        "draft_scoring": "S14_clue2_same_address_uptake_DRAFT",
        "verdict": verdict,
        "verdict_reason": reason,
        "instrument_honest": {
            "E05b": {
                "n_reps": e05b["n_reps"],
                "S14_hits": e05b["S14_hits"],
                "S20_hits": e05b["S20_hits"],
                "S13_hits": e05b["S13_hits"],
                "dual_stop_S14_S20": e05b["dual_stop_S14_S20"],
                "mean_jaccard_HARD": e05b["mean_jaccard_HARD"],
                "exact_set_any": e05b["exact_set_any"],
                "exact_set_count": e05b["exact_set_count"],
                "same_address_uptake": e05b["same_address_uptake"],
                "j_ceiling_note": "3-node gold × HARD 1-2 → J≤2/3; exact=0 under HARD ≠ channel fail",
                "reps": e05b["reps"],
            },
            "sentry": {
                "E05a_S14_overtrigger": e05a_ot[2],
                "X01_S14_overtrigger": x01_ot[2],
            },
        },
        "gates": {
            "exact0_alone_is_not_channel_fail": True,
            "freeze_ArmB": False,
            "claim_zhiyin_proven": False,
            "close_E7": False,
            "E05b_status": e05b_status,
        },
        "forbidden_claims_echo": [
            "DO NOT freeze Arm-B into auth B",
            "DO NOT claim 知音 overall proven",
            "DO NOT close E7",
            "DO NOT invent numbers if API fails",
        ],
        "api_ok": api_ok,
        "source_jsonl": str(jsonl.name),
        "notes": "Step2 DRAFT = scoring caliber only; auth trunk unchanged.",
    }

    dec_path = out_dir / ("decision_E05b_Step3_%s.json" % ts)
    dec_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    mj = e05b["mean_jaccard_HARD"]
    mj_s = ("%.3f" % mj) if isinstance(mj, (int, float)) else "—"
    md = []
    md.append("# 实验摘要 · E05b 互认复测 Step3 · %s" % ts)
    md.append("")
    md.append("> **地位**：实跑摘要 · 仪器诚实并列 · DRAFT 同址摄取评分口径 · **≠** 冻 Arm-B／v3 · **≠** 关 E7 · **≠** 宣称知音已证")
    md.append("> **verdict**：`%s` · E05b 状态：`%s` · api_ok=%s" % (verdict, e05b_status, api_ok))
    md.append("")
    md.append("## 判定理由")
    md.append("")
    md.append(reason)
    md.append("")
    md.append("## 仪器诚实表（E05b covered）")
    md.append("")
    md.append("| 列 | 值 |")
    md.append("|----|----|")
    md.append("| n_reps | %d |" % e05b["n_reps"])
    md.append("| S14 hits | %s |" % e05b["S14_hits"])
    md.append("| S20 hits | %s |" % e05b["S20_hits"])
    md.append("| S13 hits | %s |" % e05b["S13_hits"])
    md.append("| dual-stop S14+S20 | %s |" % e05b["dual_stop_S14_S20"])
    md.append("| mean Jaccard (HARD 1–2) | %s |" % mj_s)
    md.append("| exact_set any | %s |" % e05b["exact_set_any"])
    md.append("| same_address_uptake (DRAFT) | %s |" % e05b["same_address_uptake"])
    md.append("| J 天花板注 | 3-node gold × HARD 1–2 → J≤2/3 |")
    md.append("| Gate | exact=0 under HARD ≠ channel fail |")
    md.append("")
    md.append("## 副作用哨兵")
    md.append("")
    md.append("| 锚 | S14 出现（过触发观察） |")
    md.append("|----|------------------------|")
    md.append("| E05a (gold 无 S14) | %s |" % e05a_ot[2])
    md.append("| X01 (gold=S27) | %s |" % x01_ot[2])
    md.append("")
    md.append("## 逐 rep（E05b）")
    md.append("")
    for r in e05b["reps"]:
        md.append("- rep%d: nodes=`%s` J=%s exact=%s uptake=%s" % (
            r["rep"], ",".join(r["nodes"]) or "(空)", r["jaccard"], r["exact_set"],
            r["same_address_uptake_rep"]))
        if r["rationale"]:
            md.append("  - rationale: %s" % r["rationale"].replace("\n", " "))
    md.append("")
    md.append("## 锁（再钉）")
    md.append("")
    md.append("- 授权 trunk = auth B（v2+F3 · S14 demote）· **未改**")
    md.append("- Arm-B／v3／v4 = **不冻**")
    md.append("- E7 = **仍开**")
    md.append("- 知音整体 = **不宣称已证**")
    md.append("- 本页只服务 E05b 互认通道「待补→补全？」在点名口径下的判定")
    md.append("")
    md.append("## 回传文件")
    md.append("")
    md.append("1. 本 summary md")
    md.append("2. `%s`" % dec_path.name)
    md.append("3. 对应 jsonl")
    md.append("")
    md.append("*score_step3.py · Asia/Shanghai*")
    md.append("")

    sum_path = out_dir / ("summary_E05b_Step3_%s.md" % ts)
    sum_path.write_text("\n".join(md), encoding="utf-8")
    print("wrote", sum_path)
    print("wrote", dec_path)
    print("verdict=%s E05b_status=%s" % (verdict, e05b_status))
    return 0 if api_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
