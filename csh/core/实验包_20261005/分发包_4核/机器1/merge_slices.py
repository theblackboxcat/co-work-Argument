"""
merge_slices.py — 合并各服务器回传的切片结果。

=====================================================================

为什么需要去重
--------------
多台机器可能并行跑同一片（网络重试、人工重复分发），或某片被跑了两遍。
合并时按业务键去重，**先到的为准**（因为文件按时间顺序追加，
先写入的是更早那次跑的，通常更可信）。

同时报出冲突：若同一业务键有两条且acc 不同，打印出来供人工判断——
这可能是真bug，也可能只是种子波动。**不自动丢弃，报出来。**

用法
----
    # 合并某实验的所有切片
    python merge_slices.py --exp E10 --inputs results/E10_slice*.jsonl \
        --out results/E10_merged.jsonl

    # 先干跑看有没有冲突，不写文件
    python merge_slices.py --exp E10 --inputs "results/E10_slice*.jsonl" --check

    # 验证覆盖度：是否跑满了网格
    python merge_slices.py --exp E10 --inputs "results/E10_slice*.jsonl" --verify
"""

import argparse
import glob
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))

# 网格定义（与 make_slices 一致）
GRID = {
    "E4": {"kinds": ["root_swap", "chain_reverse", "null_renaming"],
           "surfs": [None], "ns": [2000, 3000, 4000, 5000, 6500],
           "seeds": list(range(6)),
           "key": lambda r: (r.get("test_kind"), r.get("n_train"),
                             r.get("seed"))},
    "E6": {"mults": [2, 3, 4],
           "surfs": ["en", "relperm", "entperm"],
           "ns": [2000, 3000, 4000, 5000, 6500], "seeds": list(range(6)),
           "key": lambda r: (r.get("mult"), r.get("surface"),
                             r.get("n_train"), r.get("seed"))},
    "E10": {"effs": [24, 16, 8, 5, 2], "surfs": ["en", "relperm"],
            "ns": [2000, 3000, 4000, 5000, 6500], "seeds": list(range(6)),
            "key": lambda r: (r.get("C_eff3"), r.get("surface"),
                              r.get("n_train"), r.get("seed"))},
    "E8": {"ds": [64, 128, 256, 384, 512],
           "surfs": ["zh", "en", "lisp", "math", "code", "alien", "relperm"],
           "ns": [2000, 3000, 4000, 5000, 6500], "seeds": list(range(4)),
           "key": lambda r: (r.get("d_model"), r.get("surface"),
                             r.get("n_train"), r.get("seed"))},
    "E1": {"archs": ["A1", "A2", "A3", "A4"],
           "surfs": ["zh", "en", "lisp", "math", "code", "alien", "relperm"],
           "ns": [2000, 3000, 4000, 5000, 6500], "seeds": list(range(6)),
           "key": lambda r: (r.get("arch"), r.get("surface"),
                             r.get("n_train"), r.get("seed"))},
    # ---- 2026-10-06 新增三实验 ----
    "S2L": {"surfs": ["zh", "en", "lisp", "math", "code", "alien",
                      "relperm", "entperm"],
            "ns": [2000, 3000, 4000, 5000, 6500], "seeds": list(range(8)),
            "key": lambda r: (r.get("surface"), r.get("n_train"),
                              r.get("seed"))},
    "E6X": {"mults": [2, 3, 4],
            "surfs": ["en", "relperm", "entperm"],
            "ns": [6500, 8500, 11000, 14000], "seeds": list(range(6)),
            "key": lambda r: (r.get("mult"), r.get("surface"),
                              r.get("n_train"), r.get("seed"))},
    "DPX": {"cells": ["TT", "TU", "Thighovl", "Tlowovl"],
            "depths": [3, 4, 5],
            "ns": [4000, 5000, 6500, 8500, 11000, 14000],
            "seeds": list(range(6)),
            "key": lambda r: (r.get("test_kind") or r.get("cell"),
                              r.get("depth"), r.get("n_train"),
                              r.get("seed"))},
}


