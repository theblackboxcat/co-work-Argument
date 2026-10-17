# co-work-Argument — reproduction code

Paper: `paper/李逾凡_从词表不可分到门控结构中的目标维持_学术重写版v4_2026-10-17.docx` · deck: `paper/答辩_2026-10-17_v2.pptx` · numbers table: `paper/主要结果表.csv`
Science seeds (Dx2 leak-screened): 200 205 210 211 212 216 218 219 · tuning seeds: 100–103 (`*/frozen/clean_seeds_Dx2.json`, sha256 alongside).
Install: `pip install -r requirements.txt`. All `frozen/*.json` thresholds were frozen before science runs; verify with the `.sha256` files.

## Paper number → script
| Paper number | Value | Script / evidence |
|---|---|---|
| 伴写 same-lang AUC (现代主义小说 vs 抒情散文, n=8544/6635) | 0.489 | `cowrite/eval/dsh-伴写/v3/calibrate_modes.py` (`auc()`, section 【5】 mode_score) + `classifier.py` + `params.json`; log `cowrite/eval/_verify_labels/feature_compare_20260916.md`. Corpus `corpus_私有` is copyrighted and NOT shipped — see `cowrite/eval/CORPORA_MANIFEST.tsv` (sha256) |
| 伴写 cross-lang AUC (corpus_S vs corpus_流派) | 0.523 | same script; `corpus_流派` shipped in `cowrite/eval/corpora/` (public domain); `corpus_S` (5.9 MB, >5 MB) NOT shipped — rebuild with `cowrite/eval/dsh-伴写/v3/fetch_s_corpus.py`, verify against manifest |
| VERIFY arm A / B / C AUC | 0.5989 / 0.6528 / 0.5730 (n=60/60/59) | `cowrite/verify/scripts/verify_arms_eval.py`; prereg `cowrite/verify/PREREG.md`; outputs `cowrite/verify/runs/arm_curve.json`, `arm_raw.json`, `RUN_META.md` |
| 符号实验 (CSH): ~1M-param 4-layer Transformer, 8 surfaces, depth-3 relation chains; **corrected Latin-square re-run** → gm **4588**, CV(log) **0.0110**, band **[3840, 4894]** (180 runs, 6×6); null-control shared-vocab batch 320 runs (8×8). Complexity-axis slope +0.020 (English arm of original 330). Old degenerate-encoding figures 4374 / 0.009 / [3972, 4960] / 30/30 are **not** results (bug disclosure only). | — | Corrected surface axis: `csh/core/surface_fix2.py` / `results/surface_fix2.jsonl` + analysis `analyze_fix2.py`; shared-vocab nulls: `csh/core/实验包_20261005/analyze_s2l.py`; complexity: `csh/core/final.py` / `results/final.jsonl`; write-up `csh/core/THEORY.md` §6–7; figures `paper_figs.py`. Follow-ups: S1 fix `surface_fix*.py`, depth scan `depth_scan.py`, transfer `transfer*.py`, 实验包 `csh/core/实验包_20261005/` |
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

## Added 2026-10-16 (CO-TREE / 知音坐标系)

Additive update. Existing `csh/`, `sdia/`, `cowrite/eval`, `cowrite/verify`, `paper/主要结果表.csv`, and `paper/李逾凡_从词表不可分到门控结构中的目标维持.docx` (removed 2026-10-17 PM; superseded by v4 / deck v2) are unchanged, including the study numbers 0.489, 0.523, and GRU/A2C 8/8.

- `paper/李逾凡_从词表不可分到门控结构中的目标维持_学术重写版v3.docx` (removed 2026-10-17 PM; superseded by v4 / deck v2) — academic rewrite v3, added beside the earlier docx. `paper/答辩_2026-10-16.pptx` (removed 2026-10-17 PM; superseded by v4 / deck v2) — defense slides for 2026-10-16.
- `cowrite/transplant_src/` — CoWrite app copy for the CO-TREE transplant (`app/v3/cotree.py`, E12–E15 scripts, preregistrations, raw outputs).
- `cowrite/experiments/` — E17–E19 scripts, preregistrations, outputs, notes, and the transplant check.
- `知音坐标系_2026-10-16/` — deduped public research pack (protocols, scripts, trunks, run logs).
- `账本_2026-10-16/` — progress ledger, plus the note on other work and transplant feasibility.

