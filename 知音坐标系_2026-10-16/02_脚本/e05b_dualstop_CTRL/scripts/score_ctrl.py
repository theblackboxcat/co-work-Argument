#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E05b dual-stop CTRL scorer — unpressured baseline vs pressurized 144249.

Purpose: separate prompt-commanded dual from structure uptake.
- Report E05b dual under CTRL
- Report X01 dual count (baseline for negative_dual_veto gate)
- Sentry S14 AND S20
- Compare table vs pressurized run 20261017_144249
Never invent numbers.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

S14 = "S14_shared_stop"
S20 = "S20_zhiyin_align"
S13 = "S13_compressed_deixis"

UPTAKE_HINTS = re.compile(
    r"(互认|同址|共停|内外|融合|说到一块儿|确认对方|同一停|共享地址|"
    r"我刚就想说|是的|mutual|same.?address)",
    re.I,
)
FALSE_ALIGN_EXCL = re.compile(r"(而非假对齐|不是假对齐|非假对齐)", re.I)

# Fixed reference from pressurized kill-arm (author-verified)
PRESS_REF = {
    "ts": "20261017_144249",
    "E05b_dual": "3/3",
    "E05b_S14": "3/3",
    "E05b_S20": "3/3",
    "E05a_S14": "0/3",
    "E05a_S20": "3/3",
    "X01_S14": "3/3",
    "X01_S20": "1/3",
    "X01_dual_reps": 1,  # rep2 S14+S20
    "false_align_exclusion_reps": 0,
}


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
    reps = row.get("arms", {}).get(arm, []) if row else []
    n = len(reps)
    s14 = s20 = s13 = dual = exact_any = 0
    js, uptake_votes, details = [], [], []
    for i, rep in enumerate(reps):
        rec = rep.get("rec") or {}
        sc = rep.get("score") or {}
        nodes = list(rec.get("nodes") or [])
        ns = set(nodes)
        rat = str(rec.get("rationale") or "")
        if not rat:
            raw = rec.get("raw")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = None
            if isinstance(raw, dict):
                rat = str(raw.get("rationation_short") or raw.get("rationale_short") or "")
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
            "dual_stop_rep": bool(has14 and has20),
        })
    if uptake_votes.count("yes") >= 2:
        uptake = "yes"
    elif n > 0 and uptake_votes.count("no") == n:
        uptake = "no"
    else:
        uptake = "unclear"
    mean_j = (sum(js) / len(js)) if js else None
    return {
        "n_reps": n,
        "S14_hits": frac(s14, n), "S20_hits": frac(s20, n), "S13_hits": frac(s13, n),
        "dual_stop_S14_S20": frac(dual, n),
        "S14_n": s14, "S20_n": s20, "S13_n": s13, "dual_n": dual,
        "exact_set_any": bool(exact_any), "exact_set_count": exact_any,
        "mean_jaccard_HARD": mean_j,
        "same_address_uptake": uptake,
        "reps": details,
    }


def sentry_counts(row, arm="covered"):
    reps = row.get("arms", {}).get(arm, []) if row else []
    n = len(reps)
    k14 = k20 = dual = excl = 0
    for rep in reps:
        rec = rep.get("rec") or {}
        nodes = set(rec.get("nodes") or [])
        rat = str(rec.get("rationale") or "")
        if S14 in nodes:
            k14 += 1
        if S20 in nodes:
            k20 += 1
        if S14 in nodes and S20 in nodes:
            dual += 1
        if FALSE_ALIGN_EXCL.search(rat):
            excl += 1
    return {
        "n": n, "S14": frac(k14, n), "S20": frac(k20, n),
        "dual_n": dual, "dual": frac(dual, n),
        "false_align_exclusion_reps": excl,
    }


