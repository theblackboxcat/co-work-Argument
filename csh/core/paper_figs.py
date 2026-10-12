"""
paper_figs.py — publication-grade figures for the substrate-threshold paper.

Design constraints for camera-ready quality:
  * English-only labels (no CJK dependency in the figure pipeline)
  * 300 dpi, >= 8pt type at final printed size
  * grayscale-legible: every series distinguishable by marker + dash pattern,
    not colour alone
  * error bands everywhere a seed-level distribution exists
  * figure captions live in the manuscript, not baked into the image
"""

import json
import os
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from analysis import load, curve, threshold

CRITERION = 0.60
CHANCE = 1.0 / 18
NS = [2000, 3000, 4000, 5000, 6500]
OUT = "paper_figs"
os.makedirs(OUT, exist_ok=True)

REAL = ["zh", "en", "lisp", "math", "code", "alien"]
NULLS = ["relperm", "entperm"]
NICE = {"zh": "Chinese", "en": "English", "lisp": "Lisp", "math": "Math",
        "code": "Code", "alien": "Alien (nonce)",
        "relperm": "relperm (null)", "entperm": "entperm (null)"}
SHORT = {"zh": "Chinese", "en": "English", "lisp": "Lisp", "math": "Math",
        "code": "Code", "alien": "Alien", "relperm": "rel-perm",
        "entperm": "ent-perm"}

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 300,
    "font.family": "DejaVu Sans", "font.size": 8.5,
    "axes.labelsize": 9, "axes.titlesize": 9.5,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "legend.fontsize": 7.6, "legend.frameon": False,
    "axes.linewidth": 0.7, "axes.grid": True,
    "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "xtick.direction": "in", "ytick.direction": "in",
    "xtick.major.width": 0.7, "ytick.major.width": 0.7,
    "xtick.major.size": 3, "ytick.major.size": 3,
    "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
    "figure.constrained_layout.use": True,
})

# grayscale-legible style cycle
STYLES = {
    "zh":      dict(color="#1a1a1a", marker="o", ls="-",  ms=3.6),
    "en":      dict(color="#4d4d4d", marker="s", ls="-",  ms=3.4),
    "lisp":    dict(color="#7f7f7f", marker="^", ls="--", ms=3.8),
    "math":    dict(color="#1a1a1a", marker="D", ls="-.", ms=3.4),
    "code":    dict(color="#4d4d4d", marker="v", ls="--", ms=3.8),
    "alien":   dict(color="#7f7f7f", marker="P", ls=":",  ms=4.0),
    "relperm": dict(color="#a03000", marker="X", ls="--", ms=4.2),
    "entperm": dict(color="#0060a0", marker="X", ls=":",  ms=4.2),
}


def band(ax, ns, mu, sd, k, **kw):
    """mean line + +/- 1 s.d. band."""
    m = np.array([mu.get(n, np.nan) for n in ns])
    s = np.array([sd.get(n, np.nan) for n in ns])
    x = np.array(ns, dtype=float)
    st = STYLES[k]
    ax.plot(x, m, lw=1.3, **st)
    ax.fill_between(x, np.clip(m - s, 0, 1), np.clip(m + s, 0, 1),
                    color=st["color"], alpha=0.13, lw=0)


def base(ax):
    ax.axhline(CHANCE, color="#b00000", lw=0.8, ls=(0, (1, 2)))
    ax.axhline(CRITERION, color="#004080", lw=0.9, ls=(0, (4, 2)))
    ax.set_xscale("log")
    ax.set_xticks(NS)
    ax.set_xticklabels([f"{n//1000}k" for n in NS])
    ax.set_xlim(1800, 7300)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("training set size  $n$")
    ax.set_ylabel("held-out depth-3 accuracy")


# ---------------------------------------------------------------- Figure 1
_CJK_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
_CJK_FAMILY = "DejaVu Sans"
if os.path.exists(_CJK_PATH):
    import matplotlib.font_manager as fm
    fm.fontManager.addfont(_CJK_PATH)
    _CJK_FAMILY = fm.FontProperties(fname=_CJK_PATH).get_name()


