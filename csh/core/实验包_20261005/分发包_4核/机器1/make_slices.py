"""
make_slices.py — 把全部待办实验切成可分发给多台机器的等成本切片。

=====================================================================

为什么需要这个
--------------
本机32 核，但同时跑多个实验会互抢 CPU（实测：单 run 从 105 s 涨到 235 s）。
把待办实验切开后分发到多台服务器，总墙钟时间 = 最长一片，
而不是全部串行。

复用 depth 5 的分片思路（见 make_shards.py），但扩展到 5 个实验：
  1. 已完成格点从清单剔除 —— 绝不重跑（这是上一次事故的根因）
  2. 按 cost = 单run 预估秒数做 LPT 装箱，而非按条数平分
  3. 每片是独立 spec 文件，不依赖本机状态
  4. 每片输出独立 jsonl，合并时按 key 去重

成本模型（实测标定）
--------------------
单 run 秒数 ≈ OVERHEAD + n_train * K *架构系数
实测 A1: n=2000 -> 7 s, n=6500 -> 105 s  =>  K ≈ 0.019, OVERHEAD ≈ 30
E8 的 d 越大越贵：成本∝ d^2
E10 的低 C_eff 档生成器退化，dataset() 重试多，额外加惩罚项

不重跑的保证
------------
1. 本脚本读全部已有 jsonl，构造 done 集合，todo 里绝不包含 done
2. 断言：分片内无重复、分片间无重叠、分片并集 == todo
3. 每片 spec 里带 `_experiment` 字段，worker 写到自己的文件名
4. 合并脚本 merge_slices.py 按 (实验, 业务键) 去重，重复的取先到的

用法
----
    python make_slices.py# 生成
    python make_slices.py --experiment E10# 只切一个实验
    python make_slices.py --n-slices 12# 切12 片（服务器数 x 每机并行度）
"""

import argparse
import json
import os
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
RES = os.path.join(PKG, "results")
OUT = os.path.join(HERE, "slices")
os.makedirs(OUT, exist_ok=True)

NS = [2000, 3000, 4000, 5000, 6500]
SEEDS6 = list(range(6))

# ---- 2026-10-06 新增：三个实验的网格 ----
# S2 拉丁方重跑：8 表面（6 真实 + 2 null）× 8 种子。种子数必须 =表面数，
# 否则 slot 配平退化回「固定 slot」，那正是 codex 证伪的设计。
S2_SURFS = ["zh", "en", "lisp", "math", "code", "alien", "relperm", "entperm"]
S2_SEEDS = 8

# E6 扩展 n 网格：原网格上界 6500，en 在 mult=2/3 有 4/6 种子阈值压在上界
# （右删失）。这里只补上界及以上的点，原网格的格点已在 E6_merged 里。
E6_EXT_NS = [6500, 8500, 11000, 14000]
E6_SEEDS = 6

# depth × n 交叉：让每个 depth 跑同一组 n，拆开 depth×n 的共变
DEPTH_CROSS_N = [4000, 5000, 6500, 8500, 11000, 14000]
DEPTH_CROSS_DEPTHS = [3, 4, 5]
DEPTH_CROSS_CELLS = ["TT", "TU", "Thighovl", "Tlowovl"]
DEPTH_CROSS_SEEDS = 6

# 各实验网格

