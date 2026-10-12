# 实验包交付说明

日期：2026-10-05
目录：`%DSH_ROOT%\appearent\package\实验包_20261005\`
前置阅读：`00_判别书核对报告.md`

---

## 这个目录里有什么

| 文件 | 对应 | 状态 | 能否直接跑 |
|---|---|---|---|
| `00_判别书核对报告.md` | — | 完成 | 文档 |
| `01_S1修复结果_180runs.md` | E0 结果 | **完成**（180 runs 已跑满） | 文档 |
| `02_如何测出边界一_规模轴实验E8设计.md` | E8 方案 | 完成 | 文档 |
| `03_S2置换检验结果.md` | E5 结果 | **完成**（14/14 稳健） | 文档 |
| `04_涌现与反涌现_U形与双降.md` | E10 方案 | 完成 | 文档 |
| `e10_ushape.py` | E10 | **preflight 通过**（五档 yield 40/40） | 是，300 runs |
| `e8_scale.py` | E8 | preflight + 冒烟通过（d=128 精确复现论文 A1） | 是，700 runs |
| `e9_ollama.py` | E9 | **端到端跑通真实 qwen2:7b** | 是 |
| `s2_permutation.py` | E5 | 已验证 | 是，零新 run |
| `surface_fix_null.py` | S2 前置 | **已跑满 60/60** | — |
| `arm_k_null.py` | E6 | 冒烟通过 | 是，270 runs |
| `decouple_e4.py` | E4 | preflight 通过 | 是，90 runs |
| `xarch.py` | E1 | 四臂全部端到端跑通 | 是，pilot 优先 |

所有脚本：
- 从 `..`（即 `package/`）import 原代码，**不修改任何原文件**；
- 输出写到 `../results/` 下**新文件**，不覆盖既有数据；
- 支持断点续跑（已存在的 key 自动跳过）；
- 带 preflight，跑之前先证明干预真的进入了模型。

## 运行环境

```
C:\Python314\python.exe      # 已验证：numpy 2.5.3 + torch 2.13.0+cpu
```

`%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe` **没有 numpy**，不要用。

## 实测参数量（vocab=197 共享词表）

| 架构 | total | embedding | body | body/A1 |
|---|---|---|---|---|
| A1 Transformer | 575,872 | 25,216 | 550,656 | 1.00× |
| A2 GNN (R-GCN, 3层) | 282,578 | 25,792 | 256,786 | 0.47× |
| A3 Mamba-like (4层) | 726,464 | 25,216 | 701,248 | 1.27× |
| A4 MLP (2层) | 593,920 | 25,216 | 568,704 | 1.03× |

A2 偏小是R-GCN 结构本身更省参数（关系嵌入走独立小表，不绑 vocab）。
**这一点必须在报告中说明**，否则会被读成"给GNN 配了更小的模型"。

A4 的 head **不与 embedding 绑定**（hidden=384 ≠ d_model=128），
A1/A3 保持 tie。这是四臂之间唯一的结构差异，也要在报告里注明。

## 绝对不要做的事

1. **不要用 `build_vocab`跑任何跨表面实验。** 它按首次出现顺序分配 id，会让
   `zh`/`math`/`alien` 拿到逐 token 相同的输入。本目录的脚本都用**跨表面共享
   id 区间**（`surface_fix.py` 方案）。若你要新写实验，照抄这个做法。
2. **不要在 `results/surface_fix.jsonl` 跑满前启动 E1/E6。** 它们的基线是
   修复后数据。判别书没提这一点，是它最大的漏洞。
3. **不要把 E5 在修复前数据上的输出当结论。** 脚本会自己拒绝出p 值并说明原因，
   但如果你手工绕过它，就得到了一个p 恒等于 1 的空洞结果。

---

## 执行的推荐顺序

### 第 0 步（已完成）

`results/surface_fix.jsonl` 已跑满 180 runs。**S1 已判定**：

```
CV(log) = 0.0141（判据 < 0.15）    7 个 τ 上恒为 0.013–0.014
15 个配对全部不同（修复前有 6 个是 30/30 逐位相同）
7/15 配对在准确率上显著，其中 5 个涉及 alien
```

详见 `01_S1修复结果_180runs.md`。

**但修复实验漏掉了 null 臂**（`surface_fix.py:48` 的 NAMES 只有 6 个真实表面），
所以 S2（论文 §6.2 的"承重检验"）还判不了。正在补跑。

### 第 0.5 步：S2 的 null 补跑（进行中）

```bash
C:/Python314/python.exe surface_fix_null.py --seeds 6 --workers 10
```

60 runs。跑完后 S2 才能判。

### 第 1 步：E5（零新 run，2 分钟）

等null 补跑完成后，**两个文件一起传**：

```bash
C:/Python314/python.exe s2_permutation.py \
    ../results/surface_fix.jsonl ../results/surface_fix_null.jsonl
