# Skill-V-lite experiment matrix

Primary validation path, with the live dots3 harness. The offline A/B in `eval_ab.py` stays available and is not this matrix.

## Preregistered success bar

Frozen with the harness. A later run may fill the results. It may not move these sentences.

This is a speak/silence check. It is not a co-address result. phi stays locked. A failed bar proposes a principle change in `principle_revision_proposal.md` and does not edit a contract.

### E1 — live expand (laptop)

Not scored in the offline run. Status stays `pending_laptop` until a laptop report is attached.

The expansion calls dots3 only on deduped turns where the four arms disagree (attention rule, logged, seed gate, revised gate), cap `--max-calls 16` unique prompts, Anthropic `/v1/messages`, thinking disabled. Silence does not call. Same key path as `eval_live_dots3.py`. No invented scores if the preflight fails.

Pass, once the laptop file exists: on that disagreement set, revised-gate `label_agree` hits/scored is at least the logged arm's, and both scored counts are at least 8. Otherwise the live expand fails. Fewer than 8 scored turns is inconclusive, not a pass.

### E2 — leave one session out

Smoke rows excluded, double-fires dropped. For each remaining session, fit on the other sessions only. Split that train by timestamp, first 60% proposal and the rest the inner replay (at least one episode on each side). Evolve the seed library there. Score the untouched held-out session with the logged action, the seed gate, and that fold's revised gate.

A fold counts only if the held-out n is at least 8, the proposal n at least 5, and the inner replay n at least 4.

A fold regresses if `worse(logged, revised)` or `worse(seed, revised)` is set (disc or FNR up, balanced accuracy down, or coverage changed). A fold strengthens if it does not regress, revised disc is strictly below logged disc, and revised disc is less than or equal to seed disc.

E2 passes if no countable fold regresses and at least one strengthens. E2 fails the system if any countable fold regresses. Otherwise E2 is inconclusive.

### E3 — ablation of the two accepted edits

Libraries, gate mode, held replay = the 2026-10-09 session (the same split as `eval_ab.py`):

- seed (neither edit)
- `require_not_mid` only (false → true)
- `planning_ms` only (2000 → 1250)
- both, in that historical order

E3 passes if on the held replay `worse(seed, both)` is empty and both disc is less than or equal to seed disc. E3 fails the system if `both` or `require_not_mid` alone regresses versus seed on that replay. `planning_ms` alone versus seed is reported. It is a warning if it regresses, not a system failure, because that edit was not accepted against the seed by itself. A component is load-bearing when removing it strictly raises held disc.

### E4 — label-shuffle null

Permute `author_feedback` on the deduped non-smoke rows. Episode signals stay put.

E4a: 200 permutations, RNG seed 20261018. Score the frozen seed library and the shipped revised library. One-sided p = (1 + count of null discs less than or equal to the real disc) / (1 + 200). Lower disc is better. E4a passes if the revised library's pooled p is below 0.05.

E4b: 100 refits, RNG seed 20261019. Same session split as `eval_ab.py` (proposal before 2026-10-09, replay that day). Count accepted edits. E4b fails the system if the real accepted count is less than or equal to the median of the null accepted counts.

E4 passes if E4a passes and E4b does not fail. E4 fails the system if E4a fails or E4b fails.

### E5 — withhold autopsy

On the deduped non-smoke rows, W is the set where the revised gate says silence and the attention rule says speak or the log spoke. Compare the share of those rows whose author wanted silence (`should_have_silent`, `silent_right`, `silent_had_nothing`) with the same share among rows the rule would speak or the log spoke.

E5 passes if W has at least 3 rows, the wanted-silence rate in W is at least 0.5, and that rate is strictly above the base rate. E5 fails the system if W has at least 3 rows and the rate is below 0.5. Fewer than 3 rows is inconclusive.

### Suite

The offline suite fails the system if any of E2, E3, E4, E5 fails the system. It passes if all four pass. A mix of passes and inconclusives, with no system failure, is mixed. E1 does not change that offline verdict. Only a system failure writes the principle proposal. phi is not edited in any of these cases.

## This run

- Offline verdict: `system_fail`
- E1: `pending_laptop`
- Probe: `/workspace/cowrite/Cowrite-test/app/v3/logs/probe.jsonl`
- Deduped n: 32 (sessions: S-20261006-234611=19, S-20261009-103650=13)
- phi edited: no

| experiment | verdict | why |
|---|---|---|
| E1 live expand | `pending_laptop` | Hook only. The laptop executor fills results/e1_live_expand_report.json. |
| E2 leave-one-session-out | `system_fail` | S-20261009-103650: vs logged: disc worsened (0.3846 -> 0.4615); vs seed: disc worsened (0.3846 -> 0.4615) (accepted content_min.0->60, planning_ms.2000->1250) |
| E3 ablation of the two accepted edits | `pass` | pair does not regress versus seed on the held replay |
| E4 label-shuffle null | `system_fail` | real accepted count 2 is at or below the shuffle median 2.0 (fixed-library revised p=0.0299; that half of the bar is separate) |
| E5 withhold autopsy | `pass` | withholds are enriched for turns the author wanted silent |

### E2 folds

| held session | n | countable | revised disc | logged disc | seed disc | accepted | verdict |
|---|---:|---|---:|---:|---:|---|---|
| S-20261006-234611 | 19 | yes | 0.3684 | 0.6842 | 0.4211 | require_not_mid.False→True | `pass` |
| S-20261009-103650 | 13 | yes | 0.4615 | 0.3846 | 0.3846 | content_min.0→60, planning_ms.2000→1250 | `system_fail` |

### E3 held replay (2026-10-09)

| library | n | disc | fnr | bacc | load-bearing |
|---|---:|---:|---:|---:|---|
| seed | 13 | 0.3846 | 0.6667 | 0.5952 | — |
| require_not_mid | 13 | 0.3077 | 0.3333 | 0.6905 | yes |
| planning_ms | 13 | 0.3846 | 0.6667 | 0.5952 | no |
| both | 13 | 0.3077 | 0.3333 | 0.6905 | — |

### E4 null

- Real revised disc 0.3125, p=0.0299 (pass bar p<0.05). Real seed disc 0.4062, p=0.1244.
- Real accepted edits: 2. Shuffle median accepted: 2.0. E4b system-fail: True.
- Permutations: score 200 (seed 20261018), refit 100 (seed 20261019).

### E5 withhold set

- |W|=13. Wanted silence in W: 11/13 (rate 0.8462). Base rate on rule-or-logged speaks: 0.6129 (n=31).
- Silence contracts that withheld: coding_silence=7, not_started_silence=4, residual_silence=1. Gate kept a logged silence while the rule said speak: 1.

### E1 live expand

- Disagreement turns: 16. Cap 16 unique calls.
- Laptop command: `python3 eval_exp_suite.py --live --only e1`
- Endpoint: `http://note3-prev-api.askdiandian.com/v1/messages` model `dots3-note-prev`, thinking disabled.
- On this disagreement set, revised-gate label_agree >= logged label_agree and both scored n >= 8. Not judged until the laptop file exists.

Principle proposal written: `principle_revision_proposal.md`

