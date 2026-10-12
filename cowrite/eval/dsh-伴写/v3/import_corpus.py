# -*- coding: utf-8 -*-
"""导入**作者自己提供**的文本（.epub / .txt）→ 语料。

## 为什么单独一个目录

`corpus_流派/` 和 `corpus_S/` 装的都是**公有领域**文本（README 里敢写"来源"）。
这一批不是——它们是**仍在版权保护期内**的当代作品，是她自己把文件给过来的。
所以出到 **`corpus_私有/`**，并且：

- **只用本地。** 不上传、不分发、不进版本库。
- **只做分类器校准与个人研究。**
- 每个语料文件头部写明来源与这句约束。

单独放一个目录，是为了让"哪份能说、哪份不能说"永远一眼分得清。

## epub 怎么解

epub 就是个 zip：`META-INF/container.xml` 指路 → `.opf` 里有书名/作者/章节顺序
→ 正文是包在里面的 xhtml。只用标准库（zipfile + ElementTree），不装任何东西。

用法：
  python v3/import_corpus.py                      # 导入默认目录
  python v3/import_corpus.py <目录>               # 指定
  python v3/import_corpus.py --min 30             # 放宽最短段落（中文段落偏短）
  python v3/import_corpus.py --scan               # 导完顺手跑一遍 P/M/S 分布
"""
import html
import os
import re
import sys
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(os.path.dirname(ROOT), '中文语料')
OUT = os.path.join(ROOT, 'corpus_私有')

# 中文段落比英文短，60 字的下限会把现代中文的大量段落滤掉（实测过得太狠）。
MIN_PARA = 40
MAX_PARA = 1500

NS = {
    'c': 'urn:oasis:names:tc:opendocument:xmlns:container',
    'o': 'http://www.idpf.org/2007/opf',
    'd': 'http://purl.org/dc/elements/1.1/',
}


def _resolve(z, p):
    """包里的路径有时是 URL 编码过的，两种都试一下。"""
    if p in z.namelist():
        return p
    q = urllib.parse.unquote(p)
    return q if q in z.namelist() else None


def epub_meta(z):
    """取书名 / 作者 + 按 spine 排好序的正文路径。
    取不到就用兜底：拿所有 html。名字不重要，别让它卡住导入。"""
    title, author, paths = '', '', []
    try:
        root = ET.fromstring(z.read('META-INF/container.xml'))
        opf = root.find('.//c:rootfile', NS).get('full-path')
        base = os.path.dirname(opf)
        pkg = ET.fromstring(z.read(opf))
        md = pkg.find('o:metadata', NS)
        if md is not None:
            t = md.find('d:title', NS)
            a = md.find('d:creator', NS)
            title = (t.text or '').strip() if t is not None else ''
            author = (a.text or '').strip() if a is not None else ''
        items = {}
        for it in pkg.findall('.//o:manifest/o:item', NS):
            items[it.get('id')] = (it.get('href'), it.get('media-type') or '')
        order = [s.get('idref') for s in pkg.findall('.//o:spine/o:itemref', NS)]
        for i in order:
            if i in items and 'html' in items[i][1]:
                p = _resolve(z, os.path.join(base, items[i][0]))
                if p:
                    paths.append(p)
    except Exception as e:
        print('  ! 元数据读取失败（按包内顺序兜底）：%s' % e)
    return title, author, paths


