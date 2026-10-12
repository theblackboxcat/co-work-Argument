# -*- coding: utf-8 -*-
"""S1 Learnable-gate switch-cue env (N-goal). coh_w≡0 always. No clock channel."""
from __future__ import annotations
import hashlib, json, inspect
from pathlib import Path
import numpy as np

# dims depend on N_goals
HID = 16
SDIM = 8
NOISE = 3
K_LO, K_HI = 30, 70
T_DEFAULT = 200


def obs_dim(N: int) -> int:
    return 1 + N + NOISE  # cue_on + onehot(N) + noise


def softmax(x):
    x = np.asarray(x, float)
    x = x - x.max()
    e = np.exp(np.clip(x, -50, 50))
    return e / (e.sum() + 1e-12)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40, 40)))


def _r(rng, shape, scale=0.4):
    return rng.standard_normal(shape).astype(np.float64) * scale


# ---------------------------------------------------------------------------
# Environment: random K per segment ∈ [30,70], random phase, cue only at switch
# ---------------------------------------------------------------------------
class SwitchCueNEnv:
    def __init__(self, N=4, T=200, cue_every=False, noise_std=0.05,
                 k_lo=K_LO, k_hi=K_HI, fixed_K=None):
        self.N = int(N)
        self.T = int(T)
        self.cue_every = bool(cue_every)
        self.noise_std = float(noise_std)
        self.k_lo = int(k_lo)
        self.k_hi = int(k_hi)
        self.fixed_K = fixed_K
        self.OBS = obs_dim(self.N)

    def reset(self, rng, removal_mode=False, removal_factor=2):
        """removal_mode: one initial cue, then no-cue for 2K steps (C6)."""
        self.t = 0
        self.goal = int(rng.integers(self.N))
        self.removal_mode = bool(removal_mode)
        self._switches = set()
        if self.removal_mode:
            # single cue at t=0; segment length 2K with K~U[k_lo,k_hi]
            K = int(self.fixed_K) if self.fixed_K else int(rng.integers(self.k_lo, self.k_hi + 1))
            self.T = int(removal_factor * K)
            self._switches = {0}
            self._seg_Ks = [K]
        else:
            # build segments with random K until cover T
            t = 0
            self._switches = {0}
            self._seg_Ks = []
            # initial cue at 0; next switch after first K (with random phase offset)
            phase = int(rng.integers(0, 10))  # small jitter; first block length
            while t < self.T:
                K = int(self.fixed_K) if self.fixed_K else int(rng.integers(self.k_lo, self.k_hi + 1))
                if t == 0:
                    nxt = min(self.T, K)  # first switch boundary
                else:
                    nxt = min(self.T, t + K)
                self._seg_Ks.append(K)
                t = nxt
                if t < self.T:
                    self._switches.add(t)
        return self.observe(rng)

    def _at_switch(self, t=None):
        if t is None:
            t = self.t
        return t in self._switches

    def observe(self, rng):
        o = np.zeros(self.OBS, dtype=float)
        show = self.cue_every or self._at_switch()
        if show:
            o[0] = 1.0
            o[1 + self.goal] = 1.0  # one-hot in slots 1..N
        o[1 + self.N:] = rng.standard_normal(NOISE) * self.noise_std
        return o

    def step(self, action, rng):
        reward = 1.0 if int(action) == self.goal else 0.0
        self.t += 1
        done = self.t >= self.T
        if not done and self._at_switch(self.t):
            # new goal ≠ current
            choices = [g for g in range(self.N) if g != self.goal]
            self.goal = int(choices[int(rng.integers(len(choices)))])
        obs = self.observe(rng) if not done else np.zeros(self.OBS)
        info = {
            "goal": self.goal,
            "cue_on": bool(self.cue_every or (self._at_switch(self.t) and not done)),
        }
        return obs, reward, done, info



