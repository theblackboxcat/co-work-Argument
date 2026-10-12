# PREREG · 提示词/框架上界 · 主动性衔接 VERIFY

> **冻结日**：2026-10-12 Asia/Shanghai（CST）  
> **性质**：预注册 · DOC ONLY 至语料可达 · **禁止假装臂已跑**  
> **姊妹件**：`计划.md` · `证据锚点_已发表数字.md` · `给子机器或本机的跑法.md` · `衔接论证草稿.md`  
> **上游锁定**：`必要性重建/决策层/ClaimBoundary_Q1_2026-10-12.md`（S3 CLOSED；不升档）

---

## 0. Status

| 项 | 状态 |
|----|------|
| 预注册本文 | **FROZEN**（本文件） |
| 臂 A/B/C/D 实测 | **A/B/C 已跑**（2026-10-12 CST · 近似 prompt-ablation · 见 `结果_臂曲线.md`）；**D 未跑** |
| Live AUC 曲线 | **已写** · `runs/arm_curve.json` · A=0.5989 / B=0.6528 / C=0.5730（n=60/60/59） |
| S3 | **CLOSED**（不变） |
| Q1 keepable claim | **不变**（不升级） |

---

## 1. Claim under test（唯一检验句）

**在固定模型 + 固定词表/词法特征实现下，叠加提示词与框架（铁律、注意力、文明度等）不会把「自动复现作者状态（P/M/S 或判层）」的天花板抬到特征可分性之上。**

EN（locked sense）：*Under fixed model and fixed lexical-feature implementation, stacking prompts/frameworks does not raise the ceiling of automatic reproduction of author state (P/M/S or judgment-layer) beyond feature separability.*

**NOT under test（立刻禁写）**：

- 「理解此人 / understanding the person」已达成  
- CSH 已否证提示词路线（CSH 仅作结构优先旁证）  
- 无限堆 prompt 可突破可分性  
- 自主设定已证 / 重开 S3 / 升级 keepable SDIA 论断

---

## 2. Arms（固定顺序；D 可选且非无限堆 prompt）

| Arm | 内容 | 允许变什么 | 禁止变什么 |
|-----|------|------------|------------|
| **A** | bare model | 仅底座模型调用 | 无铁律/无 policy/无注意力/无文明条款注入 |
| **B** | iron-laws + policy prompts | 三条铁律 + v3 `policy.py`/`SKILL` 类提示词组装 | 模型权重、词表特征实现、标注真值 |
| **C** | iron-laws + attention + civility full framework | B + 注意力机制 + C1–C13 文明条款 + 判层/⊘ 工作流 | 同上；不得另换特征空间冒充「提词有效」 |
| **D**（optional） | structure / feature change | 改特征实现、改输入结构、或换可分性相关归纳偏置 | **不是**无限 prompt stacking；若跑 D，必须单独报告为「结构臂」 |

**对照逻辑**：A→B→C 测 *prompt/framework stacking*；若增益停滞即 STOP。D 若存在，回答的是「换结构能否抬天花板」，与「堆提示词」主张正交。

---

## 3. Metrics

| 指标 | 定义 | 备注 |
|------|------|------|
| **AUC** | 对作者标签（P/M/S 代理轴或判层标签，预注册时锁定一种主标签）的 ROC-AUC | 主报告量；与已发表同语言/跨语言 AUC 同口径优先 |
| **Accuracy** | 相对作者标签的准确率 | 次要；类别不平衡时须同框报告基线 |
| **Δ(adjacent)** | AUC_B−AUC_A；AUC_C−AUC_B；（若有）AUC_D−AUC_C 或相对最近 prompt 臂 | 相邻臂增益 |
| **Diminishing-return STOP** | 若连续 **2** 步相邻增益 **< δ**，停止继续堆框架 | **δ := 0.02 AUC**（预注册默认） |

**标签口径（冻结）**：

