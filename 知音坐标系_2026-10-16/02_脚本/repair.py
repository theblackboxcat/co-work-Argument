#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复回路检验：模型自检字段 + 外部校验器 + 一次 repair，能否把「说出来」变成「做得到」

背景：sysrule 实验显示模型能在 rationale 中正确声明规则被触发，却仍输出被禁节点
      （elicitable 但不 executable）。
假设：把自检变成结构化字段（rule_check），由**外部代码**判定违规并强制 repair，
      约束才可能真正生效。这与 generate≠commit 同构：模型提议，校验器/作者裁定。

流程：pass1 输出 {nodes, rule_check} → 代码校验 → 违规则 pass2 附违规说明要求修正
"""
import json
import sys
from datetime import datetime
from pathlib import Path

DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO))
from lib import providers  # noqa: E402
from ablate import build_views, extract_json_obj, load_json, norm_edge  # noqa: E402

RULES = {
    "R1": ("禁止停靠在「存在主义平原 / 存在主义地平线」",
           {"S05_existential_plain", "S19_existential_horizon"}),
    "R2": ("禁止停靠在「化形／变形寓言」", {"S03_allegorical_transform"}),
    "R3": ("禁止停靠在「分形恐怖」", {"S06_fractal_horror"}),
}

SYSTEM = (
    "你是定位助手。你会拿到坐标系与三条硬约束。\n"
    "硬约束（判断前提，不是事后说明）：\n"
    "R1 若段落只是描写自然风景（真实的平原、风、草地、地平线等可见景物），"
    "禁止停靠在「存在主义平原 / 存在主义地平线」。\n"
    "R2 若段落把变形解释为心理疾病、创伤或躯体化症状，禁止停靠在「化形／变形寓言」。\n"
    "R3 若段落已把冲突收束为某个具体责任人并被解决，禁止停靠在「分形恐怖」。\n"
    '只输出单一 JSON：{"nodes":["<id>"],'
    '"rule_check":{"R1":false,"R2":false,"R3":false},'
    '"rationale_short":"<=2句>"}\n'
    "rule_check 中若某条规则的条件成立（即禁止停靠的情形出现），必须置为 true。"
)

WANT = {"P3_plain", "P3p_scenery", "P1_transform", "P1p_psychologized",
        "P2_fractal", "P2p_plotized"}


def main():
    cfg = load_json(DEMO / "config.json")
    trunk = load_json(DEMO / "trunk_v0.json")
    extra = load_json(DEMO / "trunk_v1_parent_edges.json")
    ex = extra.get("edges", extra) if isinstance(extra, dict) else extra
    have = {(e.get("from"), e.get("to"), e.get("kind")) for e in trunk.get("edges", [])}
    trunk = dict(trunk)
    trunk["edges"] = list(trunk.get("edges", [])) + [e for e in ex
                                                     if (e.get("from"), e.get("to"), e.get("kind")) not in have]
    ids = sorted({n["id"] for n in trunk["nodes"]})
    allowed = set(ids)
    views = build_views(trunk)
    lab = {n["id"]: n.get("label", "") for n in trunk["nodes"]}
    anchors = [a for a in load_json(DEMO / "anchors_lit_v1.json")["anchors"] if a["id"] in WANT]

    ok, detail = providers.probe(cfg, timeout=40)
    print("probe_ok=%s %s" % (ok, detail))
    if not ok:
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DEMO / "runs" / ("repair_%s.jsonl" % ts)
    out.parent.mkdir(exist_ok=True)

    for a in anchors:
        for r in range(3):
            user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                    % (views["D_full"], json.dumps(ids, ensure_ascii=False), a["text"]))
            rep1 = providers.chat(cfg, SYSTEM, user, temperature=0.2, max_tokens=800,
                                  timeout=60, thinking="disabled")
            p1 = extract_json_obj(rep1) or {}
            nodes = [x for x in (p1.get("nodes") or []) if isinstance(x, str) and x in allowed]
            rc = p1.get("rule_check") or {}
            # 外部校验器：自检为 true 却仍停靠 → 违规
            viol = [k for k, (_, banned) in RULES.items()
                    if rc.get(k) is True and set(nodes) & banned]
            rec = {"anchor_id": a["id"], "rep": r, "pass1_nodes": nodes,
                   "rule_check": rc, "violations": viol}
            if viol:
                vtext = "；".join(RULES[k][0] for k in viol)
                user2 = (user + "\n\n【校验失败】你的输出违反了你自己声明为 true 的规则（%s）："
                         "nodes=%s 中包含被禁节点。请重新输出，遵守规则；"
                         "若确实无处可停，nodes 返回空数组并说明理由。" % (vtext, nodes))
                rep2 = providers.chat(cfg, SYSTEM, user2, temperature=0.2, max_tokens=800,
                                      timeout=60, thinking="disabled")
                p2 = extract_json_obj(rep2) or {}
                n2 = [x for x in (p2.get("nodes") or []) if isinstance(x, str) and x in allowed]
                rc2 = p2.get("rule_check") or {}
                viol2 = [k for k, (_, banned) in RULES.items()
                         if rc2.get(k) is True and set(n2) & banned]
                rec.update({"pass2_nodes": n2, "rule_check2": rc2, "violations2": viol2,
                            "repaired": not viol2})
            print(" %-20s r%d  pass1=%-42s rc=%-28s 违规=%s%s" % (
                a["id"], r,
                ",".join("%s(%s)" % (n, lab.get(n, "")[:7]) for n in nodes) or "(空)",
                ",".join("%s=%s" % (k, rc.get(k)) for k in ("R1", "R2", "R3")),
                viol or "-",
                ("  → repair: %s  仍违规=%s" % (
                    ",".join("%s(%s)" % (n, lab.get(n, "")[:7]) for n in rec.get("pass2_nodes", [])) or "(空)",
                    rec.get("violations2") or "-")) if viol else ""))
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("\nwrote: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