def _env(N, T, cue_every=False, k_lo=None, k_hi=None):
    kw = {}
    if k_lo is not None:
        kw["k_lo"] = int(k_lo)
    if k_hi is not None:
        kw["k_hi"] = int(k_hi)
    return SwitchCueNEnv(N=N, T=T, cue_every=cue_every, **kw)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def make_memoryless(rng, N):
    OBS = obs_dim(N)
    return {
        "kind": "memoryless",
        "N": N,
        "W": {"W_xa": _r(rng, (N, OBS)), "b_a": _r(rng, N, 0.1)},
        "R": {},
    }


def make_rnn(rng, N):
    OBS = obs_dim(N)
    W = {
        "W_xh": _r(rng, (HID, OBS)),
        "W_hh": _r(rng, (HID, HID)),
        "b_h": _r(rng, HID, 0.1),
        "W_ha": _r(rng, (N, HID)),
        "b_a": _r(rng, N, 0.1),
    }
    W["W_hh"] = 0.7 * np.eye(HID) + 0.3 * W["W_hh"]
    return {"kind": "rnn", "N": N, "W": W,
            "R": {k: np.full_like(v, 0.5) for k, v in W.items()}}


def make_handwritten_gate(rng, N):
    """C: Branch-B-style slot; gate = write_gain * cue_on; structured enc."""
    OBS = obs_dim(N)
    # enc: one-hot cue (obs[1:1+N]) → SDIM; seed first N dims to track goals
    W_enc = _r(rng, (SDIM, N), 0.15)
    for i in range(min(N, SDIM)):
        W_enc[i, i] = 1.2
    W = {
        "W_ss": 0.92 * np.eye(SDIM) + 0.08 * _r(rng, (SDIM, SDIM), 0.2),
        "b_s": _r(rng, SDIM, 0.02),
        "W_enc": W_enc,            # (SDIM, N) * cue onehot
        "b_enc": _r(rng, SDIM, 0.02),
        "write_gain": np.array([0.95]),
        "W_sa": _r(rng, (N, SDIM), 0.3),
        "W_ca": _r(rng, (N, 1 + N), 0.15),  # cue_on+onehot bypass
        "b_a": _r(rng, N, 0.05),
    }
    # seed action readout: prefer action i when s[i] high
    for i in range(min(N, SDIM)):
        W["W_sa"][i, i] = abs(W["W_sa"][i, i]) + 0.9
        for j in range(N):
            if j != i:
                W["W_sa"][j, i] = -abs(W["W_sa"][j, i]) - 0.3
    return {"kind": "hand_gate", "N": N, "W": W,
            "R": {k: np.full_like(v, 0.5) for k, v in W.items()}}


def make_learnable_gate(rng, N, write_init="standard"):
    """D/E: g=σ(w·[obs,s]+b); s←g·write+(1−g)·s; w,b in genome.
    write_init: 'standard' (D) or 'random' (E, larger-scale unstructured).
    """
    OBS = obs_dim(N)
    in_g = OBS + SDIM
    scale_w = 1.0 if write_init == "random" else 0.35
    W = {
        # gate
        "w_g": _r(rng, in_g, 0.3),
        "b_g": _r(rng, 1, 0.1),
        # write from obs
        "W_write": _r(rng, (SDIM, OBS), scale_w),
        "b_write": _r(rng, SDIM, 0.1 if write_init == "random" else 0.05),
        # slow hold (mild)
        "W_ss": 0.85 * np.eye(SDIM) + 0.15 * _r(rng, (SDIM, SDIM), 0.25),
        "b_s": _r(rng, SDIM, 0.05),
        # action from s (+ small obs bypass)
        "W_sa": _r(rng, (N, SDIM), 0.35),
        "W_oa": _r(rng, (N, OBS), 0.1),
        "b_a": _r(rng, N, 0.05),
    }
    if write_init == "random":
        # scramble any accidental structure
        W["W_write"] = rng.standard_normal((SDIM, OBS)) * scale_w
        W["b_write"] = rng.standard_normal(SDIM) * 0.2
    return {"kind": "learn_gate", "N": N, "write_init": write_init, "W": W,
            "R": {k: np.full_like(v, 0.5) for k, v in W.items()}}


