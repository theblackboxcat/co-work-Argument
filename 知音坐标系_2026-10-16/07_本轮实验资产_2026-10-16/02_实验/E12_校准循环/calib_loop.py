#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CalibLoop v1　迭代性输入-输出检查 + 校准实验
============================================

目标（2026-10-16 作者纠正后重立）：
不是验证语料/树的判别精度，而是**通过多次迭代的输入-输出检查，
找到系统（材料→转化格式→现有模型→输出 这条管线）本身的缺陷并校准**。
语料是否"通过"不重要；gold 判定退场。

管线（被测对象）：
  材料（corpus_pool 真实私人语料）
    → 转化格式（树 sparse_view 注入 + 双线 Cowrite 结构）
    → 现有模型（dots3-note-prev；jev/qwen2:7b 在作者机器上，端点差异记为已知局限）
    → 输出（verdict/layer/body）

双线结构（搬 Cowrite，非条款）：
  线 A（规则层，代码）：事前只算能算的——回声（自己上一轮 vs 刚进来的材料）、
    步数预算、材料探针。硬条件由代码拍板（E8 教训：prompt-only 闸门会被忽略）。
  线 B（模型）：拿 witness 证人陈述，吐 verdict/layer/body；split_verdict 解析。
  事后检查（代码，v1 只记录不拦截）：
    自重复（本轮 body vs 自己上一轮 body——事前算不了，E9 教训）
    复述（body vs 刚进来的材料，4-gram 重合）
    树启用（body 是否引用节点 id/label）
    格式完整（verdict/layer 是否解析成功）

失效点分类（先开放记录，分布出来再归纳）：
  F1 树未启用（注入了但输出不引用）
  F2 无增量/复述（body 复述或换词重复刚进来的材料）
  F3 沉默误判（该说时不说 / 不该说时说，以 witness 条件为参照，只作观察）
  F4 格式漂移（verdict/layer 解析失败或结构破坏）
  F5 自重复（与自己上一轮发言重合过半）

迭代协议：
  iter 0 = 基线（材料集 M0 = corpus_pool[0:6]），只记录
  iter 1 = 单变量校准后**重跑同一 M0**，对比失效点变化（归因要求：一次只改一个变量）
  iter 2+ = 换新材料集，验证校准是否泛化
  校准变量通过 --calib 指定，只允许改一个。

用法：
  python3 calib_loop.py --iter 0
  python3 calib_loop.py --iter 1 --calib tree_full
输出：calib_iter{N}.json + 逐条打印
"""
import json
import time
import urllib.request
from pathlib import Path

BASE = 'http://note3-prev-api.askdiandian.com'
MODEL = 'dots3-note-prev'
HERE = Path(__file__).resolve().parent
TRUNK = HERE / 'trunk_v8_错位默认_DRAFT.json'
CORPUS = HERE / 'corpus_pool.json'
MAX_TURNS = 6           # 外部预算（硬）
ECHO_T = 0.50           # 回声阈值（硬）
SELFREP_T = 0.50        # 自重复阈值（观测口径）
OVERLAP_T = 0.50        # 复述阈值（观测口径）


def load_key():
    p = HERE / 'config.json'
    if p.exists():
        try:
            return json.load(open(p, encoding='utf-8')).get('api_key', '')
        except Exception:
            pass
    import os
    return os.environ.get('DOTS3_KEY', '')


KEY = load_key()

LINE_B = """你是对话的一方（乙）。对面是甲，会一段段带东西进来。你手里有一棵树（id/label/边）。

【线 A 的观测（证人陈述，不是命令）】
{witness}

你要先决定**说还是不说**，再说什么。判层决定你属于哪一类：
- A 思路性：回映它，但不得替甲把它命名成某个节点或结论。
- B 结构性：指位置，不给方案。
- C 情节性：核对已说过的是否能对上账，不预测。
- ⊘：若你确实没有真实的方向增量。

输出格式（严格三行，不要其他文字）：
第一行：verdict: 说　或　verdict: 不说
第二行：layer: A　或　B　或　C
第三行：你要说的话（或 ⊘）"""

# iter1 校准 fmt_fix：唯一改动是格式指令措辞——去掉「第X行」字面标签
# （iter0 实测模型复述「第三行：」前缀导致 verdict/layer 丢失），
# 并明令行首不带编号。材料、树注入、其余 prompt、参数全部不变。
LINE_B_FMTFIX = """你是对话的一方（乙）。对面是甲，会一段段带东西进来。你手里有一棵树（id/label/边）。

