# -*- coding: utf-8 -*-
"""E14：极性规则在调用前锁定。发现集 E13 不读、不判。"""
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
os.environ.pop("COWRITE_V3", None)

PREREG = os.path.join(HERE, "cotree_e14_prereg.json")
OUT = os.path.join(HERE, "cotree_e14_out.json")
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


def sentences(text):
    parts = re.split(r"[。！？!?；;\n]+", text or "")
    return [p.strip() for p in parts if p.strip()]


def only_unknown(text):
    s = re.sub(r"\s+", "", text or "")
    s = re.sub(r"[。！？!?]", "", s)
    return s in ("不知道", "我不知道")


def denial(sent, marks):
    return any(m in sent for m in marks)


def affirmed(text, terms, marks):
    if only_unknown(text):
        return []
    found = []
    for sent in sentences(text):
        if denial(sent, marks):
            continue
        for t in terms:
            if t in sent and t not in found:
                found.append(t)
    return found


def check_lock(seq):
    paragraphs = seq["paragraphs"]
    branches = seq["branches"]
    for turn in seq["turns"]:
        cur = paragraphs[turn["index"]]
        own = branches[turn["branch"]]
        if not any(t in cur for t in own):
            raise SystemExit("当前句没有本枝的词 %s %s" % (turn["index"], turn["branch"]))
        parent = turn["parent"]
        for span in turn["distinguish"]:
            if parent is None or span not in paragraphs[parent] or span in cur:
                raise SystemExit("区分片段不合 %s %s" % (turn["index"], span))
        if (parent is None) != (not turn["distinguish"]):
            if parent is None and turn["distinguish"]:
                raise SystemExit("无父却有片段 %s" % turn["index"])
            if parent is not None and not turn["distinguish"]:
                raise SystemExit("有父无片段 %s" % turn["index"])
        if turn["kind"] == "cont" and parent is None:
            raise SystemExit("延续却无父 %s" % turn["index"])
        if turn["kind"] != "cont" and parent is not None:
            raise SystemExit("非延续却有父 %s" % turn["index"])


def build_user(prereg, paragraphs, index):
    current = paragraphs[index]
    prior = paragraphs[:index]
    if prior:
        return prereg["prompt"].format(prior="\n".join(prior), current=current)
    return prereg["prompt_first"].format(current=current)


def judge(prereg, seq, text, index):
    turn = seq["turns"][index]
    marks = prereg["deny_marks"]
    branches = seq["branches"]
    own = affirmed(text, branches[turn["branch"]], marks)
    foreign = []
    for name, terms in branches.items():
        if name == turn["branch"]:
            continue
        hit = affirmed(text, terms, marks)
        if hit:
            foreign.append({"branch": name, "terms": hit})
    linked = affirmed(text, turn["distinguish"], marks)
    unknown = only_unknown(text)
    affirm_parent = bool(linked)
    break_ok = (not foreign) and (unknown or bool(own) or any(denial(s, marks) for s in sentences(text)) or unknown)
    if turn["kind"] == "break":
        break_ok = not foreign
    return {
        "kind": turn["kind"],
        "own": own,
        "foreign": foreign,
        "linked": linked,
        "unknown": unknown,
        "affirm_parent": affirm_parent,
        "break_ok": break_ok if turn["kind"] == "break" else False,
        "stitch": bool(foreign),
    }


def sign_of(rows):
    cont = [r for r in rows if r["kind"] == "cont" and not r.get("error")]
    brk = [r for r in rows if r["kind"] == "break" and not r.get("error")]
    ak = sum(1 for r in cont if r["affirm_parent"])
    bk = sum(1 for r in brk if r["break_ok"])
    ok = bool(cont and brk) and (ak / len(cont) > 0.5) and (bk / len(brk) > 0.5)
    return {
        "cont_affirm": {"k": ak, "n": len(cont)},
        "break_hold": {"k": bk, "n": len(brk)},
        "stitch": sum(1 for r in rows if r.get("stitch") and not r.get("error")),
        "positive": ok,
    }


def main():
    raw_bytes = open(PREREG, "rb").read()
    prereg = json.loads(raw_bytes.decode("utf-8"))
    digest = hashlib.sha256(raw_bytes).hexdigest()
    for name, seq in prereg["sequences"].items():
        check_lock(seq)
        print("PREREG", digest[:12], name)
        for turn in seq["turns"]:
            print(" ", turn["kind"], turn["index"], turn["branch"], " ".join(turn["distinguish"]))
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
                rows = [r for r in (prev.get("rows") or []) if not r.get("error")]
                done = {(r["seq"], r["rep"], r["index"]) for r in rows}
                print("RESUME", len(done), flush=True)
        except Exception:
            rows, done = [], set()

    def save(summary=None):
        blob = {"prereg_sha256": digest, "rows": rows, "summary": summary}
        text = json.dumps(blob, ensure_ascii=False, indent=2)
        if cfg["api_key"] in text:
            text = text.replace(cfg["api_key"], "[redacted]")
        open(OUT, "w", encoding="utf-8").write(text)

    for seq_name, seq in prereg["sequences"].items():
        paragraphs = seq["paragraphs"]
        for rep in range(1, repeats + 1):
            for i, _p in enumerate(paragraphs):
                if (seq_name, rep, i) in done:
                    print("SKIP", seq_name, rep, i, flush=True)
                    continue
                user = build_user(prereg, paragraphs, i)
                err, reply = "", ""
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
                got = judge(prereg, seq, reply, i)
                row = {
                    "seq": seq_name,
                    "rep": rep,
                    "index": i,
                    "user": user,
                    "raw": reply,
                    "error": err,
                    "stop": providers.last_stop(),
                }
                row.update(got)
                rows.append(row)
                save()
                print("%s R%d p%d %s affirm=%s hold=%s stitch=%s err=%s" % (
                    seq_name, rep, i, got["kind"], int(got["affirm_parent"]),
                    int(got["break_ok"]), int(got["stitch"]), "Y" if err else "n"), flush=True)

    summary = {}
    signs = []
    for seq_name in prereg["sequences"]:
        sub = [r for r in rows if r["seq"] == seq_name]
        summary[seq_name] = sign_of(sub)
        signs.append(summary[seq_name]["positive"])
    summary["regularity"] = "两套句子的符号一致，规律成立" if all(signs) else "两套符号不一致，规律尚未稳住"
    if not all(signs) and any(signs):
        summary["regularity"] = "只有一套是正号，规律尚未在两套语料上重复"
    summary["prior"] = "E1、E8、E9、E10 不在本次判决内。E13 是发现集，不进入判决。"
    save(summary)
    print(summary["regularity"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
