# -*- coding: utf-8 -*-
import os
"""Production Cowrite: unarmed prompt must match cotree-off; armed turn sends one sentence."""
import json
import sys
import tempfile
from pathlib import Path

APP = os.environ["COWRITE_APP"]
sys.path.insert(0, APP)
import providers  # noqa: E402
import server  # noqa: E402

CFG = json.loads(Path(APP, "config.json").read_text(encoding="utf-8"))
CFG.pop("cotree", None)

DOC = (
    "她把那把旧伞靠在门边，雨水顺着伞骨往下滴。\n\n"
    "走廊尽头的灯闪了两下，随后一直亮着。\n\n"
    "她在那儿站了一会儿，没有伸手。"
)
TEXT = "她在那儿站了一会儿，没有伸手。"
PREV = "走廊尽头的灯闪了两下，随后一直亮着。"


def main():
    import cotree
    root = Path(tempfile.mkdtemp(prefix="prod_scene_"))
    server.set_doc("试篇", DOC)
    skill = server.load_skill()
    paras = server.pick_context(TEXT, PREV)
    seen = {}
    real = providers.chat

    def grab(cfg, system, user, **kw):
        seen["system"] = system or ""
        seen["user"] = user or ""
        return "[B]\n这一处停在伸手之前。灯还亮着，她没有去碰。"

    providers.chat = grab
    server.providers.chat = grab
    cotree.SESSION = cotree.TreeSession(str(root / "off.jsonl"))
    off = dict(CFG)
    off["cotree"] = False
    server.call_model(off, skill, TEXT, "—", "", prev=PREV, ctx_paras=paras)
    off_user, off_system = seen["user"], seen["system"]

    cotree.SESSION = cotree.TreeSession(str(root / "on.jsonl"))
    cotree.SESSION._append({
        "id": "addr-0001", "assertion": "雨水顺着伞骨往下滴",
        "parent": None, "term": "伞骨", "layer": "B",
    })
    cotree.SESSION._append({
        "id": "addr-0002", "assertion": "面包屑还在桌沿",
        "parent": None, "term": "面包屑", "layer": "B",
    })
    on = dict(CFG)
    on["cotree"] = True
    server.call_model(on, skill, TEXT, "—", "", prev=PREV, ctx_paras=paras)
    same = seen["user"] == off_user and seen["system"] == off_system

    providers.chat = real
    server.providers.chat = real
    cards_unarmed = server.call_model(on, skill, TEXT, "—", "", prev=PREV, ctx_paras=paras)
    cotree.SESSION.arm_parent("addr-0001")
    cards_armed = server.call_model(on, skill, TEXT, "—", "", prev=PREV, ctx_paras=paras)

    def body(cards):
        if not cards:
            return ""
        return cards[0].get("body") or ""

    out = {
        "use_v3": bool(server.USE_V3),
        "prompt_same_when_unarmed": same,
        "off_has_no_continue": "不要续写" in off_user or "不要续写" in off_system,
        "unarmed_has_edge": "沿那条边" in seen["user"] if False else "沿那条边" in (off_user),
        "armed_body": body(cards_armed),
        "unarmed_body": body(cards_unarmed),
        "unarmed_type": (cards_unarmed[0].get("type") if cards_unarmed else ""),
        "armed_type": (cards_armed[0].get("type") if cards_armed else ""),
        "ledger": [
            {"id": r.get("id"), "parent": r.get("parent"), "assertion": r.get("assertion")}
            for r in cotree.SESSION.records
        ],
    }
    # The grab() leftover `seen` is the unarmed stub call. Re-check armed by the live reply only.
    out["unarmed_reply_has_crumb"] = "面包屑" in out["unarmed_body"]
    out["unarmed_reply_has_umbrella"] = "伞骨" in out["unarmed_body"]
    out["armed_reply_has_umbrella"] = "伞骨" in out["armed_body"]
    out["armed_reply_has_crumb"] = "面包屑" in out["armed_body"]
    Path(__file__).resolve().parent / "prod_scene_out.json".write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "ledger"}, ensure_ascii=False, indent=1))
    print("ledger", out["ledger"])


if __name__ == "__main__":
    main()
