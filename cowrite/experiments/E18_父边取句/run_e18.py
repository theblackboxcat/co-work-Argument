# -*- coding: utf-8 -*-
import os
"""E18: code walks the parent edge and retrieves only that sentence."""
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PR = json.loads((HERE / "prereg.json").read_text(encoding="utf-8"))
CFG = Path(os.environ["COWRITE_CONFIG"])
OUT = HERE / "out.json"

NONE = (
    "刚刚这一句：{current}\n\n"
    "用平常的话回应这一句。只谈这一句里有的事。不要编下一步。没有把握就说不知道。"
)
BAG = (
    "她刚刚写下的一句，可能接在下面两句里的一句下面。这里没有标明是哪一句。\n"
    "旧句一：{first}\n"
    "旧句二：{second}\n\n"
    "刚刚这一句：{current}\n\n"
    "用平常的话回应刚刚这一句。只把她接上的那句旧事里的具体事物说进来，另一句不要出现。"
    "看不出接的是哪一句，就说不知道。不要编下一步。不要写编号。"
)
EDGE = (
    "她刚刚写下的一句，接在先前某一句下面。沿那条边，这里只取出那一句，别的句子没有放进来。\n"
    "先前那一句：{parent}\n\n"
    "刚刚这一句：{current}\n\n"
    "用平常的话回应刚刚这一句，并把先前那一句里已经写下的具体事物说进来。"
    "不要编下一步。不要写编号。"
)


def load_key():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    key = cfg.get("api_key") or ""
    if not key:
        raise SystemExit("no api_key")
    return cfg.get("base_url") or "http://note3-prev-api.askdiandian.com", key, cfg.get("model") or "dots3-note-prev"


def call(base, key, model, user):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": 400,
        "temperature": 0.3,
        "thinking": {"type": "disabled"},
        "system": "",
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()


def check_materials(items):
    for i, it in enumerate(items):
        for sp in it["parent_spans"] + it["sibling_spans"]:
            if sp in it["current"]:
                raise SystemExit("span in current: %s %s" % (i, sp))
        for sp in it["parent_spans"]:
            if sp in it["sibling"]:
                raise SystemExit("parent span in sibling: %s %s" % (i, sp))
        for sp in it["sibling_spans"]:
            if sp in it["parent"]:
                raise SystemExit("sibling span in parent: %s %s" % (i, sp))


def score(raw, it):
    return {
        "parent_ok": any(sp in raw for sp in it["parent_spans"]),
        "sibling_bad": any(sp in raw for sp in it["sibling_spans"]),
    }


def successes(rows, set_name, arm):
    n = 0
    for r in rows:
        if r["set"] == set_name and r["arm"] == arm and r["parent_ok"] and not r["sibling_bad"]:
            n += 1
    return n


def parent_hits(rows, set_name, arm):
    return sum(1 for r in rows if r["set"] == set_name and r["arm"] == arm and r["parent_ok"])


def judge(rows, set_name):
    if parent_hits(rows, set_name, "none") > 3:
        return "作废"
    e, b = successes(rows, set_name, "edge"), successes(rows, set_name, "bag")
    if e >= 9 and e > b:
        return "父边取句优于整袋记忆"
    return "不支持"


def main():
    check_materials(PR["set_A"])
    check_materials(PR["set_B"])
    base, key, model = load_key()
    rows = []
    if OUT.exists():
        rows = json.loads(OUT.read_text(encoding="utf-8")).get("rows", [])
    done = {(r["set"], r["rep"], r["arm"], r["i"]) for r in rows}
    sets = [("A", PR["set_A"])]
    # B stays sealed until A wins. A rerun that already won will fill B.
    if any(r["set"] == "A" for r in rows) and judge(rows, "A") == "父边取句优于整袋记忆":
        sets.append(("B", PR["set_B"]))
    if not rows:
        sets = [("A", PR["set_A"])]

    for set_name, items in sets:
        for rep in range(1, 4):
            for i, it in enumerate(items):
                parent_first = (rep + i) % 2 == 0
                first, second = (it["parent"], it["sibling"]) if parent_first else (it["sibling"], it["parent"])
                prompts = {
                    "none": NONE.format(current=it["current"]),
                    "bag": BAG.format(first=first, second=second, current=it["current"]),
                    "edge": EDGE.format(parent=it["parent"], current=it["current"]),
                }
                for arm in ("none", "bag", "edge"):
                    if (set_name, rep, arm, i) in done:
                        continue
                    try:
                        raw = call(base, key, model, prompts[arm])
                        err = ""
                    except Exception as e:
                        raw, err = "", type(e).__name__
                    sc = score(raw, it)
                    row = {"set": set_name, "rep": rep, "arm": arm, "i": i, "error": err, "raw": raw}
                    row.update(sc)
                    row["success"] = bool(sc["parent_ok"] and not sc["sibling_bad"] and not err)
                    rows.append(row)
                    done.add((set_name, rep, arm, i))
                    OUT.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
                    print("%s r%d %s i%d ok=%s bad=%s err=%s" % (
                        set_name, rep, arm, i, int(sc["parent_ok"]), int(sc["sibling_bad"]), err or "-"), flush=True)

    verdict_a = judge(rows, "A")
    if verdict_a == "父边取句优于整袋记忆" and not any(r["set"] == "B" for r in rows):
        print("A won; B not in this process. rerun to fill B.", flush=True)
    summary = {
        "A": {"verdict": verdict_a, "none_parent": parent_hits(rows, "A", "none"),
              "bag": successes(rows, "A", "bag"), "edge": successes(rows, "A", "edge")},
    }
    if any(r["set"] == "B" for r in rows):
        summary["B"] = {"verdict": judge(rows, "B"), "none_parent": parent_hits(rows, "B", "none"),
                        "bag": successes(rows, "B", "bag"), "edge": successes(rows, "B", "edge")}
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
