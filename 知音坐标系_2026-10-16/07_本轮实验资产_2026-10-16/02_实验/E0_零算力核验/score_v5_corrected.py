#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正计分器 v5b（替代 run_v3_s14s20sharpen.py 内的 score()）
=========================================================

修掉的四件事，对应《核验与待裁分析 v5》§2.2 / §2.3 / §2.5：

1. **2 节点帽**（最严重）
   原口径只读 rec["nodes"]，而 BARE/COVERED_SYSTEM 都硬性要求
   「nodes 恰好 1-2 个」。后果有二：
     a. gold 含 3-4 节点的锚永不可能 exact_set —— 主效应 5 锚中只有
        E01（2 节点）可达，exact 上限 3/15 = 20%；
     b. 模型已识别的 gold 节点被挤进 edges 后彻底消失 —— 276 runs 中
        13 次（E05 covered 上 S13 有 5/15 只以边端点形式出现）。
   → 节点证据给两个口径：
       strict = nodes
       loose  = nodes ∪ {edges/offchart_edges 的 from,to}
   → 主指标从 exact_set / meanJ（均被仪器封顶）改为**微平均
     precision / recall / F1**。

2. **edge_recall 分母**
   原 score() 用全 gold 边作分母，但主效应 16 条 gold 边只有 10 条在
   trunk 中（上限 0.625）；冻结锚 meta 写明应走 Option C
   （reachable subset only），实现没做。
   → 实现 Option C：分母 = gold_edges ∩ trunk_edges。

3. **offchart 混记**
   原 offchart 把所有"不在 trunk 边表"的边都算编造，于是 gold 要求而
   trunk 缺失的边（S14→S20 parent）被记成犯规（v4 7 条、v3 3 条逐字
   命中 gold）。
   → 拆三类：
       真编造          不在 trunk 也不在 gold
       gold要求trunk缺 在 gold 但不在 trunk（不计犯规）
       拼错id          端点不在 trunk 节点表（如 S03_allegographical_*）

4. **rationale 引文无校验**
   v3 E05a covered run1 引用单元外文本「是不是……」，靠偶然发现。
   → 程序化校验：rationale 中 ≥3 字的引文片段必须能在锚文本中定位。

另加 §0 预检（D1 还原的前提验证，全部零算力）：
   - E05 完整锚是否在五个 runs 文件中都在（拆分是新增而非替换）；
   - MAIN 5 锚的 gold 是否跨版本逐字一致、且与 FROZEN 锚文件一致。

主效应分母按 D1 还原口径 = E01–E04 + E05（5 锚）。

用法：
  python3 score_v5_corrected.py --pkg <134/137包> --v4pkg <v4三件套目录>
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

MAIN = [
    "E01_huaxing_fragments_merge",
    "E02_tesolve_wilderness_plain",
    "E03_fractal_horror_struct_trap",
    "E04_interpretive_vs_plot_ending",
    "E05_huaxing_singularity_shared_stop",
]
ANCHOR_FNAME = "anchors_external_FROZEN_yunjiu_2026-10-15.json"

# rationale 引文抽取：『』「」"" '' 六类（v2/v3/v4 实际用了中文单双引号），≥3 字
QUOTE_RES = [
    re.compile(r"『([^』]{3,})』"),
    re.compile(r"「([^」]{3,})」"),
    re.compile(r"\"([^\"]{3,})\""),
    re.compile(r"'([^']{3,})'"),
]
DROP = re.compile(r"[\s…\.、，。！？；：\-—]+")

_ATEXT_CACHE = {}


def norm(s):
    return DROP.sub("", s or "")


def quotes(text):
    out = []
    for r in QUOTE_RES:
        out += [m.group(1) for m in r.finditer(text or "")]
    return out


def quote_located(q, atext):
    """引文定位校验。
    「化形/合体」是同时引用两个词干的合法引用式 → 按 / 拆分，每个词干都须在锚文本中。
    返回 'ok'（全部定位）/ 'part'（部分定位）/ 'miss'（完全越界）。
    """
    parts = [p for p in re.split(r"[/／|｜]", q) if p.strip()]
    if not parts:
        parts = [q]
    na = norm(atext)
    found = [norm(p) in na for p in parts]
    if all(found):
        return "ok"
    return "part" if any(found) else "miss"


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def trunk_edges(p):
    d = json.load(open(p, encoding="utf-8"))
    # 与 run 脚本一致：norm_edge 用 frozenset，方向不检查
    return ({(frozenset((e["from"], e["to"])), e["kind"]) for e in d["edges"]},
            {n["id"] for n in d["nodes"]})