# ---- 成本模型（实测标定，2026-10-06 重标）----
# 原模型 K_SEQ=0.019 / OVERHEAD=30 是从surface_fix2 标来的，
# 但 surface_fix2 的 vocab 是 31（旧id 分块），本轮三实验的 vocab 是
# 105–225，实测单 run 成本差一个数量级。用各自实测中位数重标：
#
#   E6 / S2L（vocab 105–225，序列模型，depth 3）
#     实测 E6_merged: (2,2000)=10.4s  (2,6500)=28.8s
#     => K ≈ (28.8-10.4)/(6500-2000) = 0.00409, OVERHEAD ≈ 2.2
#
#   ⚠ 2026-10-06 修正：K_SEQ 原是拿 E6（vocab 87）标定的，
#   但 S2L 的 vocab 是 225，更大。用 4 核机回传的 400+ runs 实测重标：
#     n=2000→20.7s  3000→30.4s  4000→40.0s  5000→49.8s  6500→64.5s
#     回归 secs = 1.2 + 0.00974 * n   R²=1.000
#   旧值低估 2.2 倍。
#
#   ⚠⚠ 更大的坑（2026-10-06 本机实跑才发现）：
#   **同一格点在 4 核机 64.5 s，本机单 run 要 236 s，慢 3.7 倍。**
#   但这不是硬件差，是**测量口径**差：
#     - 4 核回传的 secs 是在 `--workers 4` 并发下测的，含排队时间但
#       每个 worker 只占 1 核，且模型库已常驻；
#     - 本机 secs 用 `--workers 1` 测，spawn 模式下每个 worker 都要
#       重新import 一遍模型库，**单 run 有~200 s 固定开销**。
#   本机实测：n=2000→181s, n=3000→270s, n=6500→236s（非线性，
#   因为 26 worker 同时 import 时互相抢磁盘 IO）。
#
#   结论（写死在这里，别再犯）：
#   1. secs 字段**只在同一 (硬件, workers 数) 下可比**。跨机器比较
#      成本必须重标，不能搬系数。
#   2. 成本模型里的 secs 应是**单 worker 串行**的边际成本，
#      固定开销（import）要单独算进 OVERHEAD，不能混进斜率。
#   3. 墙钟 =总代价 / workers 只在 worker 数适中时成立。
#      workers 太多时 import 争抢会让单 run 变慢，总时间不降反升。
K_SEQ = 0.00974   # S2L: vocab 225, depth 3，4 核 workers=4 口径
OVERHEAD = 1.2# S2L 同上
#
#   DPX（depth_scan 同款，token 序列随 depth 变长）
#     这里必须用**逐 depth 的线性回归** secs = A_d + B_d * n，不能用
#     median(secs/n)。原因是 depth4/5 有 150–200 s 的固定开销
#     （数据集构造、词表构建等与 n 无关的部分），用 secs/n 的中位数当
#     斜率会把这份固定开销摊进小 n，既漏了 intercept 又把 slope 拉偏。
#
#     回归结果（n 单位：token 数；secs 单位：秒；R2 见括号）：
#       depth 3: A=-9.7   B=0.08181  (R2=0.999)  覆盖 n=2000..6500
#       depth 4: A=196.0  B=0.05622  (R2=0.919)  覆盖 n=5000..11000
#       depth 5: A=148.6  B=0.01214  (R2=0.923)  覆盖 n=4000..20000
#
#     depth5 的 n=4000 点来自 2026-10-06 分发包冒烟实测
#     （depth5/TT/n=4000/seed5 => 178.2 s）。这个点很关键：DPX 网格
#     从 n=4000 起，而 depth5 原有实测只覆盖 n>=11000，缺了这个点
#     depth5 会被外推到 56 s（实测 178 s，低估 3.2 倍）。
#
#     注意 depth 越大每 token 反而越便宜（B_5 << B_3），不是"越深越贵"：
#     depth5 的生成器更容易产出短样本。所以三档各自回归，不互相外推。
#
# DPX：逐 depth 的 (intercept, slope)，来自线性回归而非 secs/n 中位数。
# 数据源是 results/depth_scan_all.jsonl（本机串行，每档 6 runs），
# 不含4 核回传数据（那是在4 worker 并发下测的，会低估单 run 成本）。
COEF_DEPTH = {
    3: (-9.7, 0.08181),
    4: (196.0, 0.05622),
    5: (148.6, 0.01214),
}


def cost_seq(n):
    return OVERHEAD + K_SEQ * n


def cost_d(n, d):
    """E8：宽度 d 的平方律。d=128 归一到 1.0。"""
    return (OVERHEAD + K_SEQ * n) * (d / 128.0) ** 2


