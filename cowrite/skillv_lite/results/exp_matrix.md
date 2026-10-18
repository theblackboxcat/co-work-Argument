# Skill-V-lite experiment matrix — Round-1

Primary validation is live dots3 plus this suite. `eval_ab.py` is the offline disagreement table and is secondary.

The laptop bundle was not on this VM. Figures below are the Round-1 verdict, plus the held-replay ablation already computed on this branch for E3. No other numbers were added.

## Verdict

**Conditional keep.** Stop rule not met. No principle-revision proposal.

| experiment | Round-1 result |
|---|---|
| E1 live deduped | n=32. Revised label_agree 22/32. Seed 19/32. dots3_fail=0. |
| E2 LOSO | Re-fit unstable. Hold out 2026-10-09 fails. |
| E3 ablation | `require_not_mid` carries the held gain. `planning_ms=1250` is weak on held. |
| E4 shuffle null | p≈0.38. No statistical crown. |
| E5 withhold autopsy | No fraction in the Round-1 paste. Not invented. |

Not a 知音 result. Not content-quality proof.

## E3 held replay already on this branch

Held session 2026-10-09, n=13, gate mode.

| library | disc |
|---|---:|
| seed | 0.3846 |
| require_not_mid only | 0.3077 |
| planning_ms=1250 only | 0.3846 |
| both | 0.3077 |

## Round-2

Still running on `LAPTOP-32CD28QL`: freeze the LOSO fit, and 200 shuffles. A later commit may land that run. This matrix does not preview it.

Detail files: `iteration_verdict.md`, `e1_live_deduped.md`, `e2_holdout.md`, `e3_ablation.md`, `e4_shuffle.md`, `e5_withhold_autopsy.md`, `exp_suite_index.json`.
