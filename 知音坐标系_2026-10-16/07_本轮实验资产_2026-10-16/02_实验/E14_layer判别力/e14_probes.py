#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E14 探针：layer 判别力——B/C 触发材料构造（承接 E13 D4）
=========================================================

背景（E13 D4 遗留）：E12+E13 合并 38 个可判别发言轮 A36 / C2 / B0，
判层信号实质是常量输出。顺序偏置已被 P5 否证（A 列末位仍 6/6 A）。
剩余根因候选：① 材料形态偏置——私人叙述天然引发"回映"（A），
B 要"指位置"、C 要"核对旧账"都要求特定材料形态；② 分类学不对称——
A 对任何材料都成立，B/C 是条件性的。

本脚本单变量检验候选①：只改材料形态（prompt LINE_B / 树 / max_turns 全部不动），
构造 B/C 的触发问句，各配一个等长非触发对照，跑 reps=3 治采样噪声
（E13 D3：temp=0.5 两度造成误判风险，单轮结果不下强结论）。

探针（单变量纪律：触发句 vs 等长对照句是唯一差异）：
  P8a  [m1, m2, 甲问位置]      B 触发：第三段甲直接问"树上哪个位置"
  P8b  [m1, m2, 等长陈述]      对照：同前两轮，第三段换成等长非询问陈述
  P9a  [m1, m3, 甲对账挑矛盾]  C 触发：m1（幻想是优点）与 m3（损伤注意力）
                               是语料池现成矛盾对，第三段甲要求对上账
  P9b  [m1, m3, 等长陈述]      对照：同前两轮，第三段换成等长非对账陈述

仪器修正（记录在案，只在本脚本生效）：
  I2：v1/I1 只把 body=='⊘' 且 verdict=='不说' 记为合规沉默；verdict=='不说'
  但正文带理由的轮（D6 的 partial 形态，如 P1 k2）仍会走过 check_turn，
  收集到无意义的 F1（理由句当然不引用节点）。修正：verdict=='不说' 的轮
  **整体跳过内容侧检查**（F1/F2/F5），只记录格式形态：
    body=='⊘' 或 body==''（仅格式行输出）→ event=model_silence
    body==理由句        → event=model_silence_with_reason（D6 形态，记录不判缺陷）
  '说而⊘'矛盾（verdict=说 但 body 为 ⊘/空）仍记 F4。
  I2b（2026-10-16 第三角审计发现）：body=='' 的沉默轮（out_raw 仅
  'verdict:/layer:' 两行、无正文）原被误标 with_reason——模型没给理由，
  是格式完整的合规沉默。全史仅 1 轮命中（e14_P9b rep1 k3），已按 I2b
  重标并留注。E14 记录总表该格原写"合规沉默"（正确），是数据标签错。
  I3（2026-10-16 作者授权"你判断"后裁定）：F1 按 layer 分层——只有 layer=B 的
  发言轮不引节点记失效点（B"指位置"承诺引节点，判 B 不引 = 言行矛盾）；
  A/C 轮降级为观察项 tree_unreferenced（A"不得替甲命名节点"/C"核对旧账"
  均不承诺引节点）；layer=None（漂移）维持原口径；沉默轮已由 I2 跳过。
  重算验证见 i3_recompute.py：全史 8 次 F1 无一次在 B 轮，分层不洗掉真实缺陷。

质量维度（E14 新增记录项，不改变失效点口径）：
  C6_old_refs：本轮 body 与我方**全部前序** body 的最大 4-gram 重合
               （C 的"核对旧账"应有旧账引用；与 C5 只比上一轮不同）
  B 真伪：layer=B 且 C1_tree_used 非空 = 真指位置；layer=B 但无树引用 = 形 B

材料来源标注：m1/m2/m3 = corpus_pool.json 真实私人语料（index 1/2/3）；
第三段为**构造材料**（非语料池），结论只针对"材料形态→判层"关系，
不外推为真实语料上的表现（合成材料纪律）。

端点注（2026-10-16 作者裁定）：jev/qwen2:7b 端点可靠性存疑（开发时刚发布，
如今形势已变），端点迁移不再是阻塞项；本实验继续用 dots3-note-prev，
端点单一性记为已知局限（与 README 已知限制同一条）。