MAKERS = {
    "memoryless": make_memoryless,
    "rnn": make_rnn,
    "hand_gate": make_handwritten_gate,
    "learn_gate": lambda rng, N: make_learnable_gate(rng, N, "standard"),
    "learn_gate_randwrite": lambda rng, N: make_learnable_gate(rng, N, "random"),
}

ARM_KIND = {
    "A": "memoryless",
    "B": "rnn",
    "C": "hand_gate",
    "D": "learn_gate",
    "E": "learn_gate_randwrite",
}


def clone_agent(ag):
    out = {"kind": ag["kind"], "N": ag["N"],
           "W": {k: v.copy() for k, v in ag["W"].items()},
           "R": {k: v.copy() for k, v in ag.get("R", {}).items()}}
    if "write_init" in ag:
        out["write_init"] = ag["write_init"]
    return out


def mutate(agent, rng, strength=0.12):
    W, R = agent["W"], agent.get("R", {})
    for k in W:
        eff = strength * (0.25 + 0.75 * (1.0 - float(np.mean(R[k])))) if (R and k in R) else strength
        W[k] = W[k] + eff * rng.standard_normal(W[k].shape)


def update_resistance(agent):
    W, R = agent["W"], agent.get("R", {})
    if not R:
        return
    for k in W:
        if k not in R:
            continue
        usage = np.abs(W[k])
        target = np.clip(usage / (usage + 0.5), 0.0, 0.9)
        R[k] = R[k] + 0.05 * (target - R[k])


# ---------------------------------------------------------------------------
# Forward
# ---------------------------------------------------------------------------
def step_agent(agent, obs, state, greedy=True, rng=None):
    kind = agent["kind"]
    W = agent["W"]
    N = agent["N"]
    extras = {}
    if kind == "memoryless":
        logits = W["W_xa"] @ obs + W["b_a"]
        state = {}
        s = None
    elif kind == "rnn":
        h = state.get("h", np.zeros(HID))
        h = np.tanh(W["W_xh"] @ obs + W["W_hh"] @ h + W["b_h"])
        logits = W["W_ha"] @ h + W["b_a"]
        state = {"h": h}
        s = h  # treat h as latent for probes
        extras["s"] = h.copy()
    elif kind == "hand_gate":
        s = state.get("s", np.zeros(SDIM))
        cue_on = float(obs[0])
        cue_oh = obs[1:1 + N]
        s_hold = np.tanh(W["W_ss"] @ s + W["b_s"])
        s_write = np.tanh(W["W_enc"] @ cue_oh + W["b_enc"])
        g = float(np.clip(W["write_gain"][0], 0.0, 1.0)) * cue_on
        s = (1.0 - g) * s_hold + g * s_write
        logits = W["W_sa"] @ s + W["W_ca"] @ obs[:1 + N] + W["b_a"]
        state = {"s": s}
        extras["s"] = s.copy()
        extras["gate"] = g
    elif kind in ("learn_gate",):
        s = state.get("s", np.zeros(SDIM))
        # optional mild hold before gate mix
        s_hold = np.tanh(W["W_ss"] @ s + W["b_s"])
        write = np.tanh(W["W_write"] @ obs + W["b_write"])
        feat = np.concatenate([obs, s_hold])
        g = float(sigmoid(float(W["w_g"] @ feat + W["b_g"][0])))
        s = g * write + (1.0 - g) * s_hold
        logits = W["W_sa"] @ s + W["W_oa"] @ obs + W["b_a"]
        state = {"s": s}
        extras["s"] = s.copy()
        extras["gate"] = g
    else:
        raise ValueError(kind)

    if greedy:
        a = int(np.argmax(logits))
    else:
        p = softmax(logits)
        a = int(rng.choice(N, p=p))
    extras["logits"] = logits
    return a, state, extras


def has_latent(agent):
    return agent["kind"] in ("rnn", "hand_gate", "learn_gate", "binary_gate", "gru")


def latent_dim(agent):
    if agent["kind"] == "rnn":
        return HID
    if agent["kind"] == "gru":
        return int(agent["W"]["hid"])
    return SDIM


