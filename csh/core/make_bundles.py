"""
make_bundles.py — 为每台 worker 机器生成一个自包含的分发包。

每个 bundle 内含：
    code/    worker 运行的全部依赖（6 个 py 文件），无需其他任何文件
    spec/    该机器专属的任务清单
    out/     产出目录（worker 把 jsonl 放这里传回）
    RUN.sh / RUN.cmd   该机器专用的启动脚本
    README.md

worker 只需：解压 -> 执行 RUN -> 传回 out/depth_shardN.jsonl
"""
import json, os, shutil, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SH = os.path.join(HERE, "results", "shards")
OUT = os.path.join(HERE, "results", "bundles")
DEPS = ["run_shard.py", "depth_scan.py", "model.py", "surfaces.py",
        "substrate2.py", "transfer.py"]

if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)

manifest = json.load(open(os.path.join(SH, "MANIFEST.json"), encoding="utf-8"))

RUN_SH = """#!/bin/sh
# 分片 {i}
set -e
cd "$(dirname "$0")"
N=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
W=$(( N - 2 )); [ "$W" -lt 1 ] && W=1
echo "detected cores: $N  ->  workers: $W"
python3 code/run_shard.py \\
    --spec  spec/depth_shard{i}.json \\
    --out   out/depth_shard{i}.jsonl \\
    --workers "$W"
echo
echo "DONE.  Please return:  out/depth_shard{i}.jsonl"
"""

RUN_CMD = """@echo off
REM 分片 {i}
cd /d %~dp0
python code\\run_shard.py ^
    --spec  spec\\depth_shard{i}.json ^
    --out   out\\depth_shard{i}.jsonl ^
    --workers 4
echo.
echo DONE.  Please return:  out\\depth_shard{i}.jsonl
"""

README = """# 分片 {i} — 深度扫描 worker

## 运行

Linux / macOS：

    sh RUN.sh          （自动探测核数，留 2 核给系统）

Windows：

    RUN.cmd            （默认 4 workers，可自行改成实际核数）

## 环境要求

- Python 3
- PyTorch（**CPU 版即可，不需要 GPU**）
- **不需要 numpy**（本分片不做统计分析）

参考环境：Python 3.14 + torch 2.13 CPU，已在本机验证跑通。
缺包时：`pip install torch --index-url https://download.pytorch.org/whl/cpu`

## 时间预期

本分片 {njobs} 个任务（depth 4: {d4} 个，depth 5: {d5} 个）。
单次 depth 5 / n=20000 约 40 分钟；整片在 11 workers 下预计 3-5 小时。

## 中断了怎么办

**重新执行同一条命令即可。** 已完成的格点自动跳过，不重算；
结果逐行落盘，机器被抢占不会损坏已算部分。

## 完成后

把 `out/depth_shard{i}.jsonl` 传回主控机。这是唯一产出物。
"""

for i, s in enumerate(manifest["shards"]):
    name = s["shard"]
    bdir = os.path.join(OUT, name)
    for sub in ("spec", "out", "code"):
        os.makedirs(os.path.join(bdir, sub))
    for f in DEPS:
        shutil.copy2(os.path.join(HERE, f), os.path.join(bdir, "code", f))
    shutil.copy2(os.path.join(SH, f"{name}.json"),
                 os.path.join(bdir, "spec", f"{name}.json"))
    open(os.path.join(bdir, "RUN.sh"), "w", encoding="utf-8").write(
        RUN_SH.format(i=i))
    open(os.path.join(bdir, "RUN.cmd"), "w", encoding="utf-8").write(
        RUN_CMD.format(i=i))
    open(os.path.join(bdir, "README.md"), "w", encoding="utf-8").write(
        README.format(i=i, njobs=s["n_jobs"],
                      d4=s["by_depth"].get("4", 0),
                      d5=s["by_depth"].get("5", 0)))
    open(os.path.join(bdir, "out", "PUT_RESULT_HERE.txt"), "w").write(
        "worker 产出：depth_shard%d.jsonl 会出现在此目录\n" % i)

print("bundles ->", OUT)
for d in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, d)
    n = sum(len(f) for _, _, f in os.walk(p))
    print(f"  {d:16s} {n:3d} files")
for d in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, d)
    zp = os.path.join(OUT, f"{d}.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for r, _, fs in os.walk(p):
            for f in fs:
                full = os.path.join(r, f)
                z.write(full, os.path.join(d, os.path.relpath(full, p)))
    print(f"  {d}.zip  {os.path.getsize(zp)/1024:.1f} KB")
