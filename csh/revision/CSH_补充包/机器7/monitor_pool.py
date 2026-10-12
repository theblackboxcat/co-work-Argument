#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_pool.py — POOL 实验的前台短轮询监控。

设计约束（来自用户明确要求）：
    「服务器的清理和你是否在进程是强相关的。只要你不在对话它就会按时清楚。
      所以需要你一直监控在前台」

因此本脚本**主动在 RUN_CAP 秒后退出**，把控制权交还 agent，
避免前台命令被系统 auto-background 化后随 agent 空闲被清理。
agent 反复调用本脚本续接，形成真正的前台在场监控。
"""
import os
import sys
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
OUT = os.path.join(RES, "POOL.jsonl")
LOG = os.path.join(RES, "POOL.run.log")
DONE = os.path.join(RES, "_pool_done.flag")

TOTAL = 576
DELAY = 20
RUN_CAP = 90          # 单轮前台上限（秒），低于前台超时阈值


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(os.path.join(RES, "_pool_monitor.log"), "a") as fh:
        fh.write(line + "\n")


def proc_alive():
    """精确匹配 python 进程，避免探活shell 自身被 pgrep 误匹配。"""
    out = subprocess.run(
        ["ps", "-eo", "pid,comm,args"], capture_output=True, text=True).stdout
    n = 0
    for ln in out.splitlines():
        f = ln.split(None, 2)
        if len(f) < 3:
            continue
        if f[1].startswith("python") and "pool_orthogonal.py" in f[2] \
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


import json  # 放在函数外导入也可，但 stats 用到，需确保已加载


def main():
    if not os.path.exists(OUT):
        log("!! %s 不存在，实验未启动" % OUT)
        return
    t0 = time.time()
    while True:
        ok, err, bad = stats()
        alive = proc_alive()
        log("进度 %d/%d (%.1f%%)  worker=%d  error=%d 坏行=%d"
            % (ok, TOTAL, 100.0 * ok / TOTAL, alive, err, bad))
        if ok + err >= TOTAL:
            log("全部 %d 条已落盘，标记完成" % TOTAL)
            open(DONE, "w").write("done %d ok=%d err=%d\n" % (TOTAL, ok, err))
            break
        if not alive:
            log("!! worker 不在——尝试重启")
            subprocess.Popen([sys.executable, "pool_orthogonal.py",
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