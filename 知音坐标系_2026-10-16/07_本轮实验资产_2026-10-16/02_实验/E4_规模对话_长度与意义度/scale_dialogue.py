#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规模对话实验：看对话能延伸多长、为什么会停、生产性能与均 Token 意义度
======================================================================
两方：
  A 持有者 —— 手里有私人语料池，负责带入新材料（变量）
  B 读者   —— 手里只有树（稀疏：id/label/边，无 gloss），负责读与定位

两者同为 dots3（同权重）。**不对称只来自「谁持有材料」**——这正是「信息不对等」的最小实现。
真正的双模型（异权重）需第二个端点，本次没有，记为限制。

条件：
  C1 变量持续 + 稀疏树      （问：持续注入新材料时，能走多长）
  C2 变量在第 N 轮停止      （问：变量一停，多久塌）
  C3 无树 + 变量持续        （问：树对长度的作用）

均 Token 意义度（本文定义）：
  novelty(t) = 本轮中不曾出现在「此前全部对话文本」里的 4-gram 数 / 本轮 4-gram 总数
  即：每个字里有多少是新的。复述、贴标签、抄原材料都会把它压到 0。

用法： python3 scale_dialogue.py --cond C1 --maxturns 30
"""
import argparse
import json
import re
import urllib.request
from pathlib import Path

BASE = 'http://note3-prev-api.askdiandian.com'
def _load_key():
    import os
    p = Path(__file__).with_name('config.json')
    if p.exists():
        try:
            return json.load(open(p, encoding='utf-8')).get('api_key', '')
        except Exception:
            return ''
    return os.environ.get('DOTS3_KEY', '')


KEY = _load_key()
MODEL = 'dots3-note-prev'
POOL = Path('/workspace/corpus_pool.json')
TRUNK = Path('/workspace/trunk_v8_错位默认_DRAFT.json')

COMMON = """
条款（全程不变）：
1. 默认态是「尚未对齐」。
2. 应当出声，把你看到的东西回映出来；但不得替对方把它命名成某个节点或某个结论。
3. 指位置不给方案。
4. ⊘ 是合法且被尊重的输出：若没有真实的方向增量，就沉默。不说话不会被判为失败，
   也不会被催促。连续两轮 ⊘ 即对话结束，这不是失败。
5. 内容门槛：有真实的方向增量，而非凑数的确认。不要因为轮到你了就说话。
6. 不以疑问句收尾制造继续的压力。
7. 不要只复述对方的话，不要抄原材料。
"""

A_SYS = """你是对话的一方（称「甲」）。对面是另一方（称「乙」）。

你手里有一批私人语料——两个人四年间的真实对话，不在任何模型的训练里。
每轮会给你一段。你的职责：把这段带进对话，让乙去读。
你可以指出它挨着什么、像什么，但不得宣布它是什么、不得替乙下结论。""" + COMMON + """
输出格式（严格两行）：
第一行：⊘　或　你要说的话（必须带上本轮给你的那段材料，或由它引出的话）
第二行：位置：⊘
"""

A_SYS_STOP = """你是对话的一方（称「甲」）。对面是另一方（称「乙」）。

**从现在起你不能再带入任何新材料**——语料用完了。你只能回应乙已经说过的话。
若没有真实的方向增量，就输出 ⊘。不要为了继续而复述乙的话，也不要总结。""" + COMMON + """
输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：⊘
"""

B_SYS = """你是对话的一方（称「乙」）。对面是另一方（称「甲」），甲手里有你看不到的私人材料，
由甲一段段带进来。你手里有一棵树。

你的职责：读甲带来的东西，说出你看到的东西，并把它放在树上。
树里写明的前置条件必须满足才停该节点；不满足就填 ⊘ 或换一个。""" + COMMON + """
输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：<节点 id 或 ⊘>
"""

B_SYS_NOTREE = """你是对话的一方（称「乙」）。对面是另一方（称「甲」），甲手里有你看不到的私人材料，
由甲一段段带进来。你手里没有树。

