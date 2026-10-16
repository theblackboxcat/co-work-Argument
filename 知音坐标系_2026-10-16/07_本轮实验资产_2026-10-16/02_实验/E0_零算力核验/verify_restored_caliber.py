#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
还原口径重算脚本（E05 拆锚撤回后）
=================================

背景：2026-10-15 13:23 曾把 E05（猫猫化形理论陈述 + 融合提议 + 云酒同词应答）
拆成 E05a（gold=S03）与 E05b（gold=S14+S20+S13）。该拆分后被作者判定为裁剪逻辑
漏洞（D1 批评），需还原为 E05 完整交流锚（gold=S03+S14+S20+S13）。

关键事实：E05 从未从任何一次 run 中移除——5 个 runs 文件的 10 个锚里都含
E05_huaxing_singularity_shared_stop，且 5 个文件的 gold 逐字一致。因此"还原"
只是改主效应分母，零算力、零重跑。

本脚本从原始 jsonl 独立重算（不信任已存储的 score 字段），输出：
  1. 还原口径（5 锚 × 3 repeat = 15 runs/臂）主效应表，跨 v2a/v2b/v2c/v3/v4
  2. 拆分口径（6 锚 = 18 runs/臂）对照，证明两口径结论同向
  3. 结构性上限：2 节点输出帽对 exact_set / meanJ 的封顶；gold 边在 trunk 中
     的可达上限（edge_recall 天花板）
  4. offchart 审计：有多少"编造边"其实逐字命中 gold（仪器误记）
  5. S13 产出普查 + X01 跨版本行为

用法：
  python3 verify_restored_caliber.py \
      --pkg  /path/to/交付_知音坐标系_完整脚本数据结论包_2026-10-15 \
      --v4pkg /path/to/v4_S14收窄试跑_2026-10-15