def html_to_text(t):
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', t, flags=re.S | re.I)
    # 块级标签先换成换行，否则整章会粘成一大段
    t = re.sub(r'</?(p|div|br|h[1-6]|li|blockquote|tr)[^>]*>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    return html.unescape(t)


def read_epub(path):
    z = zipfile.ZipFile(path)
    title, author, paths = epub_meta(z)
    if not paths:
        paths = [n for n in z.namelist()
                 if re.search(r'\.(x?html|htm)$', n) and 'META-INF' not in n]
    texts = []
    for p in paths:
        raw = z.read(p)
        for enc in ('utf-8', 'gb18030', 'latin-1'):
            try:
                texts.append(html_to_text(raw.decode(enc)))
                break
            except UnicodeDecodeError:
                continue
    return title, author, texts


# 出版社版权页、书号、网址、页码——会被当成段落混进来。
#
# 2026-09-16 补，起因：跑「私有批」时系统把版权页
# `ThiseditionarrangedwithROGERS,COLERIDGE&WHITELTD(RCW)` 当正文读，
# 还给李昂的百科小传写了"你这段写得像简历"。**这是输入的问题，不是模型的问题。**
#
# 只加**确定性**判据，不碰"可能也出现在正文里"的词：
# 试过用「弱标记出现两次以上」的计分法（原名／笔名／小说集…），
# 结果把格非正文里的一句「…写下自己的笔名…小说集…」误杀了。
# 0.03% 的收益换一个误杀，不划算——**宁漏不误杀**。
# 书前页真正的兜底在 `runner.py` 的 `is_paratext`（抽样时再挡一次）
# 和「等距抽样从半格开始」（不再咬住 index 0）。
NOISE_STRONG = re.compile(
    r'ISBN|版权所有|copyright|arrangedwith|allrightsreserved|printedin'
    r'|图书在版|CIP|出版发行|责任编辑|封面设计|装帧设计|z-library|本书由'
    r'|^\s*网址|^\s*书号|^\s*印张|^\s*字数|^\s*定价|^\s*开本|https?://'
    r'|（(19|20)\d{2}\s*[—\-－]|出生于\s*(19|20)\d{2}年?'
    r'|^第\s*[0-9一二三四五六七八九十百]+\s*页$', re.I)
NOISE = NOISE_STRONG          # 向后兼容旧的引用


def is_noise(s):
    return bool(NOISE_STRONG.search(s))


def paragraphs(texts, min_len=MIN_PARA, max_len=MAX_PARA):
    out = []
    for t in texts:
        for ln in t.split('\n'):
            # 中文没有词间空格，直接压掉所有空白
            s = re.sub(r'\s+', '', ln).strip()
            s = re.sub(r'^[0-9一二三四五六七八九十百]+[、.．]?', '', s)
            if is_noise(s):
                continue
            if min_len <= len(s) <= max_len:
                out.append(s)
    return out


def slugify(name):
    s = re.sub(r'[（(].*?[)）]', '', name)
    s = re.sub(r'[^\w一-鿿]+', '_', s)
    return s.strip('_')[:48] or 'untitled'


def write_doc(slug, title, author, paras, src):
    if len(paras) < 5:
        print('  ! 段落太少，跳过：%s（%d 段）' % (slug, len(paras)))
        return 0
    os.makedirs(OUT, exist_ok=True)
    who = '（%s）' % author if author else ''
    head = ('# %s%s\n\n'
            '> 来源：%s\n'
            '>\n'
            '> **这份仍在版权保护期内。** 作者本人提供的文件，'
            '仅用于本地分类器校准与个人研究；**不分发、不上传、不进版本库。**\n\n')
    with open(os.path.join(OUT, '%s.md' % slug), 'w', encoding='utf-8') as f:
        f.write(head % (title, who, src))
        f.write('\n\n'.join(paras))
    print('  %-32s %5d 段' % (slug, len(paras)))
    return len(paras)


def scan():
    """导完就看分布。注意：分类器本身测不准（§四.18），这个表只看相对水位。"""
    import collections
    sys.path.insert(0, HERE)
    from classifier import classify
    print('\nP/M/S 分布（分类器自己的判法，参考用）：')
    agg = collections.Counter()
    for fn in sorted(os.listdir(OUT)):
        if not fn.endswith('.md'):
            continue
        t = open(os.path.join(OUT, fn), encoding='utf-8').read()
        ps = [p.strip() for p in re.split(r'\n\s*\n', t)
              if p.strip() and not p.startswith(('#', '>'))]
        c = collections.Counter(classify(p)[0] for p in ps)
        agg += c
        n = sum(c.values()) or 1
        print('  %-34s n=%-5d P%4d M%4d S%3d' % (fn[:-3], n, c['P'], c['M'], c['S']))
    n = sum(agg.values()) or 1
    print('  合计 n=%d  P=%d (%.1f%%)  M=%d (%.1f%%)  S=%d (%.1f%%)'
          % (n, agg['P'], 100.0 * agg['P'] / n, agg['M'], 100.0 * agg['M'] / n,
             agg['S'], 100.0 * agg['S'] / n))


def main():
    # 注意：不能简单地"取第一个不以 -- 开头的参数"——那样会把 `--min 20`
    # 里的 `20` 当成目录（实测踩到）。
    argv = sys.argv[1:]
    min_len = MIN_PARA
    if '--min' in argv:
        i = argv.index('--min')
        try:
            min_len = int(argv[i + 1])
        except (IndexError, ValueError):
            print('！ --min 后面要给个数字')
        argv = argv[:i] + argv[i + 2:]
    src = next((a for a in argv if not a.startswith('--')), SRC)
    if not os.path.isdir(src):
        print('找不到目录：%s' % src)
        return
    print('从 %s 导入 → %s\n' % (src, OUT))
    total = 0
    for fn in sorted(os.listdir(src)):
        path = os.path.join(src, fn)
        low = fn.lower()
        print('· %s' % fn[:46])
        try:
            if low.endswith('.epub'):
                title, author, texts = read_epub(path)
                base = (title or fn.rsplit('.', 1)[0])
                ps = paragraphs(texts, min_len)
                total += write_doc(slugify(base), base, author, ps, fn)
            elif low.endswith(('.txt', '.md')):
                t = open(path, encoding='utf-8', errors='replace').read()
                base = fn.rsplit('.', 1)[0]
                total += write_doc(slugify(base), base, '',
                                   paragraphs([t], min_len), fn)
        except Exception as e:
            print('  ! 失败：%s' % e)
    print('\n合计 %d 段 → %s' % (total, OUT))
    if '--scan' in sys.argv:
        scan()


if __name__ == '__main__':
    main()
