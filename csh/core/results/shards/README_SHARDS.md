# 深度扫描分片：多机执行说明（depth 5）

日期：2026-10-05

本目录把 `depth_scan` **剩余的 72 个 depth-5 任务**切成 **6 个等负载分片**。

---

## 1. 现状

| | |
|---|---|
| 完整网格 | 288 任务（4 基质 × 深度 3/4/5 × n 网格 × 6 种子） |
| 已完成 | **216**（depth 3 全部 120 + depth 4 全部 96） |
| 剩余 | **72**（全部是 depth 5） |
| 数据质量 | 零错误、零重复 |

已完成数据在 `results/depth_scan.jsonl`。**分片只含 depth 5，不含任何已完成的格点。**

## 2. 分片

| 分片 | 任务数 | 深度 | cost | n 范围 |
|---|---|---|---|---|
| depth_shard0–5 | 各 12 | 全部 depth 5 | 各 216000 | 11000–20000 |

6 片完全均衡（LPT 按 cost = n + 3000 切分）。

## 3. 每台机器需要什么

把 `package/` 拷过去。worker 只依赖 6 个 py 文件（`run_shard.py`
`depth_scan.py` `model.py` `surfaces.py` `substrate2.py` `transfer.py`）。

- Python 3 + PyTorch（**CPU 版即可**）
- **不需要 numpy**、不需要 GPU
- 参考环境：Python 3.14 / torch 2.13 CPU，已在本机验证

## 4. 执行

```bash
cd package
python run_shard.py \
    --spec  results/shards/depth_shard0.json \
    --out   results/shards/depth_shard0.jsonl \
    --workers 6
```

`--workers` 按机器核数调（留 1–2 核给系统）。

**断点续跑**：重复同一条命令即可，已完成的格点自动跳过。
结果逐行 flush，机器被抢占不丢数据。

## 5. 时间预期

单次 depth 5 / n=20000 约 40 分钟；每片 12 个任务。
11 workers 下整片预计 2–4 小时（取决于机器）。

## 6. 回收

把各分片的 `depth_shardN.jsonl` 收回来：

```bash
# 复制回本机
Copy-Item depth_shard*.jsonl package/results/
cd package
Get-Content results/depth_scan.jsonl,results/depth_shard*.jsonl |
    Set-Content results/depth_scan_all.jsonl -Encoding UTF8
python analyze_depth.py results/depth_scan_all.jsonl
```

`analyze_depth.py` 会自动去重、按种子配对、打印基线 sanity 行。

## 7. 这批数据要回答什么

§7.3 只在**单一深度（3）**测迁移代价，无法区分"符号记忆"与"结构抽象"。
本实验扫深度 3/4/5，两者预测相反：

| 解释 | 对深度的预测 |
|---|---|
| 符号记忆（查表） | 惩罚**平坦** |
| 结构抽象（递归） | 惩罚**上升** |

已完成的两个深度（`results/depth_scan.jsonl`，216 runs）：

| 测试基质 | 重叠 | depth 3 | depth 4 | 变化 |
|---|---|---|---|---|
| Thighovl | 5/6 | −0.004 | −0.001 | 平坦 |
| TU | 2/6 | +0.254 | +0.343 | 上升 |
| Tlowovl | 0/6 | +0.410 | +0.576 | **上升 40%** |

信号强烈倾向"结构复合"：签名表几乎完整的基质（Thighovl）完全免费，
签名表全毁的基质（Tlowovl）代价随深度大幅上升。

**depth 5 是决定性一环**——有了它才能算出斜率与置信区间，
从而给出"平坦 vs 上升"的正式判决。
