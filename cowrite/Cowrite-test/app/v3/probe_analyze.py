# -*- coding: utf-8 -*-
"""把 probe.jsonl 算成论文可用的数（纯分析，不调模型、不写任何文件）。

**它算什么**

1. 沉默的精确率与召回率（§7 其二）——完整 2x2，含未标注量
2. 剖面过期对沉默的影响（§5.4）——这条论证此前无法检验，因为 prof_stale 恒为 None
3. 作者自标 P/M/S 的重测信度（§7 其一）——按 text_head 配对两次手选
4. 「伤害」的效应差（§7 其四）——扩张型 vs 收敛型，s(g,p) 的组间差

**它不做什么**

- 不用任何模型算语义相似度。s(g,p) 需要一个外部嵌入或人工判断，
  本文件只把配对与分组**准备好**并留出位置（`sim` 字段），不伪造数值。
- 不做假设检验。样本量在几十条量级，任何 p 值都会误导。

**分母不足时给 None，不给 0。** 这是本文件最重要的一条纪律：
0 意味着"算出来是0"，None 意味着"还标不出来"。后者才是常态。
"""
import json
import math
import os
import statistics as st
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, 'logs', 'probe.jsonl')

# 与 probe.py 保持一致（这里独立写一份，避免 import 时的路径耦合）
SILENT_KINDS = ('silent_right', 'silent_wrong', 'silent_had_nothing')
SPOKE_KINDS = ('should_have_silent', 'should_have_spoken')
CONFUSION = {
    'TP': [('silence', 'silent_right')],
    'FP': [('silence', 'silent_wrong'), ('silence', 'silent_had_nothing')],
    'FN': [('spoke', 'should_have_silent')],
    'TN': [('spoke', 'should_have_spoken')],
}
TRIAL_KINDS = ('convergent', 'divergent')


def load(path=LOG_PATH):
    """读采集文件。**坏行不静默跳过**，连同行号一起报出来——
    一份静默丢行的采集数据会让下面每个数都偏。"""
    if not os.path.exists(path):
        return [], []
    rows, bad = [], []
    with open(path, encoding='utf-8') as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                bad.append((ln, str(e)[:60]))
    return rows, bad


def rate(num, den):
    """分母不足给 None。**绝不用 0 代替**——见模块开头的纪律。"""
    return round(num / den, 4) if den else None


def wilson(k, n, z=1.96):
    """Wilson 区间。样本量小的时候正态近似会给出越界或过窄的区间。"""
    if not n:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)


def _bar(title):
    print('\n' + '=' * 78)
    print(title)
    print('=' * 78)


# ---------------------------------------------------------------- 1 沉默
def report_silence(rows):
    _bar('1沉默的精确率与召回率（§7 其二）')
    sil = [r for r in rows if r.get('kind') == 'silence']
    spk = [r for r in rows if r.get('kind') == 'spoke']
    pp = [r for r in rows if r.get('kind') == 'probe_to_point']

    cell = {}
    for name, pairs in CONFUSION.items():
        cell[name] = len([r for r in rows
                          if any(r.get('kind') == k and r.get('author_feedback') == f
                                 for k, f in pairs)])
    TP, FP, FN, TN = cell['TP'], cell['FP'], cell['FN'], cell['TN']

    print('探针到点 %d ｜ 沉默 %d（未标 %d）｜ 出声 %d（未标 %d）'
          % (len(pp), len(sil), len(sil) - TP - FP, len(spk), len(spk) - FN - TN))
    print('')
    print('                作者说该沉默   作者说该说话')
    print('  它沉默了TP %5d          FP %5d' % (TP, FP))
    print('  它出了声             FN %5d          TN %5d' % (FN, TN))
    print('')
    p_ = rate(TP, TP + FP)
    r_ = rate(TP, TP + FN)
    plo, phi = wilson(TP, TP + FP)
    rlo, rhi = wilson(TP, TP + FN)
    print('精确率 = TP/(TP+FP) = %s   95%%CI %s' % (p_, (plo, phi)))
    print('召回率 = TP/(TP+FN) = %s   95%%CI %s' % (r_, (rlo, rhi)))
    if p_ is None:
        print('  → 精确率**还标不出来**（沉默侧一条未标）。这不是 0，是样本不够。')
    if r_ is None:
        print('  → 召回率**还标不出来**（出声侧一条未标）。')
        print('    **出声侧的标注是算召回率的唯一来源**——只标沉默的话，')
        print('    「该沉默却出了声」那一格永远是空的。')
    print('')
    print('标注分布：%s' % dict(Counter(
        r.get('author_feedback') for r in rows if r.get('author_feedback'))))
    return {'TP': TP, 'FP': FP, 'FN': FN, 'TN': TN,
            'precision': p_, 'recall': r_,
            'probe_to_point': len(pp), 'silence': len(sil), 'spoke': len(spk)}


