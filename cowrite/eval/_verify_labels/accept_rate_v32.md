# 对照报告 · v3 冷启动第 1–2 步

同一批段落、同一个模型、同一套采样参数。唯一变量是策略。

**文明度**一栏＝「有没有指点感」的模型判定（C1–C5 + 整体姿态）：0 表示读起来像朋友，数字越大越像评审。

| 文本 | 模式 | 臂 | 输出字数 | 管道重写 | 禁令违规 | 文明度(模型) | 文明度(脚本) | 脚本禁令命中 | 句长KL | 字TTR |
|---|---|---|---|---|---|---|---|---|---|---|
| T001 | M | v3 | 72 | — | 未跑 | 6 C1_say_I、C2_admit_uncertainty、C4_real_question、C8_no_authoring_voice、C13_one_move、overall_instruction_feel | C6×1 | D10 no full paragraph×1 | 0.159 | 0.739 |
| T002 | M | v3 | 65 | — | 未跑 | 3 C1_say_I、C8_no_authoring_voice、overall_instruction_feel | — | — | 0.036 | 0.706 |
| T003 | M | v3 | 47 | — | 未跑 | 2 C8_no_authoring_voice、overall_instruction_feel | — | — | 0.118 | 0.854 |
| T004 | M | v3 | 94 | — | 未跑 | 3 C4_real_question、C13_one_move、overall_instruction_feel | — | — | 0.142 | 0.675 |
| T005 | M | v3 | 87 | — | 未跑 | 0 — | C6×1 | — | 0.154 | 0.738 |
| T006 | M | v3 | 65 | — | 未跑 | 0 — | C1×1、C5×1 | — | 0.053 | 0.786 |

## 模式分布

- M：6 条 — 混合：情节在推进，但保持现代主义质感，不滑向商业腔

> 自动层指标只能给信号，不能判定好坏。真正的判定是作者的反馈（logs/反馈表.md）。
> **v3.2 注**：22 条标注显示这张表里的「文明度」没有预测力（见 `logs/标注分析.md`），现在真正有信号的是反馈表里的「可能判太强／太弱」那三行。
