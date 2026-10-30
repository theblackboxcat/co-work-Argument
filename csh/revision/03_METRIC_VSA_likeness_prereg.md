# 指标语言 · VSA-likeness × SB2／collision · prereg 草案 · 2026-10-30

> **纸面 only** · **本轮未跑任何新实验、未产生新数字** · 不改 `frozen/` · 不覆盖既有 `SB2_ANALYSIS.*` / `COLLISION.*` 主判决  
> 配套：`csh/core/THEORY.md` §10–§11（同日追加）  
> 文献（已 WebFetch 核验存在）：  
> - Dhayalkar, *Attention as Binding…*, arXiv:[2512.14709](https://arxiv.org/abs/2512.14709)  
> - （交叉）Wu et al., *How Do Transformers Learn Variable Binding…*, arXiv:[2505.20896](https://arxiv.org/abs/2505.20896)

---

## 0. 目的

把 arXiv:2512.14709 的 **VSA-likeness** 议程（role–filler recoverability、superposition interference、与绑定算子的对齐）**翻译**成可与本仓库既有 **SB2**、**collision** 指标并排叙述的语言，供论文/答辩改写。  
本文件是 **措辞 + prereg 草案**，不是结果报告。

---

## 1. 既有对象（只引用，不重算）

| 对象 | 路径（仓库） | 已回答的问题 |
|------|--------------|--------------|
| SB2 | `…/results/SB2_ANALYSIS.md`、`symbol_binding.py` | 类型转移置换后，熟悉 token 串上的落差 → 符号死绑定 vs 可重对齐结构 |
| collision | `…/results/COLLISION.md`、`collision_geometry.py` | 各表面 token 碰撞图几何；null 臂与真实表面是否同几何；词法池混淆 |

**纪律**：引用既有判决时，沿用原文数字与判决句；本草案不得改写「S 被推翻」等已结算措辞，除非作者另行开「改判」闸。

---

## 2. VSA 用语 → 本仓库代理（谨慎对齐）

文献核心图景：queries/keys ≈ roles，values ≈ fillers，attention ≈ soft unbinding，residual ≈ superposition。

| 文献指标族 | 建议的本仓库**行为／几何代理** | 非声称 |
|------------|--------------------------------|--------|
| **Role–filler recoverability** | SB2：`remap:*` 相对 `same` 的配对落差越小 → recoverability 越高；可用既有互补量 `1 - gap_remap/gap_shuffle` 作 **RF-proxy** 叙述 | 不是 residual 子空间上的真实 unbinding 探针 |
| **Superposition interference** | collision：`density` / `spectral_norm` / `color_imbalance`；多 token 共享位置角色 = 角色空间干扰 | 不是激活叠加容量曲线 |
| **Alignment with VSA operators** | （可选未来）拟合固定绑定/置换算子到层／头 —— **本草案不授权** | 未做 |
| **Failure modes** | SB2 shuffle 崩坏；collision 上 null 与 lisp/code 几何不全等 | 仅作诊断叙事 |

一句话对外可以说：

> SB2 的 remap 落差，我们改述为「行为级 role–filler recoverability 代理」；collision 图密度／谱范数改述为「角色空间干扰的几何代理」——二者对齐 VSA-likeness 议程，但**不等于**已在激活空间实现经典 VSA 代数。

---

## 3. Prereg 草案（未冻结 · 未开跑）

### 3.1 研究问题

- **RQ1（叙述）**：既有 SB2 判决是否可在不改主数字的前提下，用 VSA-likeness 语言重述？  
- **RQ2（可选辅指标，若开跑）**：RF-proxy 与签名保留度（`sig_retained`）是否同向？  
- **RQ3（可选）**：collision 干扰代理与表面阈值极差是否同向（既有 `corr_with_acc` 已弱；辅指标不得推翻主文）？

### 3.2 条件与数据

- **默认**：零新跑；只改文档措辞，引用 `SB2_ANALYSIS` / `COLLISION` 已发表于补充包的表。  
- **若作者后来说「开」并要求辅指标表**：仅允许从**既有** `SB2.jsonl` / `COLLISION.json` **重汇总**，禁止新 train；任何新 train 须另开实验单。

### 3.3 主／辅指标

| 级别 | 名称 | 定义 | 用途 |
|------|------|------|------|
| 主（冻结沿用） | SB2 gap | 相对 `same` 的配对落差；判决句沿用原文 | 机制归因 |
| 主（冻结沿用） | collision legitimacy | null vs 真实表面几何是否 `all_equal` | null 合法性 |
| 辅（草案） | RF-proxy | `1 - mean_gap_remap / mean_gap_shuffle` | VSA recoverability 叙述 |
| 辅（草案） | Interference-proxy | 跨表面 `density` 极差或对 `mean_acc` 的 \|r\| | 干扰叙事；弱相关时标注 |

### 3.4 决策规则（若将来结算辅指标）

| 结果 | 含义 |
|------|------|
| 辅指标与主判决同向 | 允许在论文用 VSA 语言**平行叙述** |
| 辅指标冲突 | **INC**；正文仍用 SB2／collision 原判决；VSA 语言降为「待测隐喻」 |
| 无新跑 | 只允许 §2 对照表进入 THEORY／论文「相关工作／讨论」，不得出现「我们测得 VSA-likeness=…」 |

### 3.5 明确不做

- 不重跑 SB2／collision train  
- 不改 `frozen/`  
- 不做激活 patch / 子空间 interchange（除非另开电路实验单）  
- 不把 arXiv:2512.14709 的理论命题写成 CSH 已证实结论

---

## 4. 论文可粘贴短段落（中文草稿）

> 补充包中的符号绑定判决（SB2）与 token 碰撞几何认证（collision），与向量符号架构视角下的「VSA-likeness」议程同构：前者提供行为级的 role–filler 可恢复性代理（类型转移置换后的 remap 落差），后者提供角色共享所诱导的干扰几何代理。我们采用该对齐作为**指标语言**，而非声称模型内部已实现经典绑定算子；主判决仍以 SB2／collision 原协议为准（参见 arXiv:2512.14709）。

---

## 5. 与 §10 变量绑定发育的关系

Wu et al. (arXiv:2505.20896) 的「启发式叠加而非替换」描述的是**训练动力学**；VSA-likeness 描述的是**表征代数近似程度**。二者正交：叠加叙事解释策略如何累积；VSA 叙事解释绑定是否可解绑。后续若做发育分析，可问：Phase-2 启发式是否对应低 recoverability／高干扰的局域解，Phase-3 是否提高 RF-proxy——**该假设未测**。

---

*Ollie/docs plan B · 2026-10-30 Asia/Shanghai · 纸面 · 等「开」才允许重汇总辅表*
