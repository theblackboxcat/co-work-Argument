# -*- coding: utf-8 -*-
"""补 **S 类（故事驱动）语料** —— 分类器的那个空洞。

## 为什么需要这个脚本

`scan.py` 在全量 2225 段上跑出来的分布是二分类的：只有 P 和 M，**S 一个都没有**
（《工程路径与技术回顾》§四.4）。原因不是"作者不写故事"，是**参照语料没有 S**——
`corpus_流派/` 里装的是伍尔夫、乔伊斯、惠特曼，全是"事件让位于感觉"的那一支；
卡夫卡《变形记》是唯一一个被特意加进来的 M。
用这套语料去校准，分类器就没见过"有目标、有因果、有时间线"的文本长什么样。

## 怎么补：现代主义不等于意识流

这是选材的**判断依据**，值得写下来：
二十世纪上半叶的现代主义有一整支是**硬动作、有情节**的——
海明威的短句、菲茨杰拉德的时间线、安德森的小城故事、康拉德的推进、
多斯·帕索斯的群像剪辑、黑塞和扎米亚京的处境小说。
它们同时满足两件事：**叙述方式是现代的，事件结构是传统的。**
这正是 S 需要的样本——否则补进来的会是通俗小说，那测的就不是边界，是噪声。

## 一个被纠正过的概念错误（别再犯）

**「现代文学」不等于「现代主义」。**

- **现代文学**是**时间**概念：鲁迅、老舍、萧红、郁达夫——民国那一代。
  他们做的是白话文初创的活，流派上是现实主义／社会写实，**不是现代主义**。
- **现代主义**是**流派**概念。在中国它指的是**八十年代先锋那一批**——
  格非、马原、残雪、孙甘露、早期余华、莫言——以及现在的双雪涛这一代。

我第一版把鲁迅、老舍、萧红、郁达夫当成了"中文现代主义"抓进来，是错的。
（那批文件现在还留着，但**标签已改**为"中文早期白话叙事·现实主义，
非现代主义"——它们能当情节结构样本，不能当现代主义样本。留着是因为数据有用，
改标签是因为名实不符比没有数据更糟。）

**中文现代主义目前几乎取不到**：八十年代先锋作者全部健在、全部在版权保护期内，
没有任何合法的全文来源。Wikisource 上唯一够得着的是**新感觉派刘呐鸥**
（1939 年殁，公版）的几篇——三十年代中国唯一的现代主义流派，但存量太少。
所以中文侧的 S 类目前只能靠她自己提供文本（见 README 里的待办）。

## 版权口径（只抓公有领域）

- 英文：作者均殁于 1930 年前后、且出版早于 1930 年，美国公有领域，取自 Project Gutenberg。
- 中文：中国是**作者终生 + 50 年**。鲁迅（1936 殁）、萧红（1942 殁）、
  郁达夫（1945 殁）、老舍（1966 殁）——均已进入公有领域，取自维基文库。
  **施蛰存（2003 殁）、张爱玲（1995 殁）、沈从文（1988 殁）仍在保护期内，一律不取。**
  这是本脚本最硬的一条约束：宁可少一个样本，也不碰一本还在保护期里的书。

放在本地做分类器校准与个人研究使用，不分发。

用法：
  python fetch_s_corpus.py            # 下载（已存在则复用）并建语料
  python fetch_s_corpus.py --scan     # 建完顺便跑分类器，看 P/M/S 分布
  python fetch_s_corpus.py --only wikisource
"""
import os
import re
import sys
import json
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '_cache_S原文')
OUT = os.path.join(ROOT, 'corpus_S')

# 复用 fetch_genre_corpus 的清洗函数——去重比重新写一遍重要，
# 两边清洗口径不一致的话，语料之间的分数就不可比了。
from fetch_genre_corpus import strip_gutenberg, strip_wiki, MIN_PARA, MAX_PARA  # noqa: E402

