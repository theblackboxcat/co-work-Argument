# Skill-V-lite live dots3

Speak/silence decision, then a dots3 call only when the arm says speak.
This is not a co-address result. No 知音 metric is computed here.

## Run

- Status: `ok`
- Slice: `replay` (n=13)
- Model: `dots3-note-prev`
- Endpoint: `http://note3-prev-api.askdiandian.com/v1/messages`
- Host: `LAPTOP-32CD28QL`
- Source: Author laptop run of this harness against dots3-note-prev. Per-call reply text was not copied back and is not reconstructed.
- Connectivity: ok, latency ~653 ms
- Call cap: 12 unique calls / budget 12. Shared across arms. One HTTP call per distinct prompt. Silence does not call. A speak past the budget is skipped, not failed. Laptop run used the full budget: 12/12 unique calls, 0 failures.
- Key written: no. `key_present=True`.

Gate arms use predict(..., mode=gate): the logged speak bit is the prior, a silence contract can withhold it, and a speak contract does not force a logged silence. The attention-rule arm abstains when the log has no attention state. Under this harness order (rule, logged, seed gate, revised gate) and a shared 12-call budget, the unsent speak is the logged arm on spk-1791513631141-008. That matches the laptop called column (11) and is an accounting of the cap, not a stored model reply. Cloud VM preflight on 2026-10-18 reached the same URL in about 1.7s and returned HTTP 401 Missing API key. No generation was run from the VM.

## Arms

| arm | n | speak | silence | abstain | called | ok | fail | speak_rate | label_agree | lat_ms_mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| attention rule (甲) | 13 | 10 | 2 | 1 | 10 | 10 | 0 | 0.769 | 7/12 | ~818 |
| logged (丙) | 13 | 12 | 1 | 0 | 11 | 11 | 0 | 0.923 | 8/13 | ~806 |
| Skill-V seed gate | 13 | 10 | 3 | 0 | 10 | 10 | 0 | 0.769 | 8/13 | ~811 |
| Skill-V revised gate | 13 | 7 | 6 | 0 | 7 | 7 | 0 | 0.538 | 9/13 | ~789 |

`label_agree` is the arm bit versus the author speak/silence feedback already on the row. Abstain is not scored. `called` counts speak turns that received a reply, including a shared-cache hit. `fail` is a transport or API error. A speak left unsent because the budget was full is not a failure.

Content-quality labels already on these turns (接受/太弱/太强/不对): 0.

Speak/silence plus the dots3 call path on the held replay (2026-10-09, n=13). Not co-address. label_agree compares the arm bit with author_feedback already on the row. 接受/太弱/太强/不对 are not on these rows and are not invented. Arm lat_ms_mean values are the laptop-reported averages (~). Per-call samples are omitted on purpose.
