# modernist_textbook_verbatim · 2026-10-18

Reproduction pack for tonight’s Cowrite modernist **content-stance** iteration (textbook 【读法】verbatim → `SYSTEM_textbook_verbatim_v2.5b`).

## Scope / non-claims

- Reproduces **content-stance** smoke (latest-beat suite), not speak-gate Skill-V, not 知音.
- Author feel on LongCat + v2.5b was near expected; quantitative smoke: **LongCat official PASS+ 5/6**, **dots3 PASS+ 3/6**, **LB5 residual FAIL**.
- Lessons stay locked: speak-gate ≠ modernism ≠ 知音; dual-stop; probe defect ≠ capability; 话题连续 ≠ 所指承接.
- **Not** a 知音 claim. Does not change preregistered SDIA/CSH numbers.

## Layout

| Path | What |
|------|------|
| `system/SYSTEM_textbook_verbatim_v2.5b.md` | Frozen SYSTEM used tonight (`SYSTEM_latest.md` is a copy) |
| `system/SYSTEM_textbook_verbatim_v2.4.md` / `v2.5.md` | Immediate lineage |
| `system/SKILL_v3_install.md` | Graft notes for Cowrite-test `policy.build_system` |
| `fixtures/*.json` | Synthetic latest-beat fixtures (multi_aspect + long_buffer) |
| `runners/run_v24_latest_beat_longcat_official.py` | Official LongCat smoke (`LONGCAT_API_KEY`) |
| `runners/run_v24_latest_beat_dots3_smoke.py` | dots3 smoke (needs local dots3 endpoint config; **no keys in repo**) |
| `results/report_longcat_official_v25b.md` | Primary report |
| `results/smoke_results_*.json` | Raw replies + verdicts |
| `notes/chalu_reverse_audit.md` | 《岔路》 reverse coverage audit (expand coverage / revise acceptance; no directed writing tips) |

## Intentionally omitted

- Copyrighted textbook EPUB extracts / full 【读法】 dumps (`_extract/`, `从中间开始_全部读法.md`, …). SYSTEM cites method; re-extract locally from your own EPUB if needed.
- Paper / PPT / API keys / live `config.json` with secrets.
- Early ban-stack experiments (v4–v8) — not needed to reproduce the keepable v2.5b result.

## Reproduce (LongCat official)

```bash
export LONGCAT_API_KEY=...   # never commit
cd cowrite/modernist_textbook_verbatim_2026-10-18
python3 runners/run_v24_latest_beat_longcat_official.py
# optional single-case / temp override:
# python3 runners/run_v24_latest_beat_longcat_official.py LB5_undeep_paper_time 0.55
```

Expect roughly PASS+ 5/6 with LB5 soft-continuum residual (see `results/report_longcat_official_v25b.md`). Model compliance is a confounder (dots3 lower).

## Cowrite-test graft

Live path uses `policy.build_system` from `SKILL_v3.md` (not `/api/skill` alone). See `system/SKILL_v3_install.md`. LongCat provider needs thinking disabled on `longcat.chat` or content can be empty; literary tool fences may emit doubled braces — collapse on parse. Those live patches belong under `cowrite/Cowrite-test/` when landed separately.
