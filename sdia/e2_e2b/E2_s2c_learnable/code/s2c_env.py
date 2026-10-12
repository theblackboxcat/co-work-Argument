# -*- coding: utf-8 -*-
"""S2c 必要性加压网格：错误资源有毒 + 冻结 Phase1 导航器；只进化目标模块。
Stance A：毒扣分为世界收益结构，非稳定性付款。"""
from __future__ import annotations
import hashlib, inspect
import numpy as np

H_DEFAULT, W_DEFAULT = 8, 8
WORLD_INP = 28
CUE_DIM = 3
OBS = WORLD_INP + CUE_DIM
HID = 16
SDIM = 4
ACT = 9
N_GOALS = 2
DIRS = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)]
K_LO, K_HI = 30, 70
T_DEFAULT = 120
TOX_DEFAULT = 1.5


def bin_dir(dx, dy):
    if dx == 0 and dy == 0:
        return -1
    v = np.array([dx, dy], float)
    v /= (np.linalg.norm(v) + 1e-12)
    best, bestc = 0, -2.0
    for i, (ax, ay) in enumerate(DIRS):
        c = v[0] * ax + v[1] * ay
        if c > bestc:
            bestc, best = c, i
    return best


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
# World
# ---------------------------------------------------------------------------
class ToxicValuableGrid:
    """food+gem grid; wrong-resource intake is toxic (Stance A world payoff)."""

    def __init__(self, H=H_DEFAULT, W=W_DEFAULT, T=T_DEFAULT, cue_every=False,
                 k_lo=K_LO, k_hi=K_HI, fixed_K=None, tox=TOX_DEFAULT,
                 food_rate=0.55, gem_rate=0.50, food_cap=14, gem_cap=12,
                 decay=0.006, pred_move_prob=0.12, pred_sense=3,
                 n_food_init=7, n_gem_init=6, n_obstacles_frac=0.04):
        self.H, self.W = int(H), int(W)
        self.T = int(T)
        self.cue_every = bool(cue_every)
        self.k_lo, self.k_hi = int(k_lo), int(k_hi)
        self.fixed_K = fixed_K
        self.tox = float(tox)
        self.food_rate, self.gem_rate = food_rate, gem_rate
        self.food_cap, self.gem_cap = food_cap, gem_cap
        self.decay = decay
        self.pred_move_prob = pred_move_prob
        self.pred_sense = pred_sense
        self.n_food_init = n_food_init
        self.n_gem_init = n_gem_init
        self.n_obstacles_frac = n_obstacles_frac
        self.obstacles = set()

    def _init_obstacles(self, rng):
        self.obstacles = set()
        n_obs = int(self.H * self.W * self.n_obstacles_frac)
        while len(self.obstacles) < n_obs:
            self.obstacles.add((int(rng.integers(self.H)), int(rng.integers(self.W))))

    def reset(self, rng, removal_mode=False, removal_factor=2):
        self._init_obstacles(rng)
        while True:
            x, y = int(rng.integers(self.H)), int(rng.integers(self.W))
            if (x, y) not in self.obstacles:
                self.ax, self.ay = x, y
                break
        self.energy = 1.0
        self.foods, self.gems = [], []
        for _ in range(self.n_food_init):
            self._spawn(self.foods, rng, self.food_cap)
        for _ in range(self.n_gem_init):
            self._spawn(self.gems, rng, self.gem_cap)
        self.preds = [(int(rng.integers(self.H)), int(rng.integers(self.W)))]
        self.ate_food = False
        self.got_gem = False
        self.t = 0
        self.valuable = int(rng.integers(2))
        self.removal_mode = bool(removal_mode)
        self._switches = set()
        self._seg_Ks = []
        if self.removal_mode:
            K = int(self.fixed_K) if self.fixed_K else int(rng.integers(self.k_lo, self.k_hi + 1))
            self.T = int(removal_factor * K)
            self._switches = {0}
            self._seg_Ks = [K]
        else:
            t = 0
            self._switches = {0}
            self._seg_Ks = []
            while t < self.T:
                K = int(self.fixed_K) if self.fixed_K else int(rng.integers(self.k_lo, self.k_hi + 1))
                self._seg_Ks.append(K)
                nxt = min(self.T, t + K) if t > 0 else min(self.T, K)
                t = nxt
                if t < self.T:
                    self._switches.add(t)
        self.n_valuable = 0
        self.n_other = 0
        self.score = 0.0
        return self.observe(rng)

    def _at_switch(self, t=None):
        if t is None:
            t = self.t
        return t in self._switches

    def _spawn(self, lst, rng, cap):
        if len(lst) >= cap:
            return
        for _ in range(30):
            x, y = int(rng.integers(self.H)), int(rng.integers(self.W))
            if ((x, y) not in self.obstacles and (x, y) != (self.ax, self.ay)
                    and (x, y) not in lst and (x, y) not in self.foods and (x, y) not in self.gems):
                lst.append((x, y))
                return

    def _nearest(self, items, x, y):
        best, bd = None, 1e9
        for (ix, iy) in items:
            d = abs(ix - x) + abs(iy - y)
            if d < bd:
                bd, best = d, (ix, iy)
        return best, bd

    def perceive_world(self):
        p = np.zeros(WORLD_INP, dtype=float)
        nf, df = self._nearest(self.foods, self.ax, self.ay)
        ng, dg = self._nearest(self.gems, self.ax, self.ay)
        np_, dp = self._nearest(self.preds, self.ax, self.ay)
        if nf:
            b = bin_dir(nf[0] - self.ax, nf[1] - self.ay)
            if b >= 0:
                p[b] = 1.0
            p[24] = 1.0 / (1.0 + df)
        if ng:
            b = bin_dir(ng[0] - self.ax, ng[1] - self.ay)
            if b >= 0:
                p[8 + b] = 1.0
            p[25] = 1.0 / (1.0 + dg)
        if np_:
            b = bin_dir(np_[0] - self.ax, np_[1] - self.ay)
            if b >= 0:
                p[16 + b] = 1.0
            p[26] = 1.0 / (1.0 + dp)
        p[27] = self.energy
        return p

    def cue_vec(self):
        c = np.zeros(CUE_DIM, dtype=float)
        show = self.cue_every or self._at_switch()
        if show:
            c[0] = 1.0
            c[1 + self.valuable] = 1.0
        return c

    def observe(self, rng):
        return np.concatenate([self.perceive_world(), self.cue_vec()])

    def step_world(self, rng):
        if rng.random() < self.food_rate:
            self._spawn(self.foods, rng, self.food_cap)
        if rng.random() < self.gem_rate:
            self._spawn(self.gems, rng, self.gem_cap)
        if self.preds and rng.random() < self.pred_move_prob:
            px, py = self.preds[0]
            dx, dy = self.ax - px, self.ay - py
            dist = abs(dx) + abs(dy)
            if dist <= self.pred_sense:
                stepx = 0 if dx == 0 else (1 if dx > 0 else -1)
                stepy = 0 if dy == 0 else (1 if dy > 0 else -1)
                nx, ny = px + stepx, py + stepy
                if 0 <= nx < self.H and 0 <= ny < self.W and (nx, ny) not in self.obstacles:
                    self.preds[0] = (nx, ny)
            else:
                d = int(rng.integers(8))
                nx, ny = px + DIRS[d][0], py + DIRS[d][1]
                if 0 <= nx < self.H and 0 <= ny < self.W and (nx, ny) not in self.obstacles:
                    self.preds[0] = (nx, ny)

    def move_agent(self, a):
        if a >= 1:
            dx, dy = DIRS[a - 1]
            nx, ny = self.ax + dx, self.ay + dy
            if 0 <= nx < self.H and 0 <= ny < self.W and (nx, ny) not in self.obstacles:
                self.ax, self.ay = nx, ny
        self.energy -= self.decay
        self.ate_food = False
        self.got_gem = False
        if (self.ax, self.ay) in self.foods:
            self.foods.remove((self.ax, self.ay))
            self.energy = min(2.0, self.energy + 0.35)
            self.ate_food = True
        if (self.ax, self.ay) in self.gems:
            self.gems.remove((self.ax, self.ay))
            self.got_gem = True
        dead = False
        if self.preds and self.preds[0] == (self.ax, self.ay):
            dead = True
        if self.energy <= 0:
            dead = True
        return dead

    def step(self, action, rng):
        dead = self.move_agent(int(action))
        reward = 0.0
        if self.ate_food:
            if self.valuable == 0:
                reward = 1.0
                self.n_valuable += 1
                self.score += 1.0
            else:
                self.n_other += 1
                self.score -= self.tox
                reward = -self.tox
        if self.got_gem:
            if self.valuable == 1:
                reward = 1.0
                self.n_valuable += 1
                self.score += 1.0
            else:
                self.n_other += 1
                self.score -= self.tox
                reward = -self.tox
        self.step_world(rng)
        self.t += 1
        done = self.t >= self.T or dead
        if (not done) and self._at_switch(self.t):
            self.valuable = 1 - self.valuable
        obs = self.observe(rng) if not done else np.zeros(OBS)
        info = {
            "valuable": self.valuable,
            "cue_on": bool(self.cue_every or (self._at_switch(self.t) and not done)),
            "dead": dead,
            "n_valuable": self.n_valuable,
            "n_other": self.n_other,
            "score": self.score,
        }
        return obs, reward, done, info

    def episode_return(self):
        """Toxic-aware return (Stance A world payoff)."""
        return self.score / max(1, self.T)


