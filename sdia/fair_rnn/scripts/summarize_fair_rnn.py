#!/usr/bin/env python3
"""Fair-RNN summarizer. Denominator ALWAYS 8. Emits Path-style verdict for RNN outcomes."""
import json, math, os, glob
D = os.path.dirname(os.path.abspath(__file__)) + '/..'
SEEDS = [200,205,210,211,212,216,218,219]
THR = json.load(open(f'{D}/frozen/thresholds_fair_RNN.json'))
cfg_path = f'{D}/logs/science_config_id.txt'
sel = f'{D}/tune/selected_config.json'
if os.path.exists(cfg_path):
    CFG = open(cfg_path).read().strip()
elif os.path.exists(sel):
    CFG = json.load(open(sel))['selected_config_id']
else:
    CFG = 'UNKNOWN'

def wilson(k,n,z=1.96):
    if n==0: return [0,1]
    p=k/n; den=1+z*z/n; c=(p+z*z/(2*n))/den; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,c-h),min(1,c+h)]

def g(d,*ks):
    for k in ks:
        if d is None or k not in d: return None
        d=d[k]
    return d

rows=[]
for s in SEEDS:
    matches = sorted(glob.glob(f'{D}/logs/result_arm_G_RL_RNN_fair_seed{s}_*.json'))
    # prefer exact CFG
    f = f'{D}/logs/result_arm_G_RL_RNN_fair_seed{s}_{CFG}.json'
    if not os.path.exists(f):
        f = matches[0] if matches else None
    if not f:
        rows.append({'seed':s,'status':'MISSING'}); continue
    r=json.load(open(f)); e=r.get('eval',{}); ev=r.get('evo',{})
    rows.append({
        'seed':s,'status':'VOID' if r.get('seed_void') else ('PASS' if r.get('pass') else 'FAIL'),
        'config_id': r.get('config_id'),
        'ret': g(e,'return','mean'), 'mem_A': r.get('A_return'),
        'leak_mean': g(e,'C2_leak','mean'),
        'C2_decode': g(e,'C2','decode_acc'), 'C3_flip': g(e,'C3','flip_rate'),
        'C4_pass': g(e,'C4pp','pass'), 'C6_ret': g(e,'C6','return'),
        'fails':[k for k in ['C1','C2','C3','C4pp','C5','C6'] if isinstance(e.get(k),dict) and not e[k].get('pass',False)],
        'epochs': ev.get('epochs_ran'), 'train_max': ev.get('ret_curve_max', ev.get('best_ret_train')),
        'train_last': ev.get('ret_curve_last'), 'slope_lasthalf': ev.get('ret_curve_slope_lasthalf'),
        'wall_s': r.get('wall_s'), 'file': os.path.basename(f),
    })

k=sum(x['status']=='PASS' for x in rows)
v=sum(x['status']=='VOID' for x in rows)
m=sum(x['status']=='MISSING' for x in rows)
w=wilson(k,8)

# Path-style verdict (mutual exclusive)
if m>0:
    verdict_id='INCOMPLETE'
    verdict_zh='产物不全 — 补齐后重判；不定档'
elif not (json.load(open(f'{D}/frozen/thresholds_fair_RNN.json'))):  # never
    verdict_id='BUG'
elif k>=7:
    verdict_id='RNN_PASS_ge7'
    verdict_zh='公平调参后 RNN≥7/8 → 升「无先验档候选」；不自动改E2/S3；仍禁门控普遍必要'
elif k==0 and v==0:
    verdict_id='RNN_STILL_0'
    verdict_zh='公平调参后仍0/8 → 可写本玩具本预算失败；仍禁门控普遍必要/原理不可达'
else:
    verdict_id='RNN_MIXED'
    verdict_zh=f'混合 {k}/8（VOID={v}）→ 报告Wilson；不定档；S3 CLOSED'

out={
  'schema':'fair_rnn_summary_v1',
  'denominator':8,
  'science_config_id': CFG,
  'pass':k,'void':v,'missing':m,
  'wilson95':w,
  'per_seed':rows,
  'verdict_id':verdict_id,
  'verdict_zh':verdict_zh,
  'routing': THR['routing'],
  'S3':'CLOSED',
  'E2b':'DO_NOT_REOPEN',
  'forbid': THR['forbid'],
  'thresholds_sha256': open(f'{D}/frozen/thresholds_fair_RNN.sha256').read().split()[0],
}
os.makedirs(f'{D}/logs', exist_ok=True)
json.dump(out, open(f'{D}/logs/summary.json','w'), ensure_ascii=False, indent=2)
print(f"G_RL_RNN_fair {k}/8 VOID={v} MISSING={m} wilson95=[{w[0]:.3f},{w[1]:.3f}] cfg={CFG}")
print('verdict:', verdict_id, '|', verdict_zh)
print('S3=CLOSED | do not claim 门控普遍必要 | E2b untouched')
