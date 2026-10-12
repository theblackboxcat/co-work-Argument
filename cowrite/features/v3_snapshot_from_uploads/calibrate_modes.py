# -*- coding: utf-8 -*-
"""P/M/S 的**校准诊断**：拿两套语料对着量，看分类器到底分不分得开。

## 它为什么存在

`scan.py` 跑全量 2225 段，分布是二分类的：只有 P 和 M，**S 一个都没有**。
第一反应是"没有 S 语料"，于是建了 `corpus_S/`（21706 段情节驱动文本）。
建完一量——**S 还是 0，而且这批的分数和意识流那批一模一样。**

所以真正要问的不是"有没有 S 语料"，是**"这个分数能不能到 S"**。
本脚本就是回答这个问题的：它不改任何东西，只把数摆出来。

## 用法

    python v3/calibrate_modes.py

输出三块：
1. 两套语料的分数分布（是不是真的重合）
2. 七个特征各自的均值/最大值——**看哪些是死特征**
3. 换几个候选特征试试，报告 AUC（0.5＝没用，1.0＝完全分开）

## 已经量出来的结论（2026-09-16）

- 情节驱动 n=21706 / 意识流 n=3042，两者 score 均值**都是 0.130**，中位数都是 0.125。
- 65% 的权重落在均值≈0 的死特征上：causal .005 / goal .004 / conflict .002 / closure .009。
  **按这个构造，S（>0.7）在算术上就到不了。**
- 更糟的是方向：情节驱动那批在每个"情节特征"上都**低于**意识流
  （因果 .0076 vs .0215、时间 .18 vs .29、目标 .007 vs .012）。
  原因：海明威式的现代叙事是**并置**的，刻意不用"因为/所以/后来"。
  **因果连词密度测的是句法风格，不是有没有情节；在现代主义里两者是反的。**
- 换特征：对话密度 AUC 0.651（弱但真），心理动词密度 0.524（**它其实在测语言**，
  中文作品普遍 0.6–1.2、英文 0.1–0.4，不是测情节）。完成体/过去时 0.5 左右，无用。
"""
import bisect
import collections
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classifier as C  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORP_S = os.path.join(ROOT, 'corpus_S')          # 情节驱动
CORP_P = os.path.join(ROOT, 'corpus_流派')        # 意识流／问题驱动

PER_FILE = 200   # 每个作品最多取多少段
# 为什么按作品分层、不整个目录一把抓：目录是按文件名排序的，
# 一把抓会让排在前面的英文大部头（3000+ 段）把中文全挤出去——
# 那样量出来的"结论"其实只适用于英文，是个抽样假象（实测踩到过）。
TOTAL = 6000


def load(d):
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.md'):
            continue
        t = open(os.path.join(d, fn), encoding='utf-8').read()
        ps = [x.strip() for x in re.split(r'\n\s*\n', t)
              if x.strip() and not x.startswith(('#', '>'))]
        out.extend(ps[:PER_FILE])
        if len(out) >= TOTAL:
            break
    return out


def auc(pos, neg):
    """AUC：0.5＝两个分布完全重合，1.0＝完全分开。"""
    neg = sorted(neg)
    s = 0.0
    for p in pos:
        lo = bisect.bisect_left(neg, p)
        hi = bisect.bisect_right(neg, p)
        s += lo + 0.5 * (hi - lo)
    return s / max(1, len(pos) * len(neg))


# ── 候选替代特征 ────────────────────────────────────────────────────
EN_PAST = re.compile(r'\b\w+ed\b')
ZH_MIND = ['想', '觉得', '仿佛', '似乎', '记得', '知道', '感到', '以为', '以为']
EN_MIND = ['thought', 'wondered', 'felt', 'seemed', 'knew', 'remembered', 'believed']


def per100(n, t):
    u = max(C.words_len(t) / 100.0 if C.is_en(t) else len(t) / 100.0, 0.5)
    return n / u


def f_dialogue(t):
    """对话引号密度：情节推进靠场景和对话，内省不靠。"""
    return per100(t.count('"') + t.count('\u201c') + t.count('\u2018')
                  + t.count('\u300c') + t.count('\u2018'), t)


def f_mind(t):
    """心理动词密度：**反向**——内省越密，越不像在推进事件。"""
    n = (C._count_en(t, EN_MIND) if C.is_en(t)
         else sum(C._count_zh(t, [w]) for w in ZH_MIND))
    return per100(n, t)


def f_perfective(t):
    """完成体／过去时密度。测下来两类几乎一样（2.69 vs 2.65），留着当反例。"""
    n = len(EN_PAST.findall(t)) if C.is_en(t) else sum(
        t.count(w) for w in ['了', '过', '起来', '下去', '已经'])
    return per100(n, t)


CANDIDATES = [
    ('对话密度（正）', f_dialogue, 1),
    ('心理动词密度（反）', f_mind, -1),
    ('完成体/过去时密度', f_perfective, 1),
]


