# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
THR = json.loads((ROOT / "frozen" / "thresholds_E2b.json").read_text(encoding="utf-8"))
LOGS = ROOT / "logs"
SEEDS = list(THR["seeds"])

def wilson(k, n, z=1.96):
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = k / n
    den = 1 + z**2 / n
    cen = (p + z**2 / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return float(p), float(cen - half), float(cen + half)

per = []
n_pass = n_void = n_miss = 0
n_perm_fail = n_fail = 0
c_ok = 0
for s in SEEDS:
    p = LOGS / f"result_seed{s}.json"
    if not p.exists():
        n_miss += 1
        per.append({"seed": s, "status": "MISSING"})
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    ag = d["arms"]["G_RL_GRU"]
    c4 = ag.get("C4pp", {})
    fails = []
    if not ag.get("C1", {}).get("pass"): fails.append("C1")
    if not ag.get("C2", {}).get("pass"): fails.append("C2")
    if ag.get("void_leak"): fails.append("leak_VOID")
    if not ag.get("C3", {}).get("pass"): fails.append("C3")
    if not c4.get("pass"): fails.append("C4pp")
    if not ag.get("C6", {}).get("pass"): fails.append("C6")
    if d.get("seed_void"):
        status = "VOID"; n_void += 1
    elif d.get("seed_MAIN_accept"):
        status = "PASS"; n_pass += 1
    else:
        status = "FAIL"; n_fail += 1
        if d.get("permeability_pattern"):
            n_perm_fail += 1
    if d.get("seed_C_integrity"):
        c_ok += 1
    per.append({
        "seed": s, "status": status,
        "A_ret": d.get("A_return"),
        "G_ret": ag.get("return", {}).get("mean"),
        "G_C1_C6": d.get("G_pass_C1_C6"),
        "G_C7": d.get("G_pass_C7"),
        "C_integrity": d.get("seed_C_integrity"),
        "C2": ag.get("C2", {}).get("decode_acc"),
        "C3": ag.get("C3", {}).get("flip_rate"),
        "C4pp": c4.get("pass"),
        "i_directional": c4.get("i_directional"),
        "iii_specific": c4.get("iii_specific"),
        "permeability_pattern": d.get("permeability_pattern"),
        "C6": ag.get("C6", {}).get("return"),
        "epochs": d.get("evo", {}).get("G_RL_GRU", {}).get("epochs_ran"),
        "config_id": d.get("config_id"),
        "wall_s": d.get("wall_s"),
        "fails_G": fails,
        "sparse_dwf": (c4.get("sparse") or {}).get("dwf"),
        "every_dwf": (c4.get("every") or {}).get("dwf"),
    })

p, lo, hi = wilson(n_pass, 8)
# path verdict (pre-registered; mutual exclusive A/B)
path = None
routing = None
if n_miss:
    path = "INCOMPLETE"
    routing = "missing seeds"
elif c_ok < 7:
    path = "INTEGRITY_VOID"
    routing = THR["routing"]["C_integrity_fail"]
elif n_pass >= 7:
    path = "A_efficiency"
    routing = THR["routing"]["path_A"]
elif n_fail > 0 and n_perm_fail >= max(1, (n_fail + 1) // 2):
    # ≥半数非 VOID 失败籽 match write-ok/hold-fail
    path = "B_structural"
    routing = THR["routing"]["path_B"]
else:
    path = "inconclusive_other_fail"
    routing = THR["routing"]["inconclusive"]

summary = {
    "schema": "e2b_c4pp_permeability_summary_v1",
    "denominator": 8,
    "MAIN": "G_RL_GRU",
    "label": THR["label"],
    "pass": n_pass,
    "void": n_void,
    "fail": n_fail,
    "missing": n_miss,
    "n_permeability_pattern_among_fails": n_perm_fail,
    "wilson95": [lo, hi],
    "C_integrity_ok_seeds": c_ok,
    "path_verdict": path,
    "routing_applied": routing,
    "science_config_id": (LOGS / "science_config_id.txt").read_text().strip() if (LOGS / "science_config_id.txt").exists() else None,
    "thresholds_sha256": (ROOT / "frozen" / "thresholds_E2b.sha256").read_text().split()[0],
    "per_seed": per,
    "s3_status": "CLOSED",
}
(LOGS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