def decide(e05b, x01_s, api_ok):
    """CTRL evidence reading vs pressurized 3/3."""
    if not api_ok or e05b["n_reps"] < 1:
        return ("INC", "API/样本不足；禁止编造。",
                "待补", {"prompt_command_confirmed": None, "structure_story_reopened": None})
    dual_n, n = e05b["dual_n"], e05b["n_reps"]
    # Gates relative to pressurized 3/3
    if n >= 3 and dual_n >= 2:
        return (
            "INC",
            "CTRL 下 E05b dual 仍 ≥2/3 —— 加压并非唯一原因；结构读懂叙事可重开（须人工复核哨兵）。",
            "待复核",
            {"prompt_command_confirmed": False, "structure_story_reopened": True},
        )
    if dual_n <= 1:
        # strengthens downgrade if dual 0 or 1 while press was 3/3
        conf = dual_n == 0
        return (
            "PASS_CTRL_BASELINE" if dual_n == 0 else "INC",
            (
                "CTRL dual=%s 而加压臂为 3/3 → 支持「Δ 由 dual-bias prompt 命令」；证据降权加强。"
                % e05b["dual_stop_S14_S20"]
            ),
            "待补",
            {"prompt_command_confirmed": conf or dual_n <= 1, "structure_story_reopened": False},
        )
    return ("INC", "混杂。", "待补",
            {"prompt_command_confirmed": None, "structure_story_reopened": None})


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

    empty = {
        "n_reps": 0, "S14_hits": "0/0", "S20_hits": "0/0", "S13_hits": "0/0",
        "dual_stop_S14_S20": "0/0", "S14_n": 0, "S20_n": 0, "S13_n": 0, "dual_n": 0,
        "exact_set_any": False, "exact_set_count": 0, "mean_jaccard_HARD": None,
        "same_address_uptake": "unclear", "reps": [],
    }

    if not jsonl.exists():
        decision = {
            "schema": "E05b_dualstop_CTRL_decision_v1",
            "ts": ts, "verdict": "INC",
            "verdict_reason": "jsonl missing. DO NOT invent numbers.",
            "api_ok": False,
        }
        (out_dir / ("decision_E05b_dualstop_CTRL_%s.json" % ts)).write_text(
            json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / ("summary_E05b_dualstop_CTRL_%s.md" % ts)).write_text(
            "# CTRL · missing jsonl · INC\n", encoding="utf-8")
        return 2

    meta, rows = load_rows(jsonl)
    by = {r["anchor_id"]: r for r in rows}
    e05b = score_anchor(by.get("E05b_alignment_confirmation")) if by.get("E05b_alignment_confirmation") else dict(empty)
    e05a_s = sentry_counts(by.get("E05a_huaxing_theory_monologue"))
    x01_s = sentry_counts(by.get("X01_dialogue_register_label_paraphrase_s07"))

    api_ok = True
    if args.api_ok == "false":
        api_ok = False
    elif args.api_ok == "auto":
        api_ok = e05b["n_reps"] > 0

    verdict, reason, e05b_status, flags = decide(e05b, x01_s, api_ok)

    # negative_dual_veto: for CTRL pack we RECORD baseline X01 dual;
    # the veto applies to pressurized arm narrative (already known: press X01 dual≥1).
    # If CTRL also shows X01 dual, note structure-bleed without pressure.
    negative_dual_veto = {
        "rule": "加压臂若在 X01 压出 dual → 否决「结构读懂」叙事（已用于降权加压 PASS）",
        "pressurized_X01_dual_reps": PRESS_REF["X01_dual_reps"],
        "CTRL_X01_dual": x01_s["dual"],
        "CTRL_X01_dual_n": x01_s["dual_n"],
        "pressurized_already_triggers_veto": PRESS_REF["X01_dual_reps"] >= 1,
        "CTRL_X01_dual_without_pressure": x01_s["dual_n"] >= 1,
    }

    mj = e05b["mean_jaccard_HARD"]
    decision = {
        "schema": "E05b_dualstop_CTRL_decision_v1",
        "experiment": "E05b_dualstop_CTRL_unpressured_same_batch",
        "ts": ts,
        "host_note": args.host_note,
        "trunk_used": (meta or {}).get("trunk", "trunk_v2_covered_gloss_s14_s27.json"),
        "prompt_mode": "authB_covered_NO_dualstop_bias_CTRL",
        "pressurized_ref": PRESS_REF,
        "verdict": verdict,
        "verdict_reason": reason,
        "flags": flags,
        "instrument_honest": {
            "E05b": {
                "n_reps": e05b["n_reps"],
                "S14_hits": e05b["S14_hits"],
                "S20_hits": e05b["S20_hits"],
                "S13_hits": e05b["S13_hits"],
                "dual_stop_S14_S20": e05b["dual_stop_S14_S20"],
                "mean_jaccard_HARD": mj,
                "exact_set_any": e05b["exact_set_any"],
                "same_address_uptake": e05b["same_address_uptake"],
                "reps": e05b["reps"],
            },
            "sentry": {
                "rule": "S14 AND S20 — 草案_哨兵口径扩S20",
                "E05a": {"S14_overtrigger": e05a_s["S14"], "S20_overtrigger": e05a_s["S20"],
                         "dual": e05a_s["dual"]},
                "X01": {"S14_overtrigger": x01_s["S14"], "S20_overtrigger": x01_s["S20"],
                        "dual": x01_s["dual"],
                        "false_align_exclusion_reps": x01_s["false_align_exclusion_reps"]},
            },
            "compare_vs_pressurized_144249": {
                "E05b_dual": {"CTRL": e05b["dual_stop_S14_S20"], "press": PRESS_REF["E05b_dual"]},
                "E05a_S20": {"CTRL": e05a_s["S20"], "press": PRESS_REF["E05a_S20"]},
                "X01_S14": {"CTRL": x01_s["S14"], "press": PRESS_REF["X01_S14"]},
                "X01_dual": {"CTRL": x01_s["dual"], "press_reps": PRESS_REF["X01_dual_reps"]},
            },
            "negative_dual_veto": negative_dual_veto,
        },
        "gates": {
            "CTRL_dual_ge_2_of_3_reopens_structure": True,
            "CTRL_dual_le_1_confirms_prompt_command": True,
            "freeze_ArmB": False,
            "claim_zhiyin_proven": False,
            "close_E7": False,
            "E05b_status": e05b_status,
        },
        "forbidden_claims_echo": [
            "DO NOT freeze Arm-B from CTRL alone",
            "DO NOT claim 知音 proven",
            "DO NOT close E7",
            "DO NOT invent numbers",
        ],
        "api_ok": api_ok,
        "source_jsonl": str(jsonl.name),
    }

    dec_path = out_dir / ("decision_E05b_dualstop_CTRL_%s.json" % ts)
    dec_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    mj_s = ("%.3f" % mj) if isinstance(mj, (int, float)) else "—"
    md = []
    md.append("# 实验摘要 · E05b dual-stop CTRL（无加压）· %s" % ts)
    md.append("")
    md.append("> 拆「prompt 命令双停」vs 结构摄取 · 对照加压臂 `20261017_144249` · auth B · **无** dual-bias")
    md.append("> **verdict**：`%s` · flags=%s · api_ok=%s" % (verdict, flags, api_ok))
    md.append("")
    md.append("## 判定理由")
    md.append("")
    md.append(reason)
    md.append("")
    md.append("## 对照表 · CTRL vs 加压")
    md.append("")
    md.append("| 列 | CTRL（本跑） | 加压 `144249` |")
    md.append("|----|--------------|---------------|")
    md.append("| E05b dual-stop | **%s** | **%s** |" % (e05b["dual_stop_S14_S20"], PRESS_REF["E05b_dual"]))
    md.append("| E05b S14 / S20 | %s / %s | %s / %s |" % (
        e05b["S14_hits"], e05b["S20_hits"], PRESS_REF["E05b_S14"], PRESS_REF["E05b_S20"]))
    md.append("| E05a S14 / S20 | %s / %s | %s / %s |" % (
        e05a_s["S14"], e05a_s["S20"], PRESS_REF["E05a_S14"], PRESS_REF["E05a_S20"]))
    md.append("| X01 S14 / S20 / dual | %s / %s / %s | %s / %s / %d rep |" % (
        x01_s["S14"], x01_s["S20"], x01_s["dual"],
        PRESS_REF["X01_S14"], PRESS_REF["X01_S20"], PRESS_REF["X01_dual_reps"]))
    md.append("| uptake / meanJ | %s / %s | yes / 0.667 |" % (e05b["same_address_uptake"], mj_s))
    md.append("")
    md.append("## negative_dual_veto")
    md.append("")
    md.append("- 规则：加压臂若在 X01 压出 dual → 否决「结构读懂」叙事（加压臂已触发：X01 dual ≥1 rep）。")
    md.append("- 本 CTRL 的 X01 dual = **%s**（无加压基线）。" % x01_s["dual"])
    md.append("")
    md.append("## 逐 rep（E05b CTRL）")
    md.append("")
    for r in e05b["reps"]:
        md.append("- rep%d: nodes=`%s` dual=%s J=%s uptake=%s" % (
            r["rep"], ",".join(r["nodes"]) or "(空)", r["dual_stop_rep"],
            r["jaccard"], r["same_address_uptake_rep"]))
        if r["rationale"]:
            md.append("  - rationale: %s" % r["rationale"].replace("\n", " "))
    md.append("")
    md.append("## 回传")
    md.append("")
    md.append("1. 本 summary · 2. `%s` · 3. jsonl" % dec_path.name)
    md.append("")
    md.append("*score_ctrl.py · Asia/Shanghai*")
    md.append("")

    sum_path = out_dir / ("summary_E05b_dualstop_CTRL_%s.md" % ts)
    sum_path.write_text("\n".join(md), encoding="utf-8")
    print("wrote", sum_path)
    print("wrote", dec_path)
    print("verdict=%s CTRL_dual=%s X01_dual=%s" % (verdict, e05b["dual_stop_S14_S20"], x01_s["dual"]))
    return 0 if api_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
