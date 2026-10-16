# -*- coding: utf-8 -*-
# ⚠️ 本文件是 v1 包内的【旧版】：硬编码 /workspace/uploads/cowrite_tree/app 绝对路径，
#    不可移植，且未实现协议 v1 的双臂同构 / 边计分 / parent 边合并。
#    请使用 localize_v1.py。保留本文件仅供对照查证。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知音-tree localization smoke demo (dots3).

Theory locks:
  - private corpus = positioning anchors only, NOT tree content source
  - generate ≠ commit: model proposes; do not auto-commit
  - do NOT claim understanding achieved; S3 CLOSED; smoke demo only
  - agent fitting via memory/skills is the wrong path; we demo localization onto an explicit tree

Usage:
  python3 localize.py
  python3 localize.py --config /path/to/config.json
  python3 localize.py --trunk trunk_v0.json --anchors anchors.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = Path("/workspace/uploads/cowrite_tree/app/config.json")
COWRITE_APP = Path("/workspace/uploads/cowrite_tree/app")

# Import providers without hardcoding keys into this file.
sys.path.insert(0, str(COWRITE_APP))
try:
    import providers  # type: ignore
except ImportError as e:
    print("FATAL: cannot import providers from %s: %s" % (COWRITE_APP, e), file=sys.stderr)
    sys.exit(2)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compact_trunk(trunk: dict) -> dict:
    """Compact trunk for prompt: ids, labels, gloss, layer, parent + ban/contrast edges."""
    nodes = [
        {
            "id": n["id"],
            "parent": n.get("parent"),
            "layer": n.get("layer"),
            "label": n.get("label"),
            "gloss": n.get("gloss"),
        }
        for n in trunk.get("nodes", [])
    ]
    edges = [
        {"from": e["from"], "to": e["to"], "kind": e["kind"]}
        for e in trunk.get("edges", [])
        if e.get("kind") in ("ban", "contrast")
    ]
    return {"nodes": nodes, "edges": edges}


def trunk_id_set(trunk: dict) -> set:
    return {n["id"] for n in trunk.get("nodes", [])}


def extract_json_obj(text: str):
    """Best-effort extract first JSON object from model reply."""
    if not text:
        return None
    text = text.strip()
    # fenced
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # raw object
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return None


def map_bare_to_ids(raw: str, trunk: dict) -> list:
    """Heuristic: if bare reply mentions known labels/ids, collect matching node ids."""
    if not raw:
        return []
    found = []
    lower = raw.lower()
    for n in trunk.get("nodes", []):
        nid = n["id"]
        label = n.get("label") or ""
        # match id substring or label keywords (first 4+ chars of label without punctuation)
        if nid.lower() in lower or nid in raw:
            found.append(nid)
            continue
        # label tokens
        for tok in re.split(r"[／/\s·，,。.]+", label):
            tok = tok.strip()
            if len(tok) >= 2 and tok in raw:
                found.append(nid)
                break
    # dedupe preserve order
    seen = set()
    out = []
    for x in found:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:4]


BARE_SYSTEM = (
    "你是知音对齐定位助手的对照臂（无树）。"
    "任务：为给定短段落命名 1–2 个概念停靠点（中文短名即可），"
    "用于「现代主义中文写作 / 结构主义—存在主义沟通」坐标系上的知音对齐。"
    "不要宣称理解已达成；只提议停靠点。"
    "输出用两行：STOPS: <停靠点1>; <停靠点2>\nRATIONALE: <一句理由>"
)

TREE_SYSTEM = (
    "你是知音树定位助手。只允许从给定 trunk 的 node id 中选择停靠点。"
    "generate≠commit：你只提议，不得自动提交。"
    "不要宣称理解已达成；S3 CLOSED；本任务是 smoke demo。"
    "输出必须是单一 JSON 对象，字段："
    '{"proposed_node_ids":["..."],"edges":[],"rationale":"...","needs_author_commit":true}'
    "proposed_node_ids 只能来自 trunk 的 id；选 1–2 个 stop 层优先。"
)


