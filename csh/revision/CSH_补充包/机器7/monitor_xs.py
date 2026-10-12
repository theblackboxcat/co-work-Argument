#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monitor_xs.py — XS（跨表面迁移）实验的前台短轮询监控。

与 monitor_pool.py 同构，遵守同一条约束：单轮 RUN_CAP 秒后主动退出，
交还 agent 续接，避免前台命令被 auto-background 后随 agent 空闲被清理。
"""
import os
import sys
import json
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
OUT = os.path.join(RES, "XS.jsonl")
LOG = os.path.join(RES, "XS.run.log")

TOTAL = 252
DELAY = 20
RUN_CAP = 90


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(os.path.join(RES, "_xs_monitor.log"), "a") as fh:
        fh.write(line + "\n")


def proc_alive():
    out = subprocess.run(["ps", "-eo", "pid,comm,args"],
                         capture_output=True, text=True).stdout
    n = 0
    for ln in out.splitlines():
        f = ln.split(None, 2)
        if len(f) < 3:
            continue
        if f[1].startswith("python") and "cross_surface.py" in f[2] \
           and "--workers" in f[2]:
            n += 1
    return n


def stats():
    ok = err = bad = 0
    if os.path.exists(OUT):
        for ln in open(OUT):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                bad += 1
                continue
            if r.get("acc") is None or r["acc"] != r["acc"] or "error" in r:
                err += 1
            else:
                ok += 1
    return ok, err, bad


def main():
    if not os.path.exists(OUT):
        log("!! %s 不存在" % OUT)
        return
    t0 = time.time()
    while True:
        ok, err, bad = stats()
        alive = proc_alive()
        log("XS 进度 %d/%d (%.1f%%)  worker=%d  error=%d 坏行=%d"
            % (ok, TOTAL, 100.0 * ok / TOTAL, alive, err, bad))
        if ok + err >= TOTAL:
            log("全部落盘，XS 完成")
            break
        if not alive:
            log("!! worker 不在——重启")
            subprocess.Popen([sys.executable, "cross_surface.py",
                              "--workers", "4", "--out", OUT],
                             cwd=HERE, start_new_session=True,
                             stdout=open(LOG, "a"), stderr=subprocess.STDOUT)
            time.sleep(10)
        if time.time() - t0 > RUN_CAP:
            log("达到单轮前台上限，交还 agent 续接")
            break
        time.sleep(DELAY)


if __name__ == "__main__":
    main()