def cost_depth(n, depth):
    """DPX：逐 depth 的实测线性回归 secs = A_d + B_d * n。

    不用 (n × depth) 的简单外推——实测 depth5 反而比 depth3 便宜
    （B_5=0.012 vs B_3=0.082），因为 depth5 的生成器更容易产出短样本。
    外推会把这部分便宜吃掉，导致 DPX 片数估偏。

    也不能用 median(secs/n)：depth4/5 有 150–200 s 固定开销，
    除以 n 会把它摊薄，n=4000 处会低估到 1/3（见 K_SEQ 上方注释）。
    """
    a, b = COEF_DEPTH.get(depth, COEF_DEPTH[3])
    return max(a + b * n, 1.0)


# E10 的低 C_eff 档生成器退化，dataset() 要重试更多次
E10_CEFF_PENALTY = {24: 1.0, 16: 1.0, 8: 1.1, 5: 1.5, 2: 2.5}

E10_CEFFS = [24, 16, 8, 5, 2]
E6_MULTS = [2, 3, 4]
E6_SURFS = ["en", "relperm", "entperm"]
E4_KINDS = ["root_swap", "chain_reverse", "null_renaming"]
E8_DS = [64, 128, 256, 384, 512]
E8_SURFS = ["zh", "en", "lisp", "math", "code", "alien", "relperm"]
E1_ARCHS = ["A1", "A2", "A3", "A4"]
E1_SURFS = ["zh", "en", "lisp", "math", "code", "alien", "relperm"]

# ---- 拉丁方配平要求：seed数 >= 表面数（见 latin.py 与 S1_FINAL.md 结论三）----
# 固定 slot 的方案已被 codex 证伪（同表面同种子只改 slot，n=4000 极差
# 0.1675–1.0000，方差比 1.04= 初始化运气）。故 seed 数必须够填满 slot。
E4_SEEDS = 6      # 3 个变换
E6_SEEDS = 6      # 3 个表面
E10_SEEDS = 6     # 2 个表面
E8_SEEDS = 7      # 7 个表面  <-原为 4，不满足配平
E1_SEEDS = 7      # 7 个表面  <- 原为 6，不满足配平

# 各实验网格上限 —— done 数超过它就说明判别式写宽了（见 main 的硬保险）
GRID_CAP = {
    "E4":  len(E4_KINDS) * len(NS) * E4_SEEDS,
    "E6":  len(E6_MULTS) * len(E6_SURFS) * len(NS) * E6_SEEDS,
    "E10": len(E10_CEFFS) * 2 * len(NS) * E10_SEEDS,
    "E8":  len(E8_DS) * len(E8_SURFS) * len(NS) * E8_SEEDS,
    "E1":  len(E1_ARCHS) * len(E1_SURFS) * len(NS) * E1_SEEDS,
    # 新增三个
    "S2L": len(S2_SURFS) * len(NS) * S2_SEEDS,
    "E6X": len(E6_MULTS) * len(E6_SURFS) * len(E6_EXT_NS) * E6_SEEDS,
    "DPX": len(DEPTH_CROSS_DEPTHS) * len(DEPTH_CROSS_N)
           * len(DEPTH_CROSS_CELLS) * DEPTH_CROSS_SEEDS,
}


