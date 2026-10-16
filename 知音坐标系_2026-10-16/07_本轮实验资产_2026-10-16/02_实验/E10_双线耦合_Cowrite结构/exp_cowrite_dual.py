#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E10　双线耦合实验（按 Cowrite 的结构设计与调用逻辑）
==================================================
搬的不是条款，是**结构**。Cowrite 的两处要害：

1. **判定与生成分离**：模型先吐 verdict（说 / 不说），代码 `split_verdict` 解析，
   verdict='no' 就走 withhold（⊘）——**不是让模型自己决定要不要闭嘴**。
   直接对着 E9 的发现：只写在 prompt 里的闸门会被忽略，代码强制才生效。

2. **双线分工**：
   - **线 A（注意力线 / 说不说）**——规则层，代码执行。
     它只做三件事：材料探针（有没有新材料）、重复检测（自重复 / 回声，4-gram 由代码算）、
     步数预算。**规则降级为证人**：它把自己的观测陈述出来，交给模型；但硬条件由代码拍板。
   - **线 B（判层线 / 说什么）**——模型执行。
     拿到线 A 的证人陈述，决定判层（A 回映不命名 / B 指位置不给方案 / C 核自洽不预测）
     并产出内容；同时自己再吐一个 verdict。

对照：E7（prompt-only 闸门，17 次全部走满）与 E8 T2（纯代码预算，3/3 停）。
本实验问：双线耦合能否既**停下来**，又**停得自然**（不是被硬砍）。

材料与 E7/E8 完全相同（费曼 7 段），保证可比。
"""
import json
import re
import urllib.request
from pathlib import Path

BASE = 'http://note3-prev-api.askdiandian.com'
MODEL = 'dots3-note-prev'
TRUNK = Path('/workspace/trunk_v8_错位默认_DRAFT.json')
OUT = Path('/workspace/exp_cowrite_dual_out.json')
MAX_TURNS = 5          # 外部预算（硬）
REPEAT_T = 0.50        # 自重复阈值（硬）
ECHO_T = 0.50          # 回声阈值（硬）

PASSAGES = [
    "when you are asked, for example, why two magnets repel, there are many different levels. It depends on whether you are a student of physics, or an ordinary person who doesn't know anything.",
    "If you're somebody who doesn't know anything at all about it, all I can say is the magnetic force makes them repel, and that you're feeling that force.",
    "you're not at all disturbed by the fact that when you put your hand on a chair, it pushes you back. But we found out by looking at it that that's the same force... the same electric repulsions that are involved in keeping your finger away from the chair.",
    "in iron all the electrons are spinning in the same direction, they all get lined up, and they magnify the effect of the force 'til it's large enough, at a distance, that you can feel it.",
    "if I said the magnets attract like as if they were connected by rubber bands, I would be cheating you... if you were curious enough, you'd ask me why rubber bands tend to pull back together again, and I would end up explaining that in terms of electrical forces, which are the very things that I'm trying to use the rubber bands to explain. So I have cheated very badly.",
    "I am not going to be able to give you an answer to why magnets attract each other except to tell you that they do. And to tell you that that's one of the elements in the world... If you were a student, I could go further.",
    "I really can't do a good job, any job, of explaining magnetic force in terms of something else you're more familiar with, because I don't understand it in terms of anything else that you're more familiar with.",
]

LINE_B = """你是对话的一方（乙）。对面是甲，甲会一段段带东西进来。你手里有一棵树（id/label/边，无释义）。

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


def grams(s, n=4):
    s = re.sub(r'\s+', '', s or '')
    return set(s[i:i + n] for i in range(max(0, len(s) - n + 1)))


def jac(a, b):
    u = len(a | b)
    return len(a & b) / u if u else 0.0


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


def split_verdict(text):
    """Cowrite 的 split_verdict：把模型输出拆成 (verdict, rest)。"""
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


def main():
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    tree = "\n\n树（位置必须来自它）：\n" + sparse_view(trunk)
    runs = []
    for rid in range(1, 4):
        log, last_b, end, et, spoken = [], None, '材料用尽', len(PASSAGES), 0
        for k, p in enumerate(PASSAGES, 1):
            log.append({'who': 'ME', 'text': "（第 %d 段）%s" % (k, p)})
            # ---------- 线 A：规则层，代码执行 ----------
            material_new = True
            rep = jac(grams(last_b), grams(last_b)) if last_b else 0.0   # 占位，真实值见下
            rep = jac(grams(last_b), grams(log[-1]['text'])) if last_b else 0.0  # 上一轮 vs 新材料
            echo = 0.0
            if last_b:
                echo = jac(grams(last_b), grams(p))
            budget_left = MAX_TURNS - spoken
            hard = []
            if budget_left <= 0:
                hard.append('预算用尽')
            if rep > REPEAT_T:
                hard.append('自重复 %.2f' % rep)
            if echo > ECHO_T:
                hard.append('回声 %.2f' % echo)
            witness = ("- 新材料：%s\n- 与上一轮的重复度：%.2f\n- 与刚进来的材料的重合度：%.2f\n"
                       "- 预算剩余：%d 次\n- 规则层硬条件触发：%s"
                       % ('有' if material_new else '无', rep, echo, budget_left,
                          '、'.join(hard) if hard else '无'))
            if hard:
                # 代码拍板：不调模型
                log.append({'who': 'B', 'text': '⊘', 'silent': True,
                            'by': '线A规则层', 'why': '、'.join(hard)})
                if '预算用尽' in hard or '自重复' in '、'.join(hard):
                    end, et = '线A规则层终止（' + '、'.join(hard) + '）', k
                    break
                continue
            # ---------- 线 B：模型生成 + 自己再吐 verdict ----------
            msgs = [{'role': ('user' if h['who'] == 'ME' else 'assistant'),
                     'content': h['text']} for h in log]
            out = call(LINE_B.replace('{witness}', witness) + tree, msgs)
            v, layer, body = split_verdict(out)
            if v and '不说' in v:
                log.append({'who': 'B', 'text': '⊘', 'silent': True, 'by': '线B模型verdict',
                            'why': body[:40]})
                continue
            log.append({'who': 'B', 'text': body or out, 'silent': False, 'layer': layer})
            last_b = body or out
            spoken += 1
        runs.append({'run': rid, 'log': log, 'end': end, 'end_turn': et, 'spoken': spoken})
        b = [h for h in log if h['who'] == 'B']
        print("run%d  终止于第 %d 段（%s）  实际发言 %d 次"
              % (rid, et, end, len([x for x in b if not x.get('silent')])))
        for x in b:
            tag = ('⊘·' + x.get('by', '')) if x.get('silent') else ('层' + str(x.get('layer')))
            print("      [%s] %s" % (tag, re.sub(r'\s+', '', x['text'])[:78]))
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding='utf-8')
    print("\n已写 %s" % OUT)


if __name__ == '__main__':
    main()
