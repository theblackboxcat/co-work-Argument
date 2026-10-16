# -*- coding: utf-8 -*-
import os
"""One live turn: arm one of two branches, speak, then the next prompt follows the written edge."""
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "transplant_src" / "app" / "v3"))
import cotree  # noqa: E402

CFG = json.loads(Path(os.environ["COWRITE_CONFIG"]).read_text(encoding="utf-8"))


def chat(user):
    payload = {
        "model": CFG.get("model") or "dots3-note-prev",
        "messages": [{"role": "user", "content": user}],
        "max_tokens": 400,
        "temperature": 0.3,
        "thinking": {"type": "disabled"},
        "system": "",
    }
    req = urllib.request.Request(
        (CFG.get("base_url") or "http://note3-prev-api.askdiandian.com").rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": CFG["api_key"], "anthropic-version": "2023-06-01"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()


def main():
    root = Path(tempfile.mkdtemp(prefix="e19_"))
    s = cotree.TreeSession(str(root / "ledger.jsonl"))
    s._append({"id": "addr-0001", "assertion": "雨水顺着伞骨往下滴", "parent": None, "term": "伞骨", "layer": "B"})
    s._append({"id": "addr-0002", "assertion": "面包屑还在桌沿", "parent": None, "term": "面包屑", "layer": "B"})
    s.arm_parent("addr-0001")
    prompt = s.parent_turn_prompt("她在那儿站了一会儿，没有伸手。")
    raw = chat(prompt)
    spoken = s.finish(raw, author_text="她在那儿站了一会儿，没有伸手。")
    nxt = s.parent_turn_prompt("她又在那儿站了一会儿。")
    out = {
        "withhold": spoken.withhold,
        "parent": spoken.parent,
        "reply_has_parent": "伞骨" in raw,
        "reply_has_sibling": "面包屑" in raw,
        "next_has_parent": "伞骨" in nxt,
        "next_has_sibling": "面包屑" in nxt,
        "raw": raw,
    }
    Path(__file__).resolve().parent / "out.json".write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "raw"}, ensure_ascii=False))
    print(raw[:300])


if __name__ == "__main__":
    main()
