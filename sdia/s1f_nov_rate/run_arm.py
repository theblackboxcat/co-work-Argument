# -*- coding: utf-8 -*-
"""S1f_nov_rate runner — Nov hit-rate (新建预注册，非修订 S1e).

  python run_arm.py --arm Nov --seed 16 --replica 1
  python run_arm.py --arm Nov --seed 16 --replica 2
  python run_arm.py --arm Nov --seed 100 --replica 1 --smoke   # tune only

Writes logs/result_arm_Nov_seed{SEED}_r{REPLICA}.json and genes/
"""
from __future__ import annotations
import argparse, json, os, sys, time, hashlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))
import s1_env_s1 as E
import s1e_lib as L
import s1e_arms as A

LOGS = ROOT / "logs"
GENES = ROOT / "genes"
LOGS.mkdir(exist_ok=True)
GENES.mkdir(exist_ok=True)

THR_PATH = ROOT / "frozen" / "thresholds_S1f_nov_rate.json"
THR = json.loads(THR_PATH.read_text(encoding="utf-8"))
THR_HASH = hashlib.sha256(THR_PATH.read_bytes()).hexdigest()
FIT_HASH = L.fitness_source_hash()

T = int(THR["env"]["T"])
N_DEFAULT = int(THR["env"]["N_goals"])
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

S1E_LOGS = Path("/workspace/proj_20261009/必要性重建/S1e_optimizer_signal_disentangle/logs")


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


