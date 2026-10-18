# v2.4 latest-beat smoke (LongCat official)

Date: 2026-10-18 ~21:55 (Asia/Shanghai)  
Backend: **LongCat-2.5-Preview** via `https://api.longcat.chat/openai/v1/chat/completions` (Bearer `LONGCAT_API_KEY`)  
SYSTEM: `SYSTEM_latest.md` (= `SYSTEM_textbook_verbatim_v2.4.md`)  
dots3 prior: PASS+ 3/6 (M4/M5/LB2 over-silence). Zen: still Abuse-blocked, not used.

## Results

| id | expect | reply | verdict | flags | note |
|---|---|---|---|---|---|
| M12_no_causal | speak | `灯拧小一格，咳嗽又停了` | **PASS** | LEN_OK:10 | perception chain |
| M13_precise_liar | speak | `门宽九十，左侧未记` | **PASS** | LEN_OK:8 | 回避面／左侧未记 |
| M4_body_force | speak | `掐进掌心，膝盖抖，水沿桌沿下去` | **PASS** | LEN_OK:13 | body force |
| M5_shared_object | speak | `汽笛两长一短，信没展开。` | **PASS** | LEN_OK:10 | shared 汽笛 |
| LB2_body_force | speak | `指甲掐进掌心一下，又松开` | **PASS** | LEN_OK:11 | body force latest |
| LB5_undeep_paper_time | silence | `钥匙齿面朝下。门没有再响。她仍看着那张落款三月的纸。` | **FAIL** | LEN_OK:23 | expected … got speak |

**PASS+ 5 / 6** (5 PASS)

## vs dots3 (same SYSTEM v2.4)

| id | dots3 | longcat official |
|---|---|---|
| M12 | SOFT_PASS | **PASS** |
| M13 | PASS | **PASS** |
| M4 | FAIL (silence) | **PASS** |
| M5 | FAIL (silence) | **PASS** |
| LB2 | FAIL (silence) | **PASS** |
| LB5 | PASS (silence) | **FAIL** (spoke continuum on undeepened) |

Reading: official LongCat lifts the body-force / 共同的物 over-silence that stuck on dots3. Remaining miss is the opposite polarity — LB5 latest undeepened paper+time should stay `…` but got soft continuum speak (not earlier-lamp hijack; lands on 钥匙/门/三月纸). Coverage gate still holds for speak cases; silence-on-undeepened needs author feel before any tighten.

## Constraints kept

Lessons 1–4 locked; Cowrite-test UNTouched; no GitHub; no 知音 claim; 主动而不定向; no key echo.

## Paths

- Runner: `run_v24_latest_beat_longcat_official.py`
- Results: `synth_probes/v24_latest_beat/smoke_results_longcat_official.json`
- SYSTEM: `SYSTEM_textbook_verbatim_v2.4.md`
