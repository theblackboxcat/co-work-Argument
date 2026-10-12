# -*- coding: utf-8 -*-
"""S1h2 ES-GRU: OpenAI-ES standard step + correct best-individual selection.
Fixes vs S1h (s1h_es_gru.py):
  1. BEFORE theta update, save best_vec = theta + sigma * noise[i_best] (the evaluated individual).
  2. After training, re-evaluate BOTH center theta and best_vec with independent rng (K=16), hand over the higher.
Keeps standard step: theta += (lr / sigma) * grad.
"""
from __future__ import annotations
import numpy as np
import s1e_lib as L
from s1g_es_gru import _init_gru_params, params_to_vec, vec_to_params


def openai_es_gru_std(rng, N=4, T=200, hidden=32, n_workers=64, generations=600,
                      sigma=0.08, lr=0.05, K_eval=3, log_every=20, total_evals_cap=38400,
                      k_lo=30, k_hi=70, smoke=False, K_final=16):
    if smoke:
        generations = min(generations, 5)
        n_workers = min(n_workers, 8)
        total_evals_cap = min(total_evals_cap, 40)
        K_final = min(K_final, 4)
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
        # FIX 1: save evaluated best BEFORE theta update
        i_best = int(np.argmax(fits))
        if fits[i_best] > best_fit:
            best_fit = float(fits[i_best])
            best_vec = theta + sigma * noise[i_best]
            best_params = vec_to_params(best_vec, hidden, N)
        # standard OpenAI-ES step
        theta = theta + (lr / sigma) * grad
        hist.append({"gen": gen, "best": float(fits.max()), "mean": float(fits.mean()), "evals": evals,
                     "theta_norm": float(np.linalg.norm(theta))})
        if log_every and gen % log_every == 0:
            print(f"  [ES-GRU-std-S1h2] gen={gen:3d} best={fits.max():.3f} mean={fits.mean():.3f} "
                  f"|theta|={np.linalg.norm(theta):.2f} evals={evals}", flush=True)
    # FIX 2: independent re-eval of center and best_vec (K_final episodes each); hand over higher
    seed_base = int(rng.integers(0, 2**31 - 1))
    rng_c = np.random.default_rng(seed_base)
    rng_b = np.random.default_rng(seed_base + 1)
    center_final = vec_to_params(theta, hidden, N)
    cfit = L.fitness_task_only(L.make_gru_agent(N, center_final), rng_c, N, T,
                               K_eval=K_final, k_lo=k_lo, k_hi=k_hi)
    bfit = L.fitness_task_only(L.make_gru_agent(N, best_params), rng_b, N, T,
                               K_eval=K_final, k_lo=k_lo, k_hi=k_hi)
    if cfit >= bfit:
        handed, handed_fit, handed_src = center_final, float(cfit), "center"
    else:
        handed, handed_fit, handed_src = best_params, float(bfit), "best_vec"
    print(f"  [ES-GRU-std-S1h2] final_select center={cfit:.3f} best_vec={bfit:.3f} "
          f"-> {handed_src} ({handed_fit:.3f}) K_final={K_final}", flush=True)
    return handed, {
        "best_fit_train": float(best_fit),
        "final_center_fit": float(cfit),
        "final_best_vec_fit": float(bfit),
        "final_handed_fit": float(handed_fit),
        "final_handed_src": handed_src,
        "hist": hist, "evals": evals,
        "hist_len": len(hist), "no_goal_labels": True,
        "architecture": "GRU_numpy_policy", "optimizer": "OpenAI_ES_standard_step",
        "step_rule": "theta += (lr/sigma) * eps^T f_std / n",
        "selection_fix": "best_vec_before_theta_update; independent_K16_reeval_center_vs_best",
        "k_lo": int(k_lo), "k_hi": int(k_hi), "N": int(N),
    }
