# -*- coding: utf-8 -*-
"""E13：预注册之后才调用。材料、提示和判决只读 cotree_e13_prereg.json。"""
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
os.environ.pop("COWRITE_V3", None)

PREREG = os.path.join(HERE, "cotree_e13_prereg.json")
OUT = os.path.join(HERE, "cotree_e13_out.json")
OLD = os.path.join(HERE, "cotree_e12_out.json")
CFG_SRC = os.environ["COWRITE_CONFIG"]


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


def build_user(prereg, paragraphs, index):
    current = paragraphs[index]
    prior = paragraphs[:index]
    if prior:
        return prereg["prompt"].format(prior="\n".join(prior), current=current)
    return prereg["prompt_first"].format(current=current)


def check_lock(prereg):
    paragraphs = prereg["paragraphs"]
    branches = prereg["branches"]
    for turn in prereg["turns"]:
        i = turn["index"]
        cur = paragraphs[i]
        own = branches[turn["branch"]]
        if not any(t in cur for t in own):
            raise SystemExit("当前句没有自己这一枝的词: %s" % i)
        parent = turn["parent"]
        for span in turn["distinguish"]:
            if span not in paragraphs[parent]:
                raise SystemExit("区分片段不在父句: %s %s" % (i, span))
            if span in cur:
                raise SystemExit("区分片段已经在当前句: %s %s" % (i, span))
        if parent is None and turn["distinguish"]:
            raise SystemExit("没有父句却写了区分片段: %s" % i)
        if parent is not None and not turn["distinguish"]:
            raise SystemExit("有父句却没有区分片段: %s" % i)


def place(prereg, text, index):
    turn = prereg["turns"][index]
    branches = prereg["branches"]
    raw = text or ""
    own = [t for t in branches[turn["branch"]] if t in raw]
    foreign = []
    for name, terms in branches.items():
        if name == turn["branch"]:
            continue
        hit = [t for t in terms if t in raw]
        if hit:
            foreign.append({"branch": name, "terms": hit})
    linked = [s for s in turn["distinguish"] if s in raw]
    need_parent = turn["parent"] is not None
    ok = bool(own) and not foreign and ((not need_parent) or bool(linked))
    return {
        "placed_ok": ok,
        "own": own,
        "foreign": foreign,
        "linked": linked,
        "has_parent": need_parent,
    }


def decide(prereg, rows):
    parent = [r for r in rows if r["has_parent"] and not r.get("error")]
    plain = [r for r in rows if not r["has_parent"] and not r.get("error")]
    pk = sum(1 for r in parent if r["placed_ok"])
    qk = sum(1 for r in plain if r["placed_ok"])
    if pk >= 7 and qk >= 7:
        verdict = "这八句上，干净散文能按记忆对上枝，再出现的段落对回了父枝"
    elif pk <= 3 and qk >= 7:
        verdict = "散文大多落在当前句那一枝，再出现没有对回父枝"
    else:
        verdict = "这八句上不能认为该主张已成立"
    return {
        "parent_placed": {"k": pk, "n": len(parent)},
        "plain_placed": {"k": qk, "n": len(plain)},
        "verdict": verdict,
        "prior": "E1、E8、E9、E10 不在本次判决范围内",
    }


def score_old(prereg):
    if not os.path.exists(OLD):
        return []
    old = json.load(open(OLD, encoding="utf-8"))
    rows = []
    for r in old.get("rows") or []:
        if r.get("arm") != "old" or r.get("error"):
            continue
        got = place(prereg, r.get("raw") or "", r["index"])
        rows.append({
            "rep": r["rep"],
            "index": r["index"],
            "placed_ok": got["placed_ok"],
            "has_parent": got["has_parent"],
            "own": got["own"],
            "foreign": got["foreign"],
            "linked": got["linked"],
        })
    return rows


def main():
    raw_bytes = open(PREREG, "rb").read()
    prereg = json.loads(raw_bytes.decode("utf-8"))
    digest = hashlib.sha256(raw_bytes).hexdigest()
    check_lock(prereg)
    paragraphs = prereg["paragraphs"]
    print("PREREG", digest[:12])
    for turn in prereg["turns"]:
        print("p%d %s parent=%s distinguish=%s" % (
            turn["index"], turn["branch"], turn["parent"], " ".join(turn["distinguish"])))
    if "--dry" in sys.argv:
        return 0

    cfg = load_cfg()
    import providers

    repeats = int(prereg["repeats"])
    rows = []
    done = set()
    if os.path.exists(OUT) and "--fresh" not in sys.argv:
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
            if prev.get("prereg_sha256") == digest:
                rows = [r for r in prev.get("rows") or [] if not r.get("error")]
                done = {(r["rep"], r["index"]) for r in rows}
                print("RESUME", len(done), flush=True)
        except Exception:
            rows = []
            done = set()

    def save(summary=None):
        blob = {
            "prereg_sha256": digest,
            "rows": rows,
            "old_channel_rescore": score_old(prereg),
            "summary": summary,
        }
        text = json.dumps(blob, ensure_ascii=False, indent=2)
        if cfg["api_key"] in text:
            text = text.replace(cfg["api_key"], "[redacted]")
        open(OUT, "w", encoding="utf-8").write(text)

    for rep in range(1, repeats + 1):
        for i, _para in enumerate(paragraphs):
            if (rep, i) in done:
                print("SKIP", rep, i, flush=True)
                continue
            user = build_user(prereg, paragraphs, i)
            err = ""
            reply = ""
            for attempt in range(3):
                try:
                    reply = providers.chat(
                        cfg, "", user,
                        temperature=float(prereg["temperature"]),
                        max_tokens=int(prereg["max_tokens"]),
                        timeout=180,
                        thinking=str(prereg["thinking"]))
                    err = ""
                    break
                except Exception as e:
                    err = type(e).__name__
                    time.sleep(2 + attempt * 3)
            got = place(prereg, reply, i)
            row = {
                "rep": rep,
                "index": i,
                "user": user,
                "raw": reply,
                "error": err,
                "stop": providers.last_stop(),
                "placed_ok": got["placed_ok"],
                "has_parent": got["has_parent"],
                "own": got["own"],
                "foreign": got["foreign"],
                "linked": got["linked"],
            }
            rows.append(row)
            save()
            print("R%d p%d ok=%s link=%s err=%s" % (
                rep, i, int(got["placed_ok"]), ",".join(got["linked"]),
                "Y" if err else "n"), flush=True)

    summary = decide(prereg, rows)
    old_rows = score_old(prereg)
    summary["old_channel_same_ruler"] = decide(prereg, old_rows) if old_rows else None
    summary["old_channel_note"] = "E12 旧臂原文在本次之前已经读过。同一把尺子的结果只作对照，不改上面的判决。"
    save(summary)
    print("VERDICT", summary["verdict"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
