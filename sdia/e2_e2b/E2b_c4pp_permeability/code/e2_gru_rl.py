# -*- coding: utf-8 -*-
"""E2 G_RL_GRU: A2C on S2c toxic world return ONLY (no goal labels).
S1f2 fix: per-episode MC return standardization.
Action = preference over {food, gem}; navigation frozen Phase1.
"""
from __future__ import annotations
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import s2c_env as E


class ActorCriticGRU(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=32):
        super().__init__()
        self.hidden = hidden
        self.gru = nn.GRUCell(obs_dim, hidden)
        self.policy = nn.Linear(hidden, n_actions)
        self.value = nn.Linear(hidden, 1)

    def forward_step(self, obs, h):
        h = self.gru(obs, h)
        logits = self.policy(h)
        v = self.value(h).squeeze(-1)
        return logits, v, h


def _make_env(**override):
    kw = {**E.env_kwargs(), **override}
    return E.ToxicValuableGrid(
        H=kw.get("H", E.H_DEFAULT), W=kw.get("W", E.W_DEFAULT), T=kw.get("T", E.T_DEFAULT),
        tox=kw.get("tox", E.TOX_DEFAULT),
        food_rate=kw.get("food_rate", 0.55), gem_rate=kw.get("gem_rate", 0.50),
        food_cap=kw.get("food_cap", 14), gem_cap=kw.get("gem_cap", 12),
        n_food_init=kw.get("n_food_init", 7), n_gem_init=kw.get("n_gem_init", 6),
        n_obstacles_frac=kw.get("n_obstacles_frac", 0.04),
        k_lo=kw.get("k_lo", E.K_LO), k_hi=kw.get("k_hi", E.K_HI),
    )


def train_gru_rl(seed, hidden=32, lr=0.001, epochs_max=800, episodes_per_epoch=16,
                 gamma=0.99, entropy_coef=0.01, value_coef=0.5, early_stop_return=0.05,
                 early_stop_min_epoch=50, device="cpu", smoke=False, log_every_epochs=50,
                 eval_every_epochs=None):
    torch.manual_seed(seed)
    np_rng = np.random.default_rng(seed)
    obs_dim = E.OBS
    n_actions = E.N_GOALS  # preference choice
    model = ActorCriticGRU(obs_dim, n_actions, hidden=hidden).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    hist = []
    best_state = None
    best_ret = -1e9
    if smoke:
        epochs_max = min(epochs_max, 20)
        episodes_per_epoch = min(episodes_per_epoch, 4)
    if eval_every_epochs is None:
        eval_every_epochs = min(10, int(log_every_epochs)) if log_every_epochs else 10

    for ep in range(epochs_max):
        model.train()
        epoch_losses = []
        for _ in range(episodes_per_epoch):
            env = _make_env()
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
                # preference one-hot from sampled goal
                pref = np.zeros(E.N_GOALS, dtype=float)
                pref[int(a.item())] = 1.0
                action = E.frozen_nav_action(env, pref)
                obs, r, done, info = env.step(action, r2)
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
            # S1f2 FIX: standardize MC returns (unbiased=False avoids nan on T=1)
            if returns_t.numel() <= 1:
                returns_norm = returns_t * 0.0
                adv = returns_norm - values_t.detach()
            else:
                ret_mu = returns_t.mean()
                ret_std = returns_t.std(unbiased=False) + 1e-8
                returns_norm = (returns_t - ret_mu) / ret_std
                adv = returns_norm - values_t.detach()
                adv = (adv - adv.mean()) / (adv.std(unbiased=False) + 1e-8)
            if not torch.isfinite(returns_norm).all():
                continue  # skip pathological episode
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
            ret = eval_gru_rl_return(model, seed=seed + 9000 + ep, n_eps=8, device=device)
            hist.append({"epoch": ep, "loss": float(np.mean(epoch_losses)), "ret": ret})
            if ret > best_ret:
                best_ret = ret
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            if ep % int(log_every_epochs) == 0 or ep == epochs_max - 1:
                print(f"  [E2b G-RL] epoch={ep:4d} loss={np.mean(epoch_losses):.3f} ret={ret:.4f}", flush=True)
            if early_stop_return is not None and ret >= float(early_stop_return) and ep >= int(early_stop_min_epoch):
                print(f"  [E2b G-RL] early stop epoch={ep} ret={ret:.4f}", flush=True)
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    params = export_numpy_ac(model, hidden)
    return params, {
        "best_ret_train": float(best_ret),
        "hist": hist,
        "epochs_ran": (hist[-1]["epoch"] + 1) if hist else 0,
        "no_goal_labels": True,
        "N_pref": int(E.N_GOALS),
    }


@torch.no_grad()
def eval_gru_rl_return(model, seed, n_eps=8, device="cpu"):
    model.eval()
    rng = np.random.default_rng(seed)
    rets = []
    for _ in range(n_eps):
        env = _make_env()
        r2 = np.random.default_rng(int(rng.integers(1 << 31)))
        obs = env.reset(r2)
        h = torch.zeros(model.hidden, device=device)
        done = False
        while not done:
            o = torch.tensor(obs, dtype=torch.float32, device=device)
            logits, v, h = model.forward_step(o, h)
            a = int(torch.argmax(logits).item())
            pref = np.zeros(E.N_GOALS, dtype=float)
            pref[a] = 1.0
            action = E.frozen_nav_action(env, pref)
            obs, r, done, info = env.step(action, r2)
        rets.append(env.episode_return())
    return float(np.mean(rets))


def export_numpy_ac(model, hidden):
    sd = model.state_dict()
    w_ih = sd["gru.weight_ih"].cpu().numpy()
    w_hh = sd["gru.weight_hh"].cpu().numpy()
    b_ih = sd["gru.bias_ih"].cpu().numpy()
    b_hh = sd["gru.bias_hh"].cpu().numpy()
    H = hidden
    return {
        "hid": hidden,
        "W_ir": w_ih[0:H], "W_iz": w_ih[H:2*H], "W_in": w_ih[2*H:3*H],
        "b_ir": b_ih[0:H], "b_iz": b_ih[H:2*H], "b_in": b_ih[2*H:3*H],
        "W_hr": w_hh[0:H], "W_hz": w_hh[H:2*H], "W_hn": w_hh[2*H:3*H],
        "b_hr": b_hh[0:H], "b_hz": b_hh[H:2*H], "b_hn": b_hh[2*H:3*H],
        "W_ha": sd["policy.weight"].cpu().numpy(),
        "b_a": sd["policy.bias"].cpu().numpy(),
    }


def make_gru_rl_agent(params):
    W = {k: (np.asarray(v, float).copy() if not isinstance(v, (int, float)) else v)
         for k, v in params.items()}
    return {"kind": "gru_rl", "W": W, "hid": int(params["hid"]), "R": {}}
