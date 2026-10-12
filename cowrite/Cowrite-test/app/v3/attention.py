# -*- coding: utf-8 -*-
"""注意力机制：从光标与击键行为推断作者当下的状态，据此选伴写策略。

## 为什么要有这一层

v3 之前，系统只知道"作者停笔 N 秒了"——这是一个纯时间信号。
但写作研究里更有信息量的是**停顿发生在文本的哪一层**：

- 键盘记录研究（Inputlog，Leijten & Van Waes 2013）把停顿阈值定在 **2000ms**，
  超过这个长度的停顿对应**高层认知活动**（构思、规划），
  而 200ms 量级的短停顿只反映低层的语言编码（选词、拼写）。
  阈值 30ms 以下算噪声（手指滑动），不算停顿。
- **停顿的位置**比长度更要紧（Révész et al., 2017/2019）：
  句间/段间的停顿＝在规划下一个更大的单位；词内的停顿＝在做语言编码。
- **P-burst**（两次停顿之间的连续产出）衡量流畅度；
  **R-burst**（停顿之后发生的修改）＝作者在做**评价与修订**（Galbraith & Baaijen, 2019）。

## 所以本模块的判断是

| 观测 | 推断 | 该做什么 |
|---|---|---|
| 光标在**句中**，停 2–8 秒 | 低层语言编码（在想一个词/一个句法） | **不说话**。这是最不该打断的时候 |
| 光标在**句末/段末**，停 2 秒以上，且刚有连续产出 | P-burst 结束，在规划下一个单位 | 常规伴写（一个动作） |
| 同上，但**光标后面还有已写好的正文** | 她不在文末——写作是**非线性**的（先写结尾再回头补中间） | 出声，但**只谈"这一段/这一处"**，绝不谈"接下来写什么"（下一段早就存在） |
| 停超过 STUCK_SEC，或光标在同一处来回挪，没有新字 | 卡住 | 给"替她说短"或"一个真问题"，**不给方案** |
| 刚有**删改**（回退键密集；光标回跳要伴随删改才算），现在停了 | R-burst，作者在**评价与打磨** | 只给可核对的东西（跨段呼应），或沉默；**绝不评价** |
| 光标往上走、没有输入 | 通读/回看 | 沉默 |
| 文档开头、还没写几个字 | 尚未开始 | 沉默 |

**位置是判断的一部分，不是背景**（2026-09-19 补）。上面两行"句末/段末"的判据
**两侧对称**：文末与中间用同一套边界条件。曾经它是**不对称**的——因为前端把
"光标后面没有字符"（＝在编辑区末尾）也并进了"段末"，于是文末的任何停顿都算段末、
都能出声，而中间要恰好停在标点后才行。那一行让伴写退化成"只在文末才可能出现"，
恰好默认了线性写作。**位置现在单列成信号**（`after_chars` / `after_in_para`，
见 `_position()`），用来决定**说什么**，不再偷偷决定**说不说**。

**设计原则**：注意力机制的第一作用是**决定不出声**。
大部分状态下正确的行为是沉默——这比"更聪明地出声"更重要，
也和 D9（不打断流动）是同一条。

诚实声明：这些阈值是从群体研究借来的先验，不是本作者的实测值。
推断结果会写入埋点，等作者反馈后再用 hy4 校准。

## 丙（2026-09-20 加）：把这个判断交还给模型

作者的原话：「现在大模型的能力已经远大于我们论文中的那些判断，那些判断有些过于教条了。」

她说得对，而且有一个技术事实撑着它：实测把整篇（12 万字）一起送进去只要 3.7 秒，
**输入长度几乎不影响延迟**。也就是说，原先为了"省"而预先做掉的那些结构判断，
省下的时间约等于零，代价却是把模型的读法提前锁死了。

所以丙之下本模块的职责变了：

| | 甲 / 乙（规则版） | 丙（放权版） |
|---|---|---|
| 本模块 | **判断者** | **采集者** |
| speak | 规则说了算；false 就直接拦掉，**根本不调模型** | 恒 true；说不说由模型读完现场自己定 |
| state | 被当成命令执行 | 降为**一个参考视角**（`regex_state`），随现场交出去 |
| action_hint | 「这一次只准做第 3 个动作」 | 空——不预设 |
| 留下的门 | 四档沉默 | 只剩 `ask`：值不值得花一次调用去问（`ASK_MIN_MS`），是**资源**判据 |

`prompt_hint()`（命令式）留给甲/乙；丙改用 `describe()`（陈述式）。
两者措辞上的分界只有一条：**describe 里不许出现"所以 / 说明 / 应该"**——
一旦出现，事实就又变回命令了。
"""
import time

