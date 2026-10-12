"""paper_figs2.py — 新增图 8（S1 修复前后）与图 9（深度扫描）。

风格与 paper_figs.py 一致：300 dpi、全英文轴标签、灰度可辨、无网格噪声。
"""
import json, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analysis as A

FIG = os.path.join(HERE, "paper_figs")
os.makedirs(FIG, exist_ok=True)
plt.rcParams.update({"font.size": 9, "axes.linewidth": 0.8,
                     "figure.dpi": 300, "savefig.dpi": 300})

REAL = ["zh", "en", "lisp", "math", "code", "alien"]
LABEL = {"zh": "Chinese", "en": "English", "lisp": "Lisp",
         "math": "Math", "code": "Code", "alien": "Alien"}


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def thresholds(rows, crit=0.60):
    ns = sorted({r["n_train"] for r in rows})
    seeds = sorted({r["seed"] for r in rows})
    surf_key = "surface"
    out = {}
    for s in REAL:
        vals = []
        for sd in seeds:
            acc = {r["n_train"]: r["acc"] for r in rows
                   if r[surf_key] == s and r["seed"] == sd}
            if len(acc) < len(ns):
                continue
            t = A.threshold(ns, [acc[n] for n in ns], crit)
            if t is not None and not np.isnan(t):
                vals.append(t)
        if vals:
            out[s] = vals
    return out


def boot(v, n=4000, seed=0):
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


# ---------------- Figure 8 ----------------
orig = load("results/final_merged.jsonl")
fixed = load("results/surface_fix2.jsonl")
to = thresholds(orig)          # 36 seeds, degenerate design
tf = thresholds(fixed)         # 6 seeds, Latin-square design

fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9))
for ax, T, title, nseed in [
        (axes[0], to, "(a) original design (degenerate ids)", 36),
        (axes[1], tf, "(b) fixed design (Latin-square ids)", 6)]:
    xs, ys, los, his = [], [], [], []
    for i, s in enumerate(REAL):
        if s not in T:
            continue
        m = float(np.mean(T[s]))
        lo, hi = boot(T[s])
        xs.append(i); ys.append(m); los.append(m - lo); his.append(hi - m)
    ax.errorbar(xs, ys, yerr=[los, his], fmt="o", color="black",
                ecolor="gray", capsize=3, ms=4, lw=1)
    ax.set_xticks(range(len(REAL)))
    ax.set_xticklabels([LABEL[s] for s in REAL], rotation=30, ha="right")
    ax.set_ylabel(r"emergence threshold $n^\star$")
    ax.set_title(title, fontsize=9)
    ax.axhspan(min(ys), max(ys), color="0.9", zorder=0)
    # annotate the degenerate triple in panel (a)
    if nseed == 36:
        for i in [0, 3, 5]:
            if i < len(xs):
                ax.annotate("", xy=(xs[i], ys[i]), xytext=(xs[i], ys[i]))
        ax.text(0.02, 0.04, "Chinese / Math / Alien identical",
                transform=ax.transAxes, fontsize=7, style="italic")
    ax.grid(alpha=0.25, lw=0.5)
fig.tight_layout()
fig.savefig(os.path.join(FIG, "fig8_s1_fix.png"), bbox_inches="tight")
plt.close(fig)
print("wrote fig8_s1_fix.png")

# ---------------- Figure 9 ----------------
rows = load("results/depth_scan_final.jsonl")
DEPTHS = [3, 4, 5]
GRID = {3: [2000, 3000, 4000, 5000, 6500],
        4: [2500, 3500, 5000, 6500, 8500, 11000],
        5: [3000, 4500, 6000, 8000, 11000, 14000, 20000]}
d = {}
for r in rows:
    d.setdefault((r["test_kind"], r["depth"], r["seed"]), {})[r["n_train"]] = r["acc"]


