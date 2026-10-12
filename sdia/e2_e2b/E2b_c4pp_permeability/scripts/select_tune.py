# -*- coding: utf-8 -*-
"""Select config by pre-registered rule; write tune/selected_config.json"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THR = json.loads((ROOT / "frozen" / "thresholds_E2b.json").read_text(encoding="utf-8"))
TUNE = ROOT / "tune"
CONFIGS = [c["id"] for c in THR["tune_grid"]]
SEEDS = [100, 101]  # minimum per thresholds

rows = []
for cfg in CONFIGS:
    n_main = n_iii = n_perm = 0
    rets = []
    present = 0
    for s in SEEDS:
        p = TUNE / f"result_seed{s}_{cfg}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        present += 1
        if d.get("seed_MAIN_accept"):
            n_main += 1
        c4 = d.get("arms", {}).get("G_RL_GRU", {}).get("C4pp", {})
        if c4.get("iii_specific"):
            n_iii += 1
        if d.get("permeability_pattern"):
            n_perm += 1
        rets.append(float(d.get("arms", {}).get("G_RL_GRU", {}).get("return", {}).get("mean", -1)))
    mean_ret = sum(rets) / len(rets) if rets else -1e9
    rows.append({
        "config_id": cfg, "n_present": present, "n_seeds": len(SEEDS),
        "n_MAIN_accept": n_main, "n_C4iii_pass": n_iii, "n_permeability_pattern": n_perm,
        "mean_G_return": mean_ret,
    })

# selection: max n_MAIN, then n_C4iii, then mean ret; tie → ceil_lr1e3
def key(r):
    prefer = 1 if r["config_id"] == "ceil_lr1e3" else 0
    return (r["n_MAIN_accept"], r["n_C4iii_pass"], r["mean_G_return"], prefer)

complete = [r for r in rows if r["n_present"] == len(SEEDS)]
if not complete:
    # fallback: any present; else default ceil_lr1e3
    pool = [r for r in rows if r["n_present"] > 0] or [{"config_id": "ceil_lr1e3", "n_MAIN_accept": 0, "n_C4iii_pass": 0, "mean_G_return": -1e9, "fallback": True}]
else:
    pool = complete
best = sorted(pool, key=key, reverse=True)[0]
out = {
    "selected_config_id": best["config_id"],
    "rows": rows,
    "rule": THR["tune_selection_rule"],
    "selected_row": best,
}
(TUNE / "selected_config.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
