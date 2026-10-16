# -*- coding: utf-8 -*-
import os
"""E17: path as a tree edge vs path as prompt text. Prereg is not edited."""
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREREG = json.loads((HERE / "prereg.json").read_text(encoding="utf-8"))
TRUNK_PATH = (
    Path(__file__).resolve().parents[3]
    / "知音坐标系_2026-10-16"
    / "07_本轮实验资产_2026-10-16"
    / "03_数据" / "树" / "trunk_v8_错位默认_DRAFT.json"
)
CFG = Path(os.environ["COWRITE_CONFIG"])
OUT = HERE / "out.json"

PASSAGES = [
    "when you are asked, for example, why two magnets repel, there are many different levels. It depends on whether you are a student of physics, or an ordinary person who doesn't know anything.",
    "If you're somebody who doesn't know anything at all about it, all I can say is the magnetic force makes them repel, and that you're feeling that force.",
    "you're not at all disturbed by the fact that when you put your hand on a chair, it pushes you back. But we found out by looking at it that that's the same force... the same electric repulsions that are involved in keeping your finger away from the chair.",
    "in iron all the electrons are spinning in the same direction, they all get lined up, and they magnify the effect of the force 'til it's large enough, at a distance, that you can feel it.",
    "if I said the magnets attract like as if they were connected by rubber bands, I would be cheating you... if you were curious enough, you'd ask me why rubber bands tend to pull back together again, and I would end up explaining that in terms of electrical forces, which are the very things that I'm trying to use the rubber bands to explain. So I have cheated very badly.",
    "I am not going to be able to give you an answer to why magnets attract each other except to tell you that they do. And to tell you that that's one of the elements in the world... If you were a student, I could go further.",
    "I really can't do a good job, any job, of explaining magnetic force in terms of something else you're more familiar with, because I don't understand it in terms of anything else that you're more familiar with.",
]

CLAUSES = """你是对话的一方（乙）。对面是甲，甲会一段段带东西进来。你手里有一棵树（id/label/边，无释义）。

条款（全程不变）：
1. 默认态是「尚未对齐」。
2. 应当出声，把你看到的东西回映出来；但不得替甲把它命名成某个节点或某个结论。
3. 指位置不给方案。
4. ⊘ 是合法且被尊重的输出。
5. 内容门槛：有真实的方向增量。
6. 不以疑问句收尾制造继续的压力。
7. 不要只复述对方的话，不要抄原材料。
8. 若本轮要说的话已经在已走过的某一步里说过，输出 ⊘。
9. 每轮提交一个位置，须满足树里写明的前置条件。

输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：<节点 id 或 ⊘>
"""

TEXT_PATH = """
【已走过的路径·写在下面这段文字里】
{path}
若要推进，请说明你是在路径的哪一步上推进的（写出步号）。
"""

TREE_PATH = """
【已走过的路径】不在这段话里。路径是树上 kind=path 的边，指向 D1、D2 这些节点。节点的 label 是那一步的话。若要推进，写出你接在哪个 D 节点上。
"""


def load_key():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    key = cfg.get("api_key") or ""
    if not key:
        raise SystemExit("no api_key")
    return cfg.get("base_url") or "http://note3-prev-api.askdiandian.com", key, cfg.get("model") or "dots3-note-prev"


def call(base, key, model, system, user):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": 400,
        "temperature": 0.5,
        "thinking": {"type": "disabled"},
        "system": system,
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    return "".join(
        b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"
    ).strip()


