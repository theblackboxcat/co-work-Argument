"""核对资料库新回传切片的交付量，并重算三实验覆盖度。

用法：python audit_library_returns.py
"""
import collections
import glob
import json
import os
import re
import sys

PKG = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(PKG, "results")
LIB = os.path.join(RES, "from_library")
SLICES = os.path.join(PKG, "实验包_20261005", "slices")

# 网格定义（与 make_slices.py 保持一致）
NS = [2000, 3000, 4000, 5000, 6500]
S2_SURFS = ["zh", "en", "lisp", "math", "code", "alien", "relperm", "entperm"]
S2_SEEDS = 8
E6_MULTS = [2, 3, 4]
E6_SURFS = ["en", "relperm", "entperm"]
E6_EXT_NS = [6500, 8500, 11000, 14000]
E6_SEEDS = 6
DC_N = [4000, 5000, 6500, 8500, 11000, 14000]
DC_DEPTHS = [3, 4, 5]
DC_CELLS = ["TT", "TU", "Thighovl", "Tlowovl"]
DC_SEEDS = 6


def key_of(r):
    """返回 (实验, 业务键) 或 None。判别式与 make_slices._load_all_done 一致。"""
    arm = r.get("arm", "")
    acc = r.get("acc")
    if acc is None or acc != acc or "error" in r:
        return None
    if arm == "S2_latin":
        n = r.get("n_train")
        if n not in NS:
            return None
        return ("S2L", (r.get("surface"), n, r.get("seed")))
    if arm == "K_null":
        n = r.get("n_train")
        if n in E6_EXT_NS:
            return ("E6X", (r.get("mult"), r.get("surface"), n, r.get("seed")))
        if n in NS:
            return ("E6", (r.get("mult"), r.get("surface"), n, r.get("seed")))
        return None
    if arm in ("depth_scan", "depth_cross"):
        n = r.get("n_train")
        if n not in DC_N:
            return None
        return ("DPX", (r.get("test_kind") or r.get("cell"), r.get("depth"),
                        n, r.get("seed")))
    if arm == "E4":
        return ("E4", (r.get("test_kind"), r.get("n_train"), r.get("seed")))
    if arm == "E10":
        return ("E10", (r.get("C_eff3"), r.get("surface"), r.get("n_train"),
                        r.get("seed")))
    return None


def scan(paths, tag):
    """读一批 jsonl，返回 {exp: set(keys)} 与统计。"""
    done = collections.defaultdict(set)
    nline = nbad = 0
    for p in paths:
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            nline += 1
            try:
                r = json.loads(ln)
            except Exception:
                nbad += 1
                continue
            k = key_of(r)
            if k is None:
                if r.get("acc") is None or r.get("acc") != r.get("acc") \
                        or "error" in r:
                    nbad += 1
                continue
            done[k[0]].add(k[1])
    return done, nline, nbad


def full_grid(exp):
    if exp == "S2L":
        return {(sf, n, s) for sf in S2_SURFS for n in NS for s in range(S2_SEEDS)}
    if exp == "E6X":
        return {(m, sf, n, s) for m in E6_MULTS for sf in E6_SURFS
                for n in E6_EXT_NS for s in range(E6_SEEDS)}
    if exp == "DPX":
        return {(c, d, n, s) for d in DC_DEPTHS for c in DC_CELLS
                for n in DC_N for s in range(DC_SEEDS)}
    return set()


def main():
    # ---- 1. 每片交付量核对 ----
    print("=" * 78)
    print("1. 资料库新回传：spec 派工 vs 实际交付")
    print("=" * 78)
    libfiles = sorted(glob.glob(os.path.join(LIB, "*.jsonl")))
    # 只看属于本轮 7 台 4 核包的（带 M#_ 前缀或在 v3 文件夹里）
    new_batch = [p for p in libfiles
                 if re.search(r"(^M\d_|__)", os.path.basename(p))]
    rows = []
    tot_spec = tot_got = 0
    for p in sorted(new_batch):
        base = os.path.basename(p)
        m = re.search(r"(S2L|E6X|DPX)_slice(\d+)", base)
        if not m:
            continue
        exp, idx = m.group(1), m.group(2)
        spec_path = os.path.join(SLICES, f"{exp}_slice{idx}.json")
        nspec = 0
        if os.path.exists(spec_path):
            nspec = len(json.load(open(spec_path, encoding="utf-8")))
        ngot = 0
        keys = set()
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            k = key_of(r)
            if k:
                ngot += 1
                keys.add(k[1])
        rows.append((base, exp, nspec, ngot, len(keys)))
        tot_spec += nspec
        tot_got += ngot
    print(f"{'文件':46s} {'实验':5s} {'派工':>5s} {'实收':>5s} {'去重':>5s}")
    for base, exp, nspec, ngot, nk in rows:
        flag = "" if (nspec == 0 or nk >= nspec) else "  <-- 缺口"
        print(f"{base:46s} {exp:5s} {nspec:5d} {ngot:5d} {nk:5d}{flag}")
    print(f"\n本轮合计：派工 {tot_spec} / 实收 {tot_got} / 去重后 {tot_got}")
    print(f"（注：old batch 的 22 片不带 M# 前缀，不计入本轮）")

    # ---- 2. 全量合并后的覆盖度 ----
    print()
    print("=" * 78)
    print("2. 全量合并后的三实验覆盖度")
    print("=" * 78)
    top = glob.glob(os.path.join(RES, "*.jsonl"))
    d4 = glob.glob(os.path.join(RES, "from_4core", "*.jsonl"))
    allp = top + d4 + libfiles
    done, nline, nbad = scan(allp, "all")
    print(f"扫描 {len(allp)} 个文件 / {nline} 行，"
          f"无效行 {nbad}（error 或 NaN）")
    for e in ("S2L", "E6X", "DPX", "E6", "E4", "E10"):
        g = full_grid(e)
        if not g:
            print(f"  {e:5s} done = {len(done.get(e, set())):4d}（网格未定义，仅计数）")
            continue
        miss = g - done.get(e, set())
        print(f"  {e:5s} done = {len(done.get(e, set()) & g):4d} / {len(g):4d}"
              f"   待跑 {len(miss):4d}"
              f"   ({100*len(done.get(e,set())&g)/len(g):5.1f}%)")
        if miss:
            by_surf = collections.Counter(k[0] for k in miss)
            print("        缺口按第一维:", dict(sorted(by_surf.items(),
                                                      key=lambda x: -x[1])))

    # ---- 3. 只用「旧数据 + 本轮新回传」的覆盖度 ----
    print()
    print("=" * 78)
    print("3. 只算 资料库新回传 相对 「之前已完成」的增量")
    print("=" * 78)
    old, _, _ = scan(top + d4, "old")
    for e in ("S2L", "E6X", "DPX"):
        g = full_grid(e)
        o = old.get(e, set()) & g
        n = done.get(e, set()) & g
        print(f"  {e:5s} 之前 {len(o):4d} -> 现在 {len(n):4d}"
              f"   净增 {len(n) - len(o):4d}   仍待跑 {len(g - n):4d}")


if __name__ == "__main__":
    main()