# -*- coding: utf-8 -*-
"""冷启动对照 runner（执行文档 §八）。

第 1 步：基线跑 20 条 —— 用**当前 skill**（非定向，绝不生成正文）。
第 2 步：注入 v3 跑 20 条 —— 用 P/M/S 模式 + 禁令矩阵 + 新的输出形态。
两边同一批段落、同一个模型、同一套采样参数，唯一变量是策略。

跑完产出：
  v3/logs/samples.jsonl   埋点
  v3/logs/反馈表.md        给作者标「接受/太弱/太强/不对 + 还想不想写」
  v3/logs/对照报告.md      自动层指标的并排对比

用法：
  python runner.py                 # 跑默认 20 条
  python runner.py --limit 6       # 先跑 6 条看效果
  python runner.py --dry           # 不调模型，只打印 prompt（检查/离线）
  python runner.py --arm v3        # 只跑 v3
  python runner.py --corpus corpus_流派非P --tag 流派 --desc "现代主义/后现代公有领域"
         # 分批跑：每批在 logs/ 留一份 反馈表_<tag>.md，并自动并进总表
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORPUS_DIR = os.path.join(ROOT, 'corpus')
LOG_DIR = os.path.join(HERE, 'logs')

sys.path.insert(0, HERE)
from classifier import classify, load_params, MODE_DESC  # noqa: E402
from policy import build_system, build_user, sampling  # noqa: E402
from bans import active_ban_keys  # noqa: E402
import metrics as M  # noqa: E402
import telemetry as T  # noqa: E402

ALL_BAN_KEYS = list(M.BAN_PATTERNS.keys()) + ['D10_no_full_paragraph']

# 管道层拦截：这几条是**确定性可查**的，不该指望提示词压住。
# 提示词里写反例反而会把用例勾出来（v3.0 的 D7 就栽过一次），
# 所以这里改用「生成 → 正则查 → 带修正说明重写」的循环。
# v3.2：22 条作者标注说明 C1–C13 那一堆对"她会不会接受"几乎没有预测力
# （C11/C6/C7/C1/C5 命中即接受，文明度甚至反向），所以硬拦截只留一条：
# C9 是**形式**问题，不是解读问题——唯一一条命中了负面判定的规则。
# v3.8：C11 连"软记录"也一并撤出（见 metrics.RETIRED_CIVILITY_PATTERNS）。
HARD_CIVILITY = [
    'C9_no_mixed_language',
]
FIXNOTE = {
    'C9_no_mixed_language': '中文里不要夹带英文单词。',
    'D12_verbatim_copy': '你把她原文抄进来了。不要引超过一处，也不要把她写的句子整段搬出来——'
                         '你要说的是你自己的话。',
}
MAX_RETRY = 2


# ── 语料 ────────────────────────────────────────────────────────────
# 副文本（paratext）过滤。2026-09-16 加，起因见下。
#
# 跑「私有批」时抓到的：每章的**第 0 段**恰好是版权页／作者简介。
# 于是系统把一行版权声明 `ThiseditionarrangedwithROGERS,COLERIDGE&…`
# 当成正文读，还给它编了一段文学解读；把李昂的百科小传读成"你这段写得挺全，
# 但像简历"。这不是模型的问题，是**输入的问题**——
# 而它从没被发现，是因为前面的语料（公版小说）正文干净，
# 只有从 epub 抽出来的书才带这些书前书后的页。
#
# 两条一起改：
#   ① 抽到的段落先过一次副文本判据；
#   ② 等距抽样改成**从半格开始**（int((i+0.5)*step)），
#      不再每次都咬住 index 0——那正是书前页最密的地方。
PARATEXT = re.compile(
    r'ISBN|ISBN-13|版权所有|图书在版|出版发行|CIP\s*数据|定价|印张|开本|书号'
    r'|arranged\s*with|arrangedwith|All rights reserved|Copyright|Printed in'
    r'|作者简介|生于\s*(19|20)\d{2}|出生于\s*(19|20)\d{2}'
    r'|（(19|20)\d{2}\s*[—\-－]'
    r'|^\s*[A-Za-z0-9&.,()\-\s]{25,}$'      # 整段是一串没有中文的版权字串
)
# 注意这里**没有**收「原名／笔名／小说集」这类词：它们在正文里也会出现
# （格非正文里有「…接过读者们递过来的小说集，写下自己的笔名…」，实测被误杀过）。
# 判副文本要的是**确定性证据**（年份区间、图书在版编目、无中文的版权串），
# 不是"像不像简介"。宁漏不误杀——漏掉一段副文本只脏一条样本，
# 误杀一段正文就是把它从她的谱系里删掉。


def is_paratext(p):
    return bool(PARATEXT.search(p))


def load_segments(limit=20, per_file=0):
    """从 corpus/ 读所有 .txt/.md，按空行切段，返回 (text_id, text, prev)。

    per_file > 0 时：每个文件**等距抽** N 段（长章短章一视同仁），
    避免"前 20 段"全被第一个文件吃掉。冷启动要的是覆盖，不是顺序。
    """
    if not os.path.isdir(CORPUS_DIR):
        return [], '没有语料目录：%s' % CORPUS_DIR
    files = sorted(f for f in os.listdir(CORPUS_DIR)
                   if f.lower().endswith(('.txt', '.md', '.markdown'))
                   and not f.startswith(('_', 'README', 'readme')))
    if not files:
        return [], '语料目录是空的：%s（把目标质感范文放进来，.txt 或 .md）' % CORPUS_DIR

    segs = []
    for name in files:
        raw_lines = []
        with open(os.path.join(CORPUS_DIR, name), encoding='utf-8') as f:
            for line in f:
                # 去掉标题与引用行——那是说明文字，不是正文
                if line.lstrip().startswith(('#', '>', '<!--')):
                    continue
                raw_lines.append(line)
        raw = '\n'.join(raw_lines)
        paras, prev = [], ''
        for p in re.split(r'\n\s*\n', raw):
            p = p.strip()
            if len(p) < 20:          # 太短的不算一段
                continue
            if is_paratext(p):       # 版权页／作者简介不是正文，见上面的说明
                continue
            paras.append((p, prev))
            prev = p

        # per_file：每章等距抽 N 段，长章短章一视同仁
        # 从半格开始（i+0.5），别咬 index 0——书前页就在那儿。
        if per_file > 0 and len(paras) > per_file:
            step = len(paras) / float(per_file)
            paras = [paras[int((i + 0.5) * step)] for i in range(per_file)]

        for p, pv in paras:
            segs.append(('T%03d' % (len(segs) + 1), p, pv))
        if per_file == 0 and len(segs) >= limit:
            break
    return (segs if per_file else segs[:limit]), None


# ── 模型 ────────────────────────────────────────────────────────────
def load_cfg():
    with open(os.path.join(ROOT, 'config.json'), encoding='utf-8') as f:
        return json.load(f)


def call_model(cfg, system, user, samp):
    payload = {
        'model': cfg.get('model'),
        'messages': [{'role': 'user', 'content': user}],
        'system': system,
        'max_tokens': int(samp.get('max_tokens', 2048)),
        'temperature': float(samp.get('temperature', 0.3)),
    }
    if 'top_p' in samp:
        payload['top_p'] = samp['top_p']
    if str(samp.get('thinking', 'disabled')).lower() != 'enabled':
        payload['thinking'] = {'type': 'disabled'}
    req = urllib.request.Request(
        cfg['base_url'].rstrip('/') + '/v1/messages',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'x-api-key': cfg.get('api_key', ''),
                 'anthropic-version': '2023-06-01'},
        method='POST')
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode('utf-8'))
    txt = ''.join(b.get('text', '') for b in data.get('content', [])
                  if b.get('type') == 'text')
    if not txt.strip():
        return '⊘ 模型没有给出正文（stop=%s）' % data.get('stop_reason'), None
    return txt, data.get('stop_reason')


# 跨样本的开头形状史：模板只在序列里显形，单条看不出来。
# 只在 v3 臂上记（baseline 是给对照用的，不该被我们的管道修）。
OPEN_HISTORY = []
# 最近几条的正文，用来查「句式习惯」（偶发 vs 口头禅，见 metrics.habit_hit）
RECENT_OUTPUTS = []


# ── 两条臂 ──────────────────────────────────────────────────────────
def baseline_prompt():
    with open(os.path.join(ROOT, 'SKILL.md'), encoding='utf-8') as f:
        skill = f.read()
    with open(os.path.join(ROOT, 'WORKFLOW.md'), encoding='utf-8') as f:
        wf = f.read()
    return skill + '\n\n---\n\n' + wf


def run_one(cfg, seg, params, arm, dry=False, use_judge=False, use_civility=False):
    tid, text, prev = seg
    mode, score, detail = classify(text, params)
    if arm == 'baseline':
        system = baseline_prompt()
        rules = 'baseline(非定向·绝不生成正文)'
        keys = ALL_BAN_KEYS
    else:
        system, meta = build_system(text, params)
        mode = meta['mode']
        rules = '%s-%s' % (mode, 'strict' if mode == 'P' else 'mixed')
        keys = active_ban_keys(params, mode)

    cap = 0 if arm == 'baseline' else int(
        (params.get('policy', {}).get(mode, {}) or {}).get('max_chars', 0) or 0)
    user = build_user(text, prev, max_chars=cap)
    samp = sampling(params)

    retries = 0
    ban_open = ''
    if dry:
        out, stop = '(dry run，未调模型)', None
    else:
        out, stop = call_model(cfg, system, user, samp)
        # 管道层拦截：硬违规就带着修正说明重写（最多 MAX_RETRY 次）
        for _ in range(MAX_RETRY):
            bad = [k for k in HARD_CIVILITY if k in M.civility_hits(out)]
            if arm != 'baseline' and M.verbatim_span(out, text):
                bad = bad + ['D12_verbatim_copy']
            rep = M.opening_repeat(out, OPEN_HISTORY) if arm != 'baseline' else None
            if not bad and not rep:
                break
            retries += 1
            if rep:
                ban_open = rep['ban_char']
            fix = '；'.join(FIXNOTE[k] for k in bad)
            if ban_open:
                fix = (fix + '；' if fix else '') + '开头不许用「%s」' % ban_open
            if arm != 'baseline':
                user = build_user(text, prev, max_chars=cap, ban_opening=ban_open)
            user = user + '\n\n（上一条作废，重写。%s）' % fix
            out, stop = call_model(cfg, system, user, samp)
    if arm != 'baseline':
        # 句式习惯要在**加入本条之前**查，否则自己和自己比
        habit = M.habit_hit(out, RECENT_OUTPUTS)
        OPEN_HISTORY.append(M.opening_shape(out))
        RECENT_OUTPUTS.append(out)
        del RECENT_OUTPUTS[:-40]
    else:
        habit = None

    m = M.evaluate(text, out, keys)
    m['retries'] = retries
    if habit:
        m['habit_hits'] = habit

    # hy4 判定层（§六 第二层）：脚本正则区分不了「方向」和「成文」，交给模型判
    if use_judge and not dry:
        try:
            import judge as J
            verdict = J.judge(text, mode, out, params, cfg)
            m['hy4_judge'] = {
                'n_violate': verdict.get('n_violate'),
                'violated': [k for k, v in (verdict.get('verdicts') or {}).items()
                             if isinstance(v, dict) and v.get('verdict') == 'violate'],
            }
        except Exception as e:
            m['hy4_judge'] = {'error': str(e)}

    # 文明度判定（v3.1）：这条输出有没有「指点感」
    if use_civility and not dry:
        try:
            import judge as J
            cv = J.judge_civility(text, out, cfg)
            m['civility'] = {
                'n_violate': cv.get('n_violate'),
                'violated': [k for k, v in (cv.get('verdicts') or {}).items()
                             if isinstance(v, dict) and v.get('verdict') == 'violate'],
            }
        except Exception as e:
            m['civility'] = {'error': str(e)}

    if dry:
        # --dry 是拿来检查 prompt 的，不该污染埋点、更不该覆盖真结果。
        # （已经踩过一次：干跑把合并好的反馈表和对照报告一起冲掉了。）
        return {
            'text_id': tid, 'text': text, 'mode': mode, 'score': score,
            'rules': rules, 'output': out, 'metrics': m, 'stop': stop,
            'system_chars': len(system), 'dry': True,
        }

    T.record({
        'text_id': tid,
        'arm': arm,
        'initial_mode': mode,
        'mode_score': score,
        'rules_applied': rules,
        'metrics': m,
        'output_preview': out[:200],
        'feature_detail': detail,
    })
    return {
        'text_id': tid, 'text': text, 'mode': mode, 'score': score,
        'rules': rules, 'output': out, 'metrics': m, 'stop': stop,
        'system_chars': len(system),
    }


# ── 报告 ────────────────────────────────────────────────────────────
def write_reports(results, params, tag=None, desc=''):
    os.makedirs(LOG_DIR, exist_ok=True)
    by_tid = {}
    for r in results:
        by_tid.setdefault(r['text_id'], {})[r['arm'] if 'arm' in r else 'baseline'] = r

    # 反馈表：给作者标
    lines = ['# 反馈表 · v3 冷启动第 3 步（请作者标）', '',
             '每行填两栏：**反馈**（接受 / 太弱 / 太强 / 不对）'
             '、**还想写吗**（会立刻接着写 / 停了一下 / 不想写了）。',
             '空着也行——空着本身就是数据。', '',
             '> 填完把这个文件发我，或直接在对话里说 T00x 怎么样。', '']
    for tid, pair in by_tid.items():
        b = pair.get('baseline', {})
        v = pair.get('v3', {})
        mode = (v or b).get('mode', '-')
        lines.append('## %s ｜ 判定模式 %s（分数 %s）' % (tid, mode, (v or b).get('score', '-')))
        src = (v or b).get('text', '')
        lines.append('**原文**：%s' % (src[:160] + ('…' if len(src) > 160 else '')))
        lines.append('')
        for arm, key in (('基线（当前 skill）', 'baseline'), ('v3（模式+禁令）', 'v3')):
            r = pair.get(key)
            if not r:
                continue
            lines.append('**%s** ｜ %s ｜ %d 字' % (
                arm, r.get('rules', '-'), r['metrics']['output_chars']))
            lines.append('')
            lines.append('> %s' % r['output'].replace('\n', '\n> '))
            lines.append('')
            ch = r['metrics'].get('civility_hits') or {}
            if ch:
                lines.append('痕迹检查（软）：%s' % '；'.join(
                    '%s（%s）' % (k.split('_')[0], '、'.join(v))
                    for k, v in ch.items()))
                lines.append('')
            vb = r['metrics'].get('verbatim_span')
            if vb:
                lines.append('**照抄原文**：与原文连续重合 ≥24 字（「%s…」）' % vb[:16])
                lines.append('')
            hb = r['metrics'].get('habit_hits') or {}
            if hb:
                lines.append('**句式成了习惯**：%s' % '；'.join(
                    '%s（%s）' % (k.split('_')[0], '、'.join(v)) for k, v in hb.items()))
                lines.append('')
            sh = r['metrics'].get('soft_hits') or {}
            if sh:
                # 这三条是从作者标注里反推的，命中率高得多——放在审阅时最显眼的位置
                lines.append('**可能判太强／太弱**：%s' % '；'.join(
                    '%s（%s）' % (k.split('_')[0], '、'.join(v))
                    for k, v in sh.items()))
                lines.append('')
            lines.append('反馈：＿＿＿＿＿　还想写吗：＿＿＿＿＿　改了什么：＿＿＿＿＿')
            lines.append('')
        lines.append('---')
        lines.append('')
    stamp = time.strftime('%m-%d %H:%M')
    if tag:
        # 每批单独留一份，再由 merge_feedback.py 并成总表——
        # 不然跑第二批会把第一批覆盖掉（已经发生过一次）。
        bp = os.path.join(LOG_DIR, '反馈表_%s.md' % tag)
        with open(bp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(
                ['# 批次 %s ｜ %s ｜ %s' % (tag, desc or '', stamp), '']
                + lines[1:]))
        idx = os.path.join(LOG_DIR, '_批次.json')
        items = []
        if os.path.isfile(idx):
            with open(idx, encoding='utf-8') as f:
                items = json.load(f)
        items = [x for x in items if x.get('tag') != tag]
        items.append({'tag': tag, 'desc': desc or tag,
                      'n': len(by_tid), 'ts': stamp})
        with open(idx, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        try:
            import merge_feedback
            os.chdir(HERE)
            merge_feedback.merge()
        except Exception as e:
            print('（合并总表失败：%s）' % e)
    else:
        with open(os.path.join(LOG_DIR, '反馈表.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    # 对照报告：自动层指标
    lines = ['# 对照报告 · v3 冷启动第 1–2 步', '',
             '同一批段落、同一个模型、同一套采样参数。唯一变量是策略。', '',
             '**文明度**一栏＝「有没有指点感」的模型判定（C1–C5 + 整体姿态）：'
             '0 表示读起来像朋友，数字越大越像评审。', '',
             '| 文本 | 模式 | 臂 | 输出字数 | 管道重写 | 禁令违规 | 文明度(模型) | 文明度(脚本) | 脚本禁令命中 | 句长KL | 字TTR |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    for tid, pair in by_tid.items():
        mode = (pair.get('v3') or pair.get('baseline') or {}).get('mode', '-')
        for key in ('baseline', 'v3'):
            r = pair.get(key)
            if not r:
                continue
            m = r['metrics']
            jj = m.get('hy4_judge') or {}
            nvec = jj.get('n_violate')
            vio = '、'.join(x.split('_')[0] for x in (jj.get('violated') or [])) or '—'
            jcell = ('%s %s' % (nvec, vio)) if isinstance(nvec, int) else '未跑'
            cv = m.get('civility') or {}
            ncv = cv.get('n_violate')
            cvcell = ('%s %s' % (ncv, '、'.join(cv.get('violated') or []) or '—')) \
                if isinstance(ncv, int) else '未跑'
            hits = '、'.join('%s×%d' % (k.replace('_', ' '), len(v))
                             for k, v in m['ban_hits'].items()) or '—'
            chits = '、'.join('%s×%d' % (k.split('_')[0], len(v))
                              for k, v in (m.get('civility_hits') or {}).items()) or '—'
            lines.append('| %s | %s | %s | %d | %s | %s | %s | %s | %s | %.3f | %.3f |' % (
                tid, mode, key, m['output_chars'],
                ('%d 次' % m['retries']) if m.get('retries') else '—',
                jcell, cvcell, chits, hits,
                m['kl_sentence_len'], m['ttr_char']))
    lines += ['', '## 模式分布', '']
    modes = {}
    for tid, pair in by_tid.items():
        m = (pair.get('v3') or pair.get('baseline') or {}).get('mode', '-')
        modes[m] = modes.get(m, 0) + 1
    for k, v in sorted(modes.items()):
        lines.append('- %s：%d 条 — %s' % (k, v, MODE_DESC.get(k, '')))
    lines += ['', '> 自动层指标只能给信号，不能判定好坏。'
              '真正的判定是作者的反馈（logs/反馈表.md）。',
              '> **v3.2 注**：22 条标注显示这张表里的「文明度」没有预测力（见 `logs/标注分析.md`），'
              '现在真正有信号的是反馈表里的「可能判太强／太弱」那三行。', '']
    # 有 tag 就单独存一份，别让下一批冲掉这一批（对照报告也被冲过一次）
    name = '对照报告_%s.md' % tag if tag else '对照报告.md'
    with open(os.path.join(LOG_DIR, name), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=20, help='跑几条（默认 20）')
    ap.add_argument('--arm', default='both', choices=['both', 'baseline', 'v3'])
    ap.add_argument('--dry', action='store_true', help='不调模型，只走流程')
    ap.add_argument('--judge', action='store_true',
                    help='跑 hy4 判定层（每条输出多一次模型调用）')
    ap.add_argument('--civility', action='store_true',
                    help='跑文明度判定 C1–C5（每条输出多一次模型调用）')
    ap.add_argument('--per-file', type=int, default=0,
                    help='每个语料文件等距抽 N 段（长章短章平等覆盖）')
    ap.add_argument('--tag', default=None,
                    help='批次名。给了就单独存一份 反馈表_<tag>.md 并并进总表')
    ap.add_argument('--desc', default='', help='批次说明（写进总表的批次清单）')
    ap.add_argument('--corpus', default=None,
                    help='指定语料目录（默认 ../corpus）。'
                         '跑非 P 段落用 `python pick_nonp.py --write` 生成的 ../corpus_非P')
    ap.add_argument('--out-report', action='store_true', default=True)
    a = ap.parse_args()

    global CORPUS_DIR
    if a.corpus:
        CORPUS_DIR = a.corpus if os.path.isabs(a.corpus) \
            else os.path.join(ROOT, a.corpus)

    segs, err = load_segments(a.limit, per_file=a.per_file)
    if err:
        print(err)
        return
    if not segs:
        print('语料里没有可用的段落（每段至少 20 字）。')
        return

    params = load_params()
    cfg = None if a.dry else load_cfg()
    arms = ['baseline'] if a.arm == 'baseline' else (
        ['v3'] if a.arm == 'v3' else ['baseline', 'v3'])

    print('语料：%d 段 · 臂：%s · 参数版本 v%s'
          % (len(segs), '+'.join(arms), params.get('version')))
    results = []
    for i, seg in enumerate(segs, 1):
        for arm in arms:
            t0 = time.time()
            try:
                r = run_one(cfg, seg, params, arm, dry=a.dry,
                            use_judge=a.judge, use_civility=a.civility)
            except Exception as e:
                print('[%s/%s] 失败：%s' % (seg[0], arm, e))
                continue
            r['arm'] = arm
            results.append(r)
            print('[%d/%d] %s %-8s %s  %d字 %dms' % (
                i, len(segs), seg[0], arm, r['mode'],
                r['metrics']['output_chars'], int((time.time() - t0) * 1000)))

    if a.dry:
        print('\n（--dry：不写报告、不记埋点，避免冲掉真结果）')
        return
    write_reports(results, params, tag=a.tag, desc=a.desc)
    print('\n产出：')
    print('  ', os.path.join(LOG_DIR, 'samples.jsonl'))
    print('  ', os.path.join(LOG_DIR, '反馈表.md'))
    print('  ', os.path.join(LOG_DIR, '对照报告.md'))


if __name__ == '__main__':
    main()
