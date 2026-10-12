# -*- coding: utf-8 -*-
"""冒烟：自由对话通道（kind='free'）。

和 smoke_rewrite.py 的区别：那一批是**预设按钮**（措辞我写死在 REWRITE 里），
这一批是**她自己说的话**——措辞来自调用方，模型照做。

用法：
  python v3/smoke_say.py                      跑内置的三句
  python v3/smoke_say.py "你刚才那句凭什么这么说"   只跑指定的（可多句）
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

WORDS = [
    '你凭什么说"怕惊动了什么"？我原文里根本没有这个。',
    '别分析我。就告诉我这句 reads 起来是快还是慢。',
    '帮我看看第二句是不是多余的。只说是或不是，然后给一句理由。',
]


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode('utf-8'))


for w in (sys.argv[1:] or WORDS):
    try:
        r = post({'text': TEXT, 'prev': PREV, 'section': '§1', 'probe': 1,
                  'kind': 'free', 'free': w, 'prev_output': PREV_OUT})
    except Exception as e:
        print('请求失败: %s' % e)
        continue
    print('\n' + '=' * 60)
    print('她说：%s' % w)
    if r.get('error'):
        print('  ERROR:', r['error'])
        continue
    for c in r.get('cards') or []:
        print('  ' + (c.get('body') or '').replace('\n', '\n  '))