def expected_keys(exp):
    g = GRID[exp]
    keys = set()
    if exp == "E4":
        for k in g["kinds"]:
            for n in g["ns"]:
                for s in g["seeds"]:
                    keys.add((k, n, s))
    elif exp == "E6":
        for m in g["mults"]:
            for sf in g["surfs"]:
                for n in g["ns"]:
                    for s in g["seeds"]:
                        keys.add((m, sf, n, s))
    elif exp == "E10":
        for e in g["effs"]:
            for sf in g["surfs"]:
                for n in g["ns"]:
                    for s in g["seeds"]:
                        keys.add((e, sf, n, s))
    elif exp == "E8":
        for d in g["ds"]:
            for sf in g["surfs"]:
                for n in g["ns"]:
                    for s in g["seeds"]:
                        keys.add((d, sf, n, s))
    elif exp == "E1":
        for a in g["archs"]:
            for sf in g["surfs"]:
                for n in g["ns"]:
                    for s in g["seeds"]:
                        keys.add((a, sf, n, s))
    elif exp == "S2L":
        for sf in g["surfs"]:
            for n in g["ns"]:
                for s in g["seeds"]:
                    keys.add((sf, n, s))
    elif exp == "E6X":
        for m in g["mults"]:
            for sf in g["surfs"]:
                for n in g["ns"]:
                    for s in g["seeds"]:
                        keys.add((m, sf, n, s))
    elif exp == "DPX":
        for c in g["cells"]:
            for d in g["depths"]:
                for n in g["ns"]:
                    for s in g["seeds"]:
                        keys.add((c, d, n, s))
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True)
    ap.add_argument("--inputs", required=True,
                    help="glob 模式，务必加引号")
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true", help="只报冲突，不写文件")
    ap.add_argument("--verify", action="store_true", help="检查网格覆盖")
    args = ap.parse_args()

    files = sorted(glob.glob(args.inputs))
    if not files:
        print(f"没有文件匹配 {args.inputs}")
        return
    print(f"exp = {args.exp}   输入 {len(files)} 个文件")
    for f in files:
        print(f"  {f}")

    keyfn = GRID[args.exp]["key"]
    seen = {}
    conflicts = []
    bad = 0
    for f in files:
        for ln in open(f, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                bad += 1
                continue
            if r.get("acc") is None or r["acc"] != r["acc"] or "error" in r:
                bad += 1
                continue
            k = tuple(keyfn(r))
            if k in seen:
                if abs(seen[k]["acc"] - r["acc"]) > 1e-9:
                    conflicts.append((k, seen[k]["acc"], r["acc"],
                                      seen[k].get("_slice"), r.get("_slice")))
                continue
            seen[k] = r

    print()
    print(f"有效 {len(seen)} 条   跳过无效/错误 {bad} 条")

    if conflicts:
        print()
        print(f"!! {len(conflicts)} 处冲突（同一格点被跑出不同 acc）：")
        for k, a1, a2, s1, s2 in conflicts[:20]:
            print(f"   {k}  acc={a1:.4f} ({s1})  vs  {a2:.4f} ({s2})")
        if len(conflicts) > 20:
            print(f"   ... 其余 {len(conflicts)-20} 处")
        print("   这些不是错误（可能是重复分发），但值得看一眼。")
        print("   合并时取先到的。")

    if args.verify:
        exp_keys = expected_keys(args.exp)
        missing = exp_keys - set(seen)
        extra = set(seen) - exp_keys
        print()
        print("=" * 60)
        print(f"网格覆盖：应有 {len(exp_keys)}，实得 {len(seen)}，"
              f"缺 {len(missing)}")
        if missing:
            by = defaultdict(int)
            for k in missing:
                by[str(k[0])] += 1
            print("  缺失分布：", dict(sorted(by.items())))
            print("  补跑：把缺的格点用 make_slices.py --experiment "
                  f"{args.exp} 重新切（它会读现有结果自动剔除已完成的）")
        if extra:
            print(f"  !! 有 {len(extra)} 条不在网格内，检查是否参数写错")
        print("=" * 60)
        return

    if args.check:
        print("\n--check 模式，未写文件。")
        return

    out = args.out or os.path.join(
        PKG, "results", f"{args.exp}_merged.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for k in sorted(seen, key=str):
            fh.write(json.dumps(seen[k], ensure_ascii=False) + "\n")
    print(f"\n-> {out}  ({len(seen)} 条)")


if __name__ == "__main__":
    main()
