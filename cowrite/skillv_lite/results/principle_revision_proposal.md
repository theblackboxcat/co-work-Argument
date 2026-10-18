# Principle revision proposal

The preregistered bar failed. This file proposes the principle change. It does not edit phi, bounds, or prompt text. Implement only after an executor verdict.

Offline verdict: `system_fail`.

## E2 — leave-one-session-out

A library fit on one session moved a session that never entered the evidence gate in the wrong direction (disagreement, false-negative rate, or balanced accuracy). Principle: a bound move is not a skill until it is non-regressive on a session the gate did not see. Proposed change: keep `revised_library.json` as an exploratory artifact and do not treat it as the skill to ship. Further bound search waits for a third labeled session. Existing phi stays locked. No contract is added here.

Measured: S-20261009-103650: vs logged: disc worsened (0.3846 -> 0.4615); vs seed: disc worsened (0.3846 -> 0.4615) (accepted content_min.0->60, planning_ms.2000->1250)

## E4 — label-shuffle null

The revised library is not distinguishable from shuffled labels, or the evidence gate accepts at least as many coordinate steps on shuffled labels as on the real ones. Principle: a disc drop on this probe is not yet evidence that the contracts track the author's silence. Proposed change: stop the bound search. The next change is the acceptance rule — a strict drop on the replay buffer, and at least two sessions outside the proposal slice — not a rewrite of phi.

Measured: real accepted count 2 is at or below the shuffle median 2.0 (fixed-library revised p=0.0299; that half of the bar is separate)

phi lock: unchanged. No API key is involved in this proposal.