def load_s1e_A_return(seed: int) -> tuple[float, dict]:
    p = S1E_LOGS / f"result_arm_A_seed{seed}.json"
    if not p.exists():
        raise FileNotFoundError(f"missing S1e A baseline for seed {seed}: {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    # Prefer A_return field (used for C1 in S1e); fallback eval return
    mem = d.get("A_return")
    if mem is None:
        mem = d["eval"]["return"]["mean"]
    meta = {
        "source": "S1e_A_return_reuse",
        "path": str(p),
        "s1e_seed_void": bool(d.get("seed_void")),
        "s1e_A_eval_return": float(d["eval"]["return"]["mean"]),
    }
    return float(mem), meta


def eval_arm_agent(ag, mem_return, N, T, seed):
    eval_seed = seed + 10_000
    n_eps = 16
    out = {"kind": ag["kind"]}
    m, s, xs = E.evaluate(ag, N=N, T=T, n_eps=n_eps, seed=eval_seed, greedy=True)
    out["return"] = {"mean": m, "std": s, "n": n_eps}
    margin = m - mem_return
    c1 = (margin >= C1_MARGIN) and (m >= C1_ABS)
    out["C1"] = {"pass": bool(c1), "margin": float(margin), "abs": float(m)}
    if not L.has_latent(ag):
        out["C2"] = {"pass": False, "na": True}
        out["C2_leak"] = {"pass": True, "na": True, "void": False}
        out["C3"] = {"pass": False, "na": True}
        out["C4pp"] = {"pass": False, "na": True}
        out["C6"] = {"pass": False, "na": True}
        out["C5"] = {"pass": True, "fitness_source_hash": FIT_HASH}
        out["all_pass"] = False
        out["void_leak"] = False
        return out
    S_tr, G_tr, _ = E.collect_s_goal(ag, n_eps=max(8, n_eps // 2), N=N, T=T,
                                     seed=eval_seed + 1, non_cue_only=True)
    S_te, G_te, _ = E.collect_s_goal(ag, n_eps=max(8, n_eps // 2), N=N, T=T,
                                     seed=eval_seed + 2, non_cue_only=True)
    dec = E.multinomial_decode_acc(S_tr, G_tr, S_te, G_te, N)
    c2 = dec >= C2_MIN
    out["C2"] = {"pass": bool(c2), "decode_acc": float(dec), "threshold": C2_MIN}
    leak = E.obs_window_decode_acc(ag, N=N, T=T, seed=eval_seed + 7, n_eps=12, window=LEAK_WIN)
    void_leak = leak > LEAK_MAX
    out["C2_leak"] = {"pass": (not void_leak), "leak_acc": float(leak),
                      "max_allowed": LEAK_MAX, "void": bool(void_leak)}
    cents, _, _ = E.goal_centroids(ag, N=N, T=T, seed=eval_seed + 3, n_eps=max(12, n_eps))
    flip, n_u = E.criterion3_flip_rate(ag, cents, N=N, T=T, n_trials=max(40, n_eps * 2),
                                       seed=eval_seed + 4, within_steps=C3_STEPS)
    c3 = flip >= C3_MIN
    out["C3"] = {"pass": bool(c3), "flip_rate": float(flip), "threshold": C3_MIN, "n_trials": int(n_u)}
    c4 = L.c4pp_toy(ag, N=N, T=T, seed=eval_seed + 5, thr=C4PP, n_eps=int(C4PP.get("n_eps", 16)))
    out["C4pp"] = c4
    src = L.FITNESS_SOURCE
    body_lines = [ln for ln in src.splitlines() if not ln.strip().startswith('#')
                  and '"""' not in ln]
    body = "\n".join(body_lines)
    has_bad = any(b in body for b in ["coh_w", "s_var", "stability_term", "delta_s_penalty"])
    c5 = (not has_bad) and ("scores.append(ret)" in src)
    out["C5"] = {"pass": bool(c5), "fitness_source_hash": FIT_HASH}
    m6, s6, _ = E.evaluate(ag, N=N, T=T, n_eps=n_eps, seed=eval_seed + 9,
                           removal_mode=True, removal_factor=C6_FAC)
    c6 = m6 >= C6_MIN
    out["C6"] = {"pass": bool(c6), "return": float(m6), "threshold": C6_MIN}
    all_pass = bool(c1 and c2 and (not void_leak) and c3 and c4.get("pass") and c5 and c6)
    out["all_pass"] = all_pass
    out["void_leak"] = bool(void_leak)
    return out


def nov_rng(seed: int, replica: int):
    """Independent of S1e (which used seed + hash('Nov')%10000)."""
    return np.random.default_rng(int(seed) + 1_000_003 * int(replica) + (hash("Nov") % 10000))


def train_nov(seed, replica, N, smoke=False):
    cfg = THR["arms"]["Nov"]
    rng = nov_rng(seed, replica)
    g, p = (6, 12) if smoke else (int(cfg["gens"]), int(cfg["pop"]))
    best, hist = A.evolve_novelty(
        rng, N=N, gens=g, pop_n=p, T=T,
        K_eval=2 if smoke else int(cfg["K_eval"]),
        mut=float(cfg.get("mut", 0.12)),
        elite=float(cfg.get("elite", 0.25)),
    )
    return best, hist


def allowed_seed(seed: int, smoke: bool) -> bool:
    if smoke:
        return seed in THR["tune_seeds"] or seed in THR["seeds_primary"] or seed in THR["seeds_extended_rate"]
    # science: primary or extended
    return seed in THR["seeds_primary"] or seed in THR["seeds_extended_rate"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["Nov"])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--replica", type=int, required=True, help="replica_id (primary=1, extended=2)")
    ap.add_argument("--N", type=int, default=N_DEFAULT)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--mem_return", type=float, default=None)
    args = ap.parse_args()

    if args.smoke:
        assert args.seed in THR["tune_seeds"], f"smoke/tune only on {THR['tune_seeds']}, got {args.seed}"
    else:
        assert allowed_seed(args.seed, False), f"seed {args.seed} not in pre-registered science sets"
        if args.replica == int(THR["replica_primary"]):
            assert args.seed in THR["seeds_primary"], f"primary replica requires seed in {THR['seeds_primary']}"
        elif args.replica == int(THR["replica_extended"]):
            assert args.seed in THR["seeds_extended_rate"], f"extended replica requires seed in {THR['seeds_extended_rate']}"
        else:
            raise AssertionError(f"replica must be {THR['replica_primary']} or {THR['replica_extended']}")

    t0 = time.time()
    print(f"===== S1f_nov_rate arm={args.arm} seed={args.seed} r={args.replica} "
          f"N={args.N} smoke={args.smoke} =====", flush=True)
    print(f"thresholds_sha256={THR_HASH}", flush=True)
    assert THR_HASH == Path(ROOT / "frozen" / "thresholds_S1f_nov_rate.sha256").read_text().split()[0], \
        "thresholds hash mismatch vs frozen sha256 file"

    if args.mem_return is not None:
        mem_ret = float(args.mem_return)
        a_meta = {"source": "cli_mem_return"}
    elif args.smoke:
        # quick local A for tune seed only
        rng = np.random.default_rng(args.seed)
        best_a, _ = L.evolve("memoryless", rng, N=args.N, gens=8, pop_n=12, T=T, K_eval=2)
        mem_ret, _, _ = E.evaluate(best_a, N=args.N, T=T, n_eps=6, seed=args.seed + 10_000, greedy=True)
        a_meta = {"source": "smoke_local_A", "A_return": float(mem_ret)}
    else:
        print("-- load S1e A baseline", flush=True)
        mem_ret, a_meta = load_s1e_A_return(args.seed)

    print(f"-- train Nov seed={args.seed} replica={args.replica}", flush=True)
    ag, evo = train_nov(args.seed, args.replica, args.N, smoke=args.smoke)
    gene_path = GENES / f"gene_N{args.N}_seed{args.seed}_r{args.replica}_Nov.npz"
    save_agent(ag, gene_path)

    print("-- eval", flush=True)
    ev = eval_arm_agent(ag, mem_ret, args.N, T, args.seed)
    void_A = mem_ret > float(THR["void_rules"]["A_return_gt_N4"])
    seed_void = bool(void_A or ev.get("void_leak"))
    panel = "primary" if (not args.smoke and args.replica == int(THR["replica_primary"])
                          and args.seed in THR["seeds_primary"]) else (
            "extended" if (not args.smoke and args.replica == int(THR["replica_extended"])) else "tune_or_other")
    result = {
        "schema": "s1f_nov_rate_result_v1",
        "experiment_id": "S1f_nov_rate",
        "arm": "Nov",
        "seed": args.seed,
        "replica": args.replica,
        "panel": panel,
        "N": args.N,
        "thresholds_file_hash": THR_HASH,
        "fitness_source_hash": FIT_HASH,
        "tier_label_zh": "指定统计量档",
        "tier_name": "松档",
        "l2_variant": "L2-self_candidate",
        "gate_form": THR["tier"]["gate_form"],
        "forbid_claim": THR["tier"]["forbid_claim"],
        "A_return": mem_ret,
        "A_meta": a_meta,
        "void_env_A_ceiling": bool(void_A),
        "seed_void": seed_void,
        "pass": bool(ev.get("all_pass") and not seed_void),
        "eval": ev,
        "evo": {},
        "wall_s": time.time() - t0,
        "MAIN": THR["MAIN"],
        "void_denom_policy": 8,
    }
    evo_out = {}
    if isinstance(evo, dict):
        for k in ("best_fit_train", "best_ret_train", "evals", "epochs_ran", "no_goal_labels", "hist_len"):
            if k in evo:
                evo_out[k] = evo[k]
        if "best_hist" in evo and isinstance(evo["best_hist"], list) and evo["best_hist"]:
            evo_out["best_hist_tail"] = evo["best_hist"][-5:]
            evo_out["best_hist_len"] = len(evo["best_hist"])
    result["evo"] = evo_out

    outp = LOGS / f"result_arm_Nov_seed{args.seed}_r{args.replica}.json"
    outp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "pass": result["pass"], "void": seed_void,
                      "ret": ev["return"]["mean"], "panel": panel,
                      "wall_s": result["wall_s"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