# ── 英文：现代主义，但情节是实的 ────────────────────────────────────
GUTENBERG_S = [
    (64317, 'fitzgerald_gatsby', '菲茨杰拉德《了不起的盖茨比》(1925)', '现代主义·时间线完整，目标与因果都外露'),
    (75201, 'hemingway_farewell', '海明威《永别了，武器》(1929)', '现代主义·短句硬动作，战时推进'),
    (67138, 'hemingway_sun', '海明威《太阳照常升起》(1926)', '现代主义·对话推进'),
    (61085, 'hemingway_in_our_time', '海明威《在我们的时代里》(1925)', '现代主义·极短 vignette'),
    (22949, 'anderson_winesburg', '舍伍德·安德森《小城畸人》(1919)', '现代主义·小镇群像，事件驱动'),
    (219, 'conrad_heart_of_darkness', '康拉德《黑暗的心》(1899)', '前现代主义·推进＋处境'),
    (217, 'lawrence_sons_and_lovers', '劳伦斯《儿子与情人》(1913)', '现代主义·心理＋情节'),
    (71853, 'dospassos_manhattan_transfer', '多斯·帕索斯《曼哈顿中转站》(1925)', '现代主义·群像剪辑'),
    (1999, 'huxley_crome_yellow', '赫胥黎《克罗姆·耶娄》(1921)', '现代主义·讽刺情节'),
    (58340, 'lewis_tarr', '温德姆·刘易斯《塔尔》(1918)', '现代主义·漩涡派，冲突外露'),
    (78572, 'rhys_quartet', '简·里斯《四重奏》(1928)', '现代主义·女性处境，情节推进'),
    (8387, 'hamsun_hunger', '汉姆生《饥饿》(1890)', '前现代主义·第一人称内省＋事件'),
    (805, 'fitzgerald_this_side', '菲茨杰拉德《人间天堂》(1920)', '现代主义·成长线'),
    (9830, 'fitzgerald_beautiful_damned', '菲茨杰拉德《美丽与毁灭》(1922)', '现代主义·婚姻线'),
    (61963, 'zamyatin_we', '扎米亚京《我们》(1924)', '现代主义·反乌托邦，处境＋推进'),
    (75756, 'hesse_steppenwolf', '黑塞《荒原狼》(1927)', '现代主义·处境小说'),
]

# ── 中文 甲：新感觉派（三十年代中国唯一的现代主义流派，公版）──────────
# 刘呐鸥 1939 年殁，穆时英 1940 年殁——这两位是中文现代主义里仅有的公版作者。
# 但 Wikisource 上存量极少（穆时英一篇都没有），所以这一组目前只有几篇。
WIKISOURCE_MODERNIST = [
    ('遊戲 (劉吶鷗)', 'liunaou_youxi', '刘呐鸥《游戏》', '中文现代主义·新感觉派'),
    ('兩個時間的不感症者', 'liunaou_two_time', '刘呐鸥《两个时间的不感症者》', '中文现代主义·新感觉派'),
    ('熱情之骨', 'liunaou_passion', '刘呐鸥《热情之骨》', '中文现代主义·新感觉派'),
    ('都市風景線', 'liunaou_cityscape', '刘呐鸥《都市风景线》', '中文现代主义·新感觉派'),
]