def interp_log(acc, target):
    pts = sorted(acc.items())
    for i in range(len(pts) - 1):
        n0, a0 = pts[i]; n1, a1 = pts[i + 1]
        if a0 <= target <= a1:
            if a1 == a0:
                return n0
            t = (target - a0) / (a1 - a0)
            return float(np.exp(np.log(n0) + t * (np.log(n1) - np.log(n0))))
    return None


def acc_at(acc, nq):
    pts = sorted(acc.items())
    if nq <= pts[0][0]:
        return pts[0][1]
    if nq >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        n0, a0 = pts[i]; n1, a1 = pts[i + 1]
        if n0 <= nq <= n1:
            t = (np.log(nq) - np.log(n0)) / (np.log(n1) - np.log(n0))
            return a0 + t * (a1 - a0)
    return pts[-1][1]


CELLS = ["Thighovl", "TU", "Tlowovl"]
MARK = {"Thighovl": "s", "TU": "^", "Tlowovl": "o"}
OVL = {"Thighovl": "5/6", "TU": "2/6", "Tlowovl": "0/6"}
gaps = {c: {} for c in CELLS}
tt_thr = {}
for dep in DEPTHS:
    ns = GRID[dep]
    tv = []
    for s in range(6):
        aT = d.get(("TT", dep, s))
        if not aT or len(aT) < len(ns):
            continue
        t = interp_log({n: aT[n] for n in ns}, 0.60)
        if t is not None:
            tv.append(t)
            for c in CELLS:
                aC = d.get((c, dep, s))
                if aC and len(aC) >= len(ns):
                    gaps[c].setdefault(dep, []).append(0.60 - acc_at({n: aC[n] for n in ns}, t))
    tt_thr[dep] = tv

fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9))
ax = axes[0]
for c in CELLS:
    xs = [dep for dep in DEPTHS if gaps[c].get(dep)]
    ms = [float(np.mean(gaps[c][dep])) for dep in xs]
    es = []
    for dep in xs:
        lo, hi = boot(gaps[c][dep])
        es.append((float(np.mean(gaps[c][dep])) - lo, hi - float(np.mean(gaps[c][dep]))))
    e = np.array(es).T
    ax.errorbar(xs, ms, yerr=e, marker=MARK[c], color="black",
                ls="-" if c == "Tlowovl" else ("--" if c == "TU" else ":"),
                label=f"{c} ({OVL[c]})", capsize=3, ms=4, lw=1.1)
ax.set_xticks(DEPTHS)
ax.set_xlabel("chain depth")
ax.set_ylabel(r"gap at crossing  $\tau - \mathrm{acc}_{\mathrm{cell}}(n^\star_{\mathrm{TT}})$")
ax.set_title("(a) transfer gap vs depth", fontsize=9)
ax.set_ylim(-0.04, 0.60)
ax.legend(fontsize=7, frameon=True, framealpha=0.97, loc="center right", edgecolor="0.6")
ax.grid(alpha=0.25, lw=0.5)

ax = axes[1]
xs = DEPTHS
ms = [float(np.mean(tt_thr[dep])) for dep in xs]
es = []
for dep in xs:
    lo, hi = boot(tt_thr[dep])
    es.append((float(np.mean(tt_thr[dep])) - lo, hi - float(np.mean(tt_thr[dep]))))
ax.errorbar(xs, ms, yerr=np.array(es).T, marker="o", color="black", capsize=3, ms=4, lw=1.1)
ax.set_xticks(DEPTHS)
ax.set_xlabel("chain depth")
ax.set_ylabel(r"baseline threshold $n^\star_{\mathrm{TT}}$")
ax.set_title("(b) depth does raise task difficulty", fontsize=9)
ax.grid(alpha=0.25, lw=0.5)
fig.tight_layout()
fig.savefig(os.path.join(FIG, "fig9_depth_scan.png"), bbox_inches="tight")
plt.close(fig)
print("wrote fig9_depth_scan.png")