def ek(e):
    return (frozenset((e["from"], e["to"])), e["kind"])


def nodes_of(rec, loose):
    ns = set(rec.get("nodes", []))
    if loose:
        for e in rec.get("edges", []) + rec.get("offchart_edges", []):
            ns.add(e["from"])
            ns.add(e["to"])
    return ns


def gold_key(r):
    return (tuple(sorted(r["gold"]["nodes"])),
            tuple(sorted((e["from"], e["to"], e["kind"]) for e in r["gold"]["edges"])))


def _load_anchor_texts(pkg, v4):
    """载入 FROZEN 锚文件（v4 三件套里没有锚文件，回查 134 包）。"""
    if _ATEXT_CACHE:
        return _ATEXT_CACHE
    cands = [pkg / "03_锚与主干" / ANCHOR_FNAME,
             v4 / "pkg" / "03_锚与主干" / ANCHOR_FNAME,
             v4 / "03_锚与主干" / ANCHOR_FNAME]
    for c in cands:
        if c.exists():
            for x in json.load(open(c, encoding="utf-8"))["anchors"]:
                _ATEXT_CACHE[x["id"]] = (x.get("text", ""),
                                         (tuple(sorted(x["gold"]["nodes"])) if "gold" in x else None))
            break
    return _ATEXT_CACHE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--v4pkg", required=True)
    a = ap.parse_args()
    pkg, v4 = Path(a.pkg), Path(a.v4pkg)

    RUNS = [
        ("v2a", "10:28", "trunk_v2_covered",
         pkg / "02_脚本" / "runs" / "v2_20261015_102822.jsonl",
         pkg / "03_锚与主干" / "trunk_v2_covered.json"),
        ("v2b", "11:17", "trunk_v2_covered_gloss_s14_s27",
         pkg / "02_脚本" / "runs" / "v2_20261015_111753.jsonl",
         pkg / "03_锚与主干" / "trunk_v2_covered_gloss_s14_s27.json"),
        ("v2c", "13:28", "同v2b(冻结锚重跑)",
         pkg / "02_脚本" / "runs" / "v2_20261015_132811.jsonl",
         pkg / "03_锚与主干" / "trunk_v2_covered_gloss_s14_s27.json"),
        ("v3", "16:41", "trunk_v3_s14s20_sharpen_DRAFT",
         pkg / "04_原始数据_runs" / "v3_s14s20sharpen_20261015_164100.jsonl",
         pkg / "06_新包核验与续证" / "实验补报_2026-10-15" / "trunk_v3_s14s20_sharpen_DRAFT.json"),
        ("v4", "17:36", "trunk_v4_s14_narrowed_DRAFT",
         v4 / "pkg" / "v4_s14narrowed_20261015_173608.jsonl",
         v4 / "pkg" / "trunk_v4_s14_narrowed_DRAFT.json"),
    ]
    miss = [(n, str(p)) for n, _, _, p, _ in RUNS if not p.exists()]
    miss += [(n, str(p)) for n, _, _, _, p in RUNS if not p.exists()]
    if miss:
        for n, p in miss:
            print("[FATAL] 缺文件 %-4s %s" % (n, p))
        raise SystemExit(2)

    atext_map = _load_anchor_texts(pkg, v4)
    frozen_gold = {k: v[1] for k, v in atext_map.items() if v[1]}

    # ---------- §0 预检：D1 还原的前提（零算力） ----------
    print("=" * 116)
    print("§0　预检：E05 完整锚在全部 runs 文件中在场 + gold 跨版本一致（D1 还原前提）")
    print("=" * 116)
    all_rows = {}
    for name, ts, tn, rp, tp in RUNS:
        all_rows[name] = load_jsonl(rp)
    e05_in = {n: any(r.get("anchor_id") == "E05_huaxing_singularity_shared_stop"
                     for r in rows) for n, rows in all_rows.items()}
    print("E05 完整锚在场：", "，".join("%s=%s" % (n, "有" if v else "**缺**")
                                       for n, v in e05_in.items()))
    split_in = {n: any(r.get("anchor_id", "").startswith("E05a") or
                       r.get("anchor_id", "").startswith("E05b")
                       for r in rows) for n, rows in all_rows.items()}
    print("E05a/E05b 在场：", "，".join("%s=%s" % (n, "有" if v else "无")
                                       for n, v in split_in.items()),
          "（拆分锚自 v2c 起新增，从未顶替 E05）")
    gold_by_ver = {}
    for n, rows in all_rows.items():
        for r in rows:
            if r.get("anchor_id") in MAIN:
                gold_by_ver.setdefault(r["anchor_id"], {})[n] = gold_key(r)
    ok = True
    for aid in MAIN:
        vs = gold_by_ver.get(aid, {})
        ref = vs.get("v3")
        same = all(v == ref for v in vs.values())
        fz = frozen_gold.get(aid)
        fz_ok = (fz is None) or (fz == ref[0])
        if not (same and fz_ok):
            ok = False
        print("%-4s %-46s 跨版本%s 与FROZEN锚文件%s"
              % ("OK" if (same and fz_ok) else "DIFF", aid[:44],
                 "一致" if same else "**不一致**",
                 "一致" if fz_ok else "**不一致**"))
        if not same:
            for v, g in vs.items():
                if g != ref:
                    print("      %s → %s" % (v, g))
    print("结论：还原口径 5 锚 × 3 repeat = 15 runs/臂 可直接重算，无需补跑。"
          if ok else "结论：**gold 存在跨版本差异，还原前须先裁定**。")
    print()

    # ---------- 表 1：主效应（还原口径，微平均 P/R/F1 + Option C edgeR + offchart 分类） ----------
    print("=" * 116)
    print("表 1　主效应（还原口径 5 锚 × 3 repeat = 15 runs/臂）")
    print("      节点指标为微平均；edgeR 走 Option C（分母 = gold ∩ trunk）；offchart 已拆分三类")
    print("=" * 116)
    print("%-4s %-8s %-8s %-26s %-26s %-11s %-22s"
          % ("ver", "臂", "节点口径", "precision / recall / F1",
             "（原口径 exact / meanJ 对照）", "edgeR OptC", "offchart 编造/金缺/拼错id"))
    for loose_tag, loose in (("strict", False), ("loose", True)):
        for name, ts, tn, rp, tp in RUNS:
            TR, VALID = trunk_edges(tp)
            rows = all_rows[name]
            for arm in ("bare", "covered"):
                tp_ = fp = fn = 0
                ex = 0
                J = []
                er_num = er_den = 0
                off_fake = off_goldmiss = off_typo = 0
                for r in rows:
                    if r.get("type") == "meta" or not r.get("anchor_id"):
                        continue
                    if r["anchor_id"] not in MAIN:
                        continue
                    ge = {ek(e) for e in r["gold"]["edges"]}
                    gr = ge & TR
                    gn = set(r["gold"]["nodes"])
                    for x in r["arms"].get(arm, []):
                        M = nodes_of(x["rec"], loose)
                        tp_ += len(M & gn)
                        fp += len(M - gn)
                        fn += len(gn - M)
                        ex += (set(x["rec"]["nodes"]) == gn)
                        u = len(M | gn)
                        J.append(len(M & gn) / u if u else 1.0)
                        pe = {ek(e) for e in x["rec"]["edges"]}
                        er_num += len(pe & gr)
                        er_den += len(gr)
                        for e in x["rec"]["offchart_edges"]:
                            k = ek(e)
                            if k in ge:
                                off_goldmiss += 1
                            elif (e["from"] not in VALID) or (e["to"] not in VALID):
                                off_typo += 1
                            else:
                                off_fake += 1
                if tp_ + fp == 0:
                    continue
                P = tp_ / (tp_ + fp) if (tp_ + fp) else 0.0
                R = tp_ / (tp_ + fn) if (tp_ + fn) else 0.0
                F = 2 * P * R / (P + R) if (P + R) else 0.0
                print("%-4s %-8s %-8s %-26s %-26s %-11s %-22s"
                      % (name, arm, loose_tag,
                         "%.3f / %.3f / %.3f" % (P, R, F),
                         "%d/15  %.3f" % (ex, sum(J) / len(J)),
                         "%.3f" % (er_num / er_den if er_den else 0),
                         "%d / %d / %d" % (off_fake, off_goldmiss, off_typo)))
        print("-" * 116)
    print("注 1：exact / meanJ 为原口径对照（strict nodes），被 2 节点帽封顶——5 锚中仅 E01")
    print("       gold=2 节点可达，exact 上限 3/15=20%，meanJ 上限 0.700。")
    print("注 2：loose 口径把 edges 端点也算作节点证据，会把「边对但没敢写进 nodes」的")
    print("       正确识别捞回来，但也会把纯边推理的假阳性算进分子——两种口径图景不同，")
    print("       须并列阅读，不单独采信任一。")

    # ---------- 表 1b：引文定位校验（全锚口径，仪器完整性诊断） ----------
    print()
    print("=" * 116)
    print("表 1b　rationale 引文定位校验（全 10 锚 × 3 repeat 口径，与主效应分母无关）")
    print("       三段：完全定位 / 部分定位（疑似改写引文）/ 完全越界（锚文本中不存在）")
    print("=" * 116)
    for name, ts, tn, rp, tp in RUNS:
        rows = all_rows[name]
        ok_n = part_n = miss_n = 0
        bad_examples = []
        for r in rows:
            if r.get("type") == "meta" or not r.get("anchor_id"):
                continue
            at = atext_map.get(r["anchor_id"], ("", None))[0]
            for arm in ("bare", "covered"):
                for x in r["arms"].get(arm, []):
                    for q in quotes(x["rec"].get("rationale", "")):
                        st = quote_located(q, at)
                        if st == "ok":
                            ok_n += 1
                        elif st == "part":
                            part_n += 1
                            bad_examples.append(("部分", r["anchor_id"], arm, q))
                        else:
                            miss_n += 1
                            bad_examples.append(("越界", r["anchor_id"], arm, q))
        print("%-4s 引文 %-3d  完全定位 %-3d  部分定位 %-2d  完全越界 %-2d"
              % (name, ok_n + part_n + miss_n, ok_n, part_n, miss_n))
        for tag, aid, arm, q in bad_examples[:4]:
            print("       [%s] %s %s 『%s』" % (tag, aid[:40], arm, q))
        if len(bad_examples) > 4:
            print("       ……另 %d 例" % (len(bad_examples) - 4))
    print("-" * 116)
    print("注：「化形/合体」式斜杠复合引文按词干拆分，每个词干都须在锚文本中定位；")
    print("    完全越界 = 模型给不存在的文本加了引号（仪器可信度问题，非准确度问题）。")

    # ---------- 表 2：逐节点命中矩阵（loose 口径） ----------
    print()
    print("=" * 116)
    print("表 2　逐 gold 节点命中矩阵（loose 口径：nodes ∪ edges 端点）")
    print("      格式 = 命中的节点实例数 /(runs × gold 节点数)，即节点级 recall 原始计数")
    print("=" * 116)
    order = ["v2a", "v2b", "v2c", "v3", "v4"]
    GN = {}
    for aid in MAIN:
        for name, ts, tn, rp, tp in RUNS:
            for r in all_rows[name]:
                if r.get("anchor_id") == aid:
                    GN[aid] = set(r["gold"]["nodes"])
                    break
            if aid in GN:
                break
    hdr = "%-50s %-6s" % ("锚（gold 节点数）", "臂")
    for v in order:
        hdr += " %-7s" % v
    print(hdr)
    for aid in MAIN:
        gn = GN[aid]
        for arm in ("bare", "covered"):
            line = "%-50s %-6s" % ("%s (%d)" % (aid[:44], len(gn)), arm)
            for name, ts, tn, rp, tp in RUNS:
                hit = tot = 0
                for r in all_rows[name]:
                    if r.get("anchor_id") != aid:
                        continue
                    for x in r["arms"].get(arm, []):
                        tot += 1
                        hit += len(nodes_of(x["rec"], True) & gn)
                line += " %-7s" % ("%d/%d" % (hit, tot * len(gn)) if tot else "-")
            print(line)
    print("-" * 116)

    # ---------- 表 3：误停节点（非 gold）top ----------
    print()
    print("=" * 116)
    print("表 3　误停节点统计（loose 口径，模型主张了但不在该锚 gold 中的节点）")
    print("=" * 116)
    for name, ts, tn, rp, tp in RUNS:
        rows = all_rows[name]
        c = Counter()
        for r in rows:
            if r.get("type") == "meta" or r["anchor_id"] not in MAIN:
                continue
            gn = set(r["gold"]["nodes"])
            for arm in ("bare", "covered"):
                for x in r["arms"].get(arm, []):
                    for n in nodes_of(x["rec"], True) - gn:
                        c[n] += 1
        top = "、".join("%s×%d" % (k.replace("_", " ")[:22], v)
                        for k, v in c.most_common(6))
        print("%-4s 误停实例 %-3d  %s" % (name, sum(c.values()), top))


if __name__ == "__main__":
    main()
