# -*- coding: utf-8 -*-
"""S1e arms: G-RL (A2C/REINFORCE), OpenAI-ES learn_gate, Baldwin, Novelty gate."""
from __future__ import annotations
import copy
import numpy as np

import s1_env_s1 as E
import s1e_lib as L

SDIM = E.SDIM
HID = E.HID


# ---------------------------------------------------------------------------
# Novelty gate agent
# ---------------------------------------------------------------------------
def make_novelty_gate(rng, N):
    """g = σ(k * ||x - x̄|| - θ); no cue channel designated. x includes full obs."""
    OBS = E.obs_dim(N)
    W = {
        "k": np.array([1.0], dtype=float),
        "theta": np.array([0.5], dtype=float),
        "ema": np.array([0.05], dtype=float),  # xbar update rate (evolved soft)
        "W_write": E._r(rng, (SDIM, OBS), 0.35),
        "b_write": E._r(rng, SDIM, 0.05),
        "W_ss": 0.85 * np.eye(SDIM) + 0.15 * E._r(rng, (SDIM, SDIM), 0.25),
        "b_s": E._r(rng, SDIM, 0.05),
        "W_sa": E._r(rng, (N, SDIM), 0.35),
        "W_oa": E._r(rng, (N, OBS), 0.1),
        "b_a": E._r(rng, N, 0.05),
    }
    return {"kind": "novelty_gate", "N": N, "W": W,
            "R": {k: np.full_like(v, 0.5) for k, v in W.items()}}


def step_novelty(agent, obs, state, greedy=True, rng=None):
    W = agent["W"]
    N = agent["N"]
    s = state.get("s", np.zeros(SDIM))
    xbar = state.get("xbar", np.zeros_like(obs))
    s_hold = np.tanh(W["W_ss"] @ s + W["b_s"])
    write = np.tanh(W["W_write"] @ obs + W["b_write"])
    ema = float(np.clip(W["ema"][0], 0.01, 0.5))
    xbar = (1.0 - ema) * xbar + ema * obs
    dist = float(np.linalg.norm(obs - xbar))
    k = float(W["k"][0])
    theta = float(W["theta"][0])
    g = float(E.sigmoid(k * dist - theta))
    s = g * write + (1.0 - g) * s_hold
    logits = W["W_sa"] @ s + W["W_oa"] @ obs + W["b_a"]
    state = {"s": s, "xbar": xbar}
    extras = {"s": s.copy(), "gate": g, "logits": logits, "dist": dist}
    if greedy:
        a = int(np.argmax(logits))
    else:
        p = E.softmax(logits)
        a = int(rng.choice(N, p=p))
    return a, state, extras


# ---------------------------------------------------------------------------
# Baldwin: genome = init + plasticity coeffs; weights NOT inherited across gens
# lifetime three-factor: (R - baseline) * pre * post
# ---------------------------------------------------------------------------
def make_baldwin_genome(rng, N):
    OBS = E.obs_dim(N)
    # init templates + plasticity rates (eta) + baseline EMA
    G = {
        "W_write0": E._r(rng, (SDIM, OBS), 0.25),
        "b_write0": E._r(rng, SDIM, 0.05),
        "W_ss0": 0.85 * np.eye(SDIM) + 0.1 * E._r(rng, (SDIM, SDIM), 0.2),
        "b_s0": E._r(rng, SDIM, 0.05),
        "W_sa0": E._r(rng, (N, SDIM), 0.25),
        "W_oa0": E._r(rng, (N, OBS), 0.1),
        "b_a0": E._r(rng, N, 0.05),
        "w_g0": E._r(rng, OBS + SDIM, 0.2),
        "b_g0": E._r(rng, 1, 0.05),
        "eta_write": np.array([0.02], dtype=float),
        "eta_sa": np.array([0.02], dtype=float),
        "eta_g": np.array([0.01], dtype=float),
        "baseline_ema": np.array([0.05], dtype=float),
    }
    return {"kind": "baldwin_genome", "N": N, "G": G}


