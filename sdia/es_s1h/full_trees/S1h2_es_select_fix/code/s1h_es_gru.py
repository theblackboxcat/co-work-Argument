# -*- coding: utf-8 -*-
"""S1h ES-GRU: OpenAI-ES on GRU policy weights with the STANDARD step.
Only change vs s1g_es_gru.openai_es_gru: the update rule.
  S1g (legacy): theta += lr * sigma * g        (g = eps^T f_std / n)
  S1h (std):    theta += (lr / sigma) * g      (= lr/(n*sigma) * sum f_std_i eps_i, Salimans et al. 2017)
Everything else (init, noise, fitness, best-individual selection, budget) is identical.
"""
from __future__ import annotations
import numpy as np
import s1e_lib as L
from s1g_es_gru import _init_gru_params, params_to_vec, vec_to_params


def openai_es_gru_std(rng, N=4, T=200, hidden=32, n_workers=64, generations=600,
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
        theta = theta + (lr / sigma) * grad
        i_best = int(np.argmax(fits))
        if fits[i_best] > best_fit:
            best_fit = float(fits[i_best])
            best_params = vec_to_params(theta + sigma * noise[i_best], hidden, N)
        hist.append({"gen": gen, "best": float(fits.max()), "mean": float(fits.mean()), "evals": evals,
                     "theta_norm": float(np.linalg.norm(theta))})
        if log_every and gen % log_every == 0:
            print(f"  [ES-GRU-std] gen={gen:3d} best={fits.max():.3f} mean={fits.mean():.3f} "
                  f"|theta|={np.linalg.norm(theta):.2f} evals={evals}", flush=True)
    center_final = vec_to_params(theta, hidden, N)
    cfit = L.fitness_task_only(L.make_gru_agent(N, center_final), rng, N, T, K_eval=K_eval, k_lo=k_lo, k_hi=k_hi)
    if cfit > best_fit:
        best_params, best_fit = center_final, cfit
    return best_params, {
        "best_fit_train": best_fit, "hist": hist, "evals": evals,
        "hist_len": len(hist), "no_goal_labels": True,
        "architecture": "GRU_numpy_policy", "optimizer": "OpenAI_ES_standard_step",
        "step_rule": "theta += (lr/sigma) * eps^T f_std / n",
        "k_lo": int(k_lo), "k_hi": int(k_hi), "N": int(N),
    }
