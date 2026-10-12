# -*- coding: utf-8 -*-
"""Dx2 leak ruler: diagnose within-seed SD, calibrate n_rep, pre-screen clean seeds >=200."""
from __future__ import annotations
import json, hashlib, time, math
from pathlib import Path
import numpy as np
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))
import s1_env_s1 as E

LOGS = ROOT / "logs"
FROZEN = ROOT / "frozen"
LOGS.mkdir(exist_ok=True)

THR = json.loads((FROZEN / "thresholds_Dx2.json").read_text(encoding="utf-8"))
THR_HASH = hashlib.sha256((FROZEN / "thresholds_Dx2.json").read_bytes()).hexdigest()

N = 4
T = int(THR["env"]["T"])
K_LO, K_HI = THR["env"]["K_switch_range"]
WIN = int(THR["acceptance_per_seed_reused"]["C2_leak_window"])
N_EPS = int(THR["acceptance_per_seed_reused"]["n_eps_default"])
LEAK_MAX = float(THR["acceptance_per_seed_reused"]["C2_leak_max_N4"])
MARGIN_MAX = float(THR["prescreen"]["accept_leak_mean_max"])
SE_TARGET = float(THR["diagnosis"]["SE_target"])
VOID_SEEDS = list(THR["diagnosis"]["void_seeds"])
NONVOID_SEEDS = list(THR["diagnosis"]["nonvoid_seeds"])
TUNE_SEEDS = list(THR["diagnosis"]["tune_seeds_for_sample_size"])
N_REP0 = int(THR["diagnosis"]["n_rep_initial"])
SEED_START = int(THR["prescreen"]["seed_start"])
N_CLEAN = int(THR["prescreen"]["n_clean_target"])

AGENT = E.make_memoryless(np.random.default_rng(0), N)


def probe_seed(science_seed: int, i: int) -> int:
    return int(science_seed) + 10007 + int(i) * 100003


def measure_leak(science_seed: int, i: int, n_eps: int = N_EPS) -> float:
    return float(E.obs_window_decode_acc(
        AGENT, N=N, T=T, seed=probe_seed(science_seed, i),
        n_eps=n_eps, window=WIN, k_lo=K_LO, k_hi=K_HI,
    ))


def summarize(samples):
    a = np.asarray(samples, float)
    mean = float(a.mean())
    sd = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    se = sd / math.sqrt(len(a)) if len(a) else float("nan")
    return {
        "samples": [float(x) for x in a],
        "mean": mean,
        "sd": sd,
        "se": se,
        "min": float(a.min()),
        "max": float(a.max()),
        "n": len(a),
        "hist_probe_i0": float(a[0]) if len(a) else None,
        "void_if_i0": bool(a[0] > LEAK_MAX) if len(a) else None,
        "void_if_mean": bool(mean > LEAK_MAX),
        "pass_margin_mean": bool(mean <= MARGIN_MAX),
    }


def diagnose_seeds(seeds, n_rep, tag):
    out = {}
    for s in seeds:
        samples = [measure_leak(s, i) for i in range(n_rep)]
        out[str(s)] = summarize(samples)
        st = out[str(s)]
        print(f"  [{tag}] seed={s:4d} mean={st['mean']:.4f} sd={st['sd']:.4f} se={st['se']:.4f} "
              f"i0={st['hist_probe_i0']:.4f} range=[{st['min']:.3f},{st['max']:.3f}]", flush=True)
    return out


