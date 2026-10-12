"""
run_shard.py — 在 worker 机器上执行一个 depth_scan 分片。

用法（在 worker 机器上，进入包含 package/ 的目录）：
    python run_shard.py --spec results/shards/depth_shard0.json \
                        --out  results/shards/depth_shard0.jsonl \
                        --workers 6

设计要点
--------
* 只依赖 depth_scan.py / model.py / surfaces.py / substrate2.py / transfer.py，
  与产出它的机器无关。确定性来自种子，结果可复现。
* 自带断点续跑：重复执行同一 --spec 不会重跑已完成的格点，中断后可安全重入。
* 结果逐行 flush 落盘，机器被抢占也不会丢失已完成部分。
* --append 模式把结果并入共享总表，适配多机协作（见 README_SHARDS.md）。
"""
import argparse, json, os, sys, time, multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def job(spec):
    cell, depth, n_train, seed = spec
    try:
        from depth_scan import run_one
        return run_one(cell, depth, n_train, seed)
    except Exception:
        import traceback
        return {"cell": cell, "test_kind": cell, "arm": "depth_scan",
                "depth": depth, "n_train": n_train, "seed": seed,
                "acc": float("nan"), "error": traceback.format_exc()[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="分片 JSON: [[cell,depth,n,seed],...]")
    ap.add_argument("--out", required=True, help="本分片输出 jsonl")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--append-to", default=None,
                    help="可选：同时并入这个共享总表（多机汇总用）")
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as fh:
        specs = [tuple(x) for x in json.load(fh)]
    print(f"spec: {args.spec}  jobs: {len(specs)}  workers: {args.workers}", flush=True)

    # resume: skip anything already present in --out
    done = set()
    if os.path.exists(args.out):
        for ln in open(args.out, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try:
                    r = json.loads(ln)
                    if r.get("acc") is not None and r["acc"] == r["acc"] and "error" not in r:
                        done.add((r.get("cell") or r.get("test_kind"),
                                  r["depth"], r["n_train"], r["seed"]))
                except Exception:
                    pass
    todo = [s for s in specs if s not in done]
    print(f"already done: {len(done)}  -> to run: {len(todo)}", flush=True)

    t0 = time.time(); nd = 0
    ctx = mp.get_context("spawn")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fh = open(args.out, "a", encoding="utf-8")
    shared = open(args.append_to, "a", encoding="utf-8") if args.append_to else None
    try:
        with ProcessPoolExecutor(args.workers, mp_context=ctx) as ex:
            futs = {ex.submit(job, s): s for s in todo}
            for fut in as_completed(futs):
                r = fut.result()
                line = json.dumps(r, ensure_ascii=False) + "\n"
                fh.write(line); fh.flush()
                if shared:
                    shared.write(line); shared.flush()
                nd += 1
                el = time.time() - t0
                eta = el / nd * (len(todo) - nd)
                print(f"[{nd}/{len(todo)}] {r.get('cell')} d={r.get('depth')} "
                      f"n={r.get('n_train')} s={r.get('seed')} "
                      f"acc={r.get('acc', float('nan')):.3f} | ETA {eta/60:.1f}m",
                      flush=True)
    finally:
        fh.close()
        if shared:
            shared.close()
    print("done ->", args.out)


if __name__ == "__main__":
    main()