def run_bare(cfg, anchor: dict, trunk: dict, timeout: int) -> dict:
    user = (
        "段落（定位锚，非树内容源）：\n%s\n\n"
        "请命名 1–2 个概念停靠点。"
    ) % anchor["text"]
    try:
        reply = providers.chat(
            cfg, BARE_SYSTEM, user,
            temperature=0.2, max_tokens=512, timeout=timeout, thinking="disabled",
        )
        err = None
    except Exception as e:
        reply = ""
        err = "%s: %s" % (type(e).__name__, e)
    mapped = map_bare_to_ids(reply or "", trunk)
    return {
        "arm": "bare",
        "ok": err is None,
        "error": err,
        "raw_reply": reply,
        "proposed_raw": reply,
        "mapped_node_ids": mapped,
        "needs_author_commit": True,
    }


def run_tree(cfg, anchor: dict, trunk: dict, timeout: int) -> dict:
    compact = compact_trunk(trunk)
    ids = sorted(trunk_id_set(trunk))
    user = (
        "TRUNK (compact JSON):\n%s\n\n"
        "允许的 node id 列表：%s\n\n"
        "定位锚段落（非树内容源）：\n%s\n\n"
        "请只从上述 id 中选择 1–2 个停靠点，输出规定 JSON；"
        "needs_author_commit 必须为 true。"
    ) % (
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")),
        json.dumps(ids, ensure_ascii=False),
        anchor["text"],
    )
    try:
        reply = providers.chat(
            cfg, TREE_SYSTEM, user,
            temperature=0.2, max_tokens=768, timeout=timeout, thinking="disabled",
        )
        err = None
    except Exception as e:
        reply = ""
        err = "%s: %s" % (type(e).__name__, e)

    parsed = extract_json_obj(reply or "")
    proposed = []
    edges = []
    rationale = ""
    on_trunk = False
    if isinstance(parsed, dict):
        proposed = [x for x in (parsed.get("proposed_node_ids") or []) if isinstance(x, str)]
        # filter to trunk only
        allowed = trunk_id_set(trunk)
        on_trunk = all(p in allowed for p in proposed) if proposed else False
        proposed = [p for p in proposed if p in allowed]
        edges = parsed.get("edges") or []
        rationale = parsed.get("rationale") or ""
    return {
        "arm": "tree",
        "ok": err is None,
        "error": err,
        "raw_reply": reply,
        "parsed": parsed,
        "proposed_node_ids": proposed,
        "edges": edges,
        "rationale": rationale,
        "on_trunk": on_trunk,
        "needs_author_commit": True,
    }


