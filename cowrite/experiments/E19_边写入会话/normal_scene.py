# -*- coding: utf-8 -*-
import os
"""Normal CoWrite path: loaded document, call_model, empty ledger then a second stop.

Does not print the API key. Records which prompt actually reached dots3.
"""
import json
import sys
import tempfile
from pathlib import Path

APP = str(Path(__file__).resolve().parents[2] / "transplant_src" / "app")
sys.path.insert(0, APP)
sys.path.insert(0, str(Path(APP) / "v3"))

import providers  # noqa: E402
import server  # noqa: E402
import cotree  # noqa: E402

CFG = json.loads(Path(os.environ["COWRITE_CONFIG"]).read_text(encoding="utf-8"))
CFG["cotree"] = True

DOC = (
    "她把那把旧伞靠在门边，雨水顺着伞骨往下滴。\n\n"
    "走廊尽头的灯闪了两下，随后一直亮着。\n\n"
    "她在那儿站了一会儿，没有伸手。"
)

SEEN = []
_REAL = providers.chat


def _flags(system, user):
    blob = (system or "") + "\n" + (user or "")
    return {
        "system_empty": not (system or "").strip(),
        "has_workflow_steps": "请严格按 WORKFLOW" in (user or ""),
        "has_fact_protocol": "交给代码核对的三行" in (user or ""),
        "has_edge_prompt": "沿那条边" in (user or ""),
        "has_no_continue": "不要续写正文" in (user or ""),
        "has_layer_mark": "[A]/[B]/[C]" in (user or ""),
        "has_umbrella": "伞骨" in blob,
        "has_lamp": "走廊" in blob,
        "has_crumb": "面包屑" in blob,
        "user": user or "",
        "system_head": (system or "")[:80],
    }


def wrapped(cfg, system, user, **kw):
    SEEN.append(_flags(system, user))
    return _REAL(cfg, system, user, **kw)


providers.chat = wrapped


def brief_card(cards):
    if not cards:
        return {}
    c = cards[0]
    return {
        "type": c.get("type"),
        "layer": c.get("layer"),
        "struct_layer": c.get("struct_layer"),
        "by": c.get("by"),
        "body": c.get("body") or "",
        "verdict": c.get("verdict"),
    }


def main():
    root = Path(tempfile.mkdtemp(prefix="cowrite_scene_"))
    cotree.SESSION = cotree.TreeSession(str(root / "ledger.jsonl"))
    server.set_doc("试篇", DOC)
    skill = server.load_skill()
    ctx = ""

    turns = [
        ("停在第三段", "她在那儿站了一会儿，没有伸手。", "走廊尽头的灯闪了两下，随后一直亮着。"),
        ("又写下一段", "她又看了一眼，还是没有动。", "她在那儿站了一会儿，没有伸手。"),
    ]
    rows = []
    for name, text, prev in turns:
        paras = server.pick_context(text, prev)
        cards = server.call_model(CFG, skill, text, "—", ctx, prev=prev, ctx_paras=paras)
        prompt = SEEN[-1]
        recs = [
            {"id": r.get("id"), "parent": r.get("parent"), "assertion": r.get("assertion"), "layer": r.get("layer")}
            for r in cotree.SESSION.records
        ]
        rows.append({
            "turn": name,
            "text": text,
            "prev": prev,
            "ctx_paras": [p.get("text") for p in paras],
            "prompt": {k: v for k, v in prompt.items() if k != "user"},
            "user": prompt["user"],
            "card": brief_card(cards),
            "ledger": recs,
        })

    # Two stored sentences, nothing armed. Normal server never calls arm_parent.
    cotree.SESSION = cotree.TreeSession(str(root / "siblings.jsonl"))
    cotree.SESSION._append({
        "id": "addr-0001", "assertion": "雨水顺着伞骨往下滴",
        "parent": None, "term": "伞骨", "layer": "B",
    })
    cotree.SESSION._append({
        "id": "addr-0002", "assertion": "面包屑还在桌沿",
        "parent": None, "term": "面包屑", "layer": "B",
    })
    text = "她在那儿站了一会儿，没有伸手。"
    prev = "走廊尽头的灯闪了两下，随后一直亮着。"
    cards = server.call_model(
        CFG, skill, text, "—", ctx, prev=prev,
        ctx_paras=server.pick_context(text, prev))
    prompt = SEEN[-1]
    rows.append({
        "turn": "两条枝都在账本里，没有指定父边",
        "text": text,
        "prev": prev,
        "prompt": {k: v for k, v in prompt.items() if k != "user"},
        "user": prompt["user"],
        "card": brief_card(cards),
        "ledger": [
            {"id": r.get("id"), "parent": r.get("parent"), "assertion": r.get("assertion")}
            for r in cotree.SESSION.records
        ],
    })

    out = Path(__file__).resolve().parent / "normal_scene_out.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for row in rows:
        p = row["prompt"]
        print("---", row["turn"])
        print("workflow", p["has_workflow_steps"], "fact", p["has_fact_protocol"],
              "edge", p["has_edge_prompt"], "nocont", p["has_no_continue"],
              "umbrella", p["has_umbrella"], "lamp", p["has_lamp"], "crumb", p["has_crumb"])
        print("body:", (row["card"].get("body") or "")[:180].replace("\n", " / "))
        print("ledger:", row["ledger"])


if __name__ == "__main__":
    main()