def sparse(nodes, edges):
    return json.dumps(
        {
            "nodes": [{"id": n["id"], "label": n.get("label", "")} for n in nodes],
            "edges": [
                {"from": e["from"], "to": e["to"], "kind": e["kind"]} for e in edges
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def compact(s):
    return re.sub(r"\s+", "", s or "")


def first_sentence(s):
    s = compact(s)
    parts = re.split(r"[。；]", s)
    return (parts[0] if parts and parts[0] else s)[:60]


def cites(prev, body, passage):
    prev_c, body_c, pas_c = compact(prev), compact(body), compact(passage)
    if len(prev_c) < 8:
        return False
    for i in range(0, len(prev_c) - 7):
        w = prev_c[i : i + 8]
        if w in body_c and w not in pas_c:
            return True
    return False


def parse(out):
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    if not lines:
        return "", "⊘"
    pos = "⊘"
    if len(lines) > 1 and lines[-1].startswith("位置"):
        pos = lines[-1].split("：", 1)[-1].strip()
        body = "\n".join(lines[:-1])
    else:
        body = "\n".join(lines)
    return body, pos[:40]


def decide(text_hits, tree_hits):
    if tree_hits > text_hits and tree_hits >= 4:
        return "写回边优于写在提示里"
    if text_hits == 0 and tree_hits == 0:
        return "这七段上写回边没有产生可核对的引用"
    return "不支持「写回边优于写在提示里」"


def main():
    base, key, model = load_key()
    trunk = json.loads(TRUNK_PATH.read_text(encoding="utf-8"))
    base_nodes = [{"id": n["id"], "label": n.get("label", "")} for n in trunk["nodes"]]
    base_edges = [
        {"from": e["from"], "to": e["to"], "kind": e["kind"]} for e in trunk.get("edges", [])
    ]
    known = {n["id"] for n in base_nodes}
    rows = []
    if OUT.exists():
        rows = json.loads(OUT.read_text(encoding="utf-8")).get("rows", [])
    done = {(r["rep"], r["arm"], r["k"]) for r in rows}

    for rep in range(1, 4):
        for arm in ("text", "tree"):
            path = []
            drafts_n, drafts_e = [], []
            for k, passage in enumerate(PASSAGES, 1):
                if (rep, arm, k) in done:
                    prev = [r for r in rows if r["rep"] == rep and r["arm"] == arm and r["k"] < k]
                    path = [(r["pos"], r["sentence"]) for r in prev]
                    continue
                if arm == "text":
                    ptext = (
                        "\n".join(
                            "%d. [%s] %s" % (i + 1, a, c) for i, (a, c) in enumerate(path)
                        )
                        or "（尚无）"
                    )
                    system = CLAUSES + TEXT_PATH.format(path=ptext) + "\n\n树：\n" + sparse(base_nodes, base_edges)
                else:
                    system = CLAUSES + TREE_PATH + "\n\n树：\n" + sparse(base_nodes + drafts_n, base_edges + drafts_e)
                user = "（第 %d 段）%s" % (k, passage)
                try:
                    raw = call(base, key, model, system, user)
                    err = ""
                except Exception as e:
                    raw, err = "", type(e).__name__
                body, pos = parse(raw)
                sentence = first_sentence(body)
                hit = False if k == 1 or not path else cites(path[-1][1], body, passage)
                row = {
                    "rep": rep,
                    "arm": arm,
                    "k": k,
                    "pos": pos,
                    "sentence": sentence,
                    "cite_prev": hit,
                    "error": err,
                    "raw": raw,
                }
                rows.append(row)
                path.append((pos, sentence))
                if arm == "tree":
                    did = "D%d" % k
                    drafts_n.append({"id": did, "label": sentence[:24]})
                    src = pos if pos in known or pos.startswith("D") else "UNPLACED"
                    drafts_e.append({"from": src, "to": did, "kind": "path"})
                OUT.write_text(
                    json.dumps({"prereg": PREREG["id"], "rows": rows}, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                print("rep%d %s k%d cite=%s err=%s" % (rep, arm, k, int(hit), err or "-"), flush=True)

    def hits(arm):
        return sum(1 for r in rows if r["arm"] == arm and r["k"] >= 2 and r["cite_prev"])

    th, eh = hits("tree"), hits("text")
    verdict = decide(eh, th)
    summary = {"text_cite": eh, "tree_cite": th, "verdict": verdict, "errors": sum(1 for r in rows if r["error"])}
    OUT.write_text(
        json.dumps({"prereg": PREREG["id"], "summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
