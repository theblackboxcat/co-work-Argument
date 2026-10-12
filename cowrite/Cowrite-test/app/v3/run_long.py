# -*- coding: utf-8 -*-
"""长文本连续伴写：把**一整节**（一千到两千字）当成一个系统来跑。

之前所有测试都是**孤立短段落**——每段独立判定、独立成文。
那测不出两件事：

1. **模式会不会漂移**：同一节里前几段是 P，后面推进起来变成 M，
   策略跟不跟得上？（`classify` 每段重算，所以它会——但要看。）
2. **连着说十几轮之后，伴写者会不会掉回口头禅**：
   单轮看不出来的东西，轮次一排出来就很显眼。
   这里用「相邻两条输出首句的字面重合度」来测——真实对话里
   相邻承接句不该长得一样。

用法：
  python run_long.py --src corpus/爱别离_§01_....md --window 1600 --turns 10
  python run_long.py --list                    # 看可选的源
"""
import argparse
import os
import re
import sys
import time
import urllib.request
import json
import difflib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(HERE, 'logs')

sys.path.insert(0, HERE)
from classifier import MODE_DESC, classify, load_params  # noqa: E402
from policy import build_system, build_user, sampling  # noqa: E402
import metrics as M  # noqa: E402
from runner import HARD_CIVILITY, FIXNOTE, MAX_RETRY, call_model, load_cfg  # noqa: E402


def list_sources():
    for d in ('corpus', 'corpus_非P', 'corpus_流派', 'corpus_流派非P'):
        p = os.path.join(ROOT, d)
        if not os.path.isdir(p):
            continue
        print('[%s]' % d)
        for fn in sorted(os.listdir(p)):
            if fn.lower().endswith(('.md', '.txt')) and not fn.startswith(('_', 'README')):
                print('   %s' % fn)
        print()


def read_paras(src):
    p = src if os.path.isabs(src) else os.path.join(ROOT, src)
    with open(p, encoding='utf-8') as f:
        raw = f.read()
    return [x.strip() for x in re.split(r'\n\s*\n', raw)
            if len(x.strip()) >= 20 and not x.strip().startswith(('#', '>'))]


def pick_window(paras, window_chars, start=0):
    """从 start 起连续取若干段，凑到 window_chars 左右。"""
    out, n = [], 0
    for p in paras[start:]:
        out.append(p)
        n += len(p)
        if n >= window_chars:
            break
    return out


def first_sent(s):
    s = re.sub(r'^\[[PMS]\]\s*', '', s).strip()
    parts = re.split(r'[。！？；\n]', s)
    return (parts[0] if parts else s).strip()[:24]


def sim(a, b):
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


