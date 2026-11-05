# 设计 · Reactive Writing · 先承重再建议 · 2026-11-05

> **纸面设计笔记** · 不关开臂 · **不**改数字／gold／frozen／AUC／CSH／SDIA  
> **不**把 E05b／E7 标成 CLOSED · **不**宣称知音／L2 已证 · **不**授权新臂  
> 不进 `frozen/` · 不重跑 · 不改 author 已结算数字  
> 上游（只引用，不改判）：  
> - `设计_NordiCHI2026_先承重与失败不可外包_2026-11-01.md`（先承重再动工；本页把建议收成一道门，不改那一页的顺序）  
> - `设计_WhoOwnsTheText_voice承重与provenance_2026-11-02.md`（决策点在建议出现之后；本页在建议之前）  
> - `设计_CHI2026_加蛋_措辞承重与概念公摊_2026-10-31.md`（措辞承重／概念公摊；本页不重划那一刀）  
> - `现状白话_2026-10-17.md`（E05b 定位 dual 待补；E7 开）

---

## 0. 为什么记这一页

NordiCHI 页登记何时交：先承重，再动工。Who Owns 页登记建议已经出现之后，接受或拒绝要在决策点上看见。这一页补的是更早的一道门。承重草稿先由人写下，建议才许出现。

脚手架在 `cowrite/reactive_order/`。它只记这个顺序，供分工伦理留过程证据。放在 `00_结论/`：这是对开臂的设计吸收，不是协议或理论骨架的修订。不结算任何臂。

---

## 1. 文献

两篇都只作设计输入。CHBAH 没有测「先有人稿再许建议」。CoWriter 没有这道拒绝门。下面的映射是本仓库的剪法。

### 1.1 Pennanen、Kanerva、Guckelsberger · CHBAH / OSF

- **题**：*How prompting and editing shape psychological ownership in AI-assisted creative writing*
- **作者**：Niki Pennanen，Pyry Kanerva，Christian Guckelsberger。Aalto 门户著录此序。OSF 预注册署名序为 Pyry Kanerva，Niki Pennanen，Christian Guckelsberger。
- **入口**：https://doi.org/10.1016/j.chbah.2026.100381 · *Computers in Human Behavior: Artificial Humans*，article 100381。门户著录 E-pub ahead of print，2026-08-22。
- **预注册**：*Effects of Prompting Style and Editing on Psychological Ownership in Human–AI Co-creative Writing*，https://doi.org/10.17605/osf.io/2su5t ，登记日 2026-01-30。
- **本页读到的文本**：Aalto 门户摘要，与 ScienceDirect 页上的同一段摘要。本环境未打开全文 PDF，不引表内均值。
- **做法**：预注册混合析因，N = 273。无 AI，或 AI 下单次提示对迭代提示，交叉可编辑／不可编辑。被试写的是短故事；编辑发生在生成之后。
- **摘要层可核**：编辑提高心理所有权，单次提示之后尤其明显。不能编辑时，迭代提示提高所有权；能编辑时，这条增益不再出现。作者把两条路写成部分可替代：控制感和自我投入落在过程的不同阶段。完全手写的所有权仍明显高于全部 AI 条件；按努力、感知故事质量和内在动机做的探索性协变量调整之后，这个缺口还在。文内的设计句：所有权要紧时，避开一次性把整篇交出去，让人既能掌舵，也能直接改写出来的文本。
- **摘要没有写的**：没有承重句，没有「草稿不在就拒绝建议」的门。本页不把这篇读成这道门已经测过。

### 1.2 Amar 等 · CoWriter

- **题**：*CoWriter: Guiding Methodological and Synergetic Human-LLM Co-Authoring*
- **作者**：Shmuel Amar，Benjamin Lieber，Ori Shapira，Debanjana Kar，Sebastian Maximilian Dennerlein，Yufang Hou，Ido Dagan
- **入口**：https://arxiv.org/abs/2610.31277 · arXiv:2610.31277
- **文本**：本页依据 arXiv HTML（2610.31277）。
- **做法**：探索性被试内，N = 14。每人一次 CoWriter，一次标准 LLM 对话加画布，写有来源的长文。CoWriter 用 Leader、Monitor、Reviewer 把人带过目标、头脑风暴、提纲、起草、审改。它主动邀请人参与。它不等人先写下承重句再放建议。
- **与本页相关的结果**（HTML 正文）：相对基线，作者感到文本更能照见自己的看法，文档所有权更高。成功的 agent engagement 合计 235 对 109，约 2.2 倍。愿意用自己的名字发表该文：11 人偏向 CoWriter，1 人偏向基线（p = 0.006）。外部读者把成稿评得更有 “human touch”（故事性、独特的个人经验）。摘要把这组成绩写成：用既有的人类写作实践把人留在过程里，对协同作者有益。
- **文内自己标明的边界**：探索性，小样本，一种长文任务。主动带流程，没有析因「承重草稿缺失时拒绝建议」。本页不搬 Leader，不开主动臂。只借一句压力：对话加画布容易把人留成事后监督；人还在场的时候，所有权和读者感到的人味一起动。

