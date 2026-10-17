#!/usr/bin/env python3
"""Analyze R-A + R-B; decision codes EXACTLY as prereg §7 (no E-pass revival)."""
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
    BETA_DEFAULT,
    BETA_ORG_LEVELS,
    BOOTSTRAP_B,
    CI_LEVEL,
    D_LIST,
    EXEC_PAD_DIMS,
    MIN_SIDE_POINTS,
    R1_CORR_CAP,
    RB_U_DELAY_ALPHA_STEPS,
    REPORT_PATH,
    RESULTS_DIR,
    SAME_MORPH_ALPHA_REL,
    SAME_MORPH_GAP_RATIO,
    SEEDS,
)
from criticality import bootstrap_gap_ci, same_morphology

# §1.2 return sentences (locked)
RA_PASS_SENTENCE = (
    "在本浅层嵌套栈上，α-面协变成立且相对 O-M/D 有差别 → 达到作者可用停靠的路径须承认："
    "共址候选不能被单层容量相图单独解释；后续停靠协议应保留『组织—执行同律』为边界，而非加长窗口。"
)
RA_FAIL_SENTENCE = (
    "嵌套地址在 α-面上无独立协变 → 知音主张收缩为：本探针不支持『分层组织带来可返回的共址边界』；"
    "资源回 L2 最小主干定位／coverage／作者确认。"
)
RB_PASS_SENTENCE = (
    "组织序参量与执行效用可分协变 → 快速知音停靠的操作定义应保留『定位态 ≠ 答卷生成』分拆；"
    "协议层可用此边界设计确认轮／coverage，而非堆上下文冒充懂人。"
)
RB_FAIL_SENTENCE = (
    "嵌套可分性未立 → 知音主张不得再写『组织层单独保证共址停靠』；"
    "回 L2 用作者确认与主干定位取证，本探针闭合。"
)
RETURN_BRIDGE = (
    "探针收口：绑定非因、涌现未立；知音原命题仍在，但须离开本玩具的「绑定→共址」捷径，"
    "改走停靠定位或可返回的新问题——容量现象学不是共址证明。"
)
ORIG_PROP = "系统能否快速成为知音／共址停靠（懂人），而非假长记忆；NN-of-NN 只是为其服务的微观必要性探针。"


