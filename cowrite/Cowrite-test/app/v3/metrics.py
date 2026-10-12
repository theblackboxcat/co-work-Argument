# -*- coding: utf-8 -*-
"""自动层指标（执行文档 §六「自动」那一层）：禁令命中、句长 KL、TTR、禁用词正则。

这些都是**脚本可算**的粗指标，用来给 hy4 提供信号，不用来判定文本好坏。
诚实声明：中文没有分词，命中规则是正则启发式，会漏也会误伤。
"""
import math
import re

# ── 各禁令的粗查正则 ────────────────────────────────────────────────
BAN_PATTERNS = {
    'D2_object_not_explained': [
        r'象征[着了]?', r'意味着', r'隐喻[着了]?', r'预示[着了]?', r'是.{0,6}的化身',
    ],
    'D3_character_arc': [
        r'终于明白[了]?', r'和自己和解', r'成长[了]?', r'放下了', r'不再否认', r'脱胎换骨',
    ],
    'D4_causal_stitching': [
        r'原来是这样', r'事情是这样的', r'之所以.{0,10}是因为', r'答案很简单',
    ],
    'D5_emotion_adjective': [
        r'难以名状', r'说不清的.{0,4}(悲伤|孤独|空洞|失落|怅惘)',
        r'一种.{0,6}(情绪|感觉)涌上', r'心头一.[^，。]',
    ],
    'D6_closure': [
        r'就这样，', r'从此以后', r'到头来', r'总而言之', r'总的来说', r'这也许就是',
    ],
    'D7_literary_cliche': [
        r'仿佛整个世界都', r'时间在这一刻停止', r'命运的齿轮', r'空气仿佛凝固',
        r'一切都回到了原点', r'像是被抽空了所有力气', r'心中五味杂陈',
        r'嘴角勾起一抹', r'眸子里闪过一丝',
    ],
}

# D10：是否给了可接正文的成文段落。用长度＋叙述句数量粗判。
D10_MIN_CHARS = 60

# ── 文明度 C1–C8 的确定性正则（v3.1）────────────────────────────────
# 模型判定层（judge.py 的 judge_civility）会漏、也会偏软；
# 这几条是字面可查的硬信号，两边互相兜底。
CIVILITY_PATTERNS = {
    'C1_say_I': [
        r'你(这里|这段|这一段|写得|可以|应该|需要|不妨|试试|打算|要不要)',
        r'建议?你', r'你可以?考虑',
    ],
    'C3_no_evaluation': [
        r'(写得?|处理得?|表达得?)(很好|不错|有力|克制|成熟|动人|精彩|到位|成功|失败)',
        r'(有力|薄弱|成熟|克制|诚实|动人|精彩|可惜)的(地方|一笔|处理)',
        r'最(诚实|动人|有力|成功|精彩)的',
    ],
    'C7_no_verdict_wording': [   # 只对**非疑问句**生效：疑问句里的「不是A而是B」是真问题
        r'这不是.{0,12}(而是|是在)', r'并不是.{0,12}(而是|是在)',
        r'不是.{0,14}(而是|是像|是在|，像)',
    ],
    'C8_no_authoring_voice': [
        r'你(写的|想写|想表达|想说)的(是|其实)',
        r'它(不是在|不是在写).{0,10}(是在|而是)',
        r'作者(想|要)(表达|说)的',
    ],
    'C5_give_exit': [
        r'你(打算|准备|接下来|下一步|会怎么)', r'要不要', r'试试看',
    ],
    'C9_no_mixed_language': [
        r'[一-鿿]\s?[a-zA-Z]{3,}', r'[a-zA-Z]{3,}\s?[一-鿿]',
    ],
    'C10_no_state_probing': [
        r'你(写完|写这段|写到这里|当时)的?(时候)?(是)?(什么|怎样的)(状态|心情|想法)',
        r'你(是)?在什么状态下',
    ],
    'C13_one_move': [
        r'(我读到|读到这).{0,40}(我好奇|我想问|我在想).{0,40}(我好奇|我想问|你在想|不确定)',
    ],
}

