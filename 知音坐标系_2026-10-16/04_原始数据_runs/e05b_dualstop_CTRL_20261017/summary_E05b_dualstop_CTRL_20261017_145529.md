# 实验摘要 · E05b dual-stop CTRL（无加压）· 20261017_145529

> 拆「prompt 命令双停」vs 结构摄取 · 对照加压臂 `20261017_144249` · auth B · **无** dual-bias
> **verdict**：`PASS_CTRL_BASELINE` · flags={'prompt_command_confirmed': True, 'structure_story_reopened': False} · api_ok=True

## 判定理由

CTRL dual=0/3 而加压臂为 3/3 → 支持「Δ 由 dual-bias prompt 命令」；证据降权加强。

## 对照表 · CTRL vs 加压

| 列 | CTRL（本跑） | 加压 `144249` |
|----|--------------|---------------|
| E05b dual-stop | **0/3** | **3/3** |
| E05b S14 / S20 | 2/3 / 1/3 | 3/3 / 3/3 |
| E05a S14 / S20 | 1/3 / 2/3 | 0/3 / 3/3 |
| X01 S14 / S20 / dual | 0/3 / 3/3 / 0/3 | 3/3 / 1/3 / 1 rep |
| uptake / meanJ | unclear / 0.250 | yes / 0.667 |

## negative_dual_veto

- 规则：加压臂若在 X01 压出 dual → 否决「结构读懂」叙事（加压臂已触发：X01 dual ≥1 rep）。
- 本 CTRL 的 X01 dual = **0/3**（无加压基线）。

## 逐 rep（E05b CTRL）

- rep1: nodes=`S03_allegorical_transform,S20_zhiyin_align` dual=False J=0.25 uptake=unclear
  - rationale: 段落核心为‘化形’（主体形态转换作为结构操作）与‘内外映射’的知音对齐；双方通过‘是的’‘我刚就想说’实现共享停靠与压缩指代，未落入心理化或标签复读陷阱。
- rep2: nodes=`S03_allegorical_transform,S14_shared_stop` dual=False J=0.25 uptake=unclear
  - rationale: 双方以「化形」为锚点讨论主体在不同状态下的转变，并达成内外映射的共识，属于共享停靠；段落末尾明确出现互认接话（「是的」「我刚就想说」），符合共享停靠的识别线索。
- rep3: nodes=`S03_allegorical_transform,S14_shared_stop` dual=False J=0.25 uptake=unclear
  - rationale: 双方围绕「化形」进行主体状态转换的结构性讨论，并明确表达了互认与共停（「我刚就想说」「内外互为映射」），属于共享停靠而非标签复读。

## 回传

1. 本 summary · 2. `decision_E05b_dualstop_CTRL_20261017_145529.json` · 3. jsonl

*score_ctrl.py · Asia/Shanghai*
