# -*- coding: utf-8 -*-
"""S1c extensions: binary gate, curriculum evolve, C4″_toy, agent I/O."""
from __future__ import annotations
import copy
import hashlib
import inspect
import json
from pathlib import Path
import numpy as np

import s1_env_s1 as E

HID = E.HID
SDIM = E.SDIM


def make_binary_gate(rng, N):
    """g = 1[w·[obs,s]+b > 0]; discrete innate-bias narrowing arm."""
    OBS = E.obs_dim(N)
    in_g = OBS + SDIM
    W = {
        "w_g": E._r(rng, in_g, 0.3),
        "b_g": E._r(rng, 1, 0.1),
        "W_write": E._r(rng, (SDIM, OBS), 0.35),
        "b_write": E._r(rng, SDIM, 0.05),
        "W_ss": 0.85 * np.eye(SDIM) + 0.15 * E._r(rng, (SDIM, SDIM), 0.25),
        "b_s": E._r(rng, SDIM, 0.05),
        "W_sa": E._r(rng, (N, SDIM), 0.35),
        "W_oa": E._r(rng, (N, OBS), 0.1),
        "b_a": E._r(rng, N, 0.05),
    }
    return {"kind": "binary_gate", "N": N, "W": W,
            "R": {k: np.full_like(v, 0.5) for k, v in W.items()}}


def make_gru_agent(N, params: dict):
    """Wrap trained GRU numpy weights as probeable agent."""
    return {"kind": "gru", "N": N, "W": params, "R": {}}


# Monkey-patch step_agent / has_latent / latent_dim via wrappers
_orig_step = E.step_agent
_orig_has = E.has_latent
_orig_ldim = E.latent_dim


def step_agent(agent, obs, state, greedy=True, rng=None):
    kind = agent["kind"]
    if kind == "binary_gate":
        W = agent["W"]
        N = agent["N"]
        s = state.get("s", np.zeros(SDIM))
        s_hold = np.tanh(W["W_ss"] @ s + W["b_s"])
        write = np.tanh(W["W_write"] @ obs + W["b_write"])
        feat = np.concatenate([obs, s_hold])
        g = 1.0 if float(W["w_g"] @ feat + W["b_g"][0]) > 0.0 else 0.0
        s = g * write + (1.0 - g) * s_hold
        logits = W["W_sa"] @ s + W["W_oa"] @ obs + W["b_a"]
        state = {"s": s}
        extras = {"s": s.copy(), "gate": g, "logits": logits}
        if greedy:
            a = int(np.argmax(logits))
        else:
            p = E.softmax(logits)
            a = int(rng.choice(N, p=p))
        return a, state, extras
    if kind == "gru":
        W = agent["W"]
        N = agent["N"]
        h = state.get("h", np.zeros(W["hid"]))
        x = obs.astype(np.float64)
        # Match torch.nn.GRUCell exactly
        r = E.sigmoid(W["W_ir"] @ x + W["b_ir"] + W["W_hr"] @ h + W["b_hr"])
        z = E.sigmoid(W["W_iz"] @ x + W["b_iz"] + W["W_hz"] @ h + W["b_hz"])
        n = np.tanh(W["W_in"] @ x + W["b_in"] + r * (W["W_hn"] @ h + W["b_hn"]))
        h = (1.0 - z) * n + z * h
        logits = W["W_ha"] @ h + W["b_a"]
        state = {"h": h}
        extras = {"s": h.copy(), "logits": logits}
        if greedy:
            a = int(np.argmax(logits))
        else:
            p = E.softmax(logits)
            a = int(rng.choice(N, p=p))
        return a, state, extras
    return _orig_step(agent, obs, state, greedy=greedy, rng=rng)


def has_latent(agent):
    return agent["kind"] in ("rnn", "hand_gate", "learn_gate", "binary_gate", "gru")


def latent_dim(agent):
    if agent["kind"] == "rnn":
        return HID
    if agent["kind"] == "gru":
        return int(agent["W"]["hid"])
    return SDIM


# Patch E module so evaluate/rollout use our step
E.step_agent = step_agent
E.has_latent = has_latent
E.latent_dim = latent_dim

