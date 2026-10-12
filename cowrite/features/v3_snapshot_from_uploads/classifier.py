# -*- coding: utf-8 -*-
"""v3 模式分类器（冷启动版，v3.2 起支持英文）。

七个特征各打 0–1 分，加权求和 → mode_score → P / M / S。

诚实声明：这是**词表启发式**，不是分词、不是句法分析、更不是语义模型。
它的唯一用途是给进化循环一个**可比较的粗糙起点**（执行文档 §2.1）。
真正的边界要靠 hy4 用作者的反馈把它拟合过去（§1.3）。

**为什么加了英文**：现代主义/后现代这批参照文本（伍尔夫、乔伊斯、惠特曼）
只有英文公有领域版。原来的中文词表在英文上是全零输入——
所有文本都会被判成「没有任何目标/因果/冲突」的极端 P，
这不是"它们是 P"，这是"词表瞎了"。加了英文词表之后，判定才有跨语言可比性。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# ── 中文词表 ────────────────────────────────────────────────────────
CAUSAL = ['因为', '所以', '于是', '结果', '因此', '从而', '导致', '致使', '为了',
          '既然', '由此', '难怪', '以至于', '这样一来']
TIME_DEIXIS = ['后来', '然后', '接着', '第二天', '那年', '那天', '三天后', '多年以后',
               '此刻', '之前', '之后', '当时', '从前', '终于有一天', '前一天', '那年夏天']
# 目标句只收显式措辞。不放宽到「要去…」这种歧义结构——
# 「说要去买酱油」会被误判成人物目标（实测教训）。
GOAL = ['决定', '打算', '必须', '非得', '一定要', '下定决心', '暗下决心',
        '目标是', '发誓', '立誓', '下决心', '务必', '不惜']
ACTION_VERB = ['走', '跑', '拿', '放', '推', '拉', '打', '追', '逃', '转身', '抬头',
               '低头', '进门', '出门', '站起', '坐下', '抓住', '松开', '扔', '翻', '敲']
SENSORY_VERB = ['看', '听', '闻', '摸', '望', '感觉', '听见', '看见', '注意到',
                '察觉', '隐约', '似乎', '像是', '仿佛']
CONFLICT = ['争', '吵', '打', '反对', '拒绝', '冲突', '对抗', '阻止', '逼', '威胁',
            '拦', '不让', '偏要', '拗', '决裂', '翻脸']
CLOSURE = ['终于', '从此', '再也不', '就这样', '明白了', '知道了', '原来如此',
           '总算', '到头来', '最终', '再没有']

# ── 英文词表（同样只收显式措辞）────────────────────────────────────
EN_CAUSAL = ['because', 'therefore', 'consequently', 'as a result', 'thus',
             'hence', 'since', 'in order to', 'so that', 'owing to']
EN_TIME_DEIXIS = ['then', 'afterwards', 'later', 'meanwhile', 'the next day',
                  'the day before', 'after a while', 'at that moment',
                  'some years later', 'once', 'years ago', 'by then',
                  'in the meantime', 'all at once', 'suddenly']
EN_GOAL = ['decided to', 'resolved to', 'determined to', 'made up his mind',
           'made up her mind', 'was resolved', 'vowed', 'set out to',
           'must go', 'had to go', 'was obliged', 'intended to', 'meant to']
EN_ACTION = ['walked', 'ran', 'took', 'put', 'pushed', 'pulled', 'opened',
             'closed', 'turned', 'rose', 'sat', 'stood', 'grasped', 'threw',
             'knocked', 'entered', 'climbed', 'stepped', 'hurried', 'lifted',
             'crossed', 'raised', 'dropped', 'flung', 'seized']
EN_SENSORY = ['looked', 'watched', 'listened', 'heard', 'felt', 'seemed',
              'smelt', 'smelled', 'noticed', 'perceived', 'glimpsed',
              'appeared', 'observed', 'wondered', 'as if', 'as though']
EN_CONFLICT = ['quarrel', 'argued', 'refused', 'opposed', 'struggled',
               'fought', 'threatened', 'resisted', 'insisted', 'angry',
               'contrary', 'conflict', 'forced', 'against him', 'against her']
EN_CLOSURE = ['at last', 'in the end', 'finally', 'never again', 'from then on',
              'at length', 'and so it was', 'there was no more', 'for the last time']

ASCII_RE = re.compile(r'[A-Za-z]')


def is_en(t):
    """粗略判语言：ASCII 字母占非空字符一半以上就算英文。"""
    if not t:
        return False
    body = re.sub(r'\s', '', t)
    if not body:
        return False
    return len(ASCII_RE.findall(body)) / len(body) > 0.5


def words_len(t):
    return len(re.findall(r"[A-Za-z']+", t))


# 繁→简：只收**本文件词表里实际用到的字**，不是完整字表。
# 为什么需要：维基文库的中文公版原文是繁体，而下面所有中文词表是简体的。
# 直接拿繁体文本去 count，"因为/于是/结果" 一个都命中不了——
# 那不是"这些文本没有因果"，是**词表对繁体瞎了**（和英文词表的老问题同源）。
# 试过让它转简体：MediaWiki 的 variant 参数对 action=parse 的正文**不生效**，
# 所以只能在这里补一张够用的映射表。
TRAD2SIM = {
    '為': '为', '於': '于', '結': '结', '從': '从', '導': '导', '難': '难',
    '這': '这', '樣': '样', '來': '来', '後': '后', '當': '当', '終': '终',
    '決': '决', '須': '须', '標': '标', '發': '发', '務': '务', '轉': '转',
    '頭': '头', '進': '进', '鬆': '松', '聽': '听', '聞': '闻', '覺': '觉',
    '隱': '隐', '約': '约', '爭': '争', '對': '对', '絕': '绝', '衝': '冲',
    '脅': '胁', '攔': '拦', '讓': '让', '臉': '脸', '總': '总', '沒': '没',
    '記': '记', '個': '个', '們': '们', '時': '时', '說': '说', '過': '过',
    '還': '还', '給': '给', '開': '开', '關': '关', '問': '问', '學': '学',
    '實': '实', '應': '应', '點': '点', '麼': '么', '會': '会', '裡': '里',
    '著': '着', '兒': '儿', '舊': '旧', '曆': '历', '氣': '气', '雲': '云',
}


def _simplify(text):
    return ''.join(TRAD2SIM.get(c, c) for c in text)


def _count_zh(text, words):
    """按简体口径计数：**先把文本折成简体再数**。

    繁体原文直接数简体词会全零，那会把"词表瞎了"误读成"文本没有这个特征"。
    """
    return sum(_simplify(text).count(w) for w in words)


def _count_en(text, phrases):
    n = 0
    for p in phrases:
        n += len(re.findall(r'\b' + re.escape(p) + r'\b', text, flags=re.I))
    return n


def _count(text, words):
    return _count_en(text, words) if is_en(text) else _count_zh(text, words)


def _sentences(text):
    if is_en(text):
        parts = re.split(r'(?<=[.!?])["\')\]]?\s+|\n+', text)
    else:
        parts = re.split(r'[。！？；!?;\n]+', text)
    return [p.strip() for p in parts if p.strip()]


def _n_units(text):
    """密度特征的基准单位：中文按 100 字，英文按 20 词（大约等长）。"""
    return max(1.0, words_len(text) / 20.0 if is_en(text) else len(text) / 100.0)


def _measure(text):
    """句长的度量单位：中文按字，英文按词。"""
    unit = (lambda s: words_len(s)) if is_en(text) else (lambda s: len(s))
    return unit


# ── 七个特征 ────────────────────────────────────────────────────────
def f_causal_density(t):
    words = EN_CAUSAL if is_en(t) else CAUSAL
    return min(1.0, _count(t, words) / _n_units(t) / 2.0)


def f_action_sensory_ratio(t):
    """动作动词占「动作+感官」之比。感官占优＝注视与迟疑，偏 P；动作占优＝偏 S。

    动词样本太少时不给结论（返回中性 0.5）——
    否则「全文没有一个感官动词」会被算成动作压倒性占优（实测教训）。
    """
    a = _count(t, EN_ACTION if is_en(t) else ACTION_VERB)
    s = _count(t, EN_SENSORY if is_en(t) else SENSORY_VERB)
    if a + s < 2:
        return 0.5
    return a / (a + s)


def f_goal_sentence(t):
    return min(1.0, _count(t, EN_GOAL if is_en(t) else GOAL) / 2.0)


def f_time_deixis(t):
    words = EN_TIME_DEIXIS if is_en(t) else TIME_DEIXIS
    return min(1.0, _count(t, words) / _n_units(t) / 2.0)


def f_sentence_length_var(t):
    """句长变异系数取反：变异越大越像现代主义句式（偏 P）。"""
    unit = _measure(t)
    ss = [unit(s) for s in _sentences(t)]
    if len(ss) < 2:
        return 0.5
    mean = sum(ss) / len(ss) or 1
    var = sum((x - mean) ** 2 for x in ss) / len(ss)
    cv = var ** 0.5 / mean
    return max(0.0, 1.0 - min(1.0, cv / 0.8))


def f_external_conflict(t):
    words = EN_CONFLICT if is_en(t) else CONFLICT
    return min(1.0, _count(t, words) / _n_units(t) / 2.0)


def f_closure_tendency(t):
    words = EN_CLOSURE if is_en(t) else CLOSURE
    ss = _sentences(t)
    tail = ss[-1] if ss else t[-40:]
    if _count(tail, words):
        return 1.0
    return 0.3 if _count(t, words) else 0.0


FEATURES = [
    ('causal_density', f_causal_density),
    ('action_sensory_ratio', f_action_sensory_ratio),
    ('goal_sentence', f_goal_sentence),
    ('time_deixis', f_time_deixis),
    ('sentence_length_var', f_sentence_length_var),
    ('external_conflict', f_external_conflict),
    ('closure_tendency', f_closure_tendency),
]


# ── 入口 ────────────────────────────────────────────────────────────
def load_params(path=None):
    p = path or os.path.join(HERE, 'params.json')
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def classify(text, params=None):
    """返回 (mode, score, 各特征明细)。"""
    params = params or load_params()
    cfg = params.get('classifier', {})
    weights = cfg.get('weights', {})
    thr = cfg.get('threshold', {}) or {}
    p_max = thr.get('P_max', 0.30)
    m_max = thr.get('M_max', 0.70)

    detail, total_w, score = {}, 0.0, 0.0
    for name, fn in FEATURES:
        v = max(0.0, min(1.0, fn(text)))
        w = float(weights.get(name, 0.0))
        detail[name] = round(v, 3)
        score += v * w
        total_w += w
    if total_w:
        score = score / total_w

    mode = 'P' if score < p_max else ('M' if score <= m_max else 'S')
    return mode, round(score, 3), detail


MODE_DESC = {
    'P': '问题驱动：悬置的张力，答案留在文本里，不落地',
    'M': '混合：情节在推进，但保持现代主义质感，不滑向商业腔',
    'S': '故事驱动：有目标、有因果、有时间线',
}

if __name__ == '__main__':
    import sys
    for sample in sys.argv[1:] or [
        '他决定去找她。因为他已经等了三天，终于忍不下去了。',
        'He decided to go to her. He had waited three days, and at last he could bear it no more.',
    ]:
        m, s, d = classify(sample)
        print('%s mode=%s score=%.3f  en=%s' % (sample[:34], m, s, is_en(sample)))
        for k, v in d.items():
            print('  %-22s %.3f' % (k, v))
