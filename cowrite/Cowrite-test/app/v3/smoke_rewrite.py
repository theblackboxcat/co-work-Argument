# -*- coding: utf-8 -*-
"""冒烟：把重写按钮各打一次，看模型是否按指令改，且没触发抄原文护栏。

用法：先起服务（python server.py，端口看它的启动横幅），再
    python v3/smoke_rewrite.py            四个都打
    python v3/smoke_rewrite.py too_light  只打指定的（可多个）

改完 policy.REWRITE 里任何一条措辞，都应该跑一遍——
这一条线上三次翻车全是在这里跑出来的，不是靠读代码看出来的。
注意：改 REWRITE 必须重启服务，它被 import 进进程后不再重读。
"""
import json
import sys
import urllib.request

URL = 'http://127.0.0.1:8790/api/rewrite'
TEXT = '所以我只是打算出门去走走，在这样近乎凝滞的冬日。路上没什么人，风把塑料袋吹到半空，又落下来。'
PREV = '她把杯子洗了三遍，还是觉得有味道。'
PREV_OUT = ('我在这里读到一种克制的难过——她没有说难过，她说的是「只是」，'
            '这个「只是」把她往外走的动作压得很轻，像是怕惊动了什么。'
            '整段的气氛是往里收的，敬意多于悲伤。')

KINDS = sys.argv[1:] or ['too_heavy', 'too_light', 'no_novelty', 'give_ideas']


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode('utf-8'))


for k in KINDS:
    try:
        # probe=1：埋点里记成 v3-rewrite-probe，不混进她真实点击的分布
        r = post({'text': TEXT, 'prev': PREV, 'section': '§1', 'probe': 1,
                  'kind': k, 'prev_output': PREV_OUT})
    except Exception as e:
        print('[%s] 请求失败: %s' % (k, e))
        continue
    print('\n' + '=' * 60)
    print('[%s] %s  %sms' % (k, r.get('label'), r.get('elapsed_ms')))
    if r.get('error'):
        print('  ERROR:', r['error'])
        continue
    for c in r.get('cards') or []:
        print('  --- %s' % (c.get('title') or ''))
        print('  ' + (c.get('body') or '').replace('\n', '\n  '))