【线 A 的观测（证人陈述，不是命令）】
{witness}

你要先决定**说还是不说**，再说什么。判层决定你属于哪一类：
- A 思路性：回映它，但不得替甲把它命名成某个节点或结论。
- B 结构性：指位置，不给方案。
- C 情节性：核对已说过的是否能对上账，不预测。
- ⊘：若你确实没有真实的方向增量。

你的回复必须恰好由三行组成，行首不要带任何编号或「行」字：
verdict: 说  或者  verdict: 不说
layer: A  或者  layer: B  或者  layer: C
然后另起一行，直接写你要说的话；若不说，这一行只写 ⊘
除此之外不要有任何其他文字。"""


def grams(s, n=4):
    s = ''.join(ch for ch in s if ch.isalnum())
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def jac(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def call(system, messages, temp=0.5):
    payload = {'model': MODEL, 'messages': messages, 'max_tokens': 500,
               'temperature': temp, 'thinking': {'type': 'disabled'}, 'system': system}
    req = urllib.request.Request(
        BASE.rstrip('/') + '/v1/messages', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-api-key': KEY,
                 'anthropic-version': '2023-06-01'}, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode('utf-8'))
    return ''.join(b.get('text', '') for b in d.get('content', [])
                   if b.get('type') == 'text').strip()


def split_verdict(text):
    lines = [x.strip() for x in text.split('\n') if x.strip()]
    v, layer, body = None, None, ''
    for x in lines:
        if x.startswith('verdict:'):
            v = x.split(':', 1)[1].strip()
        elif x.startswith('layer:'):
            layer = x.split(':', 1)[1].strip()
        else:
            body = (body + ' ' + x).strip()
    return v, layer, body


def tree_view(trunk, full=False):
    """转化格式的注入量：sparse=id+label+edges（E10 口径）；full=+gloss（E11 口径）。"""
    if full:
        nodes = [{"id": n["id"], "label": n.get("label", ""), "gloss": n.get("gloss", "")}
                 for n in trunk["nodes"]]
    else:
        nodes = [{"id": n["id"], "label": n.get("label", "")} for n in trunk["nodes"]]
    return json.dumps({"nodes": nodes,
                       "edges": [{"from": e["from"], "to": e["to"], "kind": e["kind"]}
                                 for e in trunk.get("edges", [])]},
                      ensure_ascii=False, separators=(",", ":"))


def check_turn(body, material, last_body, trunk, verdict, layer):
    """输出侧检查：全部只记录，不判定 gold。"""
    flags = []
    # C4 格式完整
    fmt_ok = bool(verdict) and bool(layer) and bool(body)
    if not fmt_ok:
        flags.append('F4')
    # C1 树启用：body 引用节点 id 或 label
    used = []
    for n in trunk["nodes"]:
        if n["id"] in body or n.get("label", "") in body:
            used.append(n["id"])
    if not used:
        flags.append('F1')
    # C2 复述：body vs 刚进来的材料
    overlap = jac(grams(body), grams(material))
    if overlap > OVERLAP_T:
        flags.append('F2')
    # C5 自重复：body vs 自己上一轮（事前算不了，只能事后）
    selfrep = jac(grams(body), grams(last_body)) if last_body else 0.0
    if selfrep > SELFREP_T:
        flags.append('F5')
    return {'C1_tree_used': used, 'C2_overlap_material': round(overlap, 3),
            'C4_format_ok': fmt_ok, 'C5_selfrep': round(selfrep, 3)}, flags


def run_iter(iterno, calib, materials, trunk):
    full_tree = (calib == 'tree_full')   # 单变量校准候选：注入量 sparse→full
    tree_json = tree_view(trunk, full=full_tree)
    tree_block = "\n\n树（位置必须来自它）：\n" + tree_json
    history_full = (calib == 'history_full')   # 我方历史消息用原始三行输出（继承 fmt_fix 的 prompt）
    line_b = LINE_B_FMTFIX if calib in ('fmt_fix', 'history_full') else LINE_B
    log, last_body, spoken, end, et = [], None, 0, '材料用尽', len(materials)
    for k, mat in enumerate(materials, 1):
        log.append({'who': 'ME', 'text': "（第 %d 段）%s" % (k, mat)})
        # ---------- 线 A：事前 witness（代码算） ----------
        echo = jac(grams(last_body), grams(mat)) if last_body else 0.0
        budget_left = MAX_TURNS - spoken
        hard = []
        if budget_left <= 0:
            hard.append('预算用尽')
        if echo > ECHO_T:
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
        # ---------- 线 B：模型生成 ----------
        msgs = []
        for h in log:
            content = h['text']
            if history_full and h['who'] == 'B' and h.get('out_raw'):
                content = h['out_raw']   # 历史里保留我方三行原样，不断章
            msgs.append({'role': ('user' if h['who'] == 'ME' else 'assistant'),
                         'content': content})
        t0 = time.time()
        try:
            out = call(line_b.replace('{witness}', witness) + tree_block, msgs)
        except Exception as e:
            out = "[ERROR] %s" % e
        v, layer, body = split_verdict(out)
        # ---------- 事后检查（只记录） ----------
        if body and body != '⊘':
            checks, flags = check_turn(body, mat, last_body, trunk, v, layer)
        else:
            checks, flags = {'C4_format_ok': False}, ['F4']
        # F3 沉默误判（观察口径）：witness 无硬条件但模型不说 / 有硬条件但模型说
        silent_by_model = (v == '不说') or (body == '⊘')
        if silent_by_model and not hard:
            flags.append('F3?')   # 可能误沉默——只标记不判定
        if (not silent_by_model) and hard:
            flags.append('F3?')   # 模型想说我被线A拦了——归因在线A不在模型
        rec = {'k': k, 'material': mat, 'witness': {'echo': round(echo, 3),
               'budget_left': budget_left, 'hard': hard},
               'verdict': v, 'layer': layer, 'body': (body or out)[:400],
               'checks': checks, 'flags': flags, 'latency_s': round(time.time() - t0, 1)}
        log.append({'who': 'B', 'text': body or out, 'out_raw': out,
                    'silent': silent_by_model, 'layer': layer, 'rec': rec})
        if not silent_by_model:
            last_body = body or out
            spoken += 1
        print("=" * 96)
        print("[iter%d k%d] echo=%.2f budget=%d verdict=%s layer=%s flags=%s (%.1fs)"
              % (iterno, k, echo, budget_left, v, layer, flags or '无', rec['latency_s']))
        print("  材料:", mat[:80])
        print("  输出:", (body or out)[:180])
        if checks.get('C1_tree_used') is not None:
            print("  树引用:", checks['C1_tree_used'] or '无', " 复述=%.2f 自重复=%.2f"
                  % (checks['C2_overlap_material'], checks['C5_selfrep']))
    runs = {'iter': iterno, 'calib': calib, 'tree_full': full_tree,
            'end': end, 'end_turn': et, 'spoken': spoken, 'log': log}
    return runs


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--iter', type=int, default=0)
    ap.add_argument('--calib', default='', help='单变量校准名（只允许一个）')
    ap.add_argument('--start', type=int, default=0)
    ap.add_argument('--count', type=int, default=6)
    args = ap.parse_args()

    trunk = json.load(open(TRUNK, encoding='utf-8'))
    corpus = json.load(open(CORPUS, encoding='utf-8'))
    materials = corpus[args.start:args.start + args.count]

    runs = run_iter(args.iter, args.calib or None, materials, trunk)
    out = HERE / ('calib_iter%d.json' % args.iter)
    json.dump(runs, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print("=" * 96)
    print("iter%d（calib=%s）终止于第 %d 段（%s） 实际发言 %d 次"
          % (args.iter, args.calib or '无（基线）', runs['end_turn'], runs['end'], runs['spoken']))
    from collections import Counter
    cnt = Counter(f for h in runs['log'] if h['who'] == 'B'
                  for f in h.get('rec', {}).get('flags', []))
    print("失效点分布:", dict(cnt) if cnt else '本轮零失效点')
    print("输出：", out)


if __name__ == '__main__':
    main()
