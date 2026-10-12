# -*- coding: utf-8 -*-
"""诊断：**服务端对全文的把握是载入那一刻的**，之后她的每一次改动都进不去。

她 2026-09-19 提的问题（原话）：
    「模型需要在更短的间隔去核对作者对于文本的更改，并且实时地更新自己对
      全文的把握，而不是只在伴写实际发生的时候才去读局部文本，那样会导致
      交互侧的理论上出现严重的问题」

先把这个判断**当成一个待证伪的假设**来查，不先信。

查到的事实（读代码得到，下面每一条都跑一遍验证）：
  · `DOC_STORE` 只有**一个**写入口：`set_doc()`，而它只被 `_api_doc`（载入）调用。
    前端在伴写时只送**当前段 + 前一段**（`web/index.html` 的 `cursorContext()`），
    全文从不回传。
  · 于是 `pick_context()` / `find_para_no()` / `next_para_info()` / `doc_meta()`
    全都在读同一张**载入时的快照**。
  · `PROFILE`（全文剖面）是载入时通读一遍的结果，`built_at` 之后就再没重算过，
    而它在 prompt 里的抬头是「你自己通读整篇后记下的判断」，
    还附了一句许可——「如果这一处正好落在你记下的某一条上，那可以说」。

这份脚本不去修任何东西，只把后果量出来：
**她改动之后，模型眼前的那份"文档"里还剩多少是真的。**

用法：  python v3/diag_freshness.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server      # noqa: E402

# ── 载入时的那一份 ───────────────────────────────────────────────
P1 = '她把杯子洗了三遍，还是觉得有味道。'
P2 = '所以我只是打算出门去走走，在这样近乎凝滞的冬日。'
P3 = '路上没什么人，风把塑料袋吹到半空，又落下来。'
P4 = '她把杯子洗了三遍，杯壁上还留着那个味道。'      # ← 与 P1 高度重合，会被召回
LOADED = '\n\n'.join([P1, P2, P3, P4])

# ── 她之后在浏览器里做的事（真实发生在编辑区，服务端看不到）────────
P3_NEW = '路上没什么人。风把塑料袋吹到半空，又落下来，挂在了铁栏上。'
P4_DELETED = P4                                     # 整段删掉
P5_NEW = '她后来把那把伞丢在了车站。'
# ⚠️ 夹具教训：第一版把 NOW 写成 4 段，**恰好和 LOADED 同为 89 字 4 段**，
#    于是第 1 项假装"一致"了——和这次在治的病一模一样（不会红的断言）。
#    漂移必须体现在**段数与字数都不同**上。
NOW = '\n\n'.join([P1, P3_NEW, P5_NEW])             # 现在正文真正是这 3 段（P2、P4 已删）

# 她插入的一段（在第 2、3 段之间新写的）——载入时不存在
INSERTED = '走到巷口的时候她想起来，钥匙还插在门上。'


class Capture:
    """假的 urlopen：截住真正要发出去的 payload，回一个空内容。"""

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


def payload_for(text, prev='', hint=''):
    """照 /api/cowrite 的走法发一次，返回真正发出去的 payload 全文。"""
    cap = Capture()
    orig = server.urllib.request.urlopen
    server.urllib.request.urlopen = cap
    try:
        server.call_model(server.load_config(), server.load_skill(),
                          text, '—', '（无预置语料）',
                          prev=prev, ctx_paras=server.pick_context(text, prev),
                          attn_hint=hint, mode='P')
    finally:
        server.urllib.request.urlopen = orig
    p = cap.payload or {}
    if 'system' in p:
        return p.get('system', '') + '\n' + p['messages'][0]['content']
    return '\n'.join(m.get('content', '') for m in p.get('messages', []))


def main():
    server.set_doc('新鲜度诊断', LOADED)
    server.PROFILE.update({'status': 'none', 'text': '', 'built_at': 0})
    problems = 0

    print('=' * 68)
    print('0. 载入')
    print('=' * 68)
    m = server.doc_meta()
    print('  服务端：%d 字 / %d 段' % (m['chars'], m['paragraphs']))
    print('  这次刻意让漂移明显（段数和字数都要不同），免得断言自己骗自己')
    print('  前端有没有回传的路径？ —— 只有 /api/doc（载入那一次）。')

    # ── 1. 服务端的"文档"停在载入那一刻 ─────────────────────────
    print()
    print('=' * 68)
    print('1. 她改完之后，服务端那份"文档"还是旧的')
    print('=' * 68)
    m2 = server.doc_meta()
    now_paras = len(NOW.split('\n\n'))
    drift = (m2['chars'] != len(NOW)) or (m2['paragraphs'] != now_paras)
    print('  服务端仍报：%d 字 / %d 段' % (m2['chars'], m2['paragraphs']))
    print('  实际是：    %d 字 / %d 段' % (len(NOW), now_paras))
    if drift:
        print('  ✗ 不一致——服务端对全文的把握已经和正文脱节')
        problems += 1
    else:
        print('  ok 一致')

    # ── 2. 她删掉的整段，还会当"文档原文"递给模型 ───────────────
    print()
    print('=' * 68)
    print('2. 她删掉的那一段，还会出现在【文档中与当前段落相关的原文片段】里')
    print('=' * 68)
    pay = payload_for(P1)
    leaked = '杯壁上还留着那个味道' in pay
    print('  她现在这一段：%s' % P1)
    print('  被删掉的旧第 4 段原文在 payload 里？ %s' % ('**在**' if leaked else '不在'))
    if leaked:
        print('  ✗ 模型被告知了一段**正文里已经不存在**的文字，还标着段号和字数。')
        print('    这是最坏的一种：它不是在猜，是在**据实引用一个幽灵**。')
        problems += 1
    else:
        print('  ok 没有泄漏已删除的旧文')

    # ── 3. §48 刚加的「后一段」，在她真用起来时就失效 ───────────
    print()
    print('=' * 68)
    print('3. §48 的【光标后面那一段】：她一插入新段就定位不到')
    print('=' * 68)
    nxt = server.next_para_info(INSERTED)
    print('  她在第 2、3 段之间新写了一段（载入时不存在）：%s' % INSERTED)
    print('  find_para_no(新段) → %r' % server.find_para_no(INSERTED))
    print('  next_para_info(新段) → %r' % (nxt,))
    if nxt is None:
        print('  ✗ 定位不到 → 不给【后一段】。')
        print('    可**前端**量的是编辑区，它说得很对：after_chars > 0，后面有字。')
        print('    于是模型知道"后面有东西"却看不见——它照样只能猜"接下来写什么"。')
        print('    而"先写结尾、回头补中间"正是 §48 要治的那个场景：')
        print('    她回头补的时候，光标多半落在**新写的**段落里。')
        problems += 1
    else:
        print('  ok 定位到了')

    # ── 4. 剖面被当作"你自己通读整篇后记下的判断" ───────────────
    print()
    print('=' * 68)
    print('4. 全文剖面照样以"你自己通读整篇后记下的判断"的身份出现')
    print('=' * 68)
    # 演如下：剖面在载入时生成，记的是**旧**的那一篇（含已被删掉的东西）
    server.PROFILE.update({'status': 'ready', 'built_at': 1.0,
                           'text': '· 反复出现的是"洗杯子"这个动作，它在结尾又回来了一次。',
                           'doc_chars': len(LOADED)})
    pay4 = payload_for(P1)
    has_prof = '全文剖面' in pay4
    has_stale = ('洗杯子' in pay4)
    marked = any(k in pay4 for k in ('剖面已过期', '剖面过期', '已经变了', '与当前正文不一致'))
    print('  剖面进了 payload？ %s' % has_prof)
    print('  里面那条"洗杯子在结尾又回来了一次"（那一段已被她删了）进去了？ %s'
          % ('**进了**' if has_stale else '没进'))
    print('  payload 里有没有任何"它已经旧了"的标记？ %s' % ('有' if marked else '**没有**'))
    if has_stale and not marked:
        print('  ✗ 剖面是**无标记的旧判断**，而 prompt 明说"落在你记下的某一条上，那可以说"。')
        print('    于是模型会照着一条已经不成立的观察去说话——它自己还以为那是通读所得。')
        problems += 1
    else:
        print('  ok 剖面没有以陈旧身份出现')

    print()
    print('=' * 68)
    print('小结：%d 处脱节' % problems)
    print('=' * 68)
    print('共同根因只有一条：**服务端只被喂过一次（载入），之后全靠那一份。**')
    print('前端的探针每 8 秒问一次"要不要出声"，却从不问"你手里的稿子还是这份吗"。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