def run(src, window_chars, turns, dry=False):
    params = load_params()
    cfg = None if dry else load_cfg()
    paras = read_paras(src)
    win = pick_window(paras, window_chars)
    if len(win) < turns + 1:
        turns = max(1, len(win) - 1)
    print('源：%s ｜ 窗口 %d 段 / %d 字 ｜ 轮次 %d'
          % (os.path.basename(src), len(win), sum(map(len, win)), turns))

    rows = []
    openings = []          # 跨轮开头形状——模板只在这里显形
    for i in range(1, turns + 1):
        cur = win[i]
        prev = win[i - 1]
        # 文档上下文＝本节里**前面所有**段落（这才是"一两千字的系统"）
        doc_ctx = '【本节前面已写下的段落】\n' + '\n'.join(
            '· %s' % w[:120] for w in win[:i - 1]) if i >= 2 else ''
        mode, score, detail = classify(cur, params)
        system, meta = build_system(cur, params)
        cap = int((params.get('policy', {}).get(meta['mode'], {}) or {}).get('max_chars', 0))
        user = build_user(cur, prev, doc_ctx, max_chars=cap)
        samp = sampling(params)

        retries = 0
        ban_open = ''
        if dry:
            out, stop = '(dry run)', None
        else:
            out, stop = call_model(cfg, system, user, samp)
            for _ in range(MAX_RETRY):
                bad = [k for k in HARD_CIVILITY if k in M.civility_hits(out)]
                rep = M.opening_repeat(out, openings)
                if not bad and not rep:
                    break
                retries += 1
                if rep:
                    ban_open = rep['ban_char']
                fix = '；'.join(FIXNOTE[k] for k in bad)
                if ban_open:
                    fix = (fix + '；' if fix else '') + '开头不许用「%s」' % ban_open
                user = build_user(cur, prev, doc_ctx, max_chars=cap,
                                  ban_opening=ban_open)
                user = user + '\n\n（上一条作废，重写。%s）' % fix
                out, stop = call_model(cfg, system, user, samp)

        body = re.sub(r'^\[[PMS]\]\s*', '', out).strip()
        m = M.evaluate(cur, out, [])
        shape = M.opening_shape(out)
        openings.append(shape)
        rows.append({
            'i': i, 'mode': meta['mode'], 'score': meta['score'],
            'len': len(body), 'retries': retries,
            'first': first_sent(body),
            'civ': sorted(M.civility_hits(out)),
            'shape': shape,
            'out': body,
        })
        print('  [%d/%d] %s %.3f  %3d字 重写%d  %s'
              % (i, turns, meta['mode'], meta['score'], len(body), retries,
                 '、'.join(x.split('_')[0] for x in sorted(M.civility_hits(out))) or '—'))
        time.sleep(0.2)

    # 相邻首句相似度：连着说会不会掉回同一个句式
    sims = [sim(rows[i]['first'], rows[i + 1]['first']) for i in range(len(rows) - 1)]
    modes = [r['mode'] for r in rows]
    flips = sum(1 for i in range(1, len(modes)) if modes[i] != modes[i - 1])
    # 开头形状：字面相似度测不出「那 X」这种换了物件、没换句法的模板
    shapes = [r['shape'] for r in rows]
    shape_rep = max((shapes.count(s) for s in set(shapes) if s), default=0)

    os.makedirs(LOG, exist_ok=True)
    lines = ['# 长文本连续伴写报告', '',
             '源：`%s` ｜ 窗口 %d 段 / %d 字 ｜ 轮次 %d' % (
                 src, len(win), sum(map(len, win)), len(rows)), '',
             '## 会不会漂移', '',
             '- 模式序列：%s' % ' → '.join(modes),
             '- 模式翻转次数：**%d**' % flips, '',
             '## 会不会掉回口头禅', '',
             '- 相邻两条首句相似度：%s' % '、'.join(str(x) for x in sims) or '—',
             '- 最高相似度：**%s**（>0.6 说明连着两句几乎一样，是模板）'
             % (max(sims) if sims else '—'), '',
             '### 开头形状（字面相似度测不出的模板）', '',
             '- 形状序列：%s' % ' · '.join(s or '—' for s in shapes),
             '- 同一个形状最多出现 **%d** 次（DEICTIC＝那/这/它/他/她 一类回指开头）'
             % shape_rep, '',
             '## 逐轮', '',
             '| 轮 | 模式 | 分数 | 字数 | 重写 | 开头 | 首句 | 文明度(脚本) |',
             '|---|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append('| %d | %s | %.3f | %d | %d | %s | %s | %s |' % (
            r['i'], r['mode'], r['score'], r['len'], r['retries'],
            r['shape'] or '—',
            r['first'].replace('|', '/')[:24],
            '、'.join(x.split('_')[0] for x in r['civ']) or '—'))
    lines += ['', '## 全文', '']
    for r in rows:
        lines.append('**第 %d 轮（%s %.3f）**' % (r['i'], r['mode'], r['score']))
        lines.append('')
        lines.append('> %s' % r['out'].replace('\n', '\n> '))
        lines.append('')
    with open(os.path.join(LOG, '长文本报告.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('\n→ %s' % os.path.join(LOG, '长文本报告.md'))
    print('模式翻转 %d ｜ 首句相似度最高 %s ｜ 开头形状最多重复 %d 次'
          % (flips, max(sims) if sims else '—', shape_rep))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--src', default=None)
    ap.add_argument('--window', type=int, default=1600)
    ap.add_argument('--turns', type=int, default=8)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    if a.list or not a.src:
        list_sources()
        if not a.src:
            print('用 --src <目录>/<文件> 指定一节。')
        return
    run(a.src, a.window, a.turns, dry=a.dry)


if __name__ == '__main__':
    main()