# ── 阈值（来自写作过程研究的先验，待校准）────────────────────────
PAUSE_PLANNING_MS = 2000     # 高层规划的最小停顿（Inputlog 惯例）
PAUSE_STUCK_MS = 15000       # 超过这个长度且没有新字＝卡住
REVIEW_HOLD_MS = 8000        # 光标停在旧位置这么久＝在回看
REVISION_WINDOW_MS = 30000   # 修订密度看最近 30 秒
REVISION_DENSE = 3           # 30 秒内 ≥3 次删改＝在打磨
JUMP_DENSE = 2               # 30 秒内 ≥2 次光标回跳＝在来回比对

# 丙（放权）唯一还留下的规则门：**值不值得花一次调用去问它**。
# 注意这不是"该不该说话"——那是模型的判断了（见 infer(delegate=True)）。
# 这条只管"这么短的停顿，问了也是浪费"。
ASK_MIN_MS = 3000

# 句末/段末的判定：停在这些符号之后，或就停在一个空行/段尾
SENT_END = '。！？；…!?;'
PARA_END = '\n'


def _now():
    return int(time.time() * 1000)


# ── 状态与策略 ──────────────────────────────────────────────────────
STATES = {
    'CODING': {
        'name': '低层语言编码（句中停顿）',
        'speak': False,
        'delay': 20,
        'action': '',
        'why': '光标停在句子中间，这是选词/选句法的停顿（<2s 量级的高层规划尚未开始）。'
               '此刻出声＝打断语言编码，代价最大。',
    },
    'PLANNING': {
        'name': 'P-burst 结束，在规划下一个单位',
        'speak': True,
        'delay': 8,
        'action': '五个动作里任选一个最真的：'
                  '1 递你自己的东西／2 替她说短／3 一个真问题／4 说你卡住／5 极短一句。',
        'why': '连续产出刚结束，光标停在句末或段末——这是标准的规划停顿，可以说话。',
    },
    'RECONTEXT': {
        'name': '不在文末（光标后面已有写好的正文）',
        'speak': True,
        'delay': 8,
        'action': '只做**动作 3「一个真问题」**，或给**一处可核对的位置事实**'
                  '（这一处与后文的呼应、同一个词在别处出现过几次、两处时间对不对）。'
                  '**不做 1**（不递你自己的东西——她手上正握着一段在补）、'
                  '**不做 2**（不替她说短）、**不做 4/5**。'
                  '**绝不给「接下来写什么」「下一段可以…」这类话**——'
                  '她后面已经有正文了，那句是空话，而且会让她觉得你在替她缺的那块填空。',
        'why': '她不在文末：光标后面还有已经写好的东西，说明这一篇不是从头顺着写的。'
               '这时候"下一个单位"未必紧跟在光标之后，能谈的是**这一处**本身。'
               '位置的来源是 after_chars / after_in_para 两个信号，不是猜的。',
    },
    'STUCK': {
        'name': '卡住（久停且无新字）',
        'speak': True,
        'delay': 12,
        'action': '只做**动作 2「替她说短」**或**动作 3「一个真问题」**（问题必须带上你的猜测）。'
                  '**不做 1**（她在等一个落点，不是在等闲聊）；'
                  '**不给位置事实、不给结构观察**——卡住的时候被给一张地图，'
                  '等于被告知"你自己看"；**更不给方向、不给方案**——'
                  '卡住时被给方案，等于别人替你写了。',
        'why': '卡住时作者要的是被接住，不是被指点。方案会夺走所有权。',
    },
    'POLISHING': {
        'name': 'R-burst，在打磨',
        'speak': True,
        'delay': 15,
        'action': '只做**动作 5「极短一句」**，或者给**一处可核对的位置事实**'
                  '（这个词在文档别处出现过几次、两处时间对不对）——说完就停。'
                  '**不做 1、不做 3**：不要递你自己的东西，不要抛问题。'
                  '**不做任何评价、不给任何建议**——她正在自己评价，不要抢。',
        'why': '修订＝作者自己的评价活动。这时候插嘴评价，等于把她的判断换成我的；'
               '而打磨中的人不需要再接一个新话题。',
    },
    'REVIEWING': {
        'name': '在通读/回看',
        'speak': False,
        'delay': 0,
        'action': '',
        'why': '光标在往上走且没有输入——她在读，不是在写。不打断阅读。',
    },
    'NOT_STARTED': {
        'name': '尚未开始',
        'speak': False,
        'delay': 0,
        'action': '',
        'why': '文档开头、几乎没有内容。这时候说什么都是凭空。',
    },
}


