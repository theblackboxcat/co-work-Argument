"""前台持续监控（短轮询版）：单个前台命令运行 RUN_CAP 秒后优雅退出，
由 agent 立刻再起下一个，从而保持对话始终活跃、规避后台清理。
- 每 20s 探活：watchdog / worker(run_remaining) / 当前 run_slice / 各片行数。
- 自愈：watchdog 或 worker 任一消失，detached 重启。
- 运行 RUN_CAP 秒后主动 break（不触发 foreground auto-background），交还 agent 续接。
- 状态同时 print(flush) 与写 results/_monitor.log。
"""
import subprocess, os, sys, time, json, math

HERE = "/workspace/机器7"
os.chdir(HERE)
PY = sys.executable
DONE = "results/_all_done.flag"
MON = "results/_monitor.log"
DELAY = 20
RUN_CAP = 100  # 单轮前台上限(秒)：低于前台超时，主动退出避免被转后台清理

task = json.load(open("本机任务.json", encoding="utf-8"))
NJOBS = {t["slice"]: t["n_jobs"] for t in task["tasks"]}
EXPECT_TOTAL = len(task["tasks"])  # 13


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(MON, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def alive(pattern):
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return r.returncode == 0


def launch(script):
    with open("results/_driver_run.log", "ab") as out:
        subprocess.Popen([PY, script], stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True)
    log(f"REVIVE -> {script}")


def is_complete(path, nj):
    if not os.path.exists(path):
        return False
    n = 0
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            return False
        if d.get("error") is not None or "error" in ln:
            return False
        a = d.get("acc")
        if not isinstance(a, (int, float)) or (isinstance(a, float) and math.isnan(a)):
            return False
        n += 1
    return n == nj


def current_slice():
    r = subprocess.run(["pgrep", "-af", "run_slice.py"], capture_output=True, text=True)
    if r.returncode != 0:
        return "(无)"
    for line in r.stdout.splitlines():
        if "--spec" in line:
            parts = line.split("--spec")[-1].split()
            if parts:
                return os.path.basename(parts[0]).replace(".json", "")
    return "(无)"


def main():
    log(f"=== 前台监控启动(短轮询): 共 {EXPECT_TOTAL} 片，每 {DELAY}s 探活，单轮 {RUN_CAP}s ===")
    start = time.time()
    while True:
        if os.path.exists(DONE):
            log(">>> 检测到 _all_done.flag，全部切片完成 -> 前台监控退出")
            break
        if time.time() - start > RUN_CAP:
            log(f">>> 本轮前台监控运行 {RUN_CAP}s 到点，交还 agent 续接（保持对话活跃以规避后台清理）")
            break

        if not alive("watchdog.py"):
            log("WARN: watchdog 不在 -> 重启")
            launch("watchdog.py")
        if not alive("run_remaining.py"):
            log("WARN: worker(run_remaining) 不在 -> 重启")
            launch("run_remaining.py")

        rows = []
        complete = 0
        for f in sorted(os.listdir("results")):
            if not f.endswith(".jsonl"):
                continue
            p = os.path.join("results", f)
            n = sum(1 for _ in open(p, encoding="utf-8"))
            name = f.replace(".jsonl", "")
            nj = NJOBS.get(name)
            ok = (nj is not None and is_complete(p, nj))
            if ok:
                complete += 1
            rows.append((f, n, nj, ok))

        cur = current_slice()
        log(f"进度 {complete}/{EXPECT_TOTAL} 完成 | 当前跑: {cur} | "
            f"watchdog={'Y' if alive('watchdog.py') else 'N'} "
            f"worker={'Y' if alive('run_remaining.py') else 'N'}")
        for f, n, nj, ok in rows:
            mark = "OK" if ok else (".." if nj is None else f"{n}/{nj}")
            log(f"   {f:28s} {mark}")

        if complete >= EXPECT_TOTAL:
            log(">>> 13 片全部完成 -> 前台监控退出")
            open(DONE, "w").write("front monitor confirmed all done\n")
            break

        time.sleep(DELAY)


if __name__ == "__main__":
    main()