# ── 中文 乙：早期白话叙事（**现实主义，不是现代主义**）─────────────────
# 留着的理由：它们的**情节结构**是实的（有目标、因果、时间线、收束），
# 可以当 S 的结构样本。但**不能**当现代主义样本——把鲁迅叫现代主义是概念错误。
WIKISOURCE_S = [
    ('阿Q正傳', 'luxun_aq', '鲁迅《阿Q正传》', '中文早期白话叙事·现实主义，非现代主义'),
    ('藥', 'luxun_medicine', '鲁迅《药》', '中文早期白话叙事·现实主义，非现代主义'),
    ('祝福', 'luxun_blessing', '鲁迅《祝福》', '中文早期白话叙事·现实主义，非现代主义'),
    ('孔乙己', 'luxun_kongyiji', '鲁迅《孔乙己》', '中文早期白话叙事·现实主义，非现代主义'),
    ('故鄉', 'luxun_hometown', '鲁迅《故乡》', '中文早期白话叙事·现实主义，非现代主义'),
    ('狂人日記', 'luxun_madman', '鲁迅《狂人日记》', '中文早期白话叙事·现实主义，非现代主义'),
    ('駱駝祥子', 'laoshe_camel', '老舍《骆驼祥子》', '中文早期白话叙事·现实主义，非现代主义'),
    ('月牙兒', 'laoshe_crescent', '老舍《月牙儿》', '中文早期白话叙事·现实主义，非现代主义'),
    ('離婚', 'laoshe_divorce', '老舍《离婚》', '中文早期白话叙事·现实主义，非现代主义'),
    ('貓城記', 'laoshe_cat_city', '老舍《猫城记》', '中文早期白话叙事·现实主义，非现代主义'),
    ('老張的哲學', 'laoshe_laozhang', '老舍《老张的哲学》', '中文早期白话叙事·现实主义，非现代主义'),
    ('二馬', 'laoshe_er_ma', '老舍《二马》', '中文早期白话叙事·现实主义，非现代主义'),
    ('生死場', 'xiaohong_life_death', '萧红《生死场》', '中文早期白话叙事·现实主义，非现代主义'),
    ('馬伯樂', 'xiaohong_mabole', '萧红《马伯乐》', '中文早期白话叙事·现实主义，非现代主义'),
    ('商市街', 'xiaohong_shangshi', '萧红《商市街》', '中文早期白话叙事·现实主义，非现代主义'),
    ('春風沉醉的晚上', 'yudafu_spring_night', '郁达夫《春风沉醉的晚上》', '中文早期白话叙事·现实主义，非现代主义'),
]


def _wiki_text(page):
    """取维基文库正文。

    两个坑，都是在中文侧踩的：
    1. **分页嵌入**：很多长篇的正文不在主页面上，主页面只有
       `<pages index="XXX.pdf" from= to= />`,`action=raw` 拿回来是个空壳
       （阿Q正传、骆驼祥子、生死场都是这样，第一次跑全 0 段就是因为这个）。
       所以 raw 拿不到东西的时候退回 `action=parse`，那个会把嵌入展开。
    2. **SSL 握手偶尔超时**：重试几次。
    """
    url_raw = ('https://zh.wikisource.org/w/index.php?title=%s&action=raw'
               % urllib.parse.quote(page))
    txt = _get(url_raw)
    if len(txt) >= 2000 and '<pages index=' not in txt:
        return txt
    url_api = ('https://zh.wikisource.org/w/api.php?action=parse&prop=text'
               '&format=json&formatversion=2&page=' + urllib.parse.quote(page))
    html = json.loads(_get(url_api))['parse']['text']
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.S)
    html = re.sub(r'<[^>]+>', '\n', html).replace('&#8203;', '').replace('&nbsp;', ' ')
    html = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), html).replace('&amp;', '&')
    keep = []
    for ln in html.split('\n'):
        ln = ln.strip()
        if not ln:
            continue
        # 页面上挂的导航、版权说明、姊妹计划——都不是正文
        if any(k in ln for k in ('←', '→', '姊妹计划', '分类', '数据项', '图册',
                                 '百科', '吴典', '粤典', '本作品收錄', '本作品收录',
                                 '维基文库收录', '公有領域', '公有领域')):
            continue
        if re.match(r'^第[一二三四五六七八九十百]+[章节節]', ln) and len(ln) < 20:
            continue
        keep.append(ln)
    return '\n'.join(keep)


def _get(url, timeout=45, tries=3):
    """维基文库偶尔 SSL 握手超时，重试几次再放弃。"""
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'lir-research/1.0'})
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            for enc in ('utf-8', 'gb18030'):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode('utf-8', errors='replace')
        except Exception as e:
            last = e
    raise last


