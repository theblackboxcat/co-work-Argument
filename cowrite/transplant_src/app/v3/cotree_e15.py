# -*- coding: utf-8 -*-
"""E15：容器假说。规则在调用前锁定。E13、E14 不重判。"""
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
os.environ.pop("COWRITE_V3", None)

import cotree_e14 as base

PREREG = os.path.join(HERE, "cotree_e15_prereg.json")
OUT = os.path.join(HERE, "cotree_e15_out.json")
CFG_SRC = os.environ["COWRITE_CONFIG"]


def judge(prereg, seq, text, index):
    turn = seq["turns"][index]
    marks = prereg["deny_marks"]
    branches = seq["branches"]
    own = base.affirmed(text, branches[turn["branch"]], marks)
    foreign = []
    for name, terms in branches.items():
        if name == turn["branch"]:
            continue
        hit = base.affirmed(text, terms, marks)
        if hit:
            foreign.append({"branch": name, "terms": hit})
    linked = base.affirmed(text, turn["distinguish"], marks)
    back = base.affirmed(text, prereg["anaphora"], marks)
    return {
        "kind": turn["kind"],
        "own": own,
        "foreign": foreign,
        "linked": linked,
        "anaphora": back,
        "unknown": base.only_unknown(text),
        "break_ok": not foreign,
        "cont_link": bool(linked) or (bool(back) and bool(own)),
        "stitch": bool(foreign),
    }


def block_sign(rows):
    brk = [r for r in rows if r["kind"] == "break" and not r.get("error")]
    cont = [r for r in rows if r["kind"] == "cont" and not r.get("error")]
    held = sum(1 for r in brk if r["break_ok"])
    linked = sum(1 for r in cont if r["cont_link"])
    return {
        "break_hold": {"k": held, "n": len(brk)},
        "cont_link": {"k": linked, "n": len(cont)},
        "stitch": sum(1 for r in rows if r.get("stitch") and not r.get("error")),
    }


def main():
    raw_bytes = open(PREREG, "rb").read()
    prereg = json.loads(raw_bytes.decode("utf-8"))
    digest = hashlib.sha256(raw_bytes).hexdigest()
    for name, seq in prereg["sequences"].items():
        base.check_lock(seq)
        print("PREREG", digest[:12], name, "container", seq["container"])
    if "--dry" in sys.argv:
        return 0

    cfg = base.load_cfg()
    import providers
    repeats = int(prereg["repeats"])
    rows, done = [], set()
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
                    continue
                user = base.build_user(prereg, paragraphs, i)
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
                    "seq": seq_name, "rep": rep, "index": i,
                    "user": user, "raw": reply, "error": err,
                    "stop": providers.last_stop(),
                }
                row.update(got)
                rows.append(row)
                save()
                print("%s R%d p%d %s hold=%s link=%s stitch=%s err=%s" % (
                    seq_name, rep, i, got["kind"], int(got["break_ok"]),
                    int(got["cont_link"]), int(got["stitch"]),
                    "Y" if err else "n"), flush=True)

    summary = {name: block_sign([r for r in rows if r["seq"] == name])
               for name in prereg["sequences"]}
    sep = summary["sep"]["break_hold"]
    one = summary["one"]["break_hold"]
    sep_pos = sep["n"] and sep["k"] / sep["n"] > 0.5
    one_pos = one["n"] and one["k"] / one["n"] <= 0.5
    if sep_pos and one_pos:
        summary["regularity"] = "符号翻转成立：没有共同容器时断开守住，有共同容器时断开被缝上"
    else:
        summary["regularity"] = "容器假说没有出现预定的翻转"
    summary["prior"] = "E1、E8、E9、E10 不在本次判决内。E13、E14 不重判。"
    save(summary)
    print(summary["regularity"])
    print(json.dumps({k: summary[k] for k in ("sep", "one", "regularity")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