def load_raw() -> List[Dict[str, Any]]:
    rows = []
    with open(RESULTS_DIR / "cells_raw.jsonl", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def seed_matrix(
    rows: List[Dict],
    d: int,
    org: str,
    metric: str,
    beta_org: float,
    exec_pad_dim: int,
    eta: str = "low",
    arm: str = "main",
    pad: str = "none",
) -> Tuple[np.ndarray, List[float]]:
    by_a = {a: {} for a in ALPHA_LIST}
    for r in rows:
        if (
            r["d"] == d
            and r["eta"] == eta
            and r["organizer"] == org
            and r["arm"] == arm
            and r["pad"] == pad
            and abs(float(r["beta_org"]) - float(beta_org)) < 1e-9
            and int(r["exec_pad_dim"]) == int(exec_pad_dim)
        ):
            by_a[r["alpha"]][r["seed"]] = r[metric]
    mats = []
    for seed in SEEDS:
        row = [by_a[a].get(seed, np.nan) for a in ALPHA_LIST]
        mats.append(row)
    return np.asarray(mats, dtype=float), list(ALPHA_LIST)


def fit_cp(rows, d, org, metric, beta_org, exec_pad_dim, rng) -> Dict[str, Any]:
    if org == "D" and metric == "m":
        return {"critical": False, "reason": "m_undefined_for_D", "alpha_c": None, "gap": None,
                "ci_low": None, "ci_high": None, "mu_left": None, "mu_right": None}
    mat, alphas = seed_matrix(rows, d, org, metric, beta_org, exec_pad_dim)
    if np.isnan(mat).all():
        return {"critical": False, "reason": "all_nan", "alpha_c": None, "gap": None,
                "ci_low": None, "ci_high": None, "mu_left": None, "mu_right": None}
    col_mean = np.nanmean(mat, axis=0)
    mat = mat.copy()
    inds = np.where(np.isnan(mat))
    mat[inds] = np.take(col_mean, inds[1])
    return bootstrap_gap_ci(mat, alphas, MIN_SIDE_POINTS, BOOTSTRAP_B, CI_LEVEL, rng)


def alpha_c_rel_spread(alpha_cs: List[float]) -> Optional[float]:
    """Max pairwise |a-b|/mean(a,b); None if <2 finite values."""
    vals = [a for a in alpha_cs if a is not None and a == a and a > 0]
    if len(vals) < 2:
        return None
    worst = 0.0
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            mid = 0.5 * (vals[i] + vals[j])
            if mid <= 0:
                continue
            worst = max(worst, abs(vals[i] - vals[j]) / mid)
    return worst


def alpha_idx(a: Optional[float]) -> Optional[int]:
    if a is None:
        return None
    # nearest grid midpoint index: alpha_c is midpoint between ALPHA_LIST[t] and [t+1]
    # map to left-edge index by finding closest mid
    mids = [0.5 * (ALPHA_LIST[i] + ALPHA_LIST[i + 1]) for i in range(len(ALPHA_LIST) - 1)]
    dists = [abs(a - m) for m in mids]
    return int(np.argmin(dists))


def analyze_RA(rows: List[Dict], rng) -> Dict[str, Any]:
    """R-A: α-plane coincidence of criticality; O-H vs O-M/D difference required."""
    beta, ep = BETA_DEFAULT, 0
    per_d = {}
    for d in D_LIST:
        entry = {"d": d}
        for org in ["O-H", "O-M", "D"]:
            entry[org] = {
                "m_cp": fit_cp(rows, d, org, "m", beta, ep, rng),
                "U_cp": fit_cp(rows, d, org, "U", beta, ep, rng),
            }
        per_d[d] = entry

    # α_c coincidence across d for O-H m and U
    oh_m_acs = [per_d[d]["O-H"]["m_cp"].get("alpha_c") for d in D_LIST]
    oh_u_acs = [per_d[d]["O-H"]["U_cp"].get("alpha_c") for d in D_LIST]
    spread_m = alpha_c_rel_spread(oh_m_acs)
    spread_u = alpha_c_rel_spread(oh_u_acs)
    m_coincide = spread_m is not None and spread_m < SAME_MORPH_ALPHA_REL
    u_coincide = spread_u is not None and spread_u < SAME_MORPH_ALPHA_REL

    # gap sign consistency U vs m (O-H, per d then majority)
    gap_sign_ok = []
    for d in D_LIST:
        gm = per_d[d]["O-H"]["m_cp"].get("gap")
        gu = per_d[d]["O-H"]["U_cp"].get("gap")
        if gm is None or gu is None:
            gap_sign_ok.append(False)
        else:
            gap_sign_ok.append(np.sign(gm) == np.sign(gu) and gm != 0 and gu != 0)
    gap_signs_consistent = sum(gap_sign_ok) >= 2  # majority of d

    # O-H vs O-M/D morphology difference on α-plane (need DIFFERENCE for RA-pass)
    oh_vs_om_same = []
    oh_vs_d_same = []
    for d in D_LIST:
        # compare on U (m undefined for D)
        oh_vs_om_same.append(
            same_morphology(
                per_d[d]["O-H"]["U_cp"], per_d[d]["O-M"]["U_cp"],
                SAME_MORPH_ALPHA_REL, SAME_MORPH_GAP_RATIO,
            )
        )
        oh_vs_d_same.append(
            same_morphology(
                per_d[d]["O-H"]["U_cp"], per_d[d]["D"]["U_cp"],
                SAME_MORPH_ALPHA_REL, SAME_MORPH_GAP_RATIO,
            )
        )
    # "有可报告差别"：majority of d show NOT same morphology vs O-M and vs D
    has_diff_om = sum(1 for x in oh_vs_om_same if not x) >= 2
    has_diff_d = sum(1 for x in oh_vs_d_same if not x) >= 2
    has_OMD_difference = has_diff_om or has_diff_d
    # pure capacity / Hopfield-only if O-H looks same as BOTH controls on majority
    hopfield_only = (sum(oh_vs_om_same) >= 2) and (sum(oh_vs_d_same) >= 2)

    # Only-m-stable U-drifts falsifier
    only_m_stable = m_coincide and (not u_coincide)

    # Predictions held?
    pred_coincide = m_coincide and u_coincide
    pred_gap = gap_signs_consistent
    predictions_ok = pred_coincide and pred_gap and has_OMD_difference and (not only_m_stable)

    falsifiers = {
        "alpha_drift_beyond_20pct": (not m_coincide) or (not u_coincide),
        "only_m_stable_U_drifts": only_m_stable,
        "K_Hopfield_only_OMD_no_diff": hopfield_only,
    }

    if hopfield_only and pred_coincide:
        code = "H-lit-align"  # demoted
        kill = "K-Hopfield-only"
    elif falsifiers["alpha_drift_beyond_20pct"] or falsifiers["only_m_stable_U_drifts"]:
        code = "RA-fail"
        kill = "K-no-cov" if falsifiers["alpha_drift_beyond_20pct"] else None
    elif predictions_ok:
        code = "RA-pass"
        kill = None
    else:
        code = "RA-fail"
        kill = "K-no-cov"

    return {
        "code": code,
        "kill": kill,
        "per_d": {str(d): _serialize_d(per_d[d]) for d in D_LIST},
        "spread_m": spread_m,
        "spread_u": spread_u,
        "m_coincide_20pct": m_coincide,
        "u_coincide_20pct": u_coincide,
        "gap_signs_consistent": gap_signs_consistent,
        "oh_vs_om_same_per_d": oh_vs_om_same,
        "oh_vs_d_same_per_d": oh_vs_d_same,
        "has_OMD_difference": has_OMD_difference,
        "hopfield_only": hopfield_only,
        "falsifiers": falsifiers,
        "return_sentence": RA_PASS_SENTENCE if code == "RA-pass" else RA_FAIL_SENTENCE,
    }


def _serialize_d(entry):
    out = {"d": entry["d"]}
    for org in ["O-H", "O-M", "D"]:
        out[org] = {
            "m_cp": _cp_pub(entry[org]["m_cp"]),
            "U_cp": _cp_pub(entry[org]["U_cp"]),
        }
    return out


def _cp_pub(cp):
    keys = ["critical", "reason", "alpha_c", "gap", "ci_low", "ci_high", "mu_left", "mu_right"]
    return {k: cp.get(k) for k in keys}


def analyze_RB(rows: List[Dict], rng) -> Dict[str, Any]:
    """R-B: oppose-diagonal — (i) β twists m; (ii) exec_pad twists U, not fake α_c."""
    # --- knife (i): β sweep, ep=0 ---
    knife_i = {}
    for beta in BETA_ORG_LEVELS:
        knife_i[beta] = {}
        for d in D_LIST:
            knife_i[beta][d] = {
                "O-H": {
                    "m_cp": fit_cp(rows, d, "O-H", "m", beta, 0, rng),
                    "U_cp": fit_cp(rows, d, "O-H", "U", beta, 0, rng),
                },
                "O-M": {
                    "m_cp": fit_cp(rows, d, "O-M", "m", beta, 0, rng),
                    "U_cp": fit_cp(rows, d, "O-M", "U", beta, 0, rng),
                },
                "D": {
                    "U_cp": fit_cp(rows, d, "D", "U", beta, 0, rng),
                },
            }

    # Does β mainly move m's α_c for O-H?
    m_acs_by_beta = {
        b: [knife_i[b][d]["O-H"]["m_cp"].get("alpha_c") for d in D_LIST]
        for b in BETA_ORG_LEVELS
    }
    u_acs_by_beta = {
        b: [knife_i[b][d]["O-H"]["U_cp"].get("alpha_c") for d in D_LIST]
        for b in BETA_ORG_LEVELS
    }

    def mean_ac(acs):
        vals = [a for a in acs if a is not None]
        return float(np.mean(vals)) if vals else None

    m_moved = False
    u_followed = True
    delay_ok = True
    base_b = BETA_DEFAULT
    for b in BETA_ORG_LEVELS:
        if abs(b - base_b) < 1e-12:
            continue
        for di, d in enumerate(D_LIST):
            ac_m0 = knife_i[base_b][d]["O-H"]["m_cp"].get("alpha_c")
            ac_mb = knife_i[b][d]["O-H"]["m_cp"].get("alpha_c")
            ac_u0 = knife_i[base_b][d]["O-H"]["U_cp"].get("alpha_c")
            ac_ub = knife_i[b][d]["O-H"]["U_cp"].get("alpha_c")
            if ac_m0 is not None and ac_mb is not None and abs(ac_m0 - ac_mb) > 1e-9:
                m_moved = True
            # U should follow or delay ≤ RB_U_DELAY_ALPHA_STEPS
            if ac_mb is not None and ac_ub is not None:
                im = alpha_idx(ac_mb)
                iu = alpha_idx(ac_ub)
                if im is not None and iu is not None:
                    if abs(im - iu) > RB_U_DELAY_ALPHA_STEPS:
                        delay_ok = False
            # falsifier: m moves, U completely frozen with no delay window
            if (
                ac_m0 is not None and ac_mb is not None and abs(ac_m0 - ac_mb) > 1e-9
                and ac_u0 is not None and ac_ub is not None and abs(ac_u0 - ac_ub) < 1e-12
            ):
                # U completely unmoved while m moved — check if within delay is N/A; fail
                u_followed = False

    knife_i_ok = m_moved and delay_ok and u_followed

    # --- knife (ii): exec_pad sweep, β=default ---
    knife_ii = {}
    for ep in EXEC_PAD_DIMS:
        knife_ii[ep] = {}
        for d in D_LIST:
            knife_ii[ep][d] = {
                "O-H": {
                    "m_cp": fit_cp(rows, d, "O-H", "m", BETA_DEFAULT, ep, rng),
                    "U_cp": fit_cp(rows, d, "O-H", "U", BETA_DEFAULT, ep, rng),
                },
                "O-M": {
                    "m_cp": fit_cp(rows, d, "O-M", "m", BETA_DEFAULT, ep, rng),
                    "U_cp": fit_cp(rows, d, "O-M", "U", BETA_DEFAULT, ep, rng),
                },
                "D": {
                    "U_cp": fit_cp(rows, d, "D", "U", BETA_DEFAULT, ep, rng),
                },
            }

    # (ii) should distort U curve / noise floor; NOT create fake α_c decoupled from m
    fake_uc_decoupled = False
    u_distorted = False
    for ep in EXEC_PAD_DIMS:
        if ep == 0:
            continue
        for d in D_LIST:
            m0 = knife_ii[0][d]["O-H"]["m_cp"]
            u0 = knife_ii[0][d]["O-H"]["U_cp"]
            me = knife_ii[ep][d]["O-H"]["m_cp"]
            ue = knife_ii[ep][d]["O-H"]["U_cp"]
            # U level / gap change → distorted
            if u0.get("gap") is not None and ue.get("gap") is not None:
                if abs(u0["gap"] - ue["gap"]) > 1e-6 or (
                    u0.get("mu_right") is not None and ue.get("mu_right") is not None
                    and abs(u0["mu_right"] - ue["mu_right"]) > 1e-5
                ):
                    u_distorted = True
            # fake α_c: U critical with α_c far from m's α_c while m α_c stable
            if ue.get("critical") and me.get("alpha_c") is not None and ue.get("alpha_c") is not None:
                im = alpha_idx(me["alpha_c"])
                iu = alpha_idx(ue["alpha_c"])
                m_stable = (
                    m0.get("alpha_c") is not None
                    and abs(m0["alpha_c"] - me["alpha_c"]) < 1e-9
                )
                if im is not None and iu is not None and abs(im - iu) > RB_U_DELAY_ALPHA_STEPS and m_stable:
                    # U criticality location drifted from m while m unmoved → decoupled fake
                    fake_uc_decoupled = True
            elif ue.get("critical") and (me.get("alpha_c") is None or not me.get("critical")):
                # U critical without m critical at same knife → decoupled
                if m0.get("critical"):
                    fake_uc_decoupled = True

    knife_ii_ok = (not fake_uc_decoupled) and u_distorted

    # O-M/D copy same oppose-diagonal response? (bypass)
    # Check: does O-M m α_c move with β like O-H? and D U move with β?
    om_copies_i = True  # start True, disprove
    d_copies_i = True
    # For content-agnostic O-M, β_scale may move m; "copy" means same directional
    # oppose-diagonal pattern as O-H across both knives. Conservative: if O-M and D
    # show same β→α_c(m) movement magnitude class as O-H AND same exec_pad U fake, fail.
    oh_m_shift = []
    om_m_shift = []
    for b in BETA_ORG_LEVELS:
        if abs(b - BETA_DEFAULT) < 1e-12:
            continue
        for d in D_LIST:
            a0 = knife_i[BETA_DEFAULT][d]["O-H"]["m_cp"].get("alpha_c")
            ab = knife_i[b][d]["O-H"]["m_cp"].get("alpha_c")
            if a0 is not None and ab is not None:
                oh_m_shift.append(ab - a0)
            a0m = knife_i[BETA_DEFAULT][d]["O-M"]["m_cp"].get("alpha_c")
            abm = knife_i[b][d]["O-M"]["m_cp"].get("alpha_c")
            if a0m is not None and abm is not None:
                om_m_shift.append(abm - a0m)
    if oh_m_shift and om_m_shift:
        # copy if same sign majority and comparable magnitude
        same_sign = sum(
            1 for x, y in zip(oh_m_shift, om_m_shift) if np.sign(x) == np.sign(y) and x != 0
        )
        om_copies_i = same_sign >= max(1, len(oh_m_shift) // 2)
    else:
        om_copies_i = False  # O-M didn't produce comparable shifts → not a copy

    # D has no m; check D U α_c movement under β (should be ~0 if β unused)
    d_u_shifts = []
    for b in BETA_ORG_LEVELS:
        if abs(b - BETA_DEFAULT) < 1e-12:
            continue
        for d in D_LIST:
            a0 = knife_i[BETA_DEFAULT][d]["D"]["U_cp"].get("alpha_c")
            ab = knife_i[b][d]["D"]["U_cp"].get("alpha_c")
            if a0 is not None and ab is not None:
                d_u_shifts.append(abs(ab - a0))
    d_copies_i = bool(d_u_shifts) and (np.mean(d_u_shifts) > 0.05) and m_moved

    omd_copy_fail = om_copies_i and d_copies_i

    falsifiers = {
        "ii_fake_Uc_decoupled_from_m": fake_uc_decoupled,
        "i_m_moves_U_frozen": m_moved and (not u_followed),
        "i_U_delay_exceeds_window": not delay_ok,
        "omd_copies_oppose_diagonal": omd_copy_fail,
        "i_m_did_not_move": not m_moved,
        "ii_U_not_distorted": not u_distorted,
    }

    predictions_ok = knife_i_ok and knife_ii_ok and (not omd_copy_fail)

    if falsifiers["ii_fake_Uc_decoupled_from_m"] or falsifiers["i_m_moves_U_frozen"] or falsifiers["i_U_delay_exceeds_window"] or omd_copy_fail:
        code = "RB-fail"
        kill = "K-no-cov"
    elif predictions_ok:
        code = "RB-pass"
        kill = None
    else:
        code = "RB-fail"
        kill = "K-no-cov"

    def pub_knife(kdict):
        out = {}
        for k, v in kdict.items():
            out[str(k)] = {
                str(d): {
                    org: {met: _cp_pub(cp) for met, cp in orgdict.items()}
                    for org, orgdict in dv.items()
                }
                for d, dv in v.items()
            }
        return out

    return {
        "code": code,
        "kill": kill,
        "knife_i_ok": knife_i_ok,
        "knife_ii_ok": knife_ii_ok,
        "m_moved_with_beta": m_moved,
        "u_followed_or_delay_ok": u_followed and delay_ok,
        "u_distorted_by_exec_pad": u_distorted,
        "fake_uc_decoupled": fake_uc_decoupled,
        "om_copies_i": om_copies_i,
        "d_copies_i": d_copies_i,
        "falsifiers": falsifiers,
        "delay_window_alpha_steps": RB_U_DELAY_ALPHA_STEPS,
        "knife_i": pub_knife(knife_i),
        "knife_ii": pub_knife(knife_ii),
        "return_sentence": RB_PASS_SENTENCE if code == "RB-pass" else RB_FAIL_SENTENCE,
    }


def r1_corr(rows) -> Dict[str, float]:
    ms, us = [], []
    for r in rows:
        if (
            r["eta"] == "low"
            and r["pad"] == "none"
            and r["organizer"] == "O-H"
            and r["arm"] == "main"
            and abs(float(r["beta_org"]) - BETA_DEFAULT) < 1e-9
            and int(r["exec_pad_dim"]) == 0
            and r["m"] == r["m"]
        ):
            ms.append(r["m"])
            us.append(r["U"])
    if len(ms) < 5:
        return {"corr": float("nan"), "n": len(ms)}
    return {"corr": float(np.corrcoef(ms, us)[0, 1]), "n": len(ms)}


def decide(ra: Dict, rb: Dict, r1: Dict) -> Dict[str, Any]:
    """Pack decision per prereg §7–§8. No E-pass."""
    kills = []
    if ra.get("kill"):
        kills.append(ra["kill"])
    if rb.get("kill"):
        kills.append(rb["kill"])

    # R1: if corr>0.9 cannot claim exec separated
    r1_block = (r1.get("corr") == r1.get("corr")) and (r1["corr"] > R1_CORR_CAP)

    ra_code = ra["code"]
    rb_code = rb["code"]

    pack_pass = (ra_code == "RA-pass") and (rb_code == "RB-pass") and ("K-Hopfield-only" not in kills)

    # Instr-curve / conform-for-conform: if we somehow had curve success but would
    # refuse return sentences — we always paste §1.2, so K-zero-return not auto.
    # K-conform-for-conform only if pack would pass but we detect zero-return intent.
    # We always attach return sentences → not triggered by analyzer.

    if "K-Hopfield-only" in kills and ra_code != "RA-pass":
        pack_code = "Pack-kill"
    elif pack_pass:
        pack_code = "RA+RB-pack-pass"
    elif ra_code == "H-lit-align" and rb_code.startswith("RB"):
        pack_code = "Pack-kill"  # demoted lit-align; not into 知音主叙事
    else:
        pack_code = "Pack-kill" if (ra_code != "RA-pass" or rb_code != "RB-pass") else "RA+RB-pack-pass"
        if not pack_pass:
            pack_code = "Pack-kill"

    # Gates
    purpose_gate = {
        "status": "PASS",
        "note": "首页复述原命题+返回桥；不赎回E-pass；通过≠涌现；服务停靠边界非仪器学",
    }
    # Service gate: must use §1.2 sentences only
    service_gate = {
        "status": "PASS",
        "RA_return": ra["return_sentence"],
        "RB_return": rb["return_sentence"],
    }
    # Bypass kill gate (prereg §1.3 / §8): only when a "pass" would be capacity-only
    # or oppose-diagonal curves with zero return. Do NOT fire K-Hopfield-only merely
    # because O-M/D look similar under an already-failed RA (that is K-no-cov).
    bypass = False
    bypass_reason = None
    if ra_code == "H-lit-align":
        bypass = True
        bypass_reason = "K-Hopfield-only"
    if ra_code == "RA-pass" and ra.get("hopfield_only"):
        bypass = True
        bypass_reason = "K-Hopfield-only"
        ra_code = "H-lit-align"
    # Instr-curve: RB curves ok-looking but pack would claim without §1.2 — we always
    # paste return sentences; fire only if RB-pass with explicit zero-return flag.
    if rb_code == "RB-pass" and ra_code not in ("RA-pass",) and rb.get("zero_return"):
        bypass = True
        bypass_reason = "K-conform-for-conform"

    bypass_gate = {
        "status": "FAIL" if bypass else "PASS",
        "reason": bypass_reason,
    }

    if bypass:
        pack_code = "Pack-kill"

    return {
        "RA": ra_code,
        "RB": rb_code,
        "pack": pack_code,
        "kills": sorted(set(kills)),
        "r1": r1,
        "r1_blocks_exec_separation_claim": r1_block,
        "gates": {
            "purpose": purpose_gate,
            "service": service_gate,
            "bypass_kill": bypass_gate,
        },
        "E_pass_redeemed": False,
        "Fail_Bind_H2_authority": True,
        "emergence_claimed": False,
        "into_zhiyin_main_narrative": pack_code == "RA+RB-pack-pass" and not bypass,
    }


def plots(rows, ra, rb):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # R-A: m and U vs α for O-H across d (β=default, ep=0)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, metric, title in zip(axes, ["m", "U"], ["m (attn mass)", "U (−MSE)"]):
        for d in D_LIST:
            mat, alphas = seed_matrix(rows, d, "O-H", metric, BETA_DEFAULT, 0)
            mean = np.nanmean(mat, axis=0)
            std = np.nanstd(mat, axis=0)
            ax.errorbar(alphas, mean, yerr=std, marker="o", label=f"d={d}")
        ax.set_xlabel("α = N_priv / d")
        ax.set_ylabel(metric)
        ax.set_title(f"R-A O-H {title}")
        ax.legend()
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "plot_RA_OH_alpha_plane.png", dpi=120)
    plt.close(fig)

    # R-A: O-H vs O-M vs D U curves at d=32
    fig, ax = plt.subplots(figsize=(6, 4))
    d = 32
    for org, style in [("O-H", "o-"), ("O-M", "s--"), ("D", "^:")]:
        mat, alphas = seed_matrix(rows, d, org, "U", BETA_DEFAULT, 0)
        ax.plot(alphas, np.nanmean(mat, axis=0), style, label=org)
    ax.set_xlabel("α")
    ax.set_ylabel("U")
    ax.set_title(f"R-A U curves d={d} (O-H vs O-M/D)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "plot_RA_OMD_U_d32.png", dpi=120)
    plt.close(fig)

    # R-B-i: m α_c vs β for O-H
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, metric in zip(axes, ["m", "U"]):
        for d in D_LIST:
            ys = []
            for b in BETA_ORG_LEVELS:
                cp = fit_cp(rows, d, "O-H", metric, b, 0, np.random.default_rng(0))
                ys.append(cp.get("alpha_c") if cp.get("alpha_c") is not None else np.nan)
            ax.plot(BETA_ORG_LEVELS, ys, "o-", label=f"d={d}")
        ax.set_xlabel("β_org")
        ax.set_ylabel(f"α̂_c({metric})")
        ax.set_title(f"R-B(i) O-H α̂_c({metric}) vs β")
        ax.legend()
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "plot_RB_i_alpha_c_vs_beta.png", dpi=120)
    plt.close(fig)

    # R-B-ii: U curves vs α at different exec_pad
    fig, ax = plt.subplots(figsize=(6, 4))
    d = 32
    for ep in EXEC_PAD_DIMS:
        mat, alphas = seed_matrix(rows, d, "O-H", "U", BETA_DEFAULT, ep)
        ax.plot(alphas, np.nanmean(mat, axis=0), "o-", label=f"exec_pad={ep}")
    ax.set_xlabel("α")
    ax.set_ylabel("U")
    ax.set_title(f"R-B(ii) O-H U vs α (d={d})")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "plot_RB_ii_U_vs_exec_pad.png", dpi=120)
    plt.close(fig)

    # R-B-ii: m curves (should stay similar)
    fig, ax = plt.subplots(figsize=(6, 4))
    for ep in EXEC_PAD_DIMS:
        mat, alphas = seed_matrix(rows, d, "O-H", "m", BETA_DEFAULT, ep)
        ax.plot(alphas, np.nanmean(mat, axis=0), "o-", label=f"exec_pad={ep}")
    ax.set_xlabel("α")
    ax.set_ylabel("m")
    ax.set_title(f"R-B(ii) O-H m vs α (d={d})")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "plot_RB_ii_m_vs_exec_pad.png", dpi=120)
    plt.close(fig)


