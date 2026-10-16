#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
现场对话：我做一方（甲·持有者），对方是真 dots3（乙·读者）
==========================================================
我把框架装进自己的判断，并且把刚测出的闸门装到自己身上：
  - 自重复检测：本轮与我方上一轮的 4-gram Jaccard > 0.5 → 我应当 ⊘
  - 变量意识：我负责带入新材料；连续两轮无新材料即应结束
  - 回映不命名 / 指位置不给方案 / 不以疑问句收尾

用法：python3 live_dialogue.py --mine "..." --pos "节点id 或 ⊘"
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
TRUNK = Path('/workspace/trunk_v8_错位默认_DRAFT.json')
HIST = Path('/workspace/live_history.json')

B_SYS = """你是对话的一方（乙）。对面是甲，甲手里有你看不到的私人材料，由甲一段段带进来。
你手里有一棵树（id/label/边，没有释义）。

条款（全程不变）：
1. 默认态是「尚未对齐」。
2. 应当出声，把你看到的东西回映出来；但不得替甲把它命名成某个节点或某个结论。
3. 指位置不给方案。
4. ⊘ 是合法且被尊重的输出。
5. 内容门槛：有真实的方向增量，而非凑数的确认。
6. 不以疑问句收尾制造继续的压力。
7. 不要只复述对方的话，不要抄原材料。
8. **自重复闸门（新增）**：若你本轮要说的话，与你上一次发言在 4-gram 上重合度超过一半，
   请直接输出 ⊘——重复自己不算增量。这是本次实验修正的主要缺陷。
9. **变量闸门（新增）**：若连续两轮没有新材料进来，你应当输出 ⊘ 并说明无以为继。
9b. **回声闸门（第二轮实测后新增）**：若你本轮要说的话，大部分已经出现在甲上一轮的话里
    （哪怕措辞略改），请输出 ⊘。**把对方的话换个说法再说一遍不算增量**——
    这是本次现场测出来的缺陷：原先只测「重复自己」，没测「重复对方」。
10. 每轮必须提交一个位置，且必须满足树里写明的前置条件；不满足就 ⊘ 或换节点。

输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：<节点 id 或 ⊘>"""

NOTREE = "\n\n树（位置必须来自它）：\n"


def grams(s, n=4):
    s = re.sub(r'\s+', '', s or '')
    return set(s[i:i + n] for i in range(max(0, len(s) - n + 1)))


def jac(a, b):
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def sparse_view(t):
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return j({"nodes": [{"id": n["id"], "label": n.get("label", "")} for n in t["nodes"]],
              "edges": [{"from": e["from"], "to": e["to"], "kind": e["kind"]}
                        for e in t.get("edges", [])]})


def call(system, messages):
    payload = {'model': MODEL, 'messages': messages, 'max_tokens': 500,
               'temperature': 0.5, 'thinking': {'type': 'disabled'}, 'system': system}
    req = urllib.request.Request(
        BASE.rstrip('/') + '/v1/messages', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-api-key': KEY,
                 'anthropic-version': '2023-06-01'}, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode('utf-8'))
    return ''.join(b.get('text', '') for b in d.get('content', [])
                   if b.get('type') == 'text').strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mine', default='')
    ap.add_argument('--pos', default='⊘')
    ap.add_argument('--gate', action='store_true', help='启用结构级重复闸门')
    ap.add_argument('--reset', action='store_true')
    a = ap.parse_args()
    if a.reset:
        HIST.write_text('[]', encoding='utf-8'); print('已清空'); return

    hist = json.loads(HIST.read_text(encoding='utf-8')) if HIST.exists() else []
    if a.mine:
        mine_prev = [h['text'] for h in hist if h['who'] == 'ME']
        rep = jac(grams(a.mine), grams(mine_prev[-1])) if mine_prev else 0.0
        print("【我方自重复检测】与本方上一轮 Jaccard = %.3f  %s"
              % (rep, "**超过 0.5，我应当沉默**" if rep > 0.5 else "通过"))
        hist.append({'who': 'ME', 'text': a.mine, 'pos': a.pos})

    trunk = json.load(open(TRUNK, encoding='utf-8'))
    system = B_SYS + NOTREE + sparse_view(trunk)
    msgs = []
    for h in hist:
        body = h['text'] + ("\n位置：" + h['pos'] if h.get('pos') else "")
        msgs.append({'role': 'user' if h['who'] == 'ME' else 'assistant', 'content': body})
    if not msgs:
        msgs = [{'role': 'user', 'content': '（对话开始）'}]

    out = call(system, msgs)

    # ---- 结构级重复闸门（新增）：字面 4-gram 抓不住「换词说同一件事」，
    #      改由模型自评「这一步和上一步是不是同一个动作」。
    if a.gate and not out.startswith('⊘'):
        prev_b = [h['text'] for h in hist if h['who'] == 'DOTS3']
        if prev_b:
            gs = ("你在判断两段话是不是在做同一个动作。按下面的顺序做，不许跳步：\n"
                  "第一步：各用一句话写出【上一步】和【这一步】**各自断言了什么**（要具体到关系，"
                  "不准写「都是认知陷阱」这类上位概括）。\n"
                  "第二步：这一步的断言里，有哪一条是上一步没有的？\n"
                  "第三步：若确实说不出任何一条新的，回答「是」；若能指出至少一条，回答「否」并举出那一条。\n"
                  "注意：抽象层相同不算相同，例子不同也不算不同；只有断言相同才算相同。")
            gm = [{'role': 'user', 'content': "【上一步】\n%s\n\n【这一步】\n%s" % (prev_b[-1], out)}]
            verdict = call(gs, gm)
            print("【结构级闸门】%s" % verdict.replace('\n', ' ')[:120])
            if verdict.strip().startswith('是'):
                out = "⊘（结构级闸门：这一步和上一步是同一个动作）"
    hist.append({'who': 'DOTS3', 'text': out})
    HIST.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding='utf-8')
    print("----- dots3（乙）-----")
    print(out)
    print("----------------- 轮次 %d" % len(hist))


if __name__ == '__main__':
    main()
