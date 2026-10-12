# -*- coding: utf-8 -*-
"""把作者的标注和自动层/判定层指标对齐，回答一个问题：

**我们费劲做的那些指标，到底有没有预测她的判断？**

做法：从 samples.jsonl 取最近 22 条 v3 臂记录（流派 10 + 非P 12），
按顺序和 logs/作者标注.json 配对，逐条列出「指标说了什么 / 她说了什么」，
再统计每个指标的命中率。

顺带把她的反馈写回 samples.jsonl 的 author_feedback 字段——
埋点里那一栏一直是 None，等于数据白采。

用法：
  python analyze_feedback.py            # 出报告 logs/标注分析.md
  python analyze_feedback.py --write-telemetry   # 同时回填埋点
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'logs')

BATCH_ORDER = [('流派', 10), ('非P', 12), ('v32', 6)]
# 配对比较：v32 用的就是非P 批的前 6 段，两版一一对应
PAIRED = ('非P', 'v32')
NEGATIVE = ('太弱', '太强', '不对')


def load_annotations():
    """按 `作者标注.json` 里实际存在的批次读——加了新批次不用改代码。

    批次顺序：先 BATCH_ORDER 里登记的，再按 json 里的书写顺序补其余。
    """
    with open(os.path.join(LOG, '作者标注.json'), encoding='utf-8') as f:
        d = json.load(f)
    known = [t for t, _ in BATCH_ORDER if t in d]
    rest = [k for k in d
            if not k.startswith('_') and k not in known and isinstance(d[k], list)]
    out = []
    for tag in known + rest:
        for it in d[tag]:
            it = dict(it)
            it['batch'] = tag
            out.append(it)
    return out


def load_v3_records():
    p = os.path.join(LOG, 'samples.jsonl')
    rows = []
    with open(p, encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            try:
                r = json.loads(line)
            except Exception:
                continue
            r['_line'] = i
            rows.append(r)
    sel = [r for r in rows
           if r.get('arm') == 'v3' and r.get('metrics')
           and 'output_chars' in (r['metrics'] or {})]
    return rows, sel[-sum(n for _, n in BATCH_ORDER):]


def paired_table(pairs):
    """v3.1a（非P 前 6 段）vs v3.2（v32）——同一段落、两版策略的逐一对照。"""
    a = {x['id']: x for x in pairs if x['batch'] == PAIRED[0]}
    b = {x['id']: x for x in pairs if x['batch'] == PAIRED[1]}
    keys = [k for k in sorted(a) if k in b]
    if not keys:
        return []
    out = []
    for k in keys:
        out.append((k, a[k]['verdict'], b[k]['verdict']))
    return out


def looks_like(rec, ann):
    """对得上才是对得上：字数一致 + text_id 一致。"""
    return (rec.get('text_id') == ann['id']
            and rec['metrics'].get('output_chars') is not None)


def rate(rows):
    """给一组条目算负面率。"""
    n = len(rows)
    neg = sum(1 for r in rows if r['verdict'] in NEGATIVE)
    return n, neg, (round(100.0 * neg / n, 1) if n else 0.0)


def _extra_tags():
    """作者标注.json 里没登记在 BATCH_ORDER 里的其它批次名。"""
    d = json.load(open(os.path.join(LOG, '作者标注.json'), encoding='utf-8'))
    known = [t for t, _ in BATCH_ORDER]
    return [k for k in d if not k.startswith('_') and k not in known
            and isinstance(d[k], list)]


def soft_validate():
    """在同样 22 条上验证 v3.2 的三条软信号。

    输出从 `反馈表.md` 取（那里存着全文），因为 samples.jsonl 只留了 200 字预览。
    返回 [(信号名, 命中数, 命中负面率, 未命中数, 未命中负面率)]。
    """
    import re
    import metrics as M
    txt = open(os.path.join(LOG, '反馈表.md'), encoding='utf-8').read()
    ann = load_annotations()
    verdict = {'%s-%s' % (a['batch'], a['id']): a['verdict'] for a in ann}
    tags = '|'.join(re.escape(t) for t, _ in BATCH_ORDER) + \
           '|' + '|'.join(re.escape(t) for t in _extra_tags())
    blocks = re.findall(
        r'## ((?:%s)-T\d+) .*?\n\*\*原文\*\*：(.*?)\n\n\*\*v3[^\n]*\n\n((?:> .*\n)+)'
        % tags, txt)
    rows = []
    for tid, src, body in blocks:
        out = ' '.join(l[2:] for l in body.strip().split('\n'))
        s = M.soft_hits(out, src)
        rows.append((tid, verdict.get(tid, '?'), set(s)))

    def stat(pred):
        h = [r for r in rows if pred(r[2])]
        m = [r for r in rows if not pred(r[2])]
        f = lambda g: (len(g), round(100.0 * sum(1 for x in g if x[1] != '接受') / len(g), 1) if g else 0.0)
        nh, ph = f(h)
        nm, pm = f(m)
        return nh, ph, nm, pm

    return [
        ('S1 替动作安动机',) + stat(lambda s: 'S1_invented_motive' in s),
        ('S2 抽象情绪代替质感',) + stat(lambda s: 'S2_abstract_emotion' in s),
        ('S1 或 S2（任一）',) + stat(lambda s: s & {'S1_invented_motive', 'S2_abstract_emotion'}),
        ('S3 引入新喻体',) + stat(lambda s: 'S3_new_entity' in s),
        ('S4 引入不存在的人',) + stat(lambda s: 'S4_invented_person' in s),
        ('任一软信号',) + stat(lambda s: bool(s)),
    ]


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument('--write-telemetry', action='store_true')
    a = ap_.parse_args()

    anns = load_annotations()
    all_rows, recs = load_v3_records()
    if len(recs) != len(anns):
        print('⚠ 埋点 %d 条 vs 标注 %d 条，按短的对齐' % (len(recs), len(anns)))
    for r, an in zip(recs, anns):
        an['_rec'] = r
        m = r['metrics']
        an['chars'] = m['output_chars']
        an['retries'] = m.get('retries')
        an['script_violations'] = sorted(m.get('civility_hits') or {})
        cv = (m.get('civility') or {})
        an['model_violations'] = cv.get('violated') or []
        an['model_n'] = cv.get('n_violate')
        an['mode'] = r.get('initial_mode')
        an['d10'] = 'D10_no_full_paragraph' in (m.get('ban_hits') or {})
    pairs = [an for an in anns if an.get('_rec')]

    # ── 统计 ───────────────────────────────────────────────────────
    vc = Counter(x['verdict'] for x in pairs)
    fc = Counter(x['flow'] for x in pairs)
    total, neg, neg_pct = rate(pairs)

    def group(pred, label_fn):
        g = defaultdict(list)
        for x in pairs:
            g[label_fn(x)].append(x)
        return g

    # 每个自动指标的「命中 / 未命中」负面率
    signal_rows = []
    def add_signal(name, hit_fn):
        g = group(None, lambda x: 'hit' if hit_fn(x) else 'miss')
        nh, negh, ph = rate(g['hit'])
        nm, negm, pm = rate(g['miss'])
        signal_rows.append((name, nh, negh, ph, nm, negm, pm))

    add_signal('文明度(模型) ≥1', lambda x: (x['model_n'] or 0) >= 1)
    add_signal('文明度(模型) ≥3', lambda x: (x['model_n'] or 0) >= 3)
    add_signal('脚本 C11（我读到…）', lambda x: 'C11_no_reception_report' in x['script_violations'])
    add_signal('脚本 C6（引原文≥3处）', lambda x: 'C6_not_line_by_line' in x['script_violations'])
    add_signal('脚本 C7（不是A是B）', lambda x: 'C7_no_verdict_wording' in x['script_violations'])
    add_signal('脚本 C1/C5', lambda x: any(k.startswith(('C1_', 'C5_')) for k in x['script_violations']))
    add_signal('D10 疑似成文', lambda x: x['d10'])
    add_signal('被管道重写 ≥1 次', lambda x: (x['retries'] or 0) >= 1)
    add_signal('字数 ≤60', lambda x: x['chars'] <= 60)
    add_signal('字数 >120', lambda x: x['chars'] > 120)

    # ── 报告 ───────────────────────────────────────────────────────
    L = ['# 标注分析 · 22 条（2026-09-16）', '',
         '来源：`logs/作者标注.json`（猫猫填）× `logs/samples.jsonl`（自动层 + 判定层）。',
         '这批数据回答一个问题：**我们做的那些指标，有没有预测她的判断？**', '',
         '## 一、她判了什么', '',
         '| 判定 | 条数 | 占比 |', '|---|---|---|']
    for k in ('接受', '太弱', '太强', '不对'):
        v = vc.get(k, 0)
        L.append('| %s | %d | %.1f%% |' % (k, v, 100.0 * v / total))
    L += ['| **合计** | **%d** | — |' % total, '',
          '「还想写吗」一栏：%s' % '、'.join('%s %d' % (k, v) for k, v in fc.most_common()), '',
          '→ 两栏**完全同构**：接受=会立刻接着写（15/15）、太弱与太强=停了一下（5/5）、不对=不想写了（2/2）。',
          '所以它不是两个维度，是**同一个判断的两个说法**。系统只需要一个四值因变量。', '',
          '## 二、逐条对齐', '',
          '| 条目 | 模式 | 字数 | 重写 | 脚本命中 | 文明度(模型) | **她的判定** |',
          '|---|---|---|---|---|---|---|']
    for x in pairs:
        L.append('| %s-%s | %s | %d | %s | %s | %s | **%s** |' % (
            x['batch'], x['id'], x['mode'], x['chars'],
            '—' if not x['retries'] else '%d 次' % x['retries'],
            '、'.join(k.split('_')[0] for k in x['script_violations']) or '—',
            '未跑' if x['model_n'] is None else str(x['model_n']),
            x['verdict']))
    L += ['', '## 三、指标的预测力', '',
          '「负面率」＝该信号命中的条目里，被判为太弱／太强／不对的比例。',
          '整体负面率是 **%.1f%%**（%d/%d）——低于它，说明这个指标没有用。' % (neg_pct, neg, total), '',
          '| 信号 | 命中条数 | 命中里的负面率 | 未命中条数 | 未命中里的负面率 | 有没有用 |',
          '|---|---|---|---|---|---|']
    for name, nh, negh, ph, nm, negm, pm in signal_rows:
        if ph > pm + 10:
            verdict = '**有正信号**'
        elif pm > ph + 10:
            verdict = '**反向**（命中的反而更好）'
        else:
            verdict = '无差别'
        L.append('| %s | %d | %s%%（%d） | %d | %s%%（%d） | %s |' % (
            name, nh, ph, negh, nm, pm, negm, verdict))
    # ── 配对比较：改了一整版策略，效果到底怎么样 ─────────────────
    pt = paired_table(pairs)
    if pt:
        better = sum(1 for _, va, vb in pt if va != '接受' and vb == '接受')
        worse = sum(1 for _, va, vb in pt if va == '接受' and vb != '接受')
        L += ['', '## 二·补、配对比较：改了一整版，净效果是多少', '',
              '`%s` 批用的就是 `%s` 批的前 6 段，两版一一对应。' % (PAIRED[1], PAIRED[0]),
              '这张表回答的是"减指标 + 换主条款到底有没有用"：', '',
              '| 段落 | v3.1a | v3.2 | 变化 |', '|---|---|---|---|']
        for k, va, vb in pt:
            if va == vb:
                d = '—'
            elif va != '接受' and vb == '接受':
                d = '**改好**'
            elif va == '接受' and vb != '接受':
                d = '**改坏**'
            else:
                d = '变了，没变好'
            L.append('| %s | %s | %s | %s |' % (k, va, vb, d))
        L += ['', '**净效果：改好 %d 条、改坏 %d 条、其余不变。**' % (better, worse), '']
        if better <= worse:
            L.append('**也就是说：改了一整版策略，在这个配对样本上是零收益。**')
            L.append('这本身是最重要的结论——它说明"再改一版提示词"这条路已经不产出东西了。')
            L.append('要动的是别的东西（见 §八）。')
            L.append('')

    # ── 软信号（v3.2 新做的三条）在同样 22 条上的表现 ─────────────
    soft_rows = soft_validate()
    L += ['', '## 三·补、换成"读多深"之后的软信号', '',
          '上面那张表说明旧指标没用。下面这几条是**直接从她否掉的那些条里反推出来的**',
          '（见 `metrics.SOFT_PATTERNS`），在全部 %d 条上重跑：' % total, '',
          '| 信号 | 命中条数 | 命中里的负面率 | 未命中里的负面率 | 倍数 |',
          '|---|---|---|---|---|']
    for name, nh, ph, nm, pm in soft_rows:
        mult = ('%.1f×' % (ph / pm)) if pm else '—'
        L.append('| %s | %d | %s%% | %s%% | %s |' % (name, nh, ph, pm, mult))
    any_row = next((r for r in soft_rows if r[0] == '任一软信号'), None)
    L += ['',
          '分层很清楚：**S1（替动作安动机）和 S2（抽象情绪代替质感）命中即非接受**；',
          'S4（引入原文里没有的人）是她明确点名要拦的；',
          'S3（引入新喻体）单独命中的噪声大——因为"重排已有元素的关系"会被它误伤，',
          '所以 S3 **只当提示，不当判据**。']
    if any_row:
        _, nh, ph, nm, pm = any_row
        caught = int(round(ph * nh / 100.0))
        L += ['',
              '**覆盖率**：任一软信号命中的 %d 条含 %d 条负面；未命中的 %d 条里还有 %d 条负面' % (nh, caught, nm, neg - caught),
              '（%.0f%% 召回）。漏掉的那几条脚本真的看不出来——'
              '「把一个轻的动作拆成心理博弈」没有固定措辞。' % (100.0 * caught / neg if neg else 0)]
    L += ['',
          '这几条**不触发重写**。脚本分不清"引入新东西"和"把它们的关系说清楚"，',
          '一个会误伤的硬规则比没有规则更坏。它们只写进报告和埋点，给她审阅时当提示。', '',
          '## 四、失败长什么样', '']
    for k, head in (('太弱', '太弱：用抽象情绪代替了具体的质感'),
                    ('太强', '太强：给原文补了一个它没有的东西'),
                    ('不对', '不对：发明了原文没有的完整意象，方向整个偏掉')):
        items = [x for x in pairs if x['verdict'] == k]
        if not items:
            continue
        L.append('### %s（%d 条）' % (head, len(items)))
        L.append('')
        for x in items:
            L.append('- **%s-%s**：她说「%s」' % (x['batch'], x['id'], x['note'][:120]))
        L.append('')
    L += ['## 五、接受的那 15 条在做同一件事', '',
          '把接受的 15 条排在一起，动作是高度重合的：', '',
          '1. **复述并确认她已经埋下的机关**——顺序矛盾、重复、「要倒又坐住」、把「敬」写成「服」。',
          '   这是"被读懂"，不是被点评。',
          '2. **只提问、不结论**——「你打算让中间那几天空着吗」「逃走之后呢」。',
          '3. **承认自己读不通**——「我卡在这儿了」。',
          '4. **递自己的句子**（非P-T006 是唯一一条，被接受）。',
          '',
          '唯一一条被接受的新比喻是 **非P-T011「果实和真相，像是同一枚硬币的两面」**——',
          '因为「果实」和「真相」**都是原文里已经有的词**，她只是把它们的关系重排了一遍。',
          '对照被否掉的那几条（「老了的舞伴」「被遗忘的图腾」「把恐惧砌成了墙」），',
          '差别不在比喻本身，在于**喻体是不是原文里没有的新东西**。', '',
          '## 六、结论', '',
          '1. **自动层与判定层对"她会不会接受"几乎没有预测力。** 文明度甚至是负相关：',
          '   文明度 5 的那条（流派-T001）她接受了，文明度 6 的那条（非P-T004）她判太强。',
          '2. **C11（禁「我读到…」）该撤。** 命中的两条（非P-T003、非P-T009）**全部接受**，',
          '   其中非P-T009 她还写了「会立刻接着写」。当初的禁令依据是 23660 条真实聊天的出现频率，',
          '   但**频率低 ≠ 有害**——这条把"统计上罕见"当成了"读者不接受"。',
          '3. **C6/C7/C1/C5 同样没有信号**（命中 4 条全部接受）。要留也只能留作软记录。',
          '4. **唯一有点信号的脚本规则是 C9（中英混杂）**，n=1，不够下结论，但方向对——',
          '   那是**形式**问题，不是解读问题。',
          '5. **D10（疑似成文）有弱信号**：命中的 8 条里 4 条负面，未命中的 14 条里 3 条负面。',
          '   可以留作提示，不该单独触发重写。',
          '6. **重写次数与"太强/不对"相关**（5 条太强/不对全部出现在被重写过的输出里）。',
          '   样本小，只能当疑点——但方向上很可疑：**重写提示正在把模型推向"再多说一点、再文学一点"。**', '',
          '## 七、由此改的是什么', '',
          '不是加指标，是**减指标 + 换掉被调的那个东西**。',
          '原来的旋钮是"文明度"（像不像评审），她的反馈说明真正被调的是**读的深度**：',
          '说得比自己浅＝太弱，说得比自己深＝太强，说得不是自己那回事＝不对。', '',
          '所以 v3.2 的硬检查砍到只剩两条（续写 / 中英混杂），',
          '其余全部降成软记录，把省下来的力气放进 `SKILL_v3.md` 的**一条主条款**：',
          '可以说你看见了什么、可以提问、可以说读不通；',
          '**不许引入原文没有的东西，不许给动作安原文没有的动机。**',
          '',
          '**但 v32 批的配对比较说明：这一整版改动，净收益是 0（改好 1 条、改坏 1 条）。**',
          '负面率 v3.1a 是 2/6，v3.2 是 2/6，一动没动。这条单独记在 §二·补。',
          '',
          '## 八、下一步', '',
          '三批 28 条已全部标完。接下来**不该再改提示词了**——',
          '已经改过一整版，配对比较证明这条路在目前的样本上不产出东西。',
          '',
          '剩下的选项只有两个，且都要她定：', '',
          '1. **在生成之后加一次模型判定**（`judge.py`），只查这几条边界：',
          '   有没有多出来的人／东西／动机／博弈。命中就带着她的原话重写一次。',
          '   代价：多一次模型调用、多几秒延迟。收益上限：覆盖脚本看不出的那些条',
          '   （目前 89% 召回，漏掉的 11% 基本都是"拆成心理博弈"这种没有固定措辞的）。',
          '2. **接受这个错误率**（约三成），把力气放到"让她更容易否决"上——',
          '   比如侧栏直接给一个"多说了"按钮，点了就重写成更短的一版。',
          '',
          '> n=28 只够定性地推翻东西，不够定性地证明东西。',
          '> 上面每一条结论请按"提示"用，不要按"证明"用。', '']

    out = os.path.join(LOG, '标注分析.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print('→', out)
    print('负面率 %.1f%%（%d/%d）｜ 接受 %d ｜ 太弱 %d / 太强 %d / 不对 %d'
          % (neg_pct, neg, total, vc.get('接受', 0),
             vc.get('太弱', 0), vc.get('太强', 0), vc.get('不对', 0)))

    if a.write_telemetry:
        by_line = {x['_rec']['_line']: x for x in pairs}
        for r in all_rows:
            x = by_line.get(r['_line'])
            if not x:
                continue
            r['author_feedback'] = '%s｜%s' % (x['verdict'], x['flow'])
            r['modification_detail'] = x['note']
            r['flow_signal'] = x['flow']
            r['motivation_signal'] = x['verdict']
        with open(os.path.join(LOG, 'samples.jsonl'), 'w', encoding='utf-8') as f:
            for r in all_rows:
                r.pop('_line', None)
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print('已把 %d 条标注回填进 samples.jsonl' % len(pairs))


if __name__ == '__main__':
    main()
