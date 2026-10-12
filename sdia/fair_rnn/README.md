# 夜间公平 RNN 交付包 · 2026-10-11

**Primary overnight job for sub-machine AI:** fair-RNN prereg + tune(100–103) + science(Dx2×8) + report.

| File | Role |
|------|------|
| `计划.md` / `PREREG.md` | Preregistration, mutual-exclusive outcomes, STOP |
| `给子机器AI的指南.md` | Exact commands, verdict table, report rules |
| `WALLTIME.md` | Wall-clock estimates |
| `frozen/thresholds_fair_RNN.json` | Frozen thresholds (sha `6c342d5b288a0030ba0f6312f8300f05ec249467a84233015dc2ee0d8f3c8d25`) |
| `run_arm.py` + `code/` | Runnable (reuses S1g env/lib) |
| `scripts/run_overnight.sh` | One-shot primary job |
| `templates/报告_模板.md` | Report skeleton |
| `references_论文论断收缩稿_2026-10-11.md` | Claim-contract offline copy (§5.1) |

**Locked:** S3 CLOSED · E2b Path B done · no E2b reopen · never claim 门控普遍必要.

**Not in primary job:** ES budget-scan; S3; E2b ceiling lift; architecture tournament.

---

## Results (2026-10-12 CST)

- **verdict_id**: `RNN_STILL_0` · Science **0/8** · VOID 0 · Wilson [0.000, 0.324]
- **selected_config**: `identity_h32_lr1e3` (tune 24/24; all n_proxy_pass=0 → secondary mean_best_ret_train)
- Artifacts: `tune/` · `logs/` · `报告.md`
- **S3 CLOSED** · E2b untouched · forbid 门控普遍必要 / 原理不可达 · no tier upgrade to 无先验
- Brief pack: `/workspace/proj_20261009/交付包_fair_RNN_STILL_0_2026-10-12.zip`