# ---------------------------------------------------------------------------
# Frozen Phase1 foraging navigator (never evolved)
# ---------------------------------------------------------------------------
def frozen_nav_action(env, pref):
    """pref: length-2 softmax-ish [p_food, p_gem]. Chase preferred; flee pred; starve→food."""
    pref = np.asarray(pref, float)
    if pref.sum() <= 1e-12:
        pref = np.array([0.5, 0.5])
    else:
        pref = pref / pref.sum()
    want = int(np.argmax(pref))
    # if nearly uniform, chase nearest (no memory signal)
    if abs(pref[0] - pref[1]) < 0.05:
        want = -1  # nearest mode
    nf, df = env._nearest(env.foods, env.ax, env.ay)
    ng, dg = env._nearest(env.gems, env.ax, env.ay)
    np_, dp = env._nearest(env.preds, env.ax, env.ay) if env.preds else (None, 1e9)
    if np_ is not None and dp <= 2:
        dx, dy = env.ax - np_[0], env.ay - np_[1]
        target = (env.ax + (0 if dx == 0 else (1 if dx > 0 else -1)),
                  env.ay + (0 if dy == 0 else (1 if dy > 0 else -1)))
    elif env.energy < 0.35 and nf is not None:
        target = nf
    else:
        if want == -1:
            if nf is not None and (ng is None or df <= dg):
                target = nf
            else:
                target = ng if ng is not None else nf
        else:
            tgt = nf if want == 0 else ng
            if tgt is None:
                tgt = ng if want == 0 else nf
            target = tgt
    if target is None:
        return 0
    best_a, best_d = 0, abs(target[0] - env.ax) + abs(target[1] - env.ay)
    for ai in range(1, 9):
        dx, dy = DIRS[ai - 1]
        nx, ny = env.ax + dx, env.ay + dy
        if 0 <= nx < env.H and 0 <= ny < env.W and (nx, ny) not in env.obstacles:
            d = abs(target[0] - nx) + abs(target[1] - ny)
            if d < best_d:
                best_d, best_a = d, ai
    return best_a