def criterion3_flip_rate(agent, cents, N, T, n_trials, seed, within_steps=3):
    """Freeze W; write other-goal centroid into latent; behavior flips within steps."""
    if not has_latent(agent):
        return 0.0, 0
    rng = np.random.default_rng(seed)
    flips = 0
    usable = 0
    key = "h" if agent["kind"] in ("rnn", "gru") else "s"
    for _ in range(n_trials):
        env = E.SwitchCueNEnv(N=N, T=T, cue_every=False)
        obs = env.reset(rng)
        state = {}
        for t in range(T):
            goal = env.goal
            at_cue = env.cue_every or env._at_switch(t)
            if t >= 10 and (not at_cue) and t < T - within_steps - 1:
                others = [g for g in range(N) if g != goal]
                tgt = int(others[int(rng.integers(len(others)))])
                state_f = dict(state)
                state_f[key] = cents[tgt].copy()
                ok = False
                obs_f = obs.copy()
                st = state_f
                for step_i in range(within_steps):
                    a, st, _ = step_agent(agent, obs_f, st, greedy=True)
                    if a == tgt:
                        ok = True
                        break
                usable += 1
                if ok:
                    flips += 1
                break
            a, state, _ = step_agent(agent, obs, state, greedy=True)
            obs, r, done, info = env.step(a, rng)
            if done:
                break
    return float(flips / max(1, usable)), usable


E.criterion3_flip_rate = criterion3_flip_rate


def clone_agent(ag):
    out = {"kind": ag["kind"], "N": ag["N"],
           "W": {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in ag["W"].items()},
           "R": {k: v.copy() for k, v in ag.get("R", {}).items()}}
    if "write_init" in ag:
        out["write_init"] = ag["write_init"]
    return out


def mutate(agent, rng, strength=0.12):
    W, R = agent["W"], agent.get("R", {})
    for k, v in W.items():
        if not isinstance(v, np.ndarray):
            continue
        eff = strength * (0.25 + 0.75 * (1.0 - float(np.mean(R[k])))) if (R and k in R) else strength
        W[k] = W[k] + eff * rng.standard_normal(W[k].shape)


def update_resistance(agent):
    W, R = agent["W"], agent.get("R", {})
    if not R:
        return
    for k in W:
        if k not in R or not isinstance(W[k], np.ndarray):
            continue
        usage = np.abs(W[k])
        target = np.clip(usage / (usage + 0.5), 0.0, 0.9)
        R[k] = R[k] + 0.05 * (target - R[k])


MAKERS = {
    "memoryless": E.make_memoryless,
    "rnn": E.make_rnn,
    "hand_gate": E.make_handwritten_gate,
    "learn_gate": lambda rng, N: E.make_learnable_gate(rng, N, "standard"),
    "binary_gate": make_binary_gate,
}


def fitness_task_only(agent, rng, N, T, K_eval=4, k_lo=None, k_hi=None):
    """Mean return only. No ||Δs||, s variance, or s stability term."""
    scores = []
    for _ in range(K_eval):
        env = E.SwitchCueNEnv(N=N, T=T, cue_every=False,
                              k_lo=E.K_LO if k_lo is None else k_lo,
                              k_hi=E.K_HI if k_hi is None else k_hi)
        ret, _ = E.rollout_from_reset(agent, env, rng, greedy=True)
        scores.append(ret)
    return float(np.mean(scores))


FITNESS_SOURCE = inspect.getsource(fitness_task_only)


def fitness_source_hash():
    return hashlib.sha256(FITNESS_SOURCE.encode()).hexdigest()


