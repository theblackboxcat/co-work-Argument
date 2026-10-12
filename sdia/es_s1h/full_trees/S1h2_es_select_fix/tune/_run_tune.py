
# -*- coding: utf-8 -*-
import os, sys, time, subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'

SEEDS = [100, 101, 102, 103]
LRS = [0.005, 0.01, 0.02, 0.05]
OUT = ROOT / 'tune' / 'stdout'
OUT.mkdir(parents=True, exist_ok=True)
# clear previous
for p in OUT.glob('*'):
    if p.name.startswith('_'):
        continue
    try:
        p.unlink()
    except Exception:
        pass
for p in (ROOT / 'tune').glob('result_arm_*.json'):
    p.unlink()
for p in (ROOT / 'tune').glob('hist_*.json'):
    p.unlink()

def run_one(seed, lr):
    tag = f'ES_main_s{seed}_lr{lr}'
    outp = OUT / f'{tag}.out'
    errp = OUT / f'{tag}.err'
    cmd = [sys.executable, 'run_arm.py', '--arm', 'ES_main', '--seed', str(seed), '--tune', '--lr', str(lr)]
    t0 = time.time()
    with open(outp, 'w', encoding='utf-8') as fo, open(errp, 'w', encoding='utf-8') as fe:
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=fo, stderr=fe, env=os.environ.copy())
    return tag, p.returncode, time.time() - t0

def main():
    log = OUT / '_launcher.log'
    jobs = [(s, lr) for s in SEEDS for lr in LRS]
    log.write_text(f'launch {len(jobs)} at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n', encoding='utf-8')
    results = []
    with ProcessPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(run_one, s, lr): (s, lr) for s, lr in jobs}
        for fut in as_completed(futs):
            tag, code, wall = fut.result()
            line = f'{tag} code={code} wall={wall:.0f}s\n'
            with log.open('a', encoding='utf-8') as f:
                f.write(line)
            print(line, flush=True)
            results.append((tag, code))
    nres = len(list((ROOT / 'tune').glob('result_arm_*.json')))
    fail = sum(1 for _, c in results if c != 0)
    summary = f'done fail={fail} nres={nres} at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
    with log.open('a', encoding='utf-8') as f:
        f.write(summary)
    (OUT / '_DONE').write_text('DONE\n' + summary, encoding='utf-8')
    print(summary, flush=True)
    return 0 if fail == 0 and nres == 16 else 1

if __name__ == '__main__':
    raise SystemExit(main())