def nav_oracle_mem(env):
    pref = np.zeros(2); pref[env.valuable] = 1.0
    return frozen_nav_action(env, pref)


def nav_nomem_nearest(env):
    return frozen_nav_action(env, np.array([0.5, 0.5]))


# ---------------------------------------------------------------------------
# Goal modules (only these evolve)
# ---------------------------------------------------------------------------
GOAL_KEYS = {
    "memoryless": ["W_xp", "b_p"],
    "rnn": ["W_xh", "W_hh", "b_h", "W_hp", "b_p"],
    "hand_gate": ["W_ss", "b_s", "W_enc", "b_enc", "write_gain", "W_sp", "b_p"],
    "learn_gate": ["w_g", "b_g", "W_write", "b_write", "W_ss", "b_s", "W_sp", "b_p"],
}


def make_memoryless(rng):
    """A: feedforward obs→preference; no latent memory."""
    return {
        "kind": "memoryless",
        "W": {"W_xp": _r(rng, (2, OBS), 0.3), "b_p": _r(rng, 2, 0.1)},
        "R": {"W_xp": np.full((2, OBS), 0.5), "b_p": np.full(2, 0.5)},
    }


def make_rnn(rng):
    W = {
        "W_xh": _r(rng, (HID, OBS), 0.3),
        "W_hh": 0.7 * np.eye(HID) + 0.3 * _r(rng, (HID, HID), 0.3),
        "b_h": _r(rng, HID, 0.05),
        "W_hp": _r(rng, (2, HID), 0.3),
        "b_p": _r(rng, 2, 0.05),
    }
    return {"kind": "rnn", "W": W, "R": {k: np.full_like(v, 0.5) for k, v in W.items()}}


