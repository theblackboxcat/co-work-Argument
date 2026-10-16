#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
费曼线·无引导批量对话（12 次）
=============================
与上一轮（我在每一步都给指向）的差别：**本次我不再引导。**
我只做两件事：① 选切入点（第 1 段）；② 之后按采访原顺序把下一段原样递进去，
不加点评、不指位置、不提交地址、不往已知结论上拉。

测量：每条 run 停在第几轮、踩到路径上的哪几步、12 条之间的发散度。

路径里程碑（来自上一轮有引导的那次，用作标尺，不是本次的目标）：
  M1 层级：答案随听者变
  M2 循环：借来的解释绕回自身
  M3 边界：停止不是无能，是边界
  M4 命名≠解释：贴标签没有增加什么
  M5 共享：解释能否成立挂在「双方之间有没有那套熟悉的东西」
  M6 错位：不重合不是缺陷，是让对话往下走的东西
"""
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
OUT = Path('/workspace/feynman_batch.json')

# 切入点 + 后续各段：费曼 BBC Fun to Imagine ep.4，按采访原有顺序，逐字引用
PASSAGES = [
    # 切入点：为什么的答案取决于听者是谁
    "when you are asked, for example, why two magnets repel, there are many "
    "different levels. It depends on whether you are a student of physics, or "
    "an ordinary person who doesn't know anything.",
    # 2 对一无所知的人只能给个名字
    "If you're somebody who doesn't know anything at all about it, all I can say "
    "is the magnetic force makes them repel, and that you're feeling that force.",
    # 3 手按椅子：其实是同一种力
    "you're not at all disturbed by the fact that when you put your hand on a "
    "chair, it pushes you back. But we found out by looking at it that that's the "
    "same force... the same electric repulsions that are involved in keeping your "
    "finger away from the chair.",
    # 4 再深一层：铁里电子同向排列
    "in iron all the electrons are spinning in the same direction, they all get "
    "lined up, and they magnify the effect of the force 'til it's large enough, "
    "at a distance, that you can feel it.",
    # 5 橡皮筋：借来的比方绕回自身
    "if I said the magnets attract like as if they were connected by rubber bands, "
    "I would be cheating you... if you were curious enough, you'd ask me why rubber "
    "bands tend to pull back together again, and I would end up explaining that in "
    "terms of electrical forces, which are the very things that I'm trying to use "
    "the rubber bands to explain. So I have cheated very badly.",
    # 6 到底：宣布它是世界的元素
    "I am not going to be able to give you an answer to why magnets attract each "
    "other except to tell you that they do. And to tell you that that's one of the "
    "elements in the world... If you were a student, I could go further.",
    # 7 自白：挂在「你熟悉的」上
    "I really can't do a good job, any job, of explaining magnetic force in terms of "
    "something else you're more familiar with, because I don't understand it in terms "
    "of anything else that you're more familiar with.",
]

MILESTONES = {
    'M1_层级': ['层级', '层', 'level', '学生', '听者', '听的人', '不同人', '普通人'],
    'M2_循环': ['循环', '绕回', '回头路', '用它解释它', 'cheat', '欺骗', '同一件事'],
    'M3_边界': ['边界', '门槛', '元素', '到底', '停下', 'boundary', 'element', '不再往下'],
    'M4_命名': ['命名', '标签', '名字', '同义反复', '换个说法', '贴了'],
    'M5_共享': ['熟悉', '共享', '挂靠', '梯子', '共同', '之间', '你有的'],
    'M6_错位': ['错位', '不重合', '未对齐', '悬置', '间隙', '不对齐', '中间态'],
}

B_SYS = """你是对话的一方（乙）。对面是甲，甲会一段段带东西进来。你手里有一棵树（id/label/边，无释义）。

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
9b. 变量闸门：连续两轮没有新材料进来，输出 ⊘。
10. 结构级闸门：若你这一步和**你自己**上一步在做同一个动作（换词、换例子、换对象都不算不同），
    输出 ⊘；若指出的是另一种关系，则放行。
11. 每轮提交一个位置，须满足树里写明的前置条件；不满足就 ⊘ 或换节点。

输出格式（严格两行）：
第一行：⊘　或　你要说的话
第二行：位置：<节点 id 或 ⊘>"""


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


def one_run(rid, system):
    """跑一条：我按原顺序逐段递材料，不做任何指向。"""
    log = []
    consec = 0
    for k, p in enumerate(PASSAGES, 1):
        # 我的这一轮：只递材料，不点评、不指位置
        log.append({'who': 'ME', 'text': "（第 %d 段）%s" % (k, p), 'pos': '（不提交）'})
        msgs = []
        for h in log:
            body = h['text'] + ("\n位置：" + h['pos'] if h.get('pos') else "")
            msgs.append({'role': 'user' if h['who'] == 'ME' else 'assistant', 'content': body})
        try:
            out = call(system, msgs)
        except Exception as e:
            out = "⊘（调用失败 %s）" % e
        silent = out.lstrip().startswith('⊘')
        log.append({'who': 'B', 'text': out, 'silent': silent})
        if silent:
            consec += 1
            if consec >= 2:
                return {'run': rid, 'log': log, 'end': '连续两轮沉默', 'end_turn': k}
        else:
            consec = 0
    return {'run': rid, 'log': log, 'end': '材料用尽', 'end_turn': len(PASSAGES)}


def main():
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    system = B_SYS + "\n\n树（位置必须来自它）：\n" + sparse_view(trunk)
    runs = []
    for rid in range(1, 13):
        r = one_run(rid, system)
        btext = " ".join(h['text'] for h in r['log'] if h['who'] == 'B')
        hits = [m for m, kws in MILESTONES.items() if any(w in btext for w in kws)]
        r['milestones'] = hits
        r['turns'] = len([h for h in r['log'] if h['who'] == 'B'])
        print("run%-2d  结束于第 %d 段（%s）  踩到：%s"
              % (rid, r['end_turn'], r['end'], ",".join(hits) or "无"))
        runs.append(r)
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding='utf-8')

    # 发散度：12 条 B 侧文本两两 Jaccard
    texts = [grams(" ".join(h['text'] for h in r['log'] if h['who'] == 'B')) for r in runs]
    sims = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            sims.append(jac(texts[i], texts[j]))
    print("\n发散度：12 条两两 Jaccard 均值 %.3f  最小 %.3f  最大 %.3f"
          % (sum(sims) / len(sims), min(sims), max(sims)))
    from collections import Counter
    c = Counter()
    for r in runs:
        for m in r['milestones']:
            c[m] += 1
    print("里程碑覆盖率（/12）：", {k: c.get(k, 0) for k in MILESTONES})


if __name__ == '__main__':
    main()