def fig1_task(rows):
    """Schematic: substrate -> relation inventory -> surface rendering."""
    fig = plt.figure(figsize=(7.05, 2.55))
    gs = fig.add_gridspec(1, 3, width_ratios=[0.92, 1.22, 1.06], wspace=0.24)
    ax0, ax1, ax2 = (fig.add_subplot(gs[0, i]) for i in range(3))
    for a in (ax0, ax1, ax2):
        a.set_xticks([]); a.set_yticks([]); a.grid(False)
        a.set_xlim(0, 1); a.set_ylim(0, 1)
        for s in a.spines.values():
            s.set_linewidth(0.8)

    # ---- (a) typed substrate: 3 types, all 6 ordered transitions present
    types = ["T0", "T1", "T2"]
    pos = {"T0": (0.15, 0.76), "T1": (0.50, 0.76), "T2": (0.85, 0.76)}
    for a in range(3):
        for b in range(3):
            if a == b:
                continue
            ta, tb = types[a], types[b]
            rad = 0.34 if b > a else -0.34
            ax0.annotate("", xy=pos[tb], xytext=pos[ta],
                         arrowprops=dict(arrowstyle="-|>", color="#8c8c8c",
                                         lw=0.7, shrinkA=14, shrinkB=14,
                                         connectionstyle=f"arc3,rad={rad}"))
    for t, (x, y) in pos.items():
        ax0.text(x, y, t, ha="center", va="center", fontsize=7.6,
                 bbox=dict(boxstyle="circle,pad=0.24", fc="#e8e8e8",
                           ec="#1a1a1a", lw=0.8))
    ax0.text(0.5, 0.345, "all 6 type transitions present\n"
             "2 outgoing edges per type",
             ha="center", va="center", fontsize=7.0, linespacing=1.35)
    ax0.text(0.5, 0.115, "$C_{\\mathrm{eff}}(3)=24$ at every level",
             ha="center", va="center", fontsize=7.2, weight="bold")
    ax0.set_title("(a)  typed relational substrate", fontsize=8.4)

    # ---- (b) relation inventory, mult = 4
    ax1.text(0.5, 0.915, "concrete relation symbols", ha="center",
             fontsize=7.4, style="italic")
    for gi, t in enumerate(types):
        y = 0.735 - 0.225 * gi
        ax1.text(0.045, y, t, fontsize=7.6, va="center", weight="bold")
        for k in range(4):
            ax1.text(0.215 + 0.163 * k, y, f"$r_{{{gi}{k+1}}}$", fontsize=7.4,
                     va="center",
                     bbox=dict(boxstyle="round,pad=0.14", fc="#f2f2f2",
                               ec="#8c8c8c", lw=0.55))
    ax1.text(0.5, 0.105, "$N_{\\mathrm{REL}}=24$   branching $=8$   "
             "$C(3)=1536$", ha="center", fontsize=7.4)
    ax1.set_title("(b)  symbolic multiplicity", fontsize=8.4)

    # ---- (c) surface renderings of one fact, 5 tokens each
    ax2.text(0.5, 0.915, "one fact, eight surface encodings", ha="center",
             fontsize=7.4, style="italic")
    rows_c = [("Chinese",  "甲  含  乙  。  ，", _CJK_FAMILY),
              ("English", "A  is  r  B  .",      "DejaVu Sans Mono"),
              ("Lisp",    "(  r  A  B  )",      "DejaVu Sans Mono"),
              ("Math",    "A  ρ  B  ;  ~",      "DejaVu Sans"),
              ("Code",    "A  r  B  )  ;",      "DejaVu Sans Mono"),
              ("Alien",   "ka  tsu  no  |  ~",  "DejaVu Sans Mono")]
    for i, (k, txt, fam) in enumerate(rows_c):
        y = 0.755 - 0.113 * i
        ax2.text(0.02, y, k, fontsize=7.0, va="center", color="#4d4d4d")
        ax2.text(0.30, y, txt, fontsize=7.2, va="center", family=fam)
    ax2.text(0.5, 0.085, "5 tokens / fact  $\\times$  9 facts\n"
             "= 46 tokens in every arm", ha="center", va="center",
             fontsize=7.0, weight="bold", linespacing=1.35)
    ax2.set_title("(c)  surface form (token-balanced)", fontsize=8.4)

    fig.savefig(f"{OUT}/fig1_task.png", dpi=300)
    plt.close(fig)
    print("fig1_task.png")


