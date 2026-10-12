# -*- coding: utf-8 -*-
"""G_RL_RNN: tanh RNNCell (no gates), same A2C + return-standardization as S1f2 GRU.
Ladder rung: 无先验（RNN）. Hidden/lr/epochs match G_RL_GRU.
"""
from __future__ import annotations
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

import s1_env_s1 as E


class ActorCriticRNN(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=32):
        super().__init__()
        self.hidden = hidden
        self.rnn = nn.RNNCell(obs_dim, hidden, nonlinearity="tanh")
        self.policy = nn.Linear(hidden, n_actions)
        self.value = nn.Linear(hidden, 1)

    def forward_step(self, obs, h):
        h = self.rnn(obs, h)
        logits = self.policy(h)
        v = self.value(h).squeeze(-1)
        return logits, v, h


def train_rnn_rl(seed, N=4, T=200, hidden=32, lr=0.001, epochs_max=800,
                 episodes_per_epoch=16, gamma=0.99, entropy_coef=0.01, value_coef=0.5,
                 early_stop_return=0.85, device="cpu", smoke=False,
                 k_lo=None, k_hi=None, log_every_epochs=50, eval_every_epochs=None):
    torch.manual_seed(seed)
    np_rng = np.random.default_rng(seed)
    obs_dim = E.obs_dim(N)
    model = ActorCriticRNN(obs_dim, N, hidden=hidden).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    hist = []
    best_state = None
    best_ret = -1.0
    if smoke:
        epochs_max = min(epochs_max, 30)
        episodes_per_epoch = min(episodes_per_epoch, 4)
    if k_lo is None:
        k_lo = E.K_LO
    if k_hi is None:
        k_hi = E.K_HI
    if eval_every_epochs is None:
        eval_every_epochs = min(10, int(log_every_epochs)) if log_every_epochs else 10

    for ep in range(epochs_max):
        model.train()
        epoch_losses = []
        for _ in range(episodes_per_epoch):
            env = E.SwitchCueNEnv(N=N, T=T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
            r2 = np.random.default_rng(int(np_rng.integers(1 << 31)))
            obs = env.reset(r2)
            h = torch.zeros(model.hidden, device=device)
            logps, values, rewards, ents = [], [], [], []
            done = False
            while not done:
                o = torch.tensor(obs, dtype=torch.float32, device=device)
                logits, v, h = model.forward_step(o, h)
                dist = torch.distributions.Categorical(logits=logits)
                a = dist.sample()
                logps.append(dist.log_prob(a))
                values.append(v)
                ents.append(dist.entropy())
                obs, r, done, info = env.step(int(a.item()), r2)
                rewards.append(float(r))
            R = 0.0
            returns = []
            for r in reversed(rewards):
                R = r + gamma * R
                returns.append(R)
            returns = list(reversed(returns))
            returns_t = torch.tensor(returns, dtype=torch.float32, device=device)
            logps_t = torch.stack(logps)
            values_t = torch.stack(values)
            ents_t = torch.stack(ents)
            # S1f2 FIX inherited: standardize MC returns
            ret_mu = returns_t.mean()
            ret_std = returns_t.std() + 1e-8
            returns_norm = (returns_t - ret_mu) / ret_std
            adv = returns_norm - values_t.detach()
            if adv.numel() > 1:
                adv = (adv - adv.mean()) / (adv.std() + 1e-8)
            policy_loss = -(logps_t * adv).mean()
            value_loss = F.mse_loss(values_t, returns_norm)
            entropy_loss = -ents_t.mean()
            loss = policy_loss + value_coef * value_loss + entropy_coef * entropy_loss
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            epoch_losses.append(float(loss.item()))

        if ep % eval_every_epochs == 0 or ep == epochs_max - 1:
            ret = eval_rnn_rl_return(model, N, T, seed=seed + 9000 + ep, n_eps=8, device=device,
                                    k_lo=k_lo, k_hi=k_hi)
            hist.append({"epoch": ep, "loss": float(np.mean(epoch_losses)), "ret": ret})
            if ret > best_ret:
                best_ret = ret
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            if ep % int(log_every_epochs) == 0 or ep == epochs_max - 1:
                print(f"  [G-RL-RNN] epoch={ep:4d} loss={np.mean(epoch_losses):.3f} ret={ret:.3f}", flush=True)
            if ret >= early_stop_return and ep >= 50:
                print(f"  [G-RL-RNN] early stop epoch={ep} ret={ret:.3f}", flush=True)
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    params = export_numpy_rnn(model, hidden)
    return params, {"best_ret_train": best_ret, "hist": hist,
                    "epochs_ran": (hist[-1]["epoch"] + 1) if hist else 0,
                    "no_goal_labels": True,
                    "architecture": "RNNCell_tanh_no_gates",
                    "k_lo": int(k_lo), "k_hi": int(k_hi), "N": int(N)}


@torch.no_grad()
def eval_rnn_rl_return(model, N, T, seed, n_eps=8, device="cpu", k_lo=None, k_hi=None):
    model.eval()
    rng = np.random.default_rng(seed)
    if k_lo is None:
        k_lo = E.K_LO
    if k_hi is None:
        k_hi = E.K_HI
    rets = []
    for _ in range(n_eps):
        env = E.SwitchCueNEnv(N=N, T=T, cue_every=False, k_lo=k_lo, k_hi=k_hi)
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        obs = env.reset(r2)
        h = torch.zeros(model.hidden, device=device)
        total = 0.0
        n = 0
        done = False
        while not done:
            o = torch.tensor(obs, dtype=torch.float32, device=device)
            logits, v, h = model.forward_step(o, h)
            a = int(torch.argmax(logits).item())
            obs, r, done, info = env.step(a, r2)
            total += r
            n += 1
        rets.append(total / max(1, n))
    return float(np.mean(rets))


def export_numpy_rnn(model, hidden):
    """Export RNNCell tanh weights for probe agent kind=rnn_ac."""
    sd = model.state_dict()
    # RNNCell: weight_ih (H, input), weight_hh (H, H), bias_ih, bias_hh
    params = {
        "hid": hidden,
        "W_ih": sd["rnn.weight_ih"].cpu().numpy(),
        "W_hh": sd["rnn.weight_hh"].cpu().numpy(),
        "b_ih": sd["rnn.bias_ih"].cpu().numpy(),
        "b_hh": sd["rnn.bias_hh"].cpu().numpy(),
        "W_ha": sd["policy.weight"].cpu().numpy(),
        "b_a": sd["policy.bias"].cpu().numpy(),
    }
    return params
