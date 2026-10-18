# E3 ablation, Round-1

**Conditional keep.** `stuck_speak.require_not_mid` carries the held-replay gain. `planning_ms=1250` is weak on that held set.

The laptop bundle was not on this VM. The table below is the ablation already computed on this branch (held replay = 2026-10-09, n=13, gate mode). It is the same claim as the Round-1 verdict, not a new sample.

| library | n | disc | fnr | bacc | on the held set |
|---|---:|---:|---:|---:|---|
| seed | 13 | 0.3846 | 0.6667 | 0.5952 | baseline |
| require_not_mid only | 13 | 0.3077 | 0.3333 | 0.6905 | carries the gain |
| planning_ms=1250 only | 13 | 0.3846 | 0.6667 | 0.5952 | weak (ties seed) |
| both | 13 | 0.3077 | 0.3333 | 0.6905 | same disc as require_not_mid alone |

Not a 知音 result. Not content-quality proof.
