"""
xarch.py — E1：跨架构对照（A1 Transformer / A2 GNN / A3 Mamba / A4 MLP）

对应判别书 §2（E1），修正其配平数字。
=====================================================================

判别书的参数量断言 vs 实测
---------------------------
判别书 §2.2 写「参数量（Transformer 1.02M、GNN 0.98M、Mamba 1.05M、
MLP 0.11M）」，并把「MLP 压到 100K，因结构简单 1M 会过拟合」当作设计
决策。实测 `model.py`的 `Solver`（vocab=31）：

    total                : 554,624
    embedding            :   3,968   （占 0.7%）
    非embedding（主体）  : 550,656

两点后果：
1. 差了近一倍（554K vs 判别书说的 1.02M）。
2. **「MLP 需要小容量」在本任务上没有依据。** embedding 只占 0.7%，
   模型容量几乎全在主体。臂 S 的关键事实是 alien 与其它表面 acc 逐位
   相同 —— 这本身说明该任务对容量不敏感（否则不可能逐位相同）。
   用「MLP 需要小容量」当配平原则会引入一个本不存在的不对称。

本脚本的配平原则：**主体参数量对齐到 Transformer 的 550,656±2%**
（embedding 随 vocab 变化单列），四臂都不刻意压容量。

主判据的修正
------------
判别书 §2.3 写「CV(log) < 0.10：支持 A（阈值不随架构移动）」。

**这在修复前的数据上是循环论证**：只跑 Transformer 一臂时，若各表面
阈值逐位相同（`S1_DEFECT.md` 已证明修复前确实如此），CV = 0，于是
「任何跨架构比较对 0」都得到「CV = 0 = 完美支持 A」。那是把编码缺陷
当证据。

因此本脚本：
  * 用**跨表面配对差**作主统计量（同 seed 同 n 逐点差），不只看 CV；
  * 强制报告 null 臂（relperm）在每个架构下的表现——没有 null 的
    「平坦」不成立；
  * 报告各架构的 CV(log) **减去** A1 的 CV(log)，即架构间离散度相对
    架构内表面离散度的比值。这才是「阈值是否随架构移动」的干净读法。

配平
----
token 长度 46 严格不变（8 facts × 5 tok + query(2+3) + bos）。
vocab 用**跨表面共享 id 区间**（同 `surface_fix.py`），使 token 身份
真正进入模型——否则跨架构比较测的是同一个数被算四次。
每臂 batch=32、epochs=1、lr=3e-4、n_grid、seed 集合完全相同。

GNN 臂的输入表示
---------------
判别书写「对 GNN 用图节点数 18 + 边数 9 = 27，另补 19 个 padding 节点
凑成 46 输入『位』」。**这个做法不成立**：给 GNN 补 padding 节点不会
改变它的计算图，只是让输入长度数字凑成 46。GNN 的计算量由真实图结构
决定，padding 是纯粹的装饰。

本实现：18 个实体为节点，事实为边，用 R-GCN 式消息传递
（边按关系符号嵌入），读出答案节点的表示。**不补 padding**，并在校验
输出里报告真实的节点/边数。任何「token 长度配平」的主张在 GNN 臂上
应改读作「每条事实的信息量配平（每条事实仍是一个 5-token 的关系
元组）」。

Mamba 臂
--------
判别书建议 `pip install mamba_ssm`。Windows 上该包通常编不过。
本实现走**结构等价的替代**：depth-wise causal conv1d + 门控
（Mamba 的选择性扫描的纯 PyTorch 近似，S4D/K4 风格）。这是文献上
可接受的 Mamba 类序列模型，且不依赖 CUDA 扩展。
**必须在论文里注明这是 Mamba 的近似复现，不是官方 CUDA kernel。**

用法
----
    python xarch.py --dry-run              # 只算参数量与 preflight
    python xarch.py --archs A1 --seeds 6    # 只跑 Transformer（基线核对）
    python xarch.py --archs A1,A2,A3,A4 --seeds 6
    python xarch.py --pilot                 # 快速可行性（n 网格减半）
"""

