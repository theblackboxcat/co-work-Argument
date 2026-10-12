# -*- coding: utf-8 -*-
"""S1h_es_step_fix single-arm runner.
  python run_arm.py --arm ES_easy --seed 200
  python run_arm.py --arm ES_main --seed 200
  python run_arm.py --arm ES_easy_legacy --seed 200
  python run_arm.py --arm ES_main --seed 100 --tune --lr 0.01
Science seeds: Dx2 clean [200,205,210,211,212,216,218,219]. Tune ONLY: 100-103 (--tune).
Science runs require frozen thresholds (status=frozen, lr set, sha file matches).
Leak VOID (N=4): Dx2 probe n_eps=12 x n_rep=5; mean>0.35 -> VOID; denom=8.
"""
from __future__ import annotations
import argparse, json, sys, time, hashlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))
import s1_env_s1 as E
import s1e_lib as L

LOGS = ROOT / "logs"
GENES = ROOT / "genes"
TUNE_LOGS = ROOT / "tune"
for d in (LOGS, GENES, TUNE_LOGS):
    d.mkdir(exist_ok=True)

THR_PATH = ROOT / "frozen" / "thresholds_S1h.json"
THR = json.loads(THR_PATH.read_text(encoding="utf-8"))
THR_HASH = hashlib.sha256(THR_PATH.read_bytes()).hexdigest()
FIT_HASH = L.fitness_source_hash()
CLEAN_SHA = (ROOT / "frozen" / "clean_seeds_Dx2.sha256").read_text().split()[0]
MEM_S1G = json.loads((ROOT / "frozen" / "mem_returns_S1g.json").read_text(encoding="utf-8"))

T = int(THR["env"]["T"])
ACC = THR["acceptance_per_seed"]
C1_MARGIN = float(ACC["C1_margin_over_memoryless"])
C1_ABS = float(ACC["C1_absolute_return"])
C2_MIN = float(ACC["C2_decode_acc_min"])
C3_STEPS = int(ACC["C3_flip_within_steps"])
C3_MIN = float(ACC["C3_flip_rate_min"])
C4PP = ACC["C4pp_toy"]
C6_MIN = float(ACC["C6_removal_return_min"])
C6_FAC = int(ACC["C6_removal_segment_len_factor"])
LEAK_MAX_N4 = float(ACC["C2_leak_max_N4"])
LEAK_WIN = int(ACC["C2_leak_window"])
LEAK_NEPS = int(THR["leak_probe"]["n_eps"])
LEAK_NREP = int(THR["leak_probe"]["n_rep"])
A_VOID_N4 = float(THR["void_rules"]["A_return_gt_N4"])

ARMS = ("ES_main", "ES_easy", "ES_easy_legacy")
# ES_easy and ES_easy_legacy share a stream: identical init and generation-0 noise (paired).
ARM_STREAM = {"ES_main": 1, "ES_easy": 2, "ES_easy_legacy": 2}


def save_agent(ag, path):
    payload = {"kind": ag["kind"], "N": ag["N"]}
    arrays = {}
    for k, v in (ag.get("W") or {}).items():
        if isinstance(v, np.ndarray):
            arrays[f"W_{k}"] = v
        elif isinstance(v, (int, float)):
            payload[k] = float(v)
    np.savez_compressed(path, **payload, **arrays)


def n2_rules(cfg):
    a = cfg.get("acceptance_N2")
    return a if (int(cfg["N"]) == 2 and a) else None


def leak_mean_dx2(ag, N, T, seed, k_lo, k_hi, leak_max, leak_void_enabled):
    samples = []
    for i in range(LEAK_NREP):
        probe_seed = int(seed + 10007 + i * 100003)
        acc = E.obs_window_decode_acc(ag, N=N, T=T, seed=probe_seed, n_eps=LEAK_NEPS,
                                      window=LEAK_WIN, k_lo=k_lo, k_hi=k_hi)
        samples.append(float(acc))
    arr = np.asarray(samples, float)
    return {
        "samples": samples, "mean": float(arr.mean()),
        "sd": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "n_eps": LEAK_NEPS, "n_rep": LEAK_NREP, "max": leak_max,
        "void_enabled": bool(leak_void_enabled),
        "void": bool(leak_void_enabled and float(arr.mean()) > leak_max),
    }


