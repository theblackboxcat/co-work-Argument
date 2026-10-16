# -*- coding: utf-8 -*-
"""E12：预注册之后才调用 dots3。材料与判决规则只读 cotree_e12_prereg.json。"""
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
os.environ.pop("COWRITE_V3", None)

PREREG = os.path.join(HERE, "cotree_e12_prereg.json")
OUT = os.path.join(HERE, "cotree_e12_out.json")
CFG_SRC = os.environ["COWRITE_CONFIG"]


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, centre - margin), 3), round(min(1.0, centre + margin), 3)]


def gold_b(paragraphs, terms, index):
    cur = paragraphs[index]
    prior = "\n".join(paragraphs[:index])
    hit = [t for t in terms if t in cur and t in prior]
    return hit


def self_layer(raw):
    m = re.search(r"[\[【]\s*([ABC])\s*[\]】]", raw or "")
    if m:
        return m.group(1)
    m = re.search(r"layer:\s*([ABC])", raw or "", re.I)
    if m:
        return m.group(1).upper()
    if re.search(r"[\[【]\s*[⊘]\s*[\]】]", raw or ""):
        return "SILENT"
    return ""


def load_cfg():
    src = json.load(open(CFG_SRC, encoding="utf-8"))
    if not (src.get("api_key") or "").strip():
        raise SystemExit("NO_KEY")
    return {
        "base_url": src.get("base_url"),
        "model": src.get("model"),
        "api_key": src.get("api_key"),
        "api": src.get("api") or "anthropic-messages",
    }


def rate(rows, key):
    k = sum(1 for r in rows if r[key])
    return {"k": k, "n": len(rows), "p": round(k / len(rows), 3) if rows else None,
            "wilson95": wilson(k, len(rows))}


def decide(summary):
    old_f = summary["old"]["false_B"]["p"]
    new_f = summary["new"]["false_B"]["p"]
    new_h = summary["new"]["hit_B"]["p"]
    new_w = summary["new"]["withhold"]["p"]
    if new_h == 0 and (new_w or 0) > 0.75:
        return "闸门变成沉默，不支持改进"
    if new_f < old_f and new_h > 0 and (new_w or 0) <= 0.75:
        return "新闸门优于旧的自报"
    return "不支持「新闸门优于旧的自报」"


def main():
    prereg_bytes = open(PREREG, "rb").read()
    prereg = json.loads(prereg_bytes.decode("utf-8"))
    digest = hashlib.sha256(prereg_bytes).hexdigest()
    paragraphs = prereg["paragraphs"]
    terms = prereg["terms"]
    repeats = int(prereg["repeats"])
    gold = []
    for i, para in enumerate(paragraphs):
        hit = gold_b(paragraphs, terms, i)
        gold.append({"index": i, "gold_B": bool(hit), "terms": hit, "text": para})
    print("PREREG", digest[:12], "gold_B", [g["gold_B"] for g in gold])

    dry = "--dry" in sys.argv
    if dry:
        return 0

    cfg_key = load_cfg()
    import cotree
    import providers
    import server

    raw_box = {}
    real = providers.chat

    def wrapped(c, system, user, **kw):
        text = real(c, system, user, **kw)
        raw_box["text"] = text
        return text

    server.providers.chat = wrapped
    rows = []
    out_rows = []
    done = set()
    if os.path.exists(OUT) and "--fresh" not in sys.argv:
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
            if prev.get("prereg_sha256") == digest:
                for r in prev.get("rows") or []:
                    if not r.get("error"):
                        out_rows.append(r)
                        rows.append(r)
                        done.add((r["rep"], r["arm"], r["index"]))
                print("RESUME", len(done), flush=True)
        except Exception:
            pass

    def save(partial_summary=None):
        blob = {
            "prereg_sha256": digest,
            "rows": out_rows,
            "summary": partial_summary,
        }
        text = json.dumps(blob, ensure_ascii=False, indent=2)
        if cfg_key["api_key"] in text:
            text = text.replace(cfg_key["api_key"], "[redacted]")
        open(OUT, "w", encoding="utf-8").write(text)

    for rep in range(1, repeats + 1):
        for arm in ("old", "new"):
            ledger_dir = tempfile.mkdtemp(prefix="e12_")
            cotree.SESSION = cotree.TreeSession(os.path.join(ledger_dir, "ledger.jsonl"))
            cfg = dict(cfg_key)
            cfg["cotree"] = arm == "new"
            for i, para in enumerate(paragraphs):
                if (rep, arm, i) in done:
                    print("SKIP", rep, arm, i, flush=True)
                    continue
                prior = "\n".join(paragraphs[:i])
                raw_box["text"] = ""
                err = ""
                cards = []
                for attempt in range(3):
                    try:
                        cards = server.call_model(
                            cfg, "", para, "—", "", prev=prior, delegate=True)
                        err = ""
                        break
                    except Exception as e:
                        err = type(e).__name__ + ": " + str(e)[:180]
                        time.sleep(2 + attempt * 3)
                card = (cards or [{}])[0]
                raw = raw_box.get("text") or ""
                ghit = gold_b(paragraphs, terms, i)
                is_gold = bool(ghit)
                withheld = card.get("type") == "withhold" or card.get("verdict") == "no"
                if arm == "old":
                    layer = self_layer(raw)
                    visible_b = layer == "B"
                else:
                    layer = (card.get("cotree") or {}).get("struct_layer") or card.get("struct_layer") or ""
                    visible_b = (not withheld) and layer == "B"
                row = {
                    "rep": rep,
                    "arm": arm,
                    "index": i,
                    "gold_B": is_gold,
                    "gold_terms": ghit,
                    "visible_B": visible_b,
                    "false_B": visible_b and not is_gold,
                    "hit_B": visible_b and is_gold,
                    "withhold": withheld if arm == "new" else layer == "SILENT",
                    "self_layer": self_layer(raw),
                    "struct_layer": layer,
                    "card_type": card.get("type"),
                    "reason": (card.get("cotree") or {}).get("reason") or "",
                    "verified": (card.get("cotree") or {}).get("verified"),
                    "rejected": (card.get("cotree") or {}).get("rejected"),
                    "raw": raw,
                    "body": card.get("body") or "",
                    "error": err,
                    "stop": providers.last_stop(),
                }
                rows.append(row)
                out_rows.append(row)
                save()
                print("R%d %s p%d gold=%s visibleB=%s withhold=%s err=%s" % (
                    rep, arm, i, int(is_gold), int(visible_b), int(row["withhold"]),
                    "Y" if err else "n"), flush=True)

    def pack(arm):
        subset = [r for r in rows if r["arm"] == arm and not r["error"]]
        neg = [r for r in subset if not r["gold_B"]]
        pos = [r for r in subset if r["gold_B"]]
        return {
            "n": len(subset),
            "errors": sum(1 for r in rows if r["arm"] == arm and r["error"]),
            "false_B": rate(neg, "false_B"),
            "hit_B": rate(pos, "hit_B"),
            "withhold": rate(subset, "withhold"),
        }

    summary = {"old": pack("old"), "new": pack("new")}
    summary["decision"] = decide(summary)
    save(summary)
    print("DECISION", summary["decision"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
