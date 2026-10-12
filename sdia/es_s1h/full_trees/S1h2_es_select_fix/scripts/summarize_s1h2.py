# -*- coding: utf-8 -*-
"""Summarize S1h2: tune grid (lr selection by pre-written rule) and science arms (k/8, Wilson)."""
from __future__ import annotations
import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THR = json.loads((ROOT / "frozen" / "thresholds_S1h2.json").read_text(encoding="utf-8"))


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def crit(r):
    e = r["eval"]
    return {
        "ret": e["return"]["mean"], "A": r["A_return"], "C1": e["C1"]["pass"], "C2": e["C2"]["pass"],
        "dec": e["C2"]["decode_acc"], "leak": e["C2_leak"]["mean"], "C3": e["C3"]["pass"],
        "flip": e["C3"]["flip_rate"], "C4": e["C4pp"].get("pass", False), "C6": e["C6"]["pass"],
        "void": r["seed_void"], "pass": r["pass"],
        "pm_last": r["evo"].get("pop_mean_last"), "pm_max": r["evo"].get("pop_mean_max"),
        "tn": (r["evo"].get("hist_tail") or [{}])[-1].get("theta_norm"),
    }


def tune():
    rows = {}
    for p in sorted((ROOT / "tune").glob("result_arm_ES_main_seed*_lr*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        rows.setdefault(r["lr"], {})[r["seed"]] = crit(r)
    out = {"per_lr": {}}
    print("== tune grid ES_main (N=4,K[30,70]) on tune seeds ==")
    for lr in sorted(rows):
        d = rows[lr]
        rets = [d[s]["ret"] for s in sorted(d)]
        npass = sum(d[s]["pass"] for s in d)
        mean = sum(rets) / len(rets)
        out["per_lr"][lr] = {"mean_ret": mean, "n_pass": npass, "n": len(d),
                             "seeds": {s: d[s] for s in sorted(d)}}
        print(f"lr={lr:<6} n={len(d)} mean_ret={mean:.3f} pass={npass}/{len(d)} | " +
              " ".join(f"{s}:ret={d[s]['ret']:.2f},pm={d[s]['pm_last']:.2f},|th|={d[s]['tn']:.0f},"
                       f"{'P' if d[s]['pass'] else '-'}" for s in sorted(d)))
    complete = [lr for lr in rows if len(rows[lr]) == len(THR["tune_seeds"])]
    if len(complete) == len(THR["lr_grid"]):
        ranked = sorted(complete, key=lambda lr: -out["per_lr"][lr]["mean_ret"])
        a, b = ranked[0], ranked[1]
        pick = a
        if out["per_lr"][a]["mean_ret"] - out["per_lr"][b]["mean_ret"] <= 0.02:
            ka, kb = out["per_lr"][a]["n_pass"], out["per_lr"][b]["n_pass"]
            pick = a if ka > kb else b if kb > ka else min(a, b)
        out["selected_lr"] = pick
        print(f"SELECTED lr={pick} (rule: max mean ret; tie<=0.02 -> more pass -> smaller lr)")
    return out


def science():
    out = {}
    for arm in ("ES_easy", "ES_main", "ES_easy_legacy"):
        rs = []
        for s in THR["seeds"]:
            p = ROOT / "logs" / f"result_arm_{arm}_seed{s}.json"
            if p.exists():
                rs.append((s, crit(json.loads(p.read_text(encoding="utf-8")))))
        if not rs:
            continue
        k = sum(c["pass"] for _, c in rs)
        nv = sum(c["void"] for _, c in rs)
        lo, hi = wilson(k, 8)
        out[arm] = {"k": k, "n_done": len(rs), "denom": 8, "void": nv, "wilson95": [lo, hi],
                    "group_pass": k >= 7, "seeds": {s: c for s, c in rs}}
        print(f"\n== {arm}: {k}/8 (done {len(rs)}, VOID {nv}) Wilson95=[{lo:.3f},{hi:.3f}] group_pass={k >= 7}")
        for s, c in rs:
            print(f"  {s}: ret={c['ret']:.3f} A={c['A']:.3f} C1={c['C1']:d} C2={c['C2']:d}({c['dec']:.2f}) "
                  f"leak={c['leak']:.3f} C3={c['C3']:d}({c['flip']:.2f}) C4={c['C4']:d} C6={c['C6']:d} "
                  f"void={c['void']:d} pass={c['pass']:d} pm_last={c['pm_last']:.3f} |th|={c['tn'] or float('nan'):.1f}")
    return out


if __name__ == "__main__":
    res = {"tune": tune(), "science": science()}
    if "--write" in sys.argv:
        (ROOT / "logs" / "summary_S1h2.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
