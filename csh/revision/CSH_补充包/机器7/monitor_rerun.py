"""monitor_rerun.py — 前台短轮询监控 rerun_shuffle.py。RUN_CAP 后自动退出。"""
import subprocess
import time

TOTAL = 18
DELAY = 20
RUN_CAP = 90

LOG = "results/SB2_rerun_shuffle.log"
OUT = "results/_rerun_shuffle.out"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True,
                          text=True).stdout


def alive():
    out = sh("ps -eo pid,comm,args")
    hits = [l for l in out.splitlines()
            if "python" in l.split()[1] if len(l.split()) > 1]
    return [l for l in hits if "rerun_shuffle.py" in l]


def done():
    try:
        t = open(LOG, encoding="utf-8").read()
    except OSError:
        return 0
    return t.count("acc=")


r = 0
while r < RUN_CAP:
    n = done()
    a = alive()
    stamp = time.strftime("%H:%M:%S")
    print("[%s] shuffle %d/%d (%.1f%%)  worker=%d%s"
          % (stamp, n, TOTAL, 100.0 * n / TOTAL, len(a),
             "" if a else "  [进程已退出]"), flush=True)
    if n >= TOTAL:
        print("[%s] shuffle 全部落盘" % stamp, flush=True)
        break
    if not a:
        # 进程退出但未跑完 —— 可能是 worker 掉线，看日志尾部再决定
        tail = sh("tail -n 3 %s" % OUT).strip().splitlines()
        print("   进程不在，日志尾部:", tail[-1] if tail else "(空)", flush=True)
        break
    r += 1
    time.sleep(DELAY)