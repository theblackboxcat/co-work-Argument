# -*- coding: utf-8 -*-
"""冒烟：**位置**有没有真的进到 prompt 与判断里。

背景（2026-09-19，她报的"致命故障"）：伴写默认了线性写作。前端把
"光标后面没有字符"（＝在编辑区末尾）也并进了"段末"，于是文末任何停顿都出声、
中间要恰好停在标点后才行——伴写退化成"只在文末才可能出现"。
而她"很可能先写结尾再写中间"。

**为什么不能只跑 attention.py 的自测就算过**：那只证明判断层分对了档。
"她不在文末"这件事要真的到模型眼前才算数——这条线上栽过同形状的跟头
（剖面生成成功 ≠ 注进 prompt；注意力动作集与策略正文不是同一套）。
**所以凡是"某样东西应该影响输出"，都要去抓它实际发出去的那一份。**

做法：把 server 的 urlopen 换掉，截住它实际要发的 payload，再断言。
不联网、不花钱、结果是确定性的。

用法：  python v3/smoke_position.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server      # noqa: E402
import attention   # noqa: E402  （server 已把 v3 挂上 sys.path）

P1 = '她把杯子洗了三遍，还是觉得有味道。'
P2 = '所以我只是打算出门去走走，在这样近乎凝滞的冬日。'
P3 = '路上没什么人，风把塑料袋吹到半空，又落下来。'
P4 = '她想起母亲也有一把这样的伞。'
DOC = '\n\n'.join([P1, P2, P3, P4])


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


def sent(text, hint=''):
    """把某一段当"她刚停下的段落"发一次，返回真正发出去的 prompt 全文。"""
    cap = Capture()
    orig = server.urllib.request.urlopen
    server.urllib.request.urlopen = cap
    try:
        server.call_model(server.load_config(), server.load_skill(),
                          text, '—', '（无预置语料）',
                          attn_hint=hint, mode='P')
    finally:
        server.urllib.request.urlopen = orig
    p = cap.payload or {}
    if 'system' in p:                       # anthropic 格式：system 单独一层
        return p.get('system', '') + '\n' + p['messages'][0]['content']
    return '\n'.join(m.get('content', '') for m in p.get('messages', []))


def sig_for(para_no, at_end_of_para=True, pause_ms=9000):
    """照 web/index.html 的 attentionSignals() 造一组信号。

    para_no 从 1 开始；光标落在这一段**末尾**。
    """
    paras = [P1, P2, P3, P4]
    off = sum(len(p) + 2 for p in paras[:para_no - 1]) + len(paras[para_no - 1])
    total = len(DOC)
    return dict(pause_ms=pause_ms,
                at_sentence_end=at_end_of_para,
                at_paragraph_end=False,
                mid_sentence=not at_end_of_para,
                edits_recent=0, jumps_recent=1, chars_recent=48,
                moved_up=False,
                doc_chars=total, cursor_offset=off,
                after_chars=max(0, total - off),
                after_in_para=False)


def main():
    server.set_doc('位置测试', DOC)
    server.PROFILE.update({'status': 'none', 'text': '', 'built_at': 0})
    ok = True

    # ── 1) 在文末：不该有【光标后面那一段】 ──────────────────────
    at_end = sent(P4)
    has = '【光标**后面**那一段' in at_end
    print('=== 在文末（第 4 段，后面没东西）===')
    print('  含「光标后面那一段」：%s' % has)
    if has:
        print('  ! 文末不该给后一段——它后面本来就没有东西')
        ok = False

    # ── 2) 在中间：必须把"后面那一段"给到模型眼前 ────────────────
    mid = sent(P2)
    print('\n=== 在中间（第 2 段，后面还有两段已写好）===')
    checks = [
        ('含「光标后面那一段」', '【光标**后面**那一段' in mid),
        ('给的是**紧接**的下一段（第 3 段原文）', P3 in mid),
        ('标明后面还有几段（「后面还有 2 段」）', '后面还有 2 段' in mid),
        ('带了限制措辞（不要建议她写这一段）', '不要建议她写这一段' in mid),
        ('点破"不是顺着往下写的"', '不是顺着往下写的' in mid),
        ('没有把**再后面**那段也塞进来（第 4 段不该出现）', P4 not in mid),
    ]
    for name, good in checks:
        print('  %s %s' % ('ok ' if good else 'FAIL', name))
        if not good:
            ok = False

    # ── 3) 判态 + 动作：位置换了，说什么也要换 ──────────────────
    print('\n=== 判态（前端信号 → attention.infer）===')
    st_end, info_end = attention.infer(sig_for(4))
    st_mid, info_mid = attention.infer(sig_for(2))
    cases = [
        ('文末·停在句末 → PLANNING', st_end == 'PLANNING'),
        ('中间·停在句末 → RECONTEXT', st_mid == 'RECONTEXT'),
        ('两边都出声（"说不说"上对称）',
         info_end['speak'] is True and info_mid['speak'] is True),
        ('位置标签：append / insert',
         info_end['position'] == 'append' and info_mid['position'] == 'insert'),
    ]
    for name, good in cases:
        print('  %s %s' % ('ok ' if good else 'FAIL', name))
        if not good:
            ok = False

    # ── 4) 动作限制要真的进 prompt，而不是只写在 STATES 里 ──────
    hint = attention.prompt_hint(info_mid)
    with_hint = sent(P2, hint=hint)
    print('\n=== RECONTEXT 的动作限制进没进 prompt ===')
    hchecks = [
        ('禁令「接下来写什么」在里面', '接下来写什么' in with_hint),
        ('只许"一个真问题"或位置事实', '一个真问题' in with_hint),
        ('内部状态键名没漏出去', 'RECONTEXT' not in with_hint),
    ]
    for name, good in hchecks:
        print('  %s %s' % ('ok ' if good else 'FAIL', name))
        if not good:
            ok = False

    print('\n%s' % ('通过' if ok else '**没通过**'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
