"""
run_slice.py — 切片执行器：在任意机器上跑一个 spec 文件。

=====================================================================

用法
----
    python run_slice.py --spec slices/E10_slice00.json --out results/E10_slice00.jsonl
    python run_slice.py --spec slices/E8_slice03.json  --out results/E8_slice03.jsonl --workers 4

在别的服务器上
--------------
1. 把整个 `package/` 目录（或至少 substrate2.py / surfaces.py / model.py
   与本目录）拷过去
2. 拷贝对应的 spec 文件
3. 跑上面那条命令
4. 把产出的 jsonl 传回来，用 merge_slices.py 合并

不需要拷任何数据文件——spec 里是完整的参数，不依赖本机状态。

断点续跑
--------
已存在的 (实验, 业务键) 自动跳过。中途 kill 后重跑同一条命令即可。

安全性
------
* 输出写到 --out 指定的文件，**默认不碰results/ 下的既有数据**
* 若 --out 已存在且含部分结果，自动续跑而非覆盖
* 每条结果都带 slice 名与 experiment 标签，合并时按业务键去重
"""

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)
sys.path.insert(0, HERE)


# ============================================================ 业务键 → 调用
def run_job(exp, args, seed_env=None):
    """按实验分派到一个 run_one。返回一条结果 dict。

    拉丁方改造后：词表按 (surface, seed) 在 run_one 内部现建，
    因此**任何实验都不需要进程池预初始化**。
    """
    if exp == "E4":
        import decouple_e4 as M
        kind, n, s = args
        return M.run_one(kind, n, s)

    if exp == "E6":
        import arm_k_null as M
        return M.run_one(*args)

    if exp == "E10":
        import e10_ushape as M
        return M.run_one(*args)

    if exp == "E8":
        import e8_scale as M
        return M.run_one(*args)

    if exp == "E1":
        import xarch as X
        return X.run_one(*args)

    if exp == "S2L":
        import s2_latin_rerun as M
        sf, n, s = args
        return M.run_one(sf, n, s)

    if exp == "E6X":
        import arm_k_null as M
        return M.run_one(*args)

    if exp == "DPX":
        import depth_scan as M
        cell, d, n, s = args
        return M.run_one(cell, d, n, s)

    raise ValueError(f"unknown experiment: {exp}")


def _pool_init(exp):
    """拉丁方下无需预建任何共享状态，保留空实现以兼容 ProcessPoolExecutor。"""
    return None


# 结果 dict → 业务键，用于合并去重
def _key_of(exp, res):
    """从结果 dict 反解业务键，用于去重。"""
    if exp == "E4":
        return (res.get("test_kind"), res.get("n_train"), res.get("seed"))
    if exp == "E6":
        return (res.get("mult"), res.get("surface"), res.get("n_train"),
                res.get("seed"))
    if exp == "E10":
        return (res.get("C_eff3"), res.get("surface"), res.get("n_train"),
                res.get("seed"))
    if exp == "E8":
        return (res.get("d_model"), res.get("surface"), res.get("n_train"),
                res.get("seed"))
    if exp == "E1":
        return (res.get("arch"), res.get("surface"), res.get("n_train"),
                res.get("seed"))
    if exp == "S2L":
        return (res.get("surface"), res.get("n_train"), res.get("seed"))
    if exp == "E6X":
        return (res.get("mult"), res.get("surface"), res.get("n_train"),
                res.get("seed"))
    if exp == "DPX":
        return (res.get("test_kind") or res.get("cell"), res.get("depth"),
                res.get("n_train"), res.get("seed"))
    return None


def _job(payload):
    exp, args, slice_name = payload
    try:
        r = run_job(exp, args)
        r["_slice"] = slice_name
        r["_exp"] = exp
        return r
    except Exception:
        return {"_exp": exp, "_slice": slice_name, "args": list(args),
                "acc": float("nan"),
                "error": traceback.format_exc()[-500:]}


def _args_key(exp, a):
    """业务键（与 make_slices.build_todo 的 key 同构，全部是 args 本身）。"""
    return tuple(a)


