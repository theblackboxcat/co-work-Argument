#!/usr/bin/env python3
"""E2 summarizer. Denominator ALWAYS 8. MAIN=G_RL_GRU."""
import json, math, os
from pathlib import Path
D = Path(__file__).resolve().parent.parent
SEEDS = [200, 205, 210, 211, 212, 216, 218, 219]

def wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, c - h), min(1.0, c + h)]

def g(d, *ks):
    for k in ks:
        if d is None or k not in d:
            return None
        d = d[k]
    return d

rows = []
for s in SEEDS:
    f = D / "logs" / f"result_seed{s}.json"
    if not f.exists():
        rows.append({"seed": s, "status": "MISSING"})
        continue
    r = json.loads(f.read_text(encoding="utf-8"))
    void = bool(r.get("seed_void"))
    main = bool(r.get("seed_MAIN_accept"))
    c_ok = bool(r.get("seed_C_integrity"))
    ag = r["arms"]["G_RL_GRU"]
    ac = r["arms"]["C"]
    aa = r["arms"]["A"]
    status = "VOID" if void else ("PASS" if main else "FAIL")
    rows.append({
        "seed": s, "status": status,
        "A_ret": g(aa, "return", "mean"),
        "C_ret": g(ac, "return", "mean"),
        "G_ret": g(ag, "return", "mean"),
        "G_C1_C6": g(ag, "all_C1_C6"),
        "G_C7": r.get("G_pass_C7"),
        "C_C1_C6": g(ac, "all_C1_C6"),
        "C_C7": r.get("C_pass_C7"),
        "leak_mean_G": g(ag, "C2_leak", "mean"),
        "C2": g(ag, "C2", "decode_acc"),
        "C3": g(ag, "C3", "flip_rate"),
        "C4pp": g(ag, "C4pp", "pass"),
        "C6": g(ag, "C6", "return"),
        "epochs": g(r, "evo", "G_RL_GRU", "epochs_ran"),
        "train_best": g(r, "evo", "G_RL_GRU", "best_ret_train"),
        "wall_s": r.get("wall_s"),
        "fails_G": [k for k in ["C1", "C2", "C3", "C4pp", "C5", "C6"]
                    if not (ag.get(k) or {}).get("pass", False)],
    })

k = sum(x["status"] == "PASS" for x in rows)
v = sum(x["status"] == "VOID" for x in rows)
m = sum(x["status"] == "MISSING" for x in rows)
c_int = sum(1 for x in rows if x.get("C_C7"))
out = {
    "schema": "e2_s2c_learnable_summary_v1",
    "denominator": 8,
    "MAIN": "G_RL_GRU",
    "label": "L2-self · 通用门控架构档",
    "pass": k, "void": v, "missing": m,
    "wilson95": wilson(k, 8),
    "C_integrity_pass_C7": c_int,
    "per_seed": rows,
    "s3_status": "CLOSED",
}
if m:
    route = "INCOMPLETE"
elif c_int < 7:
    route = "实验完整性风险（C 阳控未组过）"
elif k >= 7:
    route = "E2 PASS（L2-self · 通用门控架构档 @ S2c）→ S3 CLOSED；STOP"
else:
    route = "E2 FAIL → STOP；不开 S3"
out["routing_applied"] = route
thr_sha = (D / "frozen" / "thresholds_E2.sha256").read_text().split()[0]
out["thresholds_sha256"] = thr_sha
(D / "logs" / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"G_RL_GRU MAIN {k}/8 VOID={v} MISSING={m} wilson95=[{out['wilson95'][0]:.3f},{out['wilson95'][1]:.3f}]")
print("C_integrity_C7:", c_int, "/8")
print("routing:", route)
for x in rows:
    print(f"  seed{x['seed']}: {x['status']} G_ret={x.get('G_ret')} C2={x.get('C2')} C3={x.get('C3')} C4={x.get('C4pp')} fails={x.get('fails_G')}")