def evolve(kind, rng, N=4, gens=100, pop_n=36, T=200, mut=0.12, elite=0.25,
           K_eval=3, log_every=20, probe_cb=None,
           curriculum=None):
    """curriculum: dict with k_start=[lo,hi], k_end=[lo,hi] or None."""
    maker = MAKERS[kind]
    pop = [maker(rng, N) for _ in range(pop_n)]
    best_hist, mean_hist = [], []
    probes = []
    best_ag = None
    best_fit = -1.0

    for gen in range(gens):
        if curriculum is not None:
            t = gen / max(1, gens - 1)
            k_lo = int(round(curriculum["k_start"][0] * (1 - t) + curriculum["k_end"][0] * t))
            k_hi = int(round(curriculum["k_start"][1] * (1 - t) + curriculum["k_end"][1] * t))
            k_lo, k_hi = min(k_lo, k_hi), max(k_lo, k_hi)
        else:
            k_lo = k_hi = None
        fits = np.array([
            fitness_task_only(ag, rng, N, T, K_eval=K_eval, k_lo=k_lo, k_hi=k_hi)
            for ag in pop
        ])
        order = np.argsort(-fits)
        mean_hist.append(float(fits.mean()))
        best_hist.append(float(fits[order[0]]))
        if fits[order[0]] > best_fit:
            best_fit = float(fits[order[0]])
            best_ag = clone_agent(pop[order[0]])
        if log_every and gen % log_every == 0:
            extra = f" K=[{k_lo},{k_hi}]" if curriculum is not None else ""
            print(f"  [{kind}] gen={gen:3d} best={best_hist[-1]:.3f} mean={mean_hist[-1]:.3f}{extra}",
                  flush=True)
        if probe_cb is not None and (gen % log_every == 0 or gen == gens - 1):
            try:
                probes.append(probe_cb(gen, best_ag if best_ag is not None else pop[order[0]], rng))
            except Exception as e:
                probes.append({"gen": gen, "error": str(e)})
        n_elite = max(1, int(pop_n * elite))
        new_pop = [clone_agent(pop[i]) for i in order[:n_elite]]
        while len(new_pop) < pop_n:
            parent = pop[int(order[rng.integers(n_elite)])]
            child = clone_agent(parent)
            mutate(child, rng, strength=mut)
            update_resistance(child)
            new_pop.append(child)
        pop = new_pop

    return best_ag, {"best_hist": best_hist, "mean_hist": mean_hist,
                     "best_fit_train": best_fit, "probes": probes}


def c4pp_toy(agent, N, T, seed, thr, n_eps=16):
    """Toy C4″: own-codebook centroids; pin opp vs same; sparse+every specificity."""
    if not has_latent(agent):
        return {"pass": False, "na": True}
    cents, _, _ = E.goal_centroids(agent, N=N, T=T, seed=seed, n_eps=max(12, n_eps))
    key = "h" if agent["kind"] in ("rnn", "gru") else "s"

    def _run(cue_every, force_mode, ep_seed):
        rng = np.random.default_rng(ep_seed)
        rets = []
        for i in range(n_eps):
            env = E.SwitchCueNEnv(N=N, T=T, cue_every=cue_every)
            r2 = np.random.default_rng(int(rng.integers(1 << 31)))
            obs = env.reset(r2)
            state = {}
            total_r = 0.0
            n = 0
            while True:
                goal = env.goal
                # pin before step (agent may overwrite on cue)
                if force_mode == "opp":
                    others = [g for g in range(N) if g != goal]
                    tgt = others[int(r2.integers(len(others)))]
                    state = dict(state)
                    state[key] = cents[tgt].copy()
                elif force_mode == "same":
                    state = dict(state)
                    state[key] = cents[goal].copy()
                a, state, _ = step_agent(agent, obs, state, greedy=True, rng=r2)
                obs, r, done, info = env.step(a, r2)
                total_r += r
                n += 1
                if done:
                    break
            rets.append(total_r / max(1, n))
        return float(np.mean(rets))

    base = seed + 50_000
    R_same_sp = _run(False, "same", base)
    R_opp_sp = _run(False, "opp", base + 1)
    R_same_ev = _run(True, "same", base + 2)
    R_opp_ev = _run(True, "opp", base + 3)
    drop_sp = R_same_sp - R_opp_sp
    drop_ev = R_same_ev - R_opp_ev
    thr_drop = float(thr["sparse_return_drop_min"])
    thr_rs = float(thr["R_same_min"])
    thr_frac = float(thr["every_drop_max_frac_of_sparse"])
    ok = (drop_sp >= thr_drop) and (R_same_sp >= thr_rs) and (drop_ev <= thr_frac * max(drop_sp, 1e-9))
    return {
        "pass": bool(ok),
        "R_same_sparse": R_same_sp, "R_opp_sparse": R_opp_sp,
        "drop_sparse": float(drop_sp),
        "R_same_every": R_same_ev, "R_opp_every": R_opp_ev,
        "drop_every": float(drop_ev),
        "thr_drop": thr_drop, "thr_R_same": thr_rs, "thr_every_frac": thr_frac,
    }


def config_hash(cfg: dict) -> str:
    raw = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