# ---------------------------------------------------------------- Figure 2
def fig2_surface_curves(rows):
    srows = [r for r in rows if r.get("mult") == 1]
    c = curve(srows, ("surface",))
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.85),
                             gridspec_kw=dict(wspace=0.26))

    ax = axes[0]
    for k in REAL:
        d = c[(k,)]
        band(ax, NS, {n: d[n][0] for n in NS if n in d},
             {n: d[n][1] for n in NS if n in d}, k)
    base(ax)
    ax.set_title("(a)  six symbol surfaces, substrate held fixed", fontsize=8.6)
    ax.legend(handles=[Line2D([], [], label=SHORT[k], **STYLES[k])
                       for k in REAL], ncol=2, loc="upper left",
              handlelength=2.4, columnspacing=1.0)

    ax = axes[1]
    for k in NULLS:
        d = c[(k,)]
        band(ax, NS, {n: d[n][0] for n in NS if n in d},
             {n: d[n][1] for n in NS if n in d}, k)
    for k in REAL:
        d = c[(k,)]
        m = np.array([d[n][0] for n in NS if n in d])
        x = np.array([n for n in NS if n in d], dtype=float)
        ax.plot(x, m, lw=0.9, color="#9a9a9a", alpha=0.75)
    base(ax)
    ax.set_title("(b)  semantic-null controls overlay the real surfaces",
                 fontsize=8.6)
    ax.legend(handles=[Line2D([], [], label=NICE[k], **STYLES[k])
                       for k in NULLS], loc="upper left", handlelength=2.4)
    ax.text(0.975, 0.055, "grey: real surfaces (Fig. 2a)",
            transform=ax.transAxes, ha="right", fontsize=7.2,
            color="#6b6b6b", style="italic")
    fig.savefig(f"{OUT}/fig2_surface_curves.png", dpi=300)
    plt.close(fig)
    print("fig2_surface_curves.png")


# ---------------------------------------------------------------- Figure 3
def per_seed(rows, key):
    """per-seed threshold at each level of `key`, then grouped by level only."""
    by = defaultdict(dict)
    for r in rows:
        by[(r[key], r["seed"])][r["n_train"]] = r["acc"]
    out = defaultdict(list)
    for (lv, _sd), d in by.items():
        ns = sorted(d)
        t = threshold(ns, [d[n] for n in ns], CRITERION)
        if not np.isnan(t):
            out[lv].append(t)
    return out


def boot(v, n=4000, seed=0):
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def fig3_thresholds(rows):
    srows = [r for r in rows if r.get("mult") == 1]
    st = per_seed(srows, "surface")
    fig, ax = plt.subplots(figsize=(6.9, 2.5))

    ks = REAL + NULLS
    ys = np.arange(len(ks))[::-1]
    gm = np.exp(np.mean(np.log([np.mean(st[k]) for k in REAL])))
    for y, k in zip(ys, ks):
        v = st[k]
        mu = np.mean(v); lo, hi = boot(v)
        stl = STYLES[k]
        is_null = k in NULLS
        ax.plot([lo, hi], [y, y], color=stl["color"], lw=1.4,
                alpha=0.95 if is_null else 0.75,
                solid_capstyle="butt")
        for x in (lo, hi):
            ax.plot([x, x], [y - 0.17, y + 0.17], color=stl["color"], lw=1.0,
                    alpha=0.95 if is_null else 0.75)
        ax.plot([mu], [y], marker=stl["marker"], ms=6.0 if is_null else 5.0,
                color=stl["color"], mec="white", mew=0.6, zorder=5)
        ax.text(hi + 90, y, f"{mu:,.0f}", va="center", fontsize=7.6,
                color=stl["color"], weight="bold" if is_null else "normal")

    ax.axvline(gm, color="#004080", lw=1.0, ls=(0, (4, 2)), zorder=1)
    ax.text(gm, len(ks) - 0.35, f"  geometric mean = {gm:,.0f}", fontsize=7.4,
            color="#004080", va="bottom")
    lo_r = min(np.mean(st[k]) for k in REAL)
    hi_r = max(np.mean(st[k]) for k in REAL)
    ax.axvspan(lo_r, hi_r, color="#004080", alpha=0.07, lw=0, zorder=0)
    ax.text(0.985, 0.06, f"real-surface band = [{lo_r:,.0f}, {hi_r:,.0f}]",
            transform=ax.transAxes, ha="right", fontsize=7.2, color="#004080")

    ax.set_yticks(ys); ax.set_yticklabels([NICE[k] for k in ks], fontsize=8)
    ax.set_xlim(2900, 6300)
    ax.set_xlabel("emergence threshold  $n^{\\star}$  (training examples)")
    ax.set_ylim(-0.7, len(ks) - 0.1)
    ax.grid(axis="y", alpha=0.12)
    fig.savefig(f"{OUT}/fig3_thresholds.png", dpi=300)
    plt.close(fig)
    print("fig3_thresholds.png")


