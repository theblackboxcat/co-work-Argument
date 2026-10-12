# -*- coding: utf-8 -*-
"""E2_s2c_learnable runner.
  python run_arm.py --arm G_RL_GRU --seed 200
  python run_arm.py --arm C --seed 200
  python run_arm.py --arm A --seed 200
  python run_arm.py --arm ALL --seed 200   # A then C then G_RL_GRU + eval + C7
Science seeds: Dx2 clean [200,205,210,211,212,216,218,219]. Tune ONLY: 100-103 (--tune/--smoke).
VOID denom=8; S3 CLOSED.
"""
from __future__ import annotations
import argparse, json, os, sys, time, hashlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))
import s2c_env as E
import s2c_c4pp as C4
import e2_gru_rl as R

LOGS = ROOT / "logs"
GENES = ROOT / "genes"
TUNE = ROOT / "tune"
LOGS.mkdir(exist_ok=True); GENES.mkdir(exist_ok=True); TUNE.mkdir(exist_ok=True)

THR_PATH = ROOT / "frozen" / "thresholds_E2.json"
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
POP = int(THR["budget"]["pop_AC"])
GENS = int(THR["budget"]["gens_AC"])
K_EVAL = int(THR["budget"]["K_eval_train"])
C7C = THR["C7_strict"]["for_C_handwritten"]
C7G = THR["C7_strict"]["for_G_RL_GRU"]


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
    kind = str(z["kind"]) if "kind" in z.files else "unknown"
    # kind stored as array of strings sometimes
    if hasattr(kind, 'item'):
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
            hid = int(W.get("hid", 32)) if "hid" in W else 32
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


