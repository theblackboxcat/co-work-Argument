# -*- coding: utf-8 -*-
"""从《爱别离-故事环档案库.html》里抽出原文章节，写成 corpus/ 下的独立文件。

这个 HTML 就是当初被做成内嵌搜索引擎的那一版——**正文在 #novel-data 的 JSON 里**。
本脚本只做抽取与落盘，**不改动、不解读任何原文**。

用法：
  python extract_lir.py --first 7        # 抽前七大章（§1–§7）
  python extract_lir.py --secs 1,2,3     # 指定节次
  python extract_lir.py --list           # 只列清单
"""
import argparse
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # dsh-伴写/v3
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # lir/
SRC_CANDIDATES = [
    os.path.join(ROOT, '爱别离-故事环档案库.html'),
    os.path.join(os.path.dirname(ROOT), 'lir', '爱别离-故事环档案库.html'),
]
CORPUS = os.path.join(os.path.dirname(HERE), 'corpus')     # dsh-伴写/corpus


def load_doc(path=None):
    if path:
        cands = [path]
    else:
        cands = SRC_CANDIDATES
    last = None
    for c in cands:
        c = os.path.abspath(c)
        if os.path.exists(c):
            last = c
            break
    if not last:
        raise RuntimeError('找不到原文 HTML，试过：%s' % cands)
    with open(last, encoding='utf-8', errors='replace') as f:
        raw = f.read()
    m = re.search(r'id="novel-data"[^>]*>(.*?)</script>', raw, re.S)
    if not m:
        raise RuntimeError('没找到 #novel-data：%s' % last)
    return json.loads(html.unescape(m.group(1)))


def clean_block(text):
    """把一节的全文整理成干净的段落序列。"""
    out = []
    for line in str(text or '').split('\n'):
        line = line.replace('\u3000', ' ').strip()
        if len(line) < 2:
            continue
        # 去掉行首的节次编号标记（1.0.1. 之类），保留正文
        line = re.sub(r'^[0-9]+(\.[0-9]+)*\.?\s*', '', line)
        if len(line) >= 2:
            out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--first', type=int, default=7, help='抽前 N 节（默认 7）')
    ap.add_argument('--secs', default='', help='指定节次，逗号分隔，如 1,2,5')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--every', type=int, default=1,
                    help='每段取 1 条，用于长章节抽样；>1 表示每 N 段取 1 段')
    a = ap.parse_args()

    D = load_doc()
    secs = sorted(D['sections'], key=lambda s: int(s['sec']))

    if a.list:
        for s in secs:
            print('§%-3s Part%s  %-22s %8s 字  %s'
                  % (s['sec'], s['part'], s.get('title', '')[:20],
                     s.get('chars', '?'), s.get('kind', '')))
        return

    if a.secs:
        want = set(int(x) for x in a.secs.split(',') if x.strip())
    else:
        want = set(range(1, a.first + 1))

    os.makedirs(CORPUS, exist_ok=True)
    total_chars = 0
    for s in secs:
        n = int(s['sec'])
        if n not in want:
            continue
        paras = clean_block(s.get('full', ''))
        if a.every > 1:
            paras = paras[::a.every]
        if not paras:
            print('§%s 没有正文，跳过' % n)
            continue
        title = re.sub(r'[\\/:*?"<>|]', '_', s.get('title', '') or '未命名')
        fn = '爱别离_§%02d_%s.md' % (n, title[:16])
        body = '\n\n'.join(paras)
        total_chars += len(body)
        with open(os.path.join(CORPUS, fn), 'w', encoding='utf-8') as f:
            f.write(body + '\n')
        print('§%-3s %-20s %4d 段 / %7d 字  → %s'
              % (n, s.get('title', '')[:18], len(paras), len(body), fn))
    print('\n合计 %d 字。' % total_chars)


if __name__ == '__main__':
    main()