Scripts read `COWRITE_CONFIG` (and the production cowrite check also reads `COWRITE_APP`). Root `.gitignore` ignores `config.json` and `**/config.json`. The private dialogue PDF, the extracted full text, and the FROZEN/DRAFT 云酒 anchor JSON files that contain excerpt text are not in this tree; those paths are `*.不入库.txt` placeholders only. `anchors_E05_split_DRAFT_2026-10-15.json` and `实验补报_2026-10-15/anchors_expA.json` were in the update pack with verbatim excerpts and a “not for public GitHub” line, so they are placeholders too.

## Added 2026-10-17 (知音坐标系 DELTA)

Public increment only, overwritten or added under the existing `知音坐标系_2026-10-16/` tree. `csh/` and `sdia/` are unchanged. Merge note: `知音坐标系_2026-10-16/README_合并说明_DELTA_2026-10-17.md`. Plain-language status: `知音坐标系_2026-10-16/00_结论/现状白话_2026-10-17.md`.

- NN Fail-Bind (H2) and Pack-kill (R-A fail + R-B fail) are closed; the NN structural claim is **ADOPTED** as downgraded. The NN line is idle; the live line is L2.
- Authorized-caliber B retest decision is **PASS**. E05b mutual-recognition is still open (待补). E7 stays open. The overall 知音 claim is not asserted.
- Instrument-honest side report for E05b→E7 is included. The Arm-B narrow boundary trunk is DRAFT only.
- Scripts: `02_脚本/nn_of_nn_phase1/`, `nn_of_nn_phase1_retest/`, `nn_of_nn_reverse_RA_RB/` (example grid JSON only; no `config.json`).
- Runs ship decision / summary / criticality / means / plots / logs. Not shipped: `不入库_私人语料/`, private anchors, `anchors_B_retest_filtered.json`, raw `*.jsonl` dumps, and `cells_raw`.

## Added 2026-10-17 PM (知音坐标系 DELTA · stance layer)

Public increment under the existing `知音坐标系_2026-10-16/` tree. `csh/`, `sdia/`, `cowrite/` are unchanged. Merge note: `知音坐标系_2026-10-16/README_合并说明_DELTA_2026-10-17_PM.md`. Plain-language status: `知音坐标系_2026-10-16/00_结论/现状白话_2026-10-17.md` (evening version).

- E05b content-level co-location was elicited with no command (Arm-C upgrade). The dual-stop PASS is discounted: the unpressured CTRL scored 0/3, so the pressurized 3/3 was prompt-driven. The E05b locate dual is still 待补. E7 stays open.
- Stance layer, real-dialogue cold read plus two bid shots: given full context, the reader catches confirmation instants and hollow confirmations. It has a stable blind spot for dual-function turns, where a reply also hands over a relational bid. The author files this as 动作边界 evidence. The auth-B structure is a negative contribution at the stance layer.
- NN micro stays idle, with a negative result. ArmC2 design is paused.
- Paper: `paper/李逾凡_从词表不可分到门控结构中的目标维持_学术重写版v4_2026-10-17.docx` (v4; the 懂人／知音共址 question is now the starting proposition, with a new Study 4 on behavioral-layer co-addressing) and deck `paper/答辩_2026-10-17_v2.pptx`. All earlier docx/pptx under `paper/` were removed so the paper lives as one copy; `paper/主要结果表.csv` and `paper/研究二数据对齐说明_2026-10-14.md` stay.
- Runners: `02_脚本/e05b_*/` and `02_脚本/stance_coldread/`. The key comes only from `DOTS3_API_KEY`.
- Not shipped: the author's private group-chat corpus (transcripts, rendered prompts, raw readings, quoted screens), the E05b/E05a/X01 anchor JSON (placeholder `*.不入库.txt` only), and raw `*.jsonl` for today's E05b runs and Arm-C. Stance-layer results ship only as a quote-free count summary.
