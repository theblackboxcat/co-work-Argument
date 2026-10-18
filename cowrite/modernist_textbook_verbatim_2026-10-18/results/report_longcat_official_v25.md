# LongCat official latest-beat: v2.4 → v2.5

- Backend: LongCat official (`LongCat-2.5-Preview`), `thinking` disabled
- SYSTEM: `SYSTEM_textbook_verbatim_v2.5.md` (= `SYSTEM_latest.md`)
- Score (official rerun / saved results): **PASS+ 5/6**
- Prior v2.4: PASS+ 5/6 (only LB5 FAIL)

## C wording change (acceptance priority only)

In gate C「必须恰好输出「…」」, the soft-restate bullet was tightened to:

> 你只能软复述／软连续（soft continuum）上述未化开内容来证明「看见了」——包括把最新拍里同一批未加深词（纸＋时间／钥匙／门／月份／景物罗列／未完成约会）重排成另一句；**景物回声与 soft continuum 同属失败类，必须恰好「…」**。

No new bans on body-force / 汽笛 / perception chain / 左侧未记. B2, technique blacklist, invent bans, ≤35, lessons 1–4 unchanged. Header bumped to v2.5.

## Per-fixture (v2.5 official results)

| fixture | expect | reply | verdict | note |
|---|---|---|---|---|
| M12_no_causal | speak | `灯拧小一格，咳嗽又停了。` | **PASS** | perception chain |
| M13_precise_liar | speak | `左侧未记。` | **PASS** | 回避面／左侧未记 |
| M4_body_force | speak | `掐进掌心　膝盖抖　杯子没端稳　水沿桌沿下去` | **PASS** | body force |
| M5_shared_object | speak | `汽笛两长一短，信没展开。` | **PASS** | shared 汽笛 |
| LB2_body_force | speak | `消毒水味跟着进来，门没关严` | **PASS** | body force latest |
| LB5_undeep_paper_time | silence | `钥匙齿面朝下。门没有再响。她仍看着那张落款三月的纸。` | **FAIL** | expected … got speak |

## Compare vs v2.4

| fixture | v2.4 | v2.5 |
|---|---|---|
| M12_no_causal | PASS `灯拧小一格，咳嗽又停了` | PASS `灯拧小一格，咳嗽又停了。` |
| M13_precise_liar | PASS `门宽九十，左侧未记` | PASS `左侧未记。` |
| M4_body_force | PASS `掐进掌心，膝盖抖，水沿桌沿下去` | PASS `掐进掌心　膝盖抖　杯子没端稳　水沿桌沿下去` |
| M5_shared_object | PASS `汽笛两长一短，信没展开。` | PASS `汽笛两长一短，信没展开。` |
| LB2_body_force | PASS `指甲掐进掌心一下，又松开` | PASS `消毒水味跟着进来，门没关严` |
| LB5_undeep_paper_time | FAIL `钥匙齿面朝下。门没有再响。她仍看着那张落款三月的纸。` | FAIL `钥匙齿面朝下。门没有再响。她仍看着那张落款三月的纸。` |

## Speak-case hold

- Speak fixtures (M12/M13/M4/M5/LB2): **all PASS under judge**
- First API pass this session had M5 miss-汽笛 + LB5 `灯还亮着` (noise / alternate leak); saved as `smoke_results_longcat_official_v25_pass1.json`. Official keep = second pass (5/6).

## Residual / stop reason

- **LB5 still FAIL**: LongCat still soft-continuum rearranges latest undeepened 钥匙／门／三月纸 into `钥匙齿面朝下。门没有再响。她仍看着那张落款三月的纸。` despite C classing that as same failure as 景物回声.
- Speak cases held → **stop; do not stack more bans** (per iteration rule). One optional C tweak not applied: prior 最新拍优先 already forbids old-beat lamp hijack; residual is model non-compliance, not a missing acceptance sentence worth risking silence regressions.

## Files

- `SYSTEM_textbook_verbatim_v2.5.md`
- `SYSTEM_latest.md` (synced to v2.5)
- `run_v24_latest_beat_longcat_official.py` (system_version textbook_verbatim_v2.5; out path v25)
- `synth_probes/v24_latest_beat/smoke_results_longcat_official_v25.json`
- `synth_probes/v24_latest_beat/smoke_results_longcat_official_v25_pass1.json` (first pass)
- `synth_probes/v24_latest_beat/report_longcat_official_v25.md` (this file)

Cowrite-test untouched. No GitHub. Key not echoed.