- 主标签优先：作者手选 / 已标注的 **P/M/S**（或论文 §4.2 的问题驱动–故事驱动代理轴）。  
- 副标签（若样本够）：判层 A/B/C/⊘。  
- 两批标注口径不同者 **分开报告、不合并**（对齐《主动而不定向》§5.1）。

---

## 4. Anchors already-reported（必须引用为已发表，不得当作本 VERIFY 新发明）

见 `证据锚点_已发表数字.md`。摘要：

| 锚点 | 数字 | 源 |
|------|------|-----|
| 同语言 AUC | **0.489** | 《主动而不定向》§4.2 / 摘要 |
| 跨语言 AUC | **0.523** | 同上 |
| 负标注率 | **~31.8%**（22 条；三批合计 28 条 → 32.1%） | §5.1 |
| 文明度预测效度 | **无** | §5.2 / 摘要 |
| 沉默 prec / recall | **0.67 / 0.16**（**n=7**） | §3.6 / §5.1 |
| 单次重写成功率 | **~2/3** | §3.6 / §5.3 |
| CSH CV(log) | **0.009** | 《认知基底假说》· **旁证 only** |

---

## 5. Autonomy bridge table（SDIA · keepable 口径 · 禁止升级）

| 节点 | 锁定数字 | 本 VERIFY 用法 |
|------|----------|----------------|
| **S1g** | **8/8**（Wilson [0.676, 1.000]；VOID 0） | 门控档：维持并因果使用 env-cued goals 的存在性锚 |
| **E2b Path B** | **3/8** | 加压世界仅存在性；非组过 |
| **RNN STILL_0** | **0/8**（Wilson [0, 0.324]） | 公平无门控对照失败；**不得**写成门控普遍必要 |
| **S3** | **CLOSED** | 本 VERIFY **不得重开** |

桥接句（允许）：*若提示词臂曲线在特征可分性附近饱和，则「理解作者状态」不能靠堆框架解决，主动可行设计应把判别权留在作者 / 把能力建在结构（对齐 SDIA 门控档已证、S3 仍闭）。*  
桥接句（禁止）：自主设定已证；理解已达成；CSH 否证了提示词；升无先验档。

---

## 6. FORBID（写进即违规）

1. 声称 **CSH 已否证提示词**（CSH = 表面符号不移动阈值的旁证，不是本伴写任务的否证实验）。  
2. 声称 **understanding / 理解此人已达成**。  
3. **开放 S3** 或把本 VERIFY 写成 S3 实验。  
4. **升级** keepable SDIA 论断（S1g/E2b/RNN/S3 口径）。  
5. 把 **未跑臂** 写成已测数字。  
6. 用 Arm D 的结构改动冒充「提示词堆叠有效」。  
7. 合并口径不同的标注批。  
8. 把沉默 n=7 读成「⊘ 质量保证」正面主张。

---

## 7. STOP / GO criteria

| 条件 | 动作 |
|------|------|
| PC 断开且无语料上传 | **DOC ONLY**；臂曲线槽位保持「待跑」 |
| 语料+代码可达 | 按 `给子机器或本机的跑法.md` 跑 A→B→C（±D） |
| 连续 2 步 ΔAUC < 0.02 | **STOP** 堆框架；结论写入「天花板贴近可分性」 |
| 任一臂 AUC 相对 A 的总增益 ≥ 0.05 且未停 | 允许继续报告，但仍不得越出 §6 |

---

## 8. Data / code blocker（更新 2026-10-12 跑后）

- 伴写树已在 box：`/workspace/uploads/cowrite_tree/`；标注自 PC `dsh-伴写/v3/logs/` 拉到 `/workspace/uploads/cowrite_labels/`。  
- Live 臂在 PC 跑通（box→API TCP 超时）；结果在 `结果_臂曲线.md` / `runs/`。  
- **仍禁止**：升 SDIA · 开 S3 · 把 live 数字写进 keepable claim。

---

*路径：`/workspace/proj_20261009/主动性衔接_提示词上界_2026-10-12/PREREG.md`*
