"""Run one grid cell: (d, alpha, eta, organizer, arm, pad, seed)."""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np
import torch
import torch.nn as nn

from config import (
    ADAM_LR,
    ADAM_STEPS,
    BATCH_SIZE,
    BETA,
    D_PAD,
    D_V,
    D_Y,
    N_EVAL,
    N_PUB_MULT,
    RIDGE_L2,
)
from models import (
    DirectMLP,
    OrganizerH,
    OrganizerM,
    Readout,
    build_cues,
    match_hidden_for_d,
    n_atoms,
    pad_keys,
    ridge_fit,
    ridge_predict,
    sample_keys,
    sample_values,
    make_probe,
    stack_trainable_params,
)


def _torch(x: np.ndarray, device: torch.device) -> torch.Tensor:
    return torch.from_numpy(x.astype(np.float32)).to(device)


def run_cell(
    d: int,
    alpha: float,
    eta_name: str,
    noise_std: float,
    organizer: str,
    arm: str,
    pad: str,
    seed: int,
    device: Optional[torch.device] = None,
) -> Dict[str, Any]:
    device = device or torch.device("cpu")
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)

    n_priv = max(2, int(round(alpha * d)))
    n = n_atoms(n_priv, d, N_PUB_MULT)
    keys = sample_keys(n, d, rng)
    values = sample_values(n, D_V, rng)
    probe = make_probe(D_V, D_Y, rng)

    # Arm B: fixed derangement of cue templates (test-only); no fixed points
    rebind_perm = None
    if arm == "B":
        rebind_perm = rng.permutation(n)
        # ensure derangement so small-N identity cannot leave binding intact
        for _ in range(100):
            if not np.any(rebind_perm == np.arange(n)):
                break
            rebind_perm = rng.permutation(n)
        else:
            # fallback cycle
            rebind_perm = np.concatenate([np.arange(1, n), [0]])

    d_in = d + (D_PAD if pad == "pad_perp" else 0)
    keys_pad = pad_keys(keys, pad, D_PAD)

    priv_idx = np.arange(n_priv)

    def sample_batch(bs: int, rng_local: np.random.Generator, at_test: bool = False):
        """Arm B: destroy binding only at test (train uses intact binding)."""
        targets = rng_local.choice(priv_idx, size=bs, replace=True)
        use_rebind = rebind_perm if (arm == "B" and at_test) else None
        cues = build_cues(
            keys, targets, noise_std, rng_local, pad, D_PAD, rebind_perm=use_rebind
        )
        y = values[targets] @ probe.T  # [B, d_y]
        return cues, targets, y

    # ---- O-H: frozen attention + ridge readout ----
    if organizer == "O-H":
        oh = OrganizerH(beta=BETA, d=d)
        # collect train features
        n_train = max(512, 8 * n_priv)
        cues_tr, targets_tr, y_tr = sample_batch(n_train, rng, at_test=False)
        q = _torch(cues_tr, device)
        k = _torch(keys_pad, device)
        v = _torch(values, device)
        with torch.no_grad():
            mixed, attn, ent = oh.forward(q, k, v)
        X = mixed.cpu().numpy()
        W = ridge_fit(X, y_tr, RIDGE_L2)

        cues_ev, targets_ev, y_ev = sample_batch(N_EVAL, rng, at_test=True)
        qe = _torch(cues_ev, device)
        with torch.no_grad():
            mixed_e, attn_e, ent_e = oh.forward(qe, k, v)
        yhat = ridge_predict(mixed_e.cpu().numpy(), W)
        mse = float(np.mean((yhat - y_ev) ** 2))
        m = float(attn_e[np.arange(N_EVAL), targets_ev].mean().cpu())
        entropy = float(ent_e.mean().cpu())
        return _pack(
            d, alpha, n_priv, n, eta_name, noise_std, organizer, arm, pad, seed,
            m, -mse, entropy, mse, n_params=int(W.size),
        )

    # ---- O-M: train MLP mixer + readout ----
    if organizer == "O-M":
        om_hidden = 64
        om = OrganizerM(d_in, n, hidden=om_hidden).to(device)
        r = Readout(D_V, D_Y, hidden=0).to(device)
        opt = torch.optim.Adam(list(om.parameters()) + list(r.parameters()), lr=ADAM_LR)
        v = _torch(values, device)
        for step in range(ADAM_STEPS):
            cues_b, targets_b, y_b = sample_batch(BATCH_SIZE, rng, at_test=False)
            q = _torch(cues_b, device)
            y_t = _torch(y_b, device)
            mixed, w, _ = om.forward(q, v)  # intentionally no keys
            yhat = r(mixed)
            loss = ((yhat - y_t) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()

        cues_ev, targets_ev, y_ev = sample_batch(N_EVAL, rng, at_test=True)
        qe = _torch(cues_ev, device)
        with torch.no_grad():
            mixed_e, w_e, ent_e = om.forward(qe, v)
            yhat_e = r(mixed_e).cpu().numpy()
        mse = float(np.mean((yhat_e - y_ev) ** 2))
        m = float(w_e[np.arange(N_EVAL), targets_ev].mean().cpu())
        entropy = float(ent_e.mean().cpu())
        npar = om.n_params() + r.n_params()
        return _pack(
            d, alpha, n_priv, n, eta_name, noise_std, organizer, arm, pad, seed,
            m, -mse, entropy, mse, n_params=npar,
        )

    # ---- D: param-matched direct MLP ----
    if organizer == "D":
        target_p = stack_trainable_params(d_in, n, D_V, D_Y, om_hidden=64)
        hidden = match_hidden_for_d(d_in, D_Y, target_p)
        model = DirectMLP(d_in, D_Y, hidden).to(device)
        # enforce band check
        npar = model.n_params()
        ratio = npar / max(target_p, 1)
        opt = torch.optim.Adam(model.parameters(), lr=ADAM_LR)
        for step in range(ADAM_STEPS):
            cues_b, _, y_b = sample_batch(BATCH_SIZE, rng, at_test=False)
            q = _torch(cues_b, device)
            y_t = _torch(y_b, device)
            yhat = model(q)
            loss = ((yhat - y_t) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()

        cues_ev, targets_ev, y_ev = sample_batch(N_EVAL, rng, at_test=True)
        qe = _torch(cues_ev, device)
        with torch.no_grad():
            yhat_e = model(qe).cpu().numpy()
        mse = float(np.mean((yhat_e - y_ev) ** 2))
        # D has no attention mass; leave m as NaN
        m = float("nan")
        entropy = float("nan")
        return _pack(
            d, alpha, n_priv, n, eta_name, noise_std, organizer, arm, pad, seed,
            m, -mse, entropy, mse, n_params=npar, param_ratio=ratio,
            target_params=target_p,
        )

    raise ValueError(f"unknown organizer {organizer}")


def _pack(
    d, alpha, n_priv, n, eta_name, noise_std, organizer, arm, pad, seed,
    m, U, entropy, mse, n_params=0, param_ratio=None, target_params=None,
) -> Dict[str, Any]:
    return {
        "d": d,
        "alpha": alpha,
        "n_priv": n_priv,
        "n": n,
        "eta": eta_name,
        "noise_std": noise_std,
        "organizer": organizer,
        "arm": arm,
        "pad": pad,
        "seed": seed,
        "m": m,
        "U": U,
        "entropy": entropy,
        "mse": mse,
        "n_params": n_params,
        "param_ratio": param_ratio,
        "target_params": target_params,
    }
