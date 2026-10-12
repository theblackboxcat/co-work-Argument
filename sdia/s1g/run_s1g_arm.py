# -*- coding: utf-8 -*-
"""S1g_clean_confirm single-arm runner.
  python run_arm.py --arm G_RL_GRU --seed 200
  python run_arm.py --arm G_RL_RNN --seed 200
  python run_arm.py --arm C --seed 200
  python run_arm.py --arm A --seed 200
  python run_arm.py --arm ES_GRU --seed 200
Science seeds: Dx2 clean [200,205,210,211,212,216,218,219]. Tune ONLY: 100-103 (--tune).
Leak VOID: Dx2 probe n_eps=12 × n_rep=5; mean>0.35 → VOID; denom=8.
"""
from __future__ import annotations
import argparse, json, os, sys, time, hashlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent  # package root
sys.path.insert(0, str(Path(__file__).resolve().parent))  # code/
import s1_env_s1 as E
import s1e_lib as L

LOGS = ROOT / "logs"
GENES = ROOT / "genes"
TUNE_LOGS = ROOT / "tune"
LOGS.mkdir(exist_ok=True)
GENES.mkdir(exist_ok=True)
TUNE_LOGS.mkdir(exist_ok=True)

THR_PATH = ROOT / "frozen" / "thresholds_S1g.json"
THR = json.loads(THR_PATH.read_text(encoding="utf-8"))
THR_HASH = hashlib.sha256(THR_PATH.read_bytes()).hexdigest()
FIT_HASH = L.fitness_source_hash()
CLEAN_SHA = (ROOT / "frozen" / "clean_seeds_Dx2.sha256").read_text().split()[0]

T = int(THR["env"]["T"])
C1_MARGIN = float(THR["acceptance_per_seed"]["C1_margin_over_memoryless"])
C1_ABS = float(THR["acceptance_per_seed"]["C1_absolute_return"])
C2_MIN = float(THR["acceptance_per_seed"]["C2_decode_acc_min"])
C3_STEPS = int(THR["acceptance_per_seed"]["C3_flip_within_steps"])
C3_MIN = float(THR["acceptance_per_seed"]["C3_flip_rate_min"])
C4PP = THR["acceptance_per_seed"]["C4pp_toy"]
C6_MIN = float(THR["acceptance_per_seed"]["C6_removal_return_min"])
C6_FAC = int(THR["acceptance_per_seed"]["C6_removal_segment_len_factor"])
LEAK_MAX = float(THR["acceptance_per_seed"]["C2_leak_max_N4"])
LEAK_WIN = int(THR["acceptance_per_seed"]["C2_leak_window"])
LEAK_NEPS = int(THR["leak_probe"]["n_eps"])
LEAK_NREP = int(THR["leak_probe"]["n_rep"])
A_VOID = float(THR["void_rules"]["A_return_gt_N4"])

ARM_KEY = {
    "A": "A_memoryless",
    "C": "C_handwritten",
    "G_RL_GRU": "G_RL_GRU",
    "G_RL_RNN": "G_RL_RNN",
    "ES_GRU": "ES_GRU",
}


def save_agent(ag, path):
    if ag is None:
        return
    payload = {"kind": ag["kind"], "N": ag["N"]}
    arrays = {}
    src = ag.get("W") or ag.get("G") or {}
    for k, v in src.items():
        if isinstance(v, np.ndarray):
            arrays[f"W_{k}"] = v
        elif isinstance(v, (int, float)):
            payload[k] = float(v)
        else:
            payload[str(k)] = v
    np.savez_compressed(path, **payload, **arrays)


