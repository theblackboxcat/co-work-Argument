# CSH 切片包· 第 1 台

生成时间：2026-10-06 13:12

##这台机器要跑什么

| 实验 | 片数 | jobs | 预计 |
|---|---|---|---|
| DPX | 2 | 2 | 0.5 h |
| E6X | 1 | 7 | 0.2 h |
| S2L | 2 | 25 | 0.3 h |

**合计：5 片 / 34 jobs /约 1.0 小时**（4 workers，**4 核机器**）

##怎么跑

### 方式一：让本机的 AI 模型跑（推荐）

把同目录的 `提示词.md` 全文复制发给它即可。

### 方式二：自己跑

```bash
# 看有哪些片
ls slices/

# 干跑确认
python run_slice.py --spec slices/DPX_slice00.json --out results/DPX_slice00.jsonl --dry-run

# 跑一片（前台，等它结束）
python run_slice.py --spec slices/<片名>.json --out results/<片名>.jsonl --workers 4

# 全部跑完后合并验证
python merge_slices.py --exp DPX --inputs "results/DPX_slice*.jsonl" --verify
python merge_slices.py --exp E6X --inputs "results/E6X_slice*.jsonl" --verify
python merge_slices.py --exp S2L --inputs "results/S2L_slice*.jsonl" --verify
```

## 结果要传回来

`results/` 下所有 `*_slice*.jsonl`。别传原始分片目录，传 jsonl 就够。

## 中途断了怎么办

直接重跑同一条命令。`run_slice.py` 会读已有输出、跳过已完成的格点。

## 两个必须知道的坑

**1. 预估时间偏乐观，请按 1.5 倍预留。**
成本模型是实测线性回归 `secs = A + B * n`，A/B 由本机历史数据标定。
不同CPU 的单核性能差异很大，且Python 进程启动开销不计入。
第 1–5 台（每台 2 片 DPX）实际可能要 8 小时以上，请确保机器中途不睡眠/休眠。

**2. 不要把多个实验的切片合并成一个 spec 文件。**
`run_slice.py` 按整片的 experiment 派发任务，混片会被直接拒绝并报错。
即使绕过，`acc` 也会静默变成 `nan` 而不是失败——看起来"跑完了"其实什么都没算。
每片单独跑，用各自的 `results/<片名>.jsonl`。