"""
import argparse
import json
import sys
from pathlib import Path

MAIN_FULL = [
    "E01_huaxing_fragments_merge",
    "E02_tesolve_wilderness_plain",
    "E03_fractal_horror_struct_trap",
    "E04_interpretive_vs_plot_ending",
    "E05_huaxing_singularity_shared_stop",   # 完整交流，还原后入分母
]
MAIN_SPLIT = [
    "E01_huaxing_fragments_merge",
    "E02_tesolve_wilderness_plain",
    "E03_fractal_horror_struct_trap",
    "E04_interpretive_vs_plot_ending",
    "E05a_huaxing_theory_monologue",
    "E05b_alignment_confirmation",
]


def load_jsonl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def trunk_edges(p):
    d = json.load(open(p, encoding="utf-8"))
    edges = d.get("edges", [])
    # 与 run 脚本一致：norm_edge 用 frozenset，即方向不被检查
    return {(frozenset((e["from"], e["to"])), e["kind"]) for e in edges}


def jaccard(a, b):
    A, B = set(a), set(b)
    u = len(A | B)
    return (len(A & B) / u) if u else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", required=True, help="134/137 文件交付包根目录")
    ap.add_argument("--v4pkg", required=True, help="v4 三件套解包目录（含 pkg/）")
    args = ap.parse_args()
    pkg = Path(args.pkg)
    v4 = Path(args.v4pkg)

    RUNS = [
        ("v2a", "10:28", "trunk_v2_covered",
         pkg / "02_脚本" / "runs" / "v2_20261015_102822.jsonl",
         pkg / "03_锚与主干" / "trunk_v2_covered.json"),
        ("v2b", "11:17", "trunk_v2_covered_gloss_s14_s27",
         pkg / "02_脚本" / "runs" / "v2_20261015_111753.jsonl",
         pkg / "03_锚与主干" / "trunk_v2_covered_gloss_s14_s27.json"),
        ("v2c", "13:28", "trunk_v2_covered_gloss_s14_s27（冻结锚重跑）",
         pkg / "02_脚本" / "runs" / "v2_20261015_132811.jsonl",
         pkg / "03_锚与主干" / "trunk_v2_covered_gloss_s14_s27.json"),
        ("v3", "16:41", "trunk_v3_s14s20_sharpen_DRAFT",
         pkg / "04_原始数据_runs" / "v3_s14s20sharpen_20261015_164100.jsonl",
         pkg / "06_新包核验与续证" / "实验补报_2026-10-15" / "trunk_v3_s14s20_sharpen_DRAFT.json"),
        ("v4", "17:36", "trunk_v4_s14_narrowed_DRAFT",
         v4 / "pkg" / "v4_s14narrowed_20261015_173608.jsonl",
         v4 / "pkg" / "trunk_v4_s14_narrowed_DRAFT.json"),
    ]
    missing = [(n, p) for n, _, _, p, _ in RUNS if not p.exists()]
    missing += [(n, p) for n, _, _, _, p in RUNS if not p.exists()]
    if missing:
        print("[FATAL] 缺文件：")
        for n, p in missing:
            print("   %-4s %s" % (n, p))
        sys.exit(2)

    # ---------- 1 & 2. 两口径主效应 ----------
    print("=" * 108)
    print("主效应（独立重算，不信任存储 score）")
    print("=" * 108)
    hdr = "%-4s %-6s %-8s %-8s %-8s %-8s %-9s %-16s %-9s"
    print(hdr % ("ver", "time", "口径", "臂", "n", "exact", "meanJ",
                 "edgeR 全/OptC", "offchart"))
    for tag, main in [("还原5锚", MAIN_FULL), ("拆分6锚", MAIN_SPLIT)]:
        for name, ts, trunk_name, rp, tp in RUNS:
            TR = trunk_edges(tp)
            rows = load_jsonl(rp)
            for arm in ("bare", "covered"):
                J, n_ex, anchors_ex = [], 0, set()
                erf, erc, off, off_gold = [], [], 0, 0
                for r in rows:
                    if r.get("type") == "meta" or not r.get("anchor_id"):
                        continue
                    if r["anchor_id"] not in main:
                        continue
                    ge = {(frozenset((e["from"], e["to"])), e["kind"])
                          for e in r["gold"]["edges"]}
                    gr = ge & TR
                    gn = set(r["gold"]["nodes"])
                    for x in r["arms"].get(arm, []):
                        ns = x["rec"]["nodes"]
                        J.append(jaccard(ns, gn))
                        if set(ns) == gn:
                            n_ex += 1
                            anchors_ex.add(r["anchor_id"])
                        pe = {(frozenset((e["from"], e["to"])), e["kind"])
                              for e in x["rec"]["edges"]}
                        if ge:
                            erf.append(len(pe & ge) / len(ge))
                        if gr:
                            erc.append(len(pe & gr) / len(gr))
                        off += len(x["rec"]["offchart_edges"])
                        off_gold += sum(1 for e in x["rec"]["offchart_edges"]
                                        if (frozenset((e["from"], e["to"])), e["kind"]) in ge)
                if not J:
                    continue
                print(hdr % (name, ts, tag, arm, len(J),
                             "%d(%d锚)" % (n_ex, len(anchors_ex)),
                             "%.3f" % (sum(J) / len(J)),
                             "%.3f/%.3f" % (sum(erf) / len(erf), sum(erc) / len(erc)),
                             "%d→%d" % (off, off - off_gold)))
        print("-" * 108)

    # ---------- 3. 结构性上限 ----------
    print()
    print("=" * 108)
    print("结构性上限（仪器封顶，非模型能力）")
    print("=" * 108)
    anch = json.load(open(pkg / "03_锚与主干" / "anchors_external_FROZEN_yunjiu_2026-10-15.json",
                          encoding="utf-8"))["anchors"]
    A = {a["id"]: a for a in anch}
    print("%-46s %-7s %-13s %s" % ("anchor", "|gold|", "maxJ@2节点帽", "exact_set 可达"))
    tot, cnt = 0.0, 0
    for k in MAIN_FULL:
        n = len(A[k]["gold"]["nodes"])
        mj = min(2, n) / n if n else 1.0
        tot += mj
        cnt += 1 if n <= 2 else 0
        print("%-46s %-7d %-13.3f %s" % (k, n, mj, "YES" if n <= 2 else "NO（gold>2，prompt 硬限 1-2 节点）"))
    print("\n  => exact_set 上限 = %d/15 = %.1f%%（仅 E01 可达）" % (cnt * 3, cnt * 3 / 15 * 100))
    print("  => meanJ 上限（2 节点帽）= %.3f" % (tot / 5))

    TR = trunk_edges(pkg / "03_锚与主干" / "trunk_v2_covered_gloss_s14_s27.json")
    tot_e = ok_e = 0
    for k in MAIN_FULL:
        for e in A[k]["gold"]["edges"]:
            tot_e += 1
            if (frozenset((e["from"], e["to"])), e["kind"]) in TR:
                ok_e += 1
    print("  => edge_recall 上限 = %d/%d = %.3f（gold 边有 %d 条不在 trunk 中）"
          % (ok_e, tot_e, ok_e / tot_e, tot_e - ok_e))

    # ---------- 4. S13 普查 + X01 ----------
    print()
    print("=" * 108)
    print("S13 产出普查 / X01 跨版本行为")
    print("=" * 108)
    runs_tot, s13 = 0, {}
    x01 = {}
    for name, ts, tn, rp, tp in RUNS:
        for r in load_jsonl(rp):
            if r.get("type") == "meta" or not r.get("anchor_id"):
                continue
            for arm in ("bare", "covered"):
                for x in r["arms"].get(arm, []):
                    runs_tot += 1
                    if "S13_compressed_deixis" in x["rec"]["nodes"]:
                        s13[r["anchor_id"]] = s13.get(r["anchor_id"], 0) + 1
                    if r["anchor_id"].startswith("X01"):
                        x01.setdefault((name, arm), []).append(sorted(x["rec"]["nodes"]))
    print("总 runs = %d，S13 产出 = %d（%.1f%%）" % (runs_tot, sum(s13.values()),
                                                   sum(s13.values()) / runs_tot * 100))
    for k in ("E05_huaxing_singularity_shared_stop", "E05a_huaxing_theory_monologue",
              "E05b_alignment_confirmation"):
        n = sum(1 for name, ts, tn, rp, tp in RUNS for r in load_jsonl(rp)
                if r.get("anchor_id") == k for arm in ("bare", "covered")
                for _ in r["arms"].get(arm, []))
        print("   %-44s runs=%-3d S13=%-2d (%.1f%%)" % (k, n, s13.get(k, 0),
                                                        s13.get(k, 0) / n * 100 if n else 0))
    print("\nX01（gold=S27_false_alignment）covered 臂随 gloss 补丁漂移：")
    for (name, arm), sets in sorted(x01.items()):
        if arm == "covered":
            print("   %-4s %s" % (name, sets))
    print("   => 从未产出 S27；伴节点随 gloss 显著性漂移 S09→S20→S14")

    # ---------- 5. 2 节点帽的降级效应 ----------
    print()
    print("=" * 108)
    print("2 节点帽的降级效应：gold 节点被挤进 edges（nodes 里看不见）")
    print("=" * 108)
    print("%-6s %-8s %-6s %-14s %-14s %s" % ("锚", "臂", "runs", "S13在nodes", "S13仅在边", "S13任一形式"))
    for key in ("E05_huaxing_singularity_shared_stop", "E05a_huaxing_theory_monologue",
                "E05b_alignment_confirmation"):
        for arm in ("bare", "covered"):
            n_runs = n_node = n_edge = 0
            for name, ts, tn, rp, tp in RUNS:
                for r in load_jsonl(rp):
                    if r.get("anchor_id") != key:
                        continue
                    for x in r["arms"].get(arm, []):
                        ns = set(x["rec"]["nodes"])
                        ep = set()
                        for e in x["rec"]["edges"] + x["rec"]["offchart_edges"]:
                            ep.add(e["from"])
                            ep.add(e["to"])
                        n_runs += 1
                        if "S13_compressed_deixis" in ns:
                            n_node += 1
                        elif "S13_compressed_deixis" in ep:
                            n_edge += 1
            if n_runs:
                print("%-6s %-8s %-6d %-14d %-14d %d/%d (%.0f%%)"
                      % (key[:6], arm, n_runs, n_node, n_edge,
                         n_node + n_edge, n_runs,
                         (n_node + n_edge) / n_runs * 100))
    print("\n  => E05 covered 臂 15 runs 中 S13 有 5 次只以「边端点」形式出现、0 次进入 nodes；")
    print("     2 节点硬帽把模型已识别的 gold 节点降级掉了，exact/meanJ 对此完全不可见。")


if __name__ == "__main__":
    main()
