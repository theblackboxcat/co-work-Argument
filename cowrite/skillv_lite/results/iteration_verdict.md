# Iteration verdict — Skill-V-lite speak/silence

Date: 2026-10-18 Asia/Shanghai. Honest science: no invented scores; speak/silence + model-call path only; not 知音.

## Prereg bar

See `exp_matrix.md`. Primary = held slice revised lowers disc OR raises label_agree vs seed, without raising dots3_fail, and speak drop not abstain-only. Secondary = ≥1 accepted revision wins ablation on held. Null = observed Δdisc extreme under label shuffle.

## Headline numbers

| check | result |
|---|---|
| Offline deduped disc (known) | logged 丙 denser; seed gate 0.4062 → revised 0.3125 |
| E1 live deduped n=32 | rule 20 speak / 17/30 agree; logged 30 / 14/32; seed 21 / **19/32**; revised 18 / **22/32**; fail=0 all |
| E1 primary | **PASS** (agree↑, fail flat, abstain 0→0) |
| E2 LOSO hold S-20261006 | seed disc 0.4211 → loso-rev 0.3684; agree 11/19→12/19 **PASS** |
| E2 LOSO hold S-20261009 | seed 0.3846 → loso-rev **0.4615**; agree 8/13→7/13 **FAIL** |
| E2 frozen revised on protocol replay | disc 0.3846→0.3077; agree 8/13→9/13 (non-regression buffer) |
| E3 only_planning_1250 on held | no win (ties seed) |
| E3 only_stuck_not_mid on held | disc 0.3846→0.3077; agree 8/13→9/13 **WIN** |
| E3 full revised | same as stuck-only on held **WIN** |
| E4 shuffle null | Δdisc=−0.09375; p≈0.38; **not extreme** |
| E5 logged→revised withhold | TP=10 FP=2; seed→revised extra withhold TP=3 FP=1; claim **holds** |

## Pass / fail vs bar

| criterion | status |
|---|---|
| Primary (E1 live expand) | **PASS** |
| Primary (E2 LOSO, stricter) | **MIXED** (1/2 sessions) |
| Secondary (ablation) | **PASS** — `stuck_speak.require_not_mid=True` carries the held gain; `planning_ms=1250` alone does not on held replay |
| Null (shuffle) | **FAIL** — gain not extreme under label shuffle at n=32 / 20 shuffles |
| E5 capability (withhold enriches TP) | **PASS** |
| Stop rule (primary fails twice → principle rewrite) | **NOT TRIGGERED** — E1 passed; E2 only one LOSO fail |

## Interpretation

1. The shipped revised library’s **directional** improvement is real on the protocol held replay and on live deduped label_agree, and is almost entirely the **stuck mid-sentence** bound (`require_not_mid=True`). Planning 1250ms is nearly inert on the held replay speak counts.
2. **Leave-one-session-out re-fit is unstable**: when holding the original replay session, evolve on the other session accepts `recontext_speak.content_min→60` plus planning_ms, and **hurts** held disc. Frozen revised (fit under the original protocol) still looks good on that session. So “improvement” is protocol-dependent, not a free re-fit guarantee.
3. The **null shuffle does not crown** the Δdisc; with n=32 the same Δ appears often under noise. Do not claim statistical confirmation.
4. Withhold autopsy supports the capability story: revised withholds enrich author-wanted silences (10 TP vs 2 FP vs logged), better net than seed alone.
5. Live path: all dots3 calls ok (31 unique / 40 budget). Probe/label issues remain; this is not content-quality proof.

## Overall verdict

**Conditional keep — do not overclaim.** Keep the stuck mid-sentence revision as the working heuristic; treat planning_ms=1250 as optional / low-evidence on held. Do **not** assert robust LOSO generalization or shuffle-significant gain. E6 principle rewrite is **not** required by the stop rule.

## Next action

1. **Change experiments:** → **done in Round 2** (see below). Freeze-LOSO primary + 200 shuffles + third-session hunt + chrono.
2. **PR landing:** safe to land Skill-V-lite pilot + stuck `require_not_mid` with the caveats above; mention LOSO fragility and null non-significance in the PR text. Kick CloudAgent for PR #9 only if parent wants docs/results committed to `cursor/skillv-lite-pilot-09db`.
3. **Principle revision (optional, not stop-rule):** if a third session again shows re-fit harm, tighten evolve applicability (e.g. disallow `content_min` steps that change speak rate without mid-sentence evidence) — draft then, not now.
4. E6 file `principle_revision_proposal.md` **not written** (stop rule not met).

