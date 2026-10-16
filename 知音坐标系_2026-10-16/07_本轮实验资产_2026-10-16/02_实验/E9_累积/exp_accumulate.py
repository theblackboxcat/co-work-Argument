#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E9　累积实验：把每轮的地址与命题写回「路径」，下一轮可见
==========================================================
问题（下一步实验 #2）：命题一条条产出，但**彼此不引用**。
原因假设：对话历史不进入上下文，每轮只看新材料 + 树。

做法：与 E7 完全相同的费曼 7 段与条款，唯一差别——
每轮把乙上一轮的「地址 + 一句话断言」追加进一条**可见的路径**，
下一轮连同树一起给它，并允许它引用或反驳路径中的任何一步。

测量：显式引用（「上一步/第 N 步/前面那条/刚才」）的次数；
末轮是否出现综合（把前面几步串起来）。
"""
import json
import re
import urllib.request
from pathlib import Path

BASE = 'http://note3-prev-api.askdiandian.com'
MODEL = 'dots3-note-prev'
TRUNK = Path('/workspace/trunk_v8_错位默认_DRAFT.json')
OUT = Path('/workspace/exp_accumulate_out.json')

PASSAGES = [
    "when you are asked, for example, why two magnets repel, there are many different levels. It depends on whether you are a student of physics, or an ordinary person who doesn't know anything.",
    "If you're somebody who doesn't know anything at all about it, all I can say is the magnetic force makes them repel, and that you're feeling that force.",
    "you're not at all disturbed by the fact that when you put your hand on a chair, it pushes you back. But we found out by looking at it that that's the same force... the same electric repulsions that are involved in keeping your finger away from the chair.",
    "in iron all the electrons are spinning in the same direction, they all get lined up, and they magnify the effect of the force 'til it's large enough, at a distance, that you can feel it.",
    "if I said the magnets attract like as if they were connected by rubber bands, I would be cheating you... if you were curious enough, you'd ask me why rubber bands tend to pull back together again, and I would end up explaining that in terms of electrical forces, which are the very things that I'm trying to use the rubber bands to explain. So I have cheated very badly.",
    "I am not going to be able to give you an answer to why magnets attract each other except to tell you that they do. And to tell you that that's one of the elements in the world... If you were a student, I could go further.",
    "I really can't do a good job, any job, of explaining magnetic force in terms of something else you're more familiar with, because I don't understand it in terms of anything else that you're more familiar with.",
]

SYS = """你是对话的一方（乙）。对面是甲，甲会一段段带东西进来。你手里有一棵树（id/label/边，无释义）。

条款（全程不变）：
1. 默认态是「尚未对齐」。
2. 应当出声，把你看到的东西回映出来；但不得替甲把它命名成某个节点或某个结论。
3. 指位置不给方案。
4. ⊘ 是合法且被尊重的输出。
5. 内容门槛：有真实的方向增量。
6. 不以疑问句收尾制造继续的压力。
7. 不要只复述对方的话，不要抄原材料。
8. 自重复闸门 / 9. 回声闸门 / 10. 结构级闸门（与上一步是同一个动作则 ⊘）。
11. 每轮提交一个位置，须满足树里写明的前置条件。

【已走过的路径·你可以引用也可以反驳它】
{path}

若你本轮要说的话已经被路径里某一步说过，输出 ⊘。
若你要推进，请说明你是在路径的哪一步上推进的（写出步号）。

输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：<节点 id 或 ⊘>"""

REF = ['上一步', '第1步', '第2步', '第3步', '第4步', '第5步', '第6步', '前面', '前一步',
       '刚才', '此前', '上一轮', '路径', '承', '接住', '推进', '反驳', '综合', '串',
       '总起来', '说到底', '回头看']


def load_key():
    import os
    p = Path(__file__).with_name('config.json')
    if p.exists():
        try:
            return json.load(open(p, encoding='utf-8')).get('api_key', '')
        except Exception:
            return ''
    return os.environ.get('DOTS3_KEY', '')


KEY = load_key()


def call(system, messages, temp=0.5):
    payload = {'model': MODEL, 'messages': messages, 'max_tokens': 400,
               'temperature': temp, 'thinking': {'type': 'disabled'}, 'system': system}
    req = urllib.request.Request(
        BASE.rstrip('/') + '/v1/messages', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-api-key': KEY,
                 'anthropic-version': '2023-06-01'}, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode('utf-8'))
    return ''.join(b.get('text', '') for b in d.get('content', [])
                   if b.get('type') == 'text').strip()


def sparse_view(t):
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return j({"nodes": [{"id": n["id"], "label": n.get("label", "")} for n in t["nodes"]],
              "edges": [{"from": e["from"], "to": e["to"], "kind": e["kind"]}
                        for e in t.get("edges", [])]})


def first_sentence(s):
    s = re.sub(r'\s+', '', s or '')
    m = re.split(r'[。；]', s)
    return (m[0] if m and m[0] else s)[:60]


def main():
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    tree = "\n\n树（位置必须来自它）：\n" + sparse_view(trunk)
    runs = []
    for rid in range(1, 4):
        log, path = [], []
        for k, p in enumerate(PASSAGES, 1):
            log.append({'who': 'ME', 'text': "（第 %d 段）%s" % (k, p), 'pos': '（不提交）'})
            ptext = ("\n".join("%d. [%s] %s" % (i + 1, a, c) for i, (a, c) in enumerate(path))
                     or "（尚无）")
            msgs = [{'role': ('user' if h['who'] == 'ME' else 'assistant'),
                     'content': h['text'] + ("\n位置：" + h['pos'] if h.get('pos') else "")}
                    for h in log]
            out = call(SYS.replace('{path}', ptext) + tree, msgs)
            log.append({'who': 'B', 'text': out})
            lines = [x for x in out.split('\n') if x.strip()]
            pos = lines[-1].replace('位置：', '').strip() if len(lines) > 1 else '⊘'
            path.append((pos[:28], first_sentence(lines[0])))
        btext = " ".join(h['text'] for h in log if h['who'] == 'B')
        refs = [w for w in REF if w in btext]
        runs.append({'run': rid, 'log': log, 'path': path, 'refs': refs})
        print("run%d  引用词命中 %d：%s" % (rid, len(refs), "、".join(refs)))
        print("      末轮：%s" % ([h['text'] for h in log if h['who'] == 'B'][-1].replace('\n', ' ')[:100]))
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding='utf-8')
    print("\n已写 %s" % OUT)


if __name__ == '__main__':
    main()
