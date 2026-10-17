#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E05b Arm-C 升级 · 两轮：Turn1=auth B 定位（与 CTRL 字节相同）；Turn2=中性探针（独立调用，看不到 Turn1）。
3 锚 × 3 rep × 2 轮 = 18 次实验调用（+1 次 probe 连通性 ping）。
ARMC_MOCK=1 → 不发真实请求（dry-run）。"""
import argparse, hashlib, json, os, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_v2  # 与 CTRL 包字节相同
from lib import providers
import probes

CTRL_RUN_V2_SHA256 = "099c977e4d482aaa930e72ab29b4ab1828e3d49000db904d5540f00cc93180cf"
CTRL_COVERED_SYSTEM_SHA256 = "c13c5546c2aa9c44a58a040b1edaf2c722c2577ad4e54edef0641b14c333f76d"
DUAL_BIAS_MARKERS = ["dual-stop 同址摄取加压", "默认偏置双停", "双停共现"]
# 与 CTRL（run_v2.run_arm）完全同参
T1_PARAMS = dict(temperature=0.2, max_tokens=700, thinking="disabled")
T2_PARAMS = dict(temperature=0.2, max_tokens=700, thinking="disabled")


def preflight():
    f_sha = hashlib.sha256((HERE / "run_v2.py").read_bytes()).hexdigest()
    s_sha = hashlib.sha256(run_v2.COVERED_SYSTEM.encode("utf-8")).hexdigest()
    if f_sha != CTRL_RUN_V2_SHA256:
        raise SystemExit("FATAL: run_v2.py differs from CTRL pack (sha %s)" % f_sha)
    if s_sha != CTRL_COVERED_SYSTEM_SHA256:
        raise SystemExit("FATAL: COVERED_SYSTEM differs from CTRL (sha %s)" % s_sha)
    if any(m in run_v2.COVERED_SYSTEM for m in DUAL_BIAS_MARKERS):
        raise SystemExit("FATAL: dual-bias paragraph present in COVERED_SYSTEM")
    probes.assert_neutral()
    print("preflight_ok run_v2_sha=%s… covered_system_sha=%s… no_dual_bias probes_neutral" % (f_sha[:12], s_sha[:12]))
    return f_sha, s_sha


def mock_chat(system, user, anchor):
    """Deterministic fake replies for dry-run only."""
    if system == run_v2.COVERED_SYSTEM:
        nodes = {"E05b_alignment_confirmation": ["S03_allegorical_transform", "S14_shared_stop"],
                 "E05a_huaxing_theory_monologue": ["S03_allegorical_transform", "S20_zhiyin_align"],
                 "X01_dialogue_register_label_paraphrase_s07": ["S07_special_solution", "S20_zhiyin_align"]}[anchor["id"]]
        return json.dumps({"nodes": nodes, "edges": [], "needs_author_commit": True, "rationale_short": "mock"}, ensure_ascii=False)
    t = anchor["text"]
    if anchor["id"].startswith("E05b"):
        q, k = t[-12:], 1          # real substring → quote valid
    elif anchor["id"].startswith("X01"):
        q, k = "无", 2
    else:
        q, k = "这句并不存在于原文", 1  # fabricated → quote invalid → not mutual
    return json.dumps({"a_uptake_quote": q, "b_same_thing": "yes", "b_free_text": "mock free text",
                       "c_kind": k, "c_reason": "mock"}, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--trunk", required=True)
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    f_sha, s_sha = preflight()
    mock = os.environ.get("ARMC_MOCK") == "1"

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    trunk = json.loads(Path(args.trunk).read_text(encoding="utf-8"))
    anchors = json.loads(Path(args.anchors).read_text(encoding="utf-8"))["anchors"]
    want = ["E05b_alignment_confirmation", "E05a_huaxing_theory_monologue",
            "X01_dialogue_register_label_paraphrase_s07"]
    anchors = [a for a in anchors if a["id"] in want]
    assert len(anchors) == 3, [a["id"] for a in anchors]

    if mock:
        print("probe_ok=MOCK (no network)")
    else:
        ok, detail = providers.probe(cfg, timeout=40)
        print("probe_ok=%s %s" % (ok, detail))
        if not ok:
            return 2

    V = run_v2.views(trunk)
    ids = sorted({n["id"] for n in trunk["nodes"]})
    ae = {e for e in (run_v2.norm_edge(x) for x in trunk["edges"]) if e}

    def call(system, user, anchor, params):
        if mock:
            return mock_chat(system, user, anchor)
        return providers.chat(cfg, system, user, timeout=args.timeout, **params)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_calls = 0
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "meta", "ts": datetime.now().strftime("%Y%m%d_%H%M%S"),
                            "experiment": "E05b_ArmC_upgrade_elicitation_discrimination",
                            "trunk": Path(args.trunk).name, "repeat": args.repeat,
                            "mock": mock, "run_v2_sha256": f_sha, "covered_system_sha256": s_sha,
                            "t1_params": T1_PARAMS, "t2_params": T2_PARAMS,
                            "turn2_sees_turn1": False, "gloss_blind_variant": False},
                           ensure_ascii=False) + "\n")
        for a in anchors:
            for r in range(args.repeat):
                # Turn1 — identical to CTRL run_v2.run_arm
                u1 = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                      % (V["covered"], json.dumps(ids, ensure_ascii=False), a["text"]))
                raw1 = call(run_v2.COVERED_SYSTEM, u1, a, T1_PARAMS); n_calls += 1
                p1 = run_v2.extract(raw1) or {}
                nodes = [x for x in (p1.get("nodes") or []) if isinstance(x, str) and x in set(ids)]
                edges, off = [], []
                for x in p1.get("edges") or []:
                    ne = run_v2.norm_edge(x)
                    if ne is None:
                        continue
                    (edges if ne in ae else off).append(x)
                # Turn2 — independent call, anchor text only (no Turn1 output, no trunk)
                raw2 = call(probes.PROBE_SYSTEM, probes.probe_user(a["text"]), a, T2_PARAMS); n_calls += 1
                p2 = run_v2.extract(raw2) or {}
                rec = {"type": "rep", "anchor_id": a["id"], "rep": r + 1, "gold_nodes": a["gold"]["nodes"],
                       "turn1": {"nodes": nodes, "edges": edges, "offchart_edges": off,
                                 "rationale": p1.get("rationale_short", ""), "raw": raw1},
                       "turn2": {"parsed": p2, "raw": raw2}}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print("[%s] rep%d t1=%s t2.c=%s quote=%r" % (a["id"], r + 1, ",".join(nodes) or "(空)",
                      p2.get("c_kind"), str(p2.get("a_uptake_quote", ""))[:30]))
        f.write(json.dumps({"type": "end", "n_calls": n_calls}, ensure_ascii=False) + "\n")
    print("wrote %s  n_calls=%d" % (out, n_calls))
    return 0


if __name__ == "__main__":
    sys.exit(main())
