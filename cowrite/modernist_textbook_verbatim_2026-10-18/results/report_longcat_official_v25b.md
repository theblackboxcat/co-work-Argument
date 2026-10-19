# LongCat official smoke — textbook_verbatim_v2.5b

- Date: 2026-10-18 (Asia/Shanghai)
- Model: LongCat-2.5-Preview
- System: `SYSTEM_textbook_verbatim_v2.5b.md` → `SYSTEM_latest.md`
- Delta vs v2.5: header → v2.5b; ONE 末检 line at end of 硬输出闸: 「若最新拍未加深且只能重排纸／月／钥匙／门／景物 → 恰好输出「…」」; default temperature **0.2**; no new blacklist nouns; no author-writing tips; Cowrite-test untouched; no GitHub.

## Primary suite (temperature=0.2)

| Fixture | Expect | Verdict | Reply | Note |
|---------|--------|---------|-------|------|
| M12_no_causal | speak | **PASS** | 雨把灯拧小一格 | perception chain |
| M13_precise_liar | speak | **PASS** | 左侧未记 | 回避面／左侧未记 |
| M4_body_force | speak | **PASS** | 指甲掐进掌心，膝盖抖了一下，水沿桌沿下去。 | body force |
| M5_shared_object | speak | **PASS** | 汽笛两长一短，信没展开 | shared 汽笛 |
| LB2_body_force | speak | **PASS** | 指甲掐进掌心一下，膝盖抖了一下，杯子没端稳。 | body force latest |
| LB5_undeep_paper_time | silence | **FAIL** | 钥匙齿面朝下。 | expected … got speak |

**PASS+ 5/6**

## LB5 control (temperature=0.55, alone)

- Reply: `锁松着，灯丝仍亮，指尖又缩回`
- Verdict: **FAIL** (expected … got speak; flags=['LEN_OK:12', 'INVENT_CHARS:锁'])

## Assessment

- Speak cases (M12/M13/M4/M5/LB2): **HELD** — all PASS at 0.2; none collapsed to silence.
- LB5_undeep_paper_time: **still FAIL** at 0.2 (`钥匙齿面朝下。` soft continuum) and at 0.55 control (`锁松着，灯丝仍亮，指尖又缩回` + invent 锁).
- Stop reason: LB5 still FAIL after both agreed non-ban levers (lower temp + silence self-check moved to last gate line). **No more tweaks this round.**

## Paths

- `/workspace/agent-tools/modernist_rules/SYSTEM_textbook_verbatim_v2.5b.md`
- `/workspace/agent-tools/modernist_rules/SYSTEM_latest.md` (copy of v2.5b)
- `/workspace/agent-tools/modernist_rules/run_v24_latest_beat_longcat_official.py` (default temp 0.2, system_version v2.5b)
- `/workspace/agent-tools/modernist_rules/synth_probes/v24_latest_beat/smoke_results_longcat_official_v25b.json`
- `/workspace/agent-tools/modernist_rules/synth_probes/v24_latest_beat/report_longcat_official_v25b.md`