def write_report(decision: Dict, ra: Dict, rb: Dict, r1: Dict, meta: Dict):
    gates = decision["gates"]
    g1 = gates["purpose"]["status"]
    g2 = gates["service"]["status"]
    g3 = gates["bypass_kill"]["status"]

    lines = []
    lines.append("# 实验报告 · NN组织NN · 反向／共形 R-A+R-B（2026-10-17）")
    lines.append("")
    lines.append("> **DRAFT_NOT_FROZEN prereg + 作者授权开跑 2026-10-17**（说「开」）。")
    lines.append("> **不赎回 E-pass** · **Fail-Bind H2 仍为机制权威** · **通过 ≠ 涌现**。")
    lines.append("> 对照 prereg：`01_协议与理论/prereg_反向共形_RA_RB_2026-10-17.md`")
    lines.append("> 原始跑：`04_原始数据_runs/nn_of_nn_reverse_RA_RB_2026-10-17/`")
    lines.append("> 不覆盖：`nn_of_nn_phase1_2026-10-17/`、`nn_of_nn_phase1_retest_2026-10-17/`。")
    lines.append("")
    lines.append("## 0. 首页三闸状态（写死 · 先读）")
    lines.append("")
    lines.append("| 闸 | 状态 | 说明 |")
    lines.append("|----|------|------|")
    lines.append(f"| **目的闸** | **{g1}** | 原命题+返回桥已粘贴；不赎回 E-pass；通过≠涌现；服务停靠边界 |")
    lines.append(f"| **服务闸** | **{g2}** | 主叙事只用 §1.2 预注册返回句（见下） |")
    lines.append(f"| **旁路杀闸** | **{g3}** | {gates['bypass_kill'].get('reason') or '未触 K-Hopfield-only／为共形而共形'} |")
    lines.append("")
    lines.append("### 原命题（钉死）")
    lines.append("")
    lines.append(f"**{ORIG_PROP}**")
    lines.append("")
    lines.append("### 返回桥短句")
    lines.append("")
    lines.append(f"> {RETURN_BRIDGE}")
    lines.append("")
    lines.append("### 服务闸返回句（实测后主叙事只能用这两句）")
    lines.append("")
    lines.append(f"- **R-A（{decision['RA']}）**：" + ra["return_sentence"])
    lines.append(f"- **R-B（{decision['RB']}）**：" + rb["return_sentence"])
    lines.append("")
    if g1 == "PASS" and g2 == "PASS" and g3 == "PASS" and decision["pack"] == "RA+RB-pack-pass":
        lines.append("**三闸结论**：三闸均过且 pack-pass → 组合边界可返回知音命题；**仍 ≠ 涌现、≠ 赎 E-pass**。")
    elif g3 == "FAIL":
        lines.append("**三闸结论**：旁路杀闸触发 → **整包不进知音主叙事**（Pack-kill／demoted）。")
    else:
        lines.append("**三闸结论**：目的／服务闸文案就位，但判定未达 pack-pass 或协变失败 → **不进知音主叙事升格**；按 §1.2 不通过句收缩。")
    lines.append("")
    lines.append("## 1. 判定码摘要（prereg §7 · 不重开 E-pass）")
    lines.append("")
    lines.append("| 项 | 码 |")
    lines.append("|----|-----|")
    lines.append(f"| R-A | **{decision['RA']}** |")
    lines.append(f"| R-B | **{decision['RB']}** |")
    lines.append(f"| Pack | **{decision['pack']}** |")
    lines.append(f"| Kills | {', '.join(decision['kills']) if decision['kills'] else '（无）'} |")
    lines.append(f"| 进知音主叙事 | {decision['into_zhiyin_main_narrative']} |")
    lines.append(f"| E-pass 赎回 | **False**（禁止） |")
    lines.append(f"| Fail-Bind H2 权威 | **True** |")
    lines.append(f"| 涌现声称 | **False** |")
    lines.append("")
    lines.append("## 2. 方法（相对复测 · 唯二入刀）")
    lines.append("")
    lines.append("- **R-A**：固定 α=N_priv/d，同步放大 (N_priv,d)；d∈{16,32,64}；α 七点；η=low；pad=none；O-H+O-M+D；β=4.0；种子 5。")
    lines.append(f"- **R-B(i)**：只拧组织 β∈{BETA_ORG_LEVELS}；执行头锁死；延迟窗缺省 {RB_U_DELAY_ALPHA_STEPS} 个 α 格。")
    lines.append(f"- **R-B(ii)**：只拧执行／pad 进 R 的无关维∈{EXEC_PAD_DIMS}；组织 β 锁死 4.0。")
    lines.append("- 不重开正向绑定臂作主证据；不改 csh/sdia；无 LLM／私料／全树。")
    lines.append("- 变点：单变点分段拟合 + BIC 口径（SSE）+ 自助法 95% CI；同形态窗 20%／gap 比 [1/2,2]。")
    lines.append("")
    lines.append("## 3. R-A 结果（α-面重合）")
    lines.append("")
    lines.append(f"- m 跨 d 相对散布 spread_m = {ra.get('spread_m')}（要求 < {SAME_MORPH_ALPHA_REL}）→ coincide={ra.get('m_coincide_20pct')}")
    lines.append(f"- U 跨 d 相对散布 spread_u = {ra.get('spread_u')} → coincide={ra.get('u_coincide_20pct')}")
    lines.append(f"- U/m gap 符号一致（多数 d）= {ra.get('gap_signs_consistent')}")
    lines.append(f"- O-H vs O-M 同形态/d：{ra.get('oh_vs_om_same_per_d')}")
    lines.append(f"- O-H vs D 同形态/d：{ra.get('oh_vs_d_same_per_d')}")
    lines.append(f"- 相对 O-M/D 有可报告差别 = {ra.get('has_OMD_difference')}；Hopfield-only = {ra.get('hopfield_only')}")
    lines.append(f"- 否证：{json.dumps(ra.get('falsifiers'), ensure_ascii=False)}")
    lines.append("")
    lines.append("| d | O-H α_c(m) | O-H α_c(U) | O-M α_c(U) | D α_c(U) |")
    lines.append("|---|------------|------------|------------|----------|")
    for d in D_LIST:
        e = ra["per_d"][str(d)]
        def fmt(cp):
            a = cp.get("alpha_c")
            return f"{a:.3f}{'*' if cp.get('critical') else ''}" if a is not None else "—"
        lines.append(
            f"| {d} | {fmt(e['O-H']['m_cp'])} | {fmt(e['O-H']['U_cp'])} | "
            f"{fmt(e['O-M']['U_cp'])} | {fmt(e['D']['U_cp'])} |"
        )
    lines.append("")
    lines.append("\\* = 自助法 95% CI 临界。")
    lines.append("")
    lines.append("## 4. R-B 结果（组织–执行反对角）")
    lines.append("")
    lines.append(f"- 刀(i) ok={rb.get('knife_i_ok')}（m 随 β 移动={rb.get('m_moved_with_beta')}；U 跟随/延迟窗={rb.get('u_followed_or_delay_ok')}）")
    lines.append(f"- 刀(ii) ok={rb.get('knife_ii_ok')}（U 被 exec_pad 扭曲={rb.get('u_distorted_by_exec_pad')}；假 U 临界脱钩={rb.get('fake_uc_decoupled')}）")
    lines.append(f"- O-M/D 复制反对角？ om_copies={rb.get('om_copies_i')} d_copies={rb.get('d_copies_i')}")
    lines.append(f"- 否证：{json.dumps(rb.get('falsifiers'), ensure_ascii=False)}")
    lines.append(f"- 延迟窗（草案缺省）：{rb.get('delay_window_alpha_steps')} 个 α 格")
    lines.append("")
    lines.append("## 5. R1 闸")
    lines.append("")
    lines.append(f"- corr(U,m) ≈ **{r1.get('corr')}** (n={r1.get('n')})；帽={R1_CORR_CAP}")
    lines.append(f"- R1 阻断「执行已分离」话术 = {decision.get('r1_blocks_exec_separation_claim')}")
    lines.append("")
    lines.append("## 6. 图")
    lines.append("")
    lines.append("- `plot_RA_OH_alpha_plane.png`")
    lines.append("- `plot_RA_OMD_U_d32.png`")
    lines.append("- `plot_RB_i_alpha_c_vs_beta.png`")
    lines.append("- `plot_RB_ii_U_vs_exec_pad.png`")
    lines.append("- `plot_RB_ii_m_vs_exec_pad.png`")
    lines.append("")
    lines.append("## 7. 偏差与缺省")
    lines.append("")
    lines.append("- 数值缺省均用 prereg 草案：β∈{2,4,8}；exec_pad∈{0,16,32}；U 延迟窗=1 α 格；未加强制 f(m,pad) 强预测；未加 d=128；η 仅 low 主切片；臂 B 不重开主证据。")
    lines.append("- 未声称 prereg FROZEN（作者仅授权开跑，未另拍定稿冻结）。")
    lines.append(f"- 跑规模：{meta.get('n_cells')} cells，耗时 {meta.get('elapsed_sec', 'n/a')} s。")
    lines.append("")
    lines.append("## 8. 复现")
    lines.append("")
    lines.append("```bash")
    lines.append("cd /workspace/proj_20261009/论文资料_cowork/知音坐标系_2026-10-16/02_脚本/nn_of_nn_reverse_RA_RB")
    lines.append("python run_RA_RB.py")
    lines.append("python analyze_RA_RB.py")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*执笔：Grok Bot · 2026-10-17 · DRAFT_NOT_FROZEN + 开跑授权 · 不赎回 E-pass · Fail-Bind H2 仍权威 · 通过 ≠ 涌现*")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote report {REPORT_PATH}", flush=True)