def leak_mean_dx2(ag, N, T, seed, k_lo, k_hi):
    """Dx2 calibrated leak: mean over n_rep independent probes (n_eps each)."""
    samples = []
    for i in range(LEAK_NREP):
        probe_seed = int(seed + 10007 + i * 100003)
        acc = E.obs_window_decode_acc(
            ag, N=N, T=T, seed=probe_seed, n_eps=LEAK_NEPS, window=LEAK_WIN,
            k_lo=k_lo, k_hi=k_hi)
        samples.append(float(acc))
    arr = np.asarray(samples, float)
    return {
        "samples": samples,
        "mean": float(arr.mean()),
        "sd": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "se": float(arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else 0.0,
        "i0": float(samples[0]),
        "n_eps": LEAK_NEPS,
        "n_rep": LEAK_NREP,
        "max": LEAK_MAX,
        "void": bool(float(arr.mean()) > LEAK_MAX),
    }


def eval_arm_agent(ag, mem_return, N, T, seed, k_lo, k_hi):
    eval_seed = seed + 10_000
    n_eps = 16
    out = {"kind": ag["kind"]}
    m, s, xs = E.evaluate(ag, N=N, T=T, n_eps=n_eps, seed=eval_seed, greedy=True,
                          k_lo=k_lo, k_hi=k_hi)
    out["return"] = {"mean": float(m), "std": float(s), "n": n_eps}
    c1 = (m >= mem_return + C1_MARGIN) and (m >= C1_ABS)
    out["C1"] = {"pass": bool(c1), "return": float(m), "mem_return": float(mem_return),
                 "margin": C1_MARGIN, "abs": C1_ABS}
    S_tr, G_tr, _ = E.collect_s_goal(ag, n_eps=max(8, n_eps // 2), N=N, T=T,
                                     seed=eval_seed + 1, non_cue_only=True, k_lo=k_lo, k_hi=k_hi)
    S_te, G_te, _ = E.collect_s_goal(ag, n_eps=max(8, n_eps // 2), N=N, T=T,
                                     seed=eval_seed + 2, non_cue_only=True, k_lo=k_lo, k_hi=k_hi)
    dec = E.multinomial_decode_acc(S_tr, G_tr, S_te, G_te, N)
    c2 = dec >= C2_MIN
    out["C2"] = {"pass": bool(c2), "decode_acc": float(dec), "threshold": C2_MIN}
    leak = leak_mean_dx2(ag, N, T, seed, k_lo, k_hi)
    out["C2_leak"] = leak
    void_leak = bool(leak["void"])
    cents, _, _ = E.goal_centroids(ag, N=N, T=T, seed=eval_seed + 3, n_eps=max(12, n_eps),
                                  k_lo=k_lo, k_hi=k_hi)
    flip, n_u = E.criterion3_flip_rate(ag, cents, N=N, T=T, n_trials=max(40, n_eps * 2),
                                       seed=eval_seed + 4, within_steps=C3_STEPS,
                                       k_lo=k_lo, k_hi=k_hi)
    c3 = flip >= C3_MIN
    out["C3"] = {"pass": bool(c3), "flip_rate": float(flip), "threshold": C3_MIN, "n_trials": int(n_u)}
    c4 = L.c4pp_toy(ag, N=N, T=T, seed=eval_seed + 5, thr=C4PP, n_eps=int(C4PP.get("n_eps", 16)),
                   k_lo=k_lo, k_hi=k_hi)
    out["C4pp"] = c4
    out["C5"] = {"pass": True, "note": "fitness_task_only; no stability terms in source"}
    m6, s6, _ = E.evaluate(ag, N=N, T=T, n_eps=n_eps, seed=eval_seed + 9,
                           removal_mode=True, removal_factor=C6_FAC, k_lo=k_lo, k_hi=k_hi)
    c6 = m6 >= C6_MIN
    out["C6"] = {"pass": bool(c6), "return": float(m6), "threshold": C6_MIN}
    all_pass = bool(c1 and c2 and c3 and c4.get("pass", False) and c6 and not void_leak)
    out["all_pass"] = all_pass
    out["void_leak"] = bool(void_leak)
    return out


def mem_baseline_return(seed, N, T, k_lo, k_hi, smoke=False):
    path = GENES / f"gene_N{N}_seed{seed}_A.npz"
    rng = np.random.default_rng(seed)
    gens, pop = (8, 12) if smoke else (100, 36)
    old_lo, old_hi = E.K_LO, E.K_HI
    E.K_LO, E.K_HI = int(k_lo), int(k_hi)
    try:
        best, hist = L.evolve("memoryless", rng, N=N, gens=gens, pop_n=pop, T=T, K_eval=2 if smoke else 3)
    finally:
        E.K_LO, E.K_HI = old_lo, old_hi
    save_agent(best, path)
    m, _, _ = E.evaluate(best, N=N, T=T, n_eps=16 if not smoke else 6, seed=seed + 10_000, greedy=True,
                         k_lo=k_lo, k_hi=k_hi)
    return float(m), best


def train_arm(arm, seed, smoke=False):
    key = ARM_KEY[arm]
    cfg = THR["arms"][key]
    N = int(cfg["N"])
    k_lo, k_hi = int(cfg["k_lo"]), int(cfg["k_hi"])
    rng = np.random.default_rng(seed + (hash(arm) % 10000))
    if arm == "A":
        g, p = (8, 12) if smoke else (int(cfg["gens"]), int(cfg["pop"]))
        old_lo, old_hi = E.K_LO, E.K_HI
        E.K_LO, E.K_HI = k_lo, k_hi
        try:
            best, hist = L.evolve("memoryless", rng, N=N, gens=g, pop_n=p, T=T, K_eval=2 if smoke else 3)
        finally:
            E.K_LO, E.K_HI = old_lo, old_hi
        return best, {"best_fit_train": hist["best_fit_train"]}, N, k_lo, k_hi, cfg
    if arm == "C":
        g, p = (8, 12) if smoke else (int(cfg["gens"]), int(cfg["pop"]))
        old_lo, old_hi = E.K_LO, E.K_HI
        E.K_LO, E.K_HI = k_lo, k_hi
        try:
            best, hist = L.evolve("hand_gate", rng, N=N, gens=g, pop_n=p, T=T, K_eval=2 if smoke else 3)
        finally:
            E.K_LO, E.K_HI = old_lo, old_hi
        return best, {"best_fit_train": hist["best_fit_train"], "label": cfg.get("label")}, N, k_lo, k_hi, cfg
    if arm == "G_RL_GRU":
        import s1e_gru_rl as R
        params, hist = R.train_gru_rl(
            seed=seed, N=N, T=T, hidden=int(cfg["hidden"]), lr=float(cfg["lr"]),
            epochs_max=int(cfg["epochs_max"]), episodes_per_epoch=int(cfg["episodes_per_epoch"]),
            gamma=float(cfg["gamma"]), entropy_coef=float(cfg["entropy_coef"]),
            value_coef=float(cfg["value_coef"]), early_stop_return=float(cfg["early_stop_return"]),
            smoke=smoke, k_lo=k_lo, k_hi=k_hi,
            log_every_epochs=int(cfg.get("log_every_epochs", 50)),
            eval_every_epochs=int(cfg.get("log_every_epochs", 50)))
        return L.make_gru_agent(N, params), hist, N, k_lo, k_hi, cfg
    if arm == "G_RL_RNN":
        import s1g_rnn_rl as R
        params, hist = R.train_rnn_rl(
            seed=seed, N=N, T=T, hidden=int(cfg["hidden"]), lr=float(cfg["lr"]),
            epochs_max=int(cfg["epochs_max"]), episodes_per_epoch=int(cfg["episodes_per_epoch"]),
            gamma=float(cfg["gamma"]), entropy_coef=float(cfg["entropy_coef"]),
            value_coef=float(cfg["value_coef"]), early_stop_return=float(cfg["early_stop_return"]),
            smoke=smoke, k_lo=k_lo, k_hi=k_hi,
            log_every_epochs=int(cfg.get("log_every_epochs", 50)),
            eval_every_epochs=int(cfg.get("log_every_epochs", 50)))
        return L.make_rnn_ac_agent(N, params), hist, N, k_lo, k_hi, cfg
    if arm == "ES_GRU":
        import s1g_es_gru as ES
        params, hist = ES.openai_es_gru(
            rng, N=N, T=T, hidden=int(cfg["hidden"]),
            n_workers=int(cfg["n_workers"]), generations=int(cfg["generations"]),
            sigma=float(cfg["pop_sigma"]), lr=float(cfg["lr"]),
            K_eval=int(cfg["K_eval"]), total_evals_cap=int(cfg["total_param_evals_target"]),
            k_lo=k_lo, k_hi=k_hi, smoke=smoke)
        return L.make_gru_agent(N, params), hist, N, k_lo, k_hi, cfg
    raise ValueError(arm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=list(ARM_KEY.keys()))
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--mem_return", type=float, default=None)
    args = ap.parse_args()

    sci = set(THR["seeds"])
    tune = set(THR["tune_seeds"])
    if args.tune:
        assert args.seed in tune, f"tune seed {args.seed} not in {sorted(tune)}"
    elif not args.smoke:
        assert args.seed in sci, f"seed {args.seed} not in science seeds {sorted(sci)}; use --tune for 100-103"

    t0 = time.time()
    print(f"===== S1g arm={args.arm} seed={args.seed} smoke={args.smoke} tune={args.tune} =====", flush=True)
    print(f"thresholds_sha256={THR_HASH}", flush=True)
    print(f"clean_seeds_Dx2_sha256={CLEAN_SHA}", flush=True)
    print(f"s1e_acceptance_reused={THR.get('s1e_thresholds_sha256_reused_for_identical_acceptance')}", flush=True)

    ag, evo, N, k_lo, k_hi, cfg = train_arm(args.arm, args.seed, smoke=args.smoke)
    if args.mem_return is not None:
        mem_ret = float(args.mem_return)
    else:
        print(f"-- mem baseline A N={N} K=[{k_lo},{k_hi}]", flush=True)
        mem_ret, _ = mem_baseline_return(args.seed, N, T, k_lo, k_hi, smoke=args.smoke)

    save_agent(ag, GENES / f"gene_N{N}_seed{args.seed}_{args.arm}.npz")
    if isinstance(evo, dict) and "hist" in evo:
        hist_path = (TUNE_LOGS if args.tune else LOGS) / f"hist_{args.arm}_seed{args.seed}.json"
        hist_path.write_text(json.dumps(evo["hist"], ensure_ascii=False), encoding="utf-8")

    print("-- eval (leak n_eps×n_rep = %d×%d)" % (LEAK_NEPS, LEAK_NREP), flush=True)
    ev = eval_arm_agent(ag, mem_ret, N, T, args.seed, k_lo, k_hi)
    void_A = mem_ret > A_VOID
    seed_void = bool(void_A or ev.get("void_leak"))
    evo_out = {}
    if isinstance(evo, dict):
        for k in ("best_fit_train", "best_ret_train", "epochs_ran", "no_goal_labels", "label",
                  "k_lo", "k_hi", "N", "architecture", "optimizer", "evals", "hist_len"):
            if k in evo:
                evo_out[k] = evo[k]
        if "hist" in evo and isinstance(evo["hist"], list) and evo["hist"]:
            evo_out["hist_len"] = len(evo["hist"])
            evo_out["hist_tail"] = evo["hist"][-3:]
            evo_out["hist_head"] = evo["hist"][:2]
            rets = [h["ret"] for h in evo["hist"] if isinstance(h, dict) and "ret" in h]
            if rets:
                evo_out["ret_curve_mean"] = float(np.mean(rets))
                evo_out["ret_curve_max"] = float(np.max(rets))
                evo_out["ret_curve_last"] = float(rets[-1])
                half = rets[len(rets)//2:]
                if len(half) >= 2:
                    x = np.arange(len(half), dtype=float)
                    evo_out["ret_curve_slope_lasthalf"] = float(np.polyfit(x, half, 1)[0])

    result = {
        "schema": "s1g_arm_result_v1",
        "arm": args.arm,
        "seed": args.seed,
        "N": N,
        "k_lo": k_lo,
        "k_hi": k_hi,
        "thresholds_file_hash": THR_HASH,
        "clean_seeds_Dx2_sha256": CLEAN_SHA,
        "s1e_thresholds_sha256_reused": THR.get("s1e_thresholds_sha256_reused_for_identical_acceptance"),
        "fitness_source_hash": FIT_HASH,
        "A_return": mem_ret,
        "void_env_A_ceiling": bool(void_A),
        "seed_void": seed_void,
        "pass": bool(ev.get("all_pass") and not seed_void),
        "eval": ev,
        "evo": evo_out,
        "wall_s": time.time() - t0,
        "MAIN": THR["MAIN"],
        "l2_variant": cfg.get("l2_variant"),
        "ladder_rung": cfg.get("ladder_rung"),
        "tune": bool(args.tune),
    }
    out_dir = TUNE_LOGS if args.tune else LOGS
    outp = out_dir / f"result_arm_{args.arm}_seed{args.seed}.json"
    outp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {outp} pass={result['pass']} void={seed_void} leak_mean={ev['C2_leak']['mean']:.3f} wall={result['wall_s']:.1f}s", flush=True)


if __name__ == "__main__":
    main()
