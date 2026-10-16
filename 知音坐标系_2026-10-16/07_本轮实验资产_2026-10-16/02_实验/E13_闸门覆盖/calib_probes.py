#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E13 探针集：沉默/闸门/终止线的零覆盖区 + layer 坍缩判别
=====================================================

背景（E12 记录的两个零覆盖区）：
  1. 三轮 18 轮中 echo 全部 0.00、代码预算从未触发、verdict=不说 仅 iter0 k1 一次——
     **闸门系统（回声/预算）与模型侧沉默机制等于没被检验过**（系统的另一半）。
  2. layer 分布 18/18 全部坍缩为 A，未判别是 prompt 顺序偏置还是材料形态偏置。

本脚本不动 calib_loop.py（v1 历史产物，保持可复现），import 它复用同一套仪器
（call/split_verdict/check_turn/tree_view/grams/jac/ECHO_T/LINE_B_FMTFIX），
保证 E4→E12→E13 口径一致。

固定继承配置（iter2 的修复，E12 已泛化验证）：
  - fmt_fix 提示词（无「第X行」字面标签）
  - history_full（我方历史消息保留三行原样 out_raw）
  - sparse 树注入（tree_full 不纳入本轮——避免与输入侧变量混淆）

仪器修正 I1（记录在案，只在本脚本生效）：
  v1 的 else 分支把 body=='⊘' 一律记 F4；但按 fmt_fix 提示词，
  「verdict: 不说 / layer: X / ⊘」恰是**合规的沉默三行**，会被误判为格式漂移。
  E12 数据中该分支未触发（iter0 k1 的 body 是「第三行：⊘」≠'⊘'），
  但 E13 专测沉默必踩此坑，故修正：
    合规沉默 = verdict=='不说' 且 body=='⊘' → 不计 F4，记 event=model_silence
    F4 只保留三种真漂移：结构行丢失（v/layer 为 None）/ body 为空 / 说而⊘自相矛盾
  F3?（沉默误判观察口径）只在**新材料**轮上标记： filler/repeat 类输入沉默是待测机制，不是误判。

探针（单变量纪律：每个探针只改一样东西）：
  P1 词面重复    材料=[m0, m0]                    测：词面回声闸门是否点火 / 模型是否自选沉默
  P2 回贴        材料=[m0, {ECHO_BACK}]           测：回声闸门保底点火 + 终止行为（echo=1.00）
  P3 预算        max_turns=3, 材料=m0..m5         测：预算闸门终端止
  P4 零增量      材料=[m0, 嗯。, （点头，没说话）, m1, ……, m2]   测：模型侧沉默机制 + 沉默后恢复
  P5 layer 乱序  LINE_B 的 A/B/C 列出序改为 B/C/A，材料=m0..m5（与 iter2 同材料）
                                                测：layer 坍缩是 prompt 顺序偏置还是材料偏置

用法：
  python3 calib_probes.py            # 跑全部五个探针
  python3 calib_probes.py --only P4  # 只跑指定探针
