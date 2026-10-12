# -*- coding: utf-8 -*-
"""冒烟：全文剖面有没有真的进到每一次局部伴写的 prompt 里。

**为什么不能只看"剖面生成成功"就算过**：
生成是一件事，注进去是另一件事。这一条线上栽过同形状的跟头——
注意力机制的动作集和策略正文不是同一套，结果两个状态输出一模一样（§四.13）；
重写按钮在护栏重试时漏传 mode，结果"选了 S 却返回 M"（v3.6）。
**所以凡是"某样东西应该影响输出"，都要去抓它实际发出去的那一份，不能靠读代码。**

做法：把 server 的 urlopen 换掉，截住它实际要发出去的 payload，再断言。
不联网、不花钱、结果是确定性的。

用法：  python v3/smoke_profile.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402

DOC = ('她把杯子洗了三遍，还是觉得有味道。\n\n'
       '所以我只是打算出门去走走，在这样近乎凝滞的冬日。\n\n'
       '路上没什么人，风把塑料袋吹到半空，又落下来。')
FAKE_PROFILE = ('1. 调性：滞、冷。§2「凝滞」\n'
                '2. 反复出现：「洗了三遍」与「又落下来」——两处都是做了又没结果。\n'
                '3. 已建立的关系：§1 的重复与 §3 的落回构成呼应。\n'
                '4. 写法：第一人称，短句，无对话。')


class Capture:
    """假的 urlopen：把要发出去的请求截下来，回一个空内容。"""

    def __init__(self):
        self.payload = None

    def __call__(self, req, timeout=None):
        try:
            self.payload = json.loads(req.data.decode('utf-8'))
        except Exception:
            self.payload = None
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        fmt = server.load_config().get('api', 'openai-completions')
        if fmt == 'anthropic-messages':
            return json.dumps({'content': [{'type': 'text', 'text': '[M] 好的'}]}).encode()
        return json.dumps({'choices': [{'message': {'content': '[M] 好的'}}]}).encode()


def sent_user_text(profile_on):
    server.set_doc('测试文档', DOC)
    if profile_on:
        # ⚠️ `rev` 必须给，且要**对得上当前正文**——§49 之后剖面是绑内容版本的，
        #    对不上就会被**降级**（换掉护栏措辞）。这个夹具原来没有 rev，
        #    于是"打开剖面"那一趟拿到的是降级版，护栏断言就红了。
        #    又一次"夹具带着旧假设"：改判据它才现形。
        server.PROFILE.update({'status': 'ready', 'text': FAKE_PROFILE, 'built_at': 1.0,
                               'rev': server.DOC_STORE.get('rev') or 0})
    else:
        server.PROFILE.update({'status': 'none', 'text': '', 'built_at': 0, 'rev': 0})
    cap = Capture()
    orig = server.urllib.request.urlopen
    server.urllib.request.urlopen = cap
    try:
        server.call_model(server.load_config(), server.load_skill(),
                          '路上没什么人，风把塑料袋吹到半空，又落下来。',
                          '§3', '（无预置语料）', mode='P')
    finally:
        server.urllib.request.urlopen = orig
    p = cap.payload or {}
    if 'system' in p:                       # anthropic 格式：system 单独一层
        return p.get('system', '') + '\n' + p['messages'][0]['content']
    return '\n'.join(m.get('content', '') for m in p.get('messages', []))


def main():
    off = sent_user_text(False)
    on = sent_user_text(True)
    ok = True
    print('=== 关掉剖面 ===')
    print('  prompt %d 字，含「全文剖面」：%s' % (len(off), '【全文剖面' in off))
    if '【全文剖面' in off:
        print('  ! 不该出现却出现了')
        ok = False
    print('\n=== 打开剖面 ===')
    print('  prompt %d 字，含「全文剖面」：%s' % (len(on), '【全文剖面' in on))
    if '【全文剖面' not in on:
        print('  ! 剖面没注进去——生成了不等于用上了')
        ok = False
    else:
        for line in FAKE_PROFILE.split('\n'):
            if line.strip() and line.strip() not in on:
                print('  ! 剖面内容缺失：%s' % line[:40])
                ok = False
        # 别把剖面念出来——这句护栏也得在
        if '不要把它念出来' not in on:
            print('  ! 少了"不许复述剖面"的护栏')
            ok = False
        print('  逐行核对：全部在 ✓')
    if '【已载入文档】' in on and '相关的原文片段' in on:
        print('  局部相关片段也在（局部＋全局两路都有）✓')
    print('\n%s' % ('通过' if ok else '**没通过**'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
