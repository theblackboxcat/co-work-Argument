# -*- coding: utf-8 -*-
"""E2b_c4pp_permeability runner.
  python run_arm.py --seed 200 --config ceil_lr1e3
  python run_arm.py --seed 100 --config ceil_lr1e3 --tune
Science seeds: Dx2 clean. Tune ONLY 100-103. Acceptance = E2 unchanged.
Reuse E2 A/C genes for integrity/leak. S3 CLOSED.
"""
from __future__ import annotations
import argparse, json, os, sys, time, hashlib, shutil
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
E2_ROOT = ROOT.parent / "E2_s2c_learnable"
sys.path.insert(0, str(ROOT / "code"))
import s2c_env as E
import s2c_c4pp as C4
import e2_gru_rl as R

LOGS = ROOT / "logs"
GENES = ROOT / "genes"
TUNE = ROOT / "tune"
LOGS.mkdir(exist_ok=True); GENES.mkdir(exist_ok=True); TUNE.mkdir(exist_ok=True)

THR_PATH = ROOT / "frozen" / "thresholds_E2b.json"
THR = json.loads(THR_PATH.read_text(encoding="utf-8"))
THR_HASH = hashlib.sha256(THR_PATH.read_bytes()).hexdigest()
FIT_HASH = E.fitness_source_hash()
CLEAN_SHA = (ROOT / "frozen" / "clean_seeds_Dx2.sha256").read_text().split()[0]

ENV = {k: THR["env"][k] for k in (
    "H", "W", "T", "tox", "food_rate", "gem_rate", "food_cap", "gem_cap",
    "n_food_init", "n_gem_init", "n_obstacles_frac",
) if k in THR["env"]}
E.set_env_defaults(**ENV)

SEEDS = list(THR["seeds"])
TUNE_SEEDS = list(THR["tune_seeds"])
C1_MARGIN = float(THR["acceptance_per_seed"]["C1_margin_over_memoryless"])
C1_ABS = float(THR["acceptance_per_seed"]["C1_absolute_return"])
C2_MIN = float(THR["acceptance_per_seed"]["C2_decode_acc_min"])
C3_STEPS = int(THR["acceptance_per_seed"]["C3_flip_within_steps"])
C3_MIN = float(THR["acceptance_per_seed"]["C3_flip_rate_min"])
C6_MIN = float(THR["acceptance_per_seed"]["C6_removal_return_min"])
C6_FAC = int(THR["acceptance_per_seed"]["C6_removal_segment_len_factor"])
C4THR = THR["acceptance_per_seed"]["C4pp"]
A_VOID = float(THR["void_rules"]["A_return_gt"])
LEAK_WIN = int(THR["leak_probe"]["window"])
LEAK_NEPS = int(THR["leak_probe"]["n_eps"])
LEAK_NREP = int(THR["leak_probe"]["n_rep"])
CHANCE = float(THR["acceptance_per_seed"]["C2_chance_N2"])
N_EPS = int(THR["budget"]["n_eps_accept"])
N_EPS_A = int(THR["budget"]["n_eps_A_void"])
C7G = THR["C7_strict"]["for_G_RL_GRU"]
CONFIGS = {c["id"]: c for c in THR["tune_grid"]}
CEIL = THR["budget_ceiling"]


