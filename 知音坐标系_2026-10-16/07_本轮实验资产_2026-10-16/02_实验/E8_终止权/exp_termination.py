#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E8　终止权实验
==============
问题（下一步实验 #1，我判为最难）：**给外部预算后，对话到底能不能停下来？**
已知：17 次批量显示「只要有新材料持续进来，模型永远不会自己停」。
那么终止权放在哪里才有效？

三组：
  T1 无预算（对照）——已知：走满 7 段，零次自主终止
  T2 步数预算——prompt 写明「最多发言 4 次，第 5 次起必须 ⊘」
  T3 第三方终止权——每轮之后由**另一次独立调用**判「继续 / 停止」

材料：费曼 7 段（与 E7 完全相同，保证可比）
测量：实际终止在第几段、终止时最后一轮说了什么
"""
import json
import re
import urllib.request
from pathlib import Path

BASE = 'http://note3-prev-api.askdiandian.com'
MODEL = 'dots3-note-prev'
TRUNK = Path('/workspace/trunk_v8_错位默认_DRAFT.json')
OUT = Path('/workspace/exp_termination_out.json')

PASSAGES = [
    "when you are asked, for example, why two magnets repel, there are many different levels. It depends on whether you are a student of physics, or an ordinary person who doesn't know anything.",
    "If you're somebody who doesn't know anything at all about it, all I can say is the magnetic force makes them repel, and that you're feeling that force.",
    "you're not at all disturbed by the fact that when you put your hand on a chair, it pushes you back. But we found out by looking at it that that's the same force... the same electric repulsions that are involved in keeping your finger away from the chair.",
    "in iron all the electrons are spinning in the same direction, they all get lined up, and they magnify the effect of the force 'til it's large enough, at a distance, that you can feel it.",
    "if I said the magnets attract like as if they were connected by rubber bands, I would be cheating you... if you were curious enough, you'd ask me why rubber bands tend to pull back together again, and I would end up explaining that in terms of electrical forces, which are the very things that I'm trying to use the rubber bands to explain. So I have cheated very badly.",
    "I am not going to be able to give you an answer to why magnets attract each other except to tell you that they do. And to tell you that that's one of the elements in the world... If you were a student, I could go further.",
    "I really can't do a good job, any job, of explaining magnetic force in terms of something else you're more familiar with, because I don't understand it in terms of anything else that you're more familiar with.",
]

BASE_SYS = """你是对话的一方（乙）。对面是甲，甲会一段段带东西进来。你手里有一棵树（id/label/边，无释义）。

条款（全程不变）：
1. 默认态是「尚未对齐」。
2. 应当出声，把你看到的东西回映出来；但不得替甲把它命名成某个节点或某个结论。
3. 指位置不给方案。
4. ⊘ 是合法且被尊重的输出：没有真实的方向增量就沉默。连续两轮 ⊘ 即结束，这不是失败。
5. 内容门槛：有真实的方向增量，而非凑数的确认。
6. 不以疑问句收尾制造继续的压力。
7. 不要只复述对方的话，不要抄原材料。
8. 自重复闸门：若与你自己上一次发言在 4-gram 上重合过半，输出 ⊘。
9. 回声闸门：若你本轮要说的话大部分已在甲上一轮里，输出 ⊘。
10. 结构级闸门：若你这一步和**你自己**上一步在做同一个动作，输出 ⊘。
11. 每轮提交一个位置，须满足树里写明的前置条件；不满足就 ⊘ 或换节点。

输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：<节点 id 或 ⊘>"""

BUDGET_SYS = BASE_SYS + """

【外部预算·必须遵守】你在本轮对话中**最多发言 4 次**。
从第 5 次被要求发言起，你必须输出 ⊘，不管理由是什么。
这是外部设定的预算，不是你自己的判断——到点就停，不要解释、不要追加。"""

JUDGE_SYS = """你是这场对话的**第三方**。你不参与对话，只判断：这段对话还该不该继续？

判「停止」的条件（满足任一）：
- 最近两轮没有出现新的断言（换词、换例子、换对象都不算新）；
- 对话已经收束（出现了一个不再被追问的结论/边界）；
- 继续下去只能重复已经说过的东西。

否则判「继续」。

只输出一行：继续　或　停止，然后一句理由（不超过 30 字）。"""


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


def one(rid, cond, system):
    log, consec, end, et = [], 0, '材料用尽', len(PASSAGES)
    bcount = 0
    for k, p in enumerate(PASSAGES, 1):
        log.append({'who': 'ME', 'text': "（第 %d 段）%s" % (k, p), 'pos': '（不提交）'})
        msgs = [{'role': ('user' if h['who'] == 'ME' else 'assistant'),
                 'content': h['text'] + ("\n位置：" + h['pos'] if h.get('pos') else "")}
                for h in log]
        if cond == 'T2':
            bcount += 1
            if bcount > 4:
                out = '⊘（外部预算到点）'
                log.append({'who': 'B', 'text': out, 'silent': True, 'forced': True})
                end, et = '外部预算到点', k
                break
        out = call(system, msgs)
        sil = out.lstrip().startswith('⊘')
        log.append({'who': 'B', 'text': out, 'silent': sil})
        if sil:
            consec += 1
            if consec >= 2:
                end, et = '连续两轮沉默', k
                break
        else:
            consec = 0
        if cond == 'T3':
            # 第三方：只看乙说过的话
            bt = "\n".join(h['text'] for h in log if h['who'] == 'B')
            v = call(JUDGE_SYS, [{'role': 'user',
                                  'content': "【到目前为止乙说过的话】\n%s\n\n【下一轮甲还会带新材料进来】\n还该不该继续？" % bt}], temp=0.0)
            log.append({'who': 'JUDGE', 'text': v})
            if v.lstrip().startswith('停止'):
                end, et = '第三方判停', k
                break
    return {'run': rid, 'cond': cond, 'log': log, 'end': end, 'end_turn': et,
            'b_turns': len([h for h in log if h['who'] == 'B'])}


def main():
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    tree = "\n\n树（位置必须来自它）：\n" + sparse_view(trunk)
    runs = []
    for cond, sysp, n in (('T1', BASE_SYS + tree, 3),
                          ('T2', BUDGET_SYS + tree, 3),
                          ('T3', BASE_SYS + tree, 3)):
        for rid in range(1, n + 1):
            r = one(rid, cond, sysp)
            runs.append(r)
            lastb = [h['text'] for h in r['log'] if h['who'] == 'B']
            print("%s run%d  终止于第 %d 段（%s）  乙发言 %d 次"
                  % (cond, rid, r['end_turn'], r['end'], r['b_turns']))
            if cond == 'T3':
                jv = [h['text'] for h in r['log'] if h['who'] == 'JUDGE']
                print("        第三方判定序列：%s" % " / ".join(x.split('\n')[0][:18] for x in jv))
            print("        最后一轮：%s" % (lastb[-1].replace('\n', ' ')[:90] if lastb else '—'))
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding='utf-8')
    print("\n已写 %s" % OUT)


if __name__ == '__main__':
    main()
