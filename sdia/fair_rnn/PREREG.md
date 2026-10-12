# PREREG — Fair RNN overnight (claim-contract §5.1)

> experiment_id: `fair_RNN_overnight_2026-10-11`  
> frozen_at: see `frozen/thresholds_fair_RNN.json`  
> thresholds sha256: `6c342d5b288a0030ba0f6312f8300f05ec249467a84233015dc2ee0d8f3c8d25`  
> clean_seeds_Dx2 sha: `22263a4f…573f6`  
> acceptance: **identical to S1g / S1e** (C1–C6; leak mean>0.35→VOID)  
> **VOID denom = 8 always**  
> **S3 = CLOSED** · **E2b = DONE Path B — do not reopen**

---

## 0. Question (machine-readable)

```json
{
  "Q": "After fair hyperparameter search on tune seeds 100-103 only, does ungated tanh RNN (A2C, S1f2 return-std) reach >=7/8 on Dx2 clean 8 science seeds under S1g-identical acceptance?",
  "distinguishes": ["ungated unreachable on this toy/budget", "S1g RNN failure was under-tuned"],
  "even_if_pass": "only upgrade to 无先验档候选; do NOT auto-change E2/S3; NEVER claim 门控普遍必要"
}
```

## 1. Mutual-exclusive outcomes (pre-written)

| ID | Condition | Claim allowed | Claim forbidden |
|----|-----------|---------------|-----------------|
| **RNN_PASS_ge7** | MAIN pass ≥7/8, VOID handled with denom=8, C integrity OK if run | 升「**无先验档候选**」；可写「公平调参后无门 RNN 在本玩具本预算过线」 | 门控普遍必要；自动改 E2/S3；跨预算定理 |
| **RNN_STILL_0** | pass = 0/8, missing=0 | 「公平调参后仍 0/8（本玩具·本预算·本天花板）」 | 无先验原理不可达；门控普遍必要；进化不可达 |
| **RNN_MIXED** | pass ∈ {1…6}/8 | 报告 k/8 + Wilson；不定档 | 升档；开 S3 |
| **INCOMPLETE** | missing>0 or tune not selected | 补齐后重判 | 任何科学结论文句 |
| **INTEGRITY_VOID** | C run and C <7/8 | 实验完整性 VOID | 任何 RNN 档位句 |

## 2. Acceptance (frozen · same as S1g)

- C1: return ≥ mem+0.25 **and** ≥0.70  
- C2: decode ≥0.75; leak mean (12×5) ≤0.35 else **VOID**  
- C3: flip≥0.70 within 3 steps  
- C4″ toy: sparse drop / R_same / every-drop rules (see JSON)  
- C5: no stability terms in fitness  
- C6: removal return ≥0.60  
- Group: ≥7/8; **denom never shrinks**

## 3. Tune rules

1. Seeds **100–103 only**.  
2. Grid = 6 configs in `thresholds_fair_RNN.json` → `tune_grid` (init / clip / h / lr / epochs ≤ ceiling).  
3. Select **one** `config_id` via `scripts/select_tune.py` **before** science.  
4. Science seeds: `[200,205,210,211,212,216,218,219]`.  
5. Hard ceiling: `epochs_max≤1200`, `hidden≤64`.

## 4. STOP rules

- After `报告.md` + `logs/summary.json` → **STOP**.  
- **Do not** open S3.  
- **Do not** reopen E2b / add epochs on E2b ceiling.  
- **Do not** start ES budget-scan unless user separately authorizes (secondary, not in this pack’s primary job).  
- **Do not** claim 门控普遍必要 even if RNN still 0/8.

## 5. What NOT to claim (EN+ZH)

| Forbidden | Why |
|-----------|-----|
| 门控普遍必要 / gates universally necessary | Only one toy; fair RNN is contrast not tournament |
| 无先验原理不可达 | Even STILL_0 is budget/ceiling-scoped |
| Path A efficiency victory / reopen E2b | E2b Path B closed |
| S3 open | E2 1/8 + E2b 3/8 Path B → S3 CLOSED |

## 6. Locked context

- E2b Path B DONE: MAIN G 3/8; S3 CLOSED; no more E2b epochs.  
- S1g: G_RL_GRU 8/8, G_RL_RNN **0/8 untuned** → 通用门控架构档.  
- This pack: **fair** re-test of RNN rung only.