def make_hand_gate(rng):
    """C MAIN: g = write_gain * cue_on; encode valuable into s; readout preference."""
    W_enc = _r(rng, (SDIM, N_GOALS), 0.1)
    W_enc[0, 0] = 1.5
    W_enc[1, 1] = 1.5
    W_enc[1, 0] = -1.5
    W_enc[0, 1] = -1.5
    W = {
        "W_ss": 1.5 * np.eye(SDIM),  # bistable hold (Dx1 TRUE)
        "b_s": np.zeros(SDIM),
        "W_enc": W_enc,
        "b_enc": np.zeros(SDIM),
        "write_gain": np.array([0.95]),
        "W_sp": np.array([[1.0, -1.0, 0.0, 0.0], [-1.0, 1.0, 0.0, 0.0]], dtype=float),
        "b_p": np.zeros(2),
    }
    return {"kind": "hand_gate", "W": W, "R": {k: np.full_like(v, 0.5) for k, v in W.items()}}


def make_hand_gate_fresh(rng):
    """Same structure but with small noise (for evolution init)."""
    ag = make_hand_gate(rng)
    for k in ("W_enc", "W_sp", "b_p", "b_s", "b_enc"):
        ag["W"][k] = ag["W"][k] + 0.05 * rng.standard_normal(ag["W"][k].shape)
    return ag


def make_learn_gate(rng):
    in_g = OBS + SDIM
    W = {
        "w_g": _r(rng, in_g, 0.3),
        "b_g": _r(rng, 1, 0.1),
        "W_write": _r(rng, (SDIM, OBS), 0.35),
        "b_write": _r(rng, SDIM, 0.05),
        "W_ss": 0.85 * np.eye(SDIM) + 0.15 * _r(rng, (SDIM, SDIM), 0.25),
        "b_s": _r(rng, SDIM, 0.05),
        "W_sp": _r(rng, (2, SDIM), 0.3),
        "b_p": _r(rng, 2, 0.05),
    }
    return {"kind": "learn_gate", "W": W, "R": {k: np.full_like(v, 0.5) for k, v in W.items()}}


def make_oracle_goal(rng=None):
    return {"kind": "oracle_goal", "W": {}, "R": {}}


MAKERS = {
    "memoryless": make_memoryless,
    "rnn": make_rnn,
    "hand_gate": make_hand_gate_fresh,
    "learn_gate": make_learn_gate,
    "oracle_goal": make_oracle_goal,
}

ARM_KIND = {"A": "memoryless", "B": "rnn", "C": "hand_gate", "D": "learn_gate"}


def clone_agent(ag):
    out = {"kind": ag["kind"],
           "W": {k: v.copy() for k, v in ag["W"].items()},
           "R": {k: v.copy() for k, v in ag.get("R", {}).items()}}
    if "fake_bottleneck" in ag:
        out["fake_bottleneck"] = ag["fake_bottleneck"]
    if "variant" in ag:
        out["variant"] = ag["variant"]
    return out


def mutate(agent, rng, strength=0.12):
    if agent["kind"] in ("oracle_goal",):
        return
    keys = GOAL_KEYS.get(agent["kind"], list(agent["W"].keys()))
    W, R = agent["W"], agent.get("R", {})
    for k in keys:
        if k not in W:
            continue
        # protect handwritten core structure lightly for hand_gate
        eff = strength
        if R and k in R:
            eff = strength * (0.25 + 0.75 * (1.0 - float(np.mean(R[k]))))
        if agent["kind"] == "hand_gate" and k in ("W_ss",):
            # keep diagonal dominance
            noise = eff * 0.3 * rng.standard_normal(W[k].shape)
            W[k] = W[k] + noise
            # re-assert diagonal bias
            d = np.diag(np.clip(np.diag(W[k]), 0.8, 2.0))
            W[k] = 0.85 * d + 0.15 * W[k]
        else:
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


def has_latent(agent):
    return agent["kind"] in ("rnn", "hand_gate", "learn_gate", "gru_rl")


def latent_dim(agent):
    if agent["kind"] == "rnn":
        return HID
    if agent["kind"] == "gru_rl":
        return int(agent.get("hid", agent["W"].get("hid", 32)))
    return SDIM


