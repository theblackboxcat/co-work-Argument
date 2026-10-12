# -*- coding: utf-8 -*-
"""全量扫描：把语料里的每一段都过一遍分类器，看真实分布。

不调模型，纯本地，毫秒级。目的是给 hy4 提供拟合依据（执行文档 §1.3 / §2.1）：
初始阈值是拍脑袋定的，扫完才知道这个作者的文本到底落在哪。

产出 v3/logs/模式分布.md。
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORPUS = os.path.join(ROOT, 'corpus')
LOG = os.path.join(HERE, 'logs')

sys.path.insert(0, HERE)
from classifier import FEATURES, classify, load_params  # noqa: E402


CORPUS_ARG = None


def read_corpus():
    base = CORPUS_ARG or CORPUS
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if not name.lower().endswith(('.txt', '.md', '.markdown')):
            continue
        if name.startswith(('_', 'README', 'readme')):
            continue
        with open(os.path.join(base, name), encoding='utf-8') as f:
            raw = f.read()
        paras = [p.strip() for p in re.split(r'\n\s*\n', raw) if len(p.strip()) >= 20]
        out.append((name, paras))
    return out


def scan():
    params = load_params()
    docs = read_corpus()
    if not docs:
        print('语料是空的：%s' % (CORPUS_ARG or CORPUS))
        return

    total = Counter()
    feat_sum = defaultdict(float)
    rows = []
    for name, paras in docs:
        c = Counter()
        fs = defaultdict(float)
        scores = []
        for p in paras:
            mode, score, detail = classify(p, params)
            c[mode] += 1
            scores.append(score)
            for k, v in detail.items():
                fs[k] += v
        n = len(paras) or 1
        total.update(c)
        for k, v in fs.items():
            feat_sum[k] += v
        rows.append({
            'name': name, 'n': len(paras), 'c': c, 'fs': fs,
            'mean': sum(scores) / n, 'scores': scores,
        })

    os.makedirs(LOG, exist_ok=True)
    lines = ['# 模式分布 · 全量扫描（分类器本地跑，未经模型）', '',
             '语料：%s' % (CORPUS_ARG or CORPUS), '',
             '意义：初始阈值是拍脑袋定的（P<0.3 / M 0.3–0.7 / S>0.7）。'
             '这份扫描告诉你**这个语料的真实落点**——阈值该往哪挪，看这里。', '',
             '## 总体', '',
             '| 模式 | 段数 | 占比 |', '|---|---|---|']
    N = sum(total.values())
    for m in ('P', 'M', 'S'):
        lines.append('| %s | %d | %.1f%% |' % (m, total[m], 100.0 * total[m] / N))
    lines.append('| 合计 | %d | 100%% |' % N)
    lines.append('')

    lines += ['## 逐章', '',
              '| 章 | 段数 | P | M | S | 平均分 |', '|---|---|---|---|---|---|']
    for r in rows:
        n = r['n'] or 1
        lines.append('| %s | %d | %.0f%% | %.0f%% | %.0f%% | %.3f |' % (
            r['name'].replace('.md', '')[:26], r['n'],
            100.0 * r['c']['P'] / n, 100.0 * r['c']['M'] / n,
            100.0 * r['c']['S'] / n, r['mean']))
    lines.append('')

    lines += ['## 七项特征均值（全语料）', '',
              '看哪项在拖动判定——它就是要优先校准的对象。', '',
              '| 特征 | 均值 | 当前权重 |', '|---|---|---|']
    w = params['classifier']['weights']
    for k, _ in FEATURES:
        lines.append('| %s | %.3f | %.2f |' % (k, feat_sum[k] / N, w.get(k, 0)))
    lines.append('')

    # 分数分布直方图：阈值该放哪一眼能看到
    all_scores = []
    for r in rows:
        all_scores += r['scores']
    buckets = Counter(int(min(10, s * 10)) for s in all_scores)
    lines += ['## 分数分布（0–1，每 0.1 一档）', '',
              '当前切分：0.30 是 P/M 界，0.70 是 M/S 界。', '',
              '```']
    for i in range(11):
        n = buckets.get(i, 0)
        lines.append('%d.%d–%d.%d  %5d  %s' % (
            i // 10, i % 10, i // 10, i % 10, n, '█' * int(60.0 * n / max(1, N))))
    lines += ['```', '',
              '> 如果一堆段挤在 0.28–0.32 附近，说明边界切在人群中间，'
              '阈值一动就大批翻面——那种地方要谨慎，或者换特征。', '']

    out_name = globals().get('LOG_OUT') or '模式分布.md'
    out_path = os.path.join(LOG, out_name)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print('段数 %d ｜ P %d / M %d / S %d'
          % (N, total['P'], total['M'], total['S']))
    print('→', out_path)


if __name__ == '__main__':
    ap_ = argparse.ArgumentParser()
    ap_.add_argument('--corpus', default=None)
    ap_.add_argument('--out', default=None)
    _a = ap_.parse_args()
    if _a.corpus:
        CORPUS_ARG = _a.corpus if os.path.isabs(_a.corpus) else os.path.join(ROOT, _a.corpus)
    globals()['LOG_OUT'] = _a.out
    scan()
