# -*- coding: utf-8 -*-
"""冒烟：P/M/S 三个模式按钮有没有真的透到模型。

**要验的不是"按钮点了有反应"，是"三种模式给出的是三种不同的东西"。**
所以这里比较三次调用的 system prompt —— 它必须真的不同，而不是同一个提示词
换了张脸。之前踩过一次同源的坑：注意力机制的动作集和策略正文不是同一套，
STUCK 和 PLANNING 输出一模一样（§四.13）。

用法：
  python v3/smoke_mode.py            直接调 policy，看三份 system prompt 的差异
  python v3/smoke_mode.py --live     再打一次真实接口，看输出是否随之改变
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy  # noqa: E402

TEXT = '所以我只是打算出门去走走，在这样近乎凝滞的冬日。路上没什么人，风把塑料袋吹到半空，又落下来。'


def main():
    print('=== 1) system prompt 是否真的不同 ===')
    prompts = {}
    for m in ('P', 'M', 'S', None):
        s, meta = policy.build_system(TEXT, mode=m)
        prompts[m] = s
        print('  mode=%-5s → 判定=%s  来源=%s  prompt %d 字'
              % (str(m), meta['mode'], '作者' if m else '分类器', len(s)))
    ps, ss = prompts['P'], prompts['S']
    print('\n  P 与 S 的 prompt 相同吗：%s' % ('**相同——按钮没接上**' if ps == ss else '不同 ✓'))
    # 差异必须落在"读法"那一段，不能只是模式名不同
    import difflib
    diff = [l for l in difflib.unified_diff(ps.split('\n'), ss.split('\n'), lineterm='')
            if l.strip().startswith(('+', '-')) and not l.strip().startswith(('++', '--'))]
    print('  逐行差异 %d 行，其中不重复的 %d 行' % (len(diff), len(set(diff))))
    for l in list(dict.fromkeys(diff))[:6]:
        print('    %s' % l[:78])

    print('\n=== 2) 分类器猜的模式 vs 作者选的是否可能冲突 ===')
    _, auto = policy.build_system(TEXT, mode=None)
    print('  同一段，分类器猜 %s（score %.3f）' % (auto['mode'], auto['score']))
    print('  → 所以按钮的意义就是：她选什么就是什么，分类器不再有否决权。')

    if '--live' in sys.argv:
        import json
        import urllib.request
        print('\n=== 3) 真实接口三次调用 ===')
        for m in ('P', 'M', 'S'):
            body = json.dumps({'text': TEXT, 'prev': '', 'section': '§1',
                               'mode': m, 'probe': 1}).encode('utf-8')
            req = urllib.request.Request('http://127.0.0.1:8790/api/cowrite', data=body,
                                         headers={'Content-Type': 'application/json'})
            try:
                d = json.loads(urllib.request.urlopen(req, timeout=180).read().decode('utf-8'))
            except Exception as e:
                print('  [%s] 请求失败：%s' % (m, e))
                continue
            c = (d.get('cards') or [{}])[0]
            print('\n  [%s] card.layer=%s title=%s' % (m, c.get('layer'), c.get('title')))
            print('      ' + (c.get('body') or '').replace('\n', '\n      ')[:400])


if __name__ == '__main__':
    main()
