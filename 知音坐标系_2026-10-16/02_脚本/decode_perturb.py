#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解码扰动实验结果：把匿名/重排后的 id 映射回原始节点，并列出「模型当时看到的标签」。

判读要点：
  anon_id        : 只去掉 id 字面 → 若输出仍语义正确，说明不依赖 id 字面
  shuffled_label : label 重排 → 若输出节点的「展示 label」与锚语义吻合、而「原 label」不吻合，
                   说明模型跟着展示标签走（拓扑未纠正）
  anon_shuffled  : id 字面与标签语义同时剥离，只剩拓扑 → 输出若崩为随机，则拓扑不承载语义
"""
import json
import glob
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent
trunk = json.load(open(DEMO / "trunk_v0.json"))
orig = {n["id"]: {"label": n.get("label", ""), "gloss": n.get("gloss", ""),
                  "parent": n.get("parent"), "layer": n.get("layer")} for n in trunk["nodes"]}
ids_sorted = sorted(orig)
anon_map = {"n%02d" % (i + 1): oid for i, oid in enumerate(ids_sorted)}

anchors = {a["id"]: a for a in json.load(open(DEMO / "anchors_lit_v1.json"))["anchors"]}


def load_run(view):
    fs = sorted(glob.glob(str(DEMO / "runs" / ("probe2_%s_*.jsonl" % view))))
    if not fs:
        return None
    meta = None
    rows = []
    for line in open(fs[-1], encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "meta":
            meta = r
        else:
            rows.append(r)
    return meta, rows, fs[-1]


for view in ("anon_id", "shuffled_label", "anon_shuffled", "normal"):
    got = load_run(view)
    if not got:
        continue
    meta, rows, path = got
    tf = meta.get("transform", {})
    print("\n" + "=" * 96)
    print("VIEW = %s   (%s)" % (view, Path(path).name))
    print("=" * 96)
    for r in rows:
        aid = r["anchor_id"]
        note = anchors.get(aid, {}).get("construct_note", "")
        for arm, reps in r["arms"].items():
            for i, rep in enumerate(reps):
                disp = []
                for nid in rep["nodes"]:
                    if view.startswith("anon"):
                        oid = anon_map.get(nid, nid)
                    else:
                        oid = nid
                    o = orig.get(oid, {})
                    # 模型当时看到的标签
                    if view in ("shuffled_label", "anon_shuffled"):
                        sh = tf.get("shuffle", {}).get(oid, {})
                        shown = sh.get("shown_label", "?")
                    else:
                        shown = o.get("label", "?")
                    disp.append("%s｜原:%s｜见:%s" % (nid, o.get("label", "?")[:14], shown[:14]))
                print(" %-22s %-6s r%d  %s" % (aid, arm, i, "  ;;  ".join(disp) or "(空)"))
        print("   note: %s" % note)
