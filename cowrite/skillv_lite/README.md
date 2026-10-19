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

## Validation (primary)

The primary path is the live dots3 harness plus `eval_exp_suite.py`. `eval_ab.py` stays as the offline disagreement table and does not replace this path.

```bash
cd cowrite/skillv_lite
python3 eval_exp_suite.py
python3 eval_live_dots3.py --slice replay --max-calls 12
```

Round-1 verdict is a **conditional keep**. `stuck_speak.require_not_mid` carries the held-replay gain. `planning_ms=1250` is weak on that held set. Live deduped E1 (n=32) has revised label agreement 22/32 against seed 19/32, with `dots3_fail=0`. Leave-one-session-out re-fit is unstable (holding out 2026-10-09 fails). The Round-1 shuffle null is p≈0.38, which is not a statistical crown. This is not a 知音 result and not content-quality proof. The stop rule was not met, so there is no principle-revision proposal.

Round-2 has landed. Freeze-bounds LOSO (E2b) is **2/2 PASS**. The 200-shuffle null (E4b) is still not extreme (two-sided p≈0.393); there is no statistical crown. Round-2 strengthens the conditional keep and does not upgrade it. `S-20261018-174656` was the release gate, not a new Skill-V measurement, so a third labeled Skill-V session is still missing. Files: `results/iteration_verdict.md`, `results/round2_index.json`, `eval_round2.py`.

If this VM cannot reach `http://note3-prev-api.askdiandian.com`, do not invent scores. Run the live commands on `LAPTOP-32CD28QL`, where `server.py` already loads the key.

```bash
python3 eval_exp_suite.py --live --only e1
```

## Live dots3 eval

This is the check that actually calls dots3. For each arm the harness decides speak or silence, then calls the model only when the arm says speak. Silence does not open a socket. Arms share one cache, so the same prompt is sent once. The call is Anthropic `/v1/messages` with thinking disabled, through `providers.chat`, the same path `server.py` uses.

Arms, in order: frozen attention speak bit (甲), the logged action (丙), the Skill-V seed gate, the Skill-V revised gate. The gate uses the logged speak bit as its prior. A silence contract can withhold that bit. A speak contract does not force a logged silence.

Default slice is the held replay (`--slice replay`, the 2026-10-09 session, n=13). Default budget is `--max-calls 12` unique HTTP calls across all arms. A speak left unsent after that budget is skipped, not scored as a failure.

The laptop run (host `LAPTOP-32CD28QL`, model `dots3-note-prev`, endpoint `http://note3-prev-api.askdiandian.com/v1/messages`) is in `results/live_dots3_report.md`. Connectivity was ok (~653 ms). All 12 unique calls succeeded. Headline, held replay:

| arm | n | speak | silence | abstain | called | ok | fail | speak_rate | label_agree | lat_ms_mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| attention rule (甲) | 13 | 10 | 2 | 1 | 10 | 10 | 0 | 0.769 | 7/12 | ~818 |
| logged (丙) | 13 | 12 | 1 | 0 | 11 | 11 | 0 | 0.923 | 8/13 | ~806 |
| Skill-V seed gate | 13 | 10 | 3 | 0 | 10 | 10 | 0 | 0.769 | 8/13 | ~811 |
| Skill-V revised gate | 13 | 7 | 6 | 0 | 7 | 7 | 0 | 0.538 | 9/13 | ~789 |

`label_agree` is the arm bit against author speak/silence feedback already on the row. It is not a 知音 score. These probe rows do not carry 接受/太弱/太强/不对, and the report does not invent them. Per-call reply text was not copied off the laptop and is not reconstructed in the report.

```bash
cd cowrite/skillv_lite
python3 eval_live_dots3.py --slice replay --max-calls 12
```

The key is read the way `server.py` already reads it. It is never written into the report.

1. `COWRITE_CONFIG` pointing at a json file, or `config.json` next to `cowrite/Cowrite-test/app/server.py` (or the transplant copy) when that file is a dots3 config.
2. Otherwise `DOTS3_API_KEY`. Optional `DOTS3_BASE_URL` and `DOTS3_MODEL`.
3. A missing or placeholder base URL becomes `http://note3-prev-api.askdiandian.com`. The model default is `dots3-note-prev`.

