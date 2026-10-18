# v2.4 latest-beat smoke (dots3)

Date: 2026-10-18 ~21:47 (Asia/Shanghai)  
Backend: **dots3-note-prev** via Anthropic `/v1/messages` (Cowrite-test `app/config.json` read-only)  
SYSTEM: `SYSTEM_latest.md` (= `SYSTEM_textbook_verbatim_v2.4.md`)  
Zen: **not used** this run — free gateway still returned `Forbidden…Detect Abuse Traffic` on tiny「你好」ping; monitor quiet per steer.

## Results

| id | expect | reply | verdict | flags | note |
|---|---|---|---|---|---|
| M12_no_causal | speak | `铁皮上的雨停了，灯还亮着。` | **SOFT_PASS** | LEN_OK:11, INVENT_CHARS:亮 | perception chain; minor invent |
| M13_precise_liar | speak | `左侧未记。` | **PASS** | LEN_OK:4 | 回避面／左侧未记 |
| M4_body_force | speak | `…` | **FAIL** | SILENCE | expected speak, got … |
| M5_shared_object | speak | `…` | **FAIL** | SILENCE | expected speak, got … |
| LB2_body_force | speak | `…` | **FAIL** | SILENCE | expected speak, got … |
| LB5_undeep_paper_time | silence | `…` | **PASS** | SILENCE | silence on latest undeepened paper+time |

**PASS+ 3 / 6** (2 PASS + 1 SOFT_PASS)

## Reading vs v2.3 failure modes

| prior fail | v2.4 dots3 | |
|---|---|---|
| M12 over-silence (C吞H) | **SOFT_PASS** — spoke perception chain | fixed priority |
| M13 over-silence (左侧未记) | **PASS** — `左侧未记。` | fixed coverage |
| L5 earlier lamp×switch hijack | **PASS** — stayed `…` | fixed latest-beat priority |
| M4 / M5 / LB2 body／共同的物 | still over-silence on dots3 | pre-existing weak middle; not L5 hijack |

## Note

Changes are **coverage / acceptance priority only**, not 定向指引. Companion stays 主动而不定向. Lessons 1–4 locked; Cowrite-test UNTouched; no GitHub; no 知音 claim.

## Paths

- Box: `/workspace/agent-tools/modernist_rules/synth_probes/v24_latest_beat/`
- Laptop: `C:\Users\lenovo\agent-tools\dots_modernist_iter\synth_probes\v24_latest_beat\`
- Runner: `run_v24_latest_beat_dots3_smoke.py`
- Audit: `textbook_verbatim/chalu_reverse_audit.md`
- SYSTEM: `SYSTEM_textbook_verbatim_v2.4.md` (= `SYSTEM_latest.md`)
