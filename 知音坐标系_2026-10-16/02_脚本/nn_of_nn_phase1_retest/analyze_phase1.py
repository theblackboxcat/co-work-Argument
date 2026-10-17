#!/usr/bin/env python3
"""Retest analysis: criticality, arm-B m-drop apparatus check, R1 gate, report."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config import (
    ALPHA_LIST,
    ARM_B_M_DROP_CELL_FRAC,
    ARM_B_M_DROP_FRAC,
    BOOTSTRAP_B,
    CI_LEVEL,
    D_LIST,
    MIN_SIDE_POINTS,
    R1_CORR_CAP,
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


def arm_b_m_drop_table(rows: List[Dict], eta: str = "low", pad: str = "none", org: str = "O-H") -> Dict[str, Any]:
    """Per (d,α) cell: main m vs arm-B m; pass if m_B < ARM_B_M_DROP_FRAC * m_main.

    Eligibility: only cells with n_priv >= 4. When N=N_priv and n_priv<=3,
    m = mass on {i*,j*} cannot fall below ~0.5–1 by construction (no disjoint
    wrong pair / no outside atoms). Those cells are reported but excluded from
    the apparatus pass_frac (structural non-identifiability, not soft-shuffle).
    """
    means_path = RESULTS_DIR / "cell_means.json"
    means = json.loads(means_path.read_text(encoding="utf-8"))
    idx = {}
    for m in means:
        key = (m["d"], m["alpha"], m["eta"], m["organizer"], m["arm"], m["pad"])
        idx[key] = m

    cells = []
    n_pass = 0
    n_total = 0
    n_excluded = 0
    for d in D_LIST:
        for a in ALPHA_LIST:
            main = idx.get((d, a, eta, org, "main", pad))
            b = idx.get((d, a, eta, org, "B", pad))
            if not main or not b:
                continue
            n_priv = int(main["n_priv"])
            m_main = main["m_mean"]
            m_b = b["m_mean"]
            ratio = (m_b / m_main) if (m_main == m_main and m_main > 1e-12) else float("nan")
            eligible = n_priv >= 4
            passed = (m_b == m_b and m_main == m_main and m_b < ARM_B_M_DROP_FRAC * m_main)
            if not eligible:
                n_excluded += 1
            else:
                n_total += 1
                if passed:
                    n_pass += 1
            cells.append({
                "d": d,
                "alpha": a,
                "n_priv": n_priv,
                "eligible_npriv_ge4": eligible,
                "m_main": m_main,
                "m_B": m_b,
                "ratio_B_over_main": ratio,
                "pass_lt_50pct": passed if eligible else False,
                "structural_exclude": not eligible,
                "U_main": main["U_mean"],
                "U_B": b["U_mean"],
            })
    frac = n_pass / max(n_total, 1)
    apparatus_ok = (n_total > 0) and (frac >= ARM_B_M_DROP_CELL_FRAC)
    return {
        "eta": eta,
        "pad": pad,
        "organizer": org,
        "threshold_frac": ARM_B_M_DROP_FRAC,
        "cell_pass_frac_required": ARM_B_M_DROP_CELL_FRAC,
        "eligible_rule": "n_priv>=4",
        "n_pass": n_pass,
        "n_total": n_total,
        "n_structural_exclude": n_excluded,
        "pass_frac": frac,
        "apparatus_ok": apparatus_ok,
        "cells": cells,
    }


def um_correlation(rows, eta, pad, org, arm) -> Dict[str, float]:
    pairs_m, pairs_u = [], []
    for r in rows:
        if (
            r["eta"] == eta
            and r["pad"] == pad
            and r["organizer"] == org
            and r["arm"] == arm
            and r["m"] == r["m"]
        ):
            pairs_m.append(r["m"])
            pairs_u.append(r["U"])
    if len(pairs_m) < 5:
        return {"corr": float("nan"), "n": len(pairs_m)}
    c = float(np.corrcoef(pairs_m, pairs_u)[0, 1])
    return {"corr": c, "n": len(pairs_m)}


def check_fail_dim(rows, eta, pad) -> bool:
    mid_alpha = 0.2
    u_by_d = []
    for d in D_LIST:
        mat, _ = seed_matrix(rows, d, eta, "O-H", "main", pad, "U")
        if mid_alpha not in ALPHA_LIST:
            continue
        j = ALPHA_LIST.index(mid_alpha)
        u_by_d.append(float(np.nanmean(mat[:, j])))
    if len(u_by_d) < 2:
        return False
    improved = u_by_d[-1] > u_by_d[0] + 1e-6
    return not improved


def decide(cp_results: List[Dict], rows: List[Dict], drop: Dict[str, Any]) -> Dict[str, Any]:
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

    eta, pad = "low", "none"
    summary: Dict[str, Any] = {"slice": f"eta={eta}, pad={pad}", "per_d": {}}

    oh_both = []
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
        same_om_m = same_morphology(
            oh["m_cp"], om["m_cp"], SAME_MORPH_ALPHA_REL, SAME_MORPH_GAP_RATIO
        ) if (oh and om) else False
        morph_om.append(same_om or same_om_m)

        same_d = same_morphology(
            oh["U_cp"], dd["U_cp"], SAME_MORPH_ALPHA_REL, SAME_MORPH_GAP_RATIO
        ) if (oh and dd) else False
        morph_d.append(same_d)

        b_gone = True
        if oh and oh_b:
            if oh["U_cp"]["critical"] or oh["m_cp"]["critical"]:
                b_u = oh_b["U_cp"]["critical"]
                b_m = oh_b["m_cp"]["critical"]
                if b_u or b_m:
                    shifted = True
                    for metric in ["U_cp", "m_cp"]:
                        if oh[metric]["critical"] and oh_b[metric]["critical"]:
                            if same_morphology(oh[metric], oh_b[metric]):
                                shifted = False
                    b_gone = shifted and not (
                        same_morphology(oh["U_cp"], oh_b["U_cp"])
                        or same_morphology(oh["m_cp"], oh_b["m_cp"])
                    )
                else:
                    b_gone = True
            else:
                b_gone = True
        armB_shift.append(b_gone)

        redeemed = False
        if oh and oh_pad and (oh["U_cp"]["critical"] or oh["m_cp"]["critical"]):
            if not oh_pad["U_cp"]["critical"] and not oh_pad["m_cp"]["critical"]:
                mat_main, alphas = seed_matrix(rows, d, eta, "O-H", "main", "none", "U")
                mat_pad, _ = seed_matrix(rows, d, eta, "O-H", "main", "pad_perp", "U")
                hi = slice(len(alphas) // 2, None)
                u_main_hi = np.nanmean(mat_main[:, hi])
                u_pad_hi = np.nanmean(mat_pad[:, hi])
                if u_pad_hi > u_main_hi + 0.05 * abs(u_main_hi + 1e-9):
                    redeemed = True
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

    n_d = len(D_LIST)
    oh_pass_count = sum(1 for _, m_c, u_c, _ in oh_both if m_c and u_c)
    oh_m_only = sum(1 for _, m_c, u_c, _ in oh_both if m_c)
    any_same_om = any(morph_om)
    any_same_d = any(morph_d)
    all_B_ok = all(armB_shift)
    any_pad_fail = any(pad_redeem)

    r1 = um_correlation(rows, eta="low", pad="none", org="O-H", arm="main")
    r1_unfixed = (r1.get("corr") == r1.get("corr") and abs(r1["corr"]) > R1_CORR_CAP)

    apparatus_ok = bool(drop["apparatus_ok"])

    code = "Mirage"
    allowed = "停报涌现；仅见硬阈值式跳跃或证据不足。"
    rationale = []

    # Prereg decision priority
    if not apparatus_ok:
        code = "装置未生效"
        allowed = "臂 B 硬销毁未达 m 下降标准（同格主臂 m 的 50% 以下）；修代码，不升格理论。"
        rationale.append(
            f"Arm-B m-drop pass_frac={drop['pass_frac']:.2f} "
            f"({drop['n_pass']}/{drop['n_total']}) < required {ARM_B_M_DROP_CELL_FRAC}"
        )
    elif any_pad_fail and oh_pass_count >= 1:
        code = "Fail-Pad"
        allowed = "宏观可测句中「非假长记忆」支失败；Pad-⊥ 系统性赎回塌缩。"
        rationale.append("Pad-⊥ redeemed O-H collapse on ≥1 d")
    elif not all_B_ok and oh_pass_count >= 1:
        code = "Fail-Bind"
        allowed = "装置已生效，但臂 B 与主臂临界形态仍同 → 支持 H2；机制层停。"
        rationale.append("Apparatus OK but Arm B criticality not gone/shifted (H2)")
    elif any_same_d and oh_pass_count >= 1:
        code = "Fail-Org"
        allowed = "分层组织非必要；D 与分层主栈临界无别。"
        rationale.append("D shares morphology with O-H")
    elif (
        oh_pass_count >= max(1, (n_d + 1) // 2)
        and not any_same_om
        and not any_same_d
        and all_B_ok
        and not any_pad_fail
        and apparatus_ok
        and not r1_unfixed
    ):
        code = "E-pass"
        allowed = "本装置上分层 NN 组织相对对照多出共址式临界，机制层弱通过。"
        rationale.append(
            f"O-H m&U critical on {oh_pass_count}/{n_d} d; morph distinct; B ok; pad ok; R1 ok"
        )
    elif oh_m_only >= 1:
        if r1_unfixed and oh_pass_count >= max(1, (n_d + 1) // 2) and not any_same_om and not any_same_d and all_B_ok and not any_pad_fail:
            # Would have been E-pass but R1 blocks
            code = "H-pass"
            allowed = "R1 未解除（corr(U,m)>0.9）→ 不得 E-pass；标题含「联想记忆复现」。"
            rationale.append(f"R1 unfixed: corr(U,m)={r1['corr']:.4f} > {R1_CORR_CAP}")
        elif any_same_om or any_same_d:
            code = "H-pass"
            allowed = "复现联想记忆/attention 容量；不得写 NN-of-NN 涌现成立。"
            rationale.append("O-H criticality but O-M/D similar morphology → H-pass")
        elif oh_pass_count >= max(1, (n_d + 1) // 2):
            if r1_unfixed:
                code = "H-pass"
                allowed = "R1 未解除 → 不得 E-pass；复现联想记忆/attention 容量。"
                rationale.append(f"R1 unfixed: corr={r1['corr']:.4f}")
            else:
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

    # Annotate R1 even when other codes win
    if r1_unfixed and code == "E-pass":
        # safety: never allow E-pass with R1 unfixed
        code = "H-pass"
        allowed = "R1 未解除（corr(U,m)>0.9）→ 不得 E-pass。"
        rationale.append("E-pass blocked by R1 gate")

    summary["decision_code"] = code
    summary["allowed_wording"] = allowed
    summary["rationale"] = rationale
    summary["R1_U_m_corr"] = r1
    summary["R1_unfixed"] = r1_unfixed
    summary["apparatus_ok"] = apparatus_ok
    summary["armB_m_drop"] = {
        "pass_frac": drop["pass_frac"],
        "n_pass": drop["n_pass"],
        "n_total": drop["n_total"],
        "apparatus_ok": apparatus_ok,
    }
    summary["oh_pass_count"] = oh_pass_count
    summary["oh_m_only_count"] = oh_m_only
    summary["any_same_morph_om"] = any_same_om
    summary["any_same_morph_d"] = any_same_d
    summary["all_armB_ok"] = all_B_ok
    summary["any_pad_redeem"] = any_pad_fail
    return summary


def plot_phase_diagrams(rows: List[Dict], cp_results: List[Dict]):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
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
            ax_m.set_ylabel("m = mass on {i*,j*}" if col == 0 else "")
            ax_m.set_xlabel("α = N_priv / d")
            ax_u.legend(fontsize=7)
            ax_m.legend(fontsize=7)
        fig.suptitle(f"Retest main arm (combinatorial U), pad=none, η={eta}")
        fig.tight_layout()
        fig.savefig(RESULTS_DIR / f"phase_U_m_main_none_eta{eta}.png", dpi=140)
        plt.close(fig)

    fig, axes = plt.subplots(2, 3, figsize=(12, 7), sharex=True)
    for col, d in enumerate(D_LIST):
        ax_u, ax_m = axes[0, col], axes[1, col]
        for arm, pad, label, color in [
            ("main", "none", "main", "C0"),
            ("B", "none", "armB-hard", "C3"),
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
    fig.suptitle("O-H controls retest: main / arm B hard / Pad-⊥ (η=low)")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "phase_OH_controls_etalow.png", dpi=140)
    plt.close(fig)

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
    fig.suptitle("U heatmap retest (η=low, main, pad=none)")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "heatmap_U_etalow_main_none.png", dpi=140)
    plt.close(fig)


def write_report(decision: Dict, cp_results: List[Dict], rows: List[Dict], drop: Dict):
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    code = decision["decision_code"]
    title = f"实验报告 · NN 组织 NN 第 1 期复测（2026-10-17）· 判定码 {code}"
    if code == "H-pass":
        title = f"实验报告 · NN 组织 NN 第 1 期复测 · 联想记忆复现（H-pass）· 2026-10-17"
    if code == "装置未生效":
        title = f"实验报告 · NN 组织 NN 第 1 期复测 · 装置未生效 · 2026-10-17"

    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("> 复测授权：prereg_第1期复测_FailBind与R1_2026-10-17.md（作者同意开跑）。")
    lines.append("> 父结果 Fail-Bind；本跑不覆盖 `nn_of_nn_phase1_2026-10-17/`。")
    lines.append("> 唯二改动：臂 B 硬销毁绑定；组合效用 U（concat 探针）。不写涌现成立除非 E-pass。")
    lines.append("")
    lines.append("## 1. 复测目的")
    lines.append("")
    lines.append("在最小改动下使（i）臂 B 操作化无歧义（硬销毁）；（ii）U 任务强制多键/组合信息以压 R1。区分 H1（装置未切断绑定）vs H2（临界本就不依赖绑定）。")
    lines.append("")
    lines.append("## 2. 方法改动（相对第 1 期）")
    lines.append("")
    lines.append("### 2.1 臂 B：硬销毁")
    lines.append("")
    lines.append("- 保持 `{k_i,v_i}` 与主臂同一实现。")
    lines.append("- 采样有序对 `(i*,j*)∈P×P`，`i*≠j*` 后：**线索**用错排 π 在 P 上的 `(π(i*),π(j*))`，即 `q=normalize(k_π(i*)+k_π(j*))+ηε`；若 `{π(i*),π(j*)}={i*,j*}`（`n_priv=2` 必然），则改用各向同性随机单位向量作线索模板（硬销毁回退）。")
    lines.append("- 监督 `y` 仍由真对 `P[v_i*;v_j*]` 生成。")
    lines.append("- **训练与测试均**施加销毁（禁止仅测试假装打乱、不重训读出）。")
    lines.append("- 禁止软打乱：禁止 `q` 仍等于 `normalize(k_i*+k_j*)` 却声称臂 B。")
    lines.append("- 装置成功标准：同 `(d,α,η)` 格臂 B 的均值 `m < 50%` 主臂 `m`（主切片 η=low,pad=none,O-H；≥80% 格子通过）。")
    lines.append("")
    lines.append("### 2.2 组合效用 U")
    lines.append("")
    lines.append("- 线索：`q = normalize(k_i*+k_j*) + ηε`（主用 normalize 和）。")
    lines.append("- 目标：`y = P[v_i*; v_j*]`（concat 后线性探针，`P∈R^{d_y×2 d_v}`）。")
    lines.append("- `m` = 注意力/权重在 `{i*,j*}` 上的质量之和。")
    lines.append("- R1 闸：若 `corr(U,m)>0.9` → 不得 E-pass。")
    lines.append("")
    lines.append("其余：O-H / O-M / D、Pad-⊥、η 两档、变点程序、判定表与 v2 相同。")
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
        f"- 装置生效：{decision.get('apparatus_ok')} "
        f"（m-drop 通过格子 {drop['n_pass']}/{drop['n_total']} = {drop['pass_frac']:.2f}）"
    )
    lines.append(
        f"- 主切片 η=low, pad=none：O-H 同时 m&U 临界的 d 数 = "
        f"{decision.get('oh_pass_count')}/{len(D_LIST)}；"
        f"仅 m 临界 = {decision.get('oh_m_only_count')}/{len(D_LIST)}"
    )
    lines.append(
        f"- 与 O-M 同形态：{decision.get('any_same_morph_om')}；"
        f"与 D 同形态：{decision.get('any_same_morph_d')}；"
        f"臂 B 形态消失/平移：{decision.get('all_armB_ok')}；"
        f"Pad-⊥ 赎回：{decision.get('any_pad_redeem')}"
    )
    r1 = decision.get("R1_U_m_corr", {})
    lines.append(
        f"- R1：corr(U,m)≈{r1.get('corr')} (n={r1.get('n')})；"
        f"R1 未解除={decision.get('R1_unfixed')}"
    )
    lines.append("")
    lines.append("## 4. 臂 B 的 m 下降检验表（装置层，η=low, pad=none, O-H）")
    lines.append("")
    lines.append("| d | α | n_priv | 可检 | m_main | m_B | m_B/m_main | 通过(<50%) | U_main | U_B |")
    lines.append("|---|---|--------|------|--------|-----|------------|------------|--------|-----|")
    for c in drop["cells"]:
        ratio = c["ratio_B_over_main"]
        rs = "—" if ratio != ratio else f"{ratio:.3f}"
        excl = "否(结构)" if c.get("structural_exclude") else "是"
        lines.append(
            f"| {c['d']} | {c['alpha']} | {c.get('n_priv','—')} | {excl} | "
            f"{c['m_main']:.3f} | {c['m_B']:.3f} | {rs} | {c['pass_lt_50pct']} | "
            f"{c['U_main']:.4f} | {c['U_B']:.4f} |"
        )
    lines.append("")
    lines.append(
        f"汇总（仅 n_priv≥4 可检格）：通过 {drop['n_pass']}/{drop['n_total']} "
        f"（要求 ≥{int(ARM_B_M_DROP_CELL_FRAC*100)}%；"
        f"结构排除 {drop.get('n_structural_exclude',0)} 格）；"
        f"装置判定 = **{'生效' if drop['apparatus_ok'] else '未生效'}**。"
    )
    lines.append("")
    lines.append(
        "注：N=N_priv 且 n_priv≤3 时，组合 m=mass on {i*,j*} 无法降到主臂 50% 以下"
        "（无完全不相交错对 / 无私有外原子），属结构不可辨，不记为软打乱。"
    )
    lines.append("")
    lines.append("## 5. 各 d 临界摘要（η=low, pad=none, arm=main）")
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
    lines.append("\\* 表示该指标变点通过自助法 95% CI 临界判定。")
    lines.append("")
    lines.append("## 6. 对照臂与 Pad-⊥（η=low）")
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
    lines.append("## 7. 结果均值表（节选：η=low, pad=none, arm=main）")
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
    lines.append("## 8. U–m 相关（R1）")
    lines.append("")
    corr = r1.get("corr")
    lines.append(
        f"- O-H 主臂（η=low, pad=none）：corr(U,m) ≈ **{corr if corr == corr else 'nan'}** "
        f"(n={r1.get('n')})。"
    )
    if corr == corr and abs(corr) > R1_CORR_CAP:
        lines.append(f"- **R1 未解除**（>{R1_CORR_CAP}）→ 禁止宣称 E-pass。")
    else:
        lines.append(f"- R1 闸未触发（|corr|≤{R1_CORR_CAP} 或样本不足）。")
    lines.append("")
    lines.append("## 9. 图")
    lines.append("")
    lines.append(f"- `{RESULTS_DIR / 'phase_U_m_main_none_etalow.png'}`")
    lines.append(f"- `{RESULTS_DIR / 'phase_U_m_main_none_etahigh.png'}`")
    lines.append(f"- `{RESULTS_DIR / 'phase_OH_controls_etalow.png'}`")
    lines.append(f"- `{RESULTS_DIR / 'heatmap_U_etalow_main_none.png'}`")
    lines.append("")
    lines.append("## 10. 禁写核对")
    lines.append("")
    if code != "E-pass":
        lines.append("- 本文**不**声称「NN-of-NN 涌现成立」或「涌现已证明」。")
    else:
        lines.append("- 仅写机制层弱通过（E-pass）；哲学句仍未证。")
    if code == "H-pass":
        lines.append("- 标题已含「联想记忆复现」。")
    if code == "装置未生效":
        lines.append("- 不升格理论；下一步修臂 B 代码/操作化。")
    lines.append("- 未覆盖第 1 期原始跑；未使用 exact_set；未改 csh/sdia。")
    lines.append("")
    lines.append("## 11. 复现")
    lines.append("")
    lines.append("```bash")
    lines.append(f"cd {RESULTS_DIR.parent.parent / '02_脚本' / 'nn_of_nn_phase1_retest'}")
    lines.append("python run_phase1.py && python analyze_phase1.py")
    lines.append("```")
    lines.append("")
    lines.append("*执笔：Grok Bot（技术执行）· prereg 第 1 期复测 · 2026-10-17*")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report → {REPORT_PATH}")


def main():
    rows = load_raw()
    print(f"Loaded {len(rows)} raw cells")
    cp = run_criticality(rows)
    with open(RESULTS_DIR / "criticality.json", "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2, default=str)
    drop = arm_b_m_drop_table(rows)
    with open(RESULTS_DIR / "armB_m_drop.json", "w", encoding="utf-8") as f:
        json.dump(drop, f, ensure_ascii=False, indent=2, default=str)
    decision = decide(cp, rows, drop)
    with open(RESULTS_DIR / "decision.json", "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2, default=str)
    plot_phase_diagrams(rows, cp)
    write_report(decision, cp, rows, drop)
    print("Decision:", decision["decision_code"])
    print("Apparatus OK:", decision["apparatus_ok"])
    print("R1 corr:", decision["R1_U_m_corr"])
    print("Allowed:", decision["allowed_wording"])


if __name__ == "__main__":
    main()
