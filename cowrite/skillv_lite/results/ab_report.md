# Skill-V-lite offline A/B

Cowrite speak/silence policy only. This is not a co-address result.
No model was called. dots3 was not required.

## Protocol

- Labels: author feedback already on `probe.jsonl`.
- Excluded: unlabeled rows, non speak/silence events, smoke session `S-20261006-231325`.
- Primary rows are de-duplicated double-fires. Raw labeled counts are below.
- Proposal slice: sessions before 2026-10-09. Replay buffer: 2026-10-09.
- Positive class: author wanted silence.
- `disc` = (FP+FN)/n. `fnr` = FN/(FN+TP). `bacc` = (TPR+TNR)/2.
- Semantic desired silence includes `silent_had_nothing`. The project confusion table does not; it is reported separately and only for logged actions.
- Evolution may change bounds only. A step is accepted when proposal-slice disc falls and replay disc, FNR, and bacc do not worsen.
- Shipped flag default is `gate`: withhold when the contract says silence; do not force speech; do not add prompt clauses.

## Sample

| | n |
|---|---:|
| labeled speak/silence rows | 50 |
| smoke fixture excluded | 10 |
| duplicate fires dropped | 8 |
| deduped, used | 32 |
| proposal slice | 19 |
| replay buffer | 13 |
| missing attention signals (gate abstains) | 2 |

Library size: **9** contracts. Seed library version 1. Revised library version 3.

Seed cascade vs logged attention rule: speak-bit match 30/30, state+speak match 29/30.

Speak-bit matches with a different state name:
- `spk-1791301921715-029` logged CODING, contract NOT_STARTED (speak bit agrees)

## A/B on deduped labeled episodes

| arm | n | disc | fnr | bacc | silence prec | silence recall |
|---|---:|---:|---:|---:|---:|---:|
| logged (丙, as recorded) | 32 | 0.5625 | 0.9000 | 0.5500 | 1.0000 | 0.1000 |
| attention rule (甲 speak bit) | 30 | 0.4333 | 0.5789 | 0.6196 | 0.8000 | 0.4211 |
| Skill-V seed cascade | 30 | 0.4333 | 0.5789 | 0.6196 | 0.8000 | 0.4211 |
| Skill-V seed gate | 32 | 0.4062 | 0.5500 | 0.6417 | 0.8182 | 0.4500 |
| Skill-V revised cascade | 30 | 0.3333 | 0.4211 | 0.6986 | 0.8462 | 0.5789 |
| Skill-V revised gate | 32 | 0.3125 | 0.4000 | 0.7167 | 0.8571 | 0.6000 |

Silence-recall 95% Wilson intervals on this table:
- logged (丙, as recorded): [0.0279, 0.301]
- attention rule (甲 speak bit): [0.2314, 0.6372]
- Skill-V seed cascade: [0.2314, 0.6372]
- Skill-V seed gate: [0.2582, 0.6579]
- Skill-V revised cascade: [0.3628, 0.7686]
- Skill-V revised gate: [0.3866, 0.7812]

## Replay buffer only (held, 2026-10-09)

| arm | n | disc | fnr | bacc | silence prec | silence recall |
|---|---:|---:|---:|---:|---:|---:|
| logged (丙, as recorded) | 13 | 0.3846 | 0.8333 | 0.5833 | 1.0000 | 0.1667 |
| attention rule (甲 speak bit) | 12 | 0.4167 | 0.8000 | 0.5286 | 0.5000 | 0.2000 |
| Skill-V seed cascade | 12 | 0.4167 | 0.8000 | 0.5286 | 0.5000 | 0.2000 |
| Skill-V seed gate | 13 | 0.3846 | 0.6667 | 0.5952 | 0.6667 | 0.3333 |
| Skill-V revised cascade | 12 | 0.3333 | 0.4000 | 0.6571 | 0.6000 | 0.6000 |
| Skill-V revised gate | 13 | 0.3077 | 0.3333 | 0.6905 | 0.6667 | 0.6667 |

## Proposal slice only (before 2026-10-09)

