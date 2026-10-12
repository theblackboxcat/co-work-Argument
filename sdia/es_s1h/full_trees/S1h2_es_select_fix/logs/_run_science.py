
# -*- coding: utf-8 -*-
import os, sys, time, subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
for k,v in [('OMP_NUM_THREADS','1'),('OPENBLAS_NUM_THREADS','1'),('MKL_NUM_THREADS','1'),('PYTHONIOENCODING','utf-8')]:
    os.environ[k] = v

SEEDS = [200, 205, 210, 211, 212, 216, 218, 219]
ARMS = ['ES_easy', 'ES_main', 'ES_easy_legacy']
OUT = ROOT / 'logs' / 'stdout'
OUT.mkdir(parents=True, exist_ok=True)

def run_one(arm, seed):
    tag = f'{arm}_s{seed}'
    outp = OUT / f'{tag}.out'
    errp = OUT / f'{tag}.err'
    cmd = [sys.executable, 'run_arm.py', '--arm', arm, '--seed', str(seed)]
    t0 = time.time()
    with open(outp, 'w', encoding='utf-8') as fo, open(errp, 'w', encoding='utf-8') as fe:
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=fo, stderr=fe, env=os.environ.copy())
    return tag, p.returncode, time.time() - t0

def main():
    log = OUT / '_launcher.log'
    jobs = [(a, s) for a in ARMS for s in SEEDS]
    log.write_text(f'launch {len(jobs)} at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n', encoding='utf-8')
    results = []
    with ProcessPoolExecutor(max_workers=24) as ex:
        futs = {ex.submit(run_one, a, s): (a, s) for a, s in jobs}
        for fut in as_completed(futs):
            tag, code, wall = fut.result()
            line = f'{tag} code={code} wall={wall:.0f}s\n'
            with log.open('a', encoding='utf-8') as f:
                f.write(line)
            print(line, flush=True)
            results.append((tag, code))
    nres = len(list((ROOT / 'logs').glob('result_arm_*.json')))
    fail = sum(1 for _, c in results if c != 0)
    summary = f'done fail={fail} nres={nres} at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
    with log.open('a', encoding='utf-8') as f:
        f.write(summary)
    (OUT / '_DONE').write_text('DONE\n' + summary, encoding='utf-8')
    print(summary, flush=True)
    return 0 if fail == 0 and nres >= 24 else 1

if __name__ == '__main__':
    raise SystemExit(main())