def instantiate_baldwin(genome, rng):
    """Fresh weights from genome init (not inherited)."""
    G = genome["G"]
    N = genome["N"]
    noise = 0.05
    W = {
        "W_write": G["W_write0"] + noise * rng.standard_normal(G["W_write0"].shape),
        "b_write": G["b_write0"].copy(),
        "W_ss": G["W_ss0"].copy(),
        "b_s": G["b_s0"].copy(),
        "W_sa": G["W_sa0"] + noise * rng.standard_normal(G["W_sa0"].shape),
        "W_oa": G["W_oa0"].copy(),
        "b_a": G["b_a0"].copy(),
        "w_g": G["w_g0"] + noise * rng.standard_normal(G["w_g0"].shape),
        "b_g": G["b_g0"].copy(),
        "eta_write": float(np.clip(G["eta_write"][0], 1e-4, 0.2)),
        "eta_sa": float(np.clip(G["eta_sa"][0], 1e-4, 0.2)),
        "eta_g": float(np.clip(G["eta_g"][0], 1e-4, 0.2)),
        "baseline_ema": float(np.clip(G["baseline_ema"][0], 0.01, 0.3)),
    }
    return {"kind": "baldwin_agent", "N": N, "W": W, "R": {}}


def step_baldwin(agent, obs, state, greedy=True, rng=None, plastic=False, reward=None):
    W = agent["W"]
    N = agent["N"]
    s = state.get("s", np.zeros(SDIM))
    baseline = state.get("baseline", 0.0)
    s_hold = np.tanh(W["W_ss"] @ s + W["b_s"])
    write = np.tanh(W["W_write"] @ obs + W["b_write"])
    feat = np.concatenate([obs, s_hold])
    g = float(E.sigmoid(float(W["w_g"] @ feat + W["b_g"][0])))
    s_new = g * write + (1.0 - g) * s_hold
    logits = W["W_sa"] @ s_new + W["W_oa"] @ obs + W["b_a"]
    if greedy:
        a = int(np.argmax(logits))
    else:
        p = E.softmax(logits)
        a = int(rng.choice(N, p=p))
    # three-factor plasticity after action if reward provided
    if plastic and reward is not None:
        ema = W["baseline_ema"]
        mod = float(reward) - baseline
        baseline = (1.0 - ema) * baseline + ema * float(reward)
        pre_w = obs
        post_w = write
        W["W_write"] = W["W_write"] + W["eta_write"] * mod * np.outer(post_w, pre_w)
        # sa: pre=s_new, post=onehot action
        post_a = np.zeros(N); post_a[a] = 1.0
        W["W_sa"] = W["W_sa"] + W["eta_sa"] * mod * np.outer(post_a, s_new)
        W["w_g"] = W["w_g"] + W["eta_g"] * mod * g * (1 - g) * feat
        # clip
        for k in ("W_write", "W_sa", "w_g"):
            W[k] = np.clip(W[k], -5.0, 5.0)
    state = {"s": s_new, "baseline": baseline}
    extras = {"s": s_new.copy(), "gate": g, "logits": logits}
    return a, state, extras


def rollout_baldwin_lifetime(genome, env, rng, plastic_steps=150, greedy=False):
    """Run episode with plasticity; fitness = late-life return (after plastic_steps)."""
    agent = instantiate_baldwin(genome, rng)
    obs = env.reset(rng) if not hasattr(env, 't') or env.t == 0 else env.observe(rng)
    # fresh env
    env = E.SwitchCueNEnv(N=genome["N"], T=env.T if hasattr(env, 'T') else 200, cue_every=False)
    obs = env.reset(rng)
    state = {}
    total_early = 0.0
    total_late = 0.0
    n_early = n_late = 0
    done = False
    while not done:
        a, state, _ = step_baldwin(agent, obs, state, greedy=greedy, rng=rng,
                                   plastic=True, reward=None)
        obs, r, done, info = env.step(a, rng)
        # apply plasticity with received reward (eligibility: last pre/post already in step)
        # re-apply three-factor using stored - simplify: call update with reward on same step features
        # Actually step_baldwin needs reward at update time; do second pass style:
        # We already stepped; apply plasticity retroactively via a dedicated update
        _baldwin_apply_reward(agent, state, r)
        if env.t <= plastic_steps:
            total_early += r; n_early += 1
        else:
            total_late += r; n_late += 1
    late = total_late / max(1, n_late) if n_late else total_early / max(1, n_early)
    return late, agent