def write_corpus(slug, title, note, paras):
    keep = [p for p in paras if MIN_PARA <= len(p) <= MAX_PARA]
    if len(keep) < 5:
        print('  ! 段落太少，跳过：%s（%d 段）' % (slug, len(keep)))
        return 0
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, '%s.md' % slug), 'w', encoding='utf-8') as f:
        f.write('# %s ｜ %s\n\n' % (title, note))
        f.write('> 来源：公有领域。仅用于本地分类器校准与个人研究，不分发。\n\n')
        f.write('\n\n'.join(keep))
    print('  %-30s %4d 段' % (slug, len(keep)))
    return len(keep)


def main():
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    os.makedirs(CACHE, exist_ok=True)
    total = 0

    if only in (None, 'gutenberg'):
        print('古登堡（英文）：')
        for gid, slug, title, note in GUTENBERG_S:
            cache = os.path.join(CACHE, '%d.txt' % gid)
            if os.path.exists(cache):
                txt = open(cache, encoding='utf-8').read()
            else:
                try:
                    txt = _get('https://www.gutenberg.org/cache/epub/%d/pg%d.txt' % (gid, gid))
                    open(cache, 'w', encoding='utf-8').write(txt)
                except Exception as e:
                    print('  ! %s 下载失败：%s' % (slug, e))
                    continue
            total += write_corpus(slug, title, note, strip_gutenberg(txt))

    if only in (None, 'wikisource'):
        print('维基文库（中文·现代主义，新感觉派）：')
        for page, slug, title, note in WIKISOURCE_MODERNIST:
            cache = os.path.join(CACHE, re.sub(r'\W+', '_', page) + '.txt')
            if os.path.exists(cache):
                txt = open(cache, encoding='utf-8').read()
            else:
                try:
                    txt = _wiki_text(page)
                    open(cache, 'w', encoding='utf-8').write(txt)
                except Exception as e:
                    print('  ! %s 下载失败：%s' % (slug, e))
                    continue
            paras = [p for p in strip_wiki(txt) if len(p) >= MIN_PARA]
            total += write_corpus(slug, title, note, paras)

        print('维基文库（中文·早期白话叙事，现实主义，非现代主义）：')
        for page, slug, title, note in WIKISOURCE_S:
            cache = os.path.join(CACHE, re.sub(r'\W+', '_', page) + '.txt')
            if os.path.exists(cache):
                txt = open(cache, encoding='utf-8').read()
            else:
                try:
                    txt = _wiki_text(page)
                    open(cache, 'w', encoding='utf-8').write(txt)
                except Exception as e:
                    print('  ! %s 下载失败：%s' % (slug, e))
                    continue
            paras = [p for p in strip_wiki(txt) if len(p) >= MIN_PARA]
            total += write_corpus(slug, title, note, paras)

    print('\n合计 %d 段 → %s' % (total, OUT))
    if '--scan' in sys.argv:
        scan()


def scan():
    """建完就看分布——**补没补上，只能靠它说了算**，不能靠我觉得。"""
    import collections
    from classifier import classify
    print('\n各文件 P/M/S 分布：')
    agg = collections.Counter()
    for fn in sorted(os.listdir(OUT)):
        if not fn.endswith('.md'):
            continue
        txt = open(os.path.join(OUT, fn), encoding='utf-8').read()
        paras = [p.strip() for p in re.split(r'\n\s*\n', txt)
                 if p.strip() and not p.startswith(('#', '>'))]
        c = collections.Counter(classify(p)[0] for p in paras)
        agg += c
        n = sum(c.values()) or 1
        s_pct = 100.0 * c['S'] / n
        print('  %-34s n=%-5d P%3d M%3d S%3d   S=%4.1f%%'
              % (fn[:-3], sum(c.values()), c['P'], c['M'], c['S'], s_pct))
    n = sum(agg.values()) or 1
    print('\n合计 n=%d  P=%d (%.1f%%)  M=%d (%.1f%%)  S=%d (%.1f%%)'
          % (n, agg['P'], 100.0 * agg['P'] / n, agg['M'], 100.0 * agg['M'] / n,
             agg['S'], 100.0 * agg['S'] / n))


if __name__ == '__main__':
    main()