def _load_done(out, exp):
    """读已有输出，抽出已完成业务键集合。"""
    done = set()
    if not os.path.exists(out):
        return done
    for ln in open(out, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("acc") is None or r["acc"] != r["acc"] or "error" in r:
            continue
        k = _key_of(exp, r)
        if k is not None:
            done.add(tuple(k))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=str, required=True)
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec_path = args.spec if os.path.isabs(args.spec) \
        else os.path.join(HERE, args.spec)
    out = args.out if os.path.isabs(args.out) \
        else os.path.join(HERE, args.out)

    spec = json.load(open(spec_path, encoding="utf-8"))
    if not spec:
        print("empty spec")
        return
    # 一片只能属于一个实验：run_job 的派发、以及 _load_done 的续跑去重
    # 都以整批的 exp 为准。若spec 里混了多个 experiment，第 180 行
    # 取 spec[0] 会让后面所有 job 按错误的实验派发，且不报错——
    # 实测症状是 E6X 的 args（4 元组）被塞进 S2L 的 3 元组解包，
    # 报 "too many values to unpack"，任务静默变成 acc=nan。
    # 所以这里直接拒绝，不要"聪明地"按 job 派发：那会让
    # _load_done(out, exp) 的去重键和实际跑的实验对不上。
    exps = {s.get("experiment") for s in spec}
    if len(exps) > 1:
        raise SystemExit(
            f"ABORT: {os.path.basename(spec_path)} 里混了多个 experiment "
            f"{sorted(exps)}；一片必须只属于一个实验。\n"
            f"（run_job 的派发与断点续跑去重都按整批 exp 走，"
            f"混批会静默算错而不是报错。）")
    exp = spec[0]["experiment"]
    slice_name = os.path.splitext(os.path.basename(spec_path))[0]

    payloads = [(exp, tuple(s["args"]), slice_name) for s in spec]

    # 已完成过滤：业务键就是 args 本身（与 make_slices 的 key 同构）
    done = _load_done(out, exp)
    before = len(payloads)
    payloads = [p for p in payloads if p[1] not in done]
    if before - len(payloads):
        print(f"跳过已完成 {before - len(payloads)} 条（续跑）")

    est = sum(s.get("cost", 0) for s in spec) / 3600.0
    print(f"slice       : {slice_name}")
    print(f"experiment  : {exp}")
    print(f"jobs        : {len(payloads)} (of {len(spec)})")
    print(f"est. cost   : {est:.2f} h单机/ {args.workers} workers")
    print(f"out         : {out}")
    print()
    if args.dry_run:
        for p in payloads[:10]:
            print("   ", p[1])
        if len(payloads) > 10:
            print(f"    ... 其余 {len(payloads)-10} 条")
        return
    if not payloads:
        print("全部已完成，无需运行。")
        return

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    t0 = time.time()
    nd = 0
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    with open(out, "a", encoding="utf-8") as fh, ProcessPoolExecutor(
            args.workers, mp_context=ctx, initializer=_pool_init,
            initargs=(exp,)) as ex:
        futs = [ex.submit(_job, p) for p in payloads]
        nerr = 0
        for fut in as_completed(futs):
            # worker 被硬杀（OOM 等）时 fu.result() 抛 BrokenProcessPool。
            # 不接住的话，一个格子崩掉会带走本片其余所有在跑的 run，
            # 而已完成的那些仍然留在 --out 里（断点续跑能救回来，
            # 但那一轮的时间全白费）。这里按run 记录后继续。
            try:
                r = fut.result()
            except Exception:
                r = {"acc": float("nan"),
                     "error": "worker crashed: " + repr(
                         sys.exc_info()[1])[:300]}
            if r.get("error") or r.get("acc") is None \
                    or r["acc"] != r["acc"]:
                nerr += 1
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            nd += 1
            el = time.time() - t0
            acc = r.get("acc", float("nan"))
            print(f"[{nd}/{len(payloads)}] acc={acc:.3f} | "
                  f"ETA {el/nd*(len(payloads)-nd)/60:.1f}m | "
                  f"{r.get('error','')}", flush=True)
    print("done ->", out)
    if nerr:
        print(f"[警告] {nerr}/{len(payloads)} 条失败或为空，见上。"
              f"重跑同一条命令会跳过已成功的，只补失败的。")
    print(f"传回该文件，用 merge_slices.py 合并。")


if __name__ == "__main__":
    main()
