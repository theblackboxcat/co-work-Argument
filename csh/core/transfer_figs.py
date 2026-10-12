"""
transfer_figs.py — figures for the cross-substrate transfer experiment.

Same design constraints as paper_figs.py:
  * English-only labels, 300 dpi, >= 8pt type
  * grayscale-legible: marker + dash pattern, never colour alone
  * seed-level error bands everywhere
  * captions live in the manuscript

FIGURES
  fig5  the 2x2 learning curves, plus the null-arm curves on the same axes,
        so the comparison the verdict rests on is visible rather than asserted
  fig6  the within-row paired penalty, transfer cells against null controls,
        with the bootstrap CIs that decide A vs confounded
  fig7  signature overlap vs branching, the search that says whether the
        confound is separable at n_rel = 6
"""

import json
import os
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

CRITERION = 0.60
CHANCE = 1.0 / 18
OUT = "paper_figs"
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 300,
    "font.family": "DejaVu Sans", "font.size": 8.5,
    "axes.labelsize": 9, "axes.titlesize": 9.5,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "legend.fontsize": 7.4, "legend.frameon": False,
    "axes.linewidth": 0.7, "axes.grid": True,
    "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "xtick.direction": "in", "ytick.direction": "in",
    "xtick.major.width": 0.7, "ytick.major.width": 0.7,
    "xtick.major.size": 3, "ytick.major.size": 3,
    "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
    "figure.constrained_layout.use": False,
})

# grayscale-legible: filled markers for transfer, hollow for baseline,
# dotted for the label-permutation nulls
STYLES = {
    "TT":  dict(color="#1a1a1a", marker="o", ls="-",  ms=4.2, mfc="#1a1a1a"),
    "UU":  dict(color="#4d4d4d", marker="s", ls="-",  ms=4.0, mfc="#4d4d4d"),
    "TU":  dict(color="#1a1a1a", marker="^", ls="--", ms=4.4, mfc="none", mew=1.0),
    "UT":  dict(color="#4d4d4d", marker="D", ls="--", ms=4.0, mfc="none", mew=1.0),
    "TTp": dict(color="#8c8c8c", marker="v", ls=":",  ms=4.0, mfc="none", mew=0.9),
    "UUp": dict(color="#b5b5b5", marker="P", ls=":",  ms=4.0, mfc="none", mew=0.9),
}
LABEL = {
    "TT":  "TT  typed $\\rightarrow$ typed",
    "UU":  "UU  untyped $\\rightarrow$ untyped",
    "TU":  "TU  typed $\\rightarrow$ untyped",
    "UT":  "UT  untyped $\\rightarrow$ typed",
    "TTp": "TTp  labels permuted (null)",
    "UUp": "UUp  labels permuted (null)",
}


STYLES.update({
    "Thighovl": dict(color="#1a1a1a", marker="^", ls="-", ms=4.4, mfc="none", mew=1.0),
    "Tlowovl": dict(color="#8c8c8c", marker="v", ls="--", ms=4.2, mfc="none", mew=1.0),
})
LABEL.update({
    "Thighovl": "overlap 5/6, $C_{eff}$ 13  (harder structure, table intact)",
    "Tlowovl": "overlap 0/6, $C_{eff}$ 3  (table destroyed)",
})


