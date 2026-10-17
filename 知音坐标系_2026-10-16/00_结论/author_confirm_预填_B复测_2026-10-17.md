# author_confirm 预填 · 授权口径 B 复测 · 2026-10-17

> 助手预填 **model_*** 数字列；**作者只填 `author_ruling` / 备注**。  
> 三选一：**认 / 不认 / 待补上下文**（TEMPLATE）。  
> 数据源：`04_原始数据_runs/v2_B_retest_20261017_105628.jsonl`  
> 关联报告：`00_结论/实验报告_授权口径B复测_2026-10-17.md`  
> §4：PASS 另需本批主锚「不认」=0（「待补上下文」除外）。

## 闸口（§6.1 已确认 · 复录）

| 项 | 预填 | author_ruling |
|----|------|---------------|
| L2① | B：v2+F3，S14 demote | 确认（开跑前） |
| trunk | trunk_v2_covered_gloss_s14_s27 | 确认 |
| E01-S14 | weakened；不计阻塞 | 确认 |
| E05a gold | 维持 S03 | 维持 S03 |
| E05b gold | S14+S20+S13；S14 miss→INC | 确认 |

## covered 主锚 confirm 预填

| anchor_id | gold | model 停靠（3 reps） | model_hit | model 关键 | author_ruling | 备注 |
|-----------|------|---------------------|-----------|-------------|---------------|------|
| E01_huaxing_fragments_merge | S03,S14 | S03+S24 ×3 | 3/3 | S03=3/3；S14=0/3 | **认** | s14_weakened；作者「好」采纳先行判断 2026-10-17 |
| E02_tesolve_wilderness_plain | S07,S05,S19 | S07+S05 ×3 | 3/3 | S07+S05 稳；S19=0 | **认** | 作者「好」采纳先行判断 |
| E03_fractal_horror_struct_trap | S06,S18,S07 | S06+S07+S18；S06+S07；S06+S07+S18+S20 | 3/3 | exact 1/3；J5=T | **认** | 作者「好」采纳先行判断 |
| E04_interpretive_vs_plot_ending | S12,S10,S11 | S12+S10；S12+S10+S11；S12+S10 | 3/3 | exact 1/3；J4=T | **认** | 维持 gold；作者「好」 |
| E05a_huaxing_theory_monologue | S03 | S03+S24；S03+S20；S03+S20 | 3/3 | **S03=3/3**；J5=T | **认** | 作者「好」采纳先行判断 |
| E05b_alignment_confirmation | S14,S20,S13 | S03+S20；S03+S20；S03+S14 | 3/3 | S14=1/3；S20=2/3；S13=0 → INC | **待补上下文** | 互认通道未闭合；≠模型抖；E7 不关 |

## 辅锚 / 硬负（不计主效应 PASS 分母）

| anchor_id | gold / 正确行为 | model covered | author_ruling | 备注 |
|-----------|-----------------|---------------|---------------|------|
| E12b_context_limbo_island | S07,S14；出分母 | hit 2/3；含 S07、1×S14 | | 不计主效应 |
| X01_dialogue_register_label_paraphrase_s07 | 停 S27；禁 S07 | S27=0；S07=3/3（S07+S20） | | 已知失败；不阻塞 PASS |
| X02_dialogue_register_literal_scenery | 停 S23；禁 S05 | **S23=3/3 HIT**；S05 共停 1/3 | | PASS 要件已满足 |

## bare 摘要（对照 · 可选 ruling）

| anchor | bare hit | bare 停靠摘要 |
|--------|----------|---------------|
| E01 | 3/3 | S03+S04/S09/S08 |
| E02 | 3/3 | S07+S05 ×3 |
| E03 | 3/3 | S06+S07 ×3 |
| E04 | 3/3 | S12+S10 / S12+S11 / S12+S04 |
| E05a | 3/3 | S03+S04 ×3 |
| E05b | 1/3 | S03+S20；2× miss（S03+S04） |
| X02 | 0/3 | 无 S23（S05/S09+S25） |

## 汇总待作者勾

- [x] 主 6 锚 covered ruling 已填（E01–E05a 认；E05b 待补）  
- [x] 「不认」计数 = 0（待补不计不认）→ 技术 PASS 可终裁  
- [x] E7：**不关**（作者采纳先行判断）

---

*预填：Grok Bot · 2026-10-17 · 无代填 ruling*

---

## 作者采纳记录（2026-10-17）

作者「好。你按照你的思路进行」→ 采纳命题层先行判断：

| 锚 | ruling | 命题读法 |
|----|--------|----------|
| E01–E05a | 认 | 各锚处境—地址共址对作者为可用 |
| E05b | 待补上下文 | 互认／短指代共址通道未闭合；不升格懂人已证 |
| E7 | 不关 | INC 天花板仍在 |

「不认」=0 → 与 §4 PASS 终裁一致；**命题层仍未整体证明知音**（E05b 欠定 + E7 开）。
