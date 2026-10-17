"""Run one grid cell — combinatorial U inherited; R-A/R-B knobs: beta_org, exec_pad_dim."""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import torch

from config import (
    ADAM_LR,
    ADAM_STEPS,
    BATCH_SIZE,
    BETA_DEFAULT,
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
    build_pair_cues,
    concat_exec_pad,
    concat_exec_pad_np,
    make_derangement_on_P,
    make_probe_concat,
    match_hidden_for_d,
    n_atoms,
    pad_keys,
    ridge_fit,
    ridge_predict,
    sample_keys,
    sample_values,
    stack_trainable_params,
    wrong_pair_indices,
)


def _torch(x: np.ndarray, device: torch.device) -> torch.Tensor:
    return torch.from_numpy(x.astype(np.float32)).to(device)


def _pair_mass(attn_or_w: torch.Tensor, ti: np.ndarray, tj: np.ndarray) -> float:
    b = np.arange(ti.shape[0])
    return float((attn_or_w[b, ti] + attn_or_w[b, tj]).mean().cpu())


def run_cell(
    d: int,
    alpha: float,
    eta_name: str,
    noise_std: float,
    organizer: str,
    arm: str,
    pad: str,
    seed: int,
    beta_org: float = BETA_DEFAULT,
    exec_pad_dim: int = 0,
    sweep: str = "R-A",
    device: Optional[torch.device] = None,
) -> Dict[str, Any]:
    """
    Same combinatorial task as retest. R-A/R-B knobs:
      beta_org: O-H attention β; O-M logits temperature scale = beta_org/BETA_DEFAULT
      exec_pad_dim: irrelevant dims concat into readout input (knife ii); 0 = off
    Arm B path kept but package main evidence uses arm=main only.
    """
    device = device or torch.device("cpu")
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)

    n_priv = max(2, int(round(alpha * d)))
    n = n_atoms(n_priv, d, N_PUB_MULT)
    keys = sample_keys(n, d, rng)
    values = sample_values(n, D_V, rng)
    probe = make_probe_concat(D_V, D_Y, rng)

    rebind_perm = None
    if arm == "B":
        rebind_perm = make_derangement_on_P(n_priv, n, rng)

    d_in = d + (D_PAD if pad == "pad_perp" else 0)
    keys_pad = pad_keys(keys, pad, D_PAD)
    priv_idx = np.arange(n_priv)
    ep = int(exec_pad_dim)

    def sample_batch(bs: int, rng_local: np.random.Generator):
        ti = rng_local.choice(priv_idx, size=bs, replace=True)
        tj = np.empty(bs, dtype=int)
        for b in range(bs):
            choices = priv_idx[priv_idx != ti[b]]
            tj[b] = int(rng_local.choice(choices))
        concat_v = np.concatenate([values[ti], values[tj]], axis=1)
        y = concat_v @ probe.T
        if arm == "B":
            assert rebind_perm is not None
            cue_i, cue_j, force_rnd = wrong_pair_indices(
                ti, tj, n_priv, rebind_perm, rng_local
            )
            cues = build_pair_cues(
                keys, ti, tj, noise_std, rng_local, pad, D_PAD,
                cue_i=cue_i, cue_j=cue_j, force_random_cue=force_rnd,
            )
        else:
            cues = build_pair_cues(
                keys, ti, tj, noise_std, rng_local, pad, D_PAD,
            )
        return cues, ti, tj, y

    # ---- O-H ----
    if organizer == "O-H":
        oh = OrganizerH(beta=float(beta_org), d=d)
        n_train = max(512, 8 * n_priv)
        cues_tr, ti_tr, tj_tr, y_tr = sample_batch(n_train, rng)
        q = _torch(cues_tr, device)
        k = _torch(keys_pad, device)
        v = _torch(values, device)
        with torch.no_grad():
            mixed, attn, ent = oh.forward(q, k, v)
        X = concat_exec_pad_np(mixed.cpu().numpy(), ep, rng)
        W = ridge_fit(X, y_tr, RIDGE_L2)

        cues_ev, ti_ev, tj_ev, y_ev = sample_batch(N_EVAL, rng)
        qe = _torch(cues_ev, device)
        with torch.no_grad():
            mixed_e, attn_e, ent_e = oh.forward(qe, k, v)
        Xe = concat_exec_pad_np(mixed_e.cpu().numpy(), ep, rng)
        yhat = ridge_predict(Xe, W)
        mse = float(np.mean((yhat - y_ev) ** 2))
        m = _pair_mass(attn_e, ti_ev, tj_ev)
        entropy = float(ent_e.mean().cpu())
        return _pack(
            d, alpha, n_priv, n, eta_name, noise_std, organizer, arm, pad, seed,
            m, -mse, entropy, mse, n_params=int(W.size),
            beta_org=beta_org, exec_pad_dim=ep, sweep=sweep,
        )

    # ---- O-M ----
    if organizer == "O-M":
        # effective β: scale logits relative to default
        beta_scale = float(beta_org) / float(BETA_DEFAULT)
        om_hidden = 64
        om = OrganizerM(d_in, n, hidden=om_hidden, beta_scale=beta_scale).to(device)
        r_in = D_V + ep
        r = Readout(r_in, D_Y, hidden=0).to(device)
        opt = torch.optim.Adam(list(om.parameters()) + list(r.parameters()), lr=ADAM_LR)
        v = _torch(values, device)
        for step in range(ADAM_STEPS):
            cues_b, ti_b, tj_b, y_b = sample_batch(BATCH_SIZE, rng)
            q = _torch(cues_b, device)
            y_t = _torch(y_b, device)
            mixed, w, _ = om.forward(q, v)
            mixed_p = concat_exec_pad(mixed, ep, seed + step)
            yhat = r(mixed_p)
            loss = ((yhat - y_t) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()

        cues_ev, ti_ev, tj_ev, y_ev = sample_batch(N_EVAL, rng)
        qe = _torch(cues_ev, device)
        with torch.no_grad():
            mixed_e, w_e, ent_e = om.forward(qe, v)
            mixed_ep = concat_exec_pad(mixed_e, ep, seed + 9999)
            yhat_e = r(mixed_ep).cpu().numpy()
        mse = float(np.mean((yhat_e - y_ev) ** 2))
        m = _pair_mass(w_e, ti_ev, tj_ev)
        entropy = float(ent_e.mean().cpu())
        npar = om.n_params() + r.n_params()
        return _pack(
            d, alpha, n_priv, n, eta_name, noise_std, organizer, arm, pad, seed,
            m, -mse, entropy, mse, n_params=npar,
            beta_org=beta_org, exec_pad_dim=ep, sweep=sweep,
        )

    # ---- D ----
    if organizer == "D":
        # D has no org β; beta_org recorded but unused (control: should not move with β)
        # knife (ii): expand input by exec_pad_dim irrelevant dims on q
        d_in_eff = d_in + ep
        target_p = stack_trainable_params(d_in, n, D_V, D_Y, om_hidden=64)
        hidden = match_hidden_for_d(d_in_eff, D_Y, target_p)
        model = DirectMLP(d_in_eff, D_Y, hidden).to(device)
        npar = model.n_params()
        ratio = npar / max(target_p, 1)
        opt = torch.optim.Adam(model.parameters(), lr=ADAM_LR)
        for step in range(ADAM_STEPS):
            cues_b, _, _, y_b = sample_batch(BATCH_SIZE, rng)
            if ep > 0:
                pad_b = rng.normal(size=(cues_b.shape[0], ep)).astype(np.float64)
                pad_b /= np.linalg.norm(pad_b, axis=1, keepdims=True) + 1e-12
                cues_b = np.concatenate([cues_b, pad_b], axis=1)
            q = _torch(cues_b, device)
            y_t = _torch(y_b, device)
            yhat = model(q)
            loss = ((yhat - y_t) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()

        cues_ev, ti_ev, tj_ev, y_ev = sample_batch(N_EVAL, rng)
        if ep > 0:
            pad_e = rng.normal(size=(cues_ev.shape[0], ep)).astype(np.float64)
            pad_e /= np.linalg.norm(pad_e, axis=1, keepdims=True) + 1e-12
            cues_ev = np.concatenate([cues_ev, pad_e], axis=1)
        qe = _torch(cues_ev, device)
        with torch.no_grad():
            yhat_e = model(qe).cpu().numpy()
        mse = float(np.mean((yhat_e - y_ev) ** 2))
        m = float("nan")
        entropy = float("nan")
        return _pack(
            d, alpha, n_priv, n, eta_name, noise_std, organizer, arm, pad, seed,
            m, -mse, entropy, mse, n_params=npar, param_ratio=ratio,
            target_params=target_p,
            beta_org=beta_org, exec_pad_dim=ep, sweep=sweep,
        )

    raise ValueError(f"unknown organizer {organizer}")


def _pack(
    d, alpha, n_priv, n, eta_name, noise_std, organizer, arm, pad, seed,
    m, U, entropy, mse, n_params=0, param_ratio=None, target_params=None,
    beta_org=BETA_DEFAULT, exec_pad_dim=0, sweep="R-A",
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
        "beta_org": float(beta_org),
        "exec_pad_dim": int(exec_pad_dim),
        "sweep": sweep,
        "task": "combinatorial_concat",
        "armB_mode": "hard_wrong_pair_train_and_test",
    }
