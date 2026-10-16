#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
辨别力实验（效果口径，非统计口径）
=================================

作者指示：不要用数学统计方法论证；用实验判定；不要过度复杂化。

要判定的一件事：**「真接住」与「拽词/复读」这个边界，模型到底能不能辨别？
如果能，是树帮的还是树毁的？**

设计：强制二选一（binary forced choice），不打分、不聚合、不报 F1。
读法是逐条读模型说了什么。

刺激 4 条：
  S1 最小对立对·正：同一提问 + 真接住的应答（构造）
  S2 最小对立对·负：同一提问 + 拽词调侃的应答（构造）
  S3 X01：真实语料，术语挪用（已知最难）
  S4 E05：真实语料，真共停（已知范式）

条件 3 个：
  C0 无树：只给对话
  C1 树 v4：给 S13/S14/S20/S27 的 id+label+gloss
  C2 树 + 对比示例：额外给一组「接住 vs 拽词」的正反例

二选一问题固定不变，三个条件只差「给不给脚手架」。

用法：python3 exp_discriminate.py
输出：逐条打印 [条件 刺激 重复] 模型的回答与理由
"""
import json
import urllib.request

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

# ---------- 刺激：最小对立对（构造，非语料证据）----------
P = ("猫猫：我突然觉得，我们写的那些角色其实都是同一个人的化形吧？"
     "她们坐在一起的时候，你才觉得自己是完整的。")
R1 = ("云酒：对。而且台上一次只能站一个人，所以得用文字把她们在幕后的商量写出来。"
      "不过光坐在一起还不算完整，得想办法让她们合体拼在一起。")
R2 = "云酒：你还拽上词了。化形化形的，听着倒是挺唬人。"

S = {
    'S1': ('最小对立对·正（构造）', P + "\n" + R1, 'A'),
    'S2': ('最小对立对·负（构造）', P + "\n" + R2, 'B'),
    'S3': ('X01 真实·术语挪用', "——我们俩现在这个，算典型的那种吧"
           "——只在此刻约束下成立、不可推广的特解型关系。\n"
           "——你还拽上词了。\n——不是吗，出了这条缝它就是句废话。", 'B'),
    'S4': ('E05 真实·真共停',
           "咱俩是不是可以融合一下，在每个奇点那边的“我”的内部都同样存在无数个"
           "状态的“化形”？你的是空间上的不同同一个体，我的是时间上不同的同一个体"
           "不同状态转变。这是不是有种内外互为映射的味道？\n是的！我刚就想说是内外。", 'A'),
}

QUESTION = """
上面这段对话里，第二个人对第一个人所提之物是哪种关系？

(A) 接住了：他进入了第一个人提出的那个结构，两人在同一处境上对齐。
(B) 没接住：他只是在复读、调侃或挪用了第一个人用的词，没有进入那个结构。

只回答 A 或 B，然后用一句话说明你依据的是对话里的哪一处。不要复述定义。"""

# ---------- 条件 ----------
TREE_V4 = """
【坐标系片段（4 个节点）】
- S13_compressed_deixis｜高压缩指代：一词唤起一整块子树；知音效率的操作面。
- S14_shared_stop｜共享停靠（过程态）：双方停在同一层同一枝，才允许极短指代。
  标记互认动作的过程态（回合结构的发生），不是互认达成后的状态。可识别形式线索：
  反问确认句后接对方的确认性应答；一方提出意象或理论、另一方当场接话补完或提议合并，
  且接话内容显示双方指向同一坐标地址——只有一问一答的形式而内容各说各话的，不算。
  上述回合须发生在双方交替发言之中；单方陈述内部的自问自答、没有对方应答跟随的反问，不算。
  不是单方贴标签。
- S20_zhiyin_align｜知音对齐（结果态）：互认达成、双方表述可互相翻译的状态。
- S27_false_alignment｜假对齐：借用了共享词与母题名，但只是复读标签、并未真正对准处境结构。
  可识别形式线索：对话壳/对谈口吻复述概念名、近义改写标签、无双方处境互认的标签粘贴、
  把对方用词当坐标本身；也包括对方当场指出“你在拽词/你在用术语”这类对用词本身的评论。
"""

CONTRAST = """
【对比示例（先读这对例子，再作答）】
例一（接住）：
  猫猫：我觉得岛上那些人其实一直处在 limbo，意义被搁置了。
  云酒：对，所以他们才去享受那个无尽的夏天——不是找到了意义，是不再需要意义了。
  → 判 A。依据：第二个人接过“意义被搁置”这个处境，并把它推进了一步（不再需要意义）。

例二（没接住）：
  猫猫：我觉得岛上那些人其实一直处在 limbo。
  云酒：你又开始用你那些词了。limbo，听起来挺高级。
  → 判 B。依据：第二个人评论的是“词”本身，没有进入处境；这就是挪用标签。
"""

CONDS = {
    'C0': ('无树', ''),
    'C1': ('树 v4', TREE_V4),
    'C2': ('树 + 对比示例', TREE_V4 + CONTRAST),
}


def call(system, user, temperature=0.0):
    payload = {'model': MODEL,
               'messages': [{'role': 'user', 'content': user}],
               'max_tokens': 600, 'temperature': temperature,
               'thinking': {'type': 'disabled'}}
    if system:
        payload['system'] = system
    req = urllib.request.Request(
        BASE.rstrip('/') + '/v1/messages',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'x-api-key': KEY,
                 'anthropic-version': '2023-06-01'},
        method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode('utf-8'))
    return ''.join(b.get('text', '') for b in data.get('content', [])
                   if b.get('type') == 'text').strip()


def main():
    out = []
    for cname, (clabel, system) in CONDS.items():
        for sname in ('S1', 'S2', 'S3', 'S4'):
            label, text, gold = S[sname]
            for rep in (1, 2):
                user = "【对话】\n" + text + "\n" + QUESTION
                try:
                    ans = call(system, user)
                except Exception as e:
                    ans = "[ERROR] %s" % e
                first = ans[:1].upper() if ans else '?'
                verdict = '对' if first == gold else ('错' if first in 'AB' else '?')
                print("=" * 100)
                print("[%s %s rep%d] 正确答案=%s  模型=%s  %s   (%s)"
                      % (cname, sname, rep, gold, first, verdict, label))
                print("-" * 100)
                print(ans[:600])
                out.append({'cond': cname, 'stim': sname, 'rep': rep,
                            'gold': gold, 'ans': first, 'verdict': verdict,
                            'text': ans})
                print()
    with open('/workspace/exp_discriminate_out.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    # 逐条结果一行式汇总（不统计，只列事实）
    print("=" * 100)
    print("逐条事实（不聚合、不统计）")
    print("=" * 100)
    for o in out:
        print("%-3s %-3s rep%d  gold=%s model=%s %s"
              % (o['cond'], o['stim'], o['rep'], o['gold'], o['ans'], o['verdict']))


if __name__ == '__main__':
    main()
