# 实验报告 · E05b dual-stop CTRL · A/B 定案 · 2026-10-17

> **CTRL 机器闸**：`PASS_CTRL_BASELINE` · ts=`20261017_145529` · auth B · **无** dual-bias  
> **flags**：`prompt_command_confirmed=true` · `structure_story_reopened=false`  
> **E05b**：**待补**（撤回「补全候选」）· E7 开 · 不冻 Arm-B · 不宣称知音已证

---

## 0. 懂人／知音共址：两胜 · 一缺口

**胜①**：主靶 dual **0↔3** 的 Δ **锁定为 prompt 命令**（CTRL=Step3 回放；加压=命令齐出）。  
**胜②（更深）**：负样本上「互认节点粘性」**两边都是 3/3** —— 过触发来自 **S14/S20 gloss／语义边界**，不是 prompt。  
**缺口**：共址要真打开，下一枪必须打 **节点／gloss 边界**，不是再拧 locate 指令。

---

## 1. A/B 总表

| 列 | CTRL `145529`（无加压） | 加压 `144249` | Step3 `142455` |
|----|-------------------------|---------------|----------------|
| E05b dual-stop | **0/3** | **3/3** | **0/3** |
| E05b S14 / S20 | 2/3 · 1/3 | 3/3 · 3/3 | 2/3 · 1/3 |
| meanJ / uptake | 0.25 / unclear | 0.667 / yes | 0.25 / unclear |
| E05a S14 / S20 | 1/3 · 2/3 | 0/3 · 3/3 | 0/3 · 3/3 |
| X01 S14 / S20 / dual | 0/3 · 3/3 · **0/3** | 3/3 · 1/3 · **≥1 rep** | 0/3 · 3/3 · 0 |

**CTRL = Step3 精确回放**（dual／S14／S20／J／uptake 同构）→ 同批对照干净。

---

## 2. 胜① · prompt_command_confirmed

加压唯一自变量 = `COVERED_SYSTEM` dual-bias 段（trunk／anchors／providers 字节同）。  
CTRL dual **0/3** vs 加压 **3/3** → **Δ 归因 prompt 命令**。结构「自发齐出」叙事 **不重开**。  
加压机器 PASS **降权坐实**：可发射 ≠ 通道已打开。

---

## 3. 胜② · gloss 吸引（author 必录）

计 **任一** 互认节点（S14 **或** S20）粘上负样本：

| 锚 | CTRL | 加压 |
|----|------|------|
| E05a | **3/3** tagged | **3/3** tagged |
| X01 | **3/3** tagged | **3/3** tagged |

加压只做 **S14↔S20 挪位**（X01：CTRL 全 S20 → 加压变 S14 主导并压出 dual），**不减**假粘。  
**含义**：负向过触发 **≠** 来自 prompt；**S14/S20 gloss 本身**在吸这些文本（语义边界重叠）。  
冻边界谈话 → 改打 **node／gloss 边界**，别再调 prompt。

`negative_dual_veto`：加压已在 X01 压出 dual → 「结构读懂」否决成立；CTRL 下 X01 dual=0，更衬托「dual 齐出靠命令、假粘靠 gloss」。

---

## 4. 总判

| | |
|--|--|
| A/B | **定案**：prompt-command Δ 锁定 |
| 更深发现 | 负向过触发 = trunk／gloss 吸引 |
| E05b | **待补**（非补全候选） |
| 共址 | 可发射性已钉 · 结构摄取未钉 · 边界未清 |
| 下一枪 | **S14/S20 gloss 边界杀臂**（先纸面设计，等「开」） |

---

## 5. 原始指针

`04_原始数据_runs/e05b_dualstop_CTRL_20261017/`（decision／summary／jsonl · ts=`145529`）  
加压对照：`04_原始数据_runs/e05b_dualstop_20261017/`（`144249`）

---

## 一行

**命令 Δ 锁死 · 假粘在 gloss · E05b 回待补 · 下一刀砍边界。**

*Ollie · 2026-10-17 Asia/Shanghai · author 分析全文采纳 · 无编造*
