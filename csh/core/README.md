# 认知基底假说：涌现阈值实验（论文 + 迁移实验 + 深度扫描 完整包）

生成日期：2026-10-04；**修订：2026-10-06**

## 论文成品

| 文件 | 说明 |
|---|---|
| `认知基底假说_涌现阈值_论文.docx` | Word 版，含 9 张图、20 张表 |
| `认知基底假说_涌现阈值_论文.pdf` | PDF 版（A4，25 页） |
| `PAPER.md` | 论文源文稿（Markdown） |

**2026-10-06 修订要点**（详见 `DEPTH_SCAN_VERDICT.md`、`S1_FINAL.md`、`REANALYSIS_36SEED.md`）：

- **§5 由"三个陷阱"扩为六个**，新增 §5.5 编码退化（本文最重要的方法学发现）、§5.6 网格错配与天花板效应、§5.7 分母趋零的假显著
- **§6.1 S1 换用修复后的编码**：CV(log) 由 0.009（退化，同一数算三次）改为 **0.0110**（6 个真正独立的表面），15 个配对全部不显著；原图 3 保留作退化对照，新增图 8
- **§6.2 S2 改为统计检验**，并如实报告它**未获干净判定**（null 臂与真实表面的词表规模不匹配 225 vs 169；两种合理的配对方式给出不同结论）
- **§6.3 K-A**：36 种子下补报"单跳假象"——全四点 $r=+0.906$ 全部来自 mult 1→2，去掉首点后斜率降到 $+0.008$
- **§7.4 新增深度扫描（432 次运行）**：正面检验"符号记忆"解释——**迁移代价随深度完全平坦**，量级由签名重叠度决定，支持符号记忆而非结构复合；新增图 9
- **§2.5 新增与 Neural Thickets（Gan & Isola 2026）的对照**，并在 §8 边界一给出规模轴的可证伪后续
- **§9 结论重写**为四条结论 + 六条方法学教训

## 核心结论（当前版）

1. **结构而非符号数目决定阈值**：$C_{\mathrm{eff}}(3)=24$ 恒定、符号数目增长 64 倍（$C(3)$: 24→1536）时阈值平坦。
2. **符号身份不是约束源**：6 个真正独立的表面共享阈值（CV(log)=0.0110），15 个配对全部不显著。
3. **模型学到的是符号级关联，而非可迁移的结构抽象**：迁移代价跟随签名表损伤（$0/6 \to +0.410$，$2/6 \to +0.245$，$5/6 \to -0.004$），且**随深度完全平坦**。
4. **表层现象与结构内容必须分别测量**——六条方法学教训，其中三条会使结论反转或使证据失效。

## 本轮新增的实验

| 实验 | 运行数 | 脚本 | 结论 |
|---|---|---|---|
| S1 修复（拉丁方配平） | 180 | `surface_fix2.py` | 6 个独立表面共享阈值，CV=0.0110 |
| S1 修复（分块，被证伪） | 180 | `surface_fix.py` | id 块位置混淆，保留作对照 |
| id 块位置控制实验 | 36 | `idblock_control.py` | 同一表面换块位置：0.1675–1.0000 |
| 深度扫描（depth 3/4/5） | 432 | `depth_scan.py` | **代价随深度平坦** → 支持符号记忆 |
| 深度网格补点 | 96 | `run_shard.py` + `spec_gridfix.json` | 使三个深度的交叉点都被括住 |
| S2 null 补跑 | 60 | `surface_fix_null.py` | 与真实表面词表规模不匹配，未获干净判定 |

## 论文理论部分

`THEORY.md` — 认知基底假说的理论陈述。

## 迁移实验报告

`TRANSFER_REPORT.md` — 迁移实验的独立技术报告。

## 结论与方法学文档

| 文件 | 内容 |
|---|---|
| `S1_FINAL.md` | S1 缺陷、修复、最终判决的完整证据链 |
| `DEPTH_SCAN_VERDICT.md` | 深度扫描的最终判决与网格缺陷记录 |
| `GRID_DEFECT.md` | depth 4/5 网格错配的记录（同类错误犯了两次） |
| `REANALYSIS_36SEED.md` | 36 种子重算 S1 / S2 / K-A |
| `S1_CORRECTION_idblock.md` | 对并行包"alien 系统性更慢"结论的纠正 |

## 实验代码

### 主实验与机制

