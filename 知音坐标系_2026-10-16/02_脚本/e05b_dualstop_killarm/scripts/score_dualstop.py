#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E05b dual-stop kill-arm scorer.

PASS: dual-stop ≥2/3 on E05b
FAIL: dual-stop 0/3 and uptake == no
INC:  dual 1/3 or mixed / unclear

Sentry: report S14 AND S20 overtrigger on E05a/X01
(规则草案_哨兵口径扩S20). Sentry does NOT veto PASS for this arm.
Never invent numbers. Does not freeze Arm-B / claim 知音 / close E7.
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
    js, uptake_votes, details = [], [], []
    for i, rep in enumerate(reps):
        rec = rep.get("rec") or {}
        sc = rep.get("score") or {}
        nodes = list(rec.get("nodes") or [])
        ns = set(nodes)
        rat = str(rec.get("rationale") or "")
        # also peek raw.rationation_short if rationale empty
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


def sentry_counts(row, arm="covered"):
    """Return S14 and S20 overtrigger counts + false-align exclusion flag (X01)."""
    reps = row.get("arms", {}).get(arm, []) if row else []
    n = len(reps)
    k14 = k20 = excl = 0
    for rep in reps:
        rec = rep.get("rec") or {}
        nodes = set(rec.get("nodes") or [])
        rat = str(rec.get("rationale") or "")
        if S14 in nodes:
            k14 += 1
        if S20 in nodes:
            k20 += 1
        if FALSE_ALIGN_EXCL.search(rat):
            excl += 1
    return {
        "n": n,
        "S14_n": k14, "S20_n": k20,
        "S14": frac(k14, n), "S20": frac(k20, n),
        "false_align_exclusion_reps": excl,
    }