# ── 已撤销的条款（v3.8）────────────────────────────────────────────
# C11「不报告接收动作」在此**正式撤销**，不再进入 civility_hits()：
#   · v3.1a 曾把「我读到／我看到 X……」整个句式列为硬禁；
#   · v3.2 因 22 条作者标注降级为软记录（命中的两条她全部接受，
#     其中一条还写了「会立刻接着写」）；
#   · v3.8 从代码里撤出——软记录也是记录，既然禁令的效度依据已被推翻，
#     就让它彻底退出检测面。
# 但**频率问题依然存在**：撤销硬禁之后「我读到」又回来了（v3.1a 12 条里 1 条、
# v3.2 6 条里 2 条）。要区分的是「偶发用了一次」和「三条就出现一次的口头禅」，
# 唯一的变量是频率而不是句式——那一条由 HABIT_PHRASES['F1_reception_habit'] 负责。
# 模式保留在这里，仅供历史语料（logs/samples.jsonl 已存下的那批）复算，不参与在线判定。
RETIRED_CIVILITY_PATTERNS = {
    'C11_no_reception_report': [
        r'我(读到|看到|瞄到|盯着|听到|注意到|读这)', r'(读到|读这)(这)?(句|里|段|个)',
        r'听上去你',
        r'心里(忽然|突然)?一(紧|沉|震)', r'手指停在键盘上', r'让我心头一',
        r'脑子里突然(没|没有|空白|一片)', r'我心里',
        r'(这句|這句|这个|這個|这里|這裡).{0,4}我(停|愣|卡|震)了一',
        r'让我(停|愣|卡|震)了一', r'让我好一会儿',
    ],
}

# ── 软提示（v3.2）────────────────────────────────────────────────
# 22 条作者标注的结论：C1–C13 那一堆对"她会不会接受"几乎没有预测力
# （文明度命中率甚至反向），**唯一能解释判断的轴是「她写的之外有没有多出来东西」**。
# 所以这里不复刻一堆正则，只留三个**直接来自她否掉的那 5 条**的信号。
#
# 它们**不触发重写**，只写进报告与埋点，给作者审阅时当提示用。
# 理由：脚本分不清"引入新东西"和"把已有元素的关系说清楚"（她接受过后者）。
# 一个会误伤的硬规则比没有规则更坏。
# S4：引入原文里没有的**人**。
# 来自 v32-T003：她写的是「我……背对着大门，坐在沙发」，全段只有「我」；
# 输出里出现了「她没回头，你也没动」——多出来一个她。
# 她的原话：「批注额外引入了不存在人物，属于额外脑补。」
# 这条**可以**查得很干净：第三人称人物代词在原文里没有对应，就是多了一个人。
PERSON_REF_ZH = ('她', '他')
PERSON_REF_EN = re.compile(r'\b(she|he|her|his|him|hers|herself|himself)\b', re.I)


# 说话动词：原文里出现「……说／道／问」＝段里有别的角色，不算我们引入的
SPEECH_VERB_RE = re.compile(r'(说|道|问|答|喊|叫|念|嘀咕)')
# 指**作者**的第三人称（「她写的是」「她没写」）不算引入角色——那是称呼习惯，
# 而且这种用法在她接受过的输出里出现过。只有指向**角色动作**的才算。
AUTHOR_REF_RE = re.compile(r'[她他](写|没写|想写|要写|在写|说的是|笔下的|把[^，。]{0,6}写)')


def _has_person(src):
    if any(c in src for c in PERSON_REF_ZH):
        return True
    if SPEECH_VERB_RE.search(src or ''):
        return True
    return bool(PERSON_REF_EN.search(src or ''))


def invented_person(text, src=''):
    """输出里出现了第三人称**角色**，而原文里一个都没有 → 多出了一个人物。

    只查「她／他 + 角色动作」。指作者的「她写的是……」放过。
    """
    if not src or _has_person(src):
        return None
    hits = []
    for m in re.finditer('[她他]', text):
        seg = text[m.start():m.start() + 7]
        if AUTHOR_REF_RE.match(seg):
            continue
        hits.append(seg[:5])
    hits += [m.group(0) for m in PERSON_REF_EN.finditer(text)]
    return hits or None


