#!/usr/bin/env python3
"""S1g summarizer: per-arm pass/VOID/Wilson, per-seed table, RNN diagnostics. Denominator ALWAYS 8."""
import json, glob, math, os, sys
D = os.path.dirname(os.path.abspath(__file__)) + '/..'
SEEDS = [200,205,210,211,212,216,218,219]
ARMS = ['A','C','G_RL_GRU','G_RL_RNN','ES_GRU']
def wilson(k,n,z=1.96):
    if n==0: return [0,1]
    p=k/n; den=1+z*z/n; c=(p+z*z/(2*n))/den; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,c-h),min(1,c+h)]
def g(d,*ks):
    for k in ks:
        if d is None or k not in d: return None
        d=d[k]
    return d
out={'schema':'s1g_summary_v2','denominator':8,'arms':{}}
th=json.load(open(f'{D}/frozen/thresholds_S1g.json'))
for arm in ARMS:
    rows=[]
    for s in SEEDS:
        f=f'{D}/logs/result_arm_{arm}_seed{s}.json'
        if not os.path.exists(f): rows.append({'seed':s,'status':'MISSING'}); continue
        r=json.load(open(f)); e=r['eval']; ev=r.get('evo',{})
        rows.append({'seed':s,'status':'VOID' if r.get('seed_void') else ('PASS' if r['pass'] else 'FAIL'),
            'ret':g(e,'return','mean'),'mem_A':r['A_return'],'leak_mean':g(e,'C2_leak','mean'),
            'C2_decode':g(e,'C2','decode_acc'),'C3_flip':g(e,'C3','flip_rate'),
            'C4_drop_sparse':g(e,'C4pp','drop_sparse'),'C6_ret':g(e,'C6','return'),
            'fails':[k for k in ['C1','C2','C3','C4pp','C5','C6'] if not e[k]['pass']],
            'epochs':ev.get('epochs_ran'),'train_max':ev.get('ret_curve_max',ev.get('best_fit_train')),
            'train_last':ev.get('ret_curve_last'),'train_mean':ev.get('ret_curve_mean'),
            'slope_lasthalf':ev.get('ret_curve_slope_lasthalf'),'wall_s':r.get('wall_s')})
    k=sum(x['status']=='PASS' for x in rows); v=sum(x['status']=='VOID' for x in rows); m=sum(x['status']=='MISSING' for x in rows)
    out['arms'][arm]={'pass':k,'n':8,'void':v,'missing':m,'wilson95':wilson(k,8),'per_seed':rows}
# ES hist curve diagnostics
for s in SEEDS:
    f=f'{D}/logs/hist_ES_GRU_seed{s}.json'
    if os.path.exists(f):
        h=json.load(open(f)); m=[x['mean'] for x in h]
        for row in out['arms']['ES_GRU']['per_seed']:
            if row['seed']==s: row['pop_mean_first50']=sum(m[:50])/50; row['pop_mean_last50']=sum(m[-50:])/50
# RNN hist diagnostics
for s in SEEDS:
    f=f'{D}/logs/hist_G_RL_RNN_seed{s}.json'
    if os.path.exists(f):
        h=json.load(open(f)); rets=[x['ret'] for x in h]; ls=[x['loss'] for x in h]
        for row in out['arms']['G_RL_RNN']['per_seed']:
            if row['seed']==s: row['ret_curve']=[round(x,3) for x in rets]; row['loss_first']=ls[0]; row['loss_last']=ls[-1]
A=out['arms']
gru=A['G_RL_GRU']['pass']>=7; rnn=A['G_RL_RNN']['pass']>=7; cok=A['C']['pass']>=7
if not cok: route='实验完整性VOID（C败）'
elif gru and rnn: route='L2-self 无先验档'
elif gru: route='通用门控架构档'
elif rnn: route='（未预写：仅RNN过）'
else: route='回头查 leak / 测量'
out['routing_applied']=route; out['E2']='STOP_not_authorized'
out['thresholds_sha256']=open(f'{D}/frozen/thresholds_S1g.sha256').read().split()[0]
json.dump(out,open(f'{D}/logs/summary.json','w'),ensure_ascii=False,indent=1)
for arm in ARMS:
    a=A[arm]; print(f"{arm:9s} {a['pass']}/8 VOID={a['void']} MISSING={a['missing']} wilson95=[{a['wilson95'][0]:.3f},{a['wilson95'][1]:.3f}]")
print('routing:',route)