输出：e13_P{1..5}_*.json + 终端摘要
"""
import json
import time
import argparse
from pathlib import Path
from collections import Counter

import calib_loop as CL   # 复用仪器；import 时有 __main__ 保护，不会执行 main()

HERE = Path(__file__).resolve().parent
TRUNK = HERE / 'trunk_v8_错位默认_DRAFT.json'
CORPUS = HERE / 'corpus_pool.json'

# ---- P5 单变量：只把 A/B/C 的列出顺序改成 B/C/A，其余与 LINE_B_FMTFIX 逐字相同 ----
_ORDER_BLOCK = """- A 思路性：回映它，但不得替甲把它命名成某个节点或结论。
- B 结构性：指位置，不给方案。
- C 情节性：核对已说过的是否能对上账，不预测。
- ⊘：若你确实没有真实的方向增量。"""
_ORDER_BLOCK_SHUFFLED = """- B 结构性：指位置，不给方案。
- C 情节性：核对已说过的是否能对上账，不预测。
- A 思路性：回映它，但不得替甲把它命名成某个节点或结论。
- ⊘：若你确实没有真实的方向增量。"""
LINE_B_SHUFFLE = CL.LINE_B_FMTFIX.replace(_ORDER_BLOCK, _ORDER_BLOCK_SHUFFLED)
_sl = LINE_B_SHUFFLE.split('\n')
assert _sl[6].startswith('- B') and _sl[7].startswith('- C') and _sl[8].startswith('- A'), \
    'P5 乱序替换失败——检查 _ORDER_BLOCK 与 LINE_B_FMTFIX 是否逐字一致'
assert LINE_B_SHUFFLE != CL.LINE_B_FMTFIX


def probe(name, note, materials, line_b, max_turns=6):
    """与 calib_loop.run_iter 同构的一轮循环；差异只有三处（均在注释中声明）：
    ① 材料支持 {ECHO_BACK} 占位（P2 需要把上一轮发言原样回贴）；
    ② history_full 恒开（继承 iter2 修复，不再作为变量）；
    ③ I1 修正的沉默/格式分类。
    """
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    corpus = json.load(open(CORPUS, encoding='utf-8'))
    mats = [corpus[m] if isinstance(m, int) else m for m in materials]
    # 材料类型标注（fresh 首次出现 / repeat 重复出现 / filler 零增量 / echo_back 回贴）
    seen, kinds = set(), []
    for m in materials:
        if m == '{ECHO_BACK}':
            kinds.append('echo_back')
        elif isinstance(m, int):
            kinds.append('repeat' if m in seen else 'fresh')
            seen.add(m)
        else:
            kinds.append('filler')

    tree_block = "\n\n树（位置必须来自它）：\n" + CL.tree_view(trunk, full=False)
    log, last_body, spoken = [], None, 0
    end, et = '材料用尽', len(mats)
    for k, (mat, kind) in enumerate(zip(mats, kinds), 1):
        if mat == '{ECHO_BACK}':
            mat = last_body if last_body else '（我方上一轮未发言，无可回贴）'
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
        # ---------- 线 B：模型生成（history_full 恒开） ----------
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
        # ---------- I1 修正后的分类 ----------
        spec_silence = (v == '不说' and body == '⊘')
        if spec_silence:
            checks, flags = {'C4_format_ok': True, 'event': 'model_silence'}, []
            silent_by_model = True
        else:
            silent_by_model = (v == '不说') or (body == '⊘')
            if body and body != '⊘':
                checks, flags = CL.check_turn(body, mat, last_body, trunk, v, layer)
                checks['event'] = 'speech' if not silent_by_model else 'partial'
            else:
                checks = {'C4_format_ok': False,
                          'event': 'say_but_silent' if v == '说' else 'empty_or_drift'}
                flags = ['F4']
        # F3? 只在新材料轮标记（filler/repeat 沉默是待测机制，非误判）
        if silent_by_model and not hard and kind == 'fresh':
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
            spoken += 1
        print("=" * 96)
        print("[%s k%d/%s] echo=%.2f budget=%d verdict=%s layer=%s flags=%s (%.1fs)"
              % (name, k, kind, echo, budget_left, v, layer, flags or '无', rec['latency_s']))
        print("  材料:", mat[:80].replace('\n', ' '))
        print("  输出:", (body or out)[:180].replace('\n', ' '))
        if checks.get('C1_tree_used') is not None:
            print("  树引用:", checks['C1_tree_used'] or '无',
                  " 复述=%.2f 自重复=%.2f" % (checks['C2_overlap_material'], checks['C5_selfrep']))
    return {'probe': name, 'note': note, 'calib': 'fmt_fix+history_full(继承)',
            'max_turns': max_turns, 'end': end, 'end_turn': et,
            'spoken': spoken, 'log': log}


def summarize(runs):
    mt = [h['rec'] for h in runs['log'] if h['who'] == 'B' and 'rec' in h]
    la = [h for h in runs['log'] if h['who'] == 'B' and 'rec' not in h]
    flags = Counter(f for r in mt for f in r['flags'])
    layers = Counter(r['layer'] for r in mt if r['layer'] and r['layer'] != '⊘')
    verdicts = Counter(r['verdict'] for r in mt)
    events = Counter(r['checks'].get('event') for r in mt)
    echo_max = max([r['witness']['echo'] for r in mt], default=0.0)
    selfrep_max = max([r['checks'].get('C5_selfrep', 0.0) for r in mt], default=0.0)
    tree_rounds = sum(1 for r in mt if r['checks'].get('C1_tree_used'))
    print("-" * 96)
    print("[%s] %s" % (runs['probe'], runs['note']))
    print("  喂入 %d 段 / 模型轮 %d / 线A拦 %d / 实际发言 %d / 终止：%s（第 %s 段）"
          % (len(mt) + len(la), len(mt), len(la), runs['spoken'], runs['end'], runs['end_turn']))
    print("  verdict 分布:", dict(verdicts), " layer 分布:", dict(layers) or '无')
    print("  事件:", dict(events), " 失效点:", dict(flags) or '零失效点')
    print("  echo 峰值=%.2f 自重复峰值=%.2f 树引用轮数=%d" % (echo_max, selfrep_max, tree_rounds))
    return {'probe': runs['probe'], 'note': runs['note'], 'fed': len(mt) + len(la),
            'model_turns': len(mt),
            'lineA': len(la), 'spoken': runs['spoken'], 'end': runs['end'],
            'verdicts': dict(verdicts), 'layers': dict(layers),
            'events': dict(events), 'flags': dict(flags) or '零失效点',
            'echo_max': echo_max, 'selfrep_max': selfrep_max, 'tree_rounds': tree_rounds}


PROBES = [
    ('P1', '词面重复：测词面回声闸门是否点火 / 模型是否自选沉默',
     [0, 0], CL.LINE_B_FMTFIX, 6),
    ('P2', '回贴：echo=1.00 保底点火，测回声闸门终端止行为',
     [0, '{ECHO_BACK}'], CL.LINE_B_FMTFIX, 6),
    ('P3', '预算：max_turns=3 喂 6 段新材料，测预算闸门终端止',
     [0, 1, 2, 3, 4, 5], CL.LINE_B_FMTFIX, 3),
    ('P4', '零增量： filler 输入测模型侧沉默机制 + 沉默后恢复',
     [0, '嗯。', '（点头，没说话）', 1, '……', 2], CL.LINE_B_FMTFIX, 6),
    ('P5', 'layer 乱序：A/B/C 列出序改 B/C/A，同材料对照 iter2',
     [0, 1, 2, 3, 4, 5], LINE_B_SHUFFLE, 6),
    # ---- 第二波：P3 的两次新材料沉默，单变量对照（预算显示 3 vs 6）----
    ('P6', '预算对照：max_turns=6 同材料（对照 iter2/P3，兼作仪器交叉核验）',
     [0, 1, 2, 3, 4, 5], CL.LINE_B_FMTFIX, 6),
    ('P7', 'P3 原样重跑：max_turns=3 同材料（判别沉默是预算显示效应还是采样噪声）',
     [0, 1, 2, 3, 4, 5], CL.LINE_B_FMTFIX, 3),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='', help='只跑指定探针，如 P4')
    args = ap.parse_args()
    summary = []
    for name, note, mats, lb, mt in PROBES:
        if args.only and name != args.only:
            continue
        runs = probe(name, note, mats, lb, max_turns=mt)
        out = HERE / ('e13_%s_%s.json' % (name, {'P1': 'echo_repeat', 'P2': 'echo_back',
                                                 'P3': 'budget', 'P4': 'zero_increment',
                                                 'P5': 'layer_shuffle', 'P6': 'budget_ctrl',
                                                 'P7': 'budget_repeat'}[name]))
        json.dump(runs, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        summary.append(summarize(runs))
        print("  输出：", out)
    print("=" * 96)
    print("E13 汇总")
    print("%-4s %-28s %5s %5s %5s %6s %-22s %-18s %s"
          % ('探针', '测什么', '喂入', '模型轮', '线A拦', '发言', 'verdict', 'layer', '失效点'))
    for s in summary:
        print("%-4s %-28s %5d %5d %5d %6d %-22s %-18s %s"
              % (s['probe'], s['note'].split('：')[0][:12], s['fed'], s['model_turns'],
                 s['lineA'], s['spoken'], str(s['verdicts']), str(s['layers']), s['flags']))


if __name__ == '__main__':
    main()