| arm | n | disc | fnr | bacc | silence prec | silence recall |
|---|---:|---:|---:|---:|---:|---:|
| logged (丙, as recorded) | 19 | 0.6842 | 0.9286 | 0.5357 | 1.0000 | 0.0714 |
| attention rule (甲 speak bit) | 18 | 0.4444 | 0.5000 | 0.6250 | 0.8750 | 0.5000 |
| Skill-V seed cascade | 18 | 0.4444 | 0.5000 | 0.6250 | 0.8750 | 0.5000 |
| Skill-V seed gate | 19 | 0.4211 | 0.5000 | 0.6500 | 0.8750 | 0.5000 |
| Skill-V revised cascade | 18 | 0.3333 | 0.4286 | 0.7857 | 1.0000 | 0.5714 |
| Skill-V revised gate | 19 | 0.3158 | 0.4286 | 0.7857 | 1.0000 | 0.5714 |

## Revisions

Accepted: **2**. Rejected by the evidence gate: **3**. Grid points considered: 36.

| bound | from | to | proposal disc | replay disc | replay fnr | replay bacc |
|---|---|---|---:|---:|---:|---:|
| stuck_speak.require_not_mid | False | True | 0.3684 | 0.3077 | 0.3333 | 0.6905 |
| *shared*.planning_ms | 2000 | 1250 | 0.3158 | 0.3077 | 0.3333 | 0.6905 |

When two grid values tie on the replay buffer, the smaller step from the current bound is kept.

Rejected proposals (they improved the proposal slice and failed the replay gate):

- `recontext_speak.content_min` 0 → 40: disc worsened (0.3077 -> 0.3846)
- `recontext_speak.content_min` 0 → 60: disc worsened (0.3077 -> 0.3846)
- `recontext_speak.content_min` 0 → 80: disc worsened (0.3077 -> 0.4615)

Rubric–outcome disagreements on the deduped set after revision: **10** (seed: 12).

## Logged actions in the project confusion table

TP 1, FP 1, FN 18, TN 12. precision 0.5000, recall 0.0526.

Project cells on logged actions only. silent_had_nothing is FP in this table and a desired silence in the semantic counterfactual table.

The published anchor (precision 0.67, recall 0.16, n=7) is a different sample. These numbers do not replace it.

## Sensitivity: same arms without de-duplication

| arm | n | disc | fnr | bacc |
|---|---:|---:|---:|---:|
| logged (丙, as recorded) | 40 | 0.4750 | 0.9048 | 0.5476 |
| attention rule (甲 speak bit) | 37 | 0.3784 | 0.6000 | 0.6412 |
| Skill-V seed cascade | 37 | 0.3784 | 0.6000 | 0.6412 |
| Skill-V seed gate | 40 | 0.3500 | 0.5714 | 0.6617 |
| Skill-V revised cascade | 37 | 0.3243 | 0.4500 | 0.6868 |
| Skill-V revised gate | 40 | 0.3000 | 0.4286 | 0.7068 |

## Failure modes

- Labels are sparse and were produced by one author on one test build.
- Several probe rows are double-fires of the same pause; the primary table de-duplicates them.
- The packed signal does not store doc_chars. NOT_STARTED on those rows uses passage length and after_chars as a proxy. One 32-character mid-document passage (spk-1791301921715-029) is therefore named NOT_STARTED instead of CODING; both decisions are silence, so the speak bit still matches.
- Rows with a null signal pack abstain. The gate keeps the logged action there.
- silent_had_nothing is a desired silence in the counterfactual table and an FP in the project table.
- Content-quality labels (接受/太弱/太强/不对) answer a different question and are not used as speak outcomes.
- Gate mode cannot repair a logged silence. It only withholds logged speech.
- The residual silence contract has no positive rubric, so some misses are not attributed to a named speak heuristic.
- Accepted revisions are fit on the earlier session. The held session is the non-regression check, not a large confirmation sample.

## How to read a negative

Disagreement counts (FP+FN): deduped logged 18/32, seed gate 13/32, revised gate 10/32. Held 2026-10-09 buffer: logged 5/13, seed gate 5/13, revised gate 4/13. The seed gate matches the frozen 甲 speak bit on every row that has a logged state. On the held buffer the seed gate does not lower disc; it ties the logged action. The revised gate's held-set drop is a small count, and the silence-recall Wilson intervals on the pooled set overlap. No system-prompt clause was added. This is a cowrite speak/silence metric, not a co-address result.