# ============================================================ done 收集
def _load_all_done():
    """扫 results/ 下所有 jsonl，构造 (实验, 业务键) 的 done 集合。

    业务键是元组，实验名从 arm 字段或文件名推断。
    """
    done = collections.defaultdict(set)
    for fn in os.listdir(RES):
        if not fn.endswith(".jsonl"):
            continue
        path = os.path.join(RES, fn)
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("acc") is None or r["acc"] != r["acc"] or "error" in r:
                continue
            arm = r.get("arm", "")
            # 判别式必须用 arm 字段，不能用"C_eff3 in r"——论文原有的
            # final.jsonl 臂 K 记录也带 C_eff3，会被误判成 E10 已完成，
            # 导致真任务被当成"已完成"而漏跑（实测done=1440，上限只有300）。
            if arm == "E10":
                done["E10"].add((r.get("C_eff3"), r.get("surface"),
                                 r.get("n_train"), r.get("seed")))
            elif arm == "K_null":
                # E6 原网格与 E6X 扩展网格**共用 arm="K_null"**，
                # 必须靠 n_train 区分，否则 E6X 的记录会被记进 E6 的
                # done（实测 E6 done=351 = 270 + 81，E6X done=0，
                # 于是 216 个 E6X 真任务被当成"已完成"而漏跑）。
                #
                # 两网格在 n 上只共享 6500，其余完全不重叠：
                #   E6  原：2000/3000/4000/5000/6500
                #   E6X扩展：6500/8500/11000/14000
                # 所以判据是"n 是否属于扩展网格"，6500 归 E6
                # （它本来就跑完了，计入不会漏跑；归 E6X 也不会漏）。
                n = r.get("n_train")
                if n in E6_EXT_NS:
                    done["E6X"].add((r.get("mult"), r.get("surface"),
                                     n, r.get("seed")))
                else:
                    done["E6"].add((r.get("mult"), r.get("surface"),
                                    n, r.get("seed")))
            elif arm == "E4":
                done["E4"].add((r.get("test_kind"), r.get("n_train"),
                                r.get("seed")))
            elif arm == "E8":
                done["E8"].add((r.get("d_model"), r.get("surface"),
                                r.get("n_train"), r.get("seed")))
            elif arm == "X":
                done["E1"].add((r.get("arch"), r.get("surface"),
                                r.get("n_train"), r.get("seed")))
            elif arm == "S2_latin":
                done["S2L"].add((r.get("surface"), r.get("n_train"),
                                 r.get("seed")))
            elif arm == "depth_cross" or arm == "depth_scan":
                # depth_scan_all.jsonl 里arm 是 "depth_scan"，
                # depth_cross.py 产出的是 "depth_scan"（复用 depth_scan.job）。
                # 两者业务键相同 (cell, depth, n, seed)，须一并计入 done，
                # 否则 depth_cross 的共用网格上已有格点会被重复跑一遍
                # （实测会多跑 216 个jobs = 全部 3 个重叠 n × 4 cell × 6 种子）。
                #
                # 但**必须只计入 DPX 网格内的 n**：depth_scan_all 用的是
                # 自己的 n 网格（含 2500/3500/4500/6000/8000/20000），
                # 这些点不在 DEPTH_CROSS_N 里。不加过滤会让 done
                # 虚高到 630 > 上限 432（GRID_CAP 硬保险拦下）。
                n = r.get("n_train")
                if n in DEPTH_CROSS_N:
                    done["DPX"].add((r.get("test_kind") or r.get("cell"),
                                     r.get("depth"), n, r.get("seed")))
            # E6 的扩展网格与原网格同arm（K_null），靠 n_train 区分：
            # 原网格已在 done 里，扩展网格是新点，故只需同一判别式。
    return done


# ============================================================ 待办清单
def build_todo(exp, done):
    """返回 [(业务键元组, cost秒)]。业务键决定 worker 的执行参数。"""
    todo = []
    d = done.get(exp, set())

    if exp == "E4":
        for k in E4_KINDS:
            for n in NS:
                for s in range(E4_SEEDS):
                    key = (k, n, s)
                    if key not in d:
                        todo.append((key, cost_seq(n)))

    elif exp == "E6":
        for m in E6_MULTS:
            for sf in E6_SURFS:
                for n in NS:
                    for s in range(E6_SEEDS):
                        key = (m, sf, n, s)
                        if key not in d:
                            todo.append((key, cost_seq(n)))

    elif exp == "E10":
        for ce in E10_CEFFS:
            pen = E10_CEFF_PENALTY[ce]
            for sf in ["en", "relperm"]:
                for n in NS:
                    for s in range(E10_SEEDS):
                        key = (ce, sf, n, s)
                        if key not in d:
                            todo.append((key, cost_seq(n) * pen))

    elif exp == "S2L":
        for sf in S2_SURFS:
            for n in NS:
                for s in range(S2_SEEDS):
                    key = (sf, n, s)
                    if key not in d:
                        todo.append((key, cost_seq(n)))

    elif exp == "E6X":
        # 扩展 n 网格：原 NS 的格点已在 E6_merged.jsonl 里，done 会剔掉。
        # 只列E6_EXT_NS。
        for m in E6_MULTS:
            for sf in E6_SURFS:
                for n in E6_EXT_NS:
                    for s in range(E6_SEEDS):
                        key = (m, sf, n, s)
                        if key not in d:
                            todo.append((key, cost_seq(n)))

    elif exp == "DPX":
        for dd in DEPTH_CROSS_DEPTHS:
            for cell in DEPTH_CROSS_CELLS:
                for n in DEPTH_CROSS_N:
                    for s in range(DEPTH_CROSS_SEEDS):
                        key = (cell, dd, n, s)
                        if key not in d:
                            todo.append((key, cost_depth(n, dd)))

    elif exp == "E8":
        for dd in E8_DS:
            for sf in E8_SURFS:
                for n in NS:
                    for s in range(E8_SEEDS):
                        key = (dd, sf, n, s)
                        if key not in d:
                            todo.append((key, cost_d(n, dd)))

    elif exp == "E1":
        # A2/A3/A4 单 run 约为 A1 的 1.2–1.5 倍；A4 在 d 维度上更快
        arch_pen = {"A1": 1.0, "A2": 1.4, "A3": 1.3, "A4": 0.6}
        for a in E1_ARCHS:
            for sf in E1_SURFS:
                for n in NS:
                    for s in range(E1_SEEDS):
                        key = (a, sf, n, s)
                        if key not in d:
                            todo.append((key, cost_seq(n) * arch_pen[a]))
    else:
        raise ValueError(exp)
    return todo


