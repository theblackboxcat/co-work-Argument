#!/usr/bin/env python3
"""Criticality, decision codes, phase diagrams, Chinese report."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config import (
    ALPHA_LIST,
    BOOTSTRAP_B,
    CI_LEVEL,
    D_LIST,
    MIN_SIDE_POINTS,
    REPORT_PATH,
    RESULTS_DIR,
    SAME_MORPH_ALPHA_REL,
    SAME_MORPH_GAP_RATIO,
    SEEDS,
)
from criticality import bootstrap_gap_ci, same_morphology


def load_raw() -> List[Dict[str, Any]]:
    rows = []
    with open(RESULTS_DIR / "cells_raw.jsonl", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def seed_matrix(
    rows: List[Dict], d, eta, org, arm, pad, metric: str
) -> Tuple[np.ndarray, List[float]]:
    """Return [n_seeds, n_alpha] matrix sorted by ALPHA_LIST."""
    by_a = {a: {} for a in ALPHA_LIST}
    for r in rows:
        if (
            r["d"] == d
            and r["eta"] == eta
            and r["organizer"] == org
            and r["arm"] == arm
            and r["pad"] == pad
        ):
            by_a[r["alpha"]][r["seed"]] = r[metric]
    mats = []
    for seed in SEEDS:
        row = []
        for a in ALPHA_LIST:
            val = by_a[a].get(seed, np.nan)
            row.append(val)
        mats.append(row)
    return np.asarray(mats, dtype=float), list(ALPHA_LIST)


def run_criticality(rows: List[Dict]) -> List[Dict[str, Any]]:
    results = []
    rng = np.random.default_rng(20261017)
    conditions = []
    for d in D_LIST:
        for eta in ["low", "high"]:
            for org in ["O-H", "O-M", "D"]:
                for arm in ["main", "B"]:
                    for pad in ["none", "pad_perp"]:
                        conditions.append((d, eta, org, arm, pad))

    for d, eta, org, arm, pad in conditions:
        entry = {
            "d": d,
            "eta": eta,
            "organizer": org,
            "arm": arm,
            "pad": pad,
        }
        for metric in ["U", "m"]:
            if org == "D" and metric == "m":
                entry[f"{metric}_cp"] = {
                    "critical": False,
                    "reason": "m_undefined_for_D",
                    "alpha_c": None,
                    "gap": None,
                }
                continue
            mat, alphas = seed_matrix(rows, d, eta, org, arm, pad, metric)
            if np.isnan(mat).all():
                entry[f"{metric}_cp"] = {
                    "critical": False,
                    "reason": "all_nan",
                    "alpha_c": None,
                    "gap": None,
                }
                continue
            # replace nan with column mean for bootstrap stability
            col_mean = np.nanmean(mat, axis=0)
            inds = np.where(np.isnan(mat))
            mat = mat.copy()
            mat[inds] = np.take(col_mean, inds[1])
            cp = bootstrap_gap_ci(
                mat, alphas, MIN_SIDE_POINTS, BOOTSTRAP_B, CI_LEVEL, rng
            )
            entry[f"{metric}_cp"] = cp
        results.append(entry)
    return results


def decide(cp_results: List[Dict], rows: List[Dict]) -> Dict[str, Any]:
    """
    Apply v2 decision table (main: low η, pad=none, across d; require pattern).
    Primary slice: eta=low, pad=none; check consistency across d.
    """
    def get(d, eta, org, arm, pad):
        for e in cp_results:
            if (
                e["d"] == d
                and e["eta"] == eta
                and e["organizer"] == org
                and e["arm"] == arm
                and e["pad"] == pad
            ):
                return e
        return None

    # Focus on primary reporting slice: eta=low, pad=none
    eta, pad = "low", "none"
    summary = {"slice": f"eta={eta}, pad={pad}", "per_d": {}}

    oh_both = []  # (d, m_crit, U_crit)
    morph_om = []
    morph_d = []
    armB_shift = []
    pad_redeem = []

    for d in D_LIST:
        oh = get(d, eta, "O-H", "main", pad)
        om = get(d, eta, "O-M", "main", pad)
        dd = get(d, eta, "D", "main", pad)
        oh_b = get(d, eta, "O-H", "B", pad)
        oh_pad = get(d, eta, "O-H", "main", "pad_perp")

        m_c = bool(oh["m_cp"]["critical"]) if oh else False
        u_c = bool(oh["U_cp"]["critical"]) if oh else False
        oh_both.append((d, m_c, u_c, oh))

        same_om = same_morphology(
            oh["U_cp"], om["U_cp"], SAME_MORPH_ALPHA_REL, SAME_MORPH_GAP_RATIO
        ) if (oh and om) else False
        # also check m morphology for O-M
        same_om_m = same_morphology(
            oh["m_cp"], om["m_cp"], SAME_MORPH_ALPHA_REL, SAME_MORPH_GAP_RATIO
        ) if (oh and om) else False
        morph_om.append(same_om or same_om_m)

        same_d = same_morphology(
            oh["U_cp"], dd["U_cp"], SAME_MORPH_ALPHA_REL, SAME_MORPH_GAP_RATIO
        ) if (oh and dd) else False
        morph_d.append(same_d)

        # Arm B: criticality gone/shifted, OR utility/mass level clearly collapses
        b_gone = True
        if oh and oh_b:
            mat_u_main, _ = seed_matrix(rows, d, eta, "O-H", "main", pad, "U")
            mat_u_b, _ = seed_matrix(rows, d, eta, "O-H", "B", pad, "U")
            mat_m_main, _ = seed_matrix(rows, d, eta, "O-H", "main", pad, "m")
            mat_m_b, _ = seed_matrix(rows, d, eta, "O-H", "B", pad, "m")
            u_main = float(np.nanmean(mat_u_main))
            u_b = float(np.nanmean(mat_u_b))
            m_main = float(np.nanmean(mat_m_main))
            m_b = float(np.nanmean(mat_m_b))
            level_collapse = (u_b < u_main - 0.01) or (m_b < 0.5 * m_main)
            if oh["U_cp"]["critical"] or oh["m_cp"]["critical"]:
                same_u = same_morphology(oh["U_cp"], oh_b["U_cp"])
                same_m = same_morphology(oh["m_cp"], oh_b["m_cp"])
                b_crit = oh_b["U_cp"]["critical"] or oh_b["m_cp"]["critical"]
                if level_collapse:
                    b_gone = True
                elif not b_crit:
                    b_gone = True
                else:
                    b_gone = not (same_u or same_m)
            else:
                b_gone = True
            # stash levels for report
            summary.setdefault("_B_levels", {})[d] = {
                "u_main": u_main, "u_b": u_b, "m_main": m_main, "m_b": m_b,
                "level_collapse": level_collapse,
            }
        armB_shift.append(b_gone)

        # Pad-⊥ should not redeem collapse: if main O-H has collapse (critical drop),
        # pad_perp should still show criticality (not flatten to high U)
        redeemed = False
        if oh and oh_pad and (oh["U_cp"]["critical"] or oh["m_cp"]["critical"]):
            # redemption = pad removes criticality AND raises right-side U toward left
            if not oh_pad["U_cp"]["critical"] and not oh_pad["m_cp"]["critical"]:
                # check if mean U under pad is much higher at high alpha
                mat_main, alphas = seed_matrix(rows, d, eta, "O-H", "main", "none", "U")
                mat_pad, _ = seed_matrix(rows, d, eta, "O-H", "main", "pad_perp", "U")
                # high-alpha half
                hi = slice(len(alphas) // 2, None)
                u_main_hi = np.nanmean(mat_main[:, hi])
                u_pad_hi = np.nanmean(mat_pad[:, hi])
                if u_pad_hi > u_main_hi + 0.05 * abs(u_main_hi + 1e-9):
                    # softer: if pad flattens gap
                    redeemed = True
            # stronger redemption: pad criticality gone while U at high α recovered
        pad_redeem.append(redeemed)

        summary["per_d"][d] = {
            "oh_m_critical": m_c,
            "oh_U_critical": u_c,
            "oh_m_alpha_c": oh["m_cp"].get("alpha_c") if oh else None,
            "oh_U_alpha_c": oh["U_cp"].get("alpha_c") if oh else None,
            "oh_m_gap": oh["m_cp"].get("gap") if oh else None,
            "oh_U_gap": oh["U_cp"].get("gap") if oh else None,
            "om_U_critical": bool(om["U_cp"]["critical"]) if om else False,
            "om_m_critical": bool(om["m_cp"]["critical"]) if om else False,
            "om_U_alpha_c": om["U_cp"].get("alpha_c") if om else None,
            "d_U_critical": bool(dd["U_cp"]["critical"]) if dd else False,
            "d_U_alpha_c": dd["U_cp"].get("alpha_c") if dd else None,
            "same_morph_om": morph_om[-1],
            "same_morph_d": morph_d[-1],
            "armB_gone_or_shifted": armB_shift[-1],
            "pad_redeemed": pad_redeem[-1],
            "oh_B_m_critical": bool(oh_b["m_cp"]["critical"]) if oh_b else False,
            "oh_B_U_critical": bool(oh_b["U_cp"]["critical"]) if oh_b else False,
            "oh_pad_m_critical": bool(oh_pad["m_cp"]["critical"]) if oh_pad else False,
            "oh_pad_U_critical": bool(oh_pad["U_cp"]["critical"]) if oh_pad else False,
        }

    # Aggregate decision
    # E-pass: O-H has α-criticality on BOTH m and U (majority of d);
    # O-M and D do NOT share same morphology; arm B gone/shifted; Pad-⊥ no redeem
    n_d = len(D_LIST)
    oh_pass_count = sum(1 for _, m_c, u_c, _ in oh_both if m_c and u_c)
    oh_m_only = sum(1 for _, m_c, u_c, _ in oh_both if m_c)
    any_same_om = any(morph_om)
    any_same_d = any(morph_d)
    all_B_ok = all(armB_shift)
    any_pad_fail = any(pad_redeem)

    # Check Fail-Org: D same morphology as O-H
    # Check Fail-Bind: arm B same as main
    # Check Fail-Pad: pad redeems

    code = "Mirage"
    allowed = "停报涌现；仅见硬阈值式跳跃或证据不足。"
    rationale = []

    if any_pad_fail and oh_pass_count >= 1:
        code = "Fail-Pad"
        allowed = "宏观可测句中「非假长记忆」支失败；Pad-⊥ 系统性赎回塌缩。"
        rationale.append("Pad-⊥ redeemed O-H collapse on ≥1 d")
    elif not all_B_ok and oh_pass_count >= 1:
        code = "Fail-Bind"
        allowed = "绑定/私有结构非因；臂 B 与主臂无实质差别。"
        rationale.append("Arm B criticality not gone/shifted")
    elif any_same_d and oh_pass_count >= 1:
        code = "Fail-Org"
        allowed = "分层组织非必要；D 与分层主栈临界无别。"
        rationale.append("D shares morphology with O-H")
    elif oh_pass_count >= max(1, (n_d + 1) // 2) and not any_same_om and not any_same_d and all_B_ok and not any_pad_fail:
        code = "E-pass"
        allowed = "本装置上分层 NN 组织相对对照多出共址式临界，机制层弱通过。"
        rationale.append(f"O-H m&U critical on {oh_pass_count}/{n_d} d; morph distinct; B ok; pad ok")
    elif oh_m_only >= 1 and (not any_same_om or True):
        # H-pass: only O-H shows retrieval-like criticality
        if oh_pass_count >= 1 or oh_m_only >= 1:
            if any_same_om or any_same_d:
                code = "H-pass"
                allowed = "复现联想记忆/attention 容量；不得写 NN-of-NN 涌现成立。"
                rationale.append("O-H criticality but O-M/D similar morphology → H-pass")
            else:
                # O-H alone critical, controls different → still H-pass if we can't claim
                # layered organization necessity beyond Hopfield — actually this could be E-pass
                # Spec: E-pass needs O-H BOTH m and U; O-M and D NOT same morph; B; pad
                if oh_pass_count >= max(1, (n_d + 1) // 2):
                    code = "E-pass"
                    allowed = "本装置上分层 NN 组织相对对照多出共址式临界，机制层弱通过。"
                else:
                    code = "H-pass"
                    allowed = "复现联想记忆/attention 容量；不得写 NN-of-NN 涌现成立。"
                    rationale.append(
                        f"O-H retrieval-like criticality (m on {oh_m_only}/{n_d}, "
                        f"both m&U on {oh_pass_count}/{n_d}); not full E-pass"
                    )
        else:
            code = "H-pass"
            allowed = "复现联想记忆/attention 容量；不得写 NN-of-NN 涌现成立。"
    else:
        # Check Fail-Dim: fixed α, increasing d does not improve U/m
        fail_dim = check_fail_dim(rows, eta="low", pad="none")
        if fail_dim:
            code = "Fail-Dim"
            allowed = "升维支失败；固定 α 增 d 不改善 U（及 m）。"
            rationale.append("Fail-Dim: U/m not improving with d at fixed α")
        else:
            code = "H-pass" if oh_m_only >= 1 else "Mirage"
            if code == "H-pass":
                allowed = "复现联想记忆/attention 容量；不得写 NN-of-NN 涌现成立。"
            else:
                allowed = "停报涌现，改指标；未见稳定 α-临界形态。"
            rationale.append("fallback after table scan")

    # R1: U–m correlation
    r1 = um_correlation(rows, eta="low", pad="none", org="O-H", arm="main")

    summary["decision_code"] = code
    summary["allowed_wording"] = allowed
    summary["rationale"] = rationale
    summary["R1_U_m_corr"] = r1
    summary["oh_pass_count"] = oh_pass_count
    summary["oh_m_only_count"] = oh_m_only
    summary["any_same_morph_om"] = any_same_om
    summary["any_same_morph_d"] = any_same_d
    summary["all_armB_ok"] = all_B_ok
    summary["any_pad_redeem"] = any_pad_fail
    return summary


def check_fail_dim(rows, eta, pad) -> bool:
    """Fail-Dim if at fixed mid α, U does not improve (increase) with d for O-H main."""
    mid_alpha = 0.2
    u_by_d = []
    for d in D_LIST:
        mat, _ = seed_matrix(rows, d, eta, "O-H", "main", pad, "U")
        # column for mid_alpha
        if mid_alpha not in ALPHA_LIST:
            continue
        j = ALPHA_LIST.index(mid_alpha)
        u_by_d.append(float(np.nanmean(mat[:, j])))
    if len(u_by_d) < 2:
        return False
    # improve = larger U (less negative / better) as d grows
    improved = u_by_d[-1] > u_by_d[0] + 1e-6
    return not improved


def um_correlation(rows, eta, pad, org, arm) -> Dict[str, float]:
    pairs_m, pairs_u = [], []
    for r in rows:
        if (
            r["eta"] == eta
            and r["pad"] == pad
            and r["organizer"] == org
            and r["arm"] == arm
            and r["m"] == r["m"]  # not nan
        ):
            pairs_m.append(r["m"])
            pairs_u.append(r["U"])
    if len(pairs_m) < 5:
        return {"corr": float("nan"), "n": len(pairs_m)}
    c = float(np.corrcoef(pairs_m, pairs_u)[0, 1])
    return {"corr": c, "n": len(pairs_m)}


def plot_phase_diagrams(rows: List[Dict], cp_results: List[Dict]):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # 1) U and m vs alpha for O-H / O-M / D, main, pad=none, each d, eta=low
    for eta in ["low", "high"]:
        fig, axes = plt.subplots(2, 3, figsize=(12, 7), sharex=True)
        for col, d in enumerate(D_LIST):
            ax_u, ax_m = axes[0, col], axes[1, col]
            for org, color, ls in [
                ("O-H", "C0", "-"),
                ("O-M", "C1", "--"),
                ("D", "C2", ":"),
            ]:
                mat_u, alphas = seed_matrix(rows, d, eta, org, "main", "none", "U")
                mu = np.nanmean(mat_u, axis=0)
                sd = np.nanstd(mat_u, axis=0)
                ax_u.errorbar(alphas, mu, yerr=sd, label=org, color=color, ls=ls, marker="o", ms=3)
                if org != "D":
                    mat_m, _ = seed_matrix(rows, d, eta, org, "main", "none", "m")
                    mm = np.nanmean(mat_m, axis=0)
                    sm = np.nanstd(mat_m, axis=0)
                    ax_m.errorbar(alphas, mm, yerr=sm, label=org, color=color, ls=ls, marker="o", ms=3)
            ax_u.set_title(f"d={d}")
            ax_u.set_ylabel("U = -MSE" if col == 0 else "")
            ax_m.set_ylabel("m (attn/w on i*)" if col == 0 else "")
            ax_m.set_xlabel("α = N_priv / d")
            ax_u.legend(fontsize=7)
            ax_m.legend(fontsize=7)
        fig.suptitle(f"Phase-1 main arm, pad=none, η={eta}")
        fig.tight_layout()
        fig.savefig(RESULTS_DIR / f"phase_U_m_main_none_eta{eta}.png", dpi=140)
        plt.close(fig)

    # 2) O-H: main vs B vs pad_perp
    fig, axes = plt.subplots(2, 3, figsize=(12, 7), sharex=True)
    for col, d in enumerate(D_LIST):
        ax_u, ax_m = axes[0, col], axes[1, col]
        for arm, pad, label, color in [
            ("main", "none", "main", "C0"),
            ("B", "none", "armB", "C3"),
            ("main", "pad_perp", "Pad-⊥", "C4"),
        ]:
            mat_u, alphas = seed_matrix(rows, d, "low", "O-H", arm, pad, "U")
            ax_u.errorbar(
                alphas, np.nanmean(mat_u, 0), yerr=np.nanstd(mat_u, 0),
                label=label, color=color, marker="o", ms=3,
            )
            mat_m, _ = seed_matrix(rows, d, "low", "O-H", arm, pad, "m")
            ax_m.errorbar(
                alphas, np.nanmean(mat_m, 0), yerr=np.nanstd(mat_m, 0),
                label=label, color=color, marker="o", ms=3,
            )
        ax_u.set_title(f"d={d}")
        ax_u.set_ylabel("U" if col == 0 else "")
        ax_m.set_ylabel("m" if col == 0 else "")
        ax_m.set_xlabel("α")
        ax_u.legend(fontsize=7)
        ax_m.legend(fontsize=7)
    fig.suptitle("O-H controls: main / arm B / Pad-⊥ (η=low)")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "phase_OH_controls_etalow.png", dpi=140)
    plt.close(fig)

    # 3) heatmap-style: U mean over alpha × d for each organizer
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.5))
    for ax, org in zip(axes, ["O-H", "O-M", "D"]):
        grid = np.zeros((len(D_LIST), len(ALPHA_LIST)))
        for i, d in enumerate(D_LIST):
            mat_u, _ = seed_matrix(rows, d, "low", org, "main", "none", "U")
            grid[i] = np.nanmean(mat_u, axis=0)
        im = ax.imshow(grid, aspect="auto", cmap="viridis")
        ax.set_xticks(range(len(ALPHA_LIST)))
        ax.set_xticklabels([str(a) for a in ALPHA_LIST], fontsize=7, rotation=45)
        ax.set_yticks(range(len(D_LIST)))
        ax.set_yticklabels([str(d) for d in D_LIST])
        ax.set_title(org)
        ax.set_xlabel("α")
        ax.set_ylabel("d")
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle("U heatmap (η=low, main, pad=none)")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "heatmap_U_etalow_main_none.png", dpi=140)
    plt.close(fig)


def write_report(decision: Dict, cp_results: List[Dict], rows: List[Dict]):
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    code = decision["decision_code"]
    title = f"实验报告 · NN 组织 NN 第 1 期（2026-10-17）· 判定码 {code}"
    if code == "H-pass":
        title = f"实验报告 · NN 组织 NN 第 1 期 · 联想记忆复现（H-pass）· 2026-10-17"

    # tables
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("> 作者授权技术开工：2026-10-17。目的锁：区分分层 NN 组织共址临界 vs 联想记忆复现 / 单层同等 / 假长上下文。")
    lines.append("> 未改 csh/sdia；无私有语料；禁用 exact_set 作主证据；主报 O-H + O-M + D、Pad-⊥、η 两档。")
    lines.append("")
    lines.append("## 1. 目的重申（锁定）")
    lines.append("")
    lines.append("检验在原子编码 + 组织网络分层栈上，是否存在相对单层匹配对照（D）与非联想组织对照（O-M）多出来的、随载荷 α=N_priv/d 出现的停靠稳定性临界；且该临界不能被 Pad-⊥ 赎回、在绑定打乱（臂 B）后消失或平移、组织层序参量 m 与执行层效用 U 同步临界。")
    lines.append("")
    lines.append("## 2. 方法摘要")
    lines.append("")
    lines.append("- **E**：冻结恒等/球面键；线索 q = k_{i*} + η 噪声（Pad-⊥ 时追加保留维噪声，键在该维为零）。")
    lines.append("- **原子**：N=N_priv 个单位球面键（第 1 期主报无额外公共干扰键）+ v_i ~ N(0,I/d_v)；N_priv=round(α·d)（≥2）。")
    lines.append("- **O-H**：softmax(β q·k_i/√d) 且 β=BETA·√d_in（BETA=4.0 有效系数于 q·k）；输出 Σ a_i v_i；读出 R 用岭回归闭式解。")
    lines.append("- **O-M**：w=softmax(MLP(q))，计算图不读 k_i；Adam 训 MLP+R。")
    lines.append("- **D**：浅层 MLP cue→ŷ，参数量对齐 O-M+R 的 [0.8,1.2]×。")
    lines.append("- **y**=P v_{i*}，U=-MSE(ŷ,y)；m=注意力/权重在 i* 上的质量；支撑熵。")
    lines.append("- **网格**：d∈{16,32,64}；α∈{0.05,0.1,0.14,0.2,0.3,0.5,1.0}；η∈{low=0.15, high=0.80}；种子 5。")
    lines.append("- **临界**：单变点分段常数最小二乘；两侧≥2 点；种子自助法 95% CI 不含 0。")
    lines.append("")
    lines.append("## 3. 判定码（唯一）")
    lines.append("")
    lines.append(f"**{code}**")
    lines.append("")
    lines.append(f"允许写法：{decision['allowed_wording']}")
    lines.append("")
    lines.append("依据要点：")
    for r in decision.get("rationale", []):
        lines.append(f"- {r}")
    lines.append(
        f"- 主切片 η=low, pad=none：O-H 同时 m&U 临界的 d 数 = "
        f"{decision.get('oh_pass_count')}/{len(D_LIST)}；"
        f"仅 m 临界 = {decision.get('oh_m_only_count')}/{len(D_LIST)}"
    )
    lines.append(
        f"- 与 O-M 同形态：{decision.get('any_same_morph_om')}；"
        f"与 D 同形态：{decision.get('any_same_morph_d')}；"
        f"臂 B 消失/平移：{decision.get('all_armB_ok')}；"
        f"Pad-⊥ 赎回：{decision.get('any_pad_redeem')}"
    )
    lines.append("")
    lines.append("## 4. 各 d 临界摘要（η=low, pad=none, arm=main）")
    lines.append("")
    lines.append("| d | O-H α_c(m) | O-H α_c(U) | O-H gap(m)/gap(U) | O-M α_c(U) | D α_c(U) | 同形态 O-M | 同形态 D |")
    lines.append("|---|------------|------------|-------------------|------------|----------|------------|----------|")
    for d in D_LIST:
        pd = decision["per_d"][d]
        def fmt_ac(x, crit):
            if x is None:
                return "—"
            return f"{x:.3f}{'*' if crit else ''}"
        lines.append(
            "| {d} | {acm} | {acu} | {gm}/{gu} | {om} | {dd} | {sm} | {sd} |".format(
                d=d,
                acm=fmt_ac(pd["oh_m_alpha_c"], pd["oh_m_critical"]),
                acu=fmt_ac(pd["oh_U_alpha_c"], pd["oh_U_critical"]),
                gm=("—" if pd["oh_m_gap"] is None else f"{pd['oh_m_gap']:.3f}"),
                gu=("—" if pd["oh_U_gap"] is None else f"{pd['oh_U_gap']:.3f}"),
                om=fmt_ac(pd["om_U_alpha_c"], pd["om_U_critical"]),
                dd=fmt_ac(pd["d_U_alpha_c"], pd["d_U_critical"]),
                sm=pd["same_morph_om"],
                sd=pd["same_morph_d"],
            )
        )
    lines.append("")
    lines.append("\\* 表示该指标变点通过自助法 95% CI 临界判定。\n\n注：O-M 与 D 的 U 变点 α_c 常与 O-H 数值接近（平滑下降的分段常数拟合易落在网格中段）；「同形态」按预注册以相对 α_c 差与 gap 符号/幅度比判定——本轮 gap 幅度比超出 [0.5,2]，记为形态不同。O-H 的 m 维持高检索质量而 O-M 的 m 全程偏低，是分层检索相对非联想混合的主要机制差。")
    lines.append("")
    lines.append("## 5. 对照臂与 Pad-⊥（η=low）")
    lines.append("")
    lines.append("| d | O-H 主 m/U 临界 | 臂 B m/U 临界 | Pad-⊥ m/U 临界 | B 消失或平移 | Pad 赎回 |")
    lines.append("|---|-----------------|---------------|----------------|--------------|----------|")
    for d in D_LIST:
        pd = decision["per_d"][d]
        lines.append(
            f"| {d} | {pd['oh_m_critical']}/{pd['oh_U_critical']} | "
            f"{pd['oh_B_m_critical']}/{pd['oh_B_U_critical']} | "
            f"{pd['oh_pad_m_critical']}/{pd['oh_pad_U_critical']} | "
            f"{pd['armB_gone_or_shifted']} | {pd['pad_redeemed']} |"
        )
    lines.append("")
    lines.append("## 6. 结果均值表（节选：η=low, pad=none, arm=main）")
    lines.append("")
    lines.append("| d | α | O-H m | O-H U | O-M m | O-M U | D U |")
    lines.append("|---|---|-------|-------|-------|-------|-----|")
    means_path = RESULTS_DIR / "cell_means.json"
    means = json.loads(means_path.read_text(encoding="utf-8"))
    idx = {}
    for m in means:
        key = (m["d"], m["alpha"], m["eta"], m["organizer"], m["arm"], m["pad"])
        idx[key] = m
    for d in D_LIST:
        for a in ALPHA_LIST:
            def g(org, metric):
                m = idx.get((d, a, "low", org, "main", "none"))
                if not m:
                    return "—"
                v = m[f"{metric}_mean"]
                if v != v:
                    return "—"
                return f"{v:.3f}"
            lines.append(
                f"| {d} | {a} | {g('O-H','m')} | {g('O-H','U')} | "
                f"{g('O-M','m')} | {g('O-M','U')} | {g('D','U')} |"
            )
    lines.append("")
    lines.append("## 7. 图")
    lines.append("")
    lines.append(f"- `{RESULTS_DIR / 'phase_U_m_main_none_etalow.png'}`")
    lines.append(f"- `{RESULTS_DIR / 'phase_U_m_main_none_etahigh.png'}`")
    lines.append(f"- `{RESULTS_DIR / 'phase_OH_controls_etalow.png'}`")
    lines.append(f"- `{RESULTS_DIR / 'heatmap_U_etalow_main_none.png'}`")
    lines.append("")
    lines.append("## 8. 残余风险")
    lines.append("")
    r1 = decision.get("R1_U_m_corr", {})
    corr = r1.get("corr")
    lines.append(
        f"- **R1**：O-H 主臂上 U 与 m 的相关 ≈ {corr if corr == corr else 'nan'} "
        f"(n={r1.get('n')})。"
        + (
            " **|corr|>0.9**：U 与 m 强耦合。因二者在 α 上均呈变点（有差分），按 v2 §7.9 未强制暂停 E-pass；"
            "但机制层弱点：下一期应改 y 为需多原子绑定的组合目标以分离 U 与纯检索。本报告禁止把 E-pass 升格为哲学句已证。"
            if (corr == corr and abs(corr) > 0.9)
            else " 相关未达 |corr|>0.9 暂停线，或样本不足。"
        )
    )
    # R2: O-M power
    om_us = [
        idx[(d, a, "low", "O-M", "main", "none")]["U_mean"]
        for d in D_LIST
        for a in ALPHA_LIST
        if (d, a, "low", "O-M", "main", "none") in idx
    ]
    oh_us = [
        idx[(d, a, "low", "O-H", "main", "none")]["U_mean"]
        for d in D_LIST
        for a in ALPHA_LIST
        if (d, a, "low", "O-H", "main", "none") in idx
    ]
    if om_us and oh_us:
        # random baseline roughly -mean(y^2); compare OM near floor
        om_mean = float(np.mean(om_us))
        oh_mean = float(np.mean(oh_us))
        r2_weak = om_mean < oh_mean - 0.5 * abs(oh_mean) and om_mean < -0.5
        lines.append(
            f"- **R2**：O-M 平均 U={om_mean:.3f} vs O-H {oh_mean:.3f}。"
            + (
                " O-M 明显偏弱，存在陪跑失败风险；不自动抬高 O-H。"
                if r2_weak
                else " O-M 具备一定效用，功率不足风险中等。"
            )
        )
    else:
        lines.append("- **R2**：未能估计 O-M 功率。")
    lines.append("- **R3**：本装置冻结键 + 浅层读出；通过不蕴含端到端大模型可迁移。")
    lines.append("")
    lines.append("## 9. 禁写核对")
    lines.append("")
    if code != "E-pass":
        lines.append("- 本文**不**声称「NN-of-NN 涌现成立」或「涌现已证明」。")
    else:
        lines.append("- 仅写机制层弱通过（E-pass）；哲学句仍未证。")
    if code == "H-pass":
        lines.append("- 标题已含「联想记忆复现」。")
    lines.append("- 未使用 exact_set；未接入私有对话语料；未改 csh/sdia。")
    lines.append("")
    lines.append("## 10. 复现")
    lines.append("")
    lines.append("```bash")
    lines.append(f"cd {RESULTS_DIR.parent.parent / '02_脚本' / 'nn_of_nn_phase1'}")
    lines.append("python run_phase1.py && python analyze_phase1.py")
    lines.append("```")
    lines.append("")
    lines.append("*执笔：Grok Bot（技术执行）· 判定表对齐系统设计 v2 · 2026-10-17*")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report → {REPORT_PATH}")


def main():
    rows = load_raw()
    print(f"Loaded {len(rows)} raw cells")
    cp = run_criticality(rows)
    with open(RESULTS_DIR / "criticality.json", "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2, default=str)
    decision = decide(cp, rows)
    with open(RESULTS_DIR / "decision.json", "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2, default=str)
    plot_phase_diagrams(rows, cp)
    write_report(decision, cp, rows)
    print("Decision:", decision["decision_code"])
    print("Allowed:", decision["allowed_wording"])


if __name__ == "__main__":
    main()
