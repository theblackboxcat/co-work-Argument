# -*- coding: utf-8 -*-
"""Select fair-RNN config by preregistered rule; write tune/selected_config.json"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THR = json.loads((ROOT / "frozen" / "thresholds_fair_RNN.json").read_text(encoding="utf-8"))
TUNE = ROOT / "tune"
CONFIGS = [c["id"] for c in THR["tune_grid"]]
SEEDS = list(THR["tune_seeds"])
MIN_PRESENT = int(THR["tune_selection_rule"].get("min_tune_seeds_present", 3))

rows = []
for cfg in CONFIGS:
    n_proxy = 0
    rets = []
    present = 0
    epochs = []
    hiddens = []
    for s in SEEDS:
        p = TUNE / f"result_arm_G_RL_RNN_fair_seed{s}_{cfg}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        present += 1
        if d.get("proxy_pass") or d.get("pass"):
            n_proxy += 1
        br = d.get("evo", {}).get("best_ret_train")
        if br is None:
            br = d.get("evo", {}).get("ret_curve_max", -1)
        rets.append(float(br if br is not None else -1))
        epochs.append(int(d.get("config", {}).get("epochs_max") or d.get("evo", {}).get("epochs_max") or 9999))
        hiddens.append(int(d.get("config", {}).get("hidden") or d.get("evo", {}).get("hidden") or 9999))
    mean_ret = sum(rets) / len(rets) if rets else -1e9
    rows.append({
        "config_id": cfg,
        "n_present": present,
        "n_seeds": len(SEEDS),
        "n_proxy_pass": n_proxy,
        "mean_best_ret_train": mean_ret,
        "epochs_max": min(epochs) if epochs else 9999,
        "hidden": min(hiddens) if hiddens else 9999,
    })

def key(r):
    # maximize proxy; then mean ret; then prefer fewer epochs, smaller hidden; tie → baseline_s1g
    prefer = 1 if r["config_id"] == "baseline_s1g" else 0
    return (r["n_proxy_pass"], r["mean_best_ret_train"], -r["epochs_max"], -r["hidden"], prefer)

complete = [r for r in rows if r["n_present"] >= MIN_PRESENT]
if not complete:
    pool = [r for r in rows if r["n_present"] > 0] or [{
        "config_id": "baseline_s1g", "n_proxy_pass": 0, "mean_best_ret_train": -1e9,
        "epochs_max": 800, "hidden": 32, "fallback": True, "n_present": 0,
    }]
else:
    pool = complete
best = sorted(pool, key=key, reverse=True)[0]
out = {
    "selected_config_id": best["config_id"],
    "rows": rows,
    "rule": THR["tune_selection_rule"],
    "selected_row": best,
    "S3": "CLOSED",
    "forbid": ["tune on science seeds", "claim 门控普遍必要", "open S3", "reopen E2b"],
}
(TUNE / "selected_config.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