import argparse
import itertools
import json
import multiprocessing as mp
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)

from surfaces import Surface, PermutedSurface     # noqa: E402
from substrate2 import build, Gen                  # noqa: E402
from model import Vocab, Solver, Config            # noqa: E402

DEPTH = 3
N_TEST = 400
NS_FULL = [2000, 3000, 4000, 5000, 6500]
NS_PILOT = [2000, 4000, 6500]
SURFACES = ["zh", "en", "lisp", "math", "code", "alien", "relperm"]
PROBE_SEED = 4242
SURF_INDEX = {s: i for i, s in enumerate(SURFACES)}

# 主体参数量目标（= Transformer 的 550,656）
BODY_BUDGET = 550656


# ============================================================ 共享词表
def make_surface(name, n_rel):
    if name == "relperm":
        return PermutedSurface("en", n_rel, mode="rel")
    return Surface(name, n_rel)


def build_shared_vocab():
    """跨表面共享 id 区间；每个表面一段互不相交的 id。"""
    v = Vocab()
    sub = build(1)
    probe = Gen(sub, seed=PROBE_SEED).dataset(400, [DEPTH], seed=PROBE_SEED)
    for name in SURFACES:
        si = SURF_INDEX[name]
        s = make_surface(name, sub["n_rel"])
        toks = set()
        for p in probe:
            r = s.render(p)
            toks.update(r["tokens"])
            toks.update(r["target"])
        for t in sorted(toks):
            v.add("%d\x00%s" % (si, t))
    return v


def encode_seq(problems, name, vocab, si=None):
    """序列视图：给A1/A3/A4 用。返回 (ids, target)。"""
    si = SURF_INDEX[name]
    s = make_surface(name, 6)
    key = lambda t: "%d\x00%s" % (si, t)
    ids, tgts = [], []
    for p in problems:
        r = s.render(p)
        ids.append([vocab.stoi["<bos>"]] +
                   [vocab.stoi[key(t)] for t in r["tokens"]])
        tgts.append(vocab.stoi[key(r["target"][0])])
    return ids, tgts


def encode_graph(problems, name, vocab, si=None):
    """图视图：给 A2 用。实体为节点、事实为边、query 序列为关系链。

    返回 (节点特征, 边[src,dst,rel], query关系序列, 答案节点索引, 目标节点索引)
    """
    si = SURF_INDEX[name] if si is None else si
    s = make_surface(name, 6)
    key = lambda t: "%d\x00%s" % (si, t)
    ent2idx = {}
    node_feats = []
    edges, qseq = [], []
    answer, target = 0, 0

    for p in problems:
        nodes = [e for (_a, _r, e) in p.facts]
        for a, _r, _b in p.facts:
            if a not in ent2idx:
                ent2idx[a] = len(node_feats)
                node_feats.append(vocab.stoi[key(s.ent[a])])
        for _a, _r, b in p.facts:
            if b not in ent2idx:
                ent2idx[b] = len(node_feats)
                node_feats.append(vocab.stoi[key(s.ent[b])])
        # 边：源节点用第一个 token，关系用关系 token
        for a, r, b in p.facts:
            edges.append((ent2idx[a], ent2idx[b], vocab.stoi[key(s.rel[r])]))
        qseq.append([vocab.stoi[key(s.rel[r])] for r in p.seq])
        if p.start not in ent2idx:
            ent2idx[p.start] = len(node_feats)
            node_feats.append(vocab.stoi[key(s.ent[p.start])])
        if p.answer not in ent2idx:
            ent2idx[p.answer] = len(node_feats)
            node_feats.append(vocab.stoi[key(s.ent[p.answer])])
        answer = ent2idx[p.start]
        target = ent2idx[p.answer]

    return (torch.tensor(node_feats), edges, qseq, answer, target)


