"""
rerun_shuffle.py — 只重跑 SB2 的 shuffle 臂（18 runs）。

起因：symbol_binding.py 的 shuffle 分支写成 p = dict(p); p["facts"] = fs，
那是对局部变量重新绑定，test_p 的元素从未被改动。因此 shuffle 臂在
SB2.jsonl 里18/18 逐位等于 same —— 一个不改变任何输入的空干预。
正文§6.3 观察（一）「模型完全不依赖事实的排列顺序」建立在这个空干预上，
按本文自己的判据三不能作为证据。

本脚本只重算 shuffle 臂，其余四臂逐位保留（它们不经过该分支）。
写回时按(arm_name, n_train, seed) 精确替换，不触碰其他行。
"""
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import symbol_binding as sb

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "results", "SB2.jsonl")
OUT = os.path.join(HERE, "results", "SB2.jsonl")
LOG = os.path.join(HERE, "results", "SB2_rerun_shuffle.log")

ARM = "shuffle:pi_6cycle"
SPECS = [(ARM, n, s) for n in sb.NS for s in range(sb.N_SEEDS)]


def main():
    t0 = time.time()
    with open(LOG, "a", encoding="utf-8") as lg:
        lg.write("\n" + "=" * 70 + "\n")
        lg.write("rerun_shuffle:重跑 %s，%d runs\n" % (ARM, len(SPECS)))
        lg.write("=" * 70 + "\n")

    rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    keep = [r for r in rows if r.get("arm_name") != ARM]
    print("原有 %d 行，保留非 shuffle 的 %d 行" % (len(rows), len(keep)))

    got = {}
    with ProcessPoolExecutor(max_workers=4) as ex:
        for i, r in enumerate(ex.map(sb.job, SPECS), 1):
            got[(r["arm_name"], r["n_train"], r["seed"])] = r
            el = time.time() - t0
            with open(LOG, "a", encoding="utf-8") as lg:
                lg.write("[%2d/%d] %-20s n=%d s=%d acc=%s  %.0fs\n"
                         % (i, len(SPECS), ARM, r["n_train"], r["seed"],
                            ("%.4f" % r["acc"]) if r.get("acc") is not None
                            else "ERR", el))
            print("[%2d/%d] n=%d s=%d acc=%s  %.0fs"
                  % (i, len(SPECS), r["n_train"], r["seed"],
                     ("%.4f" % r["acc"]) if r.get("acc") is not None else "ERR",
                     el))

    final = keep + [got[k] for k in sorted(got)]
    with open(OUT, "w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    errs = [r for r in got.values() if r.get("acc") is None]
    print("\n写回 %d 行；错误 %d；总耗时 %.0fs"
          % (len(final), len(errs), time.time() - t0))
    if errs:
        print("错误样例:", errs[0].get("error"))
        sys.exit(1)


if __name__ == "__main__":
    main()