# ============================================================ LPT 装箱
def lpt_pack(todo, n_slices):
    """LPT：最贵的任务先放进当前最轻的片。保证各片总代价接近。"""
    items = sorted(todo, key=lambda x: -x[1])
    loads = [0.0] * n_slices
    buckets = [[] for _ in range(n_slices)]
    for key, c in items:
        i = loads.index(min(loads))
        buckets[i].append((key, c))
        loads[i] += c
    return buckets, loads


# ============================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", type=str, default=None)
    ap.add_argument("--n-slices", type=int, default=12,
                    help="全局默认片数；被 --plan 覆盖")
    ap.add_argument("--plan", type=str, default=None,
                    help="按实验指定片数，如 'E4=8,E6=14,E10=16'。"
                         "夜间建议按单片 <=1h 设定。")
    ap.add_argument("--out", type=str, default=OUT)
    args = ap.parse_args()

    plan = {}
    if args.plan:
        for part in args.plan.split(","):
            k, v = part.split("=")
            plan[k.strip()] = int(v)

    out = args.out if os.path.isabs(args.out) else os.path.join(HERE, args.out)
    os.makedirs(out, exist_ok=True)

    exps = ([args.experiment] if args.experiment
            else ["S2L", "E6X", "DPX"])
    done = _load_all_done()

    # ---- 拉丁方配平前提检查 ----
    # seed 数必须 >= 表面数，否则 slot 配平不完全，表面主效应与 slot 噪声纠缠。
    # 固定 slot 的方案已被 S1_FINAL.md 结论三证伪（初始化运气，非符号效应）。
    import latin
    print("=" * 78)
    print("拉丁方配平检查（seed 数须>= 表面数）")
    print("=" * 78)
    par = {
        "S2L": (S2_SURFS, S2_SEEDS),
        "E6X": (E6_SURFS, E6_SEEDS),
        # DPX 不用拉丁方（沿用 depth_scan 的 typed/en 设计，
        # 拉丁方只在多表面对比时才需要）。这里只报种子数。
        "DPX": (None, DEPTH_CROSS_SEEDS),
    }
    for e in exps:
        names, sd = par[e]
        if names is None:
            print(f"  {e:5s} 不用拉丁方  种子 {sd}")
            continue
        ok, msg = latin.check_parity(names, sd)
        print(f"  {e:5s} 表面 {len(names):2d}  种子 {sd:2d}  "
              f"{'OK' if ok else '不满足'}")
        if not ok:
            print(f"        -> {msg}")
    print()

    print("=" * 78)
    print("已完成格点（从 results/*.jsonl 扫出，绝不重跑）")
    print("=" * 78)
    for e in exps:
        print(f"  {e:5s} done = {len(done.get(e, set())):4d}")

    grand_todo = []
    for e in exps:
        todo = build_todo(e, done)
        if not todo:
            print(f"\n{e}: 全部已完成，跳过")
            continue
        n = min(plan.get(e, args.n_slices), len(todo))
        buckets, loads = lpt_pack(todo, n)
        maxload, minload = max(loads), min(loads)

        # --- 硬保险：done 数不得超过网格上限 ---
        # 防止"判别式写宽了-> 误判已完成 -> 真任务被漏跑"这类事故。
        # 曾实测：final.jsonl 的臂 K 记录也带 C_eff3，导致 E10 done=1440
        # （上限 300），若不拦会静默漏跑 240 个真任务。
        cap = GRID_CAP[e]
        if len(done.get(e, set())) > cap:
            raise SystemExit(
                f"ABORT {e}: done={len(done[e])} > 网格上限 {cap}\n"
                f"       说明判别式把别的实验数据当成了 {e} 的已完成结果。\n"
                f"       请检查 make_slices._load_all_done 的 arm 判别式。")
        if len(done.get(e, set())) > cap * 0.99:
            print(f"  [warn] {e}: done={len(done[e])} 已接近上限 {cap}，"
                  f"请确认判别式正确")

        print()
        print("=" * 78)
        print(f"{e}: {len(todo)} jobs -> {n} slices   "
              f"总代价 {sum(loads)/3600:.2f} h   "
              f"每片 {minload/3600:.2f}–{maxload/3600:.2f} h")
        print("=" * 78)

        # 写盘前先清掉本实验的旧切片。
        # 必要性：片数会随 done 增长而变少（实测 DPX 从 12 片降到 6 片），
        # 旧文件不会自己消失，于是 slices/ 里同时躺着 6 片新的（各 3 jobs）
        # 和 6 片旧的（各 18 jobs）。按glob 统计会得出 126 jobs 的假象，
        # 而真实待办只有 18。下游build_6packs 也会把旧片一起打包。
        import glob as _glob
        for _old in _glob.glob(os.path.join(out, f"{e}_slice*.json")):
            os.remove(_old)

        manifest = []
        for i, b in enumerate(buckets):
            # 片内按业务键排序，保证执行顺序可复现
            b.sort(key=lambda x: (str(x[0][0]), x[0][-2], x[0][-1]))
            name = f"{e}_slice{i:02d}"
            spec = [{"experiment": e, "args": list(k), "cost": round(c, 1)}
                    for k, c in b]
            with open(os.path.join(out, f"{name}.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(spec, fh, indent=1, ensure_ascii=False)
            manifest.append({
                "slice": name,
                "experiment": e,
                "n_jobs": len(b),
                "cost_seconds": round(sum(c for _k, c in b), 1),
                "est_hours": round(sum(c for _k, c in b) / 3600, 2),
                "runner": f"run_slice.py --spec slices/{name}.json",
            })
            print(f"  {name:14s} jobs={len(b):4d}  est={sum(c for _k,c in b)/3600:5.2f} h")

        # ---- 安全断言 ----
        allkeys = [k for b in buckets for k, _c in b]
        assert len(allkeys) == len(set(allkeys)), f"{e}: 片内重复"
        assert len(allkeys) == len(todo), f"{e}: 覆盖不全"
        assert not (set(allkeys) & done.get(e, set())), f"{e}: 与已完成重叠"
        grand_todo.append((e, allkeys))

        with open(os.path.join(out, f"{e}_MANIFEST.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"experiment": e, "n_slices": n,
                       "n_jobs": len(todo),
                       "total_cost_hours": round(sum(loads) / 3600, 2),
                       "slices": manifest}, fh, indent=2, ensure_ascii=False)

    print()
    print("=" * 78)
    total_jobs = sum(len(k) for _e, k in grand_todo)
    print(f"总待办{total_jobs} jobs")
    print(f"spec 目录: {out}")
    print("下一步：run_slice.py --spec slices/<name>.json --out <你的结果文件>")
    print("=" * 78)


if __name__ == "__main__":
    main()