## Artifacts

- `exp_matrix.md`, `e1_live_deduped.*`, `e2_holdout.*`, `e3_ablation.*`, `e4_shuffle.*`, `e5_withhold_autopsy.*`, `exp_suite_index.json`, `eval_exp_suite.py`


---

## Round 2 (2026-10-18 Asia/Shanghai) — change experiments

Goal: replace re-fit LOSO with **freeze-bounds** as primary; tighten null (200 shuffles); hunt third session; optional chrono freeze. No principle rewrite unless E1-style primary **and** freeze-LOSO both fail.

### Round-2 headline table

| check | result | vs Round-1 |
|---|---|---|
| **E2b freeze-LOSO** hold `S-20261006-234611` | seed disc 0.4211→**0.3158**; agree 11/19→**13/19** **PASS** | strengthens (was secondary footnote) |
| **E2b freeze-LOSO** hold `S-20261009-103650` | seed 0.3846→**0.3077**; agree 8/13→**9/13** **PASS** | strengthens (re-fit had FAIL here) |
| E2b all sessions | **2/2 PASS** | primary holdout read now clean |
| E2 re-fit (footnote only) | still 1/2 FAIL | unchanged; do not use as primary |
| **E4b** n=200 shuffles | Δ=−0.09375; two-sided p≈**0.393**; one-sided p(Δ≤obs)≈0.318; rank 11/200 (≈5th pct from most negative); null α=0.05 **NO** | leaves null weak (same conclusion as n=20) |
| Chrono protocol / 10-06→10-09 | **PASS** (0.385→0.308, 8→9/13) | supports freeze |
| Chrono 70/30 within pool | **tie FAIL** (0.400→0.400, 6/10=6/10) | small late slice; does not overturn |
| **E2c third session** | **NONE** as a Skill-V label set. `S-20261018-174656` was the release gate, not a new Skill-V measurement | blocks stronger claim |

### Round-2 pass/fail

| criterion | status |
|---|---|
| Freeze-LOSO primary (E2b) | **PASS** (2/2) |
| E1 live (Round-1, unchanged) | **PASS** |
| Null (E4b, 200) | **FAIL** (not extreme; Δ sits in a common bin −0.094 with 53/200 draws) |
| Third-session confirmation | **BLOCKED** — `S-20261018-174656` was the release gate, not a new labeled Skill-V session (`e2c_need_third_session.md`) |
| E6 stop rule | **NOT TRIGGERED** — freeze-LOSO and E1 both pass |

### Go / no-go

| decision | call |
|---|---|
| **Keep stuck `require_not_mid=True`** | **GO** — freeze-LOSO + E1 + E3 ablation + E5 withhold all agree directionally |
| **Keep `planning_ms=1250` as evidenced gain** | **NO-GO / optional** — still inert on held replay alone |
| **Stronger claim** (“robust / significant improvement”) | **NO-GO until a third labeled Skill-V session** + preferably null or larger n. `S-20261018-174656` does not count: it was the release gate |
| **Principle rewrite (E6)** | **NO** — stop rule not met |
| **Round-2 effect on prior verdict** | **Strengthens conditional keep** (freeze-LOSO cleans the holdout story); **does not** upgrade to strong claim (null still weak; n=2 sessions) |

### Interpretation (Round-2)

1. The Round-1 “LOSO unstable” finding was about **re-fitting**, not about the shipped frozen library. Under freeze-bounds, revised beats seed on **both** sessions.
2. More shuffles do not rescue significance: observed Δ is mild relative to the discrete disc lattice (steps of 1/32); many null draws hit the same −0.09375 bin.
3. Without a third author-labeled Skill-V session, external validity stays thin. Unlabeled sessions in the probe cannot fill the gap. `S-20261018-174656` was the release gate. It is not a new Skill-V measurement and does not enter E2b or E2c.

### Next action (post Round-2)

1. Collect a **third labeled session** per `e2c_need_third_session.md`, then re-run E2b (+ optional live).
2. Land stuck revision in PR with caveats: freeze-LOSO positive, shuffle null non-significant, n=2 sessions.
3. Do **not** write `principle_revision_proposal.md` now.

### Round-2 artifacts

- `eval_round2.py`, `e2b_freeze_loso.*`, `e4b_shuffle200.*`, `e2chrono_freeze.*`, `e2c_need_third_session.*`, `round2_index.json`