def calibrate_n_rep(tune_seeds, se_target=SE_TARGET, max_rep=40, n_eps=N_EPS):
    """Find smallest n_rep such that median SE across tune seeds < se_target.
    Uses progressive pooling of independent probes."""
    # First get a large pool to estimate sd and required n
    pool_n = max_rep
    per = {}
    for s in tune_seeds:
        samples = [measure_leak(s, i, n_eps=n_eps) for i in range(pool_n)]
        per[str(s)] = samples
        print(f"  [tune] seed={s} pool{pool_n} mean={np.mean(samples):.4f} sd={np.std(samples,ddof=1):.4f}", flush=True)

    # sd of single probe (pooled estimate)
    sds = [float(np.std(v, ddof=1)) for v in per.values()]
    sd_med = float(np.median(sds))
    # n for SE = sd/sqrt(n) < target
    n_needed = int(math.ceil((sd_med / se_target) ** 2)) if sd_med > 0 else 1
    n_needed = max(5, min(pool_n, n_needed))

    # also try higher n_eps as alternative
    alt = {}
    for n_eps_try in (24, 48):
        sds2 = []
        for s in tune_seeds:
            samples = [measure_leak(s, i, n_eps=n_eps_try) for i in range(10)]
            sds2.append(float(np.std(samples, ddof=1)))
            print(f"  [tune n_eps={n_eps_try}] seed={s} sd10={sds2[-1]:.4f} mean={np.mean(samples):.4f}", flush=True)
        alt[str(n_eps_try)] = {"sd_median": float(np.median(sds2)),
                               "n_rep_for_se": int(math.ceil((np.median(sds2) / se_target) ** 2))}

    # Choose: prefer keeping n_eps=12 with larger n_rep if reasonable; else raise n_eps
    choice = {"n_eps": n_eps, "n_rep": n_needed, "sd_median_single": sd_med,
              "se_at_choice": sd_med / math.sqrt(n_needed),
              "alternatives_n_eps": alt}
    # If n_needed > 25, prefer n_eps=48 if it reduces total work
    work_12 = n_needed * 12
    for k, v in alt.items():
        ne = int(k)
        nr = max(5, v["n_rep_for_se"])
        if nr * ne < work_12 and v["sd_median"] > 0:
            choice = {"n_eps": ne, "n_rep": nr, "sd_median_single": v["sd_median"],
                      "se_at_choice": v["sd_median"] / math.sqrt(nr),
                      "alternatives_n_eps": alt,
                      "switched_from_n_eps12_n_rep": n_needed}
            work_12 = nr * ne  # keep searching cheaper
    return choice, per


def investigate_generator(seeds, n_eps_traj=32):
    """Cue-bleed diagnostics: fraction of non-cue windows that still contain a cue frame."""
    rng_root = np.random.default_rng(12345)
    rows = {}
    for s in seeds:
        # use historical probe seed structure for one long look
        ps = probe_seed(s, 0)
        rng = np.random.default_rng(ps)
        cue_in_window = []
        ks = []
        switches = []
        for ep in range(n_eps_traj):
            env = E._env(N, T, cue_every=False, k_lo=K_LO, k_hi=K_HI)
            r2 = np.random.default_rng(int(rng.integers(1 << 31)))
            obs = env.reset(r2)
            buf_cue = []
            for t in range(T):
                cue_vis = bool(env.cue_every or env._at_switch(env.t))
                buf_cue.append(1 if cue_vis else 0)
                if len(buf_cue) > WIN:
                    buf_cue.pop(0)
                if (not cue_vis) and len(buf_cue) == WIN:
                    cue_in_window.append(1 if any(buf_cue) else 0)
                # step with dummy action 0
                obs, r, done, info = env.step(0, r2)
                if done:
                    break
            ks.extend(env._seg_Ks)
            switches.append(len(env._switches))
        rows[str(s)] = {
            "frac_noncue_windows_with_cue_frame": float(np.mean(cue_in_window)) if cue_in_window else None,
            "n_windows": len(cue_in_window),
            "K_mean": float(np.mean(ks)) if ks else None,
            "K_std": float(np.std(ks)) if ks else None,
            "switches_per_ep_mean": float(np.mean(switches)) if switches else None,
            "note": "obs non-cue = noise only; leak comes from cue frames still in window after switch",
        }
        print(f"  [gen] seed={s} frac_cue_in_win={rows[str(s)]['frac_noncue_windows_with_cue_frame']:.4f} "
              f"K_mean={rows[str(s)]['K_mean']:.1f} sw/ep={rows[str(s)]['switches_per_ep_mean']:.2f}", flush=True)
    return rows


def prescreen(n_rep, n_eps, start=SEED_START, need=N_CLEAN, hard_cap=500):
    clean = []
    scanned = []
    s = start
    while len(clean) < need and s < start + hard_cap:
        samples = [measure_leak(s, i, n_eps=n_eps) for i in range(n_rep)]
        st = summarize(samples)
        st["seed"] = s
        scanned.append(st)
        ok = st["mean"] <= MARGIN_MAX
        mark = "KEEP" if ok else "skip"
        print(f"  [pre] seed={s:4d} mean={st['mean']:.4f} se={st['se']:.4f} sd={st['sd']:.4f} {mark}", flush=True)
        if ok:
            clean.append(s)
        s += 1
    return clean, scanned


