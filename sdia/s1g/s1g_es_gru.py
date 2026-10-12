# -*- coding: utf-8 -*-
"""Optional ES-GRU: OpenAI-ES on GRU policy weights (no value head). L2-self.
Budget matched to S1e ES: n_workers=64 × gens≤600, total_evals_cap=38400.
"""
from __future__ import annotations
import numpy as np
import s1_env_s1 as E
import s1e_lib as L


def _init_gru_params(rng, N, hidden=32):
    """Xavier-ish init matching torch defaults roughly."""
    obs = E.obs_dim(N)
    H = hidden
    scale_in = 1.0 / np.sqrt(obs)
    scale_h = 1.0 / np.sqrt(H)
    def m(rows, cols, s):
        return rng.uniform(-s, s, size=(rows, cols)).astype(np.float64)
    def b(n):
        return np.zeros(n, dtype=np.float64)
    params = {
        "hid": H,
        "W_ir": m(H, obs, scale_in), "W_iz": m(H, obs, scale_in), "W_in": m(H, obs, scale_in),
        "b_ir": b(H), "b_iz": b(H), "b_in": b(H),
        "W_hr": m(H, H, scale_h), "W_hz": m(H, H, scale_h), "W_hn": m(H, H, scale_h),
        "b_hr": b(H), "b_hz": b(H), "b_hn": b(H),
        "W_ha": m(N, H, 1.0 / np.sqrt(H)),
        "b_a": b(N),
    }
    return params


PARAM_KEYS = [
    "W_ir", "W_iz", "W_in", "b_ir", "b_iz", "b_in",
    "W_hr", "W_hz", "W_hn", "b_hr", "b_hz", "b_hn",
    "W_ha", "b_a",
]


def params_to_vec(params):
    return np.concatenate([params[k].ravel() for k in PARAM_KEYS])


def vec_to_params(vec, hidden, N):
    params = {"hid": hidden}
    offset = 0
    shapes = {
        "W_ir": (hidden, E.obs_dim(N)), "W_iz": (hidden, E.obs_dim(N)), "W_in": (hidden, E.obs_dim(N)),
        "b_ir": (hidden,), "b_iz": (hidden,), "b_in": (hidden,),
        "W_hr": (hidden, hidden), "W_hz": (hidden, hidden), "W_hn": (hidden, hidden),
        "b_hr": (hidden,), "b_hz": (hidden,), "b_hn": (hidden,),
        "W_ha": (N, hidden), "b_a": (N,),
    }
    for k in PARAM_KEYS:
        shape = shapes[k]
        n = int(np.prod(shape))
        params[k] = vec[offset:offset + n].reshape(shape).astype(np.float64)
        offset += n
    return params


def openai_es_gru(rng, N=4, T=200, hidden=32, n_workers=64, generations=600,
                  sigma=0.08, lr=0.05, K_eval=3, log_every=20, total_evals_cap=38400,
                  k_lo=30, k_hi=70, smoke=False):
    if smoke:
        generations = min(generations, 5)
        n_workers = min(n_workers, 8)
        total_evals_cap = min(total_evals_cap, 40)
    center = _init_gru_params(rng, N, hidden)
    theta = params_to_vec(center)
    best_fit = -1.0
    best_params = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in center.items()}
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
            p = vec_to_params(theta + sigma * noise[i], hidden, N)
            ag = L.make_gru_agent(N, p)
            fits[i] = L.fitness_task_only(ag, rng, N, T, K_eval=K_eval, k_lo=k_lo, k_hi=k_hi)
            evals += 1
        f_std = (fits - fits.mean()) / (fits.std() + 1e-8)
        grad = (noise.T @ f_std) / max(1, n_workers)
        theta = theta + lr * sigma * grad
        i_best = int(np.argmax(fits))
        if fits[i_best] > best_fit:
            best_fit = float(fits[i_best])
            best_params = vec_to_params(theta + sigma * noise[i_best], hidden, N)
        hist.append({"gen": gen, "best": float(fits.max()), "mean": float(fits.mean()), "evals": evals})
        if log_every and gen % log_every == 0:
            print(f"  [ES-GRU] gen={gen:3d} best={fits.max():.3f} mean={fits.mean():.3f} evals={evals}", flush=True)
    center_final = vec_to_params(theta, hidden, N)
    cfit = L.fitness_task_only(L.make_gru_agent(N, center_final), rng, N, T, K_eval=K_eval, k_lo=k_lo, k_hi=k_hi)
    if cfit > best_fit:
        best_params, best_fit = center_final, cfit
    return best_params, {
        "best_fit_train": best_fit, "hist": hist, "evals": evals,
        "hist_len": len(hist), "no_goal_labels": True,
        "architecture": "GRU_numpy_policy", "optimizer": "OpenAI_ES",
        "k_lo": int(k_lo), "k_hi": int(k_hi), "N": int(N),
    }