def _baldwin_apply_reward(agent, state, reward):
    """Lightweight: boost/decay W_sa toward last action using modulator only on sa scale."""
    W = agent["W"]
    baseline = state.get("baseline", 0.0)
    ema = W["baseline_ema"]
    mod = float(reward) - baseline
    state["baseline"] = (1.0 - ema) * baseline + ema * float(reward)
    s = state.get("s", np.zeros(SDIM))
    # Hebbian-like on readout magnitude
    W["W_sa"] = W["W_sa"] + W["eta_sa"] * mod * 0.1 * np.outer(np.tanh(W["W_sa"] @ s), s)
    W["W_sa"] = np.clip(W["W_sa"], -5.0, 5.0)


def fitness_baldwin(genome, rng, N, T, K_eval=3, plastic_steps=150):
    scores = []
    for _ in range(K_eval):
        env = E.SwitchCueNEnv(N=N, T=T, cue_every=False)
        late, ag = rollout_baldwin_lifetime(genome, env, rng, plastic_steps=plastic_steps, greedy=False)
        scores.append(late)
    return float(np.mean(scores)), ag


def evolve_baldwin(rng, N=4, gens=200, pop_n=64, T=200, plastic_steps=150, K_eval=3,
                   mut=0.12, elite=0.25, log_every=20):
    pop = [make_baldwin_genome(rng, N) for _ in range(pop_n)]
    best_hist, mean_hist = [], []
    best_g, best_ag, best_fit = None, None, -1.0
    for gen in range(gens):
        fits = []
        agents = []
        for g in pop:
            f, ag = fitness_baldwin(g, rng, N, T, K_eval=K_eval, plastic_steps=plastic_steps)
            fits.append(f); agents.append(ag)
        fits = np.asarray(fits)
        order = np.argsort(-fits)
        best_hist.append(float(fits[order[0]]))
        mean_hist.append(float(fits.mean()))
        if fits[order[0]] > best_fit:
            best_fit = float(fits[order[0]])
            best_g = copy.deepcopy(pop[order[0]])
            best_ag = agents[order[0]]
        if log_every and gen % log_every == 0:
            print(f"  [Bald] gen={gen:3d} best={best_hist[-1]:.3f} mean={mean_hist[-1]:.3f}", flush=True)
        n_elite = max(1, int(pop_n * elite))
        new_pop = [copy.deepcopy(pop[i]) for i in order[:n_elite]]
        while len(new_pop) < pop_n:
            parent = pop[int(order[rng.integers(n_elite)])]
            child = copy.deepcopy(parent)
            for k, v in child["G"].items():
                if isinstance(v, np.ndarray):
                    child["G"][k] = v + mut * rng.standard_normal(v.shape)
            new_pop.append(child)
        pop = new_pop
    # final phenotype for eval: re-run lifetime once from best genome
    if best_g is not None:
        _, best_ag = fitness_baldwin(best_g, rng, N, T, K_eval=1, plastic_steps=plastic_steps)
    return best_ag, best_g, {"best_hist": best_hist, "mean_hist": mean_hist, "best_fit_train": best_fit}


# ---------------------------------------------------------------------------
# OpenAI-ES on learn_gate flat vector
# ---------------------------------------------------------------------------
def _learn_gate_keys(N):
    OBS = E.obs_dim(N)
    # shapes matching E.make_learnable_gate
    return [
        ("w_g", (OBS + SDIM,)),
        ("b_g", (1,)),
        ("W_write", (SDIM, OBS)),
        ("b_write", (SDIM,)),
        ("W_ss", (SDIM, SDIM)),
        ("b_s", (SDIM,)),
        ("W_sa", (N, SDIM)),
        ("W_oa", (N, OBS)),
        ("b_a", (N,)),
    ]


def agent_to_vec(ag):
    parts = []
    for k, _ in _learn_gate_keys(ag["N"]):
        parts.append(ag["W"][k].ravel())
    return np.concatenate(parts)


def vec_to_agent(vec, N, template=None):
    ag = E.make_learnable_gate(np.random.default_rng(0), N, "standard") if template is None else L.clone_agent(template)
    ag["kind"] = "learn_gate"
    offset = 0
    for k, shape in _learn_gate_keys(N):
        n = int(np.prod(shape))
        ag["W"][k] = vec[offset:offset + n].reshape(shape).astype(float)
        offset += n
    return ag


