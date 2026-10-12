# -*- coding: utf-8 -*-
"""Gradient-trained GRU (BPTT) ruler for S1c switch-cue toy."""
from __future__ import annotations
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

import s1_env_s1 as E


class SwitchGRU(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=32):
        super().__init__()
        self.hidden = hidden
        self.gru = nn.GRUCell(obs_dim, hidden)
        self.head = nn.Linear(hidden, n_actions)

    def forward_episode(self, obs_seq):
        T = obs_seq.shape[0]
        h = torch.zeros(self.hidden, device=obs_seq.device, dtype=obs_seq.dtype)
        logits = []
        for t in range(T):
            h = self.gru(obs_seq[t], h)
            logits.append(self.head(h))
        return torch.stack(logits, 0)


def _collect_episode(env, rng, device):
    """Obs sequence is action-independent in this env; labels = goal (= oracle action)."""
    obs = env.reset(rng)
    obs_list, goal_list = [], []
    done = False
    while not done:
        goal = env.goal
        obs_list.append(obs.copy())
        goal_list.append(goal)
        obs, r, done, info = env.step(goal, rng)
    return (
        torch.tensor(np.stack(obs_list), dtype=torch.float32, device=device),
        torch.tensor(np.asarray(goal_list), dtype=torch.long, device=device),
    )


def train_gru(seed, N=4, T=200, hidden=32, lr=0.003, epochs_max=400,
              episodes_per_epoch=8, early_stop_return=0.85, device="cpu"):
    torch.manual_seed(seed)
    np_rng = np.random.default_rng(seed)
    obs_dim = E.obs_dim(N)
    model = SwitchGRU(obs_dim, N, hidden=hidden).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    hist = []
    best_state = None
    best_ret = -1.0

    for ep in range(epochs_max):
        model.train()
        losses = []
        for _ in range(episodes_per_epoch):
            env = E.SwitchCueNEnv(N=N, T=T, cue_every=False)
            obs_seq, goals = _collect_episode(
                env, np.random.default_rng(int(np_rng.integers(1 << 31))), device)
            logits = model.forward_episode(obs_seq)
            loss = F.cross_entropy(logits, goals)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            losses.append(float(loss.item()))

        if ep % 10 == 0 or ep == epochs_max - 1:
            ret = eval_gru_return(model, N, T, seed=seed + 9000 + ep, n_eps=8, device=device)
            hist.append({"epoch": ep, "loss": float(np.mean(losses)), "ret": ret})
            if ret > best_ret:
                best_ret = ret
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            if ep % 50 == 0:
                print(f"  [GRU] epoch={ep:3d} loss={np.mean(losses):.3f} ret={ret:.3f}", flush=True)
            if ret >= early_stop_return and ep >= 30:
                print(f"  [GRU] early stop epoch={ep} ret={ret:.3f}", flush=True)
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    params = export_numpy(model, hidden)
    return params, {"best_ret_train": best_ret, "hist": hist,
                    "epochs_ran": (hist[-1]["epoch"] + 1) if hist else 0}


@torch.no_grad()
def eval_gru_return(model, N, T, seed, n_eps=8, device="cpu"):
    model.eval()
    rng = np.random.default_rng(seed)
    rets = []
    for _ in range(n_eps):
        env = E.SwitchCueNEnv(N=N, T=T, cue_every=False)
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        obs = env.reset(r2)
        h = torch.zeros(model.hidden, device=device)
        total = 0.0
        n = 0
        done = False
        while not done:
            x = torch.tensor(obs, dtype=torch.float32, device=device)
            h = model.gru(x, h)
            a = int(torch.argmax(model.head(h)).item())
            obs, r, done, info = env.step(a, r2)
            total += r
            n += 1
        rets.append(total / max(1, n))
    return float(np.mean(rets))


def export_numpy(model: SwitchGRU, hidden: int) -> dict:
    """Export matching PyTorch GRUCell formulas exactly."""
    sd = model.state_dict()
    w_ih = sd["gru.weight_ih"].cpu().numpy()
    w_hh = sd["gru.weight_hh"].cpu().numpy()
    b_ih = sd["gru.bias_ih"].cpu().numpy()
    b_hh = sd["gru.bias_hh"].cpu().numpy()
    H = hidden
    return {
        "hid": H,
        "W_ir": w_ih[0:H], "W_iz": w_ih[H:2 * H], "W_in": w_ih[2 * H:3 * H],
        "W_hr": w_hh[0:H], "W_hz": w_hh[H:2 * H], "W_hn": w_hh[2 * H:3 * H],
        "b_ir": b_ih[0:H], "b_iz": b_ih[H:2 * H], "b_in": b_ih[2 * H:3 * H],
        "b_hr": b_hh[0:H], "b_hz": b_hh[H:2 * H], "b_hn": b_hh[2 * H:3 * H],
        "W_ha": sd["head.weight"].cpu().numpy(),
        "b_a": sd["head.bias"].cpu().numpy(),
    }