```

预期：`STEP 1` 显示 0 个退化配对，`STEP 3` 给出真 p 值。

**对照跑一遍修复前数据**（用于论文里说明"为什么必须先修"）：
```bash
C:/Python314/python.exe s2_permutation.py ../results/final.jsonl
```
→ 报 14 个组合 SKIPPED，这就是判别书会踩的坑。

### 第 2 步：E6（270 runs，约 2 小时）

```bash
C:/Python314/python.exe arm_k_null.py --seeds 6 --workers 10
```

先看 preflight 是否全OK（en vs relperm/entperm 必须 0/30 identical）。

### 第 3 步：E4（90 runs，约 30 分钟）

```bash
C:/Python314/python.exe decouple_e4.py --seeds 6 --dry-run   # 先看 preflight
C:/Python314/python.exe decouple_e4.py --seeds 6
```

### 第 4 步：E1（先pilot）

```bash
C:/Python314/python.exe xarch.py --pilot --seeds 2 --workers 10   # 快速可行性
C:/Python314/python.exe xarch.py --seeds 6 --workers 10           # 完整 840 runs
```

E1 的 A3 是 **Mamba 的纯 PyTorch 近似**，不是官方 CUDA kernel。论文引用时
必须如实标注，不能写成"我们用了 Mamba"。

### 第 5 步：E8 规模轴（最后做）

```bash
C:/Python314/python.exe e8_scale.py --dry-run                 # 先看参数量表
C:/Python314/python.exe e8_scale.py --d 64,128,256 --seeds 3  # pilot
C:/Python314/python.exe e8_scale.py --seeds 4                 # 完整 700 runs，约 18 h
C:/Python314/python.exe e8_scale.py --analyze-only            # 只分析
```

测的是 $n^\star(d_{\text{model}})$——涌现阈值随模型宽度的变化。
详见 `02_如何测出边界一_规模轴实验E8设计.md`。

**E8 放最后**：它最贵，且依赖前面积累的编码规范（共享 id 区间）与
null 规范（relperm 作承重对照）。基线没立住就跑，等于把 §5 三个陷阱
重新踩一遍。

---

## 各实验的判定规则

### E5（S2 置换检验）

- `p > 0.10` 在全部 7 个 τ 上 → S2 稳健，§6.4 那句"应改为统计检验"落地
- `p < 0.05` 在某些 τ 上 → §6.2 结论要限定到通过的那些判据
- **出现 SKIPPED** → 数据退化，先修编码，别硬跑

### E6（臂 K 补 null）

逐 mult 水平上，null 阈值与该mult 的 en 基线做**同 seed 同 n 的配对差**：
- 差 = 0 或 CI 含零 → 符号置换的代价在复杂度增长下仍为零，§8 边界四关闭
- mult=4 时 null 显著变难 → 符号数目 × 结构复杂度有交互，臂 K 结论要加限定

**注意**：本实验的 vocab（约 105–169）比臂 S 的 31 大，因为要让 token 身份
进入模型。这是**允许的变化**，但论文里必须显式说明，并给出理由。

### E4（签名表解耦）

三个变换（`root_swap` / `chain_reverse` / `null_renaming`）都是 6/6 签名重叠、
`C_eff(3)=24` 不变，变的只是 `pools`（类型→实体划分）：

- 迁移代价< 5% baseline → **C 赢**（签名表够用，实体归属无关）
- 迁移代价 > 15% baseline → **L2 存活**
- **null_renaming 的代价 > 变换的代价** → 变换效应只是重命名，不支持 L2

最后一条最重要：没有它，"变换免费"可能只是因为模型本来就在做符号级记忆。

### E1（跨架构）

**主判据不是 CV(log)**（判别书那样写会循环论证，因为修复前 CV=0）。
用：各架构阈值相对 A1 的偏移，配合同 seed 同 n 的逐点配对差。

- 各架构阈值差 < 10%（且null 在每个架构下都免费）→ 阈值不随架构移动
- 架构间系统移动 > 30%，且 relperm 的代价在所有架构下同量级 → 效应由
  **符号身份**驱动，不是架构
- 架构间移动与 relperm 代价不同量级 → 效应由**架构归纳偏置**驱动

**辅判据**：A2 GNN 的 relperm 代价是否与 A1 同量级。若 GNN 上 relperm 变难而
A1 上不变，说明 A1 的「30/30 相同」是 Transformer 特有的捷径。

---

## 判别书里我没有落地的实验，及原因

| 实验 | 为什么不落地 |
|---|---|
| **E2**（Boroditsky 表面） | 判别书设计的三个表面**依然是同构直译**——它自己批评现有臂 S 是 `甲 含 乙` vs `A is r B` 同构，然后自己把 `含` 换成 `右`/`上`。而 `surfaces.py:121` 的中文臂第 4、5 个 token 是**硬填充**（`[A,R,B,"。","，"]`），操纵的隐喻方向在第 3 位，填充位不变。更根本的是测到的差异会被 §7.3 已证明的"符号级记忆"吸收，判别不出 A vs B——除非再做一次 null 对照。要做需重新设计。 |
| **E3**（域外基质） | 三个基质全部违反自述不变量。S1（非结合复合）：`c_eff()` 数的是类型签名，关系层违反结合律**对模型不可见**，测不出东西。S3（自包含实体）：与 `Gen.make()` 的 `used` 集合机制直接冲突，会静默返回 `None`、训练集不足 n 条。S2（循环因果）：会改变事实数与 token 数，违反配平。需先做可行性验证再排期。 |
| **E7**（人类对照） | 判别书说"不要在本文做"，方向对但理由不够硬。婴儿 violation-of-expectation 测的是单步预期违反，本文任务是 depth-3 多跳关系追踪——婴儿无法完成本文任务，所以**不对应同一个能力**。这不���"超出尺度"，是错位。 |

---

## 判别书说对的部分（保留）

- **三层拆解 L1/L2/L3（§1）是这份材料里最有价值的判断。** 论文确实把三层绑在
  一起卖了，§9 结论第一句确实该改成三层表述。L2 被 §7.3 削弱这一点与论文
  原文一致（`PAPER.md:393`）。
- **E5、E6 是零/低成本高收益**，判断正确（虽然 E5 的前提当时是错的）。
- **token 长度 46 严格配平**属实。
- **§8 边界四（臂 K 缺 null）真实存在**，`final.py:113` 只跑 en。

---

## 下一步（等数据）

1. `surface_fix.jsonl` 跑满 → 跑 E5 → 得到 S1/S2 的真实结论
2. 若 S1 在修复后**仍**成立（`0 退化配对 + 少数显著对`）→ 论文主张更强，
   因为 token 身份确实进模型了
3. 若 S1 **不**成立（多个显著对，尤其 alien 系统性不同）→ §6.1 的
   "六个表面共享阈值"要下调，且这本身是个**新发现**：alien 在修复前测不出
   与人类表面的差异（因为它实现上就是 zh），修复后测出来了
4. 无论哪种，§9 结论第一句都应改成三层表述；这一条**现在就能做**