def _position(sig):
    """光标在文档的**哪个位置类型**上。缺字段一律当 'append'——
    老前端不带这两个信号，那就保持它原来的行为，不要让缺信号变成"她不在文末"。

    三种位置（她说的"非线性写作"全落在这里）：
      append  光标后面没有字 → 在文末往下写（唯一被支持了很久的那种）
      within  光标后面还有**本段内**的字 → 她在一段中间补/改
      insert  光标落在段落边界上，但后面还有别段 → 在两段之间插一段
    """
    after = _num(sig.get('after_chars'))
    if after <= 0:
        return 'append'
    return 'within' if sig.get('after_in_para') else 'insert'


def infer(sig, delegate=False):
    """sig 是前端给的一组信号，缺字段就当没有。

    返回 (state_key, info dict)；info 含 name / speak / delay / action / why /
    signals（回显，便于埋点与调试）。

    **delegate=True ＝ 丙（放权）**：规则不再决定说不说。
    它照常算出 state，但那个 state 从此只是一个**参考视角**，
    另外存进 `regex_state` 留档；真正拦不拦，由模型读完现场自己判。
    这里唯一还留着的门是 `ask`——"这一处值不值得花一次调用去问"，
    是**资源**判据（问了也是浪费），不是内容判据。
    """
    state, info = _infer_rules(sig)
    if not delegate:
        return state, info
    pause = _num(sig.get('pause_ms'))
    info = dict(info)
    info['regex_state'] = state
    info['regex_speak'] = info.get('speak')
    info['delegated'] = True
    info['speak'] = True               # 规则不再拦；说不说归模型
    info['action_hint'] = ''           # 也不预设"只准做哪一个动作"
    info['ask'] = not (state == 'NOT_STARTED' or pause < ASK_MIN_MS)
    return state, info


def _num(v, default=0):
    """把信号值变成数。坏值退回默认，**不抛**。

    原来一律用 `int(sig.get('x') or 0)`：只要前端送来的不是数字
    （空串之外的任何一种：'—'、'很久'、对象），这里就抛 ValueError，
    而这个函数在**每一次出牌判断**里都跑——等于一个坏信号能让整套
    注意力机制失灵，还只在服务端 stderr 留一行。
    """
    try:
        return int(float(v))
    except Exception:
        return default


