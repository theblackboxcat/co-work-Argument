# E2c — Need a third labeled session

**No third labeled speak/silence session found** on laptop or box probes.

## What was searched

- `../logs/probe.jsonl`
  - labeled: {'S-20261006-231325': 10, 'S-20261006-234611': 23, 'S-20261009-103650': 17}
  - unlabeled speak/silence rows by session: {'S-20261009-103650': 2, 'S-20261009-112609': 1}
- `/workspace/repro_repo_candidate/cowrite/Cowrite-test/app/v3/logs/probe.jsonl`
  - labeled: {'S-20261006-231325': 10, 'S-20261006-234611': 23, 'S-20261009-103650': 17}
  - unlabeled speak/silence rows by session: {'S-20261009-103650': 2, 'S-20261009-112609': 1}
- `/workspace/uploads/pc/cowtest/app/v3/logs/probe.jsonl`
  - labeled: {'S-20261006-231325': 10, 'S-20261006-234611': 23, 'S-20261009-103650': 17}
  - unlabeled speak/silence rows by session: {'S-20261009-103650': 2, 'S-20261009-112609': 1}
- `/workspace/uploads/cowrite_tree/app/v3/logs/probe.jsonl`
  - labeled: {'S-20261006-231325': 10, 'S-20261006-234611': 23, 'S-20261009-103650': 17}
  - unlabeled speak/silence rows by session: {'S-20261009-103650': 2, 'S-20261009-112609': 1}
- `/workspace/agent-tools/skillv_live_bundle/skillv_lite/../../repro_repo_candidate/cowrite/Cowrite-test/app/v3/logs/probe.jsonl` — missing
- `C:\Users\lenovo\AppData\Local\Temp\skillv_live\skillv_live_bundle\logs\probe.jsonl` — missing

## Known real labeled sessions (only two)

- `S-20261006-234611`
- `S-20261009-103650`
- Smoke fixture excluded: `S-20261006-231325`

Other sessions exist in the probe but **lack `author_feedback`** (e.g. `S-20261006-231622`, `S-20261006-235323`, `S-20261008-*`, `S-20261009-112609`). They cannot enter holdout tables.

## Required log format for a third session

Append rows to `probe.jsonl` (JSONL, UTF-8), one object per line, with:

```json
{
  "ts": "2026-10-XXT..",
  "session": "S-YYYYMMDD-HHMMSS",
  "kind": "spoke" | "silence",
  "event_id": "spk-... or sil-...",
  "attn_state": "CODING|PLANNING|STUCK|...",
  "attn_signals": { "pause_ms": ..., "mid_sentence": ..., "...": ... },
  "author_feedback": "should_have_silent|should_have_spoken|silent_right|silent_wrong|silent_had_nothing",
  "text_len": 123,
  "text_head": "optional preview"
}
```

Constraints:

- `kind` must be `spoke` or `silence`.
- `author_feedback` must be one of the five semantic labels above (content-quality labels like 接受/太弱 are **not** speak outcomes).
- Prefer a **new** `session` id not equal to the two known real sessions.
- Include `attn_signals` when possible so the gate does not abstain.
- After logging ≥8–12 labeled rows on a new day/session, re-run `eval_round2.py` / E2b to strengthen or weaken the freeze-LOSO claim.