def load(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if not np.isnan(r.get("acc", np.nan)):
                    rows.append(r)
    return rows


def curve(rows, key="cell"):
    acc = defaultdict(list)
    for r in rows:
        acc[(r[key], r["n_train"])].append(r["acc"])
    out = defaultdict(dict)
    for (c, n), v in acc.items():
        out[c][n] = (float(np.mean(v)), float(np.std(v)), len(v))
    return out


def boot(v, n=4000, seed=0):
    v = [x for x in v if x is not None and not np.isnan(x)]
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def cell_seed_n(rows):
    by = defaultdict(dict)
    for r in rows:
        by[(r["cell"], r["seed"])][r["n_train"]] = r["acc"]
    return by


def paired(rows, cell, base):
    """acc(base) - acc(cell), averaged within seed.  POSITIVE = cost."""
    by = cell_seed_n(rows)
    a = {s: d for (c, s), d in by.items() if c == base}
    b = {s: d for (c, s), d in by.items() if c == cell}
    per_seed = {}
    per_n = defaultdict(list)
    for s in sorted(set(a) & set(b)):
        ns = sorted(set(a[s]) & set(b[s]))
        if not ns:
            continue
        ds = [a[s][n] - b[s][n] for n in ns]
        per_seed[s] = float(np.mean(ds))
        for n, d in zip(ns, ds):
            per_n[n].append(d)
    return per_seed, {n: float(np.mean(v)) for n, v in sorted(per_n.items())}


def fig_curves(rows, nulls):
    c = curve(rows + nulls)
    ns = sorted({r["n_train"] for r in rows + nulls})

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9), sharey=True)
    fig.subplots_adjust(left=0.105, right=0.995, top=0.87, bottom=0.16,
                        wspace=0.10)

    # (panel, [(cell, baseline), ...]) -- baseline only annotates transfer cells
    panels = (
        (axes[0], [("TT", "TT"), ("UU", "UU")],
         "(a)  within-substrate baselines"),
        (axes[1], [("TT", "TT"), ("UU", "UU"), ("TU", "TT"), ("UT", "UU")],
         "(b)  cross-substrate transfer"),
    )
    for ax, series, title in panels:
        for cell, base in series:
            if cell not in c:
                continue
            d = c[cell]
            xs = [n for n in ns if n in d]
            ys = [d[n][0] for n in xs]
            es = [d[n][1] for n in xs]
            lbl = LABEL.get(cell, cell)
            if cell != base:
                lbl += f"\n(cost vs {base})"
            ax.errorbar(xs, ys, yerr=es, capsize=1.8, elinewidth=0.8,
                        capthick=0.8, label=lbl, zorder=3, **STYLES[cell])
        ax.axhline(CHANCE, color="#999999", lw=0.7, ls=(0, (1, 2)), zorder=1)
        ax.axhline(CRITERION, color="#666666", lw=0.8, ls=(0, (4, 2)), zorder=1)
        ax.set_xscale("log")
        ax.set_xlabel("training examples $n$")
        ax.set_title(title, loc="left")
        ax.set_ylim(-0.04, 1.06)

    axes[0].set_ylabel("depth-3 accuracy on the test substrate")
    axes[0].text(2100, CHANCE + 0.035, "chance", fontsize=6.6, color="#777777")
    axes[0].text(2100, CRITERION + 0.035, "criterion 0.60", fontsize=6.6,
                 color="#555555")
    axes[0].legend(loc="upper left", handlelength=2.4, labelspacing=0.32,
                   borderpad=0.2)

    fig2, ax2 = plt.subplots(figsize=(3.4, 2.5))
    fig2.subplots_adjust(left=0.155, right=0.98, top=0.80, bottom=0.17)
    for cell in ("TTp", "UUp"):
        if cell not in c:
            continue
        d = c[cell]
        xs = [n for n in ns if n in d]
        ax2.errorbar(xs, [d[n][0] for n in xs], yerr=[d[n][1] for n in xs],
                     capsize=1.8, elinewidth=0.8, capthick=0.8,
                     label=LABEL[cell], zorder=3, **STYLES[cell])
    ax2.axhline(CHANCE, color="#999999", lw=0.7, ls=(0, (1, 2)), zorder=1)
    ax2.axhline(CRITERION, color="#666666", lw=0.8, ls=(0, (4, 2)), zorder=1)
    ax2.set_xscale("log")
    ax2.set_xlabel("training examples $n$")
    ax2.set_ylabel("depth-3 accuracy")
    ax2.set_ylim(-0.04, 1.06)
    ax2.set_title("(c)  null control: same substrate,\n      relation labels permuted",
                  loc="left")
    ax2.legend(loc="upper left", handlelength=2.4, labelspacing=0.32,
               borderpad=0.2)

    fig.savefig(f"{OUT}/fig5_transfer_curves.png")
    fig2.savefig(f"{OUT}/fig5b_null_curves.png")
    plt.close(fig)
    plt.close(fig2)
    print("wrote fig5_transfer_curves.png, fig5b_null_curves.png")


def fig_penalty(rows, nulls, dec=None):
    dec = dec or []
    allr = rows + nulls + dec
    items = [("Tlowovl", "TT", "Tlowovl\noverlap 0/6"),
             ("TU", "TT", "TU\noverlap 2/6"),
             ("UT", "UU", "UT  (vs UU)"),
             ("TTp", "TT", "TTp\nlabels permuted"),
             ("UUp", "UU", "UUp\nlabels permuted"),
             ("Thighovl", "TT", "Thighovl\noverlap 5/6")]

    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    ys, labels = [], []
    for i, (cell, base, lab) in enumerate(items):
        per_seed, _ = paired(allr, cell, base)
        if not per_seed:
            continue
        v = list(per_seed.values())
        mu = float(np.mean(v))
        lo, hi = boot(v)
        ys.append(i)
        labels.append(lab)
        ax.errorbar([mu], [i], xerr=[[mu - lo], [hi - mu]], fmt="o",
                    ms=4.2, color=STYLES[cell]["color"], mfc="none", mew=1.1,
                    capsize=2.4, elinewidth=1.0, capthick=1.0, zorder=3)

    ax.axvline(0, color="#333333", lw=0.9, zorder=2)
    ax.text(0.005, len(items) - 0.42, "no cost", fontsize=6.8, color="#333333")
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=6.9)
    ax.set_ylim(-0.6, len(items) - 0.05)
    ax.set_xlabel("accuracy transferred away,  $acc(\\mathrm{base}) - acc(\\mathrm{cell})$\n"
                  "(positive = the transfer costs accuracy)")
    ax.set_title("Transfer cost vs. label-permutation cost", loc="left")
    ax.grid(axis="y", alpha=0.12)

    fig.subplots_adjust(left=0.31, right=0.965, top=0.92, bottom=0.26)
    fig.savefig(f"{OUT}/fig6_penalty.png")
    plt.close(fig)
    print("wrote fig6_penalty.png")


