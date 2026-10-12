# -*- coding: utf-8 -*-
"""S2c C4″（Dx1 协议）：自身码本 + 定向 Δwf；新 FAKE 对照。"""
from __future__ import annotations
import numpy as np
import s2c_env as E


def bootstrap_ci(fn, n, B=2000, seed=0):
    rng = np.random.default_rng(seed)
    vals = [fn(rng.integers(0, n, n)) for _ in range(B)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def ep_seeds(seed, n):
    rng = np.random.default_rng(int(seed))
    return [int(rng.integers(1 << 31)) for _ in range(n)]


def make_true_hand(seed):
    rng = np.random.default_rng(int(seed) + 123_000)
    return E.make_hand_gate(rng)


def make_fake(seed, variant):
    ag = make_true_hand(seed)
    ag["variant"] = variant
    if variant == "fake_zero":
        ag["fake_bottleneck"] = True
        for k in ("write_gain", "W_enc", "W_sp", "b_p"):
            ag["W"][k] = np.zeros_like(ag["W"][k])
    elif variant in ("fake_pos_last", "fake_pos_cue", "fake_rand_cue"):
        pass
    else:
        raise ValueError(variant)
    return ag


def _pos_vec(env):
    v = np.zeros(E.SDIM)
    v[0] = 2.0 * env.ax / max(1, env.H - 1) - 1.0
    v[1] = 2.0 * env.ay / max(1, env.W - 1) - 1.0
    return v


def step_variant(agent, obs, state, env, irng):
    v = agent["variant"]
    Wt = agent["W"]
    cue = obs[E.WORLD_INP:]
    cue_on = float(cue[0])
    s_in = state.get("s", np.zeros(E.SDIM))
    if v == "fake_pos_last":
        s = s_in.copy()
        s_next = _pos_vec(env)
    elif v in ("fake_pos_cue", "fake_rand_cue"):
        g = float(np.clip(Wt["write_gain"][0], 0, 1)) * cue_on
        wv = _pos_vec(env) if v == "fake_pos_cue" else irng.uniform(-1, 1, E.SDIM)
        s = (1 - g) * s_in + g * wv
        s_next = s
    else:
        raise ValueError(v)
    pref = E.softmax(Wt["W_sp"] @ s + Wt["b_p"])
    a = E.frozen_nav_action(env, pref)
    return a, {"s": s_next}, s


def run_episode(agent, ep_seed, cue_every=False, pin=None, record_s=False, removal=False):
    kw = E.env_kwargs()
    env = E.ToxicValuableGrid(
        H=kw.get("H", E.H_DEFAULT), W=kw.get("W", E.W_DEFAULT), T=kw.get("T", E.T_DEFAULT),
        cue_every=cue_every, tox=kw.get("tox", E.TOX_DEFAULT),
        food_rate=kw.get("food_rate", 0.55), gem_rate=kw.get("gem_rate", 0.50),
        food_cap=kw.get("food_cap", 14), gem_cap=kw.get("gem_cap", 12),
        n_food_init=kw.get("n_food_init", 7), n_gem_init=kw.get("n_gem_init", 6),
        n_obstacles_frac=kw.get("n_obstacles_frac", 0.04),
    )
    r = np.random.default_rng(int(ep_seed))
    irng = np.random.default_rng((int(ep_seed) ^ 0x5EED_F00D) & 0xFFFFFFFF)
    obs = env.reset(r, removal_mode=removal) if removal else env.reset(r)
    state = {}
    S, G = [], []
    custom = agent.get("variant") in ("fake_pos_last", "fake_pos_cue", "fake_rand_cue")
    while True:
        val_before = env.valuable
        cue_vis = bool(env.cue_every or env._at_switch(env.t))
        if pin is not None:
            state = dict(state)
            key = "h" if agent.get("kind") in ("rnn", "gru_rl") else "s"
            state[key] = np.asarray(pin(val_before), float).copy()
        if custom:
            a, state, s_read = step_variant(agent, obs, state, env, irng)
        else:
            a, state, ex = E.step_agent(agent, obs, state, env, greedy=True, rng=r)
            s_read = ex.get("s")
        if record_s and s_read is not None and not cue_vis:
            S.append(np.asarray(s_read, float).copy())
            G.append(val_before)
        obs, rew, done, info = env.step(a, r)
        if done:
            break
    return {"n_val": env.n_valuable, "n_other": env.n_other, "ret": env.episode_return(),
            "score": env.score, "S": S, "G": G}


def centroids(agent, seed, n_eps=40):
    S, G = [], []
    for es in ep_seeds(seed, n_eps):
        o = run_episode(agent, es, record_s=True)
        S += o["S"]; G += o["G"]
    S = np.asarray(S); G = np.asarray(G, int)
    dim = int(S.shape[1]) if len(S) else (E.latent_dim(agent) if E.has_latent(agent) else E.SDIM)
    c = [S[G == k].mean(0) if (G == k).any() else np.zeros(dim) for k in range(E.N_GOALS)]
    return c, S, G


def decode_acc_split(S, G):
    n = len(G)
    if n < 10:
        return 0.5
    k = n // 2
    return E.multinomial_decode_acc(S[:k], G[:k], S[k:], G[k:])


def new_c4pp(agent, seed, thr):
    n_eps = int(thr["n_eps"])
    n_cent = int(thr["n_eps_centroid"])
    cents, S, G = centroids(agent, seed + 1, n_cent)
    dec = decode_acc_split(S, G)
    _, S2, G2 = centroids(agent, seed + 4, int(thr["n_eps_codebook_heldout"]))
    if len(G2):
        d0 = np.linalg.norm(S2 - cents[0], axis=1)
        d1 = np.linalg.norm(S2 - cents[1], axis=1)
        pred = (d1 < d0).astype(int)
        bal = [float((pred[G2 == k] == k).mean()) for k in range(E.N_GOALS) if (G2 == k).any()]
        cb = float(np.mean(bal)) if bal else 0.5
    else:
        cb = 0.5
    out = {"centroid_dist": float(np.linalg.norm(cents[0] - cents[1])),
           "decode_acc_centroid_data": float(dec),
           "codebook_heldout_bal_acc": cb}
    for tag, ce, sd in (("sparse", False, seed + 2), ("every", True, seed + 3)):
        rows = []
        for es in ep_seeds(sd, n_eps):
            po = run_episode(agent, es, ce, pin=lambda vb, c=cents: c[1 - int(vb)])
            ps = run_episode(agent, es, ce, pin=lambda vb, c=cents: c[int(vb)])
            ho = run_episode(agent, es, ce)
            rows.append((ho["n_val"], ho["n_other"], po["n_val"], po["n_other"],
                         ps["n_val"], ps["n_other"]))
        A = np.asarray(rows, float)

        def wf(v, o):
            t = v.sum() + o.sum()
            return float(o.sum() / t) if t > 0 else 0.0

        def dwf(idx):
            return wf(A[idx, 2], A[idx, 3]) - wf(A[idx, 4], A[idx, 5])

        idx_all = np.arange(len(A))
        d = dwf(idx_all)
        lo, hi = bootstrap_ci(dwf, len(A), B=int(thr.get("bootstrap_B", 2000)), seed=seed + 7)
        v_same, v_opp = A[:, 4].mean(), A[:, 2].mean()
        vdrop = float((v_same - v_opp) / max(v_same, 1e-9))
        out[tag] = {
            "wf_healthy": wf(A[:, 0], A[:, 1]), "wf_opp": wf(A[:, 2], A[:, 3]),
            "wf_same": wf(A[:, 4], A[:, 5]),
            "dwf": float(d), "dwf_ci95": [lo, hi],
            "V_healthy": float(A[:, 0].mean()), "V_opp": float(v_opp), "V_same": float(v_same),
            "V_drop_frac_opp_vs_same": vdrop, "n_eps": int(len(A)),
        }
    sp, ev = out["sparse"], out["every"]
    c_0 = cb >= thr["codebook_bal_acc_min"]
    c_i = (sp["dwf"] >= thr["dwf_min"]) and (sp["dwf_ci95"][0] > thr["dwf_ci_lo_gt"])
    c_ii = sp["V_drop_frac_opp_vs_same"] >= thr["V_drop_frac_min"]
    c_iii = ev["dwf"] <= thr["every_max_frac_of_sparse"] * max(sp["dwf"], 1e-9)
    out.update({
        "0_codebook_valid": bool(c_0), "i_directional": bool(c_i),
        "ii_valuable_drop": bool(c_ii), "iii_specific": bool(c_iii),
        "pass_without_codebook_clause": bool(c_i and c_ii and c_iii),
        "pass": bool(c_0 and c_i and c_ii and c_iii),
    })
    return out