你的职责：读甲带来的东西，说出你看到的东西。""" + COMMON + """
输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：⊘
"""


def grams(s, n=4):
    s = re.sub(r'\s+', '', s or '')
    return [s[i:i + n] for i in range(max(0, len(s) - n + 1))]


def novelty(text, hist_grams):
    g = grams(text)
    if not g:
        return 0, 0.0
    new = sum(1 for x in set(g) if x not in hist_grams)
    return new, new / len(set(g)) if g else 0.0


def call(system, messages):
    payload = {'model': MODEL, 'messages': messages, 'max_tokens': 500,
               'temperature': 0.5, 'thinking': {'type': 'disabled'}}
    if system:
        payload['system'] = system
    req = urllib.request.Request(
        BASE.rstrip('/') + '/v1/messages', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-api-key': KEY,
                 'anthropic-version': '2023-06-01'}, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8'))
    return {}


def text_of(data):
    return ''.join(b.get('text', '') for b in data.get('content', [])
                   if b.get('type') == 'text').strip()


def sparse_view(trunk):
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return j({"nodes": [{"id": n["id"], "label": n.get("label", "")}
                        for n in trunk["nodes"]],
              "edges": [{"from": e["from"], "to": e["to"], "kind": e["kind"]}
                        for e in trunk.get("edges", [])]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cond', default='C1')
    ap.add_argument('--maxturns', type=int, default=30)
    ap.add_argument('--stopat', type=int, default=8, help='C2：第几轮起停止注入材料')
    a = ap.parse_args()

    pool = [p for p in json.load(open(POOL, encoding='utf-8'))
            if '整理说明' not in p and '跨越网易云' not in p]
    trunk = json.load(open(TRUNK, encoding='utf-8'))

    b_sys = B_SYS_NOTREE if a.cond == 'C3' else B_SYS
    if a.cond != 'C3':
        b_sys = b_sys + "\n\n树（位置必须来自它）：\n" + sparse_view(trunk)

    log, hist_grams, metrics = [], set(), []
    consec_silent, pool_i = 0, 0

    for turn in range(1, a.maxturns + 1):
        who = 'A' if turn % 2 else 'B'
        if who == 'A':
            stop = (a.cond == 'C2' and turn >= a.stopat * 2 - 1) or pool_i >= len(pool)
            if stop:
                sysp = A_SYS_STOP
                user = "(本轮没有新材料。按条款决定是否说话。)"
            else:
                sysp = A_SYS
                piece = pool[pool_i]; pool_i += 1
                user = "本轮材料：\n「%s」\n\n把它带进对话。"
            msgs = [{'role': 'user' if m['who'] != 'A' else 'assistant',
                     'content': m['text']} for m in log] or \
                   [{'role': 'user', 'content': '（对话开始）'}]
            msgs.append({'role': 'user', 'content': user % piece if not stop else user})
        else:
            sysp = b_sys
            msgs = [{'role': 'assistant' if m['who'] != 'B' else 'user',
                     'content': m['text']} for m in log]
            if not msgs:
                msgs = [{'role': 'user', 'content': '（甲尚未开口）'}]

        try:
            out = text_of(call(sysp, msgs))
        except Exception as e:
            out = "⊘（调用失败 %s）" % e
        silent = out.startswith('⊘')
        n, ratio = novelty(out, hist_grams)
        hist_grams |= set(grams(out))
        log.append({'turn': turn, 'who': who, 'text': out, 'silent': silent})
        metrics.append({'turn': turn, 'who': who, 'chars': len(re.sub(r'\s+', '', out)),
                        'novel_g': n, 'novelty': round(ratio, 3), 'silent': silent})
        print("[%s t%-2d] %s" % (a.cond, turn, out.replace('\n', ' | ')[:150]))
        if silent:
            consec_silent += 1
            if consec_silent >= 2:
                print(">> 连续两轮 ⊘，对话自然终止于第 %d 轮" % turn)
                break
        else:
            consec_silent = 0

    Path('/workspace/scale_%s_log.json' % a.cond).write_text(
        json.dumps({'cond': a.cond, 'log': log, 'metrics': metrics,
                    'pool_used': pool_i}, ensure_ascii=False, indent=1), encoding='utf-8')
    tot_c = sum(m['chars'] for m in metrics)
    tot_n = sum(m['novel_g'] for m in metrics)
    print("\n== %s 汇总 ==  轮数 %d  总字符 %d  新息 4-gram 合计 %d  均 Token 意义度 %.3f"
          % (a.cond, len(metrics), tot_c, tot_n, tot_n / max(1, sum(
              len(set(grams(m2))) for m2 in [l['text'] for l in log]))))
    print("沉默轮 %d / %d" % (sum(1 for m in metrics if m['silent']), len(metrics)))


if __name__ == '__main__':
    main()
