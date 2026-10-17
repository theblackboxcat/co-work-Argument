"""Frozen-key atoms, organizers O-H / O-M, single-layer D, linear readout R."""
from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def sample_keys(n: int, d: int, rng: np.random.Generator) -> np.ndarray:
    """Unit-sphere keys in R^d (first d coords); pad dims stay zero externally."""
    x = rng.normal(size=(n, d)).astype(np.float64)
    x /= np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x


def sample_values(n: int, d_v: int, rng: np.random.Generator) -> np.ndarray:
    return (rng.normal(size=(n, d_v)) / math.sqrt(d_v)).astype(np.float64)


def make_probe(d_v: int, d_y: int, rng: np.random.Generator) -> np.ndarray:
    P = rng.normal(size=(d_y, d_v)).astype(np.float64)
    P /= np.linalg.norm(P, axis=1, keepdims=True) + 1e-12
    return P


def n_atoms(n_priv: int, d: int, n_pub_mult: float) -> int:
    return max(n_priv, n_priv + int(round(n_pub_mult * d)))


def build_cues(
    keys: np.ndarray,
    targets: np.ndarray,
    noise_std: float,
    rng: np.random.Generator,
    pad: str,
    d_pad: int,
    rebind_perm: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Cue for target i*: k_{i*} + isotropic noise (on key subspace).
    Pad-⊥: append d_pad dims of noise; keys elsewhere get zero-pad so pad never helps match.
    Arm B: rebind_perm maps target index -> wrong key used as cue template.
    """
    n_batch = targets.shape[0]
    d = keys.shape[1]
    if rebind_perm is not None:
        cue_src = rebind_perm[targets]
    else:
        cue_src = targets
    base = keys[cue_src].copy()
    noise = rng.normal(size=base.shape) * noise_std
    cue_key = base + noise
    if pad == "pad_perp":
        pad_noise = rng.normal(size=(n_batch, d_pad)).astype(np.float64) * noise_std
        # normalize pad block to unit scale similar to key noise energy
        return np.concatenate([cue_key, pad_noise], axis=1)
    return cue_key


def pad_keys(keys: np.ndarray, pad: str, d_pad: int) -> np.ndarray:
    if pad == "pad_perp":
        z = np.zeros((keys.shape[0], d_pad), dtype=np.float64)
        return np.concatenate([keys, z], axis=1)
    return keys


class OrganizerH:
    """Modern continuous Hopfield / scaled dot-product attention. Keys frozen.

    Config BETA is the effective coefficient on q·k (retrieval sharpness).
    Implemented as β_raw = BETA * √d_in so that
        softmax(β_raw q·k_i / √d) = softmax(BETA q·k_i),
    matching the registered formula attn = softmax(β q·k_i / √d).
    """

    def __init__(self, beta: float, d: int):
        self.beta = beta  # effective coeff on q·k
        self.d = d

    def forward(
        self, q: torch.Tensor, keys: torch.Tensor, values: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        # q: [B, d_in], keys: [N, d_in], values: [N, d_v]
        d_in = float(keys.shape[1])
        scale = math.sqrt(d_in)
        beta_raw = self.beta * scale  # so β_raw/√d = self.beta
        logits = beta_raw * (q @ keys.T) / scale  # [B, N] == beta * q·k
        attn = F.softmax(logits, dim=-1)
        out = attn @ values
        entropy = -(attn * (attn.clamp_min(1e-12).log())).sum(dim=-1)
        return out, attn, entropy


class OrganizerM(nn.Module):
    """Content-agnostic mixer: w = softmax(MLP(q)); MUST NOT read keys."""

    def __init__(self, d_in: int, n: int, hidden: int = 64):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(d_in, hidden),
            nn.Tanh(),
            nn.Linear(hidden, n),
        )
        self.n = n

    def forward(
        self, q: torch.Tensor, values: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        logits = self.mlp(q)
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


class DirectMLP(nn.Module):
    """Single-layer (shallow) D: cue (+pad) → ŷ; param-matched to stack."""

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
    """
    Choose hidden so |θ_D| ∈ [0.8, 1.2] × target.
    params ≈ d_in*h + h + h*d_y + d_y = h*(d_in + 1 + d_y) + d_y
    """
    denom = d_in + 1 + d_y
    h = max(4, int(round((target_params - d_y) / denom)))
    # fine-tune
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
    """Trainable count for O-M + linear R (M keys frozen). Used to size D."""
    # O-M: Linear(d_in,h)+bias + Linear(h,n)+bias
    om = d_in * om_hidden + om_hidden + om_hidden * n + n
    r = d_v * d_y + d_y
    return om + r


def ridge_fit(X: np.ndarray, Y: np.ndarray, l2: float) -> np.ndarray:
    """Closed-form multi-output ridge: W shape [d_v, d_y] for ŷ = X @ W."""
    d = X.shape[1]
    A = X.T @ X + l2 * np.eye(d)
    B = X.T @ Y
    return np.linalg.solve(A, B)


def ridge_predict(X: np.ndarray, W: np.ndarray) -> np.ndarray:
    return X @ W
