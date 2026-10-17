"""Frozen-key atoms, organizers O-H / O-M, single-layer D, linear readout R.

Inherited from phase-1 retest (combinatorial U + hard arm-B kept frozen).
R-A/R-B additions:
- OrganizerH.beta / OrganizerM.beta_scale for R-B knife (i)
- exec_pad dims concat into readout input for R-B knife (ii)
- Arm-B path retained but not used as main evidence in this package
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def sample_keys(n: int, d: int, rng: np.random.Generator) -> np.ndarray:
    x = rng.normal(size=(n, d)).astype(np.float64)
    x /= np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x


def sample_values(n: int, d_v: int, rng: np.random.Generator) -> np.ndarray:
    return (rng.normal(size=(n, d_v)) / math.sqrt(d_v)).astype(np.float64)


def make_probe_concat(d_v: int, d_y: int, rng: np.random.Generator) -> np.ndarray:
    """Linear probe on concatenated values: y = P [v_i; v_j], P shape [d_y, 2*d_v]."""
    P = rng.normal(size=(d_y, 2 * d_v)).astype(np.float64)
    P /= np.linalg.norm(P, axis=1, keepdims=True) + 1e-12
    return P


def n_atoms(n_priv: int, d: int, n_pub_mult: float) -> int:
    return max(n_priv, n_priv + int(round(n_pub_mult * d)))


def make_derangement_on_P(n_priv: int, n: int, rng: np.random.Generator) -> np.ndarray:
    """Fixed derangement π on private indices P={0..n_priv-1}; identity elsewhere."""
    perm = np.arange(n)
    if n_priv < 2:
        return perm
    p = rng.permutation(n_priv)
    for _ in range(200):
        if not np.any(p == np.arange(n_priv)):
            break
        p = rng.permutation(n_priv)
    else:
        p = np.concatenate([np.arange(1, n_priv), [0]])
    perm[:n_priv] = p
    return perm


def build_pair_cues(
    keys: np.ndarray,
    targets_i: np.ndarray,
    targets_j: np.ndarray,
    noise_std: float,
    rng: np.random.Generator,
    pad: str,
    d_pad: int,
    cue_i: Optional[np.ndarray] = None,
    cue_j: Optional[np.ndarray] = None,
    force_random_cue: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Combinatorial cue: q = normalize(k_a + k_b) + ηε.
    Main: (a,b)=(i*,j*). Arm B: wrong pair or random unit if force_random_cue.
    FORBIDDEN: soft shuffles that leave q = normalize(k_i*+k_j*) while claiming destroy.
    """
    n_batch = targets_i.shape[0]
    if cue_i is None:
        cue_i = targets_i
    if cue_j is None:
        cue_j = targets_j
    base = keys[cue_i] + keys[cue_j]
    base = base / (np.linalg.norm(base, axis=1, keepdims=True) + 1e-12)
    if force_random_cue is not None:
        mask = np.asarray(force_random_cue, dtype=bool)
        if mask.any():
            rnd = rng.normal(size=(int(mask.sum()), keys.shape[1])).astype(np.float64)
            rnd /= np.linalg.norm(rnd, axis=1, keepdims=True) + 1e-12
            base = base.copy()
            base[mask] = rnd
    noise = rng.normal(size=base.shape) * noise_std
    cue_key = base + noise
    if pad == "pad_perp":
        pad_noise = rng.normal(size=(n_batch, d_pad)).astype(np.float64) * noise_std
        return np.concatenate([cue_key, pad_noise], axis=1)
    return cue_key


def pad_keys(keys: np.ndarray, pad: str, d_pad: int) -> np.ndarray:
    if pad == "pad_perp":
        z = np.zeros((keys.shape[0], d_pad), dtype=np.float64)
        return np.concatenate([keys, z], axis=1)
    return keys


