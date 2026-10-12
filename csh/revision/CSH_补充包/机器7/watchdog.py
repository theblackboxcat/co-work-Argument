"""看门狗：监控 run_remaining.py 进程，若其消失且任务未完成则自动 detached 重启。
- 与 run_remaining 进程生命周期解耦（start_new_session），任一层被清另一层可独立存活。
- 完成信号：results/_all_done.flag（由新版 run_remaining 末尾写入）。
- 兜底：agent 侧会周期性探活，watchdog 自身被清时由 agent 手动重启 run_remaining。
"""
import subprocess, os, sys, time

HERE = "/workspace/机器7"
os.chdir(HERE)
PY = sys.executable
DONE = "results/_all_done.flag"
LOG = "results/_watchdog.log"


def log(msg):
    ts = time.strftime("%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")


def proc_alive():
    r = subprocess.run(["pgrep", "-f", "run_remaining.py"],
                       capture_output=True, text=True)
    return r.returncode == 0


def all_done():
    return os.path.exists(DONE)


log("watchdog start")
while True:
    if all_done():
        log("ALL DONE detected -> watchdog exit")
        break
    if not proc_alive():
        log("run_remaining.py 不在 -> detached 重启")
        with open("results/_driver_run.log", "ab") as out:
            subprocess.Popen([PY, "run_remaining.py"],
                             stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True)
        time.sleep(8)  # 给新进程启动时间，避免重复拉起
    time.sleep(20)