def eval_arm_agent(ag, mem_return, N, T, seed, k_lo, k_hi, leak_max, leak_void_enabled):
    eval_seed = seed + 10_000
    n_eps = 16
    out = {"kind": ag["kind"]}
    m, s, _ = E.evaluate(ag, N=N, T=T, n_eps=n_eps, seed=eval_seed, greedy=True, k_lo=k_lo, k_hi=k_hi)
    out["return"] = {"mean": float(m), "std": float(s), "n": n_eps}
    c1 = (m >= mem_return + C1_MARGIN) and (m >= C1_ABS)
    out["C1"] = {"pass": bool(c1), "return": float(m), "mem_return": float(mem_return),
                 "margin": C1_MARGIN, "abs": C1_ABS}
    S_tr, G_tr, _ = E.collect_s_goal(ag, n_eps=max(8, n_eps // 2), N=N, T=T, seed=eval_seed + 1,
                                     non_cue_only=True, k_lo=k_lo, k_hi=k_hi)
    S_te, G_te, _ = E.collect_s_goal(ag, n_eps=max(8, n_eps // 2), N=N, T=T, seed=eval_seed + 2,
                                     non_cue_only=True, k_lo=k_lo, k_hi=k_hi)
    dec = E.multinomial_decode_acc(S_tr, G_tr, S_te, G_te, N)
    c2 = dec >= C2_MIN
    out["C2"] = {"pass": bool(c2), "decode_acc": float(dec), "threshold": C2_MIN}
    leak = leak_mean_dx2(ag, N, T, seed, k_lo, k_hi, leak_max, leak_void_enabled)
    out["C2_leak"] = leak
    cents, _, _ = E.goal_centroids(ag, N=N, T=T, seed=eval_seed + 3, n_eps=max(12, n_eps),
                                   k_lo=k_lo, k_hi=k_hi)
    flip, n_u = E.criterion3_flip_rate(ag, cents, N=N, T=T, n_trials=max(40, n_eps * 2),
                                       seed=eval_seed + 4, within_steps=C3_STEPS, k_lo=k_lo, k_hi=k_hi)
    c3 = flip >= C3_MIN
    out["C3"] = {"pass": bool(c3), "flip_rate": float(flip), "threshold": C3_MIN, "n_trials": int(n_u)}
    c4 = L.c4pp_toy(ag, N=N, T=T, seed=eval_seed + 5, thr=C4PP, n_eps=int(C4PP.get("n_eps", 16)),
                    k_lo=k_lo, k_hi=k_hi)
    out["C4pp"] = c4
    out["C5"] = {"pass": True, "note": "fitness_task_only; no stability terms in source"}
    m6, _, _ = E.evaluate(ag, N=N, T=T, n_eps=n_eps, seed=eval_seed + 9, removal_mode=True,
                          removal_factor=C6_FAC, k_lo=k_lo, k_hi=k_hi)
    c6 = m6 >= C6_MIN
    out["C6"] = {"pass": bool(c6), "return": float(m6), "threshold": C6_MIN}
    out["void_leak"] = bool(leak["void"])
    out["all_pass"] = bool(c1 and c2 and c3 and c4.get("pass", False) and c6 and not leak["void"])
    return out


def mem_baseline_return(seed, N, T, k_lo, k_hi, smoke=False):
    rng = np.random.default_rng(seed)
    gens, pop = (8, 12) if smoke else (100, 36)
    old_lo, old_hi = E.K_LO, E.K_HI
    E.K_LO, E.K_HI = int(k_lo), int(k_hi)
    try:
        best, _ = L.evolve("memoryless", rng, N=N, gens=gens, pop_n=pop, T=T, K_eval=2 if smoke else 3)
    finally:
        E.K_LO, E.K_HI = old_lo, old_hi
    m, _, _ = E.evaluate(best, N=N, T=T, n_eps=16 if not smoke else 6, seed=seed + 10_000, greedy=True,
                         k_lo=k_lo, k_hi=k_hi)
    return float(m)


def train_arm(arm, seed, lr, smoke=False):
    cfg = THR["arms"][arm]
    N = int(cfg["N"])
    k_lo, k_hi = int(cfg["k_lo"]), int(cfg["k_hi"])
    rng = np.random.default_rng([int(seed), ARM_STREAM[arm]])
    kw = dict(N=N, T=T, hidden=int(cfg["hidden"]), n_workers=int(cfg["n_workers"]),
              generations=int(cfg["generations"]), sigma=float(cfg["pop_sigma"]), lr=float(lr),
              K_eval=int(cfg["K_eval"]), total_evals_cap=int(cfg["total_param_evals_target"]),
              k_lo=k_lo, k_hi=k_hi, smoke=smoke)
    if cfg["step_rule"] == "standard":
        import s1h_es_gru as ES
        params, hist = ES.openai_es_gru_std(rng, **kw)
    elif cfg["step_rule"] == "s1g_legacy":
        import s1g_es_gru as ES
        params, hist = ES.openai_es_gru(rng, **kw)
    else:
        raise ValueError(cfg["step_rule"])
    return L.make_gru_agent(N, params), hist, N, k_lo, k_hi, cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=ARMS)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--lr", type=float, default=None, help="tune-only override")
    args = ap.parse_args()

    cfg = THR["arms"][args.arm]
    if args.tune:
        assert args.seed in set(THR["tune_seeds"]), f"tune seed {args.seed} not in {THR['tune_seeds']}"
    elif not args.smoke:
        assert args.seed in set(THR["seeds"]), f"seed {args.seed} not in science seeds {THR['seeds']}"
        assert args.lr is None, "--lr override forbidden on science seeds"
        assert THR.get("status") == "frozen", "thresholds not frozen; science run forbidden"
        sha_file = (ROOT / "frozen" / "thresholds_S1h.sha256").read_text().split()[0]
        assert sha_file == THR_HASH, "thresholds_S1h.json changed after freeze"
    lr = args.lr if args.lr is not None else cfg.get("lr")
    if cfg["step_rule"] == "s1g_legacy":
        lr = float(cfg["lr"])
    assert lr is not None, "lr not set (pending tune); pass --lr with --tune"

    t0 = time.time()
    print(f"===== S1h arm={args.arm} seed={args.seed} lr={lr} smoke={args.smoke} tune={args.tune} =====", flush=True)
    print(f"thresholds_sha256={THR_HASH}", flush=True)

    ag, evo, N, k_lo, k_hi, cfg = train_arm(args.arm, args.seed, lr, smoke=args.smoke)
    print(f"-- mem baseline A N={N} K=[{k_lo},{k_hi}] (train wall {time.time() - t0:.0f}s)", flush=True)
    mem_ret = mem_baseline_return(args.seed, N, T, k_lo, k_hi, smoke=args.smoke)
    mem_s1g = MEM_S1G.get(str(args.seed)) if N == 4 else None

    n2 = n2_rules(cfg)
    leak_max = float(n2["C2_leak_max"]) if n2 else LEAK_MAX_N4
    leak_void_enabled = bool(n2["C2_leak_void_enabled"]) if n2 else True
    a_void_line = float(n2["A_return_gt_void"]) if n2 else A_VOID_N4

    tag = f"_lr{lr:g}" if args.tune else ""
    out_dir = TUNE_LOGS if args.tune else LOGS
    if not args.smoke:
        save_agent(ag, GENES / f"gene_N{N}_seed{args.seed}_{args.arm}{tag}.npz")
    (out_dir / f"hist_{args.arm}_seed{args.seed}{tag}.json").write_text(
        json.dumps(evo["hist"], ensure_ascii=False), encoding="utf-8")

    print("-- eval (leak n_eps x n_rep = %d x %d)" % (LEAK_NEPS, LEAK_NREP), flush=True)
    ev = eval_arm_agent(ag, mem_ret, N, T, args.seed, k_lo, k_hi, leak_max, leak_void_enabled)
    void_A = mem_ret > a_void_line
    seed_void = bool(void_A or ev["void_leak"])
    h = evo["hist"]
    means = [x["mean"] for x in h]
    evo_out = {k: evo[k] for k in ("best_fit_train", "evals", "hist_len", "optimizer", "no_goal_labels") if k in evo}
    evo_out.update({
        "pop_mean_first": means[0] if means else None,
        "pop_mean_last": means[-1] if means else None,
        "pop_mean_max": max(means) if means else None,
        "hist_tail": h[-3:],
    })
    result = {
        "schema": "s1h_arm_result_v1",
        "arm": args.arm, "seed": args.seed, "N": N, "k_lo": k_lo, "k_hi": k_hi,
        "step_rule": cfg["step_rule"], "lr": float(lr), "sigma": float(cfg["pop_sigma"]),
        "thresholds_file_hash": THR_HASH, "clean_seeds_Dx2_sha256": CLEAN_SHA,
        "fitness_source_hash": FIT_HASH,
        "A_return": mem_ret, "A_return_S1g_record": mem_s1g,
        "A_void_line": a_void_line, "void_env_A_ceiling": bool(void_A),
        "seed_void": seed_void,
        "pass": bool(ev["all_pass"] and not seed_void),
        "eval": ev, "evo": evo_out,
        "wall_s": time.time() - t0,
        "role": cfg.get("role"), "tune": bool(args.tune), "smoke": bool(args.smoke),
    }
    outp = out_dir / f"result_arm_{args.arm}_seed{args.seed}{tag}{'_smoke' if args.smoke else ''}.json"
    outp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {outp.name} pass={result['pass']} void={seed_void} ret={ev['return']['mean']:.3f} "
          f"A={mem_ret:.3f} leak={ev['C2_leak']['mean']:.3f} wall={result['wall_s']:.1f}s", flush=True)


if __name__ == "__main__":
    main()