def goal_preference(agent, obs, state, env, rng=None):
    """Return (pref[2], new_state, extras). Navigation is external/frozen."""
    kind = agent["kind"]
    W = agent["W"]
    extras = {}
    world = obs[:WORLD_INP]
    cue = obs[WORLD_INP:]

    if kind == "oracle_goal":
        pref = np.zeros(2); pref[env.valuable] = 1.0
        s = np.zeros(SDIM); s[env.valuable] = 1.0
        state = {"s": s}
        extras["s"] = s.copy()
        return pref, state, extras

    if kind == "memoryless":
        logits = W["W_xp"] @ obs + W["b_p"]
        pref = softmax(logits)
        state = {}
        extras["s"] = None
        return pref, state, extras

    if kind == "rnn":
        h = state.get("h", np.zeros(HID))
        h = np.tanh(W["W_xh"] @ obs + W["W_hh"] @ h + W["b_h"])
        pref = softmax(W["W_hp"] @ h + W["b_p"])
        state = {"h": h}
        extras["s"] = h.copy()
        return pref, state, extras

    if kind == "hand_gate":
        s = state.get("s", np.zeros(SDIM))
        cue_on = float(cue[0])
        cue_oh = cue[1:1 + N_GOALS]
        s_hold = np.tanh(W["W_ss"] @ s + W["b_s"])
        s_write = np.tanh(W["W_enc"] @ cue_oh + W["b_enc"])
        g = float(np.clip(W["write_gain"][0], 0.0, 1.0)) * cue_on
        s = (1.0 - g) * s_hold + g * s_write
        if agent.get("fake_bottleneck"):
            pref = np.array([0.5, 0.5])
        else:
            pref = softmax(W["W_sp"] @ s + W["b_p"])
        state = {"s": s}
        extras["s"] = s.copy()
        extras["gate"] = g
        return pref, state, extras

    if kind == "learn_gate":
        s = state.get("s", np.zeros(SDIM))
        s_hold = np.tanh(W["W_ss"] @ s + W["b_s"])
        write = np.tanh(W["W_write"] @ obs + W["b_write"])
        feat = np.concatenate([obs, s_hold])
        g = float(sigmoid(float(W["w_g"] @ feat + W["b_g"][0])))
        s = g * write + (1.0 - g) * s_hold
        pref = softmax(W["W_sp"] @ s + W["b_p"])
        state = {"s": s}
        extras["s"] = s.copy()
        extras["gate"] = g
        return pref, state, extras

    if kind == "gru_rl":
        # numpy GRUCell (reset/update/new) matching torch export; latent = h
        H = int(W["hid"])
        h = state.get("h", np.zeros(H))
        x = np.asarray(obs, float)
        r_t = sigmoid(W["W_ir"] @ x + W["b_ir"] + W["W_hr"] @ h + W["b_hr"])
        z_t = sigmoid(W["W_iz"] @ x + W["b_iz"] + W["W_hz"] @ h + W["b_hz"])
        n_t = np.tanh(W["W_in"] @ x + W["b_in"] + r_t * (W["W_hn"] @ h + W["b_hn"]))
        h = (1.0 - z_t) * n_t + z_t * h
        logits = W["W_ha"] @ h + W["b_a"]
        pref = softmax(logits)
        state = {"h": h}
        extras["s"] = h.copy()
        extras["pref_logits"] = logits.copy()
        return pref, state, extras

    raise ValueError(kind)


def step_agent(agent, obs, state, env, greedy=True, rng=None):
    pref, state, extras = goal_preference(agent, obs, state, env, rng=rng)
    a = frozen_nav_action(env, pref)
    extras["pref"] = np.asarray(pref, float).copy()
    return a, state, extras


# ---------------------------------------------------------------------------
# Rollout / evaluate / evolve
# ---------------------------------------------------------------------------
def make_env(**kw):
    return ToxicValuableGrid(**kw)


def rollout(agent, env, rng, greedy=True, record=False, lesion_s=False, force_s=None,
            store_obs=False, pin=None):
    obs = env.reset(rng) if not getattr(env, "_pre_reset", False) else env.observe(rng)
    state = {}
    n = 0
    traj = [] if record else None
    while True:
        val_before = env.valuable
        cue_vis = bool(env.cue_every or env._at_switch(env.t))
        obs_pre = obs.copy()
        if pin is not None and has_latent(agent):
            key = "h" if agent["kind"] in ("rnn", "gru_rl") else "s"
            state = dict(state)
            state[key] = np.asarray(pin(val_before), float).copy()
        if force_s is not None and has_latent(agent):
            key = "h" if agent["kind"] in ("rnn", "gru_rl") else "s"
            s0 = state.get(key, np.zeros(latent_dim(agent)))
            state = dict(state)
            state[key] = force_s(n, s0, val_before)
        if lesion_s and has_latent(agent):
            key = "h" if agent["kind"] in ("rnn", "gru_rl") else "s"
            state = dict(state)
            state[key] = np.clip(rng.standard_normal(latent_dim(agent)), -1, 1)
        a, state, extras = step_agent(agent, obs, state, env, greedy=greedy, rng=rng)
        obs, r, done, info = env.step(a, rng)
        n += 1
        if record:
            row = {
                "t": n - 1, "a": a, "r": r, "valuable": val_before,
                "s": None if extras.get("s") is None else extras["s"].copy(),
                "cue_visible": cue_vis,
                "pref": extras.get("pref"),
            }
            if store_obs:
                row["obs"] = obs_pre
            traj.append(row)
        if done:
            break
    ret = env.episode_return()
    return ret, traj, {"n_valuable": env.n_valuable, "n_other": env.n_other,
                       "steps": n, "score": env.score}


