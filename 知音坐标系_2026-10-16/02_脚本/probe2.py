#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe2 · 关键判别点的重复验证 + 表示扰动

repeat  : 对指定锚 × 臂 × N 次采样，检验稳定性（单次结果可能是噪声）
perturb : 打破表达的统计一致性（M6 原则的转译）
    anon_id        : id 换成 n01..n27（保留 label 与拓扑）→ 检验是否靠 id 字面
    shuffled_label : label 在节点间随机重排（拓扑不变）  → 若输出跟着错配 label 走，
                     则模型只读 label、拓扑无约束 → 树作为拓扑不成立
    no_gloss       : 去掉释义（保留 id/label/parent/layer/边）→ 检验 gloss 是否制造字面捷径
"""
import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from ablate import (ARM_SYSTEM, BARE_SYSTEM, build_views, extract_json_obj,  # noqa: E402
                    load_json, norm_edge)


def load_trunk(args):
    trunk = load_json(args.trunk)
    extra = load_json(args.parent_edges)
    ex = extra.get("edges", extra) if isinstance(extra, dict) else extra
    have = {(e.get("from"), e.get("to"), e.get("kind")) for e in trunk.get("edges", [])}
    trunk = dict(trunk)
    trunk["edges"] = list(trunk.get("edges", [])) + [e for e in ex
                                                     if (e.get("from"), e.get("to"), e.get("kind")) not in have]
    return trunk


def transform(trunk, mode, seed=7):
    t = dict(trunk)
    t["nodes"] = [dict(n) for n in trunk["nodes"]]
    info = {"mode": mode, "seed": seed}
    if mode == "anon_id":
        ids = sorted({n["id"] for n in t["nodes"]})
        m = {old: "n%02d" % (i + 1) for i, old in enumerate(ids)}
        for n in t["nodes"]:
            n["id"] = m[n["id"]]
            if n.get("parent"):
                n["parent"] = m.get(n["parent"], n["parent"])
        for e in t["edges"]:
            e["from"] = m.get(e["from"], e["from"])
            e["to"] = m.get(e["to"], e["to"])
        info["map"] = m
    elif mode == "shuffled_label":
        labels = [n.get("label", "") for n in t["nodes"]]
        glosses = [n.get("gloss", "") for n in t["nodes"]]
        rnd = random.Random(seed)
        idx = list(range(len(labels)))
        rnd.shuffle(idx)
        orig = {}
        for i, j in enumerate(idx):
            orig[t["nodes"][i]["id"]] = {"orig_label": labels[i], "shown_label": labels[j],
                                         "orig_gloss": glosses[i], "shown_gloss": glosses[j]}
        for i, j in enumerate(idx):
            t["nodes"][i]["label"] = labels[j]
            t["nodes"][i]["gloss"] = glosses[j]
        info["shuffle"] = orig
        info["shuffled"] = any(orig[k]["orig_label"] != orig[k]["shown_label"] for k in orig)
    elif mode == "no_gloss":
        for n in t["nodes"]:
            n.pop("gloss", None)
    elif mode == "anon_shuffled":
        # 先匿名 id（去掉 id 字面线索）
        ids0 = sorted({n["id"] for n in t["nodes"]})
        m = {old: "n%02d" % (i + 1) for i, old in enumerate(ids0)}
        for n in t["nodes"]:
            n["id"] = m[n["id"]]
            if n.get("parent"):
                n["parent"] = m.get(n["parent"], n["parent"])
        for e in t["edges"]:
            e["from"] = m.get(e["from"], e["from"])
            e["to"] = m.get(e["to"], e["to"])
        info["map"] = m
        # 再重排 label+gloss（去掉标签语义线索）→ 唯一可用信息只剩拓扑
        labels = [n.get("label", "") for n in t["nodes"]]
        glosses = [n.get("gloss", "") for n in t["nodes"]]
        rnd = random.Random(seed)
        idx = list(range(len(labels)))
        rnd.shuffle(idx)
        orig = {}
        for i, j in enumerate(idx):
            orig[t["nodes"][i]["id"]] = {"shown_label": labels[j], "shown_gloss": glosses[j]}
        for i, j in enumerate(idx):
            t["nodes"][i]["label"] = labels[j]
            t["nodes"][i]["gloss"] = glosses[j]
        info["shuffle"] = orig
    return t, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEMO / "config.json"))
    ap.add_argument("--trunk", default=str(DEMO / "trunk_v0.json"))
    ap.add_argument("--parent-edges", default=str(DEMO / "trunk_v1_parent_edges.json"))
    ap.add_argument("--anchors", default=str(DEMO / "anchors_lit_v1.json"))
    ap.add_argument("--mode", default="repeat", choices=["repeat", "perturb"])
    ap.add_argument("--view-mode", default="normal",
                    choices=["normal", "anon_id", "shuffled_label", "no_gloss", "anon_shuffled"])
    ap.add_argument("--arms", default="A_whitelist,D_full")
    ap.add_argument("--only", default="", help="逗号分隔的 anchor id 子集")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    cfg = load_json(args.config)
    trunk = load_trunk(args)
    trunk, info = transform(trunk, args.view_mode)
    ids = sorted({n["id"] for n in trunk["nodes"]})
    allowed = set(ids)
    allowed_edges = {e for e in (norm_edge(x) for x in trunk["edges"]) if e}
    views = build_views(trunk)
    anchors = load_json(args.anchors)["anchors"]
    if args.only:
        want = {x.strip() for x in args.only.split(",")}
        anchors = [a for a in anchors if a["id"] in want]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s | view=%s | anchors=%d | arms=%s | repeat=%d"
          % (ok, args.view_mode, len(anchors), ",".join(arms), args.repeat))
    if not ok:
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("probe2_%s_%s.jsonl" % (args.view_mode, ts))
    out.parent.mkdir(exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "meta", "mode": args.mode, "view_mode": args.view_mode,
                            "arms": arms, "repeat": args.repeat, "transform": info,
                            "ts": ts}, ensure_ascii=False) + "\n")

    lab_of = {n["id"]: n.get("label", "") for n in trunk["nodes"]}
    orig_lab = {n["id"]: n.get("label", "") for n in load_trunk(args)["nodes"]}
    for a in anchors:
        row = {"anchor_id": a["id"], "arms": {}}
        for arm in arms:
            reps = []
            for r in range(args.repeat):
                user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                        % (views[arm], json.dumps(ids, ensure_ascii=False), a["text"]))
                rep = providers.chat(cfg, ARM_SYSTEM[arm], user, temperature=0.2,
                                     max_tokens=700, timeout=args.timeout, thinking="disabled")
                p = extract_json_obj(rep)
                nodes, edges, off = [], [], []
                if isinstance(p, dict):
                    nodes = [x for x in (p.get("nodes") or []) if isinstance(x, str) and x in allowed]
                    for x in p.get("edges") or []:
                        ne = norm_edge(x)
                        if ne is None:
                            continue
                        (edges if ne in allowed_edges else off).append(x)
                reps.append({"nodes": nodes, "edges": edges, "off": off,
                             "rationale": (p or {}).get("rationale_short", "")})
            row["arms"][arm] = reps
            shown = ["%s(%s)" % (n, lab_of.get(n, "")) for rp in reps for n in [tuple(rp["nodes"])]]
            print("[%s][%s] %s" % (a["id"], arm, " | ".join(
                "%s" % (",".join(rp["nodes"]),) for rp in reps)))
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("\nwrote: %s" % out)
    if args.view_mode == "shuffled_label":
        print("\n=== label 重排映射（id: 原 label -> 展示 label）===")
        for k in sorted(info["shuffle"])[:30]:
            v = info["shuffle"][k]
            print(" %-28s %s  ->  %s" % (k, v["orig_label"], v["shown_label"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