def wilson_ci(k, n, z=1.96):
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = k / n
    den = 1 + z**2 / n
    cen = (p + z**2 / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return float(p), float(cen - half), float(cen + half)


def save_agent(ag, path):
    payload = {"kind": ag["kind"]}
    if "hid" in ag:
        payload["hid"] = int(ag["hid"])
    arrays = {}
    for k, v in ag.get("W", {}).items():
        if isinstance(v, np.ndarray):
            arrays[f"W_{k}"] = v
        elif isinstance(v, (int, float, np.floating, np.integer)):
            payload[str(k)] = float(v) if not isinstance(v, (int, np.integer)) else int(v)
    np.savez_compressed(path, **payload, **arrays)


def load_agent(path):
    z = np.load(path, allow_pickle=False)
    kind = str(z["kind"])
    if hasattr(kind, "item"):
        kind = kind.item()
    kind = str(kind)
    W = {}
    hid = None
    for k in z.files:
        if k.startswith("W_"):
            W[k[2:]] = np.asarray(z[k], float)
        elif k == "hid":
            hid = int(np.asarray(z[k]).item())
    if kind == "gru_rl":
        if hid is None:
            hid = 32
        if "hid" not in W:
            W["hid"] = hid
        return {"kind": "gru_rl", "W": W, "hid": hid, "R": {}}
    return {"kind": kind, "W": W, "R": {}}


def leak_mean_dx2_style(ag, seed, a_leak_emp=None):
    samples = []
    for i in range(LEAK_NREP):
        probe_seed = int(seed + 10007 + i * 100003)
        acc = E.obs_window_decode_acc(ag, seed=probe_seed, n_eps=LEAK_NEPS, window=LEAK_WIN)
        samples.append(float(acc))
    arr = np.asarray(samples, float)
    if a_leak_emp is None:
        leak_max = CHANCE + 0.10
        mode = "theoretical_chance+0.10_fallback"
    else:
        leak_max = float(a_leak_emp) + 0.10
        mode = "A_empirical+0.10"
    mean = float(arr.mean())
    return {
        "samples": samples, "mean": mean,
        "sd": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "se": float(arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else 0.0,
        "i0": float(samples[0]), "n_eps": LEAK_NEPS, "n_rep": LEAK_NREP,
        "max_allowed": leak_max, "a_leak_emp": a_leak_emp, "mode": mode,
        "void": bool(mean > leak_max), "dx2_heritage_line_N4": 0.35,
    }


def eval_arm_agent(ag, mem_return, seed, a_leak_emp=None, n_eps=None):
    eval_seed = seed + 10_000
    n_eps = int(n_eps or N_EPS)
    out = {"kind": ag["kind"]}
    m, s, xs = E.evaluate(ag, n_eps=n_eps, seed=eval_seed, greedy=True)
    out["return"] = {"mean": float(m), "std": float(s), "n": n_eps}
    margin = m - mem_return
    c1 = (margin >= C1_MARGIN) and (m >= C1_ABS)
    out["C1"] = {"pass": bool(c1), "margin": float(margin), "abs": float(m),
                 "thr_margin": C1_MARGIN, "thr_abs": C1_ABS}

    if not E.has_latent(ag):
        out["C2"] = {"pass": False, "na": True}
        out["C2_leak"] = {"pass": True, "na": True, "void": False}
        out["C3"] = {"pass": False, "na": True}
        out["C4pp"] = {"pass": False, "na": True}
        out["C5"] = {"pass": True, "note": "fitness_task_only"}
        out["C6"] = {"pass": False, "na": True}
        out["all_C1_C6"] = False
        out["void_leak"] = False
        out["permeability_pattern"] = False
        return out

    S_tr, G_tr = E.collect_s_goal(ag, n_eps=max(12, n_eps // 4), seed=eval_seed + 1)
    S_te, G_te = E.collect_s_goal(ag, n_eps=max(12, n_eps // 4), seed=eval_seed + 2)
    dec = E.multinomial_decode_acc(S_tr, G_tr, S_te, G_te) if len(G_tr) else 0.5
    c2 = dec >= C2_MIN
    out["C2"] = {"pass": bool(c2), "decode_acc": float(dec), "threshold": C2_MIN,
                 "chance": CHANCE, "n_train": int(len(G_tr)), "n_test": int(len(G_te))}

    leak = leak_mean_dx2_style(ag, seed, a_leak_emp=a_leak_emp)
    out["C2_leak"] = leak
    void_leak = bool(leak["void"])

    cents, _, _ = E.goal_centroids(ag, seed=eval_seed + 3, n_eps=max(20, n_eps // 3))
    flip, n_u = E.criterion3_flip_rate(ag, cents, seed=eval_seed + 4,
                                       n_trials=max(40, n_eps // 2), within_steps=C3_STEPS)
    c3 = flip >= C3_MIN
    out["C3"] = {"pass": bool(c3), "flip_rate": float(flip), "threshold": C3_MIN,
                 "within_steps": C3_STEPS, "n_trials": int(n_u)}

    c4 = C4.new_c4pp(ag, seed=eval_seed + 11, thr=C4THR)
    out["C4pp"] = c4
    i_ok = bool(c4.get("i_directional"))
    iii_ok = bool(c4.get("iii_specific"))
    out["permeability_pattern"] = bool(i_ok and (not iii_ok))  # write-ok / hold-fail

    src = E.FITNESS_SOURCE
    body_lines = [ln for ln in src.splitlines() if not ln.strip().startswith('#')
                  and '"""' not in ln]
    body = "\n".join(body_lines)
    has_bad = any(b in body for b in ["coh_w", "s_var", "stability_term", "delta_s_penalty"])
    c5 = (not has_bad) and ("scores.append(ret)" in src)
    out["C5"] = {"pass": bool(c5), "fitness_source_hash": FIT_HASH, "banned_terms_in_body": has_bad}

    m6, s6, _ = E.evaluate(ag, n_eps=max(40, n_eps // 2), seed=eval_seed + 9,
                           removal_mode=True, removal_factor=C6_FAC)
    c6 = m6 >= C6_MIN
    out["C6"] = {"pass": bool(c6), "return": float(m6), "threshold": C6_MIN, "segment_factor": C6_FAC}

    all_pass = bool(c1 and c2 and (not void_leak) and c3 and c4.get("pass") and c5 and c6)
    out["all_C1_C6"] = all_pass
    out["void_leak"] = bool(void_leak)
    return out


def probe_C2_C3(ag, seed_base):
    S_tr, G_tr = E.collect_s_goal(ag, n_eps=10, seed=seed_base + 1)
    S_te, G_te = E.collect_s_goal(ag, n_eps=10, seed=seed_base + 2)
    dec = E.multinomial_decode_acc(S_tr, G_tr, S_te, G_te) if len(G_tr) else 0.5
    c2 = dec >= C2_MIN
    cents, _, _ = E.goal_centroids(ag, seed=seed_base + 3, n_eps=16)
    flip, n_u = E.criterion3_flip_rate(ag, cents, seed=seed_base + 4, n_trials=30, within_steps=C3_STEPS)
    c3 = flip >= C3_MIN
    m, _, _ = E.evaluate(ag, n_eps=8, seed=seed_base + 5)
    return {
        "ret": float(m),
        "C2": {"pass": bool(c2), "decode_acc": float(dec)},
        "C3": {"pass": bool(c3), "flip_rate": float(flip), "n_trials": int(n_u)},
        "C2_and_C3": bool(c2 and c3),
    }


def run_c7_gru_frozen(ag, seed, smoke=False):
    n_probes = 3 if smoke else int(C7G["n_probes"])
    probes = []
    for i in range(n_probes):
        pr = probe_C2_C3(ag, seed + 90_000 + i * 997)
        probes.append({"gen": int(i), **pr})
    last3 = probes[-3:] if len(probes) >= 3 else probes
    n_both = sum(1 for p in last3 if p.get("C2_and_C3"))
    return {
        "probes": probes, "last3_C2_and_C3": n_both,
        "goal_channel_retained_strict": bool(n_both >= 2),
        "note": THR["C7_strict"]["disclaimer"], "rule": C7G["rule"],
        "mode": C7G["mode"],
    }


def resolve_config(config_id):
    if config_id not in CONFIGS:
        raise SystemExit(f"unknown config {config_id}; choose from {list(CONFIGS)}")
    cfg = dict(CONFIGS[config_id])
    # enforce ceiling
    assert cfg["epochs_max"] <= CEIL["epochs_max"]
    assert cfg["episodes_per_epoch"] <= CEIL["episodes_per_epoch"]
    return cfg


def train_G(seed, cfg, smoke=False):
    es_ret = cfg.get("early_stop_return", CEIL["early_stop_return"])
    es_min = int(cfg.get("early_stop_min_epoch", CEIL["early_stop_min_epoch"]))
    params, hist = R.train_gru_rl(
        seed=seed, hidden=32, lr=float(cfg["lr"]),
        epochs_max=int(cfg["epochs_max"]), episodes_per_epoch=int(cfg["episodes_per_epoch"]),
        gamma=0.99, entropy_coef=float(cfg["entropy_coef"]),
        value_coef=0.5, early_stop_return=es_ret,
        early_stop_min_epoch=es_min,
        smoke=smoke, log_every_epochs=50, eval_every_epochs=50,
    )
    return R.make_gru_rl_agent(params), hist


def train_AC_local(seed, smoke=False):
    """Fallback when E2 A/C genes absent (tune seeds 101–103)."""
    rng = np.random.default_rng(seed)
    g, p = (6, 10) if smoke else (100, 36)
    best_A, _ = E.evolve("memoryless", rng, gens=g, pop_n=p, K_eval=2 if smoke else 8)
    rng_c = np.random.default_rng(seed + 333)
    best_C, _ = E.evolve("hand_gate", rng_c, gens=g, pop_n=p, K_eval=2 if smoke else 8)
    save_agent(best_A, GENES / f"gene_seed{seed}_A.npz")
    save_agent(best_C, GENES / f"gene_seed{seed}_C.npz")
    return best_A, best_C


def load_e2_AC(seed, smoke=False):
    a_path = E2_ROOT / "genes" / f"gene_seed{seed}_A.npz"
    c_path = E2_ROOT / "genes" / f"gene_seed{seed}_C.npz"
    local_a = GENES / f"gene_seed{seed}_A.npz"
    local_c = GENES / f"gene_seed{seed}_C.npz"
    if a_path.exists() and c_path.exists():
        shutil.copy2(a_path, local_a)
        shutil.copy2(c_path, local_c)
        return load_agent(a_path), load_agent(c_path)
    if local_a.exists() and local_c.exists():
        return load_agent(local_a), load_agent(local_c)
    print(f"-- E2 A/C missing for seed {seed}; training local A/C", flush=True)
    return train_AC_local(seed, smoke=smoke)


def load_e2_C_integrity(seed):
    """Prefer E2 result JSON for C C7 integrity (avoid re-evo)."""
    p = E2_ROOT / "logs" / f"result_seed{seed}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return {
        "C_pass_C1_C6": bool(d.get("C_pass_C1_C6")),
        "C_pass_C7": bool(d.get("C_pass_C7")),
        "seed_C_integrity": bool(d.get("seed_C_integrity")),
        "C_return": d.get("arms", {}).get("C", {}).get("return", {}).get("mean"),
        "source": str(p),
        "note": "reused from E2 identical env+acceptance",
    }


def run_seed(seed, config_id, smoke=False, do_c7=True, out_dir=None, tag_suffix=""):
    t0 = time.time()
    cfg = resolve_config(config_id)
    out_dir = Path(out_dir or LOGS)
    tag = f"seed{seed}{tag_suffix}"
    print(f"\n===== E2b {tag} config={config_id} {'SMOKE' if smoke else ''} =====", flush=True)
    print(f"  cfg={cfg}", flush=True)
    n_eps = 20 if smoke else N_EPS
    n_a = 12 if smoke else N_EPS_A

    print("-- load E2 A/C genes", flush=True)
    ag_A, ag_C = load_e2_AC(seed, smoke=smoke)

    print("-- train G_RL_GRU (budget↑)", flush=True)
    ag_G, evo_G = train_G(seed, cfg, smoke=smoke)
    save_agent(ag_G, GENES / f"gene_{tag}_G_RL_GRU.npz")
    (out_dir / f"hist_G_RL_GRU_{tag}.json").write_text(
        json.dumps(evo_G.get("hist", []), ensure_ascii=False, indent=1), encoding="utf-8")

    m_mem, _, _ = E.evaluate(ag_A, n_eps=n_a, seed=seed + 10_000)
    void_A = m_mem > A_VOID
    a_leak_emp = E.obs_window_decode_acc(ag_A, seed=seed + 50_000, n_eps=16, window=LEAK_WIN)

    print("-- eval G_RL_GRU", flush=True)
    ae_G = eval_arm_agent(ag_G, m_mem, seed, a_leak_emp=a_leak_emp, n_eps=n_eps)
    print(
        f"  G: ret={ae_G['return']['mean']:.4f} C1={ae_G['C1'].get('pass')} "
        f"C2={ae_G.get('C2',{}).get('pass')} C3={ae_G.get('C3',{}).get('pass')} "
        f"C4pp={ae_G.get('C4pp',{}).get('pass')} i={ae_G.get('C4pp',{}).get('i_directional')} "
        f"iii={ae_G.get('C4pp',{}).get('iii_specific')} perm={ae_G.get('permeability_pattern')} "
        f"C6={ae_G.get('C6',{}).get('pass')} all={ae_G.get('all_C1_C6')} "
        f"leak_void={ae_G.get('void_leak')}",
        flush=True,
    )

    # light A/C return sanity
    m_C, _, _ = E.evaluate(ag_C, n_eps=min(40, n_eps), seed=seed + 10_000)
    c_int = load_e2_C_integrity(seed) if seed in SEEDS else None

    seed_void = bool(void_A or ae_G.get("void_leak"))
    g_c16 = bool(ae_G.get("all_C1_C6")) and not seed_void

    results = {
        "seed": seed,
        "experiment_id": "E2b_c4pp_permeability",
        "label": THR["label"],
        "config_id": config_id,
        "config": cfg,
        "thresholds_file_hash": THR_HASH,
        "fitness_source_hash": FIT_HASH,
        "clean_seeds_Dx2_sha256": CLEAN_SHA,
        "pre_registered_seeds": SEEDS,
        "env": ENV,
        "A_return": float(m_mem),
        "C_return_reeval": float(m_C),
        "void_env_A_ceiling": bool(void_A),
        "A_leak_empirical": float(a_leak_emp),
        "leak_void_line": float(a_leak_emp) + 0.10,
        "evo": {"G_RL_GRU": {
            "best_ret_train": evo_G.get("best_ret_train"),
            "epochs_ran": evo_G.get("epochs_ran"),
            "no_goal_labels": True,
            "config_id": config_id,
        }},
        "arms": {"G_RL_GRU": ae_G},
        "seed_void": seed_void,
        "G_pass_C1_C6": g_c16,
        "C_integrity_from_E2": c_int,
        "s3_status": "CLOSED",
        "permeability_pattern": bool(ae_G.get("permeability_pattern")),
    }

    results["C7_G"] = None
    if do_c7 and g_c16:
        print(f"-- C7 GRU frozen probes for seed {seed}", flush=True)
        results["C7_G"] = run_c7_gru_frozen(ag_G, seed, smoke=smoke)
        results["G_pass_C7"] = bool(results["C7_G"].get("goal_channel_retained_strict"))
    else:
        results["G_pass_C7"] = False

    results["seed_MAIN_accept"] = bool(g_c16 and results.get("G_pass_C7"))
    if c_int is not None:
        results["seed_C_integrity"] = bool(c_int.get("seed_C_integrity"))
    else:
        # tune seeds: no E2 science result; treat C gene re-eval return > C1_ABS as soft OK
        results["seed_C_integrity"] = bool(m_C >= C1_ABS)
    results["wall_s"] = time.time() - t0

    out_path = out_dir / f"result_{tag}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"===== done {tag} wall={results['wall_s']:.1f}s MAIN={results['seed_MAIN_accept']} "
          f"perm={results['permeability_pattern']} VOID={seed_void} =====", flush=True)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--config", required=True, choices=list(CONFIGS.keys()))
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--no-c7", action="store_true")
    args = ap.parse_args()
    seed = args.seed
    if args.tune or args.smoke:
        if args.tune and seed not in TUNE_SEEDS:
            print(f"WARN: tune seed {seed} not in {TUNE_SEEDS}", flush=True)
        out = TUNE
        suffix = f"_{args.config}"
    else:
        if seed not in SEEDS:
            raise SystemExit(f"science seed {seed} not in frozen list {SEEDS}")
        out = LOGS
        suffix = ""
    run_seed(seed, args.config, smoke=args.smoke, do_c7=not args.no_c7,
             out_dir=out, tag_suffix=suffix)


if __name__ == "__main__":
    main()
