# 设计 · 伴写／知音文献对照 · EMNLP 不对称 agency + Incipit 确认轮 · 2026-10-30

> **纸面设计笔记** · 不关任何开臂 · **不**把 E05b／Arm-C／ArmC2／dualstop 标成 CLOSED  
> 不进 `frozen/` · 不重跑 · 不改 author 已结算数字  
> 上游臂状态（只引用，不改判）：  
> - `设计_E05b_ArmC升级_elicitation判别_2026-10-17.md`（引出成立、判别卡态度层）  
> - `设计_ArmC2_态度层判别_2026-10-17.md`（**暂停**）  
> - `设计_E05b_dualstop杀臂_2026-10-17.md`（PASS 降权；定位 dual 仍待补）  
> - `回原命题_共址已成立层与未成立层_2026-10-17.md`

---

## 0. 为什么记这一页

周报材料把两篇伴写向文献标为 KEEP，可喂 **E05b／stance 指标设计** 与 **确认轮交互**，但必须落成「设计笔记」而非「臂已闭合」。本页只登记：可借的度量、与共址命题的对齐方式、以及**明确仍开着的口**。

---

## 1. 文献 A · Humans Introduce, Models Elaborate（EMNLP 2026）

- **题**：*Humans Introduce, Models Elaborate: Asymmetric Narrative Agency in Human-LLM Co-Writing*  
- **入口**：https://aclanthology.org/2026.emnlp-main.2002/  
- **核验**：Anthology 页存在（2026 EMNLP main）。  
- **主张（摘要层）**：HH / HA / AA 三条件对照；HA **不是** HH 与 AA 的中间态，而呈不对称——**人更常引入新颖且更持久的叙事材料，模型更常铺陈／稳定既有语境**。度量含 turn 级 valence adaptation、semantic novelty、transience、resonance。

### 1.1 可借度量 → 知音／E05b 词典（草案）

| EMNLP 度量 | 伴写／知音转写 | 可能挂靠的既有臂 |
|------------|----------------|------------------|
| **semantic novelty**（谁引入新材料） | 「引入」≈ 新停靠提议／新枝；人高 novelty、模型低 → 与 generate≠commit、模型作放大器同向 | Arm-C elicitation：谁在 (b) 自由文本里**先**给出可映射地址 |
| **resonance**（材料是否被后续轮接住） | 「共鸣／接住」≈ uptake；与共址「说到同一处」同族 | Arm-C (a) 有效接话引文；dual-stop 的「同 rep 共现」是更硬的结构版 |
| **transience**（材料是否很快消失） | 高 transience ≈ 假对齐／标签闪现（X01 族） | 负对照：标签复读被判 mutual 的失败模式 |
| **valence adaptation** | 态度／口气层；与 ArmC2「接内容 vs 接说法」同向 | ArmC2 **仍暂停**；本页**不**重开，只登记可对齐 |

**设计含义（不执行）**：若日后重开读者层臂，优先把「mutual」拆成 **Introduce 分**（novelty：是否引入可映射新所指）与 **Elaborate 分**（resonance：是否稳定对方已指），避免单一 mutual 票把「铺陈」误记成「互认」。

### 1.2 与共址命题的对齐句

> 知音共址要的是「双方指向同一处」；EMNLP 的不对称说明 HA 里**指向的发起权**往往在人，模型承担的是语境稳定化。E05b 切片上：引出成立 ≠ 态度层判别成立；「模型会铺陈」不能当成「模型已互认」。

### 1.3 明确不借／不越界

- 不把 HA 不对称写成「知音已证」或「懂人已达成」。  
- 不把 EMNLP 的故事写作任务直接等同于外源锚定位任务。  
- **开臂状态不变**：Arm-C 粗筛 FAIL／细读「引出成立、判别卡态度层」照旧；ArmC2 仍暂停；dual 定位仍待补。

---

## 2. 文献 B · Incipit 确认轮（arXiv:2609.31007）

- **题**：*Incipit: Axiom-Grounded Scaffolding for Human–AI Literary Creation*  
- **入口**：https://arxiv.org/abs/2609.31007  
- **核验**：arXiv 摘要页存在。  
- **可借点（交互／表述，非直接合入代码）**：  
  1. **五轮方向对话**，末轮为 **confirmation**，把 creative seed 固化后再进入匹配／蓝图；  
  2. 规划层（axiom → L1–L3 blueprint）可检视、可补丁；generate 前结构先行；  
  3. 文内已给 **prereg 三条件对照草案**（Direct / Plan / Axiom），且作者**明确未跑**用户研究——与我们「纸面 prereg、未开不跑」纪律同构。

### 2.1 映射到伴写／知音

| Incipit | 本仓库 | 备注 |
|---------|--------|------|
| confirmation 轮固化 seed | author confirm／手选提交（generate≠commit） | 可借鉴「末轮只确认、不继续发散」的交互文案 |
| 可检视 axiom / blueprint | 共享可寻址坐标系 + 小子图提议 | 容器不同（文学公理 ≠ 文化×时代树），纪律同：显式、可编辑、可拒绝 |
| Direct vs Plan vs Axiom 预注册 | 理论骨架 §6 最小可证伪；协议 v1 双臂 | 可参考其「拆开规划 vs 知识层」的对照写法；**不**标我们任何臂因此闭合 |

### 2.2 可写入 E05b 交互的一句（草案，未开）

若未来做「确认轮」小改版探针（须另开设计+「开」）：

> Turn_k 末增加 **confirmation 小题**：请用一句话复述「双方是否指向同一处／同一态度」；仅当确认项与 (a)(b) 细读一致时，才把该 rep 记入粗筛票——用于降低「铺陈流利」对 mutual 的虚高。

**现状**：本句**未实施**；不改变任何已跑 jsonl 的计分。

---

## 3. 开臂清单（保持打开 · 本页不得关闭）

| 臂／口 | 状态（引用既有页） | 本页动作 |
|--------|-------------------|----------|
| E05b 定位 dual | 待补 | 无 |
| Arm-C elicitation | 引出成立；判别粗筛未过；态度层卡点 | 仅登记 novelty/resonance 拆分设想 |
| ArmC2 态度层 | **暂停** | **不重开** |
| dualstop 杀臂 | 机器 PASS、证据降权 | 无 |
| 知音整体 | 不宣称已证 | 无 |

---

## 4. 下一步（仅登记，不执行）

1. 若作者要计量「人引入／模型铺陈」：先开一页 **prereg**（锚集合、novelty 操作化、与 Arm-C 三问的关系），再谈调用预算。  
2. 若作者要 confirmation 轮：先改纸面探针文案，**小流量试跑**须另说「开」。  
3. 文献条目可回链 `01_协议与理论/文献对照_树纲领是否已有_2026-10-15.md` 作附录指针（另 PR 时可补一行；本包已含本设计页）。

---

*docs plan B · 2026-10-30 Asia/Shanghai · 纸面 · 开臂保持打开*
