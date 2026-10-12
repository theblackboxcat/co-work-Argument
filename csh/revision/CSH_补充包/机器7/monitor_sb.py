#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monitor_sb.py — SB（符号绑定判决）实验的前台短轮询监控。"""
import os, sys, json, time, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
OUT = os.path.join(RES, "SB2.jsonl")
LOG = os.path.join(RES, "SB2.run.log")
TOTAL, DELAY, RUN_CAP = 90, 20, 90
def log(m):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), m)
    print(line, flush=True)
    open(os.path.join(RES, "_sb_monitor.log"), "a").write(line + "\n")
def alive():
    o = subprocess.run(["ps","-eo","pid,comm,args"],capture_output=True,text=True).stdout
    return sum(1 for l in o.splitlines()
               if len(l.split(None,2))>2 and l.split(None,2)[1].startswith("python")
               and "symbol_binding.py" in l.split(None,2)[2] and "--workers" in l.split(None,2)[2])
def stats():
    ok=err=bad=0
    if os.path.exists(OUT):
        for ln in open(OUT):
            ln=ln.strip()
            if not ln: continue
            try: r=json.loads(ln)
            except Exception: bad+=1; continue
            if r.get("acc") is None or r["acc"]!=r["acc"] or "error" in r: err+=1
            else: ok+=1
    return ok,err,bad
def main():
    if not os.path.exists(OUT):
        log("!! %s 不存在" % OUT); return
    t0=time.time()
    while True:
        ok,err,bad=stats(); a=alive()
        log("SB %d/%d (%.1f%%)  worker=%d  error=%d 坏行=%d"
            % (ok,TOTAL,100.0*ok/TOTAL,a,err,bad))
        if ok+err>=TOTAL:
            log("SB 全部落盘，完成"); break
        if not a:
            log("!! worker 不在——重启")
            subprocess.Popen([sys.executable,"symbol_binding.py","--workers","4","--out",OUT],
                             cwd=HERE,start_new_session=True,
                             stdout=open(LOG,"a"),stderr=subprocess.STDOUT)
            time.sleep(10)
        if time.time()-t0>RUN_CAP:
            log("达到单轮前台上限，交还 agent 续接"); break
        time.sleep(DELAY)
if __name__=="__main__": main()