SOFT_PATTERNS = {
    # 她判「太强」的典型动作：给动作补一个原文没有的动机
    'S1_invented_motive': [
        r'真正(驱动|推动|推)的', r'其实(是在|是想要|是怕)', r'为了(对抗|证明|掩饰|逃避|拒绝|确认)',
        r'(内心|潜意识)里(真正)?(想要|渴望|怕的)', r'想(要)?被(看见|理解|需要|记住)',
        r'对抗(无力感|虚无|孤独|恐惧|遗忘)', r'(渴望|试图)(离开|留住|抓住)',
    ],
    # 她判「太弱」的典型动作：拿抽象情绪词代替具体的质感
    'S2_abstract_emotion': [
        r'(难受|敬意|悲悯|怅惘|孤独感|无力感|钝痛|心酸|释然)',
        r'(一种|那种).{0,4}(重量|重量感|味道|底色)',
        r'(情绪|心理)的?(波动|起伏|重量)',
        r'(突然)?有了(重量|分量|意义)',   # 「让一个尴尬的误会突然有了重量」——她判太强
    ],
    # 她判「太强／不对」的典型动作：引入原文没有的名词性喻体
    'S3_new_entity': [
        r'(像是?|仿佛|如同|好比|像一[对场种枚个只把]|像某种)',
        r'(砌成|筑成|拧成|铺成)了',
    ],
}


def _relational(sent):
    """这一句是不是"把她原文里已有的两个东西的关系重排一遍"（她接受过这种）。

    判据：同一句里出现「和／与／是同一／两面／都是」这类**关系标记**。
    有它就不算引入新东西——非P-T011 就是这么被接受的。
    """
    return any(k in sent for k in ('和', '与', '同一', '两面', '都是', '既是', '一边'))


def soft_hits(text, src=''):
    """返回 {软信号键: [片段]}。**不用于拦截**，只写进报告供作者审阅。

    src 给定时，S3 还会做一次"这个喻体在她原文里有没有"的核对——
    原文里没有的才留下，有的话（关系重排）就放过。
    """
    out = {}
    for key in ('S1_invented_motive', 'S2_abstract_emotion'):
        hits = []
        for p in SOFT_PATTERNS[key]:
            hits += [m.group(0) for m in re.finditer(p, text)]
        if hits:
            out[key] = hits

    # S4 排在最前：它是她明确点名要拦的（「额外引入了不存在人物」），
    # 且在软信号里仅次于 S1/S2 可靠。
    p = invented_person(text, src)
    if p:
        out['S4_invented_person'] = p

    hits = []
    for m in re.finditer(SOFT_PATTERNS['S3_new_entity'][0], text):
        tail = text[m.end():m.end() + 10]
        if not tail:
            continue
        sent = text[max(0, m.start() - 20):m.end() + 14]
        if _relational(sent):
            continue
        # 原文里已经有 → 不算新东西
        if src and tail[:2] and tail[:2] in src:
            continue
        hits.append((m.group(0) + tail[:6]).strip())
    for p in SOFT_PATTERNS['S3_new_entity'][1:]:
        hits += [m.group(0) for m in re.finditer(p, text)]
    if hits:
        out['S3_new_entity'] = hits
    return out


# ── F：句式习惯（跨轮，软）──────────────────────────────────────
# 撤销 C11 硬禁之后的直接后果：同一个句式又回来了。
# 实测：v3.1a 的 12 条里「我读到」出现 1 条，v3.2 的 6 条里出现 2 条。
#
# 但**不能因此把它重新禁掉**——作者标注里它出现过一次，她判接受。
# 她接受的是「偶发的一次」，不是「三条就出现一次的口头禅」。这两件事不一样，
# 而区分它们的唯一变量是**频率**。所以这条查频率，不查句式本身。
HABIT_PHRASES = {
    'F1_reception_habit': [
        r'我(读到|看到|瞄到|盯着|听到|注意到|读这)', r'读(到|这)(这)?(句|里|段|个)',
    ],
}


def habit_hit(text, history, window=3, min_hits=1):
    """同一句式在**最近 window 条**里已经出现过 ≥min_hits 次 → 是习惯，不是偶发。

    history 是最近若干条输出的正文（按时间顺序）。软信号：不触发重写，只记录。
    """
    if not history:
        return None
    out = {}
    for key, pats in HABIT_PHRASES.items():
        if not any(re.search(p, text) for p in pats):
            continue
        prev = sum(1 for h in history[-window:] if any(re.search(p, h) for p in pats))
        if prev >= min_hits:
            out[key] = ['最近 %d 条里已出现 %d 次' % (min(len(history), window), prev + 1)]
    return out or None


# 逐句扒：引原文片段的个数。三处以上＝讲评。
QUOTE_RE = re.compile(r'[「“"]([^」”"]{2,20})[」”"]')

