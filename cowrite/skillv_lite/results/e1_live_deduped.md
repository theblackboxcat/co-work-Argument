# E1 live dots3, deduped Round-1

Speak/silence plus the model call. Not a 知音 result. Not content-quality proof.

Reconstructed from the Round-1 verdict. The laptop bundle was not on this VM, so this file does not add arm-level latency, speak counts, or reply text.

| | |
|---|---|
| slice | deduped labeled turns |
| n | 32 |
| revised gate label_agree | 22/32 |
| seed gate label_agree | 19/32 |
| dots3_fail | 0 |

Revised label agreement is higher than the seed gate on this live set (22/32 > 19/32). Every dots3 call in the reported tally succeeded.

Endpoint used by the harness: `http://note3-prev-api.askdiandian.com/v1/messages`, Anthropic messages, thinking disabled. The key stays where `server.py` loads it.

Round-2 is a different run and is not included here. It has landed in `e2b_freeze_loso`, `e4b_shuffle200`, and `round2_index.json`.