def run_c7_handwritten(ag, seed, smoke=False):
    rng = np.random.default_rng(seed + 77_000)
    gens = 8 if smoke else int(C7C["continue_gens"])
    every = 4 if smoke else int(C7C["probe_every"])
    pop_n = max(8, POP // 4)
    pop = [E.clone_agent(ag) for _ in range(pop_n)]
    for i in range(1, pop_n):
        E.mutate(pop[i], rng, 0.08)
    probes = []
    for gen in range(gens):
        fits = [E.fitness_task_only(a, rng, K_eval=max(2, K_EVAL // 2)) for a in pop]
        order = np.argsort(fits)[::-1]
        elite_n = max(2, pop_n // 4)
        elites = [pop[i] for i in order[:elite_n]]
        best = E.clone_agent(elites[0])
        if gen % every == 0 or gen == gens - 1:
            pr = probe_C2_C3(best, seed + gen * 17)
            probes.append({"gen": int(gen), **pr})
        newpop = [E.clone_agent(e) for e in elites]
        while len(newpop) < pop_n:
            parent = elites[int(rng.integers(elite_n))]
            child = E.clone_agent(parent)
            E.mutate(child, rng, 0.10)
            E.update_resistance(child)
            newpop.append(child)
        pop = newpop
    last3 = probes[-3:] if len(probes) >= 3 else probes
    n_both = sum(1 for p in last3 if p.get("C2_and_C3"))
    return {
        "probes": probes, "last3_C2_and_C3": n_both,
        "goal_channel_retained_strict": bool(n_both >= 2),
        "note": THR["C7_strict"]["disclaimer"], "rule": C7C["rule"], "mode": "evo_continue",
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


def train_A(seed, smoke=False):
    rng = np.random.default_rng(seed)
    g, p = (6, 10) if smoke else (GENS, POP)
    best, hist = E.evolve("memoryless", rng, gens=g, pop_n=p, K_eval=2 if smoke else K_EVAL)
    return best, {"best_fit_train": hist["best_fit_train"]}


def train_C(seed, smoke=False):
    rng = np.random.default_rng(seed + 333)
    g, p = (6, 10) if smoke else (GENS, POP)
    best, hist = E.evolve("hand_gate", rng, gens=g, pop_n=p, K_eval=2 if smoke else K_EVAL)
    return best, {"best_fit_train": hist["best_fit_train"],
                  "label": THR["arms"]["C_handwritten"]["label"]}


def train_G(seed, smoke=False):
    cfg = THR["arms"]["G_RL_GRU"]
    params, hist = R.train_gru_rl(
        seed=seed, hidden=int(cfg["hidden"]), lr=float(cfg["lr"]),
        epochs_max=int(cfg["epochs_max"]), episodes_per_epoch=int(cfg["episodes_per_epoch"]),
        gamma=float(cfg["gamma"]), entropy_coef=float(cfg["entropy_coef"]),
        value_coef=float(cfg["value_coef"]), early_stop_return=float(cfg["early_stop_return"]),
        smoke=smoke, log_every_epochs=int(cfg.get("log_every_epochs", 50)),
        eval_every_epochs=int(cfg.get("log_every_epochs", 50)),
    )
    return R.make_gru_rl_agent(params), hist


def run_seed_all(seed, smoke=False, do_c7=True, out_dir=None):
    t0 = time.time()
    out_dir = Path(out_dir or LOGS)
    tag = f"seed{seed}"
    print(f"\n===== E2 {tag} {'SMOKE' if smoke else ''} =====", flush=True)
    n_eps = 20 if smoke else N_EPS
    n_a = 12 if smoke else N_EPS_A

    print("-- train A", flush=True)
    ag_A, evo_A = train_A(seed, smoke=smoke)
    save_agent(ag_A, GENES / f"gene_{tag}_A.npz")

    print("-- train C", flush=True)
    ag_C, evo_C = train_C(seed, smoke=smoke)
    save_agent(ag_C, GENES / f"gene_{tag}_C.npz")

    print("-- train G_RL_GRU", flush=True)
    ag_G, evo_G = train_G(seed, smoke=smoke)
    save_agent(ag_G, GENES / f"gene_{tag}_G_RL_GRU.npz")
    (out_dir / f"hist_G_RL_GRU_{tag}.json").write_text(
        json.dumps(evo_G.get("hist", []), ensure_ascii=False, indent=1), encoding="utf-8")

    m_mem, _, _ = E.evaluate(ag_A, n_eps=n_a, seed=seed + 10_000)
    void_A = m_mem > A_VOID
    a_leak_emp = E.obs_window_decode_acc(ag_A, seed=seed + 50_000, n_eps=16, window=LEAK_WIN)

    agents = {"A": ag_A, "C": ag_C, "G_RL_GRU": ag_G}
    evo = {"A": evo_A, "C": evo_C, "G_RL_GRU": {
        "best_ret_train": evo_G.get("best_ret_train"),
        "epochs_ran": evo_G.get("epochs_ran"),
        "no_goal_labels": True,
    }}
    arm_eval = {}
    for arm, ag in agents.items():
        print(f"-- eval {arm}", flush=True)
        arm_eval[arm] = eval_arm_agent(ag, m_mem, seed, a_leak_emp=a_leak_emp, n_eps=n_eps)
        ae = arm_eval[arm]
        print(
            f"  {arm}: ret={ae['return']['mean']:.4f} C1={ae['C1'].get('pass')} "
            f"C2={ae.get('C2',{}).get('pass')} C3={ae.get('C3',{}).get('pass')} "
            f"C4pp={ae.get('C4pp',{}).get('pass')} all={ae.get('all_C1_C6')} "
            f"leak_void={ae.get('void_leak')}",
            flush=True,
        )

    any_leak = any(arm_eval[a].get("void_leak") for a in ("C", "G_RL_GRU"))
    seed_void = bool(void_A or any_leak)

    results = {
        "seed": seed,
        "experiment_id": "E2_s2c_learnable",
        "label": THR["label"],
        "thresholds_file_hash": THR_HASH,
        "fitness_source_hash": FIT_HASH,
        "clean_seeds_Dx2_sha256": CLEAN_SHA,
        "pre_registered_seeds": SEEDS,
        "env": ENV,
        "A_return": float(m_mem),
        "void_env_A_ceiling": bool(void_A),
        "A_leak_empirical": float(a_leak_emp),
        "leak_void_line": float(a_leak_emp) + 0.10,
        "evo": evo,
        "arms": arm_eval,
        "seed_void": seed_void,
        "C_pass_C1_C6": bool(arm_eval["C"].get("all_C1_C6")) and not seed_void,
        "G_pass_C1_C6": bool(arm_eval["G_RL_GRU"].get("all_C1_C6")) and not seed_void,
        "s3_status": "CLOSED",
    }

    results["C7_C"] = None
    results["C7_G"] = None
    if do_c7 and results["C_pass_C1_C6"]:
        print(f"-- C7 handwritten for seed {seed}", flush=True)
        results["C7_C"] = run_c7_handwritten(ag_C, seed, smoke=smoke)
        results["C_pass_C7"] = bool(results["C7_C"].get("goal_channel_retained_strict"))
    else:
        results["C_pass_C7"] = False

    if do_c7 and results["G_pass_C1_C6"]:
        print(f"-- C7 GRU frozen probes for seed {seed}", flush=True)
        results["C7_G"] = run_c7_gru_frozen(ag_G, seed, smoke=smoke)
        results["G_pass_C7"] = bool(results["C7_G"].get("goal_channel_retained_strict"))
    else:
        results["G_pass_C7"] = False

    # MAIN seed accept = G C1–C6 ∧ C7 ∧ not void; C is positive control integrity
    results["seed_MAIN_accept"] = bool(results["G_pass_C1_C6"] and results.get("G_pass_C7"))
    results["seed_C_integrity"] = bool(results["C_pass_C1_C6"] and results.get("C_pass_C7"))
    results["wall_s"] = time.time() - t0

    out_path = out_dir / f"result_{tag}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"===== done {tag} wall={results['wall_s']:.1f}s MAIN={results['seed_MAIN_accept']} "
          f"C_int={results['seed_C_integrity']} VOID={seed_void} =====", flush=True)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="ALL", choices=["A", "C", "G_RL_GRU", "ALL"])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--no-c7", action="store_true")
    args = ap.parse_args()
    seed = args.seed
    if args.tune or args.smoke:
        if seed not in TUNE_SEEDS and args.tune:
            print(f"WARN: tune seed {seed} not in {TUNE_SEEDS}", flush=True)
        out = TUNE
    else:
        if seed not in SEEDS:
            raise SystemExit(f"science seed {seed} not in frozen list {SEEDS}")
        out = LOGS
    if args.arm == "ALL":
        run_seed_all(seed, smoke=args.smoke or args.tune, do_c7=not args.no_c7, out_dir=out)
    else:
        raise SystemExit("single-arm mode not needed; use --arm ALL")


if __name__ == "__main__":
    main()
