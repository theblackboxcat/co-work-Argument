import json, numpy as np, collections, sys
sys.path.insert(0,".")
import analysis as A
rows=[json.loads(l) for l in open("results/surface_fix2.jsonl",encoding="utf-8") if l.strip()]
NAMES=["zh","en","lisp","math","code","alien"]
ns=sorted({r["n_train"] for r in rows}); seeds=sorted({r["seed"] for r in rows})
def boot(v,n=4000,seed=0):
    rng=np.random.default_rng(seed); bs=[np.mean(rng.choice(v,len(v),replace=True)) for _ in range(n)]
    return float(np.percentile(bs,2.5)),float(np.percentile(bs,97.5))
cell={(r["surface"],r["n_train"],r["seed"]):r["acc"] for r in rows}

print("="*74)
print("MEAN ACCURACY by surface x n   (Latin-square balanced id assignment)")
print("="*74)
print(f"{'surface':>8}"+"".join(f"{n:>10}" for n in ns))
for s in NAMES:
    line=f"{s:>8}"
    for n in ns:
        v=[cell[(s,n,sd)] for sd in seeds if (s,n,sd) in cell]
        line+=f"{np.mean(v):10.4f}"
    print(line)

print()
print("="*74)
print("VARIANCE DECOMPOSITION  (slot fully balanced by Latin square)")
print("="*74)
for N in ns:
    sub=[r for r in rows if r["n_train"]==N]
    surf=collections.defaultdict(list); slot=collections.defaultdict(list)
    for r in sub:
        surf[r["surface"]].append(r["acc"]); slot[r["block_slot"]].append(r["acc"])
    grand=np.mean([r["acc"] for r in sub])
    tot=np.mean([(r["acc"]-grand)**2 for r in sub])
    ss_s=np.mean([(np.mean(v)-grand)**2 for v in surf.values()])
    ss_l=np.mean([(np.mean(v)-grand)**2 for v in slot.values()])
    print(f"  n={N:>5}  total={tot:.5f}  SURFACE={ss_s:.5f} ({100*ss_s/tot:4.1f}%)"
          f"  SLOT={ss_l:.5f} ({100*ss_l/tot:4.1f}%)")

print()
print("="*74)
print("EMERGENCE THRESHOLDS  (same estimator as original S1)")
print("="*74)
thr={}
for s in NAMES:
    vals=[]
    for sd in seeds:
        d={n:cell[(s,n,sd)] for n in ns if (s,n,sd) in cell}
        if len(d)<len(ns): continue
        t=A.threshold(ns,[d[n] for n in ns],0.60)
        if t is not None and not np.isnan(t): vals.append(t)
    thr[s]=vals
    l,h=boot(vals)
    print(f"  {s:>8} thr={np.mean(vals):7.0f}  CI[{l:6.0f},{h:6.0f}]  crossed {len(vals)}/6")
good=[np.mean(v) for v in thr.values() if v]
logs=np.log(good); gm=float(np.exp(logs.mean()))
print()
print(f"  geometric mean : {gm:,.0f}")
print(f"  spread         : {max(good)-min(good):,.0f}  ({100*(max(good)-min(good))/gm:.0f}% of mean)")
print(f"  CV(log)        : {logs.std(ddof=1)/logs.mean():.4f}   (original S1 criterion: <0.15)")

print()
print("="*74)
print("PAIRED vs GRAND MEAN  (slot-balanced, per surface)")
print("="*74)
allv=[r["acc"] for r in rows]
grand=np.mean(allv)
for s in NAMES:
    d=[cell[(s,n,sd)]-np.mean([r["acc"] for r in rows if r["n_train"]==n]) for n in ns for sd in seeds if (s,n,sd) in cell]
    l,h=boot(d)
    print(f"  {s:>8} {np.mean(d):+.4f}  CI[{l:+.4f},{h:+.4f}]  {'SIGNIFICANT' if (l>0 or h<0) else 'n.s.'}")