| 文件 | 角色 |
|---|---|
| `substrate2.py` | 修正后的基质构造（3 类型 × 2 出边，`mult` 变化） |
| `substrate.py` | 第一版旋钮（以 $C(k)$ 为旋钮），保留作对照 |
| `surfaces.py` | 8 种表面编码 + `PermutedSurface` |
| `model.py` | 4 层 Transformer 编码器（约 1M 参数） |
| `final.py` / `analyze_final.py` / `diagnose.py` | 主实验执行与 S1/S2/K-A 检验 |

### 更正与诊断

| 文件 | 角色 |
|---|---|
| **`S1_DEFECT_verify.py`** | 一条命令复现编码退化（含 `--weights`） |
| **`idblock_control.py`** | id 块位置控制实验 |
| `surface_fix.py` / `surface_fix2.py` / `analyze_fix2.py` | S1 的两次修复与分析 |
| `probe_depth.py` / `analyze_depth.py` / `analyze_depth_thr.py` | 深度扫描的先导与分析 |

### 迁移与深度扫描

| 文件 | 角色 |
|---|---|
| `transfer.py` / `transfer_null.py` / `decouple.py` / `analyze_transfer.py` | 跨基质迁移（§7.3） |
| **`depth_scan.py`** / **`analyze_depth_gap.py`** | 深度扫描与主判据分析 |
| `make_shards.py` / `make_bundles*.py` / `run_shard.py` | 多机分片打包与 worker |

### 配图与文档

`paper_figs.py`（图 1–4）、`transfer_figs.py`（图 5–7）、**`paper_figs2.py`（图 8–9）**、`build_docs.py`

## 配图（300 dpi，全英文，灰度可辨）

`paper_figs/`

- `fig1_task.png` — 任务与编码示意
- `fig2_surface_curves.png` — 表面不变性学习曲线 + null 对照
- `fig3_thresholds.png` — 各表面阈值（**原设计，退化版，保留作对照**）
- `fig4_complexity.png` — 复杂度臂与 log–log 关系
- `fig5_transfer_curves.png` / `fig5b_null_curves.png` — 2×2 迁移曲线
- `fig6_penalty.png` / `fig7_decouple.png` — 惩罚对比与解耦
- **`fig8_s1_fix.png`** — **S1 修复前后对比**
- **`fig9_depth_scan.png`** — **深度扫描（差距随深度平坦 + 基线难度随深度上升）**

## 原始数据

`results/`（JSONL，每行一次运行）

| 文件 | runs | 说明 |
|---|---|---|
| `final.jsonl` | 330 | 主实验（臂 S + 臂 K），6 种子 |
| `final_merged.jsonl` | 1,980 | 主实验重跑，36 种子（7 分片合并去重） |
| `transfer.jsonl` | 187 | 跨基质 2×2 迁移矩阵 |
| `transfer_null.jsonl` | 60 | 标签重命名对照 |
| `decouple.jsonl` | 60 | 解耦臂 |
| **`depth_scan_final.jsonl`** | **432** | **深度扫描（depth 3/4/5 × 4 基质）** |
| **`surface_fix.jsonl`** | **180** | S1 修复（分块，被证伪） |
| **`surface_fix2.jsonl`** | **180** | S1 修复（拉丁方，论文采用） |
| **`surface_fix_null.jsonl`** | **60** | S2 null 补跑 |
| **`idblock_control.jsonl`** | **36** | id 块位置控制 |
| **`gridfix.jsonl`** | **96** | 深度网格补点 |
| `bundles/result/*.jsonl` | 72 | depth-5 外部机器返回 |
| `bundles4/result/*.jsonl` | 48 | depth-5 补充返回 |

**合计约 3,600 次运行**（不含早期探索批次）。

## 复现

```bash
# 主实验与迁移
python final.py && python analyze_final.py
python transfer.py --seeds 6 && python transfer_null.py --seeds 6 && python decouple.py --seeds 6

# 编码退化与修复（决定性证据）
python S1_DEFECT_verify.py --weights
python idblock_control.py --surface en --seeds 3 --ns 4000,6500
python surface_fix2.py --seeds 6 --workers 8 && python analyze_fix2.py

# 深度扫描
python depth_scan.py --seeds 6 --workers 8
python analyze_depth_gap.py results/depth_scan_final.jsonl

# 配图与文档
python paper_figs.py && python transfer_figs.py && python paper_figs2.py
python build_docs.py
```

环境：Python 3.14，PyTorch 2.13.0+cpu（原批次 2.10.0+cu128），CPU only。

**注意**：`build_docs.py` 原用 weasyprint 生成 PDF；本机缺少其原生依赖（GTK/Pango），已改为回退到 **headless Edge/Chrome** 打印 PDF（图以内嵌 base64 提供，无需网络）。
