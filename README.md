# co-work-Argument — reproduction code

Paper: `paper/李逾凡_从词表不可分到门控结构中的目标维持.docx` · numbers table: `paper/主要结果表.csv`
Science seeds (Dx2 leak-screened): 200 205 210 211 212 216 218 219 · tuning seeds: 100–103 (`*/frozen/clean_seeds_Dx2.json`, sha256 alongside).
Install: `pip install -r requirements.txt`. All `frozen/*.json` thresholds were frozen before science runs; verify with the `.sha256` files.

## Paper number → script
| Paper number | Value | Script / evidence |
|---|---|---|
| 伴写 same-lang AUC (现代主义小说 vs 抒情散文, n=8544/6635) | 0.489 | `cowrite/eval/dsh-伴写/v3/calibrate_modes.py` (`auc()`, section 【5】 mode_score) + `classifier.py` + `params.json`; log `cowrite/eval/_verify_labels/feature_compare_20260916.md`. Corpus `corpus_私有` is copyrighted and NOT shipped — see `cowrite/eval/CORPORA_MANIFEST.tsv` (sha256) |
| 伴写 cross-lang AUC (corpus_S vs corpus_流派) | 0.523 | same script; `corpus_流派` shipped in `cowrite/eval/corpora/` (public domain); `corpus_S` (5.9 MB, >5 MB) NOT shipped — rebuild with `cowrite/eval/dsh-伴写/v3/fetch_s_corpus.py`, verify against manifest |
| VERIFY arm A / B / C AUC | 0.5989 / 0.6528 / 0.5730 (n=60/60/59) | `cowrite/verify/scripts/verify_arms_eval.py`; prereg `cowrite/verify/PREREG.md`; outputs `cowrite/verify/runs/arm_curve.json`, `arm_raw.json`, `RUN_META.md` |
| 符号实验 (CSH): ~1M-param 4-layer Transformer, 8 surfaces, depth-3 relation chains, 330 runs → gm 4374, CV(log) 0.009, null band 3972–4960, slope +0.020 | — | `csh/core/final.py --seeds 6 --workers 11` (model `model.py`, surfaces `surfaces.py`, substrate `substrate2.py`, analysis `analysis.py`/`analyze_final.py`); raw `csh/core/results/final.jsonl` (330 rows); write-up `csh/core/THEORY.md` §6–7; figures `paper_figs.py`. Follow-ups: S1 fix `surface_fix*.py`, depth scan `depth_scan.py`, transfer `transfer*.py`, 实验包 `csh/core/实验包_20261005/` |
| CSH revision batch (v2): collision geometry, symbol binding SB2, pairing audit, orthogonal pool, distributional/confound, cross-surface XS | — | `csh/revision/*.py` (collision_geometry, symbol_binding, pairing_audit, pool_orthogonal, analyze_distributional, confound_report, analyze_pool, analyze_sb, analyze_xs, cross_surface, run_remaining); packaged run `csh/revision/CSH_补充包/机器7/` with `REVISION_LEDGER.md`, `rerun_shuffle.py`, `monitor_*.py`, results `results/*.json|md|jsonl` (COLLISION, SB2_ANALYSIS, PAIRING_AUDIT, POOL_ANALYSIS, DISTRIB, CONFOUND, XS_ANALYSIS) |
| GRU/A2C return-only 8/8 | Wilson [0.676,1] | `sdia/s1g/run_s1g_arm.py --arm G_RL_GRU`; summary `sdia/s1g/summary_S1g.json` |
| No-gate RNN same HP 0/8 | | `sdia/s1g/run_s1g_arm.py --arm G_RL_RNN` |
| Designated register 7/8 | | S1g arm `C` (same summary) |
| fair-RNN tuned 0/8 | | `sdia/fair_rnn/run_arm.py`, `scripts/run_tune.sh` → `select_tune.py` → `run_science_parallel.sh` → `summarize_fair_rnn.py`; `summary.json` |
| Nov gate 2/8 | | `sdia/s1f_nov_rate/run_arm.py`, `summary.json` (check seed set — see notes) |
| ES easy 8/8 / main 4/8 (seeds 205 210 211 212) | | `sdia/es_s1h/s1h2/s1h2_run_arm.py`, `s1h2_es_gru.py`, `summarize_s1h2.py`; S1h (VOID step-fix) in `sdia/es_s1h/s1h/` |
| E2 pressurized grid 1/8 | | `sdia/e2_e2b/E2_s2c_learnable/run_arm.py`, `scripts/run_science_parallel.sh`, `scripts/summarize_e2.py` |
| E2b ceiling 3/8 (200 205 212), specificity-fail 3/5, register 8/8 | | `sdia/e2_e2b/E2b_c4pp_permeability/` (`run_tune.sh`, `select_tune.py`, `run_science_parallel.sh`, `summarize_e2b.py`) |
| Leak probe (mean ≤0.30) / seed screening | | `sdia/leak_probe/run_dx2.py`; `calibration.json`, `dx2_full.json` |

## Added from the author's PC (2026-10-12)
- `csh/core/` — full 符号实验 body (from `%DSH_ROOT%/appearent/package/`, not a git repo). Of the 13 identical distribution copies under `实验包_20261005/分发包_4核|6台/机器N` only `分发包_4核/机器1` is kept, minus machine-distribution bundles (`bundles*/`, `分发包_*`), `__pycache__`, docx/pdf/zip builds. `csh/appearent_root/` holds the raw shard returns + merge script that sat beside `package/`.
- `cowrite/eval/` — AUC script (`dsh-伴写/v3/calibrate_modes.py`) and its deps, `samples.jsonl` + label/verify reports (`_verify_labels/`, private-text files removed), `CORPORA_MANIFEST.tsv` (path/bytes/sha256 of every corpus file), `corpora/corpus_流派/` (public domain).
- `cowrite/Cowrite-test/` — the whole Cowrite test build (launcher, `app/` server + v3 + web UI, licenses). Excluded: `runtime/` (bundled Python, 857 MB), `assets/models/` (TTS weights, 48 MB), `config.json` (ship `app/config.example.json`; set `DEEPSEEK_API_KEY` etc. env vars), browser profiles, pid/log/scratch files.
- `sdia/es_s1h/full_trees/` — complete S1h (`S1h_es_step_fix`) and S1h2 (`S1h2_es_select_fix`) trees with every per-seed `logs/result_arm_*.json`, `hist_*.json`, `tune/`. ES gene snapshots (`genes/*.npz`, weights) omitted.

## Not shipped (data)
| Item | Size | Why | Paper number |
|---|---|---|---|
| `corpus_S/` (28 files) | 5.9 MB | >5 MB; rebuild with `fetch_s_corpus.py` | cross-lang AUC 0.523 |
| `corpus_私有/` (9 works) | 5.6 MB | copyrighted private corpus | same-lang AUC 0.489 |
| `corpus/`, `corpus_非P/`, `corpus_流派非P/` | 0.5 MB / 27 KB / 11 KB | author/copyrighted text excerpts | calibration only |
All listed with sha256 in `cowrite/eval/CORPORA_MANIFEST.tsv`.

## Redaction
API keys removed (one real key found in `Cowrite-test/readme.txt` → `<YOUR_API_KEY>`); endpoint host → `<API_HOST>`; absolute paths → `%USERPROFILE%` / `%DSH_ROOT%` (set `DSH_ROOT` to your checkout).

Note: `%DSH_ROOT%/lir/文献/CSH论文_深度扫描更新_20261005/llm_feasibility/probe*.py` is a separate LLM-feasibility line, not CSH, and is not included.
