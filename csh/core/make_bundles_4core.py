"""
make_bundles_4core.py — 把 depth-5 补充网格（48 任务）切成 4 核机器用的分片。

背景
----
depth-5 原网格 [11000,14000,20000] 的下界高于基线交叉点，导致阈值被钉在
网格下沿、惩罚塌成 0。补充 n=6000/8000 两个点以覆盖交叉区。

任务集
------
    4 基质 x {6000, 8000} x 6 种子 = 48 jobs

切片标准：4 核机器
------------------
每台机器用 3 workers（留 1 核给系统）。实测单任务耗时（8 workers 下）：
    n=11000 -> 12.6 min   =>  n=6000 ~ 7 min, n=8000 ~ 9 min

6 片 x 8 jobs，每片含 4 个 n=6000 + 4 个 n=8000，成本均衡：
    每片 CPU 约 64 min，3 workers 下墙钟约 20-25 min。

产出
----
results/bundles4/depth_d5ext_shard{0..5}/   自包含目录
results/bundles4/depth_d5ext_shard{0..5}.zip
"""
import json, os, shutil, zipfile, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "bundles4")
DEPS = ["run_shard.py", "depth_scan.py", "model.py", "surfaces.py",
        "substrate2.py", "transfer.py"]
CELLS = ["TT", "Thighovl", "TU", "Tlowovl"]
N_EXT = [6000, 8000]
SEEDS = 6
N_SHARDS = 6

if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)

# ---- build the 48-job set ----
jobs = [(c, 5, n, s) for c in CELLS for n in N_EXT for s in range(SEEDS)]
assert len(jobs) == 48

# cost model: minutes per job, from the measured depth-5 timings
COST = {6000: 7.0, 8000: 9.0}
cost = lambda j: COST[j[2]]

# LPT: heaviest first onto the lightest shard
jobs.sort(key=lambda j: -cost(j))
buckets = [[] for _ in range(N_SHARDS)]
loads = [0.0] * N_SHARDS
for j in jobs:
    i = loads.index(min(loads))
    buckets[i].append(j)
    loads[i] += cost(j)

order = {j: k for k, j in enumerate(sorted(jobs, key=lambda x: (x[2], x[3], x[0])))}
for b in buckets:
    b.sort(key=lambda j: order[j])

RUN_SH = """#!/bin/sh
# depth-5 补充分片 {i} —— 4 核标准
set -e
cd "$(dirname "$0")"
N=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
W=$(( N - 1 )); [ "$W" -lt 1 ] && W=1; [ "$W" -gt 4 ] && W=4
echo "cores=$N -> workers=$W"
python3 code/run_shard.py \\
    --spec  spec/depth_d5ext_shard{i}.json \\
    --out   out/depth_d5ext_shard{i}.jsonl \\
    --workers "$W"
echo
echo "DONE.  Return:  out/depth_d5ext_shard{i}.jsonl"
"""

RUN_CMD = """@echo off
REM depth-5 补充分片 {i} —— 4 核标准
cd /d %~dp0
python code\\run_shard.py ^
    --spec  spec\\depth_d5ext_shard{i}.json ^
    --out   out\\depth_d5ext_shard{i}.jsonl ^
    --workers 3
echo.
echo DONE.  Return:  out\\depth_d5ext_shard{i}.jsonl
"""

README = """# depth-5 补充分片 {i}（4 核标准）

## 运行

    sh RUN.sh        (Linux/macOS，自动探测核数，4 核 -> 3 workers)

    RUN.cmd          (Windows，默认 3 workers)

## 环境

- Python 3 + PyTorch（**CPU 版即可**）
- **不需要 numpy**、不需要 GPU

## 本片内容

{jobs} 个任务：{n6} 个 n=6000 + {n8} 个 n=8000。
预计 3 workers 下约 20-25 分钟。

## 中断了怎么办

重新执行同一条命令即可。已完成的格点自动跳过，结果逐行落盘。

## 完成后

回传 `out/depth_d5ext_shard{i}.jsonl`。
"""

for i, sh in enumerate(buckets):
    name = f"depth_d5ext_shard{i}"
    bdir = os.path.join(OUT, name)
    for sub in ("spec", "out", "code"):
        os.makedirs(os.path.join(bdir, sub))
    for f in DEPS:
        shutil.copy2(os.path.join(HERE, f), os.path.join(bdir, "code", f))
    with open(os.path.join(bdir, "spec", f"{name}.json"), "w") as fh:
        json.dump(sh, fh)
    open(os.path.join(bdir, "RUN.sh"), "w", encoding="utf-8").write(RUN_SH.format(i=i))
    open(os.path.join(bdir, "RUN.cmd"), "w", encoding="utf-8").write(RUN_CMD.format(i=i))
    n6 = sum(1 for j in sh if j[2] == 6000)
    n8 = sum(1 for j in sh if j[2] == 8000)
    open(os.path.join(bdir, "README.md"), "w", encoding="utf-8").write(
        README.format(i=i, jobs=len(sh), n6=n6, n8=n8))
    open(os.path.join(bdir, "out", "PUT_RESULT_HERE.txt"), "w").write(
        "回传此目录下的 depth_d5ext_shard%d.jsonl\n" % i)

print(f"jobs total: {len(jobs)}   shards: {N_SHARDS}")
for i, sh in enumerate(buckets):
    print(f"  shard{i}: {len(sh)} jobs  n6000={sum(1 for j in sh if j[2]==6000)}"
          f"  n8000={sum(1 for j in sh if j[2]==8000)}  cost={sum(cost(j) for j in sh):.0f}min")

allj = [j for b in buckets for j in b]
assert len(allj) == len(set(allj)) == 48, "coverage error"
print("\nverified: 48 jobs, no duplicates, full coverage")

for d in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, d)
    zp = os.path.join(OUT, f"{d}.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for r, _, fs in os.walk(p):
            for f in fs:
                full = os.path.join(r, f)
                z.write(full, os.path.join(d, os.path.relpath(full, p)))
    print(f"  {d}.zip  {os.path.getsize(zp)/1024:.1f} KB")