def write_summary(path: Path, meta: dict, records: list, trunk: dict):
    lines = []
    lines.append("# Localization smoke run summary")
    lines.append("")
    lines.append("- timestamp: %s" % meta.get("timestamp_label"))
    lines.append("- provider: %s" % meta.get("provider"))
    lines.append("- model: %s" % meta.get("model"))
    lines.append("- masked_key: %s" % meta.get("masked_key"))
    lines.append("- probe_ok: %s" % meta.get("probe_ok"))
    lines.append("- probe_detail: %s" % meta.get("probe_detail"))
    lines.append("- theory: generate≠commit; anchors≠tree content; S3 CLOSED; smoke only")
    lines.append("")
    lines.append("## Per-anchor")
    lines.append("")
    for rec in records:
        a = rec["anchor_id"]
        gold = rec.get("gold_node_ids") or []
        lines.append("### %s" % a)
        lines.append("- gold: %s" % ", ".join(gold))
        bare = rec["bare"]
        tree = rec["tree"]
        if bare.get("ok"):
            lines.append("- bare mapped: %s" % (bare.get("mapped_node_ids") or ["(unmapped)"]))
            snippet = (bare.get("raw_reply") or "").replace("\n", " ")[:180]
            lines.append("- bare raw (trunc): %s" % snippet)
        else:
            lines.append("- bare ERROR: %s" % bare.get("error"))
        if tree.get("ok"):
            lines.append(
                "- tree proposed: %s (on_trunk=%s)"
                % (tree.get("proposed_node_ids"), tree.get("on_trunk"))
            )
            lines.append("- tree rationale: %s" % ((tree.get("rationale") or "")[:200]))
        else:
            lines.append("- tree ERROR: %s" % tree.get("error"))
        lines.append("")
    lines.append("## Does / does not prove")
    lines.append("")
    lines.append("- Proves (weak): scripts can dual-arm localize onto an explicit trunk.")
    lines.append("- Does NOT prove: understanding achieved; VERIFY main-table gains; agent memory/skills fitting.")
    lines.append("- Commit: none — proposals only (`needs_author_commit: true`).")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="知音-tree localization smoke demo")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="cowrite config.json path")
    ap.add_argument("--trunk", default=str(DEMO_DIR / "trunk_v0.json"))
    ap.add_argument("--anchors", default=str(DEMO_DIR / "anchors.json"))
    ap.add_argument("--timeout", type=int, default=45, help="per-call timeout seconds")
    ap.add_argument("--probe-timeout", type=int, default=40)
    ap.add_argument("--skip-run-if-probe-fails", action="store_true", default=True)
    args = ap.parse_args()

    cfg_path = Path(args.config)
    trunk_path = Path(args.trunk)
    anchors_path = Path(args.anchors)
    runs_dir = DEMO_DIR / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    cfg_raw = load_json(cfg_path)
    cfg = providers.resolve(cfg_raw)
    trunk = load_json(trunk_path)
    anchors_doc = load_json(anchors_path)
    anchors = anchors_doc.get("anchors") or []

    masked = providers.mask_key(cfg.get("api_key") or "")
    print("=== 知音 localization smoke ===")
    print("config: %s" % cfg_path)
    print("provider: %s  model: %s" % (cfg.get("provider"), cfg.get("model")))
    print("base_url: %s" % cfg.get("base_url"))
    print("masked_key: %s" % masked)
    print("configured: %s" % providers.configured(cfg))
    print("trunk nodes: %d" % len(trunk.get("nodes") or []))
    print("anchors: %d" % len(anchors))
    print("")

    print("--- probe ---")
    t0 = time.time()
    probe_ok, probe_detail = providers.probe(cfg, timeout=args.probe_timeout)
    probe_sec = round(time.time() - t0, 2)
    print("probe_ok=%s (%.2ss)" % (probe_ok, probe_sec))
    print("probe_detail: %s" % probe_detail)
    print("")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Asia/Shanghai label (box already in that zone)
    ts_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")
    run_path = runs_dir / ("run_%s.jsonl" % ts)
    summary_path = runs_dir / "summary.md"

    meta = {
        "timestamp": ts,
        "timestamp_label": ts_label,
        "provider": cfg.get("provider"),
        "model": cfg.get("model"),
        "base_url": cfg.get("base_url"),
        "masked_key": masked,
        "probe_ok": probe_ok,
        "probe_detail": probe_detail,
        "probe_sec": probe_sec,
        "trunk": str(trunk_path),
        "anchors": str(anchors_path),
        "theory_lock": "generate≠commit; anchors≠tree; S3 CLOSED; smoke",
    }

    records = []
    if not probe_ok:
        print("Probe failed — skipping dual-arm API calls (scripts+tree still delivered).")
        # still write empty-ish run log with probe failure
        with run_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "meta", **meta}, ensure_ascii=False) + "\n")
            f.write(
                json.dumps(
                    {
                        "type": "blocker",
                        "reason": "probe_failed",
                        "detail": probe_detail,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        write_summary(summary_path, meta, records, trunk)
        print("wrote: %s" % run_path)
        print("wrote: %s" % summary_path)
        return 1

    print("--- dual-arm localize ---")
    with run_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "meta", **meta}, ensure_ascii=False) + "\n")
        for anc in anchors:
            print("anchor %s ..." % anc["id"])
            bare = run_bare(cfg, anc, trunk, timeout=args.timeout)
            tree = run_tree(cfg, anc, trunk, timeout=args.timeout)
            rec = {
                "type": "anchor_result",
                "anchor_id": anc["id"],
                "gold_node_ids": anc.get("gold_node_ids"),
                "bare": {
                    k: v
                    for k, v in bare.items()
                    if k != "raw_reply" or True  # keep raw for audit; no api_key there
                },
                "tree": tree,
            }
            # ensure no key leakage from accidental dumps
            blob = json.dumps(rec, ensure_ascii=False)
            if cfg.get("api_key") and cfg["api_key"] in blob:
                blob = blob.replace(cfg["api_key"], masked)
            f.write(blob + "\n")
            records.append(rec)
            print(
                "  bare_ok=%s mapped=%s | tree_ok=%s proposed=%s on_trunk=%s"
                % (
                    bare.get("ok"),
                    bare.get("mapped_node_ids"),
                    tree.get("ok"),
                    tree.get("proposed_node_ids"),
                    tree.get("on_trunk"),
                )
            )

    write_summary(summary_path, meta, records, trunk)
    print("")
    print("wrote: %s" % run_path)
    print("wrote: %s" % summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
