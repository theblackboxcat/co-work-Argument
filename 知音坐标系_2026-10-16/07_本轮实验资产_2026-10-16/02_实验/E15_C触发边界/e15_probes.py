#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E15 探针：C 的触发边界——甲对账但材料不构成矛盾（承接 E14 §6 第 2 条）
=====================================================================

问题（E14 §6 第 2 条）：P9a 证明了"甲对账挑矛盾"触发真 C（3/3）。
下一步测 C 的边界——**甲对账但两段材料不构成矛盾**时，模型判 C（有账就对）
还是判 A？这直接检验"分类学不对称"还剩多少：
  - 若判 C 且 body 如实报告"账对上了/两段并不矛盾"→ C 条件于**甲的要求**，
    与材料是否真实矛盾无关（对账是动作承诺，不是矛盾探测器）；
  - 若判 C 且 body 硬凑一个矛盾 → 迎合甲框架（空转 C 的变体：有历史可核但核出
    不存在的矛盾）；
  - 若判 A → C 需要真实矛盾存在（分类学不对称比 E14 D1 结论更强：
    B/C 不仅条件于问句，还条件于材料内容）；
  - 若沉默 → 零增量机制在此形态上工作。

单变量设计（与 P9a 的唯一差异 = k2 材料）：
  P9a  [m1, m3, ASK_RECON]  m1（幻想是优点）vs m3（损伤注意力）= 现成矛盾对
  P10a [m1, m2, ASK_RECON]  m1（幻想让生活有了意义）vs m2（幻想有局限性、
                            走向无聊）= 软张力，不构成矛盾（m2 从未否定 m1 的
                            价值判断，只补充局限）；第三段问句与 P9a 逐字相同
  （P8a/P8b 已建立 [m1, m2] 基线：干净陈述下 3/3 合规沉默）

材料对的主题域相同（都是幻想），排除了"话题不相关"混淆；矛盾性（有/无）
是唯一变量。reps=3（E13 D3/E14 D5：temp=0.5 单轮不下强结论）。

仪器：import e14_probes 复用其 probe()/summarize_reps()——I2（verdict=不说
整体跳过内容侧检查）与 I3（F1 按 layer 分层，A/C 轮降级 tree_unreferenced）
原样继承，不在本轮重造。e14_probes 模块级断言（等长核对）随之执行，通过。

数据：e15_P10a.json（3 reps）；对照 P9a 数据从 e14_P9a.json 读取，
不与 E14 归档数据重复跑（省额度，且对照条件已固化）。
"""
import json
import argparse
from pathlib import Path

import e14_probes as E14
import calib_loop as CL

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reps', type=int, default=3)
    args = ap.parse_args()

    name = 'P10a'
    note = 'C 触发边界：甲对账（ASK_RECON 逐字同 P9a）但材料对 m1/m2 不构成矛盾'
    mats = [1, 2, {'kind': 'constructed', 'text': E14.ASK_RECON}]

    runs = [E14.probe(name, note, mats, CL.LINE_B_FMTFIX, max_turns=6)
            for _ in range(args.reps)]
    out = HERE / 'e15_P10a.json'
    json.dump({'probe': name, 'note': note, 'reps_n': args.reps, 'runs': runs},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    s = E14.summarize_reps(name, runs)
    print('=' * 96)
    print('[%s] %s' % (name, note))
    for row in s['reps']:
        print('  rep%d: layer=%s verdict=%s 发言%d 线A拦%d flags=%s tree_unref=%d'
              % (row['rep'], row['layers'], row['verdicts'], row['spoken'],
                 row['lineA'], row['flags'], row['tree_unref']))
    print('  构造轮 B·C 触发率：%s；真 B：%d；C 轮旧账引用度：%s'
          % (s['trig_rate'], s['trueB'], s['c6_on_C']))
    print('  输出：', out)

    # ---- 与 P9a（矛盾对，已入档）逐条件对照 ----
    p9 = json.load(open(HERE / 'e14_P9a.json', encoding='utf-8'))
    p9_k3 = []
    for ri, r in enumerate(p9['runs'], 1):
        for h in r['log']:
            if h['who'] == 'B' and 'rec' in h and h['rec']['mat_kind'] == 'constructed':
                p9_k3.append((ri, h['rec']))
    print('=' * 96)
    print('对照（同一 ASK_RECON，唯一差异 = k2 材料 m3 矛盾 vs m2 非矛盾）：')
    print('  P9a （m1/m3 矛盾对）构造轮：%s'
          % [(ri, r['verdict'], r['layer']) for ri, r in p9_k3])
    k3_here = []
    for ri, r in enumerate(runs, 1):
        for h in r['log']:
            if h['who'] == 'B' and 'rec' in h and h['rec']['mat_kind'] == 'constructed':
                k3_here.append((ri, h['rec']))
    print('  P10a（m1/m2 非矛盾）构造轮：%s'
          % [(ri, r['verdict'], r['layer']) for ri, r in k3_here])
    for ri, r in k3_here:
        print('  --- P10a rep%d k3 body（前 300 字）---' % ri)
        print('   ', (r.get('body') or '')[:300].replace('\n', ' '))


if __name__ == '__main__':
    main()
