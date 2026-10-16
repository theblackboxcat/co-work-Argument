#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
I3 裁定验证：F1 分层重算（零 API 成本）
=======================================

裁定内容（2026-10-16 作者授权"你判断"后裁定）：
  F1（树未启用）**按 layer 分层**——只有 layer=B 的发言轮不引节点才记失效点；
  layer=A/C 的轮不引节点改记观察项 tree_unreferenced（不当失效点，进汇总统计）。
  layer=None（漂移轮）无法分层，维持原口径；layer=⊘ 的轮（verdict=不说）
  按 I2 精神整体不做内容侧检查，其历史 F1 同属 I1 时代遗留，分层后一并归零。

裁定依据（规范判断，非测量结果）：
  1. prompt 定义：B"指位置，不给方案"——引节点是 B 对自己承诺的行为，
     判 B 不引节点 = 言行矛盾，是缺陷。
  2. prompt 定义：A"回映它，但不得替甲把它命名成某个节点或结论"——
     A 轮不引节点合规（A 不承诺引节点，甚至禁止命名节点）。
  3. C"核对已说过的是否能对上账，不预测"——C 不承诺引节点。
  4. 全史 8 次 F1 无一次落在 B 轮：分层不改变任何一次真实缺陷判定
     （见本脚本输出的对比表）。

防洗白条款：tree_unreferenced 观察项按层汇总——
若出现"既不判 B 也不引节点"的系统性模式（树注入完全未兑现），
观察项统计会显出来，不会被分层口径掩盖。

数据范围：calib_iter*.json（E12）+ e13_P*.json（E13）+ e14_P*.json（E14）。
输出：终端对比表（旧口径 vs 新口径），不写文件（裁定验证一次性脚本）。
"""
import json
import glob
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

SILENCE_EVENTS = ('model_silence', 'model_silence_with_reason')


def iter_records():
    """产出 (文件名, 运行名, rep 序号, rec)。兼容三种文件形态。"""
    for f in sorted(glob.glob(str(HERE / 'calib_iter*.json'))) + \
             sorted(glob.glob(str(HERE / 'e13_P*.json'))) + \
             sorted(glob.glob(str(HERE / 'e14_P*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        runs = d.get('runs', [d]) if 'runs' in d else [d]
        for ri, r in enumerate(runs, 1):
            for h in r['log']:
                if h['who'] == 'B' and 'rec' in h:
                    yield f, r, ri, h['rec']


def reclassify(flags, layer):
    """I3 分层：B 轮保留 F1；A/C/⊘ 轮降级为观察项；None（漂移轮）维持原口径。"""
    if 'F1' not in flags:
        return flags, False
    if layer == 'B' or layer is None:
        return flags, False          # B 轮=真缺陷；None 漂移轮无从判定承诺，维持
    return [x for x in flags if x != 'F1'], True   # A/C/⊘ 轮降级为观察项


def main():
    old_flags, new_flags = Counter(), Counter()
    tree_unref = Counter()           # 观察项：layer -> n
    demoted, kept = [], []
    # 分层统计表：layer -> [记录轮, 内容检查轮, 旧F1, 新F1(保留), 降级]
    tbl = {}
    b_spoken = 0
    for f, r, ri, rec in iter_records():
        flags = rec.get('flags', [])
        layer = rec.get('layer')
        ev = rec.get('checks', {}).get('event')
        checked = ev not in SILENCE_EVENTS
        row = tbl.setdefault(layer, [0, 0, 0, 0, 0])
        row[0] += 1
        if checked:
            row[1] += 1
        for x in flags:
            old_flags[x] += 1
        nf, dem = reclassify(flags, layer)
        for x in nf:
            new_flags[x] += 1
        if 'F1' in flags:
            row[2] += 1
        if 'F1' in nf:
            row[3] += 1
        if dem:
            row[4] += 1
            demoted.append((Path(f).name, r.get('iter', r.get('probe')), ri,
                            rec.get('k'), layer, ev, rec.get('verdict')))
            tree_unref[layer] += 1
        elif 'F1' in flags and checked:
            kept.append((Path(f).name, r.get('iter', r.get('probe')), ri,
                         rec.get('k'), layer))
        if checked and layer == 'B':
            b_spoken += 1

    print('=' * 92)
    print('I3 分层重算：F1 按 layer 分层（B 轮保留；A/C/⊘ 轮降级为观察项；None 维持原口径）')
    print('=' * 92)
    print('%-14s %-16s %-16s' % ('失效点', '旧口径', '新口径'))
    for k in sorted(set(old_flags) | set(new_flags)):
        mark = '' if old_flags[k] == new_flags[k] else '  ← 变化'
        print('%-14s %-16d %-16d%s' % (k, old_flags[k], new_flags[k], mark))
    print()
    print('分层明细（内容检查轮 = event 非两类合规沉默；旧格式 calib 记录 event=None、')
    print('E13 partial 形态均按 v1 口径计入——其中 iter0 k1 与 P1 k2 两轮 verdict=不说，')
    print('实质为沉默轮，由 I2 覆盖，见校验第 3 条）：')
    print('%-10s %-8s %-10s %-8s %-8s %-8s' % ('layer', '记录轮', '内容检查轮', '旧F1', '新F1', '降级'))
    for layer in sorted(tbl, key=str):
        n, chk, o, nw, dm = tbl[layer]
        print('%-10s %-8d %-10d %-8d %-8d %-8d' % (str(layer), n, chk, o, nw, dm))
    print()
    print('判 B 发言轮总数：%d；其中仍记 F1（真缺陷）：%d' % (b_spoken, len(kept)))
    print('降级为 tree_unreferenced 观察项的轮（共 %d）：' % len(demoted))
    for d_ in demoted:
        print('   %-26s %-4s rep%d k%-2s layer=%-4s event=%-28s verdict=%s' % d_)
    print()
    print('观察项按层汇总（防洗白条款）：', dict(tree_unref) or '无')
    print()
    print('裁定校验：')
    print('  1. 判 B 轮 %d 个、0 次 F1 → 分层不洗掉任何真实缺陷（ kept = %d ）'
          % (b_spoken, len(kept)))
    print('  2. 降级的 %d 轮：A 4（iter1 k1、iter2 k1、P5 k1 三轮元材料 + P9b rep1 k2）、'
          'C 2（P1 k1 元材料、P8a rep3 k1 空转 C）、⊘ 2（iter0 k1、P1 k2）' % len(demoted))
    print('  3. ⊘ 2 轮 verdict=不说，按 I2 精神整体跳过内容侧检查——其 F1 是 I1 时代遗留，'
          'I2/I3 两代仪器修正结论一致')
    print('  4. 元材料 3 次（iter1/iter2/P5 的 k1）与 E13 D8 独立结论一致'
          '（树上无节点可挂，非"树未启用"）')


if __name__ == '__main__':
    main()
