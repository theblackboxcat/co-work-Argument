# -*- coding: utf-8 -*-
"""按项目里的流派划分，抓**公有领域**参照文本，建成 corpus_流派/ 语料。

流派划分的依据来自本项目自己的梳理（`_归档_旧稿/30_研究主题定性` §1.1）：

    意识流（1920s–30s）  伍尔夫 / 乔伊斯 / 普鲁斯特   → 线性时间被打断，事件让位于感觉
    反小说·新小说（1949–63） 萨洛特 / 罗布-格里耶      → 重复、位移、空缺取代线性情节
    后现代·元小说        卡尔维诺 / 博尔赫斯 / 品钦    → 空缺、循环、迷宫成为常规策略
    中国 80 年代         王蒙 → 马原、残雪、格非       → 本土重演同一过程

**版权口径（重要）**：只抓公有领域。
- 伍尔夫《达洛维夫人》(1925)、乔伊斯《都柏林人》(1914)、《艺术家青年时代写照》(1916)
  ——美国公版（1929 年前出版均已进入公有领域），取自 Project Gutenberg。
- 惠特曼《草叶集》——公版。**这是金斯伯格的公开承认的直系源头**
  （长列举句、呼吸式断句），因为《嚎叫》(1956) 仍在版权期内取不到，用它顶替。
- 萧红《呼兰河传》(1940，作者 1942 年殁)——中文公版，取自维基文库；
  弱情节长篇，用作**中文侧的 M 区参照**。

放在本地做分类器校准与个人研究使用，不分发。

用法：
  python fetch_genre_corpus.py           # 下载（已存在则复用）并建语料
  python fetch_genre_corpus.py --only wikisource
"""
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '_cache_流派原文')
OUT = os.path.join(ROOT, 'corpus_流派')

GUTENBERG = [
    (2814, 'joyce_dubliners', '乔伊斯《都柏林人》', '意识流'),
    (4217, 'joyce_portrait', '乔伊斯《一个青年艺术家的画像》', '意识流'),
    (71865, 'woolf_mrs_dalloway', '伍尔夫《达洛维夫人》', '意识流'),
    (1322, 'whitman_leaves_of_grass', '惠特曼《草叶集》（顶替金斯伯格：其形式源头）', '后现代长句'),
    # 《变形记》不是意识流，它是「有处境、有推进，但没有商业情节」——
    # 正好落在 M 区（情节在推进，却保持现代主义质感）。前面四个范本几乎全是 P，
    # 靠它们凑不出 M 样本，所以补这一个。
    (5200, 'kafka_metamorphosis', '卡夫卡《变形记》', 'M 区：推进＋现代质感'),
]
WIKISOURCE = [
    ('呼蘭河傳/第一章', 'xiaohong_hulanhe_1', '萧红《呼兰河传》第一章', '中国弱情节'),
    ('呼蘭河傳/第二章', 'xiaohong_hulanhe_2', '萧红《呼兰河传》第二章', '中国弱情节'),
]

MIN_PARA, MAX_PARA = 60, 1500     # 太短没信息，太长会撑爆 prompt


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': 'lir-research/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ('utf-8', 'gb18030'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def strip_gutenberg(t):
    m = re.search(r'\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*', t, re.S)
    if m:
        t = t[m.end():]
    m = re.search(r'\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*', t, re.S)
    if m:
        t = t[:m.start()]
    t = t.replace('\r', '')
    #  Gutenberg 的行宽是硬折行（约 72 字符），要按空行合并回真实段落
    blocks, buf = [], []
    for line in t.split('\n'):
        if line.strip() == '':
            if buf:
                blocks.append(' '.join(buf))
                buf = []
        elif line.strip().startswith(('***', 'ILLUSTRATION', 'CHAPTER ')) and len(line) < 60:
            continue
        else:
            buf.append(line.strip())
    if buf:
        blocks.append(' '.join(buf))
    return [re.sub(r'\s+', ' ', b).strip() for b in blocks]


def strip_wiki(t):
    t = re.sub(r'\{\{[^{}]*\}\}', '', t)
    t = re.sub(r'\[\[[^\]|]*\|([^\]]*)\]\]', r'\1', t)
    t = re.sub(r'\[\[([^\]]*)\]\]', r'\1', t)
    t = re.sub(r'</?br\s*/?>', '\n', t)
    t = re.sub(r'<ref[^>]*>.*?</ref>', '', t, flags=re.S)
    t = re.sub(r"^=+\s*(.+?)\s*=+$", r'# \1', t, flags=re.M)
    blocks = '\n'.join(re.split(r'\n+', t)).split('\n')
    return [re.sub(r'\s+', '', b).strip() for b in blocks]


def write_corpus(slug, title, genre, paras):
    keep = [p for p in paras if MIN_PARA <= len(p) <= MAX_PARA]
    if len(keep) < 5:
        print('  ! 段落太少，跳过：%s（%d 段）' % (slug, len(keep)))
        return 0
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, '%s.md' % slug)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# %s ｜ 流派：%s\n\n' % (title, genre))
        f.write('> 来源：公有领域。仅用于本地分类器校准与个人研究，不分发。\n\n')
        f.write('\n\n'.join(keep))
    print('  %-28s %4d 段 → %s' % (slug, len(keep), os.path.basename(path)))
    return len(keep)


def main():
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    os.makedirs(CACHE, exist_ok=True)
    total = 0

    if only in (None, 'gutenberg'):
        print('古登堡：')
        for gid, slug, title, genre in GUTENBERG:
            cache = os.path.join(CACHE, '%d.txt' % gid)
            if not os.path.exists(cache):
                url = 'https://www.gutenberg.org/cache/epub/%d/pg%d.txt' % (gid, gid)
                try:
                    txt = _get(url)
                    open(cache, 'w', encoding='utf-8').write(txt)
                except Exception as e:
                    print('  ! %s 下载失败：%s' % (slug, e))
                    continue
            else:
                txt = open(cache, encoding='utf-8').read()
            total += write_corpus(slug, title, genre, strip_gutenberg(txt))

    if only in (None, 'wikisource'):
        print('维基文库：')
        for page, slug, title, genre in WIKISOURCE:
            cache = os.path.join(CACHE, re.sub(r'\W+', '_', page) + '.txt')
            if not os.path.exists(cache):
                url = ('https://zh.wikisource.org/w/index.php?title=%s&action=raw'
                       % urllib.parse.quote(page))
                try:
                    txt = _get(url)
                    open(cache, 'w', encoding='utf-8').write(txt)
                except Exception as e:
                    print('  ! %s 下载失败：%s' % (slug, e))
                    continue
            else:
                txt = open(cache, encoding='utf-8').read()
            total += write_corpus(slug, title, genre, strip_wiki(txt))

    print('\n合计 %d 段 → %s' % (total, OUT))


if __name__ == '__main__':
    main()