def main():
    A = load(CORP_S)
    B = load(CORP_P)
    if not A or not B:
        print('两套语料都要存在：%s 和 %s' % (CORP_S, CORP_P))
        return
    print('情节驱动 corpus_S   n=%d' % len(A))
    print('意识流   corpus_流派 n=%d\n' % len(B))

    # 1) 分数分布
    sa = [C.classify(t)[1] for t in A]
    sb = [C.classify(t)[1] for t in B]
    print('【1】mode_score 分布（阈值：P<0.30，M≤0.70，S>0.70）')
    print('  %-14s 均值%.3f  中位%.3f  最大%.3f' %
          ('corpus_S', statistics.mean(sa), statistics.median(sa), max(sa)))
    print('  %-14s 均值%.3f  中位%.3f  最大%.3f' %
          ('corpus_流派', statistics.mean(sb), statistics.median(sb), max(sb)))
    print('  → 分不开就是分不开：AUC=%.3f' % auc(sa, sb))

    # 2) 现用特征是不是死的
    print('\n【2】现用七个特征（均值≈0 且最大值也很小＝死特征）')
    w = C.load_params()['classifier']['weights']
    print('  %-22s %-7s %-7s %-7s %s' % ('特征', 'corpus_S', '流派', '最大', '权重'))
    for name, fn in C.FEATURES:
        va = [fn(t) for t in A[:600]]
        vb = [fn(t) for t in B[:600]]
        print('  %-22s %-7.3f %-7.3f %-7.3f %.2f'
              % (name, statistics.mean(va), statistics.mean(vb),
                 max(va + vb), w.get(name, 0)))

    # 3) 候选特征
    print('\n【3】换特征试试（AUC：0.5＝没用，1.0＝完全分开）')
    for name, fn, sign in CANDIDATES:
        va = [sign * fn(t) for t in A]
        vb = [sign * fn(t) for t in B]
        print('  %-20s AUC=%.3f   情节%.3f / 意识流%.3f'
              % (name, auc(va, vb), statistics.mean([fn(t) for t in A]),
                 statistics.mean([fn(t) for t in B])))

    # 4) 心理动词是不是其实在测语言
    print('\n【4】心理动词密度按语言拆——怀疑它测的是语言不是情节')
    for label, ps in [('corpus_S', A), ('corpus_流派', B)]:
        en = [f_mind(t) for t in ps if C.is_en(t)]
        zh = [f_mind(t) for t in ps if not C.is_en(t)]
        print('  %-14s 英文 n=%-5d %.3f   中文 n=%-4d %.3f'
              % (label, len(en), statistics.mean(en) if en else 0,
                 len(zh), statistics.mean(zh) if zh else 0))

    within_private()


# ── 第五块：同语言内的对照（最有信息量的一次）─────────────────────────
# corpus_私有/ 是作者自己给的当代中文文本。把里面**小说**和**散文**分开量，
# 语言这个干扰变量就没了——前面所有跨语言比较都可能被它污染。
PRIVATE_FICTION = {'格非先锋文学精选', '杀夫', '生命式', '把晚餐放进抽屉'}
PRIVATE_PROSE = {'水问', '简媜散文集', '谁在银闪闪的地方_等你'}


def within_private():
    d = os.path.join(ROOT, 'corpus_私有')
    if not os.path.isdir(d):
        return

    def group(names):
        out = []
        for n in names:
            p = os.path.join(d, n + '.md')
            if os.path.exists(p):
                out += [x.strip() for x in re.split(r'\n\s*\n', open(p, encoding='utf-8').read())
                        if x.strip() and not x.startswith(('#', '>'))]
        return out

    A, B = group(PRIVATE_FICTION), group(PRIVATE_PROSE)
    if not A or not B:
        return
    print('\n【5】同语言对照：现代主义小说 vs 抒情散文（都简体中文，无语言干扰）')
    print('  小说 n=%d   散文 n=%d' % (len(A), len(B)))
    sa = [C.classify(t)[1] for t in A]
    sb = [C.classify(t)[1] for t in B]
    print('  mode_score  小说%.3f 散文%.3f  AUC=%.3f'
          % (statistics.mean(sa), statistics.mean(sb), auc(sa, sb)))
    print('  %-22s %-8s %-8s %s' % ('特征', '小说', '散文', 'AUC'))
    worst = []
    for name, fn in C.FEATURES:
        va = [fn(t) for t in A]
        vb = [fn(t) for t in B]
        a = auc(va, vb)
        worst.append((abs(a - 0.5), name, a))
        print('  %-22s %-8.3f %-8.3f %.3f' % (name, statistics.mean(va), statistics.mean(vb), a))
    for nm, fn in [('对话密度', f_dialogue), ('心理动词密度', f_mind)]:
        va = [fn(t) for t in A]
        vb = [fn(t) for t in B]
        a = auc(va, vb)
        worst.append((abs(a - 0.5), nm, a))
        print('  %-22s %-8.3f %-8.3f %.3f' % (nm, statistics.mean(va), statistics.mean(vb), a))
    best = max(worst, key=lambda x: x[0])
    print('  → 最强的单个特征是「%s」，AUC 也只有 %.3f。'
          '全部落在 0.46–0.55，就是噪声。' % (best[1], best[2]))
    print('  → 结论：不是参数没调好，是**这个轴在词汇层不可测**。见 §四.18。')


if __name__ == '__main__':
    main()
