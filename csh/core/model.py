"""
model.py — a small transformer encoder, sized so the whole experiment runs on CPU.

The dependent variable is the EMERGENCE THRESHOLD: the number of distinct
training examples needed for the model to reach a fixed accuracy criterion on
held-out depth-3 problems. Everything else — architecture, optimizer, LR
schedule, batch size, steps-per-example — is held fixed across conditions.
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.set_num_threads(3)


class Config:
    d_model = 128
    n_layer = 4
    n_head = 4
    d_ff = 256
    dropout = 0.0
    max_len = 160
    tie_weights = True


class Vocab:
    def __init__(self):
        self.itos = ["<pad>", "<bos>", "<unk>"]
        self.stoi = {t: i for i, t in enumerate(self.itos)}

    def add(self, tok):
        if tok not in self.stoi:
            self.stoi[tok] = len(self.itos)
            self.itos.append(tok)
        return self.stoi[tok]

    def __len__(self):
        return len(self.itos)


class Block(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.ln1 = nn.LayerNorm(cfg.d_model)
        self.attn = nn.MultiheadAttention(cfg.d_model, cfg.n_head, dropout=cfg.dropout,
                                         batch_first=True)
        self.ln2 = nn.LayerNorm(cfg.d_model)
        self.ff = nn.Sequential(
            nn.Linear(cfg.d_model, cfg.d_ff), nn.GELU(),
            nn.Linear(cfg.d_ff, cfg.d_model), nn.Dropout(cfg.dropout))

    def forward(self, x, key_padding_mask):
        h = self.ln1(x)
        a, _ = self.attn(h, h, h, key_padding_mask=key_padding_mask,
                         need_weights=False)
        x = x + a
        x = x + self.ff(self.ln2(x))
        return x


class Solver(nn.Module):
    """Causal-free encoder: reads the whole problem, predicts the answer at the
    final position. Loss only on the answer token."""

    def __init__(self, vocab_size, cfg=Config):
        super().__init__()
        self.cfg = cfg
        self.emb = nn.Embedding(vocab_size, cfg.d_model)
        self.pos = nn.Embedding(cfg.max_len, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList([Block(cfg) for _ in range(cfg.n_layer)])
        self.lnf = nn.LayerNorm(cfg.d_model)
        self.head = nn.Linear(cfg.d_model, vocab_size, bias=False)
        if cfg.tie_weights:
            self.head.weight = self.emb.weight
        self.apply(self._init)

    def _init(self, m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, std=0.02)

    def forward(self, ids, pad_mask):
        B, L = ids.shape
        assert L <= self.cfg.max_len, f"seq {L} > max_len {self.cfg.max_len}"
        pos = torch.arange(L, device=ids.device)
        x = self.drop(self.emb(ids) + self.pos(pos)[None])
        for b in self.blocks:
            x = b(x, pad_mask)
        x = self.lnf(x)
        return self.head(x)


def build_vocab(rendered_list) -> Vocab:
    """Pre-populate the vocabulary over the WHOLE corpus before the model is
    instantiated, so len(vocab) is final when Solver is constructed."""
    v = Vocab()
    for r in rendered_list:
        v.add("<bos>")
        for t in r["tokens"]:
            v.add(t)
        for t in r["target"]:
            v.add(t)
    return v


def encode_batch(problems_rendered, vocab: Vocab, device="cpu"):
    """problems_rendered: list of dict(tokens, target). All tokens must already
    be in the vocabulary (see build_vocab)."""
    seqs, tgts = [], []
    unk = vocab.stoi["<unk>"]
    for r in problems_rendered:
        ids = [vocab.stoi["<bos>"]] + [vocab.stoi.get(t, unk) for t in r["tokens"]]
        seqs.append(ids)
        tgts.append(vocab.stoi.get(r["target"][0], unk))
    L = max(len(s) for s in seqs)
    inp = torch.full((len(seqs), L), 0, dtype=torch.long)
    pad = torch.ones((len(seqs), L), dtype=torch.bool)
    for i, s in enumerate(seqs):
        inp[i, :len(s)] = torch.tensor(s)
        pad[i, :len(s)] = False
    y = torch.tensor(tgts)
    return inp.to(device), pad.to(device), y.to(device)


def loss_fn(model, inp, pad, y, label_smooth=0.0):
    logits = model(inp, pad)[:, -1, :]
    return F.cross_entropy(logits, y, label_smoothing=label_smooth), logits


@torch.no_grad()
def accuracy(model, inp, pad, y, bs=256):
    model.eval()
    correct = 0
    for i in range(0, len(y), bs):
        lg = model(inp[i:i + bs], pad[i:i + bs])[:, -1, :]
        correct += (lg.argmax(-1) == y[i:i + bs]).sum().item()
    model.train()
    return correct / len(y)


def train_model(vocab: Vocab, train_r, test_r, steps_per_epoch=1, epochs=1,
                lr=3e-4, batch=32, seed=0, device="cpu", log=None):
    torch.manual_seed(seed)
    model = Solver(len(vocab)).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    n = len(train_r)
    total_steps = max(1, (n // batch) * epochs * steps_per_epoch)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=lr, total_steps=total_steps, pct_start=0.1)
    scaler = torch.amp.GradScaler("cpu", enabled=(device == "cuda"))

    step = 0
    done = False
    while not done:
        perm = torch.randperm(n)
        for bi in range(n // batch):
            idx = perm[bi * batch:(bi + 1) * batch]
            batch_r = [train_r[i] for i in idx.tolist()]
            inp, pad, y = encode_batch(batch_r, vocab, device)
            with torch.amp.autocast("cpu", dtype=torch.bfloat16, enabled=True):
                loss, _ = loss_fn(model, inp, pad, y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            if step < total_steps - 1:
                sched.step()
            step += 1
            if step >= total_steps:
                done = True
                break

    # final eval on held-out
    inp, pad, y = encode_batch(test_r, vocab, device)
    acc = accuracy(model, inp, pad, y)
    return model, acc, step