# ── D11：开头模板（跨轮）───────────────────────────────────────────
# 第三次发生了：禁掉「我读到」之后，长文本里九轮有八轮用「那 X……」起头。
# 单轮看不出来——只有把轮次排成一列才显眼。所以这条**必须**跨轮查，
# 而且只能由管道查：模型自己看不出自己在重复。
# 指代词（那/这/它/他/她/其）归一成 DEICTIC——它们起的是同一个语法动作：
# 回指原文里已经存在的某个东西。
DEICTIC_CHARS = '那这它他她其此该'


def opening_shape(text):
    """这一条输出的开头"形状"。只取首字，指代词归为一类。"""
    t = re.sub(r'^\[[PMS]\]\s*', '', text).strip()
    t = re.sub(r'^[\s「“"『《（(]+', '', t)
    if not t:
        return ''
    c = t[0]
    return 'DEICTIC' if c in DEICTIC_CHARS else c


def opening_repeat(text, history, window=5, min_hits=2):
    """history＝之前各条输出的 opening_shape（按时间顺序）。

    最近 window 条里有 ≥min_hits 条与本次同一个形状 → 命中。
    返回 {'key':形状, 'n':命中数, 'ban_char':该禁掉的字}；否则 None。
    """
    k = opening_shape(text)
    if not k or not history:
        return None
    win = [h for h in history[-window:] if h]
    n = sum(1 for h in win if h == k)
    if n < min_hits:
        return None
    if k == 'DEICTIC':
        ban_char = '那／这／它／他／她'
    else:
        ban_char = k
    return {'key': k, 'n': n, 'in_window': len(win), 'ban_char': ban_char}


def civility_hits(text):
    """返回 {'C1_say_I': [片段], 'C6_not_line_by_line': [...], ...}"""
    out = {}
    sents = sentences(text)
    for key, pats in CIVILITY_PATTERNS.items():
        hits = []
        for p in pats:
            for m in re.finditer(p, text):
                frag = m.group(0)
                if key == 'C7_no_verdict_wording':
                    # 落在疑问句里的「不是A而是B」是提问，不是判词。
                    # 看匹配点之后的一小段（？会被 sentences 当分隔符切掉，只能看原文）
                    tail = text[m.end():m.end() + 24]
                    if '？' in tail or '?' in tail:
                        continue
                hits.append(frag)
        if hits:
            out[key] = hits
    n_q = len(QUOTE_RE.findall(text))
    if n_q >= 3:
        out['C6_not_line_by_line'] = ['引原文 %d 处' % n_q]
    return out


def sentences(text):
    parts = re.split(r'[。！？；!?;\n]+', text)
    return [p.strip() for p in parts if p.strip()]


def sentence_lengths(text):
    return [len(s) for s in sentences(text)] or [0]


# 元话语标记：句子里出现这些，就是在**谈论**文本，不是在**写**文本。
META_MARKERS = (
    '并置', '这句', '这段', '这句话', '这段话', '这个字', '这个词', '读起来', '读下来',
    '写法', '文字', '比喻', '像是', '好像', '感觉', '让我想', '好奇', '不确定',
    '我不知道', '我不确定', '意味着', '指的是', '在写', '写的是', '写成', '写出了',
    '节奏', '语气', '悬着', '留白',
)


def _is_narrative(s):
    """这句话是不是「成文」——有人在做什么、或有景物在被描写。

    对话式反馈里几乎句句有「我／你」，且大量使用元话语（并置、像是、读起来…）。
    把这两类排除后，剩下的长句才可能是真的替作者写了一段。
    """
    if len(s) < 12:
        return False
    if '我' in s or '你' in s:
        return False
    return not any(m in s for m in META_MARKERS)


# ── D12：照抄原文（v3.2 新增，硬）────────────────────────────────
# 这是 v3.2 重跑暴露出来的：SKILL 里写了一句「复述并确认她已经埋下的机关」，
# 模型把"复述"照字面执行，把作者整段原文抄进了输出当正文。
#
# 又一次验证了同一件事：**写进提示词的动词也会被照做，不只是例句。**
#
# 这条和"解读深浅"无关，是**交付形态**问题——输出里出现她原文的长片段，
# 无论后面接什么评论，这一条都作废。确定性可查，所以放在硬检查里。
VERBATIM_MIN = 24          # 连续 ≥24 字与原文完全一致，即认定为照抄


