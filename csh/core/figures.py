"""
figures.py — learning curves, threshold comparison, and the complexity scaling.

Produces four figures:
  fig1_curves_surface.png    accuracy vs n, one line per surface
  fig2_curves_substrate.png  accuracy vs n, one line per N_REL
  fig3_thresholds.png        estimated threshold per surface (H1) and per N_REL (H2)
  fig4_joint.png             threshold heat map over the (surface x N_REL) grid
"""

import json
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analysis import load, curve, seed_thresholds, CRITERION, CHANCE

SURF_ORDER = ["zh", "en", "lisp", "math", "code", "alien", "relperm", "entperm"]
SURF_LABEL = {"zh": "中文", "en": "English", "lisp": "Lisp", "math": "math",
              "code": "code", "alien": "alien", "relperm": "rel-perm",
              "entperm": "ent-perm"}
SURF_COLOR = {"zh": "#c0392b", "en": "#2471a3", "lisp": "#117864",
              "math": "#b7950b", "code": "#6c3483", "alien": "#707b7c",
              "relperm": "#7d6608", "entperm": "#4a235a"}
NR_COLOR = {1: "#1a5276", 2: "#2874a6", 3: "#229954", 4: "#cb4335",
            2.0: "#1a5276", 4.0: "#2874a6", 6.0: "#229954", 10.0: "#cb4335"}

from matplotlib import font_manager as fm
_CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
if not os.path.exists(_CJK):
    _cands = [f.fname for f in fm.fontManager.ttflist
              if "CJK" in f.name or "WenQuanYi" in f.name]
    _CJK = _cands[0] if _cands else "DejaVu Sans"
fm.fontManager.addfont(_CJK)
_CJK_NAME = fm.FontProperties(fname=_CJK).get_name()
# a reusable FontProperties carrying the CJK family, for legends/tick labels
_CJK_PROP = fm.FontProperties(fname=_CJK, size=8)
_CJK_PROP_LBL = fm.FontProperties(fname=_CJK, size=8)

plt.rcParams.update({
    "figure.dpi": 140, "savefig.dpi": 140, "font.size": 9,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 10, "axes.labelsize": 9,
    "font.family": "sans-serif",
    "font.sans-serif": [_CJK_NAME, "DejaVu Sans"],
    "axes.unicode_minus": False,
})


def _finish(ax, xlab, ylab, title):
    ax.axhline(CHANCE, ls=":", lw=1, c="#999")
    ax.axhline(CRITERION, ls="--", lw=1, c="#c0392b", alpha=0.6)
    ax.text(0.99, CHANCE + 0.01, "chance", transform=ax.transAxes, ha="right",
            va="bottom", fontsize=7, color="#777")
    ax.text(0.99, CRITERION + 0.01, "criterion", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=7, color="#c0392b", alpha=0.8)
    ax.set_xlabel(xlab)
    ax.set_ylabel(ylab)
    ax.set_title(title, loc="left")
    ax.set_xscale("log", base=2)


def fig_curves(rows, field, values, fname, title, labels=None, colors=None,
               filter_fn=None):
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    sub = rows if filter_fn is None else [r for r in rows if filter_fn(r)]
    c = curve(sub, (field,))
    for v in values:
        if (v,) not in c:
            continue
        d = c[(v,)]
        ns = sorted(d)
        ys = [d[n][0] for n in ns]
        es = [d[n][1] for n in ns]
        lab = (labels or {}).get(v, str(v))
        col = (colors or {}).get(v)
        ax.errorbar(ns, ys, yerr=es, marker="o", ms=3.2, lw=1.5, capsize=2,
                    label=lab, color=col)
    _finish(ax, "distinct training examples", "held-out depth-3 accuracy", title)
    ax.legend(frameon=False, ncol=2, loc="upper left", prop=_CJK_PROP)
    ax.set_xticks(sorted({r["n_train"] for r in sub}))
    ax.set_xticklabels([f"{v//1000}k" if v >= 1000 else str(v)
                        for v in sorted({r["n_train"] for r in sub})])
    fig.tight_layout()
    fig.savefig(fname)
    plt.close(fig)
    print("wrote", fname)


