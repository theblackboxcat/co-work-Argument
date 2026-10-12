"""
make_shards.py — 把 depth_scan 剩余任务切成可分发的分片。

为什么按计算量而不是按数量切
----------------------------
每个 depth 的 n 网格不同，单次运行耗时随 n 近似线性增长。若按"每片相同
条数"平分，depth 5 的那一片会��成长尾，拖住整体交付。因此按
cost = n_train + OVERHEAD 加权切分，保证每片总代价接近。

安全性
------
已完成格点从清单剔除（绝不重跑），分片只含待做任务。
每片写成独立 --spec 文件，worker 机器直接读它，不依赖本机状态。
"""
import json, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
OUT = os.path.join(RES, "shards")
os.makedirs(OUT, exist_ok=True)

CELLS = ["TT", "Thighovl", "TU", "Tlowovl"]
DEPTHS = [3, 4, 5]
N_GRID = {
    3: [2000, 3000, 4000, 5000, 6500],
    4: [5000, 6500, 8500, 11000],
    5: [11000, 14000, 20000],
}
SEEDS = 6
N_SHARDS = 6
OVERHEAD = 3000          # fixed per-run cost, so cheap runs aren't over-packed

done = set()
p = os.path.join(RES, "depth_scan.jsonl")
if os.path.exists(p):
    for ln in open(p, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            r = json.loads(ln)
            if r.get("acc") is not None and r["acc"] == r["acc"] and "error" not in r:
                done.add((r["test_kind"], r["depth"], r["n_train"], r["seed"]))

todo = [(c, d, n, s)
        for d in DEPTHS for c in CELLS
        for n in N_GRID[d] for s in range(SEEDS)
        if (c, d, n, s) not in done]

total_all = sum(len(CELLS) * len(N_GRID[d]) * SEEDS for d in DEPTHS)
print(f"total grid      : {total_all}")
print(f"already done    : {len(done)}")
print(f"remaining (todo): {len(todo)}")
print(f"remaining by depth: {dict(sorted(collections.Counter(t[1] for t in todo).items()))}")

cost = lambda t: t[2] + OVERHEAD

# LPT scheduling: biggest jobs first onto the currently-lightest shard.
# This yields near-perfect balance for a small fixed shard count.
todo.sort(key=lambda t: -cost(t))
loads = [0] * N_SHARDS
buckets = [[] for _ in range(N_SHARDS)]
for t in todo:
    i = loads.index(min(loads))
    buckets[i].append(t)
    loads[i] += cost(t)

# Stable, readable ordering inside each shard.
order = {t: k for k, t in enumerate(sorted(todo, key=lambda x: (x[1], x[2], x[0], x[3])))}
for b in buckets:
    b.sort(key=lambda t: order[t])

print(f"\nshard count: {N_SHARDS}")
manifest = []
for i, sh in enumerate(buckets):
    name = f"depth_shard{i}"
    spec = os.path.join(OUT, f"{name}.json")
    with open(spec, "w", encoding="utf-8") as fh:
        json.dump(sh, fh)
    cst = sum(cost(t) for t in sh)
    manifest.append({
        "shard": name,
        "spec": f"results/shards/{name}.json",
        "n_jobs": len(sh),
        "cost_proxy": cst,
        "by_depth": {str(k): v for k, v in sorted(collections.Counter(t[1] for t in sh).items())},
        "by_cell": dict(sorted(collections.Counter(t[0] for t in sh).items())),
        "n_range": [min(t[2] for t in sh), max(t[2] for t in sh)],
    })
    print(f"  {name:16s} jobs={len(sh):3d} cost={cst:7d} "
          f"depths={dict(sorted(collections.Counter(t[1] for t in sh).items()))} "
          f"n=[{min(t[2] for t in sh)},{max(t[2] for t in sh)}]")

with open(os.path.join(OUT, "MANIFEST.json"), "w", encoding="utf-8") as fh:
    json.dump({"n_shards": N_SHARDS, "seeds": SEEDS,
               "total_remaining": len(todo), "shards": manifest}, fh, indent=2)

# sanity: no duplicates, no overlap with done, full coverage of todo
allt = [t for b in buckets for t in b]
assert len(allt) == len(set(allt)) == len(todo), "coverage/duplication error"
assert not (set(allt) & done), "shard overlaps with completed work"
print(f"\nverified: {len(allt)} jobs, no duplicates, no overlap with completed, "
      f"covers all remaining")
print(f"wrote {N_SHARDS} specs + MANIFEST.json -> results/shards/")
