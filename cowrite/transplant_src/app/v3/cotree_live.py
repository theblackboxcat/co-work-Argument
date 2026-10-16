# -*- coding: utf-8 -*-
"""对改过的 call_model 发真实 dots3 请求。密钥只从本机既有配置读入，不写入结果。"""
import json
import os
import sys
import tempfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
os.environ.pop("COWRITE_V3", None)

CFG_SRC = os.environ["COWRITE_CONFIG"]


def main():
    cfg = json.load(open(CFG_SRC, encoding="utf-8"))
    if not (cfg.get("api_key") or "").strip():
        print("NO_KEY")
        return 2
    cfg = {
        "base_url": cfg.get("base_url"),
        "model": cfg.get("model"),
        "api_key": cfg.get("api_key"),
        "api": cfg.get("api") or "anthropic-messages",
        "cotree": True,
    }
    import cotree
    import providers
    import server

    ledger = os.path.join(tempfile.mkdtemp(prefix="cotree_live_"), "ledger.jsonl")
    cotree.SESSION = cotree.TreeSession(ledger)
    raws = []
    real = providers.chat

    def wrapped(c, system, user, **kw):
        text = real(c, system, user, **kw)
        raws.append({"chars": len(text or ""), "text": text})
        return text

    server.providers.chat = wrapped
    turns = [
        ("窗外的雨还在下。她想起母亲也有一把这样的伞。", ""),
        ("这一把伞骨断了一根，她一直没修。", "窗外的雨还在下。她想起母亲也有一把这样的伞。"),
    ]
    rows = []
    for i, (text, prev) in enumerate(turns, 1):
        cards = server.call_model(cfg, "", text, "—", "", prev=prev, delegate=True)
        card = (cards or [{}])[0]
        raw = raws[-1]["text"] if raws else ""
        pub = card.get("cotree") or {}
        rows.append({
            "turn": i,
            "author": text,
            "raw": raw,
            "card_type": card.get("type"),
            "by": card.get("by"),
            "verdict": card.get("verdict"),
            "title": card.get("title"),
            "body": card.get("body"),
            "struct_layer": card.get("struct_layer") or pub.get("struct_layer"),
            "reason": pub.get("reason") or card.get("body"),
            "verified": pub.get("verified"),
            "rejected": pub.get("rejected"),
            "licensed": pub.get("licensed"),
            "stripped": pub.get("stripped"),
            "address": pub.get("address"),
            "parent": pub.get("parent"),
            "stop": providers.last_stop(),
        })
        layer = (pub.get("struct_layer") or "").replace("⊘", "SILENT")
        print("TURN", i, card.get("type"), card.get("by"),
              "layer", layer, "raw_chars", len(raw or ""))
        partial = os.path.join(os.path.dirname(__file__), "cotree_live_out.json")
        blob = json.dumps(rows, ensure_ascii=False, indent=2)
        if cfg["api_key"] in blob:
            blob = blob.replace(cfg["api_key"], "[redacted]")
        open(partial, "w", encoding="utf-8").write(blob)
    out = os.path.join(os.path.dirname(__file__), "cotree_live_out.json")
    blob = json.dumps(rows, ensure_ascii=False, indent=2)
    if cfg["api_key"] in blob:
        blob = blob.replace(cfg["api_key"], "[redacted]")
    open(out, "w", encoding="utf-8").write(blob)
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        msg = str(e)
        print("LIVE_FAIL", type(e).__name__, msg.encode("ascii", "replace").decode()[:300])
        sys.exit(1)
