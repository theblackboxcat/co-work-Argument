import itertools
from substrate2 import c_eff
TYPED=[(0,1),(0,2),(1,0),(1,2),(2,0),(2,1)]
UNTYPED=[(0,1),(0,0),(0,0),(0,0),(2,0),(1,2)]
NR=6
def m_of(a):
    n=len(a); m=[[0]*n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if a[i][1]==a[j][0]: m[i][j]=1
    return m
def ov(a): return sum(1 for x,y in zip(a,TYPED) if x==y)
seen={}
sigs=list(itertools.product(range(3),range(3)))
for a in itertools.product(sigs,repeat=NR):
    if {x[0] for x in a}!={0,1,2} or {x[1] for x in a}!={0,1,2}: continue
    m=m_of(a)
    if any(sum(r)==0 for r in m): continue
    key=(ov(a), sum(sum(r) for r in m)/NR)
    if key not in seen: seen[key]=list(a)
print('structurally valid (overlap, branching) cells:',len(seen))
print()
print(f'{"ovl":>4}{"branch":>8}{"C(3)":>7}{"C_eff":>7}  assign')
rowsout=[]
for (o,b) in sorted(seen):
    a=seen[(o,b)]
    c3,eff=c_eff(a,3)
    mk=''
    if a==TYPED: mk='  <- typed (baseline)'
    if a==UNTYPED: mk='  <- untyped (current other substrate)'
    print(f'{o:4d}{b:8.2f}{c3:7d}{eff:7d}  {a}{mk}')
    rowsout.append((o,b,a,c3,eff))
import json
json.dump([[o,b,a,c3,eff] for (o,b),a,_,_ in
           [((o,b),seen[(o,b)],0,0) for o,b in sorted(seen)]],
          open('results/overlap_cells.json','w'))