# ------------------------------------------------------- 2 剖面过期
def report_stale(rows):
    _bar('2  剖面过期对沉默的影响（§5.4）')
    print('论文的论证：「沉默也是从旧剖面算出来的——系统不出声，可能只是')
    print('因为它记得那里写过东西，而那里已经空了。」')
    print('此前无法检验，因为 prof_stale 恒为 None；现在接线了。\n')
    sil = [r for r in rows if r.get('kind') == 'silence']
    spk = [r for r in rows if r.get('kind') == 'spoke']
    has = [r for r in sil if r.get('prof_stale') is not None]
    print('沉默事件 %d 条，其中带剖面标记的 %d 条%s'
          % (len(sil), len(has),
             '' if len(has) == len(sil) else '（其余是早期手造数据，无标记）'))
    if not has:
        print('\n→ 还没有带剖面标记的沉默事件。**这条要等真实使用后才有意义**：')
        print('  手造的沉默不带 prof_stale，而真实使用中剖面过期的机会本来不多。')
        return None
    st_true = [r for r in has if r.get('prof_stale')]
    st_false = [r for r in has if not r.get('prof_stale')]
    print('  剖面过期时沉默 %d 条 ｜ 未过期 %d 条' % (len(st_true), len(st_false)))
    # 正确率对照
    for tag, grp in (('过期', st_true), ('未过期', st_false)):
        lab = [r for r in grp if r.get('author_feedback')]
        right = [r for r in lab if r.get('author_feedback') == 'silent_right']
        if lab:
            print('    %s：已标 %d，该沉默 %d ⇒ 精确率 %s'
                  % (tag, len(lab), len(right), rate(len(right), len(lab))))
        else:
            print('    %s：已标 0 ⇒ **标不出来**' % tag)
    print('\n读法：若「过期」那组的精确率明显低于「未过期」那组，')
    print('§5.4 那条论证就有了第一个实测支撑；若两组差不多，')
    print('**它就是一条合理但未获支持的猜想**，而§3.1 仍可保留 ⊘。')
    return {'stale_n': len(st_true), 'fresh_n': len(st_false)}


# ---------------------------------------------------- 3 P/M/S 重测信度
def report_mode_reliability(rows):
    _bar('3  作者自标 P/M/S 的重测信度（§7 其一）')
    picks = [r for r in rows if r.get('kind') == 'mode_pick']
    print('手选事件 %d 条' % len(picks))
    if not picks:
        print('→ 还没有手选记录。')
        return None
    # 按 text_head 配对：同一段文本被选了两次以上，才谈得上重测
    bytext = defaultdict(list)
    for r in picks:
        bytext[(r.get('text_head') or '').strip()].append(r)
    pairs = {k: v for k, v in bytext.items() if len(v) >= 2 and k}
    print('可配对的文本 %d 段（同一段被选过 ≥2 次）' % len(pairs))
    if not pairs:
        print('→ **还不能算信度**：同一段还没被选过两次。')
        print('  §7 其一的规格是「间隔重标」，所以这一步需要时间间隔，')
        print('  不是跑一次就能得的。')
        return None
    agree = dis = 0
    details = []
    for k, v in pairs.items():
        # 同一段内：取最早与最晚两次
        v2 = sorted(v, key=lambda r: r.get('epoch') or 0)
        a, b = v2[0].get('mode'), v2[-1].get('mode')
        same = (a == b)
        agree += same
        dis += (not same)
        details.append((k[:24], a, b, same))
    print('')
    print('一致 %d ｜ 不一致 %d ⇒ 重测一致率 %s'
          % (agree, dis, rate(agree, agree + dis)))
    lo, hi = wilson(agree, agree + dis)
    # 原写法 `'95%% CI %s' % (lo == hi, (lo, hi))` 只有一个占位符却给了两个
    # 参数：只要出现可配对的文本就会在这里 TypeError 崩掉，
    # 第 4 节（伤害效应差）因此从来没被打印过。
    if lo is None:
        print('95%% CI  —（分母为 0）')
    elif lo == hi:
        print('95%% CI  [%s]（样本太少，区间退化成一点）' % lo)
    else:
        print('95%% CI (%s, %s)' % (lo, hi))
    # 间隔：§7 其一要的是「间隔重标」，同一天连着选两次不算重测。
    # 这里把每段的间隔打出来，让"一致率"能被读成对的数。
    gaps = []
    for k, v in pairs.items():
        v2 = sorted(v, key=lambda r: r.get('epoch') or 0)
        e0, e1 = v2[0].get('epoch') or 0, v2[-1].get('epoch') or 0
        if e0 and e1:
            gaps.append(e1 - e0)
    if gaps:
        med = st.median(gaps)
        print('重标间隔：中位数 %.1f 小时 ｜ 最短 %.1f 小时 ｜ 最长 %.1f 小时'
              % (med / 3600.0, min(gaps) / 3600.0, max(gaps) / 3600.0))
        if med < 3600:
            print('  ⚠️ 中位间隔不足 1 小时——§7 其一要的是**间隔重标**，')
            print('     这样算出来的一致性更接近"记得刚才选了什么"，不是重测信度。')
    print('')
    for k, a, b, same in details[:12]:
        print('  %-26s %s → %s  %s' % (k, a, b, '一致' if same else '**不一致**'))
    if len(details) > 12:
        print('  ...（其余 %d 段略）' % (len(details) - 12))
    print('')
    print('读法（对齐 §7 其一的三个分支）：')
    print('  一致率高且分类器AUC 仍近随机 ⇒ 「词表判别失败」升格为「这条轴本身测不出」')
    print('  一致率低 ⇒ 「作者知道自己处于哪种模式」不成立，')
    print('                交还的就不是 P/M/S 三档而是更粗的东西')
    print('  注：本文件只测**作者自标**的一致性，不测分类器——那是另一组对照。')
    return {'pairs': len(pairs), 'agree': agree, 'disagree': dis}