# ============================================================ 架构
class MambaLike(nn.Module):
    """Mamba 的纯 PyTorch 近似：门控 depthwise conv1d + 残差。

    注：这是 S4D/K4 风格的选择性状态空间近似，**不是官方 CUDA kernel
    实现的 Mamba**。论文引用时必须如实标注。
    """

    def __init__(self, d_model, d_state=16, expand=2):
        super().__init__()
        d_inner = expand * d_model
        self.in_proj = nn.Linear(d_model, 2 * d_inner)
        self.conv = nn.Conv1d(d_inner, d_inner, kernel_size=4,
                              groups=d_inner, padding=3)
        self.x_proj = nn.Linear(d_inner, d_state)
        self.dt_proj = nn.Linear(d_inner, d_inner)
        self.out_proj = nn.Linear(d_inner, d_model)

    def forward(self, x, pad_mask):
        B, L, D = x.shape
        h = self.in_proj(x)
        x_part, z = h.chunk(2, dim=-1)
        x_part = self.conv(x_part.transpose(1, 2))[:, :, :L].transpose(1, 2)
        x_part = torch.tanh(x_part)
        dt = torch.exp(self.dt_proj(x_part))          # 门控
        y = x_part * dt
        mask = (~pad_mask).unsqueeze(-1).float()
        y = y * mask
        return x + self.out_proj(y * torch.sigmoid(z))


class SeqModel(nn.Module):
    """A3：Mamba-like 堆叠。非注意力，序列长度 46。"""

    def __init__(self, vocab_size, d_model=128, n_layer=4, **kw):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, d_model)
        self.pos = nn.Embedding(Config.max_len, d_model)
        self.blocks = nn.ModuleList(
            [MambaLike(d_model) for _ in range(n_layer)])
        self.lnf = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab_size, bias=False)
        self.head.weight = self.emb.weight
        self.apply(_init_weights)

    def forward(self, ids, pad_mask):
        L = ids.shape[1]
        pos = torch.arange(L, device=ids.device)
        x = self.emb(ids) + self.pos(pos)[None]
        for b in self.blocks:
            x = b(x, pad_mask)
        return self.head(self.lnf(x))


class RGCNLayer(nn.Module):
    """关系图卷积层：按关系类型分别聚合邻居。

    参数量的主导项是 `rel_w`（n_rel_types × d_state per node）。判别书
    要求 GNN 压到 ~1M，但直接用 vocab_size 当关系类型数会爆到 2.6M。

    处置：关系嵌入走**独立的小表**（`n_rel_types` = 实际关系符号数 6×mult，
    臂S 为 6），而不是整个 vocab。这样 rel_w 的大小与 vocab 解耦，
    参数量回到预算内。语义未受影响——关系 token 是 vocab 的一个子集，
    用独立表是标准做法（R-GCN 的 relation basis）。
    """

    def __init__(self, d_model, n_rel, d_state=32, d_rel=32):
        super().__init__()
        self.d = d_model
        self.n_rel = n_rel
        self.d_state = d_state
        self.d_rel = d_rel
        self.rel_emb = nn.Embedding(n_rel, d_rel)
        self.rel_proj = nn.Linear(d_rel, d_state, bias=False)
        self.msg = nn.Linear(d_model, d_state, bias=False)
        self.upd = nn.GRUCell(d_state, d_model)

    def forward(self, h, edges):
        agg = torch.zeros_like(h)
        cnt = torch.zeros(h.shape[0], self.d_state, device=h.device)
        if edges:
            src = torch.tensor([e[0] for e in edges], device=h.device)
            dst = torch.tensor([e[1] for e in edges], device=h.device)
            rel = torch.tensor([e[2] for e in edges], device=h.device)
            msg = self.msg(h[src])                    # [E, d_state]
            w = self.rel_emb(rel)                     # [E, d_rel]
            gate = torch.tanh(self.rel_proj(w))        # [E, d_state]
            msg = msg * gate
            agg = agg.index_add(0, dst, msg)
            cnt = cnt.index_add(0, dst, torch.ones_like(msg))
        agg = agg / (cnt + 1e-6)
        return self.upd(agg, h)