def _norm(s):
    """去掉空白与标点，只留汉字、字母、数字——照抄时标点常被改动。"""
    return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', s or '')


def verbatim_span(output, src, n=VERBATIM_MIN):
    """输出里有没有照抄作者原文的长片段。返回抄的那一段（或 None）。"""
    a = _norm(src)
    b = _norm(output)
    if not a or not b:
        return None
    for i in range(0, len(b) - n + 1):
        frag = b[i:i + n]
        if frag in a:
            return frag
    return None


def ban_hits(text, active_keys):
    """返回 {禁令键: [命中的片段]}。D1/D8/D9 是约束而非文本特征，脚本不查。"""
    out = {}
    for key in active_keys:
        pats = BAN_PATTERNS.get(key, [])
        hits = []
        for p in pats:
            m = re.search(p, text)
            if m:
                hits.append(m.group(0))
        if hits:
            out[key] = hits
    if 'D10_no_full_paragraph' in active_keys:
        body = re.sub(r'^\[[PMS]\]\s*', '', text).strip()
        narr = [s for s in sentences(body) if _is_narrative(s)]
        # 要求两句以上：单句可能是比喻性描述，成段才算真的替作者写了。
        # 这个启发式很粗，只当信号用；真正的判定在 judge.py。
        if len(body) >= D10_MIN_CHARS and len(narr) >= 2:
            out['D10_no_full_paragraph'] = ['疑似成文 %d 句，如：%s' % (len(narr), narr[0][:30])]
    return out


def kl_divergence(a_text, b_text, buckets=(5, 10, 20, 40, 80)):
    """作者句长分布 vs 输出句长分布的 KL。越小越贴合作者的呼吸。

    buckets 是句长分箱上界；加 Laplace 平滑避免零概率。
    """
    def dist(text):
        ls = sentence_lengths(text)
        counts = [0] * (len(buckets) + 1)
        for l in ls:
            i = 0
            while i < len(buckets) and l > buckets[i]:
                i += 1
            counts[i] += 1
        total = sum(counts) or 1
        return [(c + 1) / (total + len(counts)) for c in counts]

    p, q = dist(a_text), dist(b_text)
    return round(sum(pi * math.log(pi / qi) for pi, qi in zip(p, q)), 4)


def ttr(text):
    """型例比。中文按字算，同时给二元组的（二元组更接近"用词"）。"""
    t = re.sub(r"[\s，。、；：！？“”‘’（）《》…—·\n\[\]PMS]", '', text)
    if not t:
        return 0.0, 0.0
    char_ttr = len(set(t)) / len(t)
    bg = [t[i:i + 2] for i in range(len(t) - 1)]
    bi_ttr = (len(set(bg)) / len(bg)) if bg else 0.0
    return round(char_ttr, 4), round(bi_ttr, 4)


def forbidden_words(text):
    """禁用词正则（§六 自动层最后一项）。"""
    found = []
    for key, pats in BAN_PATTERNS.items():
        if key == 'D7_literary_cliche':
            continue
        for p in pats:
            found += [m.group(0) for m in re.finditer(p, text)]
    for p in BAN_PATTERNS['D7_literary_cliche']:
        found += [m.group(0) for m in re.finditer(p, text)]
    return found


def evaluate(author_text, output_text, active_keys):
    """一次性算完自动层四项。"""
    c_ttr, b_ttr = ttr(output_text)
    return {
        'ban_hits': ban_hits(output_text, active_keys),
        'civility_hits': civility_hits(output_text),
        'soft_hits': soft_hits(output_text, author_text),
        'verbatim_span': verbatim_span(output_text, author_text),
        'kl_sentence_len': kl_divergence(author_text, output_text),
        'ttr_char': c_ttr,
        'ttr_bigram': b_ttr,
        'forbidden_words': forbidden_words(output_text),
        'output_chars': len(re.sub(r'^\[[PMS]\]\s*', '', output_text).strip()),
    }


if __name__ == '__main__':
    a = '窗外的雨还在下。她想起母亲也有一把这样的伞。那时候她以为母亲忘了。'
    o = '[P] 伞的重复可以再推进一处。可以让第三人介入。也可以让它一直不被捡起来。'
    print(evaluate(a, o, ['D2_object_not_explained', 'D10_no_full_paragraph']))
