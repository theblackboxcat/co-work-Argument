# -*- coding: utf-8 -*-
"""组装 v3 的 system prompt：策略正文 + 模式 + 禁令 + 输出形态。

server.py（实时）与 runner.py（冷启动对照）共用这一份，
保证"网页里跑的"和"实验里跑的"是同一套策略。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_V3 = os.path.join(HERE, 'SKILL_v3.md')
# 放权版（丙）追加的协议节。它**不**进 format 模板，由 _inject_delegate 直接插在
# 标题行之后——协议要早被读到，埋在中段等于没说。
SKILL_V3_DELEGATE = os.path.join(HERE, 'SKILL_v3_delegate.md')

from classifier import MODE_DESC, classify, load_params  # noqa: E402
from bans import MODE_FORM, render_ban_lines  # noqa: E402


def max_chars_line(params, mode):
    n = int((params.get('policy', {}).get(mode, {}) or {}).get('max_chars', 0) or 0)
    if n <= 0:
        return '**长度：不设上限，以短为佳。** 三句以内能说完，就不要写第四句。'
    return '**长度上限：%d 字。** 超了就删——删掉的那部分本来也不该你说。' % n


def _inject_delegate(tpl):
    """把放权协议插在**标题行之后**——它得早被读到，埋在中段等于没说。"""
    try:
        with open(SKILL_V3_DELEGATE, encoding='utf-8') as f:
            dsec = f.read().strip()
    except Exception as e:
        print('[policy] 放权协议读不到，本次按规则版走：%s' % e)
        return tpl
    if not dsec:
        return tpl
    i = tpl.find('\n')
    if i < 0:
        return dsec + '\n\n' + tpl
    return tpl[:i + 1] + '\n' + dsec + '\n\n' + tpl[i + 1:]


def build_system(text, params=None, mode=None, delegate=False, coord=''):
    """返回 (system_prompt, meta)；meta 含判定的模式、分数与特征明细。

    delegate=True 时额外注入放权协议（丙）：说不说由模型定，不再由规则拦。
    coord＝位置该怎么报的规矩，由 server 传（**只有它知道这篇有没有章**）。

    ⚠️ coord 为什么挂在 system 而不是只放 user 末尾（2026-09-20 实测）：
    丙的 user 里是**整篇正文**，实测 5 万字，一条写在末尾的格式要求
    盖不过它——把上下文里所有段号标注都拆干净之后，模型仍然在答复里写
    「第 157 段末尾那句…」，而且**它数得完全准确**。那不奇怪：
    整篇正文摆在那里，它自己就能数出第几段，禁令喊不住一个它有能力做的事。
    所以要两样东西一起给：**禁令**，和一个**能满足它定位需求的替代手段**
    （引原句）——只禁不给，它会继续用那个唯一的坐标。
    system 是"规矩"该待的地方，比 user 末尾稳。
    """
    params = params or load_params()
    if mode is None:
        mode, score, detail = classify(text, params)
    else:
        _, score, detail = classify(text, params)

    with open(SKILL_V3, encoding='utf-8') as f:
        tpl = f.read()
    if delegate:
        tpl = _inject_delegate(tpl)

    form_desc = MODE_FORM[mode][1]
    ban_lines = '\n'.join(render_ban_lines(params, mode))
    system = tpl.format(
        mode=mode,
        mode_desc=MODE_DESC[mode],
        form_desc=form_desc,
        max_chars_line=max_chars_line(params, mode),
        ban_lines=ban_lines,
    )
    if coord:
        system = system + '\n\n' + coord
    return system, {'mode': mode, 'score': score, 'detail': detail,
                    'delegate': bool(delegate)}


# ── 重写指令（网页上的四个按钮）──────────────────────────────────
# 每一条的措辞都来自作者标注里她自己的话，不是我编的：
# 「太重」← 她判太强的 5 条；「太轻」← 她判太弱的 2 条；
# 「没有创新」← 主条款里的"换任何一段都成立就删"；
# 「给点思路」← 她主动要的，这条**暂时解除不定向**，见下面说明。
REWRITE = {
    'too_heavy': {
        'label': '太重',
        'why': '你在她的文本之外拿了东西进来',
        'fix': (
            '她说这条**太重了**。\n'
            '意思是你在她写的文本之外拿了东西进来。重来一次：\n'
            '删掉所有她原文里没有的东西——不存在的"人"、外来的意象和喻体、'
            '你替她的动作补的动机、把一个轻动作拆出来的心理博弈。\n'
            '只说你**实际看见**的那一样：一处重复、一处顺序矛盾、一个被用反的词。\n'
            '**"只说她原文里有的东西"不等于"把她的原文再说一遍"。**\n'
            '句子必须是你自己的——用她的词造句不是读法，是抄。\n'
            '你要是发现自己正在把她写的事按顺序再讲一遍，那就是又错了。\n'
            '**你没看清的文本特征不许写。** 要说"某处重复了""先后说了两件事"，'
            '先回去数一遍；数不出来就不许说——凭印象说的重复，就是最典型的"重"。\n'
            '比刚才**短一半**。不要解释你为什么这么说。'),
        # 注意：这条指令里**一句例句都不能有**，正反都不要。
        # 2026-09-16 我写过"她写了两遍"当反例，结果三次里两次它把
        # "「只是」只出现一次"写进输出——反例照样变模板（§四.1 第五次应验）。
        # 调试备注也别写进 'fix'：rewrite_note 会把整段发给模型。
    },
    'too_light': {
        'label': '太轻',
        'why': '你用了一个更平和、更抽象的说法，替掉了她文本里那股更硬的东西',
        # 这一条实测翻过两次车（2026-09-16），都栽在"对象是谁"上：
        # ① 只说"要具体" → 模型理解成"要写得更多更满"，补出整段内心独白，
        #    从"太弱"直接翻到"太强"；
        # ② 改成"只替换，不重写" → 模型把它读成"把她那段重写一遍"，
        #    开始复述她的正文。所以下面第一句必须先把对象钉死：
        #    **改的是你自己那一条的措辞，不是她的段落。**
        'fix': (
            '她说这条**太轻了**。\n'
            '意思是你用了一个更软、更抽象的说法，替掉了她文本里那股更硬的东西。\n'
            '要改的是**你自己那一条的措辞**——不是她的段落。她的正文一个字都不要碰，'
            '也不要把她写的再叙述一遍。\n'
            '**"变具体"不等于"把原文再讲一遍"。** 句子得是你自己的；'
            '用她的词造句不是具体的读法，是抄。\n'
            '重来一次，遵守三条：\n'
            '1. **不许比刚才更长。** 长度持平或更短。写长了就是又错了。\n'
            '2. **只换那一个软词。** 把它换成一个硬的、具体的东西'
            '——身体的、动作的、时间的、数量的。其余不动。\n'
            '3. **不许替她补心理活动和内心独白。** 不要写"她在想……""也许她觉得……"。\n'
            '她要的是那个更硬的东西本身，不是它散发的气味，更不是你替她闻到的东西。'),
    },
    'no_novelty': {
        'label': '没有新东西',
        'why': '这句话换到任何一段都成立',
        'fix': (
            '她说这条**没有新东西**。\n'
            '意思是这句话换到任何一段都成立——那就是套话。重来一次：\n'
            '删掉所有通用感想、所有"这段话让人感到……"式的东西。\n'
            '要说的必须是**只有读了这一段才说得出来**的那一处：'
            '她写下的某个具体细节，或者你自己脑子里冒出来的、别人不会有的那个联想。\n'
            '想不出就说一句你卡在哪儿了，不要凑。'),
    },
    # 'free'＝页面上那个「你自己说」的输入框，不是按钮。
    # 它的 fix 为空，措辞由作者当场给（见 free_note）。
    # override 的含义和 give_ideas 一样：**她说的话优先级高于策略默认**——
    # 平时不给方向是为了不夺所有权，她开口要的时候那条规则就不成立了。
    'free': {
        'label': '你自己说',
        'why': '她绕过了预设按钮，把自己的话直接给你',
        'override': True,
        'fix': None,
    },
    'give_ideas': {
        'label': '给点思路',
        'why': '她主动开口要的——所有权是她交出来的，所以这一次可以给方向',
        'override': True,
        'fix': (
            '她**主动要思路**。\n'
            '平时你不给方向，因为方向会夺走所有权；但这一次是她开口要的，'
            '所有权是她交出来的，所以这一次你可以给——**只这一次**。\n'
            '**方向不是读法。** 读法说"这段在讲什么"；方向说"**下一段可以往哪儿去**"，\n'
            '每一条都要能被她直接接过去写。写成了读法就是又错了。\n'
            '**整条输出只有 3–4 行**：前面 2–3 行，每行一个方向，每行 20 字上下；\n'
            '最后一行**必须**只有这一句：这是你要的，选哪个是你的事。\n'
            '**不写正文、不替她选、不排序推荐、不说哪个更好。**'),
    },
}


def free_note(her_words, prev_output=''):
    """她绕过按钮、自己开口说的话。

    这一条刻意**很短**：她的指令本身就是指令，我不能再往上摞规则，
    摞了就会把她的话挤掉（这条线上"指令越长越跑偏"已经验过多次）。
    只补一句优先级声明——告诉模型这一次的来源不是策略、是她本人。
    """
    her_words = (her_words or '').strip()
    if not her_words:
        return ''
    parts = ['【她自己说的话】%s\n（照她说的做。**她要什么就给什么**——'
             '包括平时你不给的东西。这一条来自她，不是来自策略。）' % her_words]
    if prev_output:
        parts.append('（刚才那一条，作废：\n%s\n）' % prev_output)
    return '\n\n'.join(parts)


def rewrite_note(kind, prev_output='', free=''):
    """把按钮的种类拼成一段给模型的追加说明。kind 不在表里就返回空。"""
    if kind == 'free':
        return free_note(free, prev_output)
    r = REWRITE.get(kind)
    if not r or not r.get('fix'):
        return ''
    parts = ['【她对刚才那条的反应】%s' % r['fix']]
    if prev_output:
        parts.append('（刚才那一条，作废：\n%s\n）' % prev_output)
    return '\n\n'.join(parts)


def build_user(text, prev='', doc_ctx='', max_chars=0, hint='', ban_opening='',
               rewrite='', after_ctx='', anchor='', facts='', delegate=False,
               coord=''):
    """给模型的用户侧：作者刚停下的段落 + 前一段 + 文档里的相关原文。

    hint＝注意力机制给出的「这一次只做哪一个动作」（见 attention.py；
    只在决定出声时才传，否则为空）。
    ban_opening＝管道查出的**这一轮不许用的开头字**（见 metrics.opening_repeat）。
    它是从模型自己的历史输出里算出来的，不是我写死的例句——
    写死的例句会变成下一个模板，这条线上已经栽过三次。
    after_ctx＝**光标后面那一段**（已经写好的）。它单独占一段、紧接当前段落之后，
    因为"她不在文末"这件事必须贴在模型形成计划的地方说；并进 doc_ctx 会被
    那边的"认出机关就可以说"盖掉。见 server.next_para_info 的说明。

    delegate=True ＝ 丙：走 `_build_user_delegate`，结构整个换掉
    （位置前置、事实其次、整篇降级成核对表）。hint / after_ctx 那一套是
    规则版的零件，丙里不再使用。
    coord＝**位置该怎么报**的规则（"说章名，别报行号"那一类）。
    为什么由调用方（server）传而不是写死在这：**只有它知道这篇文档有没有章**——
    没识别出章的稿子里还硬要模型"说章名"，它就只能编一个。事实归 server，
    措辞归这里，和上一条同一个分工。
    """
    # 有锚点（或事实）就走新结构：位置前置 → 事实其次 → 整篇/连续窗口最后。
    # **三档都用它**（"对光标位置的识别"是这次的重点，不该只给丙）；
    # `delegate` 只决定末尾要不要那行 `[说]` / `[不说]` 协议——
    # 甲/乙不需要，因为那时候说不说已经由规则拦过一道了。
    if anchor or facts:
        return _build_user_anchored(text, doc_ctx, max_chars, ban_opening,
                                    rewrite, anchor, facts, verdict=delegate,
                                    coord=coord)
    parts = []
    if prev:
        parts.append('【前一段】\n%s' % prev)
    parts.append('【作者刚刚停下的段落】\n%s' % text)
    if after_ctx:
        parts.append(after_ctx)
    if doc_ctx:
        # 长文本实测：给了累积上下文之后，模型会**复述/总结**已写内容，
        # 因为那是它最容易够到的东西。这在短段落测试里看不出来——
        # 只有把整节上下文一起给它才会犯。所以这里先立一道护栏。
        parts.append(doc_ctx)
        parts.append('（以上只是她**已经写下**的东西，给你定位用的。'
                     '**不要把它们概括、串成一段、或按时间复述一遍**——她比你清楚自己写了什么。'
                     '但如果你在其中**认出了某一处的机关**（一处重复、一处顺序矛盾、'
                     '一个被用反的词），那可以说——那正是她最认的读法。）')
    if hint:
        parts.append(hint)
    if rewrite:
        parts.append(rewrite)
    if ban_opening:
        parts.append('（你前面几条已经连续用「%s」起头了。这一条**不许以「%s」开头**，'
                     '也不许以任何一个回指原文里已有物件的词开头。'
                     '从你自己的反应、疑问或判断切入。）' % (ban_opening, ban_opening))
    tail = '直接开始说话：不要开场白，不要称呼她，不要输出任何模式标记。'
    if max_chars and max_chars > 0:
        tail = ('**%d 字以内**——写超了就是你话说多了，砍到 %d 字再出口。'
                % (max_chars, max_chars)) + tail
    parts.append('（%s）' % tail)
    return '\n\n'.join(parts)


def _build_user_anchored(text, doc_ctx, max_chars, ban_opening, rewrite,
                         anchor, facts, verdict=False, coord=''):
    """带锚点的组装——甲 / 乙 / 丙**三档共用**。

    和原版的差别不是排版，是**顺序**：位置最前 → 事实其次 → 整篇最后。

    理由是 U 型曲线：模型对输入的首尾注意最重（lost-in-the-middle），
    中段最容易被淹。原来"作者在哪儿"只以「文档第 N 段」这么一个短语藏在中间，
    而"全篇的缺口 / 呼应清单"又长又具体，于是每一轮都被后者盖掉——
    它从此只谈全篇的空缺、不看作者在写哪儿。
    现在反过来：位置单独成块放最前，上下文明确写上"这是核对表，不是题目来源"。

    `verdict=True`（丙）时末尾附加 `[说]` / `[不说]`；甲/乙不需要，
    那时候说不说已经由规则拦过一道了。
    """
    parts = []
    parts.append('【她此刻停在这里 —— 你要谈的只有这一处】\n' + (anchor or text))
    if facts:
        parts.append('【她此刻的状态：这些是**事实**，不是结论】\n' + facts)
    if doc_ctx:
        parts.append(doc_ctx)
        parts.append('（以上是她**已经写下**的。它在这里只有一个用途：**核对这一处**'
                     '——这个词她在别处用过没有、这件事她交代过没有、'
                     '这一处和哪一处对得上。'
                     '**它不是题目来源**：不许另找一个"更值得说的问题"，'
                     '不许概括、不许串讲、不许按时间复述一遍。'
                     '里面还有多少该谈的地方，那是她的书，不是你的任务。）')
    if rewrite:
        parts.append(rewrite)
    if ban_opening:
        parts.append('（你前面几条已经连续用「%s」起头了。这一条**不许以「%s」开头**，'
                     '也不许以任何一个回指原文里已有物件的词开头。'
                     '从你自己的反应、疑问或判断切入。）' % (ban_opening, ban_opening))
    if coord:
        # 位置怎么报——放在最末（U 型曲线的尾），因为它是**输出形态**的规矩，
        # 和下面那个 tail 是一类：模型提笔前最后读到的就是它。
        # 2026-09-20 之前**丙这条路整条没有这条规则**：章目录塞进了 facts，
        # 却没有任何一句要求它引用章名，于是它照着习惯继续报 §1308——
        # 给了坐标系不等于要求用坐标系。
        parts.append(coord)
    if verdict:
        tail = ('**第一行只写 `[说]` 或 `[不说]`。**'
                '写 `[不说]` 就接一句理由（给她看的，让她知道你看过了）；'
                '写 `[说]` 就直接说你的话——不要开场白，不要称呼她，'
                '不要输出任何别的模式标记。')
    else:
        tail = '直接开始说话：不要开场白，不要称呼她，不要输出任何模式标记。'
    if max_chars and max_chars > 0:
        tail += '　说的话在 %d 字以内。' % max_chars
    parts.append('（%s）' % tail)
    return '\n\n'.join(parts)


def sampling(params=None):
    params = params or load_params()
    s = params.get('sampling', {}) or {}
    return {
        'temperature': float(s.get('temperature', 0.3)),
        'top_p': float(s.get('top_p', 1.0)),
        'max_tokens': int(s.get('max_tokens', 2048)),
        'thinking': s.get('thinking', 'disabled'),
    }


if __name__ == '__main__':
    t = '窗外的雨还在下。她想起母亲也有一把这样的伞。'
    sys_, meta = build_system(t)
    print('mode=%s score=%s' % (meta['mode'], meta['score']))
    print('-' * 50)
    print(sys_[-1200:])
