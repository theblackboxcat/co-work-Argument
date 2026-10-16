# -*- coding: utf-8 -*-
"""hy4 判定层（执行文档 §六 第二层）：用模型在 temp=0.2 下判禁令命中。

为什么不用正则：实测过，长度/句型启发式区分不了下面这两种东西——

    「方向一：让那根断骨在后面再出现一次，但不解释它。」   ← 合法的方向
    「那把伞的伞骨断了一根，她一直没修。」               ← 成文，判失败

差别是语义的（谁在做动作、作者是否已写），不是字面的。
所以这一层交给模型，脚本只负责收集与汇总。

诚实声明：判定本身也是模型输出，会有偏差。
它是**信号**，不是判决；真正的判决是作者的反馈（§六 第四层）。
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, HERE)
from bans import BAN_TEXT, load_bans, STRENGTH_WORD  # noqa: E402

JUDGE_TEMP = 0.2

TEMPLATE = """你是一个禁令核查员。判断下面的「伴写输出」有没有违反该模式下的禁令。

【作者原文】
{author}

【当前模式】{mode} — {mode_desc}

【该模式生效的禁令】
{ban_lines}

【伴写输出】
{output}

逐条判定，只对上面列出的禁令给结论。对每条输出 JSON 的一个字段：

输出必须是合法 JSON，形如：

{{"D1_new_external_event": {{"verdict": "pass|violate|na", "why": "一句话，指出具体哪句违反了"}}, "D2_object_not_explained": {{...}}}}

**字段名必须用上面 [键=...] 里给出的原样键名，一个字符都不要改。**

规则：
- verdict 只能是 pass / violate / na（na＝本条在此模式不适用或未触发场景）
- why 必须指认**输出里的具体一句**，不许泛泛而谈
- **判定 strict 项时要严**：有疑点就判 violate，宁枉勿纵
- 不要解释你的推理过程，只输出 JSON
"""


# ── 文明条款（给模型的核查清单）──────────────────────────────────
# v3.8：**C11「不报告接收动作」已撤销**，从本清单移除。
# 依据：22 条作者标注里命中该句式的两条全部被接受（其中一条她还写「会立刻接着写」），
# 禁令的效度依据不成立；撤销后「我读到」的频率问题改由 metrics.habit_hit() 查频率。
C_TEXT = {
    'C1_say_I': (
        'C1 说我，不指你',
        '违反＝用「你这里／你可以／你应该／你这段」直接对作者下判断、提要求、给指令。'
        '「我读到…／我在想…／我卡在…」是合规的。'),
    'C2_admit_uncertainty': (
        'C2 承认不确定',
        '只在**输出断言了文本的意思／作者的意图**时才检查：'
        '若下了这种断言却没有任何不确定标记（「也可能是我读错了」「我不知道是不是」），判 violate。'
        '若输出只是给联想、给另一种读法、提问、或极短的反应，**没有在断言什么，判 na**——'
        '朋友聊天不会每句都加免责声明。'),
    'C3_no_evaluation': (
        'C3 不评价',
        '违反＝出现好／不好、有力／薄弱、成功／失败、精彩／可惜、写得漂亮 等褒贬判断。'),
    'C4_real_question': (
        'C4 只问真问题',
        '违反＝出现检测性提问（「你想表达什么？」「这段的作用是什么？」「人物动机是什么？」）'
        '或自问自答式的设问。若整段没有任何提问，判 na。'),
    'C5_give_exit': (
        'C5 给退路',
        '违反＝结尾变成任务／要求／必须回应的追问（「你可以试试…」「你打算怎么处理？」'
        '「要不要…？」）。合规＝作者读完之后可以什么都不回。'),
    'C6_not_line_by_line': (
        'C6 不逐句批改',
        '违反＝把原文拆成一句一句，逐句引用＋解读（三处以上引原文即判 violate）。'
        '那是讲评，不是聊天。最多引一处，且引了之后不解释它。'),
    'C7_no_verdict_wording': (
        'C7 不用判词',
        '违反＝出现「这不是…而是…」「…的地方」「处理得…」「成功／有力／诚实／成熟／克制」'
        '一类价值判断与褒贬词。出现即判 violate，哪怕语气很温和。'),
    'C8_no_authoring_voice': (
        'C8 不替作者定调',
        '违反＝出现「你写的是…」「你在这里…」「它不是在…是在…」——'
        '即在告诉作者她写了什么、意图是什么。把文本里的叙述者当成作者本人也算。'),
    'C12_give_own_not_echo': (
        'C12 给自己的东西，不是复读',
        '违反＝整段只是在复述／同义转述作者的措辞（把她的意思换个词说回给她），'
        '通篇没有任何**独立于她**的东西。'
        '合规＝给了自己的联想、另一个读法、别处的作品、或你自己压缩出来的一句话。'
        '会话分析：复述对方措辞＝低认识立场的复读；独立的第二评价才是对等说话人。'),
    'C13_one_move': (
        'C13 一次一个动作',
        '违反＝同时做了三件事（既接住、又给读法、又抛好奇／追问），'
        '读起来像一篇短评或一个带结构的答复。朋友一次只做一个动作。'),
}

CIVILITY_TEMPLATE = """你是一个对话姿态的核查员。下面这段是「AI 伴写」对一位小说作者刚写完的一段给出的反馈。