def main():
    rows = load_raw()
    rng = np.random.default_rng(20261017)
    print("Analyzing R-A...", flush=True)
    ra = analyze_RA(rows, rng)
    print(f"  RA code={ra['code']}", flush=True)
    print("Analyzing R-B...", flush=True)
    rb = analyze_RB(rows, rng)
    print(f"  RB code={rb['code']}", flush=True)
    r1 = r1_corr(rows)
    decision = decide(ra, rb, r1)
    print(f"  pack={decision['pack']} kills={decision['kills']}", flush=True)

    # strip bulky knife trees from decision.json top-level but keep summary
    ra_out = {k: v for k, v in ra.items()}
    rb_out = {k: v for k, v in rb.items() if k not in ("knife_i", "knife_ii")}
    rb_out["knife_i_summary"] = "see criticality_RB.json"
    rb_out["knife_ii_summary"] = "see criticality_RB.json"

    out = {
        "decision": decision,
        "RA": ra_out,
        "RB": rb_out,
        "r1": r1,
    }
    with open(RESULTS_DIR / "decision.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    with open(RESULTS_DIR / "criticality_RA.json", "w", encoding="utf-8") as f:
        json.dump(ra, f, ensure_ascii=False, indent=2, default=str)
    with open(RESULTS_DIR / "criticality_RB.json", "w", encoding="utf-8") as f:
        json.dump(rb, f, ensure_ascii=False, indent=2, default=str)

    print("Plotting...", flush=True)
    plots(rows, ra, rb)

    meta = {}
    meta_path = RESULTS_DIR / "run_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    write_report(decision, ra, rb, r1, meta)
    print("Done.", flush=True)
    print(json.dumps(decision, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