def _infer_rules(sig):
    """规则版（甲 / 乙）。丙之下它退居幕后，但**仍然要跑**——
    它算出的 state 会作为一个参考视角随现场一起交出去
    （"按老办法看，这像是卡住"），而不是命令。"""
    pause = _num(sig.get('pause_ms'))
    at_end = bool(sig.get('at_sentence_end') or sig.get('at_paragraph_end'))
    mid = bool(sig.get('mid_sentence'))
    edits = _num(sig.get('edits_recent'))      # 最近 30 秒的删改次数
    jumps = _num(sig.get('jumps_recent'))      # 最近 30 秒的光标回跳次数
    chars_recent = _num(sig.get('chars_recent'))
    moved_up = bool(sig.get('moved_up'))
    total_chars = _num(sig.get('doc_chars'))
    cursor_at = _num(sig.get('cursor_offset'))

    # 1) 还没开始 / 光标在文档开头附近
    if total_chars < 40 and cursor_at < 40:
        return 'NOT_STARTED', _pack('NOT_STARTED', sig)

    # 2) 在回看：光标往上走、没有新输入
    if moved_up and chars_recent <= 0 and pause >= REVIEW_HOLD_MS:
        return 'REVIEWING', _pack('REVIEWING', sig)

    # 3) 在打磨：最近有密集删改。
    #    **光标回跳单独不算**——"回头补中间"的时候她本来就会跳来跳去找位置，
    #    那是**写**，不是打磨（实测：跳两下、一个字没删，也会被判成 POLISHING，
    #    于是动作被压成"极短一句/位置事实"，还要 15 秒才开口）。回跳要**伴随删改**
    #    才算评价活动的证据。删改密集这一支不受影响。
    if edits >= REVISION_DENSE or (jumps >= JUMP_DENSE and edits >= 1):
        return 'POLISHING', _pack('POLISHING', sig)

    # 4) 卡住：停很久、没有新字、且没在做修订
    if pause >= PAUSE_STUCK_MS and chars_recent <= 0:
        return 'STUCK', _pack('STUCK', sig)

    # 5) 句中停顿＝低层语言编码。这是最容易被误判成"该说话"的一种。
    if mid and not at_end:
        return 'CODING', _pack('CODING', sig)

    # 6) 高层规划：停够了，且停在单位的边界上。
    #    这里**只看"停在什么单位上"**，不看她在文档的哪儿——两级判据都过才说话，
    #    文末与中间同一套（位置不参与"说不说"，见模块开头那段）。
    #    位置进来换的是**说什么**：不在文末时"下一段"早就存在，PLANNING 那套
    #    "选一个动作"会把她引向"接下来写什么"，所以换成 RECONTEXT。
    if pause >= PAUSE_PLANNING_MS and (at_end or not mid):
        pos = _position(sig)
        if pos == 'append':
            return 'PLANNING', _pack('PLANNING', sig, position=pos)
        return 'RECONTEXT', _pack('RECONTEXT', sig, position=pos)

    # 7) 其余：停顿还不够长，不要说话
    return 'CODING', _pack('CODING', sig, why_extra='停顿不足 %dms，尚不构成高层规划。'
                           % PAUSE_PLANNING_MS)


def _pack(state, sig, why_extra='', position=None):
    s = STATES[state]
    why = s['why'] + (('（' + why_extra + '）') if why_extra else '')
    return {
        'state': state,
        'name': s['name'],
        'speak': s['speak'],
        'delay_sec': s['delay'],
        'action_hint': s['action'],
        'why': why,
        'position': position or _position(sig),
        'signals': {
            'pause_ms': sig.get('pause_ms'),
            'at_sentence_end': sig.get('at_sentence_end'),
            'at_paragraph_end': sig.get('at_paragraph_end'),
            'mid_sentence': sig.get('mid_sentence'),
            'edits_recent': sig.get('edits_recent'),
            'jumps_recent': sig.get('jumps_recent'),
            'chars_recent': sig.get('chars_recent'),
            'moved_up': sig.get('moved_up'),
            'after_chars': sig.get('after_chars'),
            'after_in_para': sig.get('after_in_para'),
        },
    }


def prompt_hint(info):
    """把注意力状态写成一句给策略正文用的追加说明（只在决定说话时注入）。"""
    if not info or not info.get('speak'):
        return ''
    return ('【作者当下的注意力状态】%s。\n'
            '**这一条只准做下面这一件事，其余四个动作一律不做：**\n%s\n'
            '（推断依据：%s）\n'
            '这条限制**压过**你在别处读到的任何"选一个最真的动作"的指示——'
            '这次的动作已经由她的光标位置替你选好了。'
            % (info['name'], info['action_hint'], info['why']))


SILENT_CARD = {
    'type': 'withhold',
    'level': 'muted',
    'title': '⊘ · 注意力判断：现在不说话',
    'body': '',
    'evidence': [],
}


