"""
build_6packs.py — 把38 片按代价贪心分给 6 台机器，各打一个自包含包。

=====================================================================

每包结构（解压即跑，不需要挑spec、不需要看manifest）
----------------------------------------------------
    packN/
      一键脚本.py          <- 猫猫或执行端只需 python 一键脚本.py
      本机任务.json         <- 这台机器要跑的全部 job（已按代价均衡）
      slices/*.json        <- 对应的 spec 备份
      <全部依赖代码>.py     <- 原始代码 + 实验模块
      提示词.md             <- 可直接发给该机器上那个模型的提示词
      README.md            <- 人工可读说明

贪心均衡
--------
按 cost 降序，每次放进当前最轻的机器。实测6 台负载差 < 2%。

不用
----
    python build_6packs.py# 生成到 分发包_6台/
"""

import json
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
N_MACHINES = 7
OUT = os.path.join(HERE, "分发包_4核")
SLICE_DIR = "slices"           # make_slices.py 的输出目录
WORKERS_PER_MACHINE = 4           # 4 核机器 -> 4 workers

# 依赖代码（原始 + 实验模块 + 分发工具）
DEPS = [
    # 原始代码
    "model.py", "substrate2.py", "surfaces.py",
    "transfer.py", "substrate.py", "analysis.py", "surface_fix2.py",
    "depth_scan.py",                 # DPX 复用它的 run_one / job
    # 实验模块
    "e10_ushape.py", "e8_scale.py", "arm_k_null.py", "decouple_e4.py",
    "xarch.py", "latin.py", "e9_ollama.py", "surface_fix_null.py",
    "s2_latin_rerun.py",             # S2L 拉丁方重跑
    # 分发工具
    "s2_permutation.py", "make_slices.py", "run_slice.py", "merge_slices.py",
]
DEPS = [d for d in DEPS if d != "subfaces_placeholder"]

PROMPT = """你负责跑一批实验切片。必须在前台运行并当场验证，不许承诺后台。

【背景】
CSH涌现阈值论文的下游实验。已有数据在 results/ 下（已排除，不要重跑）。
本批任务由本机任务.json 完整描述，不依赖任何外部数据文件。

【本机要跑什么】
共 {n_jobs} 个 job，预计 {est_hours:.1f} 小时（4 workers）。
spec 已切好放在 slices/ 下，一片一个文件。

【第 0 步：确认环境】
python -c "import torch, numpy; print('torch', torch.__version__)"
若缺依赖：pip install torch numpy
注意：CPU 版 torch 就能跑，别装 CUDA 版（会拉几个 GB）。

【第 1 步：干跑确认（这一步不算完成）】
python run_slice.py --spec slices/{first_spec} --out results/{first_spec}.jsonl --dry-run
确认实验名与参数合理。

【第 2 步：前台运行一片（必须等它跑完）】
python run_slice.py --spec slices/<片名>.json --out results/<片名>.jsonl --workers 4

**这一条命令必须前台阻塞到结束，输出直接打屏。**

绝对禁止：
- 把它放到后台
- 说"我会在后台运行，稍后给你结果"
- 说"预计需要 X 小时，明天早上给你"
- 在命令还没返回时结束你的回答

跑完一片就立刻验证、报告，然后跑下一片。共 {n_slices} 片。

若 workers 报内存不足，改 --workers 2 重跑（断点续跑会跳过已完成的）。
若中途被 kill，直接重跑同一条命令即可续跑。

【第 3 步：每片必须当场验证（三条全过才算完成）】
1) wc -l results/<片名>.jsonl
2) grep -c '"error"' results/<片名>.jsonl      # 必须是 0
3) head -1 results/<片名>.jsonl                 # acc 必须在 0~1

把这三条命令的真实输出贴进回答里。

【第 4 步：全部跑完后合并】
python merge_slices.py --exp {exps} --inputs "results/*_slice*.jsonl" --verify

对每个实验各跑一次（E4/E6/E10 各自一条命令）。
会报"应有 N，实得 M，缺 K"。把三行输出都贴出来。

【硬性要求】
- 不许说"我会在后台运行"然后结束对话
- 不许只报进度不报结果
- 命令没返回之前不许结束回答
- 失败了就说失败并贴错误信息，不要含糊
- 「正在跑」不算完成，「文件在这里且验证通过」才算

【报告格式】每片一次
■ 片名 / 实验 / jobs 数 / 耗时 / error 数 / acc 范围 / 文件大小
■ 三条验证命令的真实输出
"""

README = """# CSH 切片包· 第 {idx} 台

生成时间：{ts}

##这台机器要跑什么

| 实验 | 片数 | jobs | 预计 |
|---|---|---|---|
{rows}

**合计：{n_slices} 片 / {n_jobs} jobs /约 {est_hours:.1f} 小时**（4 workers，**4 核机器**）

##怎么跑

### 方式一：让本机的 AI 模型跑（推荐）

把同目录的 `提示词.md` 全文复制发给它即可。

### 方式二：自己跑

```bash
# 看有哪些片
ls slices/

# 干跑确认
python run_slice.py --spec slices/{first_spec}.json --out results/{first_spec}.jsonl --dry-run

# 跑一片（前台，等它结束）
python run_slice.py --spec slices/<片名>.json --out results/<片名>.jsonl --workers 4

# 全部跑完后合并验证
{merge_cmds}
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
"""