_ENV_KW = {}


def set_env_defaults(**kw):
    global _ENV_KW
    _ENV_KW = dict(kw)


def env_kwargs():
    return dict(_ENV_KW)


def evaluate(agent, n_eps, seed, cue_every=False, greedy=True, lesion_s=False,
             removal_mode=False, removal_factor=2, **override):
    kw = {**_ENV_KW, **override}
    T = kw.get("T", T_DEFAULT)
    H = kw.get("H", H_DEFAULT)
    W = kw.get("W", W_DEFAULT)
    rng = np.random.default_rng(seed)
    rets = []
    for _ in range(n_eps):
        env = ToxicValuableGrid(H=H, W=W, T=T, cue_every=cue_every,
                                tox=kw.get("tox", TOX_DEFAULT),
                                food_rate=kw.get("food_rate", 0.55),
                                gem_rate=kw.get("gem_rate", 0.50),
                                food_cap=kw.get("food_cap", 14),
                                gem_cap=kw.get("gem_cap", 12),
                                n_food_init=kw.get("n_food_init", 7),
                                n_gem_init=kw.get("n_gem_init", 6),
                                n_obstacles_frac=kw.get("n_obstacles_frac", 0.04),
                                decay=kw.get("decay", 0.006),
                                pred_move_prob=kw.get("pred_move_prob", 0.12))
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        if removal_mode:
            obs = env.reset(r2, removal_mode=True, removal_factor=removal_factor)
            state = {}
            while True:
                if lesion_s and has_latent(agent):
                    key = "h" if agent["kind"] in ("rnn", "gru_rl") else "s"
                    state = dict(state)
                    state[key] = np.clip(r2.standard_normal(latent_dim(agent)), -1, 1)
                a, state, _ = step_agent(agent, obs, state, env, greedy=greedy, rng=r2)
                obs, r, done, info = env.step(a, r2)
                if done:
                    break
            rets.append(env.episode_return())
        else:
            ret, _, _ = rollout(agent, env, r2, greedy=greedy, lesion_s=lesion_s)
            rets.append(ret)
    return float(np.mean(rets)), float(np.std(rets)), rets


def fitness_task_only(agent, rng, K_eval=8, **override):
    """Toxic-aware mean return. No ||Δs|| / s variance / stability. coh_w≡0."""
    kw = {**_ENV_KW, **override}
    scores = []
    for _ in range(K_eval):
        env = ToxicValuableGrid(
            H=kw.get("H", H_DEFAULT), W=kw.get("W", W_DEFAULT), T=kw.get("T", T_DEFAULT),
            tox=kw.get("tox", TOX_DEFAULT),
            food_rate=kw.get("food_rate", 0.55), gem_rate=kw.get("gem_rate", 0.50),
            food_cap=kw.get("food_cap", 14), gem_cap=kw.get("gem_cap", 12),
            n_food_init=kw.get("n_food_init", 7), n_gem_init=kw.get("n_gem_init", 6),
            n_obstacles_frac=kw.get("n_obstacles_frac", 0.04),
            decay=kw.get("decay", 0.006), pred_move_prob=kw.get("pred_move_prob", 0.12),
        )
        ret, _, _ = rollout(agent, env, rng, greedy=True)
        scores.append(ret)
    return float(np.mean(scores))


FITNESS_SOURCE = inspect.getsource(fitness_task_only)


def fitness_source_hash():
    return hashlib.sha256(FITNESS_SOURCE.encode()).hexdigest()


def config_hash(cfg: dict) -> str:
    import json
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()


