import json, subprocess, os, sys, time, math

HERE = "/workspace/机器7"
os.chdir(HERE)
PY = sys.executable
DONE = "results/_all_done.flag"

task = json.load(open("本机任务.json", encoding="utf-8"))
# DPX_slice06 已完成，跳过；其余 12 片按原顺序
specs = [t for t in task["tasks"] if t["experiment"] != "DPX"]


def is_complete(out, nj):
    """整片是否已完成：行数==n_jobs 且无 error/坏行/NaN，acc 全在[0,1]。"""
    if not os.path.exists(out):
        return False
    n = 0
    accs = []
    for ln in open(out, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            return False  # 坏行/截断行 → 不完整
        if d.get("error") is not None or "error" in ln:
            return False
        a = d.get("acc")
        if not isinstance(a, (int, float)) or (isinstance(a, float) and math.isnan(a)):
            return False
        accs.append(a)
        n += 1
    if n != nj:
        return False
    return 0 <= min(accs) <= max(accs) <= 1


log_path = "results/_driver_log.txt"
open(log_path, "w").close()

summary = []
for t in specs:
    exp = t["experiment"]
    name = t["slice"]
    spec = t["spec"]
    out = f"results/{name}.jsonl"
    nj = t["n_jobs"]

    # 续跑策略：已完成则跳过；不完整/含坏行则删后重跑（避免残缺行累积）
    if is_complete(out, nj):
        print(f"[{name}] 已完成，跳过", flush=True)
    else:
        if os.path.exists(out):
            os.remove(out)
        cmd = [PY, "run_slice.py", "--spec", spec, "--out", out, "--workers", "4"]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        rc = r.returncode

    nlines = sum(1 for _ in open(out, encoding="utf-8")) if os.path.exists(out) else 0
    errs = 0
    accs = []
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                if '"error"' in ln:
                    errs += 1
                try:
                    d = json.loads(ln)
                    a = d.get("acc")
                    if isinstance(a, (int, float)) and not (isinstance(a, float) and math.isnan(a)):
                        accs.append(a)
                except Exception:
                    pass
    amin = min(accs) if accs else float("nan")
    amax = max(accs) if accs else float("nan")
    dur = time.time() - t0 if "t0" in dir() else 0.0
    size = os.path.getsize(out) if os.path.exists(out) else 0
    ok = (nlines == nj) and (errs == 0) and (len(accs) == nj) and (0 <= amin <= amax <= 1)
    summary.append((name, exp, nj, round(dur / 60, 1), errs, round(amin, 3), round(amax, 3), size, ok, rc))
    with open(log_path, "a", encoding="utf-8") as L:
        L.write(f"{name}\t{exp}\tjobs={nj}\tlines={nlines}\terr={errs}\t"
                f"acc=[{amin:.3f},{amax:.3f}]\tsize={size}\tok={ok}\trc={rc}\t{dur/60:.1f}m\n")
    print(f"[{name}] exp={exp} jobs={nj} lines={nlines} err={errs} "
          f"acc=[{amin:.3f},{amax:.3f}] ok={ok} {dur/60:.1f}m", flush=True)

open(DONE, "w").write("all slices done\n")
print("\n===== ALL SLICES DONE =====")
for s in summary:
    print(f"{s[0]}\t{s[1]}\tjobs={s[2]}\t{s[3]}m\terr={s[4]}\tacc=[{s[5]},{s[6]}]\tsize={s[7]}\tok={s[8]}\trc={s[9]}")
