# -*- coding: utf-8 -*-
"""
merge_shards.py —— 汇总各分片产出的 JSONL，去重、校验、合并。

用法：
    cd /workspace/csh_results
    python3 merge_shards.py                 # 合并当前目录下 shard*.jsonl
    python3 merge_shards.py a.jsonl b.jsonl # 或显式列出

产出：
    final_merged.jsonl   去重后的合并结果（供 analyze_final.py 使用）
    标准输出打印校验报告

去重键：(mult, surface, n_train, seed)
同一键出现多次时保留最后一条（后跑的覆盖先跑的）。
"""

import collections
import glob
import json
import os
import sys

KEY = lambda r: (r.get("mult"), r.get("surface"), r.get("n_train"), r.get("seed"))


def load(paths):
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        rows.append(json.loads(ln))
                    except Exception:
                        pass
    return rows


def main():
    paths = sys.argv[1:] or sorted(glob.glob("shard*.jsonl"))
    if not paths:
        print("没有找到 shard*.jsonl")
        return
    print("输入文件：%s" % ", ".join(os.path.basename(p) for p in paths))

    rows = load(paths)
    print("读入条目：%d" % len(rows))

    seen, dup = {}, 0
    for r in rows:
        k = KEY(r)
        if k in seen:
            dup += 1
        seen[k] = r
    out = list(seen.values())
    print("去重之后：%d（重复 %d）" % (len(out), dup))

    # ── 校验：任一不变量被破坏都要停下来查，不能硬合并 ──
    errs = []
    bad = [r for r in out if "error" in r]
    if bad:
        errs.append("有 %d 条带 error 字段" % len(bad))
    toks = {r.get("tok") for r in out}
    if toks != {46}:
        errs.append("tok 不唯一/不等于 46：%s（配平被破坏）" % sorted(toks))
    ce = {r.get("C_eff3") for r in out}
    if ce != {24}:
        errs.append("C_eff3 不唯一/不等于 24：%s（基质构造被改）" % sorted(ce))
    acc_bad = [r for r in out if not isinstance(r.get("acc"), (int, float))]
    if acc_bad:
        errs.append("有 %d 条 acc 不是数字" % len(acc_bad))

    seeds = sorted({r.get("seed") for r in out})
    print("种子集合：%s（共 %d 个）" % (seeds, len(seeds)))
    print("arm 分布：%s" % dict(collections.Counter(r.get("arm") for r in out)))
    print("surface ：%s" % dict(collections.Counter(r.get("surface") for r in out)))
    print("n_train ：%s" % dict(sorted(collections.Counter(r.get("n_train") for r in out).items())))
    acc = [r["acc"] for r in out if isinstance(r.get("acc"), (int, float))]
    if acc:
        print("acc 范围：%.3f – %.3f（随机基线 0.056，判据 0.60）" % (min(acc), max(acc)))
        print("越过判据的比例：%.1f%%" % (100.0 * sum(1 for a in acc if a >= 0.60) / len(acc)))

    gap = [s for s in range(min(seeds), max(seeds) + 1) if s not in seeds] if seeds else []
    if gap:
        print("⚠ 种子区间有缺口：%s（缺的分片还没交回来）" % gap)

    if errs:
        print("\n❌ 校验未通过，未写出文件：")
        for e in errs:
            print("   - %s" % e)
        return

    with open("final_merged.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n✅ 已写出 final_merged.jsonl（%d 条）" % len(out))
    print("下一步：python3 analyze_final.py final_merged.jsonl")


if __name__ == "__main__":
    main()