def wrong_pair_indices(
    targets_i: np.ndarray,
    targets_j: np.ndarray,
    n_priv: int,
    rebind_perm: np.ndarray,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Arm-B combinatorial hard destroy (document clearly):
    1. Prefer a wrong ordered pair (a,b) with a≠b and {a,b}∩{i*,j*}=∅ (fully disjoint).
    2. Else prefer {a,b}≠{i*,j*} (any different unordered pair) via π(i*),π(j*).
    3. If no alternate pair exists (n_priv<3) or only overlapping pairs (n_priv==3),
       force isotropic random unit cue (hard destroy fallback).

    y stays the true pair. Soft shuffle (q still from true keys) is forbidden.
    """
    bs = targets_i.shape[0]
    cue_i = np.empty(bs, dtype=int)
    cue_j = np.empty(bs, dtype=int)
    force_random = np.zeros(bs, dtype=bool)

    for b in range(bs):
        ti, tj = int(targets_i[b]), int(targets_j[b])
        true_set = {ti, tj}
        placed = False
        if n_priv >= 4:
            # try disjoint wrong pair
            others = [x for x in range(n_priv) if x not in true_set]
            for _ in range(40):
                a, c = rng.choice(others, size=2, replace=False)
                cue_i[b], cue_j[b] = int(a), int(c)
                placed = True
                break
        if not placed and n_priv >= 3:
            # any different unordered pair (will share one index when n_priv==3)
            for _ in range(40):
                a, c = rng.choice(n_priv, size=2, replace=False)
                if {int(a), int(c)} != true_set:
                    cue_i[b], cue_j[b] = int(a), int(c)
                    placed = True
                    # n_priv==3: overlapping only — still mark random to hard-destroy
                    if n_priv == 3:
                        force_random[b] = True
                    break
        if not placed:
            # n_priv==2 or failed: derangement fallback then force random
            cue_i[b] = int(rebind_perm[ti])
            cue_j[b] = int(rebind_perm[tj])
            force_random[b] = True
    return cue_i, cue_j, force_random


class OrganizerH:
    """Modern continuous Hopfield / scaled dot-product attention. Keys frozen."""

    def __init__(self, beta: float, d: int):
        self.beta = beta
        self.d = d

    def forward(
        self, q: torch.Tensor, keys: torch.Tensor, values: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        d_in = float(keys.shape[1])
        scale = math.sqrt(d_in)
        beta_raw = self.beta * scale
        logits = beta_raw * (q @ keys.T) / scale
        attn = F.softmax(logits, dim=-1)
        out = attn @ values
        entropy = -(attn * (attn.clamp_min(1e-12).log())).sum(dim=-1)
        return out, attn, entropy


class OrganizerM(nn.Module):
    """Content-agnostic mixer: w = softmax(beta_scale * MLP(q)); MUST NOT read keys.

    beta_scale: R-B knife (i) effective temperature on mixer logits (default 1.0).
    """

    def __init__(self, d_in: int, n: int, hidden: int = 64, beta_scale: float = 1.0):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(d_in, hidden),
            nn.Tanh(),
            nn.Linear(hidden, n),
        )
        self.n = n
        self.beta_scale = float(beta_scale)

    def forward(
        self, q: torch.Tensor, values: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        logits = self.beta_scale * self.mlp(q)
        w = F.softmax(logits, dim=-1)
        out = w @ values
        entropy = -(w * (w.clamp_min(1e-12).log())).sum(dim=-1)
        return out, w, entropy

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())


class Readout(nn.Module):
    def __init__(self, d_v: int, d_y: int, hidden: int = 0):
        super().__init__()
        if hidden and hidden > 0:
            self.net = nn.Sequential(
                nn.Linear(d_v, hidden),
                nn.Tanh(),
                nn.Linear(hidden, d_y),
            )
        else:
            self.net = nn.Linear(d_v, d_y)

    def forward(self, mixed: torch.Tensor) -> torch.Tensor:
        return self.net(mixed)

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())


def concat_exec_pad(mixed: torch.Tensor, exec_pad_dim: int, rng_torch_seed: int) -> torch.Tensor:
    """R-B knife (ii): append irrelevant Gaussian dims to organizer output before R.

    Locks org geometry; only expands readout input. exec_pad_dim=0 → identity.
    """
    if exec_pad_dim is None or int(exec_pad_dim) <= 0:
        return mixed
    b = mixed.shape[0]
    # deterministic-ish noise from seed+batch for reproducibility within cell
    g = torch.Generator(device=mixed.device)
    g.manual_seed(int(rng_torch_seed) % (2**31 - 1))
    pad = torch.randn(b, int(exec_pad_dim), generator=g, device=mixed.device, dtype=mixed.dtype)
    pad = pad / (pad.norm(dim=1, keepdim=True).clamp_min(1e-12))
    return torch.cat([mixed, pad], dim=1)


def concat_exec_pad_np(X: np.ndarray, exec_pad_dim: int, rng: np.random.Generator) -> np.ndarray:
    """NumPy twin of concat_exec_pad for ridge path."""
    if exec_pad_dim is None or int(exec_pad_dim) <= 0:
        return X
    b = X.shape[0]
    pad = rng.normal(size=(b, int(exec_pad_dim))).astype(np.float64)
    pad /= np.linalg.norm(pad, axis=1, keepdims=True) + 1e-12
    return np.concatenate([X, pad], axis=1)

class DirectMLP(nn.Module):
    def __init__(self, d_in: int, d_y: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_in, hidden),
            nn.Tanh(),
            nn.Linear(hidden, d_y),
        )

    def forward(self, q: torch.Tensor) -> torch.Tensor:
        return self.net(q)

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())


def match_hidden_for_d(d_in: int, d_y: int, target_params: int) -> int:
    denom = d_in + 1 + d_y
    h = max(4, int(round((target_params - d_y) / denom)))
    for _ in range(20):
        p = h * denom + d_y
        if p < 0.8 * target_params:
            h += 1
        elif p > 1.2 * target_params:
            h = max(4, h - 1)
        else:
            break
    return h


def stack_trainable_params(d_in: int, n: int, d_v: int, d_y: int, om_hidden: int = 64) -> int:
    om = d_in * om_hidden + om_hidden + om_hidden * n + n
    r = d_v * d_y + d_y
    return om + r


def ridge_fit(X: np.ndarray, Y: np.ndarray, l2: float) -> np.ndarray:
    d = X.shape[1]
    A = X.T @ X + l2 * np.eye(d)
    B = X.T @ Y
    return np.linalg.solve(A, B)


def ridge_predict(X: np.ndarray, W: np.ndarray) -> np.ndarray:
    return X @ W