A DeepSeek `config.json` is not used, so that key is not sent to dots3. `config.json` is gitignored.

If the preflight POST to `/v1/messages` fails, the script writes the URL and the exact error to `results/live_dots3_report.md` and exits non-zero. It does not fill in latency or reply text.

A preflight from this cloud VM reached that URL and got HTTP 401 Missing API key (there is no key on the VM). That is not a scored run, and a timeout would not be one either. The committed report is the laptop run on `LAPTOP-32CD28QL`, which has the key `server.py` already loads.

Other flags: `--probe` (same `probe.jsonl` as the offline script), `--out`, `--timeout` (default 120s), `--probe-timeout` (default 20s), `--max-tokens` (default 256; `0` uses `v3/params.json`, 2048). `--slice proposal` or `--slice all` widens the episode set; the laptop numbers are `--slice replay`.

## Offline eval (secondary, no model)

The replay uses author feedback already stored in the probe log. It does not call dots3. It answers a different question (disagreement with the author label) and does not replace the live call above. Cloud VMs that cannot reach dots3 can still run it.

```bash
cd cowrite/skillv_lite
python -m unittest discover -s tests
python eval_ab.py
```

Outputs:

- `results/ab_report.md` — baseline vs treated table
- `results/ab_report.json` — same numbers
- `results/revised_library.json` — seed library plus any gated bound changes

Offline comparison on the deduped labeled rows:

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

# exploratory bounds. Round-1 keeps require_not_mid; planning_ms=1250 is weak on held.
SKILLV_LITE=1 SKILLV_LIBRARY=revised COWRITE_V3=1 python server.py

# replace the speak bit instead of only withholding
SKILLV_LITE=1 SKILLV_MODE=cascade COWRITE_V3=1 python server.py
```

`SKILLV_LIBRARY` accepts `seed` (default), `revised`, or a path to a library JSON. Keys are not read. The offline script does not open `config.json`.

`SKILLV_LITE` left unset keeps the existing 甲/乙/丙 path, including 丙's default of letting the model decide.

## 跑法

主检验是真的去调 dots3，再加上实验组。在作者的笔记本 `LAPTOP-32CD28QL` 上跑直播扩展。这台云主机没有密钥，预检打到同一 URL 得到 HTTP 401（Missing API key），不是一次计分。超时同样不能编造分数。密钥用 `server.py` 已经在读的 `config.json`，或 `COWRITE_CONFIG` / `DOTS3_API_KEY`。不要把密钥写进仓库。

```bash
cd cowrite/skillv_lite
python3 eval_exp_suite.py
python3 eval_exp_suite.py --live --only e1
```

Round-1 是有条件保留：`require_not_mid` 承担留出集上的收益，`planning_ms=1250` 在留出集上弱。直播去重 n=32 时，修订门 label 一致 22/32，高于种子门 19/32，`dots3_fail=0`。留一会话重拟合不稳（拿掉 2026-10-09 就失败）。打乱标签的零分布 p≈0.38，没有统计上的桂冠。这不是知音，也不是内容质量证明。停机规则没触发，所以没有原则修订提案。Round-2 已落地：冻住界的 LOSO（E2b）**2/2 通过**；200 次打乱（E4b）仍不极端（双侧 p≈0.393），没有统计上的桂冠。有条件保留因此更稳，但没有升级成强结论。`S-20261018-174656` 是放行关，不是新的 Skill-V 测量，所以仍缺第三个带标签的 Skill-V 会话。云主机够不到 `note3-prev-api.askdiandian.com` 时不要编造分数，回到 `LAPTOP-32CD28QL`。

```bash
cd cowrite/skillv_lite
python3 eval_live_dots3.py --slice replay --max-calls 12
```

结果在 `results/live_dots3_report.md`。离线对照不调模型，只作辅证：

```bash
python3 -m unittest discover -s tests
python3 eval_ab.py
```

打开试点：

```bash
cd cowrite/Cowrite-test/app
SKILLV_LITE=1 COWRITE_V3=1 python3 server.py
```

不设 `SKILLV_LITE` 时，伴写主路径与现在相同。