def rollout(agent, env, rng, greedy=True, record=False, force_s=None, lesion_s=False):
    obs = env.reset(rng) if not getattr(env, "_already_reset", False) else env.observe(rng)
    # allow external reset
    if not getattr(env, "_already_reset", False):
        pass
    state = {}
    total_r = 0.0
    n = 0
    traj = [] if record else None
    while True:
        goal_before = env.goal
        cue_vis = bool(env.cue_every or env._at_switch(env.t))
        if force_s is not None and has_latent(agent):
            key = "h" if agent["kind"] in ("rnn", "gru") else "s"
            s0 = state.get(key, np.zeros(latent_dim(agent)))
            state = dict(state)
            state[key] = force_s(n, s0, goal_before)
        if lesion_s and has_latent(agent):
            key = "h" if agent["kind"] in ("rnn", "gru") else "s"
            state = dict(state)
            state[key] = np.clip(rng.standard_normal(latent_dim(agent)), -1, 1)
        a, state, extras = step_agent(agent, obs, state, greedy=greedy, rng=rng)
        obs, r, done, info = env.step(a, rng)
        total_r += r
        n += 1
        if record:
            traj.append({
                "t": n - 1,
                "a": a,
                "r": r,
                "goal": goal_before,
                "s": None if extras.get("s") is None else extras["s"].copy(),
                "cue_visible": cue_vis,
                "obs": None,  # filled optionally
            })
        if done:
            break
    return total_r / max(1, n), traj


def rollout_from_reset(agent, env, rng, greedy=True, record=False, force_s=None, lesion_s=False,
                       store_obs=False):
    obs = env.reset(rng)
    state = {}
    total_r = 0.0
    n = 0
    traj = [] if record else None
    while True:
        goal_before = env.goal
        cue_vis = bool(env.cue_every or env._at_switch(env.t))
        obs_pre = obs.copy()
        if force_s is not None and has_latent(agent):
            key = "h" if agent["kind"] in ("rnn", "gru") else "s"
            s0 = state.get(key, np.zeros(latent_dim(agent)))
            state = dict(state)
            state[key] = force_s(n, s0, goal_before)
        if lesion_s and has_latent(agent):
            key = "h" if agent["kind"] in ("rnn", "gru") else "s"
            state = dict(state)
            state[key] = np.clip(rng.standard_normal(latent_dim(agent)), -1, 1)
        a, state, extras = step_agent(agent, obs, state, greedy=greedy, rng=rng)
        obs, r, done, info = env.step(a, rng)
        total_r += r
        n += 1
        if record:
            row = {
                "t": n - 1, "a": a, "r": r, "goal": goal_before,
                "s": None if extras.get("s") is None else extras["s"].copy(),
                "cue_visible": cue_vis,
            }
            if store_obs:
                row["obs"] = obs_pre
            traj.append(row)
        if done:
            break
    return total_r / max(1, n), traj


