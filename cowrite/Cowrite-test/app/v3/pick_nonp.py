# -*- coding: utf-8 -*-
"""从语料里挑出**非 P 模式**的段落，单独落成一个小语料，供对照实验用。

为什么单独做：

- 《爱别离》前七章 P 占 95.9%，等距抽样几乎抽不到 M/S，跑出来的反馈表全是 P。
- 更大也更麻烦的一个发现：**按流派抓来的现代/后现代经典（伍尔夫、乔伊斯、
  惠特曼、卡夫卡、萧红）在现行七特征下几乎全是 P（99.4%）**。
  因为它们删掉的正是"目标句 / 因果连接词 / 外部冲突 / 收束"这四样——
  这恰好反证了项目对流派形态的判断，但也意味着：
  **靠现行特征从这类文本里凑不出 M 样本**，M 区要靠阈值或新特征。

所以 `--include-top` 会把「得分最高的一批」也带上（哪怕它们被判成 P），
用来观察"最像 M 的那批长什么样"。

用法：
  python pick_nonp.py --corpus corpus_流派 --out corpus_流派非P --include-top 8 --write
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, HERE)
from classifier import classify, load_params  # noqa: E402


def iter_paras(corpus_dir):
    for name in sorted(os.listdir(corpus_dir)):
        if not name.lower().endswith(('.txt', '.md', '.markdown')):
            continue
        if name.startswith(('_', 'README', 'readme')):
            continue
        with open(os.path.join(corpus_dir, name), encoding='utf-8') as f:
            raw = f.read()
        prev = ''
        for p in re.split(r'\n\s*\n', raw):
            p = p.strip()
            if len(p) < 20 or p.startswith(('#', '>')):
                continue
            yield name, p, prev
            prev = p


def collect(corpus_dir):
    params = load_params()
    rows = []
    for name, p, prev in iter_paras(corpus_dir):
        mode, score, detail = classify(p, params)
        rows.append({'file': name, 'mode': mode, 'score': score,
                     'text': p, 'prev': prev, 'detail': detail})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default='corpus', help='源语料目录（相对 dsh-伴写/）')
    ap.add_argument('--out', default='corpus_非P', help='输出目录（相对 dsh-伴写/）')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--include-top', type=int, default=0,
                    help='除了真正的非 P，再把得分最高的 N 段也带上（哪怕它们被判成 P）')
    ap.add_argument('--top', type=int, default=12, help='打印前几条')
    a = ap.parse_args()

    src = a.corpus if os.path.isabs(a.corpus) else os.path.join(ROOT, a.corpus)
    rows = collect(src)
    rows.sort(key=lambda r: -r['score'])
    nonp = [r for r in rows if r['mode'] != 'P']
    keep = nonp + [r for r in rows[:a.include_top] if r not in nonp]
    keep.sort(key=lambda r: -r['score'])

    print('源：%s' % src)
    print('段落 %d ｜ 真非 P %d（M %d / S %d）｜ 带 top %d 后共 %d'
          % (len(rows), len(nonp),
             sum(1 for r in nonp if r['mode'] == 'M'),
             sum(1 for r in nonp if r['mode'] == 'S'),
             a.include_top, len(keep)))
    for r in keep[:a.top]:
        print('[%s %.3f] %s' % (r['mode'], r['score'], r['text'][:80].replace('\n', ' ')))

    if a.write and keep:
        out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
        os.makedirs(out, exist_ok=True)
        for f in os.listdir(out):
            os.remove(os.path.join(out, f))
        for i, r in enumerate(keep, 1):
            path = os.path.join(out, 'NP%03d_%s_%0.3f.md' % (i, r['mode'], r['score']))
            # runner 会跳过以 # 开头的行，用标题放来源信息最安全
            with open(path, 'w', encoding='utf-8') as f:
                f.write('# 来源 %s ｜ 判定 %s ｜ 得分 %.3f\n\n%s\n'
                        % (r['file'], r['mode'], r['score'], r['text']))
        print('→ %d 个文件写入 %s' % (len(keep), out))


if __name__ == '__main__':
    main()
