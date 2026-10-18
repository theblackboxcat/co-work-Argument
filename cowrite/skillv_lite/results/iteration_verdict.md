# Round-1 iteration verdict

**Conditional keep.**

The laptop result bundle was not on this VM (`/workspace/agent-tools/skillv_live_bundle/skillv_lite/results/`). This file restates the Round-1 verdict. It does not add measurements that were not in that verdict.

- `stuck_speak.require_not_mid` carries the held-replay gain.
- `planning_ms=1250` is weak on the held replay.
- E1 live, deduped n=32: revised-gate label agreement 22/32, seed-gate 19/32, `dots3_fail=0`.
- Leave-one-session-out re-fit is unstable. Holding out 2026-10-09 fails.
- Shuffle null p≈0.38. That is not a statistical crown.
- Not a 知音 result. Not content-quality proof (接受 / 太弱 / 太强 / 不对).

The stop rule was not met. There is no `principle_revision_proposal.md`.

phi stays locked. No API key is in these results.

## Round-2

Round-2 is still running on the laptop (`LAPTOP-32CD28QL`): freeze the LOSO fit, and 200 label shuffles. This commit does not invent those numbers. A later commit may land them.