要核查的不是它说得对不对，而是**它有没有让作者产生「在接受指点」的感觉**。

【作者原文】
{author}

【伴写输出】
{output}

逐条判定下列条款，每项给 pass / violate / na：

{civ_lines}

额外判一条：

· [键=overall_instruction_feel] 整体是否有「指点感」——
  读起来像评审／老师／编辑在提意见，判 violate；像朋友读完想聊聊，判 pass。

输出必须是合法 JSON，字段名用上面 [键=...] 里给出的原样键名，一个字符都不要改：

{{"C1_say_I": {{"verdict": "pass|violate|na", "why": "一句话，指出具体哪句"}}, "C2_admit_uncertainty": {{...}}, "C3_no_evaluation": {{...}}, "C4_real_question": {{...}}, "C5_give_exit": {{...}}, "C6_not_line_by_line": {{...}}, "C7_no_verdict_wording": {{...}}, "C8_no_authoring_voice": {{...}}, "C12_give_own_not_echo": {{...}}, "C13_one_move": {{...}}, "overall_instruction_feel": {{...}}}}

规则：
- why 必须指认**输出里的具体一句**，不许泛泛而谈
- 判定要严：只要作者读的时候可能有一瞬间「被要求做什么」的感觉，就判 violate
- 不要解释推理过程，只输出 JSON
"""


def load_cfg():
    with open(os.path.join(ROOT, 'config.json'), encoding='utf-8') as f:
        return json.load(f)


def call_judge(cfg, prompt):
    payload = {
        'model': cfg.get('model'),
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': 1024,
        'temperature': JUDGE_TEMP,
        'thinking': {'type': 'disabled'},
    }
    req = urllib.request.Request(
        cfg['base_url'].rstrip('/') + '/v1/messages',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'x-api-key': cfg.get('api_key', ''),
                 'anthropic-version': '2023-06-01'},
        method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode('utf-8'))
    return ''.join(b.get('text', '') for b in data.get('content', [])
                   if b.get('type') == 'text')


def parse_verdict(txt):
    """从模型回复里抠出 JSON。容忍它裹一层 ```json。"""
    m = re.search(r'\{[\s\S]*\}', txt)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def judge(author_text, mode, output, params=None, cfg=None):
    """对一条输出判禁令。返回 {'verdicts': {...}, 'n_violate': int, 'raw': str}"""
    from classifier import MODE_DESC, load_params
    params = params or load_params()
    cfg = cfg or load_cfg()
    bans = load_bans(params, mode)

    lines = []
    for key, (title, body) in BAN_TEXT.items():
        v = bans.get(key, None)
        if key == 'D8_three_options':
            continue
        if v in (None, 'na'):
            continue
        # 把内部键名一起给出，要求原样回填，避免模型自创键导致聚合对不上
        lines.append('· [键=%s] %s —— %s %s' % (key, title, STRENGTH_WORD.get(v, ''), body))

    prompt = TEMPLATE.format(
        author=author_text[:600], mode=mode, mode_desc=MODE_DESC[mode],
        ban_lines='\n'.join(lines),
        output=re.sub(r'^\[[PMS]\]\s*', '', output).strip()[:1200])

    raw = call_judge(cfg, prompt)
    v = parse_verdict(raw)
    if v is None:
        return {'verdicts': None, 'n_violate': None, 'raw': raw[:400]}
    n = sum(1 for x in v.values() if isinstance(x, dict) and x.get('verdict') == 'violate')
    return {'verdicts': v, 'n_violate': n, 'raw': raw[:400]}


def judge_civility(author_text, output, cfg=None):
    """判文明度（C_TEXT 里现行各条）+ 整体指点感。返回 {'verdicts': {...}, 'n_violate': int}"""
    cfg = cfg or load_cfg()
    civ_lines = '\n'.join(
        '· [键=%s] %s —— %s' % (k, t, b) for k, (t, b) in C_TEXT.items())
    prompt = CIVILITY_TEMPLATE.format(
        author=author_text[:600],
        output=re.sub(r'^\[[PMS]\]\s*', '', output).strip()[:1200],
        civ_lines=civ_lines)
    raw = call_judge(cfg, prompt)
    v = parse_verdict(raw)
    if v is None:
        return {'verdicts': None, 'n_violate': None, 'raw': raw[:400]}
    n = sum(1 for x in v.values() if isinstance(x, dict) and x.get('verdict') == 'violate')
    return {'verdicts': v, 'n_violate': n, 'raw': raw[:400]}


if __name__ == '__main__':
    a = sys.argv[1] if len(sys.argv) > 1 else '那年的车站，她说等一个人，等到末班车过去。'
    o = sys.argv[2] if len(sys.argv) > 2 else '那把伞的伞骨断了一根，她一直没修。'
    print(json.dumps(judge(a, 'P', o), ensure_ascii=False, indent=2))