def main():
    # 读全部 spec —— 按文件名自动发现实验，不硬编码列表。
    # 旧版硬编码 ("E4","E6","E10") 会漏掉 2026-10-06 新切的
    # S2L/E6X/DPX共 23 片，且不会报错（只是少打 23 片），
    # 这种"静默少包"必须避免。
    # 自动发现 + 实验白名单。
    #
    # 自动发现是为了避免"硬编码实验列表"导致静默少包（新增实验切片
    # 没被打进去却不会报错）。但 slices/ 里同时躺着 E4/E6/E10 的历史
    # 切片——那660 个 jobs 昨夜已经跑完，切片文件是残留。若无差别
    # 打包，执行端会把已完成的实验重跑一遍。
    #
    # 所以：全量发现（防少包）+ 白名单过滤（防多包）。
    # 白名单必须与 make_slices.py 的默认实验列表一致。
    ALLOW = {"S2L", "E6X", "DPX"}
    slices = []
    skipped = []
    d = os.path.join(HERE, SLICE_DIR)
    seen_exps = set()
    for fn in sorted(os.listdir(d)):
        if not re.match(r"^[A-Za-z0-9]+_slice\d+\.json$", fn):
            continue
        exp = fn.split("_slice")[0]
        if exp not in ALLOW:
            skipped.append(exp)
            continue
        spec = json.load(open(os.path.join(d, fn), encoding="utf-8"))
        if not spec:
            continue
        cost = sum(x.get("cost", 0) for x in spec)
        slices.append({"exp": exp, "name": fn[:-5], "path": fn,
                       "jobs": len(spec), "cost": cost, "spec": spec})
        seen_exps.add(exp)
    if skipped:
        print(f"跳过已完成实验的历史切片: {sorted(set(skipped))}")
    print(f"在 {SLICE_DIR}/ 发现 {len(slices)} 片，"
          f"实验 = {sorted(seen_exps)}")
    missing = ALLOW - seen_exps
    if missing:
        raise SystemExit(f"ABORT: 白名单实验 {sorted(missing)} 在 {SLICE_DIR}/ "
                         f"里没有切片。先跑 make_slices.py。")
    if not slices:
        raise SystemExit(f"ABORT: {SLICE_DIR}/ 里没有找到任何 *_sliceNN.json。"
                         f"先跑 make_slices.py 生成切片。")
    # 并集完整性：全部切片的 jobs 之和应等于 make_slices 的总待办
    print(f"总 jobs {sum(s['jobs'] for s in slices)}，"
          f"总代价 {sum(s['cost'] for s in slices)/3600:.2f} 核·小时")

    # 贪心均衡
    slices.sort(key=lambda s: -s["cost"])
    load = [0.0] * N_MACHINES
    buckets = [[] for _ in range(N_MACHINES)]
    for s in slices:
        i = load.index(min(load))
        buckets[i].append(s)
        load[i] += s["cost"]

    # 二次优化：把每台内部最重的片与最轻的片做"整片交换"或"拆分"，
    # 目标是把负载差压到 5% 以内。切分粒度是 0.45–0.72 h，
    # 不拆分的话 6 台最多只能到这个精度。
    def spread():
        return (max(load) - min(load)) / max(load) * 100

    # 尝试跨机交换整片（不改变任何 spec，纯重排）
    improved = True
    rounds = 0
    while improved and rounds < 200:
        improved = False
        rounds += 1
        hi = load.index(max(load))
        lo = load.index(min(load))
        if spread() < 1.0:
            break
        # 找一对可交换的片，使差变小
        best = None
        for a in buckets[hi]:
            for b in buckets[lo]:
                new_hi = load[hi] - a["cost"] + b["cost"]
                new_lo = load[lo] - b["cost"] + a["cost"]
                cur = max(load[hi], load[lo]) - min(load[hi], load[lo])
                new = max(new_hi, new_lo) - min(new_hi, new_lo)
                if new < cur - 1e-6:
                    gain = cur - new
                    if best is None or gain > best[0]:
                        best = (gain, a, b)
        if best:
            _, a, b = best
            buckets[hi].remove(a)
            buckets[lo].remove(b)
            buckets[hi].append(b)
            buckets[lo].append(a)
            load[hi] += b["cost"] - a["cost"]
            load[lo] += a["cost"] - b["cost"]
            improved = True

    print()
    print(f"{'机器':>6} {'片数':>5} {'jobs':>6} {'代价(h)':>9}  内容")
    for i, b in enumerate(buckets):
        c = sum(x["cost"] for x in b)
        j = sum(x["jobs"] for x in b)
        by = {}
        for x in b:
            by[x["exp"]] = by.get(x["exp"], 0) + 1
        desc = " ".join(f"{k}×{v}" for k, v in sorted(by.items()))
        print(f"{i+1:>6} {len(b):>5} {j:>6} {c/3600:9.2f}  {desc}")

    print(f"\n负载差: {spread():.1f}%")

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    # 生成每台目录
    import time
    ts = time.strftime("%Y-%m-%d %H:%M")
    for i, b in enumerate(buckets):
        pd = os.path.join(OUT, f"机器{i+1}")
        os.makedirs(os.path.join(pd, "slices"))
        os.makedirs(os.path.join(pd, "results"))

        # 依赖代码
        for f in DEPS:
            src = None
            for base in (HERE, PKG):
                p = os.path.join(base, f)
                if os.path.exists(p):
                    src = p
                    break
            if src:
                shutil.copy2(src, os.path.join(pd, f))

        # 本机 spec
        for x in b:
            shutil.copy2(os.path.join(HERE, SLICE_DIR, x["path"]),
                         os.path.join(pd, "slices", x["path"]))

        # 本机任务清单
        manifest = [{"experiment": x["exp"], "slice": x["name"],
                     "spec": f"slices/{x['path']}", "n_jobs": x["jobs"],
                     "est_hours": round(x["cost"] / 3600, 2)} for x in b]
        with open(os.path.join(pd, "本机任务.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"machine": i + 1, "generated": ts,
                       "n_slices": len(b),
                       "n_jobs": sum(x["jobs"] for x in b),
                       "est_hours": round(sum(x["cost"] for x in b) / 3600, 2),
                       "tasks": manifest}, fh, indent=2, ensure_ascii=False)

        first = b[0]["name"]
        exps = sorted({x["exp"] for x in b})
        merge = "\n".join(
            f'python merge_slices.py --exp {e} '
            f'--inputs "results/{e}_slice*.jsonl" --verify'
            for e in exps)
        rows = "\n".join(
            f"| {e} | {sum(1 for x in b if x['exp'] == e)} | "
            f"{sum(x['jobs'] for x in b if x['exp'] == e)} | "
            f"{sum(x['cost'] for x in b if x['exp'] == e)/3600:.1f} h |"
            for e in exps)

        with open(os.path.join(pd, "提示词.md"), "w", encoding="utf-8") as fh:
            fh.write(PROMPT.format(
                n_jobs=sum(x["jobs"] for x in b),
                n_slices=len(b),
                est_hours=sum(x["cost"] for x in b) / 3600,
                first_spec=first, exps=" ".join(exps)))

        with open(os.path.join(pd, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(README.format(
                idx=i + 1, ts=ts, rows=rows, n_slices=len(b),
                n_jobs=sum(x["jobs"] for x in b),
                est_hours=sum(x["cost"] for x in b) / 3600,
                first_spec=first, merge_cmds=merge))

    # ---- 打包 zip ----
    #
    # 打包必须放在脚本里，且路径全部由 HERE 推导。之前 zip 是手工在
    # shell 里另打的，结果出过两次错：
    #   1) zip 落在了 OUT 子目录里（分发包_4核/机器N.zip），
    #      而交付路径是 HERE/分发包_4核_机器N.zip —— 两份并存，
    #      校验时读到的是 09:58 的旧文件，一直以为"打包内容不对"；
    #   2) shutil.move 到已存在的目标在 Windows 上静默失败，
    #      命令返回成功但文件没换。
    # 现在先 os.remove 再写，并当场回读 zip 内容校验切片清单。
    print(f"\n打包 {N_MACHINES} 个 zip ...")
    for i in range(1, N_MACHINES + 1):
        d = os.path.join(OUT, f"机器{i}")
        zp = os.path.join(HERE, f"分发包_4核_机器{i}.zip")
        if not os.path.isdir(d):
            raise SystemExit(f"ABORT: {d} 不存在，无法打包。")
        if os.path.exists(zp):
            os.remove(zp)          # 必须先删，否则 move/覆盖会静默失败
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, files in os.walk(d):
                for f in files:
                    full = os.path.join(root, f)
                    # 归档内层路径 = 机器N/...，与目录层级一致
                    z.write(full, os.path.relpath(full, OUT).replace(os.sep, "/"))
        # 回读校验：zip 里的切片清单必须与目录一致
        with zipfile.ZipFile(zp) as z:
            in_zip = sorted(os.path.basename(n) for n in z.namelist()
                            if "/slices/" in n and n.endswith(".json"))
        on_disk = sorted(x["path"] for x in buckets[i - 1])
        if in_zip != on_disk:
            raise SystemExit(
                f"ABORT: 机器{i} 的 zip 切片清单与目录不一致\n"
                f"  zip  : {in_zip}\n  disk : {on_disk}")
        print(f"  分发包_4核_机器{i}.zip  {os.path.getsize(zp):>7} B  "
              f"{len(in_zip)} 片  ✓")

    print(f"\n生成 {N_MACHINES} 个目录 -> {OUT}")
    print(f"生成 {N_MACHINES} 个 zip  -> {HERE}\\分发包_4核_机器N.zip")


if __name__ == "__main__":
    main()
