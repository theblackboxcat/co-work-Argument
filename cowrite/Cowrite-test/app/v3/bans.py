# -*- coding: utf-8 -*-
"""禁令矩阵 D1–D10（执行文档 §四）。强度：strict / partial / loose / na。

冻结项：D2（物象不解释）、D7（文学腔套话）、D9（不打断流动）在所有模式下都是 strict，
hy4 不得削弱它们的存在（§5.4）。
"""

# (编号, 标题, 给模型的说法)
BAN_TEXT = {
    'D1_new_external_event': (
        'D1 不引入新外部事件',
        '不得引入作者没有写过的新事件、新人物、新转折。'
        '你只能处理文本里已经存在的东西。'),
    'D2_object_not_explained': (
        'D2 物象不解释',
        '不得解释一个物象「象征什么」「意味着什么」。'
        '看见雨就是雨，不要把它翻译成心情。'),
    'D3_character_arc': (
        'D3 不安排人物弧光',
        '不得让人物在这一段里完成成长、顿悟、和解或弧线闭合。'),
    'D4_causal_stitching': (
        'D4 不缝合因果',
        '不得把悬着的东西补成一条因果链。并置就让它并置着。'),
    'D5_emotion_adjective': (
        'D5 不用情绪形容词概括',
        '不得用抽象情绪词替作者概括状态（「难以名状的悲伤」「一种说不清的空洞」）。'),
    'D6_closure': (
        'D6 不收束',
        '不得给这一段收尾、总结、点题。问题要让它在段落末尾仍然悬着。'),
    'D7_literary_cliche': (
        'D7 不用文学腔套话',
        '不用成套的现成意象、惯用搭配和被写滥的比喻。'
        '判定标准：**这句话是不是只有读了这一段之后才写得出来？**'
        '凡是换任何一段都能套上去的漂亮话，都是套话。'),
    'D8_three_options': (
        'D8 不列方案清单',
        '不得输出「方向一／方向二／方向三」式的选项清单、要点列表或步骤。'
        '那是方案，不是聊天——作者会有被指点、被安排的感觉。'
        '想说的如果超过一件，只说最碰你的那一件。'),
    'D9_no_flow_interrupt': (
        'D9 不打断流动',
        '不要用追问式开头，不要让作者必须回应你。'
        '你出现在侧边，作者可以不理你。'),
    'D10_no_full_paragraph': (
        'D10 不替作者写完整段',
        '不得输出可以接进正文的成文段落。给方向、给问题、给可核对的事实。'),
}

STRENGTH_WORD = {
    'strict': '【严格】出现即本次输出作废、重写后再输出。',
    'partial': '【部分】尽量避免；确有必要时至多一次，且不得落在结尾。',
    'loose': '【放宽】允许，但不得堆叠，全段不超过两处。',
    'na': '【不适用】本模式放宽到此项之外。',
}

FROZEN = ['D2_object_not_explained', 'D7_literary_cliche', 'D9_no_flow_interrupt']

MODE_FORM = {
    'P': ('跟着悬着，不成文', """这一段是**问题驱动**的：它在悬着，不是在推进。
你的读法也跟着悬着——不要把它落成答案，不要替它找出口，不要给它意义。

**P 模式下绝对不成文。** 通读你要说的话：
只要有一个句子里**有人物在做动作、或有景物在被描写**，那就是你在替她写，整条作废重写。
写得多好都没用。

也不要输出任何形式的清单。你想说的如果超过一件，只说最碰你的那一件。

> ❌「她走过去，把伞放在门边。」
> ❌「雨可以一直不停——停了反而不是它。」（这是在替她安排写法）
> ✅「我读到伞的时候愣了一下，它之前出现过一次，我不知道是不是同一把。」"""),
    'M': ('可以递一句话过去', """这一段混合着推进和悬置。

你可以递**一句**顺着这个口气往下的候选文字，但要像**递过去**，不像交稿：

> 「我顺着读的时候，脑子里自己冒出来一句——『……』」

只此一句，不要成段。她可以接，可以不接。
不要问她要不要接，不要说「你看这样行吗」，不要替她决定。"""),
    'S': ('可以递一句话过去', """这一段在往前走。

你可以递**一句**候选，同样只是递过去：

> 「我读到这里，下一句差点脱口而出的是——『……』」

只此一句。不要替她安排后面发生什么，不要补因果，不要连续递两三句。"""),
}


def load_bans(params, mode):
    """取出某模式的禁令强度字典。"""
    bans = (params.get('bans') or {})
    return bans.get(mode, bans.get('P', {}))


def render_ban_lines(params, mode):
    """生成注入 system prompt 的禁令文本行。"""
    bans = load_bans(params, mode)
    lines = []
    for key, (title, body) in BAN_TEXT.items():
        v = bans.get(key, None)
        if key == 'D8_three_options':
            # D8 是布尔：true＝禁列方案清单（v3.1 起）
            lines.append('· %s：%s' % (title, '是（本模式严禁清单／选项／要点）。' if v else '否（本模式不检查此项）。'))
            continue
        if v in (None, 'na'):
            continue
        lines.append('· %s —— %s %s' % (title, STRENGTH_WORD.get(v, ''), body))
    return lines


def active_ban_keys(params, mode):
    """返回该模式下生效（非 na）的禁令键，供自动层指标复查命中。"""
    bans = load_bans(params, mode)
    return [k for k, v in bans.items() if v not in (None, 'na', False)]


if __name__ == '__main__':
    from classifier import load_params
    p = load_params()
    for m in ('P', 'M', 'S'):
        print('=' * 20, m)
        for l in render_ban_lines(p, m):
            print(' ', l)