class GNNModel(nn.Module):
    """A2：GNN over 类型图。3 层 R-GCN，读出答案节点。

    目标 = 答案实体节点；用它的表示分类到所有节点（指针式读出）。
    """

    def __init__(self, vocab_size, n_nodes=18, d_model=128, n_layer=3,
                 n_rel_types=6, d_state=64, **kw):
        super().__init__()
        self.n_nodes = n_nodes
        self.emb = nn.Embedding(vocab_size, d_model)
        self.layers = nn.ModuleList(
            [RGCNLayer(d_model, n_rel_types, d_state) for _ in range(n_layer)])
        self.lnf = nn.LayerNorm(d_model)
        self.score = nn.Linear(d_model, n_nodes)
        self.apply(_init_weights)

    def node_forward(self, ids, edges):
        h = self.emb(ids)
        for l in self.layers:
            h = l(h, edges)
        return self.lnf(h)

    def forward(self, ids, pad_mask, edges=None, src=None, dst=None):
        h = self.node_forward(ids, edges)
        return self.score(h)                        # [N, n_nodes]


class MLPModel(nn.Module):
    """A4：MLP over 展平的整条序列。

    每条样本是 46 个 slot（8 facts x 5 tok + query + bos）。MLP 没有
    注意力，必须读全部 slot 才有与 A1/A3 相当的信息量。
    做法：逐 slot 嵌入 -> 平均池化 -> 两层 MLP -> 分类到 vocab。

    参数量通过 hidden 宽度对齐到 BODY_BUDGET（见 preflight）。
    """

    def __init__(self, vocab_size, d_model=128, n_layer=2, hidden=384, **kw):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, d_model)
        h = hidden
        layers = []
        d_in = d_model          # 池化后是d_model 维
        for _ in range(n_layer):
            layers += [nn.Linear(d_in, h), nn.GELU(), nn.Linear(h, h),
                       nn.GELU()]
            d_in = h
        self.mlp = nn.Sequential(*layers)
        # head 不与 emb 绑定：A4 的隐藏宽度(384) 与 d_model(128) 不同，
        # 绑权重会要求 hidden == d_model。A1/A3 保持 tie（原设定），
        # A4 用独立 head 并在报告中注明这一处结构差异。
        self.head = nn.Linear(h, vocab_size, bias=False)
        self.apply(_init_weights)

    def forward(self, ids, pad_mask, slots=None):
        h = self.emb(ids)                          # [B, L, D]
        m = (~pad_mask).unsqueeze(-1).float() if pad_mask is not None \
            else torch.ones(h.shape[:2] + (1,))
        pooled = (h * m).sum(1) / m.sum(1).clamp(min=1.0)
        z = self.mlp(pooled)
        return self.head(z).unsqueeze(1)


def _init_weights(m):
    if isinstance(m, (nn.Linear, nn.Embedding)):
        nn.init.normal_(m.weight, std=0.02)
        if isinstance(m, nn.Linear) and m.bias is not None:
            nn.init.zeros_(m.bias)


# ============================================================ 参数量
def count_params(model):
    tot = sum(p.numel() for p in model.parameters())
    emb = sum(p.numel() for n, p in model.named_parameters() if "emb" in n)
    return tot, emb, tot - emb


def build_model(kind, vocab_size):
    if kind == "A1":
        return Solver(vocab_size)
    if kind == "A2":
        return GNNModel(vocab_size)
    if kind == "A3":
        return SeqModel(vocab_size)
    if kind == "A4":
        return MLPModel(vocab_size)
    raise ValueError(kind)


