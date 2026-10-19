# E4b — Label shuffle null (n=200)

Δdisc = disc_revised − disc_seed (negative favors revised). Same code path as E4; n_shuffle=200.

- Labeled n=32; shuffles=200; rng_seed=20261018
- Seed disc=0.40625; revised disc=0.3125; observed Δ=-0.09375
- Shuffle Δ mean=-0.0271875 std=0.06437120741255363 min=-0.15625 max=0.15625
- Rank 11 / 200 ascending (percentile ≈ 5.0% from most negative)
- Empirical two-sided p≈0.39303482587064675 (|Δ|≥|obs|: 78/200)
- Empirical one-sided p(Δ≤obs)≈0.31840796019900497
- Null extreme-favor-revised at α=0.05: **NO**

## Histogram (coarse bins)

- Δ=-0.1560: 10
- Δ=-0.0940: 53
- Δ=-0.0310: 67
- Δ=+0.0310: 55
- Δ=+0.0940: 14
- Δ=+0.1560: 1
