# Skill-V-lite (cowrite speak/silence)

Pilot port of Skill-V (Ma et al., arXiv:2610.11781) onto cowrite's speak-or-silence decision. It does not add clauses to the system prompt. It does not test co-address.

The layer is off unless `SKILLV_LITE=1`. With the flag unset, `server.py` returns the attention result it already returned.

## What it does

Nine contracts in `contracts/library.json` freeze the speak/silence rules already in `attention.py`:

| contract | decision | seed boundary |
|---|---|---|
| `not_started_silence` | silence | doc and cursor under 40 |
| `reviewing_silence` | silence | cursor moved up, no new chars, pause ≥ 8s |
| `polishing_speak` | speak | ≥3 edits, or ≥2 jumps with an edit |
| `stuck_speak` | speak | pause ≥ 15s and no new chars |
| `coding_silence` | silence | mid-sentence, not at a boundary |
| `reprobe_mid_silence` | silence | mid-sentence and pause ≥ 8s probe |
| `planning_speak` | speak | pause ≥ 2s at a boundary, cursor at the end |
| `recontext_speak` | speak | same pause, cursor has text after it |
| `residual_silence` | silence | nothing earlier applied |

Each contract has a protected `phi` (the semantic claim), a procedure that only sets the speak bit, and a rubric of field checks. A revision may change a numeric or boolean bound. It may not rewrite `phi`.

Before a contract is allowed to decide, the applicability filter drops it only when a predicate fails on a field that was actually observed. A missing field stays uncertain. If a higher-priority contract is uncertain, the turn abstains and the previous speak bit is kept.

`SKILLV_MODE` defaults to `gate`: if the selected contract says silence, the turn is withheld; a contract that says speak does not force speech. `SKILLV_MODE=cascade` replaces the speak bit. Neither mode injects prompt text.

## Offline eval (no model)

The replay uses author feedback already stored in the probe log. It does not call dots3 or any other model. Cloud VMs that cannot reach dots3 can still run this.

```bash
cd cowrite/skillv_lite
python -m unittest discover -s tests
python eval_ab.py
```

Outputs:

- `results/ab_report.md` — baseline vs treated table
- `results/ab_report.json` — same numbers
- `results/revised_library.json` — seed library plus any gated bound changes

Primary comparison on the deduped labeled rows:

- logged action (what 丙 recorded)
- frozen attention speak bit (甲)
- Skill-V seed gate and seed cascade
- Skill-V gate and cascade after the evidence gate

The proposal slice is every labeled non-smoke session before 2026-10-09. The replay buffer is the 2026-10-09 session. A bound moves only when disagreement falls on the proposal slice and disc, FNR, and balanced accuracy do not worsen on the replay buffer.

Positive class = the author wanted silence. `disc = (FP+FN)/n`, `fnr = FN/(FN+TP)`, `bacc = (TPR+TNR)/2`.

`silent_had_nothing` counts as a desired silence in that table. The probe testkit's own confusion table counts it as a false positive; that table is printed separately and only for logged actions. The published precision 0.67 / recall 0.16 (n=7) is a different sample and is not overwritten.

Content-quality labels (`接受` / `太弱` / `太强` / `不对`) are not speak labels and are not used.

## Turn the flag on

From `cowrite/Cowrite-test/app` or `cowrite/transplant_src/app`:

```bash
# seed contracts, withhold only, no prompt changes
SKILLV_LITE=1 COWRITE_V3=1 python server.py

# boundaries accepted by the last offline run
SKILLV_LITE=1 SKILLV_LIBRARY=revised COWRITE_V3=1 python server.py

# replace the speak bit instead of only withholding
SKILLV_LITE=1 SKILLV_MODE=cascade COWRITE_V3=1 python server.py
```

`SKILLV_LIBRARY` accepts `seed` (default), `revised`, or a path to a library JSON. Keys are not read. The offline script does not open `config.json`.

`SKILLV_LITE` left unset keeps the existing 甲/乙/丙 path, including 丙's default of letting the model decide.

## dots3

This pilot's numbers come from the probe replay. A live dots3 call is not part of the comparison. If a later slice needs dots3 and the cloud VM cannot reach it, do not invent scores: record the URL and the error, and run that slice on the author's machine. Read the key the way `server.py` already does (`config.json` / the environment). Do not commit the key.

## 跑法

```bash
cd cowrite/skillv_lite
python -m unittest discover -s tests
python eval_ab.py
```

看 `results/ab_report.md`。打开试点：

```bash
cd cowrite/Cowrite-test/app
SKILLV_LITE=1 COWRITE_V3=1 python server.py
```

不设 `SKILLV_LITE` 时，伴写主路径与现在相同。