def describe(sig, info=None):
    """把信号翻成**事实句**，交给模型自己去判断说不说。

    和 `prompt_hint` 的区别是根本性的：

      prompt_hint 说「这一次只准做第 3 个动作」——那是**命令**；
      describe    只陈述发生了什么            ——那是**事实**。

    丙之所以要把前者换成后者：那些阈值是从 Inputlog 的群体研究借的**先验**，
    在这个作者身上从没实测过。拿它替她（和替模型）做决定，
    是**把统计当成了真理**——这正是"过于教条"的来源。
    事实留着，判断交回去。

    措辞上有一条纪律：**这里不许出现"所以""说明""应该"**。
    一旦出现，事实就又变回命令了。
    """
    pause = _num(sig.get('pause_ms'))
    total = _num(sig.get('doc_chars'))
    cur = _num(sig.get('cursor_offset'))
    after = _num(sig.get('after_chars'))
    ch = _num(sig.get('chars_recent'))
    ed = _num(sig.get('edits_recent'))
    jp = _num(sig.get('jumps_recent'))

    lines = ['她停笔 %d 秒了。' % round(pause / 1000.0)]

    if sig.get('mid_sentence'):
        lines.append('光标停在**句子中间**（前一个字符不是标点）。')
    elif sig.get('at_paragraph_end'):
        lines.append('光标停在**段落边界**上（她刚敲过回车，正要起一段）。')
    elif sig.get('at_sentence_end'):
        lines.append('光标停在**句末**。')

    pos = (info or {}).get('position') or _position(sig)
    if pos == 'append':
        lines.append('光标后面没有已写好的字——她在文末往下写。')
    elif pos == 'within':
        lines.append('光标后面**还有这一段的字**——她不是从头顺着写，'
                     '是在回头补这一段 / 改这一段。')
    else:
        lines.append('光标正压在两段之间，后面跟的是**另一段**已经写好的正文——'
                     '她不是从头顺着写。')

    if total:
        lines.append('全文 %d 字，光标落在第 %d 字处。' % (total, cur))

    # 章名坐标（2026-09-20）：她报过"模型只会回 §1308 这种行标"。
    # 只报段号时，模型手里唯一可引用的坐标就是段号——那对人是不可读的。
    # 这里补一句**她认得的坐标**（第几章、章名），前端 cursorParaNo() 算出、
    # 后端 chapter_of() 反查章名后放进信号里。
    # ⚠️ 只在**认得出章**时才说；认不出（无章文本）就不提，别硬编一个"第 1 章"。
    cno = _num(sig.get('chapter_no'))
    cti = (sig.get('chapter_title') or '').strip()
    pno = _num(sig.get('para_no'))
    if cno and cti:
        # 只给章名，**不给段号**：段号是模型最容易顺手抄的那个坐标，
        # 而她的界面上根本不显示它（§1308 就是这么冒出来的）。
        # 至于"该报什么"——那条规矩统一放在 user 末尾的 coord 段里：
        # **事实归事实，规矩归规矩**，别在事实句里夹带指令。
        lines.append('她现在在第 %d 章「%s」里。' % (cno, cti))
    elif pno:
        lines.append('光标在全篇第 %d 段（这一篇认不出章：没有可引用的章名，'
                     '别自己编一个）。' % pno)

    if ch or ed or jp:
        lines.append('最近 30 秒：新打 %d 字，删改 %d 次，光标回跳 %d 次。'
                     % (ch, ed, jp))
    else:
        lines.append('最近 30 秒：没有输入，也没有删改。')

    if sig.get('moved_up'):
        lines.append('她最后一下是把光标**往上**挪的。')

    st = (info or {}).get('regex_state') or (info or {}).get('state')
    if st and st in STATES:
        lines.append('（按旧的规则判，这一处读作「%s」。'
                     '那套阈值是从群体研究借的先验、不是她的实测值——'
                     '只当一个看法，不是命令。）' % STATES[st]['name'])
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys

    # 一群"同一只手、同样的停顿，只换位置"的对照。**前两组必须成对相等**——
    # 文末与中间在"说不说"上不许有差别，只在"说什么"上分岔。
    # 这三条是 2026-09-19 那个故障的正身（那时候文末一律出声、中间一律沉默）。
    cases = [
        # ⚠️ 这一条以前写的是 cursor_offset=2900 / doc_chars=3000（后面还剩 100 字）。
        #    那在旧代码里照样判 PLANNING——因为"后面有没有字"当时根本不参与判断。
        #    现在它**应该**判 RECONTEXT：她不在文末。所以夹具改成真的落在末尾，
        #    要那一档请见下面的「中间·停在句末」。
        ('刚写完一句，停 9 秒', 'PLANNING',
         dict(pause_ms=9000, at_sentence_end=True, chars_recent=48,
              doc_chars=3000, cursor_offset=3000, after_chars=0)),
        ('句中停 4 秒', 'CODING',
         dict(pause_ms=4000, mid_sentence=True, chars_recent=12,
              doc_chars=3000, cursor_offset=3000, after_chars=0)),
        ('停 40 秒没打字', 'STUCK',
         dict(pause_ms=40000, at_paragraph_end=True, chars_recent=0,
              doc_chars=3000, cursor_offset=2900, after_chars=100)),
        ('刚删了五处', 'POLISHING',
         dict(pause_ms=6000, at_sentence_end=True, edits_recent=5, chars_recent=3,
              doc_chars=3000, cursor_offset=2900, after_chars=100)),
        ('往上翻着看', 'REVIEWING',
         dict(pause_ms=12000, moved_up=True, chars_recent=0,
              doc_chars=3000, cursor_offset=400, after_chars=2600)),
        ('空文档', 'NOT_STARTED',
         dict(pause_ms=9000, doc_chars=6, cursor_offset=6, after_chars=0)),
        # ── 位置对照（本次新增）─────────────────────────────
        ('文末·停在句末', 'PLANNING',
         dict(pause_ms=9000, at_sentence_end=True, chars_recent=48,
              doc_chars=3000, cursor_offset=3000, after_chars=0)),
        ('文末·句子写一半', 'CODING',
         dict(pause_ms=9000, mid_sentence=True, chars_recent=48,
              doc_chars=3000, cursor_offset=3000, after_chars=0)),
        ('中间·停在句末', 'RECONTEXT',
         dict(pause_ms=9000, at_sentence_end=True, chars_recent=48, jumps_recent=1,
              doc_chars=3000, cursor_offset=900, after_chars=2100)),
        ('中间·段内后面还有字', 'RECONTEXT',
         dict(pause_ms=9000, at_sentence_end=True, chars_recent=48, jumps_recent=1,
              doc_chars=3000, cursor_offset=900, after_chars=2100,
              after_in_para=True)),
        ('中间·句子写一半', 'CODING',
         dict(pause_ms=9000, mid_sentence=True, chars_recent=48,
              doc_chars=3000, cursor_offset=900, after_chars=2100)),
        # 跳来跳去找位置（没删东西）——那是**写**，不是打磨
        ('中间·跳两下没删改', 'RECONTEXT',
         dict(pause_ms=9000, at_sentence_end=True, chars_recent=48, jumps_recent=3,
              edits_recent=0, doc_chars=3000, cursor_offset=900, after_chars=2100)),
        ('跳两下 + 删过一处', 'POLISHING',
         dict(pause_ms=9000, at_sentence_end=True, chars_recent=48, jumps_recent=3,
              edits_recent=1, doc_chars=3000, cursor_offset=900, after_chars=2100)),
    ]

    bad = 0
    for name, want, sig in cases:
        st, info = infer(sig)
        mark = 'ok ' if st == want else 'FAIL'
        if st != want:
            bad += 1
        print('%s %-20s → %-10s speak=%-5s delay=%2ss  pos=%s'
              % (mark, name, st, info['speak'], info['delay_sec'], info['position']))
    # 文末与中间在"说不说"上必须一致
    pairs = [('文末·停在句末', '中间·停在句末'), ('文末·句子写一半', '中间·句子写一半')]
    for a, b in pairs:
        sa = infer(dict([c for c in cases if c[0] == a][0][2]))[1]['speak']
        sb = infer(dict([c for c in cases if c[0] == b][0][2]))[1]['speak']
        ok = (sa == sb)
        if not ok:
            bad += 1
        print('%s 对称：%s 与 %s 都 %s'
              % ('ok ' if ok else 'FAIL', a, b, '出声' if sa else '沉默'))
    print('\n%d 项，%d 个不对' % (len(cases), bad))

    # ── 丙（放权）：同一批夹具，规则不再拦 ─────────────────────
    # 这里要看的**不是**"判得对不对"（那是甲才有的评分方式），而是：
    # 规则原本要沉默的那几档，现在全都进了候选，等着模型自己定。
    print('\n--- 丙（delegate=True）：规则只交事实，说不说归模型 ---')
    for name, want, sig in cases:
        _, info = infer(sig, delegate=True)
        print('%-20s 规则判=%s(%s)  丙 speak=%s  ask=%s'
              % (name, info['regex_state'],
                 '说' if info['regex_speak'] else '不说',
                 info['speak'], info['ask']))
    print('\n交出去的"事实"长这样（拿「中间·句子写一半」举例，'
          '注意它只陈述、不下结论）：')
    _sig = [c for c in cases if c[0] == '中间·句子写一半'][0][2]
    print(describe(_sig, infer(_sig, delegate=True)[1]))

    sys.exit(1 if bad else 0)