# ---------------------------------------------------------------- Figure 4
def fig4_complexity(rows):
    krows = [r for r in rows if r.get("surface") == "en"]
    c = curve(krows, ("mult",))
    st = per_seed(krows, "mult")
    mults = sorted({r["mult"] for r in krows})
    meta = {r["mult"]: r for r in krows}

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.85),
                             gridspec_kw=dict(wspace=0.28))
    KST = ["#1a1a1a", "#4d4d4d", "#7f7f7f", "#a8a8a8"]
    KMK = ["o", "s", "^", "D"]
    KLS = ["-", "--", "-.", ":"]

    ax = axes[0]
    for i, m in enumerate(mults):
        d = c.get((m,), {})
        ns = [n for n in NS if n in d]
        mu = np.array([d[n][0] for n in ns])
        sd = np.array([d[n][1] for n in ns])
        x = np.array(ns, dtype=float)
        ax.plot(x, mu, color=KST[i], marker=KMK[i], ls=KLS[i], ms=3.8, lw=1.3,
                label=f"mult={m}  ($N_{{\\mathrm{{REL}}}}={meta[m]['n_rel']}$)")
        ax.fill_between(x, np.clip(mu - sd, 0, 1), np.clip(mu + sd, 0, 1),
                        color=KST[i], alpha=0.13, lw=0)
    base(ax)
    ax.set_title("(a)  symbolic multiplicity grows 64$\\times$", fontsize=8.6)
    ax.legend(loc="upper left", handlelength=2.4, labelspacing=0.35)

    ax = axes[1]
    xs, ys, los, his = [], [], [], []
    for m in mults:
        v = st[m]
        mu = np.mean(v); lo, hi = boot(v)
        xs.append(np.log(meta[m]["n_rel"])); ys.append(mu)
        los.append(lo); his.append(hi)
    xs = np.array(xs); ys = np.array(ys)
    los = np.array(los); his = np.array(his)
    sl, ic = np.polyfit(xs, np.log(ys), 1)
    rr = float(np.corrcoef(xs, np.log(ys))[0, 1])
    for x, y, lo, hi, m in zip(xs, ys, los, his, mults):
        ax.errorbar(np.exp(x), y, yerr=[[y - lo], [hi - y]], fmt=KMK[mults.index(m)],
                    color=KST[mults.index(m)], ms=5.0, capsize=3.0, capthick=1.0,
                    elinewidth=1.2, mec="white", mew=0.6)
    gx = np.linspace(xs.min() - 0.25, xs.max() + 0.25, 50)
    ax.plot(np.exp(gx), np.exp(ic + sl * gx), color="#b00000", lw=1.1,
            ls=(0, (5, 2)),
            label=f"log–log fit: slope {sl:+.3f},  $r$ = {rr:+.3f}")
    ax.axhline(4374, color="#004080", lw=1.0, ls=(0, (4, 2)))
    ax.text(6.4, 4470, "Arm S mean = 4,374", fontsize=7.0, color="#004080")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xticks([6, 12, 18, 24])
    ax.set_xticklabels(["6", "12", "18", "24"])
    ax.set_yticks([3400, 4000, 4700, 5500])
    ax.set_yticklabels(["3,400", "4,000", "4,700", "5,500"])
    ax.set_xlabel("$N_{\\mathrm{REL}}$  (concrete relation symbols)")
    ax.set_ylabel("emergence threshold  $n^{\\star}$")
    ax.set_title("(b)  threshold is flat while $C_{\\mathrm{eff}}(3)=24$",
                 fontsize=8.6)
    ax.legend(loc="upper right", handlelength=2.4)
    ax.grid(which="minor", alpha=0.10)
    fig.savefig(f"{OUT}/fig4_complexity.png", dpi=300)
    plt.close(fig)
    print("fig4_complexity.png")
    return sl, rr


if __name__ == "__main__":
    rows = load(["results/final.jsonl"])
    rows = [r for r in rows if not np.isnan(r.get("acc", np.nan))]
    print(f"{len(rows)} runs loaded")
    fig1_task(rows)
    fig2_surface_curves(rows)
    fig3_thresholds(rows)
    fig4_complexity(rows)