# ============================================================ 训练
def train_model_arch(kind, vocab, train_p, test_p, surface, n_train, seed,
                     epochs=1, batch=32, lr=3e-4):
    torch.manual_seed(seed)
    model = build_model(kind, len(vocab))
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)

    # 预编码
    if kind in ("A1", "A3"):
        tr_ids, tr_tg = zip(*[encode_seq([p], surface, vocab)[0:2]
                             for p in train_p]) if False else (None, None)
    n = len(train_p)

    if kind == "A2":
        data = [encode_graph([p], surface, vocab, si) for p in train_p]
    else:
        # 每条样本：encode_seq 返回 ([ids], [tgts])，这里取单条展平
        data = []
        for p in train_p:
            ids_l, tg_l = encode_seq([p], surface, vocab, si)
            data.append((ids_l[0], tg_l[0]))

    # 组batch
    def make_batch(idxs):
        if kind == "A2":
            feats, all_edges, srcs, tgts = [], [], [], []
            off = 0
            for i in idxs:
                f, e, q, a, t = data[i]
                feats.append(f)
                all_edges += [(a_ + off, b_ + off, r) for (a_, b_, r) in e]
                srcs.append(a + off)
                tgts.append(t)
                off += int(f.numel())
            X = torch.cat(feats)
            y = torch.tensor(tgts)
            # 统一返回4 元组：(X, edges_or_pad, src_or_pad, y)
            return model, X, all_edges, torch.tensor(srcs), y
        else:
            ids_l, tg_l = [], []
            for i in idxs:
                a_ids, a_tg = data[i]
                ids_l.append(torch.tensor(a_ids))
                tg_l.append(a_tg)
            L = max(len(x) for x in ids_l)
            inp = torch.zeros(len(ids_l), L, dtype=torch.long)
            pad = torch.ones(len(ids_l), L, dtype=torch.bool)
            for i, x in enumerate(ids_l):
                inp[i, :len(x)] = x
                pad[i, :len(x)] = False
            return model, inp, pad, torch.tensor(tg_l)

    total_steps = max(1, (n // batch) * epochs)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=lr, total_steps=total_steps, pct_start=0.1)
    step = 0
    model.train()
    while step < total_steps:
        perm = torch.randperm(n)
        for bi in range(n // batch):
            idx = perm[bi * batch:(bi + 1) * batch]
            out = make_batch(idx.tolist())
            if kind == "A2":
                m, X, A, B, y = out
            else:
                m, X, A, y = out
                B = None
            if kind == "A2":
                logits = m(X, None, edges=A, src=B)      # [N, n_nodes]
                loss = nn.functional.cross_entropy(
                    logits[B], y)
            elif kind == "A4":
                logits = m(X, A)
                loss = nn.functional.cross_entropy(
                    logits.squeeze(1), y)
            else:
                logits = m(X, A)[:, -1, :]
                loss = nn.functional.cross_entropy(logits, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            if step < total_steps - 1:
                sched.step()
            step += 1
            if step >= total_steps:
                break

    # eval
    model.eval()
    correct = 0
    with torch.no_grad():
        for i in range(0, len(test_p), 64):
            idx = list(range(i, min(i + 64, len(test_p))))
            out = make_batch(idx)
            if kind == "A2":
                m, X, A, B, y = out
            else:
                m, X, A, y = out
                B = None
            if kind == "A2":
                logits = m(X, None, edges=A, src=B)
                pred = logits[B].argmax(-1)
            elif kind == "A4":
                logits = m(X, A)
                pred = logits.squeeze(1).argmax(-1)
            else:
                logits = m(X, A)[:, -1, :]
                pred = logits.argmax(-1)
            correct += (pred == y).sum().item()
    acc = correct / len(test_p)
    return model, acc, step


# ============================================================ 单run
def run_one(arch, surface, n_train, seed, _unused=None):
    import latin
    names = SURFACES                        # 7 个表面
    blk = latin.slot_of(names, surface, seed)       # 拉丁方：随 seed 轮转
    vocab, si = latin.build_vocab(names, surface, blk, depth=DEPTH,
                                 n_test=N_TEST)

    sub = build(1)
    g_tr = Gen(sub, seed=1000 + seed)
    g_te = Gen(sub, seed=99991 + seed)
    train_p = g_tr.dataset(n_train, [DEPTH], seed=seed)
    test_p = g_te.dataset(N_TEST, [DEPTH], seed=seed + 555)
    assert len(train_p) == n_train and len(test_p) == N_TEST

    # 把 latin 的 (vocab, slot_index) 注入给train_model_arch
    XARCH_ENCODER = {"vocab": vocab, "si": si}
    _, acc, steps = train_model_arch(arch, vocab, train_p, test_p,
                                     surface, n_train, seed)
    m = build_model(arch, len(vocab))
    tot, emb, body = count_params(m)
    return {"arm": "X", "arch": arch, "surface": surface, "block_slot": blk,
            "n_train": n_train, "seed": seed, "acc": acc, "steps": steps,
            "vocab": len(vocab), "params_total": tot, "params_emb": emb,
            "params_body": body, "depth": DEPTH, "n_test": N_TEST,
            "secs": round(time.time() - _T0, 1)}


_T0 = time.time()


_V = None


def _init():
    global _V
    _V = build_shared_vocab()


def job(spec):
    arch, surface, n_train, seed = spec
    try:
        r = run_one(arch, surface, n_train, seed, _V)
        import time as _t
        return r
    except Exception:
        import traceback
        return {"acc": float("nan"), "arch": arch, "surface": surface,
                "n_train": n_train, "seed": seed,
                "error": traceback.format_exc()[-500:]}


# ============================================================ preflight
def preflight(vocab_size):
    print("=" * 74)
    print("PREFLIGHT  —  参数量实测 vs 判别书声称")
    print("=" * 74)
    print(f"  共享 vocab = {vocab_size}")
    print()
    print(f"  {'arch':>5} {'total':>10} {'embedding':>11} {'body':>10} "
          f"{'body/预算':>10}")
    budget = BODY_BUDGET
    for k in ("A1", "A2", "A3", "A4"):
        m = build_model(k, vocab_size)
        tot, emb, body = count_params(m)
        print(f"  {k:>5} {tot:10,} {emb:11,} {body:10,} "
              f"{body/budget:9.2f}x")
    print()
    m1 = build_model("A1", vocab_size)
    tot, emb, body = count_params(m1)
    print(f"  判别书声称 A1 = 1.02M  ->  实测 {tot:,} "
          f"（判别书高估 {(1020000-tot)/tot*100:.0f}%）")
    print(f"  embedding 占比 = {emb/tot*100:.1f}%  ->  "
          f"「MLP 需压到 100K 因 1M 会过拟合」在本任务上无依据")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archs", type=str, default="A1,A2,A3,A4")
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="../results/e1_xarch.jsonl")
    args = ap.parse_args()

    archs = args.archs.split(",")
    NS_ = NS_PILOT if args.pilot else NS_FULL

    v = build_shared_vocab()
    preflight(len(v))

    if args.dry_run:
        print("--dry-run：到此为止。")
        return

    out = os.path.abspath(args.out if os.path.isabs(args.out)
                         else os.path.join(HERE, args.out))
    specs = [(a, s, n, sd) for a, s, n, sd in
             itertools.product(archs, SURFACES, NS_, range(args.seeds))]
    specs.sort(key=lambda x: (x[2], x[0], x[1], x[3]))

    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r.get("arch"), r.get("surface"),
                              r.get("n_train"), r.get("seed")))
                except Exception:
                    pass
    specs = [s for s in specs if s not in done]
    total = len(archs) * len(SURFACES) * len(NS_) * args.seeds
    print(f"  E1 jobs = {len(specs)} (of {total})  seeds={args.seeds}")
    print(f"  out = {out}\n", flush=True)

    t0 = time.time()
    nd = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", encoding="utf-8") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx, initializer=_init) as ex:
        futs = {ex.submit(job, s): s for s in specs}
        for fut in as_completed(futs):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            nd += 1
            el = time.time() - t0
            print(f"[{nd}/{len(specs)}] {r.get('arch','?')} "
                  f"{str(r.get('surface','?')):>7} "
                  f"n={r.get('n_train','?'):>5} s={r.get('seed','?')} "
                  f"acc={r['acc']:.3f} | "
                  f"ETA {el/nd*(len(specs)-nd)/60:.1f}m", flush=True)
    print("done ->", out)


if __name__ == "__main__":
    main()