用法：
  python3 e14_probes.py            # 全部 4 探针 × 3 reps
  python3 e14_probes.py --only P8a # 只跑指定探针
  python3 e14_probes.py --reps 1   # 每探针重复次数（默认 3）
输出：e14_{探针}.json（含 reps 列表与汇总）
"""
import json
import time
import argparse
from pathlib import Path
from collections import Counter

import calib_loop as CL   # 复用仪器；v1 脚本不动，口径与 E4→E12→E13 一致

HERE = Path(__file__).resolve().parent
TRUNK = HERE / 'trunk_v8_错位默认_DRAFT.json'
CORPUS = HERE / 'corpus_pool.json'

# ---- 构造材料（第三段；触发句与等长对照句是唯一变量）----
# 甲的口吻参照语料池真实对话：口语、直接。
ASK_POS = ("你刚说的这些，在咱们那棵树上是个什么位置？我每次看都绕进去了，"
           "你直接指给我看，指个节点就行。")
CTRL_POS = ("你刚说的这些我先收着，今天的材料就带到这儿，剩下的下次再说，"
            "回头我们再接着往下聊别的。")
ASK_RECON = ("你前面说这个是优点，刚才那段说的正好相反。你把自己前后说的话"
             "对上一下账，看看哪儿对不上。")
CTRL_RECON = ("你前面说的我记下了，刚才那段我也收下了，两段都先放在这儿，"
              "哪天想起来了再翻出来看。")

# ---- P8/P9 的等长核对（字符数差 <10%，确保"等长"不是空话）----
assert abs(len(ASK_POS) - len(CTRL_POS)) / max(len(ASK_POS), len(CTRL_POS)) < 0.10, \
    'P8 触发/对照长度差超 10%'
assert abs(len(ASK_RECON) - len(CTRL_RECON)) / max(len(ASK_RECON), len(CTRL_RECON)) < 0.10, \
    'P9 触发/对照长度差超 10%'


def old_refs(body, prev_bodies):
    """C6：body 与我方全部前序 body 的最大 4-gram 重合（旧账引用度）。"""
    if not prev_bodies:
        return 0.0
    g = CL.grams(body)
    return max(CL.jac(g, CL.grams(p)) for p in prev_bodies if p)


def probe(name, note, materials, line_b, max_turns=6):
    """与 calib_loop.run_iter / e13 probe 同构；差异：
    ① I2 修正的沉默轮分类（verdict=不说 整体跳过内容侧检查）；
    ② 材料支持 dict 形态 {'kind': 'constructed'|'control', 'text': ...}；
    ③ 新增 C6_old_refs 记录项。
    """
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    corpus = json.load(open(CORPUS, encoding='utf-8'))
    mats, kinds = [], []
    for m in materials:
        if isinstance(m, int):
            mats.append(corpus[m]); kinds.append('fresh_corpus')
        elif isinstance(m, dict):
            mats.append(m['text']); kinds.append(m['kind'])
        else:
            mats.append(m); kinds.append('filler')

    tree_block = "\n\n树（位置必须来自它）：\n" + CL.tree_view(trunk, full=False)
    log, last_body, prev_bodies, spoken = [], None, [], 0
    end, et = '材料用尽', len(mats)
    for k, (mat, kind) in enumerate(zip(mats, kinds), 1):
        log.append({'who': 'ME', 'text': "（第 %d 段）%s" % (k, mat)})
        # ---------- 线 A：事前 witness（与 v1 同口径） ----------
        echo = CL.jac(CL.grams(last_body), CL.grams(mat)) if last_body else 0.0
        budget_left = max_turns - spoken
        hard = []
        if budget_left <= 0:
            hard.append('预算用尽')
        if echo > CL.ECHO_T:
            hard.append('回声 %.2f' % echo)
        witness = ("- 刚进来的材料与你自己上一轮发言的重合度：%.2f\n"
                   "- 预算剩余：%d 次\n- 规则层硬条件触发：%s"
                   % (echo, budget_left, '、'.join(hard) if hard else '无'))
        if hard:
            log.append({'who': 'B', 'text': '⊘', 'silent': True,
                        'by': '线A规则层', 'why': '、'.join(hard)})
            if '预算用尽' in hard or '回声' in '、'.join(hard):
                end, et = '线A规则层终止（' + '、'.join(hard) + '）', k
                break
            continue
        # ---------- 线 B：模型生成（history_full 恒开，继承 iter2 修复） ----------
        msgs = []
        for h in log:
            content = h['text']
            if h['who'] == 'B' and h.get('out_raw'):
                content = h['out_raw']
            msgs.append({'role': ('user' if h['who'] == 'ME' else 'assistant'),
                         'content': content})
        t0 = time.time()
        try:
            out = CL.call(line_b.replace('{witness}', witness) + tree_block, msgs)
        except Exception as e:
            out = "[ERROR] %s" % e
        v, layer, body = CL.split_verdict(out)
        # ---------- I2 修正后的分类 ----------
        fmt_struct_ok = bool(v) and bool(layer)
        if v == '不说':
            # 沉默轮整体跳过内容侧检查（I2）：只记录格式形态
            silent_by_model = True
            if body in ('⊘', ''):
                # I2b：body=='' = out_raw 仅格式行（verdict:/layer:）、无正文——
                # 模型未给理由，属格式完整的合规沉默（第三角审计发现，全史 1 例：
                # e14_P9b rep1 k3 原误标 with_reason）
                checks, flags = {'C4_format_ok': fmt_struct_ok,
                                 'event': 'model_silence'}, []
            else:
                checks, flags = {'C4_format_ok': fmt_struct_ok,
                                 'event': 'model_silence_with_reason'}, []
            if not fmt_struct_ok:
                flags.append('F4')
        elif not body or body == '⊘':
            # verdict=说 但正文为空/⊘：自相矛盾，仍是 F4
            silent_by_model = True
            checks = {'C4_format_ok': False, 'event': 'say_but_silent'}
            flags = ['F4']
        else:
            silent_by_model = False
            checks, flags = CL.check_turn(body, mat, last_body, trunk, v, layer)
            checks['event'] = 'speech'
            checks['C6_old_refs'] = round(old_refs(body, prev_bodies), 3)
        # ---------- I3 修正：F1 按 layer 分层（2026-10-16 作者授权裁定） ----------
        # B"指位置，不给方案"承诺引节点：判 B 不引节点 = 言行矛盾，保留 F1（真缺陷）；
        # A"不得替甲命名成节点"/C"核对旧账"不承诺引节点：降级为观察项 tree_unreferenced；
        # layer=None（漂移轮）无从判定承诺，维持原口径；沉默轮已由 I2 跳过内容检查。
        # 防洗白：tree_unreferenced 按层汇总——"既不判 B 也不引节点"的系统性模式会显出来。
        if 'F1' in flags and layer not in ('B', None):
            flags.remove('F1')
            checks['tree_unreferenced'] = True
        # F3? 口径同 E13：新材料轮上无硬条件的沉默 / 有硬条件仍想说
        if silent_by_model and not hard and kind in ('fresh_corpus', 'constructed'):
            flags.append('F3?')
        if (not silent_by_model) and hard:
            flags.append('F3?')
        rec = {'k': k, 'mat_kind': kind, 'material': mat,
               'witness': {'echo': round(echo, 3), 'budget_left': budget_left, 'hard': hard},
               'verdict': v, 'layer': layer, 'body': (body or out)[:400],
               'checks': checks, 'flags': flags, 'latency_s': round(time.time() - t0, 1)}
        log.append({'who': 'B', 'text': body or out, 'out_raw': out,
                    'silent': silent_by_model, 'layer': layer, 'rec': rec})
        if not silent_by_model:
            last_body = body or out
            prev_bodies.append(last_body)
            spoken += 1
        print("=" * 96)
        print("[%s k%d/%s] echo=%.2f budget=%d verdict=%s layer=%s flags=%s (%.1fs)"
              % (name, k, kind, echo, budget_left, v, layer, flags or '无', rec['latency_s']))
        print("  材料:", mat[:80].replace('\n', ' '))
        print("  输出:", (body or out)[:180].replace('\n', ' '))
        if checks.get('C1_tree_used') is not None:
            print("  树引用:", checks['C1_tree_used'] or '无',
                  " 复述=%.2f 自重复=%.2f 旧账引用=%.2f"
                  % (checks['C2_overlap_material'], checks['C5_selfrep'],
                     checks.get('C6_old_refs', 0.0)))
    return {'probe': name, 'note': note, 'calib': 'fmt_fix+history_full(继承)',
            'max_turns': max_turns, 'end': end, 'end_turn': et,
            'spoken': spoken, 'log': log}


PROBES = [
    ('P8a', 'B 触发：甲问位置（构造材料第三段）',
     [1, 2, {'kind': 'constructed', 'text': ASK_POS}], CL.LINE_B_FMTFIX, 6),
    ('P8b', 'P8a 对照：等长陈述（无位置询问）',
     [1, 2, {'kind': 'control', 'text': CTRL_POS}], CL.LINE_B_FMTFIX, 6),
    ('P9a', 'C 触发：矛盾对 m1/m3 + 甲对账挑矛盾（构造材料第三段）',
     [1, 3, {'kind': 'constructed', 'text': ASK_RECON}], CL.LINE_B_FMTFIX, 6),
    ('P9b', 'P9a 对照：等长陈述（无对账）',
     [1, 3, {'kind': 'control', 'text': CTRL_RECON}], CL.LINE_B_FMTFIX, 6),
]


def run_probe_reps(name, note, mats, lb, mt, reps):
    return [probe(name, note, mats, lb, max_turns=mt) for _ in range(reps)]


def summarize_reps(name, reps_runs):
    """跨 rep 汇总：层分布、B/C 触发率、质量维度、稳定性。"""
    rows = []
    for ri, r in enumerate(reps_runs, 1):
        recs = [h['rec'] for h in r['log'] if h['who'] == 'B' and 'rec' in h]
        la = [h for h in r['log'] if h['who'] == 'B' and 'rec' not in h]
        layers = Counter(x['layer'] for x in recs if x['layer'] and x['layer'] != '⊘')
        rows.append({'rep': ri, 'layers': dict(layers),
                     'verdicts': dict(Counter(x['verdict'] for x in recs)),
                     'flags': dict(Counter(f for x in recs for f in x['flags'])),
                     'tree_unref': sum(1 for x in recs
                                       if x['checks'].get('tree_unreferenced')),
                     'spoken': r['spoken'], 'lineA': len(la),
                     'end': r['end']})
    # 触发率：构造/对照轮上出现 B 或 C 的比例（只统计模型实际发言的构造轮）
    trig, tot = 0, 0
    trueB, c6_on_C = 0, []
    for r in reps_runs:
        recs = [h['rec'] for h in r['log'] if h['who'] == 'B' and 'rec' in h]
        for x in recs:
            if x['mat_kind'] in ('constructed', 'control') and x['checks'].get('event') == 'speech':
                tot += 1
                if x['layer'] in ('B', 'C'):
                    trig += 1
                if x['layer'] == 'B' and x['checks'].get('C1_tree_used'):
                    trueB += 1
                if x['layer'] == 'C':
                    c6_on_C.append(x['checks'].get('C6_old_refs', 0.0))
    return {'probe': name, 'reps': rows,
            'trig_rate': '%d/%d' % (trig, tot),
            'trueB': trueB, 'c6_on_C': c6_on_C}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='', help='只跑指定探针，如 P8a')
    ap.add_argument('--reps', type=int, default=3)
    args = ap.parse_args()
    summary = []
    for name, note, mats, lb, mt in PROBES:
        if args.only and name != args.only:
            continue
        runs = run_probe_reps(name, note, mats, lb, mt, args.reps)
        out = HERE / ('e14_%s.json' % name)
        json.dump({'probe': name, 'note': note, 'reps_n': args.reps, 'runs': runs},
                  open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        s = summarize_reps(name, runs)
        summary.append(s)
        print("=" * 96)
        print("[%s] %s" % (name, note))
        for row in s['reps']:
            print("  rep%d: layer=%s verdict=%s 发言%d 线A拦%d flags=%s tree_unref=%d"
                  % (row['rep'], row['layers'], row['verdicts'], row['spoken'],
                     row['lineA'], row['flags'], row['tree_unref']))
        print("  构造/对照轮 B·C 触发率：%s；真 B（判 B 且引节点）：%d；C 轮旧账引用度：%s"
              % (s['trig_rate'], s['trueB'], s['c6_on_C']))
        print("  输出：", out)
    print("=" * 96)
    print("E14 汇总（B/C 触发率 = 构造或对照轮上判出 B/C 的发言轮占比）")
    for s in summary:
        print("%-4s 触发率=%-7s 真B=%d C轮旧账引用=%s"
              % (s['probe'], s['trig_rate'], s['trueB'], s['c6_on_C']))


if __name__ == '__main__':
    main()
