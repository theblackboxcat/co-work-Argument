"""本机批跑：把某实验的所有切片依次跑完，写进同一个 jsonl。

用法：python run_local_batch.py --exp S2L --workers 26

为什么需要它：run_slice.py 一次只吃一个 spec 文件。S2L 有 12 片，
逐片手工敲 12 次既慢又容易漏。本脚本按片循环调用，
每片都独立进程（避免某片崩溃带走全部），并做断点续跑
（run_slice.py 自己会跳过已完成的格点，重跑本脚本即可补跑）。
"""
import argparse
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.abspath(os.path.join(HERE, "..", "results"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True, help="S2L / E6X / DPX")
    ap.add_argument("--workers", type=int, default=26)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = args.out or os.path.join(RES, f"{args.exp}_local.jsonl")
    os.makedirs(RES, exist_ok=True)

    # 合并全部切片成一个 spec：同一实验，不违反"一片只属于一个实验"
    slices = sorted(glob.glob(os.path.join(HERE, "slices", f"{args.exp}_slice*.json")))
    if not slices:
        raise SystemExit(f"ABORT: 找不到 slices/{args.exp}_slice*.json")
    import json
    spec = []
    for f in slices:
        spec += json.load(open(f, encoding="utf-8"))
    merged = os.path.join(HERE, "slices", f"{args.exp}_all.json")
    with open(merged, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=1, ensure_ascii=False)

    cost = sum(j.get("cost", 0) for j in spec) / 3600
    print(f"实验 {args.exp}: {len(slices)} 片 / {len(spec)} jobs / "
          f"{cost:.2f} 核·h / {args.workers} workers")
    print(f"估计墙钟 {cost / args.workers * 60:.0f} 分钟（不含进程启动开销）")
    print(f"输出 -> {out}")
    print(flush=True)

    t0 = time.time()
    log = os.path.join(RES, f"_run_{args.exp}.log")
    with open(log, "w", encoding="utf-8") as lf:
        p = subprocess.run(
            [sys.executable, "-u", os.path.join(HERE, "run_slice.py"),
             "--spec", f"slices/{args.exp}_all.json",
             "--out", out, "--workers", str(args.workers)],
            cwd=HERE, stdout=lf, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    print(f"\nexit={p.returncode}  用时 {dt / 60:.1f} 分钟")
    print(f"日志 -> {log}")

    # 当场验证，不看退出码
    n = 0
    err = 0
    nan = 0
    for ln in open(out, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        n += 1
        if '"error"' in ln:
            err += 1
        elif '"acc": NaN' in ln or '"acc": nan' in ln:
            nan += 1
    print(f"验证: {n} 行, error {err}, NaN {nan}")
    if n < len(spec):
        print(f"⚠️ 不足 {len(spec)} 行——重跑本脚本会续跑补齐")


if __name__ == "__main__":
    main()