### 1.3 王焕超 ·《AI 写作是一种命运》

入口与取义同加蛋页、NordiCHI 页、Who Owns 页：https://www.baijing.cn/article/57165 。承重句的定义那几页已经登记，本页不重写。对准这一道门只用四句：

- **命运非选择题**。用还是不用，预设了一个可以退往的外部。外部不在了。CHBAH 的无 AI 格子、CoWriter 的标准对话，是那两篇里的测量对照。本页不把对照收成可以退回去的选项，也不用这道门去模拟「关掉 AI」。
- **分工伦理**。要回答的是交出去什么，留下什么。
- **承重句**。一旦被替换，整篇就无法成立的句子。先由人写下。这道门把「先」收成：草稿不在，建议不出。
- **公摊**。结构、过渡、流畅、可替换的说法。可以后交。建议若被放行，放行的是这一层。

### 1.4 已有三页（交叉，不重划）

加蛋页把 stylistic ownership 放在承重侧、conceptual contribution 放在易变公摊。NordiCHI 页的顺序仍是先承重再动工。Who Owns 页的 provenance 记的是建议出现之后的手选。本页不合并这三刀。它只加时间上的一格：建议这一格，排在承重草稿之后。

---

## 2. 映射

| 听到的 | 本页落点 |
|--------|----------|
| **承重句** | 人的承重草稿必须先在。`load_bearing_present` 为 false 时，门是 `block`，原因码 `missing_load_bearing`。没有草稿就试建议，记成 `suggest_blocked`。 |
| **公摊 fluency** | 草稿在了以后，流畅、可替换的建议才许出现。`suggest_allowed`，原因码 `ok_after_human_draft`。交出去的是这一层。 |
| **命运非选择题** | 门不问用不用模型。AI 写作已是处境。问的是顺序。 |
| **分工伦理** | 留下的是承重句。门开之后才谈得上把公摊流畅交出去。一行日志是这个分工的过程证据。 |

四相只描述这道顺序：

- `await_load_bearing`：承重草稿还不在，建议也还没试。门关着。
- `suggest_blocked`：草稿不在，建议试过。拒绝，并留下这一行。
- `load_bearing_ready`：承重草稿在了，建议还没出。门已开。
- `suggest_allowed`：草稿在场之后的建议。允许。

`span` 只收 before／after 的 sha256，或空串。不收正文，不收偏移。`notes` 最多 280 字。私人语料不入库。一行日志不是作者判决。

与 `cowrite/provenance/` 的分工：那边记建议出现之后的接受、拒绝、改后接受或丢弃。这边记建议许不许出现。生成不是提交，两处都还在。本页不改 provenance 脚手架。

---

## 3. 非主张（本页不得做的事）

| 口 | 既有状态 | 本页动作 |
|----|----------|----------|
| E05b 定位 dual | 待补 | **不关闭** |
| E7 | 开 | **不关闭** |
| 态度层／ArmC2 | 缺口；ArmC2 暂停 | 无。不重开 |
| 知音／L2 | 不宣称已证 | 无。不收成已证 |
| AUC、CSH、SDIA、结论表、结算数字、gold、`frozen/` | 已写入各页 | **不改** |
| 新实验臂 | 未授权 | **不授权**。没有操作句，没有新跑 |

CHBAH 的「手写所有权仍更高」留在那篇的测量里。本页不把它写成共址失败，也不写成这道门会把所有权买回来。CoWriter 的 2.2 倍参与和 11 对 1 留在那篇的探索性对照里。本页不把它写成知音前进，也不把它写成可以开一条主动带写的臂。

*纸面 · 2026-11-05 · 开臂保持打开 · 知音命题不宣称已证*