def fig_overlap(cells, out="paper_figs/fig7_overlap.png"):
    """cells: list of (overlap, branching, note)"""
    fig, ax = plt.subplots(figsize=(3.6, 2.5))
    br = sorted({b for o, b, *_ in cells})
    for b in br:
        os_ = sorted(o for o, bb, *_ in cells if bb == b)
        ax.plot(os_, [b] * len(os_), "o", ms=6, mfc="none", mew=1.1,
                color="#1a1a1a", zorder=3)
    for o, b, note in cells:
        if note:
            ax.annotate(note, (o, b), textcoords="offset points",
                        xytext=(7, 5), fontsize=6.8, color="#333333")
    ax.set_xlabel("signature overlap with typed  $|\\{i : assign[i]=assign_{typed}[i]\\}|$")
    ax.set_ylabel("branching factor")
    ax.set_title("The two quantities do not vary independently", loc="left")
    ax.set_xticks(sorted({o for o, _, _ in cells}))
    fig.savefig(out)
    plt.close(fig)
    print("wrote", out)


def fig_decouple(rows, dec):
    """The decisive figure: cost against signature damage, structure varied."""
    alld = rows + dec
    c = curve(alld, "cell")
    ns = sorted({r["n_train"] for r in alld
                 if r["cell"] in ("TT", "TU", "Thighovl", "Tlowovl")})

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9))

    ax = axes[0]
    for cell in ("TT", "Thighovl", "TU", "Tlowovl"):
        if cell not in c:
            continue
        d = c[cell]
        xs = [n for n in ns if n in d]
        ax.errorbar(xs, [d[n][0] for n in xs], yerr=[d[n][1] for n in xs],
                    capsize=1.8, elinewidth=0.8, capthick=0.8,
                    label=LABEL[cell], zorder=3, **STYLES[cell])
    ax.axhline(CHANCE, color="#999999", lw=0.7, ls=(0, (1, 2)), zorder=1)
    ax.axhline(CRITERION, color="#666666", lw=0.8, ls=(0, (4, 2)), zorder=1)
    ax.set_xscale("log")
    ax.set_ylim(-0.04, 1.06)
    ax.set_xlabel("training examples $n$")
    ax.set_ylabel("depth-3 accuracy")
    ax.set_title("(a)  trained on typed, tested on four substrates", loc="left")
    # legend outside the data region: the curves rise steeply through the middle
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.30), ncol=2,
              handlelength=2.2, labelspacing=0.30, columnspacing=1.2,
              borderpad=0.0)

    # (b) the attribution plot: penalty vs overlap, one point per substrate
    ax = axes[1]
    pts = [("TT", 6, 2.0, 24), ("Thighovl", 5, 2.0, 13),
           ("TU", 2, 3.0, 9), ("Tlowovl", 0, 3.0, 3)]
    # hand-placed offsets so the two near-zero points do not collide
    OFFS = {"TT": (6, 12), "Thighovl": (-4, -20), "TU": (9, 0),
            "Tlowovl": (9, 0)}
    for cell, ovl, br, ce in pts:
        per_seed, _ = paired(alld, cell, "TT")
        if not per_seed:
            continue
        v = list(per_seed.values())
        mu = float(np.mean(v))
        lo, hi = boot(v)
        st = STYLES.get(cell, STYLES["TT"])
        ax.errorbar([ovl], [mu], yerr=[[mu - lo], [hi - mu]], fmt=st["marker"],
                    ms=5.0, color=st["color"], mfc=st.get("mfc", "none"),
                    mew=1.1, capsize=2.6, elinewidth=1.0, capthick=1.0,
                    ls="none", zorder=3)
        ax.annotate(f"{cell}  (branch {br}, $C_{{eff}}$ {ce})", (ovl, mu),
                    textcoords="offset points", xytext=OFFS.get(cell, (8, 0)),
                    fontsize=6.6, color="#333333")
    ax.axhline(0, color="#333333", lw=0.9, zorder=2)
    ax.set_xlim(-0.9, 7.6)
    ax.set_ylim(-0.06, 0.50)
    ax.set_xlabel("signature overlap with the training substrate  (of 6)")
    ax.set_ylabel("accuracy cost")
    ax.set_title("(b)  cost tracks signature damage,\n      not structural difficulty",
                 loc="left")
    ax.grid(axis="x", alpha=0.12)

    fig.subplots_adjust(left=0.085, right=0.995, top=0.88, bottom=0.30,
                        wspace=0.28)
    fig.savefig(f"{OUT}/fig7_decouple.png")
    plt.close(fig)
    print("wrote fig7_decouple.png")


if __name__ == "__main__":
    rows = load("results/transfer.jsonl")
    nulls = load("results/transfer_null.jsonl")
    dec = load("results/decouple.jsonl")
    if rows:
        fig_curves(rows, nulls)
        fig_penalty(rows, nulls, dec)
        if dec:
            fig_decouple(rows, dec)
    else:
        print("no data")
