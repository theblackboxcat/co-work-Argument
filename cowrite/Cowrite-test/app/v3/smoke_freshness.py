# -*- coding: utf-8 -*-
"""冒烟：**服务端手里那份稿子，跟得上她改。**

背景（2026-09-19，她提的问题）：
    「模型需要在更短的间隔去核对作者对于文本的更改，并且实时地更新自己对全文的
      把握，而不是只在伴写实际发生的时候才去读局部文本，那样会导致交互侧的
      理论上出现严重的问题」

`v3/diag_freshness.py` 先把这个判断当成假设量过，四处脱节：
    ① `doc_meta()` 停在载入那一刻
    ② **她已删掉的整段**仍作为「文档中与当前段落相关的原文片段」进 prompt
    ③ §48 的【光标后面那一段】在**她新写的**段落上定位不到
    ④ 旧剖面无标记地以「你自己通读整篇后记下的判断」出现

这份冒烟管的是**修完之后**：上面四条必须都不再成立。

判据取的是**真正发出去的那一份 payload**，不是函数返回值——
"某样东西应该影响输出"这条线上栽过同形状的跟头（§48：剖面生成成功 ≠ 注进 prompt）。

用法：  python v3/smoke_freshness.py
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server      # noqa: E402

P1 = '她把杯子洗了三遍，还是觉得有味道。'
P2 = '所以我只是打算出门去走走，在这样近乎凝滞的冬日。'
P3 = '路上没什么人，风把塑料袋吹到半空，又落下来。'
P4 = '她把杯子洗了三遍，杯壁上还留着那个味道。'   # ← 与 P1 高度重合，会被召回
LOADED = [P1, P2, P3, P4]

P3_NEW = '路上没什么人。风把塑料袋吹到半空，又落下来，挂在了铁栏上。'
P5_NEW = '她后来把那把伞丢在了车站。'
P6 = '她把杯子洗了三遍，然后把它放回架子上。'      # 与 P1 高度重合 → 会被召回成"相关片段"
AFTER_EDIT = [P1, P3_NEW, P6, P5_NEW]       # 她删了 P2、P4，改写了 P3，又写了两段
INSERTED = '走到巷口的时候她想起来，钥匙还插在门上。'


class Capture:
    """假的 urlopen：截住真正要发出去的 payload。"""

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


def payload_for(text, prev=''):
    cap = Capture()
    orig = server.urllib.request.urlopen
    server.urllib.request.urlopen = cap
    try:
        server.call_model(server.load_config(), server.load_skill(),
                          text, '—', '（无预置语料）',
                          prev=prev, ctx_paras=server.pick_context(text, prev),
                          mode='P')
    finally:
        server.urllib.request.urlopen = orig
    p = cap.payload or {}
    if 'system' in p:
        return p.get('system', '') + '\n' + p['messages'][0]['content']
    return '\n'.join(m.get('content', '') for m in p.get('messages', []))


def fp_of(paras, known):
    """照前端的写法学指纹：[[字数, hash], …]；只给没见过正文的那些带上正文。

    hash 由前端算、服务端当**不透明令牌**——所以这里用什么算法不重要，
    只要**同一条文本给出同一个值**。
    """
    fps, texts = [], {}
    for i, t in enumerate(paras):
        h = hashlib.md5(t.encode('utf-8')).hexdigest()[:10]
        fps.append([len(t), h])
        if h not in known:
            texts[str(i)] = t
            known.add(h)
    return fps, texts


def main():
    server.set_doc('新鲜度冒烟', '\n\n'.join(LOADED))
    server.PROFILE.update({'status': 'none', 'text': '', 'built_at': 0, 'rev': 0})
    known = set()
    ok = True

    def chk(name, good, extra=''):
        nonlocal ok
        print('  %s %s%s' % ('ok  ' if good else 'FAIL', name,
                             (' :: %s' % extra) if (extra and not good) else ''))
        if not good:
            ok = False

    # ── 1. 同步之后，服务端对全文的把握跟着走 ────────────────────
    print('=== 1. 同步（她删了 2 段、改了 1 段、末尾加了 1 段）===')
    # 载入后第一趟同步只**建立基线**：那时服务端还没有可比的前一版指纹，
    # 硬算会把整篇判成"全没了"。所以先同步一次"还没动"的状态。
    base_fps, base_texts = fp_of(LOADED, known)
    server.apply_sync(base_fps, base_texts, total_chars=len('\n\n'.join(LOADED)))
    m0 = server.doc_meta()
    ch0 = server.SYNC.get('changed') or {}
    chk('基线那一趟不报假变更',
        not (ch0.get('removed') or ch0.get('added')),
        'removed=%d added=%d' % (len(ch0.get('removed') or []),
                                 len(ch0.get('added') or [])))
    chk('她没动 → 内容版本 rev 不走', m0['rev'] == 1, 'rev=%d' % m0['rev'])

    fps, texts = fp_of(AFTER_EDIT, known)
    ch = server.apply_sync(fps, texts, total_chars=len('\n\n'.join(AFTER_EDIT)))
    m = server.doc_meta()
    print('  服务端现在：%d 字 / %d 段（rev=%d，本次带正文 %d 段）'
          % (m['chars'], m['paragraphs'], m['rev'], len(texts)))
    chk('段数与正文一致', m['paragraphs'] == len(AFTER_EDIT),
        '%d vs %d' % (m['paragraphs'], len(AFTER_EDIT)))
    chk('字数与正文一致', m['chars'] == len('\n\n'.join(AFTER_EDIT)),
        '%d vs %d' % (m['chars'], len('\n\n'.join(AFTER_EDIT))))
    chk('没有洞（gap=0）', m['gaps'] == 0, 'gaps=%d' % m['gaps'])
    chk('她动了 → 内容版本 rev 走了一格', m['rev'] == 2, 'rev=%d' % m['rev'])
    rm_t = [e['text'] for e in (ch.get('removed') or [])]
    ad_t = [e['text'] for e in (ch.get('added') or [])]
    chk('变更集里"没了"的包含被她删掉的 P4', P4 in rm_t, repr(rm_t)[:150])
    chk('变更集里"新写"的包含改写的 P3 与新增的 P5',
        P3_NEW in ad_t and P5_NEW in ad_t, repr(ad_t)[:150])

    # ── 2. 她删掉的那段，不许再冒充"文档原文" ────────────────────
    # ⚠️ 断言必须**按块**看，不能整篇 grep。被删的文字**会**出现在 payload 里——
    #    但那是「正文变了」那一块，标明"已经不在了、这是旧稿"。那是**有意**的：
    #    不知道原来有什么，模型就不知道哪里**空了**（她要的正是"内容性的空白"）。
    #    要禁止的是它**冒充正文**出现在【相关原文片段】里。
    print('\n=== 2. 已删掉的整段，不许再冒充【文档中与当前段落相关的原文片段】===')

    def blk(pay, head):
        i = pay.find(head)
        if i < 0:
            return ''
        j = pay.find('\n【', i + len(head))
        return pay[i:j if j > 0 else len(pay)]

    pay = payload_for(P1)
    ctxb = blk(pay, '【文档中与当前段落相关的原文片段】')
    afterb = blk(pay, '【光标**后面**那一段')
    chgb = blk(pay, '【正文自你上次通读以来变了')
    print('  「相关原文片段」那块收到 %d 字' % len(ctxb))
    # ⚠️ 这块**必须非空**，下面那几条否定断言才有意义。
    #    第一版这里收到 0 字（因为筛选后一段都没命中），否定断言就**空过**了——
    #    和这次在治的正是同一种病（断言永远不会红）。所以先立一条**正压**。
    chk('「相关原文片段」这块存在且非空（否定断言才有意义）', len(ctxb) > 0,
        '收到 %d 字' % len(ctxb))
    chk('确实召回的是**现在**的段落（P6 在）', P6 in ctxb)
    chk('被删掉的旧第 4 段不在「相关原文片段」里', '杯壁上还留着那个味道' not in ctxb)
    chk('被删掉的旧第 2 段不在「相关原文片段」里', '近乎凝滞的冬日' not in ctxb)
    chk('被删掉的整段也不在「后一段」里', '杯壁上还留着那个味道' not in afterb)
    chk('但它**确实**出现在「正文变了」里（否则不知道哪里空了）',
        '杯壁上还留着那个味道' in chgb)
    chk('而且在那儿被明确标成旧稿', '这是旧稿，不是正文' in chgb)

    # ── 3. §48 的【后一段】要在**她新写的**段落上也能给 ──────────
    print('\n=== 3. §48 的【光标后面那一段】：她新写的段落上照样给得出 ===')
    now2 = [P1, INSERTED, P3_NEW, P5_NEW]          # 她在 P1 与 P3 之间插了一段
    fps2, texts2 = fp_of(now2, known)
    server.apply_sync(fps2, texts2, total_chars=len('\n\n'.join(now2)))
    print('  增量同步只带了 %d 段正文（其余按 hash 认出是旧的）' % len(texts2))
    chk('增量：没变的段不必重传正文', len(texts2) <= 2, '带了 %d 段' % len(texts2))
    no = server.find_para_no(INSERTED)
    chk('新写的段落定位得到', no == 2, 'find_para_no → %r' % no)
    nxt = server.next_para_info(INSERTED)
    chk('给得出后一段，且是紧接的那一段',
        bool(nxt) and nxt['text'].startswith(P3_NEW[:10]),
        repr(nxt)[:120])
    chk('报得出后面还有几段', bool(nxt) and nxt['paras_after'] == 2,
        repr(nxt)[:120])

    # ── 4. 剖面：新鲜的照旧，旧了的必须降级 ─────────────────────
    print('\n=== 4. 剖面的身份：新鲜的可用，旧了的降级 ===')
    server.PROFILE.update({'status': 'ready', 'built_at': 1.0,
                           'text': '· 反复出现的是"洗杯子"这个动作。',
                           'doc_chars': 0, 'rev': server.DOC_STORE['rev']})
    fresh = payload_for(P1)
    chk('剖面 rev 对得上 → 用原来的身份', '你自己通读整篇后记下的判断' in fresh)
    chk('且保留了那条许可（落在某一条上，那可以说）',
        '那可以说' in fresh)

    fps3, texts3 = fp_of([P1, INSERTED, P3_NEW + '她把伞柄上的水擦了擦。', P5_NEW],
                         known)
    server.apply_sync(fps3, texts3, total_chars=0)
    old = payload_for(P1)
    chk('剖面 rev 对不上 → 换成"已经旧了"的身份', '这份判断已经旧了' in old)
    chk('并且**撤掉**那条许可', '落在你记下的某一条上，那可以说' not in old)
    chk('旧剖面仍留着（当背景，比没有强）', '洗杯子' in old)

    # ── 5. 变更叙事：报的是"没了什么／新写了什么"，不是"第几段变短了"
    print('\n=== 5. 「正文变了」那一块：信息层面，不是字数 ===')
    chk('有【正文自你上次通读以来变了】这一块', '正文自你上次通读以来变了' in old)
    chk('说得清"这段文字已经不在了"', '已经不在了' in old)
    chk('说得清"这一段是新写的"', '新写的' in old)
    chk('明令不许说出来（只用于自我校正）', '不许把它说出来' in old)
    chk('没漏内部状态名', 'apply_sync' not in old and 'SYNC' not in old)

    # ── 6. 载入之后、**第一趟同步之前**她就改了（段数都不一样）──────
    # 这条是真接 HTTP 才暴露出来的：第一版在 `baseline` 分支里只有当段数相等时
    # 才给 removed/added 赋值，段数一变就 `removed` 未绑定、直接抛。
    # 更要紧的是它牵出的第二个问题：**认不出明细 ≠ 内容没变**。
    # 若因此不涨 rev，剖面就不会被判过期——正文变了而把握还装成新鲜的。
    print('\n=== 6. 第一趟同步时她已经改过（段数 3→2）===')
    server.set_doc('接线场景', '\n\n'.join([P1, P2, P3]))
    server.PROFILE.update({'status': 'ready', 'built_at': 1.0,
                           'text': '· 反复出现的是"洗杯子"这个动作。',
                           'doc_chars': 0, 'rev': server.DOC_STORE['rev']})
    k2 = set()
    f6, t6 = fp_of([P1, P3], k2)
    try:
        ch6 = server.apply_sync(f6, t6, total_chars=len(P1 + '\n\n' + P3))
        crashed = False
    except Exception as e:
        ch6, crashed = {}, True
        print('  抛了：%s' % e)
    chk('这条路上不炸（第一版这里 removed 未赋值）', not crashed)
    chk('认不出是哪几段变了就不报明细（不猜）',
        not (ch6.get('removed') or ch6.get('added')), repr(ch6)[:110])
    m6 = server.doc_meta()
    chk('但**内容版本照样涨**（否则剖面不会过期）', m6['rev'] == 2, 'rev=%d' % m6['rev'])
    chk('段数也跟上了', m6['paragraphs'] == 2, '段数=%d' % m6['paragraphs'])
    pay6 = payload_for(P1)
    chk('于是剖面确实被降级了', '这份判断已经旧了' in pay6)

    # ── 7. 同步时若某几段**没带正文**，宁可留洞也不许悄悄丢内容 ──────
    # 这条也是真 HTTP 逼出来的：第一版 `seeding` 只看"段数是否一致"，
    # 于是旧文里的**空占位**被逐位配成了正文——三段的稿子同步后
    # 凭空少一段，而 `gaps` 报 0。**静默丢内容**是这里最坏的一种。
    print('\n=== 7. 缺正文时留洞，不许悄悄变短 ===')
    server.set_doc('留洞场景', '\n\n'.join([P1, P2, P3]))
    k3 = set()
    f7, _ = fp_of([P1, P2], k3)            # 只送指纹，**不送任何正文**
    ch7 = server.apply_sync(f7, {}, total_chars=0)
    m7 = server.doc_meta()
    chk('报得出缺了 2 段（不是装作没事）', m7['gaps'] == 2, 'gaps=%d' % m7['gaps'])
    orig_text = server.DOC_STORE.get('text') or ''
    chk('全文**不重建**——不许把三段缩成空的两段',
        P1[:2] in orig_text and P3[:2] in orig_text, repr(orig_text)[:80])
    chk('给模型的话里也喊了一声（不是静默降级）',
        '不是完整的' in payload_for(P1))
    # 第二次把正文补齐 → 洞补上，而且不该借"留洞"把旧文当新文
    k3b = set()
    f7b, t7b = fp_of([P1, P2, P3], k3b)
    server.apply_sync(f7b, t7b, total_chars=len('\n\n'.join([P1, P2, P3])))
    m7b = server.doc_meta()
    chk('补齐之后没有洞了', m7b['gaps'] == 0, 'gaps=%d' % m7b['gaps'])
    chk('三段正文都回来了',
        server.DOC_STORE['text'] == '\n\n'.join([P1, P2, P3]),
        repr(server.DOC_STORE['text'])[:90])

    print('\n%s' % ('通过' if ok else '**没通过**'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