def decide(e05b, api_ok):
    """Kill-arm gates: dual≥2/3 PASS; dual0+uptake no FAIL; else INC."""
    if not api_ok or e05b["n_reps"] < 1:
        return "INC", "API/样本不足，无实跑数字；禁止编造。", "待补"
    dual_n, n = e05b["dual_n"], e05b["n_reps"]
    uptake = e05b["same_address_uptake"]
    # ≥2/3
    if n >= 3 and dual_n >= 2:
        return ("PASS",
                "dual-stop ≥2/3：授权 B 下过程(S14)+结果(S20)同 rep 共现。"
                "E05b 可主张通道在授权口径下可共现（仍是一条切片 ≠ 知音整体已证）。"
                "哨兵 S14/S20 另栏；不因此自动冻 Arm-B／关 E7。",
                "补全候选")
    if dual_n == 0 and uptake == "no":
        return ("FAIL",
                "dual-stop 0/3 且 uptake 无改善；加压未挤出共现。",
                "待补")
    return ("INC",
            "dual-stop=%s 或 uptake=%s（信号混杂／不足 2/3）；不足以 PASS/FAIL。"
            % (e05b["dual_stop_S14_S20"], uptake),
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

    empty = {
        "n_reps": 0, "S14_hits": "0/0", "S20_hits": "0/0", "S13_hits": "0/0",
        "dual_stop_S14_S20": "0/0", "S14_n": 0, "S20_n": 0, "S13_n": 0, "dual_n": 0,
        "exact_set_any": False, "exact_set_count": 0, "mean_jaccard_HARD": None,
        "same_address_uptake": "unclear", "reps": [],
    }

    if not jsonl.exists():
        decision = {
            "schema": "E05b_dualstop_kill_decision_v1",
            "ts": ts,
            "verdict": "INC",
            "verdict_reason": "jsonl missing; API likely failed. DO NOT invent numbers.",
            "api_ok": False,
            "gates": {
                "PASS_dual_ge_2_of_3": True,
                "freeze_ArmB": False,
                "claim_zhiyin_proven": False,
                "close_E7": False,
                "E05b_status": "待补",
            },
        }
        (out_dir / ("decision_E05b_dualstop_%s.json" % ts)).write_text(
            json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / ("summary_E05b_dualstop_%s.md" % ts)).write_text(
            "# E05b dual-stop 杀臂 · API/文件缺失 · INC\n\n无 jsonl。**禁止编造数字。**\n",
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

    e05b = score_anchor(e05b_row) if e05b_row else dict(empty)
    e05a_s = sentry_counts(e05a_row)
    x01_s = sentry_counts(x01_row)

    verdict, reason, e05b_status = decide(e05b, api_ok)

    decision = {
        "schema": "E05b_dualstop_kill_decision_v1",
        "experiment": "E05b_dualstop_kill_arm_authB_uptake_pressure",
        "ts": ts,
        "host_note": args.host_note,
        "trunk_used": (meta or {}).get("trunk", "trunk_v2_covered_gloss_s14_s27.json"),
        "prompt_mode": "authB_covered_plus_dualstop_uptake_pressure",
        "ctrl_included": False,
        "ctrl_note": "CTRL (Step3-style prompt) skipped to keep API cost ~9 calls; baseline = prior Step3 INC dual 0/3",
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
                "rule": "草案_哨兵口径扩S20_DRAFT — report S14 AND S20; never claim clean from S14-only",
                "E05a": {
                    "gold": "S03_only",
                    "S14_overtrigger": e05a_s["S14"],
                    "S20_overtrigger": e05a_s["S20"],
                },
                "X01": {
                    "gold": "S27_false_alignment",
                    "S14_overtrigger": x01_s["S14"],
                    "S20_overtrigger": x01_s["S20"],
                    "false_align_exclusion_reps": x01_s["false_align_exclusion_reps"],
                },
                "note": "S20-stable on negatives = freeze-talk blocker later; does not veto this arm PASS",
            },
        },
        "gates": {
            "PASS_rule": "dual_stop >= 2/3",
            "FAIL_rule": "dual_stop == 0/3 AND uptake == no",
            "INC_rule": "dual 1/3 or mixed",
            "exact0_alone_is_not_channel_fail": True,
            "freeze_ArmB": False,
            "claim_zhiyin_proven": False,
            "close_E7": False,
            "E05b_status": e05b_status,
        },
        "forbidden_claims_echo": [
            "DO NOT freeze Arm-B into auth B from this run alone",
            "DO NOT claim 知音 overall proven",
            "DO NOT close E7",
            "DO NOT invent numbers if API fails",
            "DO NOT claim sentry clean from S14-only",
        ],
        "api_ok": api_ok,
        "source_jsonl": str(jsonl.name),
        "baseline_ref": "Step3 INC 20261017_142455 dual-stop 0/3 on auth B",
    }

    dec_path = out_dir / ("decision_E05b_dualstop_%s.json" % ts)
    dec_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    mj = e05b["mean_jaccard_HARD"]
    mj_s = ("%.3f" % mj) if isinstance(mj, (int, float)) else "—"
    md = []
    md.append("# 实验摘要 · E05b dual-stop 杀臂 · %s" % ts)
    md.append("")
    md.append("> **突破向** · auth B + dual-stop 摄取加压 · **≠** 冻 Arm-B · **≠** 关 E7 · **≠** 知音整体已证")
    md.append("> **verdict**：`%s` · E05b：`%s` · api_ok=%s · CTRL=跳过" % (verdict, e05b_status, api_ok))
    md.append("")
    md.append("## 判定理由")
    md.append("")
    md.append(reason)
    md.append("")
    md.append("## 主靶 E05b（covered）")
    md.append("")
    md.append("| 列 | 值 |")
    md.append("|----|----|")
    md.append("| dual-stop S14+S20 | **%s** |" % e05b["dual_stop_S14_S20"])
    md.append("| S14 / S20 / S13 | %s / %s / %s |" % (e05b["S14_hits"], e05b["S20_hits"], e05b["S13_hits"]))
    md.append("| uptake (DRAFT) | %s |" % e05b["same_address_uptake"])
    md.append("| meanJ HARD | %s |" % mj_s)
    md.append("| exact_set any | %s |" % e05b["exact_set_any"])
    md.append("")
    md.append("## 哨兵（S14 **与** S20 · 扩口径）")
    md.append("")
    md.append("| 锚 | gold | S14 过触发 | S20 过触发 | 附 |")
    md.append("|----|------|------------|------------|-----|")
    md.append("| E05a | S03 | %s | %s | — |" % (e05a_s["S14"], e05a_s["S20"]))
    md.append("| X01 | S27 | %s | %s | false_align_excl reps=%d |" % (
        x01_s["S14"], x01_s["S20"], x01_s["false_align_exclusion_reps"]))
    md.append("")
    md.append("禁止仅凭 S14=0 宣称「哨兵干净」。")
    md.append("")
    md.append("## 逐 rep（E05b）")
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
    md.append("*score_dualstop.py · Asia/Shanghai*")
    md.append("")

    sum_path = out_dir / ("summary_E05b_dualstop_%s.md" % ts)
    sum_path.write_text("\n".join(md), encoding="utf-8")
    print("wrote", sum_path)
    print("wrote", dec_path)
    print("verdict=%s dual=%s E05b_status=%s" % (verdict, e05b["dual_stop_S14_S20"], e05b_status))
    return 0 if api_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