def fig_thresholds(rows, out):
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.3))

    # H1: surfaces
    ax = axes[0]
    st = seed_thresholds([r for r in rows if r.get("mult") == 1], ("surface",))
    ks = [k for k in SURF_ORDER if (k,) in st]
    if ks:
        m = [st[(k,)][0] for k in ks]
        lo = [st[(k,)][0] - st[(k,)][1] for k in ks]
        hi = [st[(k,)][2] - st[(k,)][0] for k in ks]
        ypos = np.arange(len(ks))
        cols = [SURF_COLOR.get(k, "#2471a3") for k in ks]
        ax.errorbar(m, ypos, xerr=[lo, hi], fmt="o", ms=5, lw=1.4, capsize=3,
                    color="#2471a3", zorder=1)
        ax.scatter(m, ypos, c=cols, s=46, zorder=3, edgecolors="none")
        ax.set_yticks(ypos)
        ax.set_yticklabels([SURF_LABEL[k] for k in ks], fontproperties=_CJK_PROP_LBL)
        ax.axvline(np.exp(np.mean(np.log(m))), ls="--", lw=1, c="#c0392b",
                   alpha=0.7, label="geometric mean")
        ax.legend(frameon=False, fontsize=8, prop={"size": 8})
    ax.set_xlabel("emergence threshold (examples)")
    ax.set_title("S: substrate fixed, surface varies\n"
                 "flat incl. null controls = structure, not symbols", loc="left")

    # H2: substrate complexity
    ax = axes[1]
    st2 = seed_thresholds([r for r in rows if r["surface"] == "en"], ("mult",))
    ks2 = sorted(k[0] for k in st2)
    if len(ks2) >= 3:
        xs = np.array(ks2, dtype=float)
        ys = np.array([st2[(k,)][0] for k in ks2])
        lo = np.array([st2[(k,)][0] - st2[(k,)][1] for k in ks2])
        hi = np.array([st2[(k,)][2] - st2[(k,)][0] for k in ks2])
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="o-", ms=5, lw=1.5, capsize=3,
                    color="#229954")
        lx, ly = np.log(xs), np.log(ys)
        sl, ic = np.polyfit(lx, ly, 1)
        r = np.corrcoef(lx, ly)[0, 1]
        xx = np.linspace(xs.min() * 0.85, xs.max() * 1.15, 50)
        ax.plot(xx, np.exp(ic + sl * np.log(xx)), ls="--", lw=1.2, c="#c0392b",
                label=f"slope {sl:.2f}, r = {r:.2f}")
        ax.legend(frameon=False, fontsize=8)
        ax.set_xscale("log", base=2)
        ax.set_yscale("log")
    ax.set_xlabel("symbolic vocabulary size  N_REL  (type structure fixed)")
    ax.set_ylabel("emergence threshold (examples)")
    ax.set_title("K: surface fixed, vocabulary varies\n"
                 "flat = structure sets threshold; rising = symbol count does",
                 loc="left")
    fig.tight_layout()
    p = os.path.join(out, "fig3_thresholds.png")
    fig.savefig(p)
    plt.close(fig)
    print("wrote", p)


def fig_joint(rows, out):
    surfs = [s for s in SURF_ORDER if any(r["surface"] == s for r in rows)]
    nrels = sorted({r["n_rel"] for r in rows})
    st = seed_thresholds(rows, ("surface", "n_rel"))
    M = np.full((len(surfs), len(nrels)), np.nan)
    for i, s in enumerate(surfs):
        for j, nr in enumerate(nrels):
            if (s, nr) in st and not np.isnan(st[(s, nr)][0]):
                M[i, j] = st[(s, nr)][0]
    fig, ax = plt.subplots(figsize=(1.5 + 1.15 * len(nrels), 0.6 + 0.42 * len(surfs)))
    im = ax.imshow(np.log10(M), cmap="viridis_r", aspect="auto")
    ax.set_xticks(range(len(nrels)))
    ax.set_xticklabels(nrels)
    ax.set_yticks(range(len(surfs)))
    ax.set_yticklabels([SURF_LABEL[s] for s in surfs], fontsize=8)
    ax.set_xlabel("substrate complexity N_REL")
    ax.set_title("threshold (log10 examples) — rows should be flat, columns rising",
                 loc="left")
    for i in range(len(surfs)):
        for j in range(len(nrels)):
            if not np.isnan(M[i, j]):
                ax.text(j, i, f"{M[i,j]:,.0f}", ha="center", va="center",
                        fontsize=7, color="w")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    p = os.path.join(out, "fig4_joint.png")
    fig.savefig(p)
    plt.close(fig)
    print("wrote", p)


def main():
    paths = sys.argv[1:] or ["results/main.jsonl"]
    out = "figures"
    os.makedirs(out, exist_ok=True)
    rows = load(paths)
    print(f"{len(rows)} runs")

    fig_curves(rows, "surface", SURF_ORDER,
               os.path.join(out, "fig1_curves_surface.png"),
               "S: accuracy vs data, one line per surface language "
               "(substrate fixed)",
               labels={k: SURF_LABEL[k] for k in SURF_ORDER},
               colors={k: SURF_COLOR[k] for k in SURF_ORDER},
               filter_fn=lambda r: r.get("mult") == 1)
    fig_curves(rows, "mult", [1, 2, 3, 4],
               os.path.join(out, "fig2_curves_complexity.png"),
               "K: accuracy vs data, one line per symbolic-vocabulary size\n"
               "(type structure fixed: C_eff(3)=24 throughout)",
               labels={k: f"N_REL={6*k}" for k in [1, 2, 3, 4]},
               colors={k: NR_COLOR.get(k) for k in [1, 2, 3, 4]},
               filter_fn=lambda r: r.get("surface") == "en")
    fig_thresholds(rows, out)
    fig_joint(rows, out)


if __name__ == "__main__":
    main()