def main():
    t0 = time.time()
    meta = {
        "thresholds_sha256": THR_HASH,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "N": N, "T": T, "K": [K_LO, K_HI], "window": WIN, "n_eps_default": N_EPS,
        "leak_max": LEAK_MAX, "margin_max": MARGIN_MAX,
    }

    print("=== Phase1 diagnosis n_rep=5 ===", flush=True)
    diag = {
        "void": diagnose_seeds(VOID_SEEDS, N_REP0, "VOID"),
        "nonvoid": diagnose_seeds(NONVOID_SEEDS, N_REP0, "nonV"),
    }
    # aggregate SD
    all_sd = [v["sd"] for d in (diag["void"], diag["nonvoid"]) for v in d.values()]
    all_se = [v["se"] for d in (diag["void"], diag["nonvoid"]) for v in d.values()]
    diag_summary = {
        "n_seeds": len(all_sd),
        "sd_median": float(np.median(all_sd)),
        "sd_mean": float(np.mean(all_sd)),
        "se_median": float(np.median(all_se)),
        "frac_sd_ge_0_03": float(np.mean([sd >= 0.03 for sd in all_sd])),
        "conclusion_preregistered_rule": None,
    }
    if diag_summary["sd_median"] >= 0.03 or diag_summary["se_median"] >= 0.02:
        diag_summary["conclusion_preregistered_rule"] = "measurement_noise_dominant"
    else:
        # check stably high among VOID
        stably = []
        for s, v in diag["void"].items():
            if v["mean"] > LEAK_MAX and v["sd"] < 0.03:
                stably.append(int(s))
        if stably:
            diag_summary["conclusion_preregistered_rule"] = "stably_high_true_leak"
            diag_summary["stably_high_void_seeds"] = stably
        else:
            diag_summary["conclusion_preregistered_rule"] = "mixed_noise_and_borderline"
    print("DIAG CONCLUSION:", diag_summary["conclusion_preregistered_rule"], flush=True)

    print("=== Phase2 calibrate on tune 100-103 ===", flush=True)
    choice, tune_pool = calibrate_n_rep(TUNE_SEEDS)
    print("CALIBRATED:", choice, flush=True)

    print("=== Phase3 generator cue-bleed probe ===", flush=True)
    # mix of high-i0 and low-i0
    gen_seeds = VOID_SEEDS[:4] + [16, 20, 43]
    gen = investigate_generator(gen_seeds)

    print("=== Phase4 pre-screen from 200 ===", flush=True)
    n_rep = int(choice["n_rep"])
    n_eps = int(choice["n_eps"])
    clean, scanned = prescreen(n_rep=n_rep, n_eps=n_eps)
    print("CLEAN:", clean, flush=True)

    # freeze clean list
    clean_doc = {
        "schema": "clean_seeds_Dx2_v1",
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "thresholds_sha256": THR_HASH,
        "protocol": {
            "n_rep": n_rep,
            "n_eps": n_eps,
            "window": WIN,
            "N": N,
            "T": T,
            "K": [K_LO, K_HI],
            "probe_seed_formula": "science_seed + 10007 + i * 100003",
            "accept_leak_mean_max": MARGIN_MAX,
            "void_line_unchanged": LEAK_MAX,
            "denom_unchanged": 8,
            "SE_target": SE_TARGET,
            "calibrated_sd_median_single": choice.get("sd_median_single"),
            "calibrated_se_at_choice": choice.get("se_at_choice"),
        },
        "seeds": clean,
        "n": len(clean),
        "scanned_until": scanned[-1]["seed"] if scanned else None,
        "n_scanned": len(scanned),
        "per_seed_stats": {str(s): next(x for x in scanned if x["seed"] == s) for s in clean},
    }
    cp = FROZEN / "clean_seeds_Dx2.json"
    cp.write_text(json.dumps(clean_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ch = hashlib.sha256(cp.read_bytes()).hexdigest()
    (FROZEN / "clean_seeds_Dx2.sha256").write_text(ch + "  clean_seeds_Dx2.json\n")
    # central copy
    central = Path("/workspace/proj_20261009/必要性重建/frozen")
    (central / "clean_seeds_Dx2.json").write_bytes(cp.read_bytes())
    (central / "clean_seeds_Dx2.sha256").write_text(ch + "  clean_seeds_Dx2.json\n")

    result = {
        "meta": meta,
        "diagnosis": diag,
        "diagnosis_summary": diag_summary,
        "calibration": choice,
        "generator_probe": gen,
        "prescreen_clean_seeds": clean,
        "prescreen_scanned": scanned,
        "clean_seeds_sha256": ch,
        "elapsed_sec": time.time() - t0,
        "STOP": "do_not_start_S1g",
    }
    (LOGS / "dx2_full.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (LOGS / "diagnosis.json").write_text(json.dumps({"diagnosis": diag, "summary": diag_summary}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (LOGS / "calibration.json").write_text(json.dumps(choice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (LOGS / "prescreen.json").write_text(json.dumps({"clean": clean, "scanned": scanned, "sha256": ch}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DONE elapsed", round(time.time() - t0, 1), "clean_sha", ch, flush=True)


if __name__ == "__main__":
    main()