def evolve(kind, rng, gens=100, pop_n=36, mut=0.12, K_eval=8, log_every=20, probe_cb=None):
    maker = MAKERS[kind]
    pop = [maker(rng) for _ in range(pop_n)]
    best_hist, mean_hist = [], []
    probes = []
    best_ag = None
    best_fit = -1e9
    elite_frac = 0.25
    for gen in range(gens):
        fits = np.asarray([fitness_task_only(ag, rng, K_eval=K_eval) for ag in pop], float)
        order = np.argsort(fits)[::-1]
        elite_n = max(2, int(pop_n * elite_frac))
        elites = [pop[i] for i in order[:elite_n]]
        best_hist.append(float(fits[order[0]]))
        mean_hist.append(float(fits.mean()))
        if fits[order[0]] > best_fit:
            best_fit = float(fits[order[0]])
            best_ag = clone_agent(pop[order[0]])
        if probe_cb is not None and (gen % log_every == 0 or gen == gens - 1):
            probes.append(probe_cb(gen, best_ag, rng))
        newpop = [clone_agent(e) for e in elites]
        while len(newpop) < pop_n:
            parent = elites[int(rng.integers(elite_n))]
            child = clone_agent(parent)
            mutate(child, rng, mut)
            update_resistance(child)
            newpop.append(child)
        pop = newpop
    if best_ag is None:
        best_ag = clone_agent(pop[0])
    return best_ag, {
        "best_hist": best_hist, "mean_hist": mean_hist,
        "best_fit_train": best_fit, "probes": probes,
    }


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------
def collect_s_goal(agent, n_eps, seed, non_cue_only=True, **override):
    kw = {**_ENV_KW, **override}
    rng = np.random.default_rng(seed)
    S, G = [], []
    for _ in range(n_eps):
        env = ToxicValuableGrid(
            H=kw.get("H", H_DEFAULT), W=kw.get("W", W_DEFAULT), T=kw.get("T", T_DEFAULT),
            tox=kw.get("tox", TOX_DEFAULT),
            food_rate=kw.get("food_rate", 0.55), gem_rate=kw.get("gem_rate", 0.50),
            food_cap=kw.get("food_cap", 14), gem_cap=kw.get("gem_cap", 12),
            n_food_init=kw.get("n_food_init", 7), n_gem_init=kw.get("n_gem_init", 6),
            n_obstacles_frac=kw.get("n_obstacles_frac", 0.04),
        )
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        _, traj, _ = rollout(agent, env, r2, greedy=True, record=True)
        for row in traj:
            if row["s"] is None:
                continue
            if non_cue_only and row["cue_visible"]:
                continue
            S.append(row["s"])
            G.append(row["valuable"])
    if not S:
        return np.zeros((0, SDIM)), np.zeros(0, dtype=int)
    return np.stack(S), np.asarray(G, int)


def multinomial_decode_acc(S_tr, G_tr, S_te, G_te, N=N_GOALS):
    if len(G_tr) < N or len(G_te) == 0:
        return 1.0 / N
    X = np.asarray(S_tr, float)
    y = np.asarray(G_tr, int)
    Xt = np.asarray(S_te, float)
    yt = np.asarray(G_te, int)
    Xb = np.concatenate([X, np.ones((len(X), 1))], 1)
    Xtb = np.concatenate([Xt, np.ones((len(Xt), 1))], 1)
    W = []
    for c in range(N):
        yy = (y == c).astype(float)
        A = Xb.T @ Xb + 1e-2 * np.eye(Xb.shape[1])
        w = np.linalg.solve(A, Xb.T @ yy)
        W.append(w)
    W = np.stack(W)
    pred = np.argmax(Xtb @ W.T, axis=1)
    return float((pred == yt).mean())