def evaluate(agent, N, T, n_eps, seed, cue_every=False, greedy=True, lesion_s=False,
             removal_mode=False, removal_factor=2, k_lo=None, k_hi=None):
    rng = np.random.default_rng(seed)
    rets = []
    for _ in range(n_eps):
        env = _env(N, T, cue_every=cue_every, k_lo=k_lo, k_hi=k_hi)
        ret, _ = rollout_from_reset(
            agent, env, np.random.default_rng(int(rng.integers(1 << 31))),
            greedy=greedy, lesion_s=lesion_s)
        if removal_mode:
            env = _env(N, T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
            ret, _ = rollout_from_reset(
                agent, env, np.random.default_rng(int(rng.integers(1 << 31))),
                greedy=greedy, lesion_s=lesion_s)
            # overwrite with proper removal env
        rets.append(ret)
    if removal_mode:
        rets = []
        rng = np.random.default_rng(seed)
        for _ in range(n_eps):
            env = _env(N, T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
            # custom: reset in removal mode
            r2 = np.random.default_rng(int(rng.integers(1 << 31)))
            obs = env.reset(r2, removal_mode=True, removal_factor=removal_factor)
            state = {}
            total_r = 0.0
            n = 0
            while True:
                if lesion_s and has_latent(agent):
                    key = "h" if agent["kind"] in ("rnn", "gru") else "s"
                    state = dict(state)
                    state[key] = np.clip(r2.standard_normal(latent_dim(agent)), -1, 1)
                a, state, _ = step_agent(agent, obs, state, greedy=greedy, rng=r2)
                obs, r, done, info = env.step(a, r2)
                total_r += r
                n += 1
                if done:
                    break
            rets.append(total_r / max(1, n))
    return float(np.mean(rets)), float(np.std(rets)), rets


# Fitness source (C5 audit) — MUST contain no stability terms
def fitness_task_only(agent, rng, N, T, K_eval=4, k_lo=None, k_hi=None):
    """Mean return only. No ||Δs||, s variance, or s stability term."""
    scores = []
    for _ in range(K_eval):
        env = _env(N, T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
        ret, _ = rollout_from_reset(agent, env, rng, greedy=True)
        scores.append(ret)
    return float(np.mean(scores))


FITNESS_SOURCE = inspect.getsource(fitness_task_only)


def fitness_source_hash():
    return hashlib.sha256(FITNESS_SOURCE.encode()).hexdigest()


def evolve(kind, rng, N=4, gens=100, pop_n=36, T=200, mut=0.12, elite=0.25,
           K_eval=3, log_every=20, probe_cb=None):
    maker = MAKERS[kind]
    pop = [maker(rng, N) for _ in range(pop_n)]
    best_hist, mean_hist = [], []
    probes = []
    best_ag = None
    best_fit = -1.0

    for gen in range(gens):
        fits = np.array([fitness_task_only(ag, rng, N, T, K_eval=K_eval) for ag in pop])
        order = np.argsort(-fits)
        mean_hist.append(float(fits.mean()))
        best_hist.append(float(fits[order[0]]))
        if fits[order[0]] > best_fit:
            best_fit = float(fits[order[0]])
            best_ag = clone_agent(pop[order[0]])
        if log_every and gen % log_every == 0:
            print(f"  [{kind}] gen={gen:3d} best={best_hist[-1]:.3f} mean={mean_hist[-1]:.3f}",
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


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------
def collect_s_goal(agent, n_eps, N, T, seed, non_cue_only=True, store_obs=False, k_lo=None, k_hi=None):
    if not has_latent(agent):
        return np.zeros((0, latent_dim(agent) if has_latent(agent) else 1)), np.zeros(0, dtype=int), []
    rng = np.random.default_rng(seed)
    S, G, OBS = [], [], []
    for _ in range(n_eps):
        env = _env(N, T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
        ret, traj = rollout_from_reset(
            agent, env, np.random.default_rng(int(rng.integers(1 << 31))),
            greedy=True, record=True, store_obs=store_obs)
        for row in traj:
            if row["s"] is None:
                continue
            if non_cue_only and row["cue_visible"]:
                continue
            S.append(row["s"])
            G.append(row["goal"])
            if store_obs:
                OBS.append(row["obs"])
    if not S:
        d = latent_dim(agent)
        return np.zeros((0, d)), np.zeros(0, dtype=int), []
    return np.stack(S), np.asarray(G, dtype=int), (np.stack(OBS) if OBS else [])


def multinomial_decode_acc(S_train, G_train, S_test, G_test, N):
    """Ridge one-vs-rest linear probe. Returns test accuracy."""
    if len(S_train) < max(20, 2 * N) or len(S_test) < max(10, N):
        return 1.0 / N
    X = np.concatenate([S_train, np.ones((len(S_train), 1))], axis=1)
    Xte = np.concatenate([S_test, np.ones((len(S_test), 1))], axis=1)
    lam = 1e-2
    scores = []
    A = X.T @ X + lam * np.eye(X.shape[1])
    for g in range(N):
        y = (G_train == g).astype(float) * 2 - 1
        try:
            w = np.linalg.solve(A, X.T @ y)
        except np.linalg.LinAlgError:
            w = np.linalg.lstsq(A, X.T @ y, rcond=None)[0]
        scores.append(Xte @ w)
    pred = np.argmax(np.stack(scores, axis=1), axis=1)
    return float(np.mean(pred == G_test))


def obs_window_decode_acc(agent, N, T, seed, n_eps=12, window=5, k_lo=None, k_hi=None):
    """C2-leak: decode goal from obs window only (no s)."""
    rng = np.random.default_rng(seed)
    X_tr, Y_tr, X_te, Y_te = [], [], [], []
    for ep in range(n_eps):
        env = _env(N, T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        obs = env.reset(r2)
        state = {}
        buf = []
        rows = []
        for t in range(T):
            cue_vis = bool(env.cue_every or env._at_switch(env.t))
            goal = env.goal
            buf.append(obs.copy())
            if len(buf) > window:
                buf.pop(0)
            if (not cue_vis) and len(buf) == window:
                feat = np.concatenate(buf)
                rows.append((feat, goal))
            a, state, _ = step_agent(agent, obs, state, greedy=True, rng=r2)
            obs, r, done, info = env.step(a, r2)
            if done:
                break
        # split eps half train/test by ep index
        target = X_tr if ep < n_eps // 2 else X_te
        ty = Y_tr if ep < n_eps // 2 else Y_te
        for f, g in rows:
            target.append(f)
            ty.append(g)
    if len(X_tr) < 20 or len(X_te) < 10:
        return 1.0 / N
    S_tr, G_tr = np.stack(X_tr), np.asarray(Y_tr, int)
    S_te, G_te = np.stack(X_te), np.asarray(Y_te, int)
    return multinomial_decode_acc(S_tr, G_tr, S_te, G_te, N)


def goal_centroids(agent, N, T, seed, n_eps=16, k_lo=None, k_hi=None):
    S, G, _ = collect_s_goal(agent, n_eps=n_eps, N=N, T=T, seed=seed, non_cue_only=True, k_lo=k_lo, k_hi=k_hi)
    cents = {}
    d = latent_dim(agent)
    for g in range(N):
        mask = G == g
        cents[g] = S[mask].mean(axis=0) if mask.sum() else np.zeros(d)
    return cents, S, G


def criterion3_flip_rate(agent, cents, N, T, n_trials, seed, within_steps=3, k_lo=None, k_hi=None):
    """Freeze W; write other-goal centroid into s; behavior flips within `within_steps`."""
    if not has_latent(agent):
        return 0.0, 0
    rng = np.random.default_rng(seed)
    flips = 0
    usable = 0
    key = "h" if agent["kind"] in ("rnn", "gru") else "s"
    for _ in range(n_trials):
        env = _env(N, T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
        obs = env.reset(rng)
        state = {}
        for t in range(T):
            goal = env.goal
            at_cue = env.cue_every or env._at_switch(t)
            if t >= 10 and (not at_cue) and t < T - within_steps - 1:
                # choose a different goal centroid
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
                    # advance env without consuming real trajectory for probe steps on forced state
                    # use same obs (frozen non-cue) — behavior readout only
                    pass
                usable += 1
                if ok:
                    flips += 1
                break
            a, state, _ = step_agent(agent, obs, state, greedy=True)
            obs, r, done, info = env.step(a, rng)
            if done:
                break
    return float(flips / max(1, usable)), usable


def pathway_ablation_return(agent, N, T, n_eps, seed):
    """Ablate cue→write pathway (zero cue channels in obs) — not content lesion."""
    rng = np.random.default_rng(seed)
    rets = []
    for _ in range(n_eps):
        env = _env(N, T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        obs = env.reset(r2)
        state = {}
        total_r = 0.0
        n = 0
        while True:
            obs_ab = obs.copy()
            obs_ab[:] = obs_ab  # keep noise
            obs_ab[0:1 + N] = 0.0  # kill cue_on + onehot
            a, state, _ = step_agent(agent, obs_ab, state, greedy=True, rng=r2)
            obs, r, done, info = env.step(a, r2)
            total_r += r
            n += 1
            if done:
                break
        rets.append(total_r / max(1, n))
    return float(np.mean(rets)), rets


def config_hash(cfg: dict) -> str:
    raw = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
