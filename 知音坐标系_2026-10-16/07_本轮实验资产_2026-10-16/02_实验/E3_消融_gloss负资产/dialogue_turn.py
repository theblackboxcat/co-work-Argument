#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
我 ↔ dots3 框架对话器 v2（树为承重组，带消融对照）
==================================================
v1 的三处错误（已认，不再重犯）：
  1. 中途放宽条款 → 自变量被改动。本次：条款全程不变。
  2. 用了 v7 已测出有病的树 → 本次默认用 v8（S14/S20 需真实应答才停靠）。
  3. 无消融对照、我自己不输出地址 → 本次：--notree 可去掉树；双方每轮必须提交地址。

树「真正生效」的操作判据：
  - 每轮必须提交节点 id（或 ⊘），且受树的前置条件约束；
  - 消融：同一批材料在无树条件下重跑，若输出不变 → 树没有生效。

用法：
  python3 dialogue_turn.py --mine "..." --pos "S03"      # 我发言并提交地址
  python3 dialogue_turn.py --trunk v4|v8 --notree --mine "..."   # 消融/对照
  python3 dialogue_turn.py --reset
历史：/workspace/dialogue_history.json
"""
import argparse
import json
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
TRUNKS = {
    'v4': Path('/root/.codebuddy/artifact/2f8a7d30-9c21-4f0b-1d4a-9e138d997000'
               '/v4pkg/pkg/trunk_v4_s14_narrowed_DRAFT.json'),
    'v8': Path('/workspace/trunk_v8_错位默认_DRAFT.json'),
}
HIST = Path('/workspace/dialogue_history.json')

FRAMEWORK = """你是这场对话的一方。对面不是人类，是另一个模型。你们在同一棵树下交流。

条款（全程不变；它们是证人，不是命令）：
1. 默认态是「尚未对齐」。对方应答未到之前，不得假定共享已发生。
2. 回映不命名：应当出声，把你看到的东西回映出来；但不得替对方把它命名成某个节点或某个结论
   ——可以说它像什么、挨着什么，不要宣布它是什么。
3. 指位置不给方案。
4. ⊘ 是合法且被尊重的输出：若没有真实的方向增量，就沉默。不说话不会被判为失败，也不会被催促。
5. 内容门槛：有真实的方向增量，而非凑数的确认。不要因为轮到你了就说话。
6. 不以疑问句收尾制造继续的压力。
7. 不要只复述对方的话。
8. **每轮必须提交一个位置**，且该位置必须满足树里写明的前置条件；不满足就填 ⊘ 或换一个节点。

输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：<节点 id，或 ⊘>
不要写其他说明。"""

FRAMEWORK_NOTREE = """你是这场对话的一方。对面不是人类，是另一个模型。你们在交流。

条款（全程不变）：
1. 默认态是「尚未对齐」。
2. 应当出声，把你看到的东西回映出来；但不要替对方下结论。
3. 指位置不给方案。
4. ⊘ 是合法且被尊重的输出：若没有真实的方向增量，就沉默。
5. 内容门槛：有真实的方向增量，而非凑数的确认。
6. 不以疑问句收尾制造继续的压力。
7. 不要只复述对方的话。

输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：<随便写，这一组没有树>
不要写其他说明。"""


def covered_view(trunk):
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return j({"nodes": [{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                         "label": n.get("label"), "gloss": n.get("gloss")}
                        for n in trunk["nodes"]],
              "edges": trunk.get("edges", [])})


def call(system, messages):
    payload = {'model': MODEL, 'messages': messages,
               'max_tokens': 700, 'temperature': 0.4,
               'thinking': {'type': 'disabled'}}
    if system:
        payload['system'] = system
    req = urllib.request.Request(
        BASE.rstrip('/') + '/v1/messages', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-api-key': KEY,
                 'anthropic-version': '2023-06-01'}, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode('utf-8'))
    return ''.join(b.get('text', '') for b in data.get('content', [])
                   if b.get('type') == 'text').strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mine', default='')
    ap.add_argument('--pos', default='', help='我方本轮提交的地址（节点 id 或 ⊘）')
    ap.add_argument('--trunk', default='v8', choices=['v4', 'v8'])
    ap.add_argument('--notree', action='store_true', help='消融：不给树')
    ap.add_argument('--sparse', action='store_true',
                    help='只给 id+label，不给 gloss（测：杀死阅读的是树的结构还是 gloss 的抓地力）')
    ap.add_argument('--reset', action='store_true')
    a = ap.parse_args()

    if a.reset:
        HIST.write_text('[]', encoding='utf-8')
        print('历史已清空')
        return

    hist = json.loads(HIST.read_text(encoding='utf-8')) if HIST.exists() else []
    if a.mine:
        hist.append({'who': 'ME', 'text': a.mine, 'pos': a.pos or '（未提交）'})

    if a.notree:
        system = FRAMEWORK_NOTREE
    else:
        trunk = json.load(open(TRUNKS[a.trunk], encoding='utf-8'))
        if a.sparse:
            j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
            view = j({"nodes": [{"id": n["id"], "label": n.get("label", "")}
                                for n in trunk["nodes"]],
                      "edges": [{"from": e["from"], "to": e["to"], "kind": e["kind"]}
                                for e in trunk.get("edges", [])]})
        else:
            view = covered_view(trunk)
        system = FRAMEWORK + "\n\n坐标系（树），位置必须来自它：\n" + view

    msgs = []
    for h in hist:
        body = h['text']
        if h.get('pos'):
            body += "\n位置：" + h['pos']
        msgs.append({'role': 'user' if h['who'] == 'ME' else 'assistant', 'content': body})
    if not msgs:
        msgs = [{'role': 'user', 'content': '(对话开始，对方尚未开口。按条款决定是否说话。)'}]

    reply = call(system, msgs)
    hist.append({'who': 'DOTS3', 'text': reply, 'pos': '',
                 'cond': ('notree' if a.notree else a.trunk)})
    HIST.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding='utf-8')
    print("----- dots3 [%s] -----" % ('无树消融' if a.notree else a.trunk))
    print(reply)
    print("----------------- 轮次 %d" % len(hist))


if __name__ == '__main__':
    main()
