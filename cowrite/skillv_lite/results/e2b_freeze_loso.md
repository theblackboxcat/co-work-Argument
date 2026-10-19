# E2b — Freeze-bounds LOSO (primary Round-2 read)

Freeze-bounds LOSO: for each session, score seed vs shipped revised_library.json with NO re-evolve on the complement. Round-1 re-fit evolve is secondary footnote only.

## Held `S-20261006-234611` (n=19) — **PASS**

| arm | n | disc | fnr | bacc | label_agree | abstain |
|---|---:|---:|---:|---:|---:|---:|
| logged | 19 | 0.6842 | 0.9286 | 0.5357 | 6/19 | 0 |
| rule | 18 | 0.4444 | 0.5000 | 0.6250 | 10/18 | 1 |
| seed_gate | 19 | 0.4211 | 0.5000 | 0.6500 | 11/19 | 0 |
| revised_frozen_gate | 19 | 0.3158 | 0.4286 | 0.7857 | 13/19 | 0 |

- disc 0.4211 → 0.3158; agree 0.5789473684210527 → 0.6842105263157895

## Held `S-20261009-103650` (n=13) — **PASS**

| arm | n | disc | fnr | bacc | label_agree | abstain |
|---|---:|---:|---:|---:|---:|---:|
| logged | 13 | 0.3846 | 0.8333 | 0.5833 | 8/13 | 0 |
| rule | 12 | 0.4167 | 0.8000 | 0.5286 | 7/12 | 1 |
| seed_gate | 13 | 0.3846 | 0.6667 | 0.5952 | 8/13 | 0 |
| revised_frozen_gate | 13 | 0.3077 | 0.3333 | 0.6905 | 9/13 | 0 |

- disc 0.3846 → 0.3077; agree 0.6153846153846154 → 0.6923076923076923

## Summary

- Sessions passing primary: **2 / 2**
- All sessions pass: **True**
- Pooled deduped: seed disc=0.4062 agree=19/32; revised disc=0.3125 agree=22/32

## Footnote (re-fit, secondary)

Round-1 E2 re-fit: hold 10-06 PASS, hold 10-09 FAIL when evolve accepted recontext content_min. That instability is why freeze is the primary Round-2 read.