def openai_es_learn_gate(rng, N=4, T=200, n_workers=64, generations=600, sigma=0.08, lr=0.05,
                         K_eval=3, log_every=20, total_evals_cap=38400):
    """Antithetic OpenAI-ES. Each generation uses n_workers perturbations (= n_workers evals)."""
    center_ag = E.make_learnable_gate(rng, N, "standard")
    theta = agent_to_vec(center_ag)
    best_fit = -1.0
    best_ag = L.clone_agent(center_ag)
    hist = []
    evals = 0
    for gen in range(generations):
        if evals >= total_evals_cap:
            break
        noise = rng.standard_normal((n_workers, theta.size))
        fits = np.zeros(n_workers)
        for i in range(n_workers):
            if evals >= total_evals_cap:
                fits[i:] = fits[:max(1, i)].mean() if i else 0.0
                break
            ag = vec_to_agent(theta + sigma * noise[i], N, template=center_ag)
            fits[i] = L.fitness_task_only(ag, rng, N, T, K_eval=K_eval)
            evals += 1
        # antithetic half reuse: also eval negative noise if budget allows
        # standardize
        f_std = (fits - fits.mean()) / (fits.std() + 1e-8)
        grad = (noise.T @ f_std) / max(1, n_workers)
        theta = theta + lr * sigma * grad  # OpenAI-ES style
        # track best among this gen
        i_best = int(np.argmax(fits))
        if fits[i_best] > best_fit:
            best_fit = float(fits[i_best])
            best_ag = vec_to_agent(theta + sigma * noise[i_best], N, template=center_ag)
        hist.append({"gen": gen, "best": float(fits.max()), "mean": float(fits.mean()), "evals": evals})
        if log_every and gen % log_every == 0:
            print(f"  [ES] gen={gen:3d} best={fits.max():.3f} mean={fits.mean():.3f} evals={evals}", flush=True)
    # final center
    center_final = vec_to_agent(theta, N, template=center_ag)
    cfit = L.fitness_task_only(center_final, rng, N, T, K_eval=K_eval)
    if cfit > best_fit:
        best_ag, best_fit = center_final, cfit
    return best_ag, {"best_fit_train": best_fit, "hist_tail": hist[-5:], "evals": evals, "hist_len": len(hist)}


# ---------------------------------------------------------------------------
# Patch step_agent for novelty + baldwin eval phenotypes
# ---------------------------------------------------------------------------
_orig_step = L.step_agent
_orig_has = L.has_latent


def step_agent(agent, obs, state, greedy=True, rng=None):
    kind = agent["kind"]
    if kind == "novelty_gate":
        return step_novelty(agent, obs, state, greedy=greedy, rng=rng)
    if kind == "baldwin_agent":
        return step_baldwin(agent, obs, state, greedy=greedy, rng=rng, plastic=False)
    return _orig_step(agent, obs, state, greedy=greedy, rng=rng)


def has_latent(agent):
    return agent["kind"] in ("rnn", "hand_gate", "learn_gate", "binary_gate", "gru",
                             "novelty_gate", "baldwin_agent")


L.step_agent = step_agent
L.has_latent = has_latent
E.step_agent = step_agent
E.has_latent = has_latent


def evolve_novelty(rng, N=4, gens=200, pop_n=64, T=200, K_eval=3, mut=0.12, elite=0.25, log_every=20):
    pop = [make_novelty_gate(rng, N) for _ in range(pop_n)]
    best_hist, mean_hist = [], []
    best_ag, best_fit = None, -1.0
    for gen in range(gens):
        fits = np.array([L.fitness_task_only(ag, rng, N, T, K_eval=K_eval) for ag in pop])
        order = np.argsort(-fits)
        best_hist.append(float(fits[order[0]]))
        mean_hist.append(float(fits.mean()))
        if fits[order[0]] > best_fit:
            best_fit = float(fits[order[0]])
            best_ag = L.clone_agent(pop[order[0]])
        if log_every and gen % log_every == 0:
            print(f"  [Nov] gen={gen:3d} best={best_hist[-1]:.3f} mean={mean_hist[-1]:.3f}", flush=True)
        n_elite = max(1, int(pop_n * elite))
        new_pop = [L.clone_agent(pop[i]) for i in order[:n_elite]]
        while len(new_pop) < pop_n:
            parent = pop[int(order[rng.integers(n_elite)])]
            child = L.clone_agent(parent)
            L.mutate(child, rng, strength=mut)
            L.update_resistance(child)
            new_pop.append(child)
        pop = new_pop
    return best_ag, {"best_hist": best_hist, "mean_hist": mean_hist, "best_fit_train": best_fit}