# -------------------------------------------------------- 4 伤害效应差
def report_harm(rows):
    _bar('4  「伤害」的效应差（§7 其四）')
    print('因变量是 s(g,p)：搭话 g 与作者后续段落 p 的语义相似度。')
    print('**本文件不算 s(g,p)**——那需要一个外部嵌入或人工判断，')
    print('凭空造一个数会让后面所有结论失真。这里只把配对与分组准备好。\n')
    tr = [r for r in rows if r.get('kind') == 'probe_trial']
    print('试验事件 %d 条' % len(tr))
    if not tr:
        print('→ 还没有试验记录。**这是缺口③④的入口**，')
        print('  而入口需要两型搭话的实际文本——那得由作者提供或另写。')
        return None
    byk = Counter(r.get('trial_kind') for r in tr)
    print('  %s' % dict(byk))
    scenes = defaultdict(list)
    for r in tr:
        scenes[r.get('scene') or ''].append(r)
    paired = {k: v for k, v in scenes.items() if k
              and len({r.get('trial_kind') for r in v}) == 2}
    # ---- 顺序效应：blind_pos 一直写进日志，但此前从不被读 ----
    # 为什么要查它：若「在前面」与「在后面」的采纳率有差异，
    # 那顺序本身就是混淆项——组间效应差里有一部分来自呈现次序，
    # 而不是搭话形态。**这是判据零那一类**（阈值/顺序被装置钉住）。
    with_pos = [r for r in tr if r.get('blind_pos') is not None]
    if not with_pos:
        print('  顺序效应：无 blind_pos，测不了'
              '（**这正是「测了不算」的那一格**——日志里没有位置字段）')
    else:
        front = [r for r in with_pos if r.get('blind_pos') == 0]
        back = [r for r in with_pos if r.get('blind_pos') == 1]
        def _acc(grp):
            j = [r for r in grp if r.get('author_feedback')
                 in ('trial_accepted', 'trial_rejected')]
            a = [r for r in j if r.get('accepted') == 1]
            return len(a), len(j)
        af, jf = _acc(front)
        ab, jb = _acc(back)
        print('  顺序效应（blind_pos %d 条有位置）:' % len(with_pos))
        print('    在前（pos=0）：已判 %d，接受 %d ⇒ 采纳率 %s'
              % (jf, af, rate(af, jf)))
        print('    在后（pos=1）：已判 %d，接受 %d ⇒ 采纳率 %s'
              % (jb, ab, rate(ab, jb)))
        # 分母不足时**不报差值**——报了会被读成"顺序无效应"，
        # 而真实情况是"还看不出来"。
        if (jf and jb):
            d = rate(af, jf) - rate(ab, jb)
            print('    前 − 后 = %s' % round(d, 4))
            print('    判读：若这个差明显大于 0，则顺序本身在起作用，'
                  '下面的组间差里混了顺序成分，不能直接读作形态效应。')
        else:
            print('    ⚠️ 某一侧分母为 0 ⇒ **现在还不能判断顺序效应**，'
                  '但这不等于「顺序无效应」。')
        # 形态与位置的交叉：这一格必须看，否则顺序与形态共变时无从归因
        cross = Counter((r.get('trial_kind'), r.get('blind_pos')) for r in with_pos)
        if cross:
            print('    形态 × 位置：%s'
                  % {'%s@%s' % (k[0][:4], k[1]): v for k, v in cross.items()})
            kinds = {k[0] for k in cross}
            poss = {k[1] for k in cross}
            if len(kinds) > 1 and len(poss) > 1:
                pass  # 两个维度都动了，才可能共变
            else:
                print('    ⚠️ 形态与位置**没有同时变动**（一个维度是固定的）'
                      '⇒ 顺序与形态未共变，组间差可归因给形态。')
        print('    位置分布：%s' % dict(Counter(r.get("blind_pos") for r in with_pos)))
        print('    形态分布：%s' % dict(Counter(r.get("trial_kind") for r in with_pos)))

    print('可配对场景 %d 个（同一场景两型都出过了）' % len(paired))
    with_sim = [r for r in tr if r.get('sim') is not None]
    print('其中已填 s 的 %d 条' % len(with_sim))
    # 采纳率：手册 §6.3 写「s 留空就只用采纳率」，但原来这一节从不读 accepted，
    # 于是采纳率一直是"有数据但没算"的状态。这里补上——**并且要能看出它算不了**。
    judged = [r for r in tr if r.get('author_feedback')
              in ('trial_accepted', 'trial_rejected', 'trial_skip')]
    reject_n = len([r for r in tr if r.get('author_feedback') == 'trial_rejected'])
    acc_rate = {}
    for k in TRIAL_KINDS:
        grp = [r for r in judged if r.get('trial_kind') == k]
        acc = [r for r in grp if r.get('accepted') == 1]
        acc_rate[k] = rate(len(acc), len(grp))
        print('  %s：已判 %d 条，其中接受 %d 条 ⇒ 采纳率 %s'
              % (k, len(grp), len(acc), acc_rate[k]))
    if reject_n == 0 and judged:
        print('  ⚠️ 一条 rejected 都没有：**采纳率的分母里没有"不接受"**，')
        print('     所以这个数恒为 100%，组间差恒为 0——它现在什么也说明不了。')
        print('     采集面板目前只有「接」按钮，没有「不接」；')
        print('     在补上另一侧之前，别把采纳率写进论文。')
    elif judged:
        a, b = acc_rate.get('divergent'), acc_rate.get('convergent')
        if a is not None and b is not None:
            print('  组间差（扩张型 − 收敛型）= %s' % round(a - b, 4))
    if not paired:
        print('→ 还不能算效应差：**同一场景必须两型都出过一次**，否则组间差无从谈起。')
        return None
    if not with_sim:
        print('→ 配对已成立，但 s(g,p) 还没填。')
        print('  这一步需要：(1) 外部嵌入，或 (2) 人工判断；')
        print('  两者都会引入一个新的测量装置，而它本身也要被审计。')
    return {'trials': len(tr), 'paired_scenes': len(paired),
            'with_sim': len(with_sim)}


# ---------------------------------------------------------------- main
def main(path=LOG_PATH):
    rows, bad = load(path)
    print('=' * 78)
    print('probe 分析：把采集事件算成论文可用的数')
    print('=' * 78)
    print('数据：%s' % path)
    print('总行数 %d ｜ 坏行 %d' % (len(rows), len(bad)))
    for ln, err in bad[:5]:
        print('  第 %d 行解析失败：%s' % (ln, err))
    if not rows:
        print('\n还没有数据。先用系统写一段，或 POST /api/probe/trial 造几条。')
        return None
    sess = Counter(r.get('session') for r in rows)
    print('会话数 %d（%s）' % (len(sess), dict(list(sess.items())[:4])))
    out = {
        'silence': report_silence(rows),
        'stale': report_stale(rows),
        'mode_reliability': report_mode_reliability(rows),
        'harm': report_harm(rows),
    }
    _bar('汇总')
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print('\n注意：本文件**不做假设检验**。样本量在几十条量级，p 值会误导。')
    print('要写进论文的话，报点估计 + 区间 + 未标注量三样，**不报p 值**。')
    return out


if __name__ == '__main__':
    main()