def obs_window_decode_acc(agent, seed, n_eps=10, window=5, **override):
    kw = {**_ENV_KW, **override}
    rng = np.random.default_rng(seed)
    feats, labels = [], []
    for _ in range(n_eps):
        env = ToxicValuableGrid(
            H=kw.get("H", H_DEFAULT), W=kw.get("W", W_DEFAULT), T=kw.get("T", T_DEFAULT),
            tox=kw.get("tox", TOX_DEFAULT),
            food_rate=kw.get("food_rate", 0.55), gem_rate=kw.get("gem_rate", 0.50),
            food_cap=kw.get("food_cap", 14), gem_cap=kw.get("gem_cap", 12),
            n_food_init=kw.get("n_food_init", 7), n_gem_init=kw.get("n_gem_init", 6),
        )
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        _, traj, _ = rollout(agent, env, r2, greedy=True, record=True, store_obs=True)
        for i, row in enumerate(traj):
            if row.get("cue_visible"):
                continue
            lo = max(0, i - window + 1)
            chunk = traj[lo:i + 1]
            if any(c.get("cue_visible") for c in chunk):
                continue
            o = np.concatenate([c["obs"][WORLD_INP:] for c in chunk])
            need = window * CUE_DIM - len(o)
            if need > 0:
                o = np.concatenate([np.zeros(need), o])
            feats.append(o)
            labels.append(row["valuable"])
    if len(labels) < 10:
        return 0.5
    X = np.stack(feats)
    y = np.asarray(labels, int)
    n = len(y)
    idx = np.arange(n)
    rng2 = np.random.default_rng(seed + 99)
    rng2.shuffle(idx)
    split = max(1, n // 2)
    tr, te = idx[:split], idx[split:]
    Xb = np.concatenate([X[tr], np.ones((len(tr), 1))], 1)
    Xtb = np.concatenate([X[te], np.ones((len(te), 1))], 1)
    Ws = []
    for c in range(N_GOALS):
        yy = (y[tr] == c).astype(float)
        A = Xb.T @ Xb + 1e-1 * np.eye(Xb.shape[1])
        w = np.linalg.solve(A, Xb.T @ yy)
        Ws.append(w)
    Ws = np.stack(Ws)
    pred = np.argmax(Xtb @ Ws.T, axis=1)
    bal = []
    for c in range(N_GOALS):
        m = y[te] == c
        if m.sum() == 0:
            continue
        bal.append(float((pred[m] == c).mean()))
    return float(np.mean(bal)) if bal else 0.5


def goal_centroids(agent, seed, n_eps=40, **override):
    S, G = collect_s_goal(agent, n_eps=n_eps, seed=seed, non_cue_only=True, **override)
    cents = []
    for c in range(N_GOALS):
        mask = G == c
        if mask.sum() == 0:
            cents.append(np.zeros(S.shape[1] if len(S) else SDIM))
        else:
            cents.append(S[mask].mean(0))
    return cents, S, G


def criterion3_flip_rate(agent, cents, seed, n_trials=40, within_steps=8, **override):
    kw = {**_ENV_KW, **override}
    rng = np.random.default_rng(seed)
    if agent["kind"] in ("rnn", "gru_rl"):
        Hdim = HID if agent["kind"] == "rnn" else latent_dim(agent)
        cents2 = []
        for c in cents:
            v = np.zeros(Hdim)
            v[: min(len(c), Hdim)] = c[: min(len(c), Hdim)]
            cents2.append(v)
        cents = cents2
    ok = 0
    used = 0
    for _ in range(n_trials):
        env = ToxicValuableGrid(
            H=kw.get("H", H_DEFAULT), W=kw.get("W", W_DEFAULT), T=min(kw.get("T", T_DEFAULT), 80),
            tox=kw.get("tox", TOX_DEFAULT),
            food_rate=kw.get("food_rate", 0.55), gem_rate=kw.get("gem_rate", 0.50),
            food_cap=kw.get("food_cap", 14), gem_cap=kw.get("gem_cap", 12),
            n_food_init=kw.get("n_food_init", 7), n_gem_init=kw.get("n_gem_init", 6),
        )
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        obs = env.reset(r2)
        true_v = env.valuable
        opp = 1 - true_v
        state = {}
        key = "h" if agent["kind"] in ("rnn", "gru_rl") else "s"
        state[key] = np.asarray(cents[opp], float).copy()
        pref_wrong = 0
        steps = 0
        while steps < within_steps:
            obs_mod = obs.copy()
            obs_mod[WORLD_INP:] = 0.0
            a, state, extras = step_agent(agent, obs_mod, state, env, greedy=True, rng=r2)
            pref = extras.get("pref", np.array([0.5, 0.5]))
            if pref[opp] > pref[true_v]:
                pref_wrong += 1
            obs, r, done, info = env.step(a, r2)
            steps += 1
            if done:
                break
        used += 1
        if pref_wrong >= max(1, within_steps // 3):
            ok += 1
    return float(ok / max(1, used)), used


def pathway_ablation_return(agent, seed, n_eps=8, **override):
    kw = {**_ENV_KW, **override}
    rng = np.random.default_rng(seed)
    rets = []
    for _ in range(n_eps):
        env = ToxicValuableGrid(
            H=kw.get("H", H_DEFAULT), W=kw.get("W", W_DEFAULT), T=kw.get("T", T_DEFAULT),
            tox=kw.get("tox", TOX_DEFAULT),
            food_rate=kw.get("food_rate", 0.55), gem_rate=kw.get("gem_rate", 0.50),
            food_cap=kw.get("food_cap", 14), gem_cap=kw.get("gem_cap", 12),
            n_food_init=kw.get("n_food_init", 7), n_gem_init=kw.get("n_gem_init", 6),
        )
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        obs = env.reset(r2)
        state = {}
        while True:
            obs2 = obs.copy()
            obs2[WORLD_INP:] = 0.0
            a, state, _ = step_agent(agent, obs2, state, env, greedy=True, rng=r2)
            obs, r, done, info = env.step(a, r2)
            if done:
                break
        rets.append(env.episode_return())
    return float(np.mean(rets)), rets
