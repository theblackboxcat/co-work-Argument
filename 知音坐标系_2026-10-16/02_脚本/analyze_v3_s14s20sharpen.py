#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 锐化草案试跑分析：与原授权口径（v2_external_frozen_E05split）对照。
输出：逐锚 covered/bare 命中表、S14/S20 专项、主效应（新口径分母）、X01/X02 复现锚。
"""
import json
import sys
from pathlib import Path

PKG = Path("/workspace/交付_知音坐标系_完整脚本数据结论包_2026-10-15")


def load(path):
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f]
    meta = lines[0]
    rows = lines[1:]
    return meta, rows


def arm_summary(rows, arm, sel):
    """sel: anchor_id -> bool"""
    hit = ex = tot = 0
    jsum = 0.0
    er_hit = er_tot = 0
    off = 0
    for r in rows:
        if not sel(r["anchor_id"]):
            continue
        for x in r["arms"].get(arm, []):
            s = x["score"]
            tot += 1
            hit += bool(s["node_hit_any"])
            ex += bool(s["exact_set"])
            if s["jaccard"] is not None:
                jsum += s["jaccard"]
            if s["edge_evaluable"] and s["edge_recall"] is not None:
                er_tot += 1
                er_hit += (1 if s["edge_recall"] >= 0.999 else 0)
            off += s["offchart"]
    return {
        "hit": "%d/%d" % (hit, tot), "exact": "%d/%d" % (ex, tot),
        "meanJ": round(jsum / tot, 3) if tot else None,
        "edgeR_full": "%d/%d" % (er_hit, er_tot) if er_tot else "—",
        "offchart": off,
    }


def main():
    v3_path = sorted((PKG / "04_原始数据_runs").glob("v3_s14s20sharpen_*.jsonl"))[-1]
    v2_path = PKG / "04_原始数据_runs" / "v2_external_frozen_E05split_20261015_132811.jsonl"
    m3, r3 = load(v3_path)
    m2, r2 = load(v2_path)
    print("v3 file:", v3_path.name, "| trunk:", m3["trunk"], "|", m3.get("trunk_status", ""))
    print("v2 file:", v2_path.name, "| trunk:", m2["trunk"])
    print()

    # 新口径主效应分母：E01-E04 + E05a + E05b（E05 原锚 superseded，不计入）
    MAIN = lambda aid: aid in {"E01_huaxing_fragments_merge", "E02_tesolve_wilderness_plain",
                               "E03_fractal_horror_struct_trap", "E04_interpretive_vs_plot_ending",
                               "E05a_huaxing_theory_monologue", "E05b_alignment_confirmation"}
    print("== 主效应（新口径 6 锚：E01-E04+E05a+E05b）==")
    for tag, rows in (("v3", r3), ("v2", r2)):
        for arm in ("bare", "covered"):
            s = arm_summary(rows, arm, MAIN)
            print("%s %-8s hit=%-7s exact=%-7s meanJ=%-6s edgeR_full=%-6s off=%d"
                  % (tag, arm, s["hit"], s["exact"], s["meanJ"], s["edgeR_full"], s["offchart"]))
    print()

    print("== 逐锚 covered 对照（v2 -> v3，每锚 3 repeat）==")
    by2 = {r["anchor_id"]: r for r in r2}
    by3 = {r["anchor_id"]: r for r in r3}
    for aid in [r["anchor_id"] for r in r3]:
        if aid not in by2:
            continue
        def sig(row, arm):
            return ["+".join(x["rec"]["nodes"]) or "(空)" for x in row["arms"].get(arm, [])]
        g = by3[aid]["gold"]["nodes"]
        print("%-46s gold=%s" % (aid, "+".join(g)))
        for arm in ("bare", "covered"):
            s2, s3 = sig(by2[aid], arm), sig(by3[aid], arm)
            mark = "" if s2 == s3 else "  <== CHANGED"
            print("   %-8s v2: %-58s v3: %-58s%s" % (arm, " | ".join(s2), " | ".join(s3), mark))
    print()

    print("== S14/S20 专项（裁法②验证）==")
    for aid in ("E01_huaxing_fragments_merge", "E05b_alignment_confirmation",
                "E12b_context_limbo_island"):
        if aid not in by3:
            continue
        for arm in ("bare", "covered"):
            for tag, by in (("v2", by2), ("v3", by3)):
                sig = ["+".join(x["rec"]["nodes"]) or "(空)" for x in by[aid]["arms"].get(arm, [])]
                s14 = sum("S14_shared_stop" in s for s in sig)
                s20 = sum("S20_zhiyin_align" in s for s in sig)
                print("%-46s %-8s %-3s S14:%d/3 S20:%d/3  %s"
                      % (aid, arm, tag, s14, s20, " | ".join(sig)))
    print()

    print("== X01/X02 复现锚（不得破坏）==")
    for aid in ("X01_dialogue_register_label_paraphrase_s07", "X02_dialogue_register_literal_scenery"):
        if aid not in by3:
            continue
        for tag, by in (("v2", by2), ("v3", by3)):
            sig = ["+".join(x["rec"]["nodes"]) or "(空)" for x in by[aid]["arms"]["covered"]]
            print("%-46s %-3s covered: %s" % (aid, tag, " | ".join(sig)))
    print()

    print("== judge 臂（v3 vs v2）==")
    for aid in [r["anchor_id"] for r in r3]:
        if aid not in by2:
            continue
        j3 = by3[aid].get("judge", {})
        j2 = by2[aid].get("judge", {})
        k3 = ",".join("%s=%s" % (k, j3.get(k)) for k in ("J1", "J2", "J3", "J4", "J5"))
        k2 = ",".join("%s=%s" % (k, j2.get(k)) for k in ("J1", "J2", "J3", "J4", "J5"))
        mark = "" if k2 == k3 else "  <== CHANGED"
        print("%-46s v2: %-70s v3: %-70s%s" % (aid, k2, k3, mark))


if __name__ == "__main__":
    main()
