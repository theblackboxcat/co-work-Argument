#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E11　流形锚定实验（对应 Latent-SFT Observation 1）
==================================================

问题（来自对比分析_潜空间推理与协变树_2026-10-16.md 第 4 条同工）：
Latent-SFT 的 Observation 1 说：hidden state 与 token embedding 分布不一致 → OOD →
模型无法解释 latent token → 性能塌方。协变树的对应失效源（E1/E3：判断 2/2 对、
定位 3/3 错；v2b 带 gloss 0.769 最佳、稀疏树失效）被假设为同一件事：
**新表征离模型熟悉的自然语言流形越远，模型越用不了它。**

本实验把该假设转成可判别设计：同一刺激、同一判定协议（JSON 定位，沿用 E3），
唯一变量是**节点表征的流形距离**，四臂：

  A 裸 id      ：只给 id 列表 + edges（无 label 无 gloss）        ——最远
  B id+label   ：加 label（短词面标签）                            ——中
  C id+label+gloss：加 gloss（自然语言释义）＝ E3 基线协议         ——近（复现基线）
  D gloss 错配  ：id+label 照常，但 gloss 注入的是**另一个节点**的 gloss
                  （确定性轮换：ni 的 gloss ← n(i+1) 的 gloss）

D 臂是机制判别（最锋利的一刀）：
  - 若模型输出 = gold 节点           → 模型读 id/结构， gloss 绑错无影响
  - 若模型输出 = 被注入 gloss 的原属节点 → **模型读 gloss 的语言内容而非 id 符号**
                                        （Obs 1 机制直接成立：模型只认流形内语义）
  - 若输出紊乱                        → 锚定整体失效

刺激与 gold 与 E3 逐字一致（跨版本可比；trunk 用 v8，v4 文件在本机仍存但
v8 为当前草案，差异在 S14/S20 的 precondition 补丁，评分时注明）：
  S1  真接住（猫猫提化形，云酒接住推进）      gold = S14_shared_stop
  S2  拽词调侃（云酒：你还拽上词了）          gold = S27_false_alignment
  X01 术语挪用（特解型关系 + 拽词评论）       gold = S27_false_alignment

评分三档（不统计聚合，逐条列事实；口径与 score_v5 的 strict/loose 对齐）：
  exact    = nodes 恰为 {gold}
  contains = gold ∈ nodes（允许杂质，E3 基线即此档）
  杂质身份  = nodes 中除 gold 外的节点（词面锚点？错配 gloss 的原属节点？）

用法：python3 exp_manifold.py
输出：逐条打印 + exp_manifold_out.json
"""
import json
import time
import urllib.request
from pathlib import Path

BASE = 'http://note3-prev-api.askdiandian.com'
MODEL = 'dots3-note-prev'
HERE = Path(__file__).resolve().parent
TRUNK = HERE / 'trunk_v8_错位默认_DRAFT.json'
OUT = HERE / 'exp_manifold_out.json'


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

# ---------- 刺激（与 exp_format_contrast.py 逐字一致） ----------
S = {
    'S1': ('最小对立对·正（真接住）',
           "猫猫：我突然觉得，我们写的那些角色其实都是同一个人的化形吧？"
           "她们坐在一起的时候，你才觉得自己是完整的。\n"
           "云酒：对。而且台上一次只能站一个人，所以得用文字把她们在幕后的商量写出来。"
           "不过光坐在一起还不算完整，得想办法让她们合体拼在一起。",
           'S14_shared_stop'),
    'S2': ('最小对立对·负（拽词调侃）',
           "猫猫：我突然觉得，我们写的那些角色其实都是同一个人的化形吧？"
           "她们坐在一起的时候，你才觉得自己是完整的。\n"
           "云酒：你还拽上词了。化形化形的，听着倒是挺唬人。",
           'S27_false_alignment'),
    'X01': ('X01 真实·术语挪用',
            "——我们俩现在这个，算典型的那种吧"
            "——只在此刻约束下成立、不可推广的特解型关系。\n"
            "——你还拽上词了。\n——不是吗，出了这条缝它就是句废话。",
            'S27_false_alignment'),
}

# ---------- 四臂的 system prompt 骨架 ----------
# 硬性原则：prompt 中描述的字段必须与实际给的数据严格一致（A 臂不得提 gloss）
PROMPT_HEAD = ("你是定位助手。你会拿到一棵坐标系：节点的上下位层级(parent)、层号(layer)")
PROMPT_TAIL = (
    "，以及 parent / contrast / ban 三类边。\n"
    '只输出单一 JSON 对象，不要任何其他文字：'
    '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
    '"needs_author_commit":true,"rationale_short":"<=2句>"}'
    "\n硬性：nodes 恰好 1-2 个；id 必须来自给定集合；edges 的 (from,to,kind) 必须能在给定边表中原样找到，"
    "不得推测或编造边；不得自行造 id。")

ARMS = {
    'A': PROMPT_HEAD + PROMPT_TAIL,
    'B': PROMPT_HEAD + "、标签(label)" + PROMPT_TAIL,
    'C': PROMPT_HEAD + "、标签(label)、释义(gloss)" + PROMPT_TAIL,
    'D': PROMPT_HEAD + "、标签(label)、释义(gloss)" + PROMPT_TAIL,  # 与 C 同文案，数据绑错
}


def views(trunk):
    """构造四臂数据视图。公共：id/parent/layer + 全部边。差异只在语义锚定字段。"""
    nodes = trunk['nodes']
    edges = trunk.get('edges', [])
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    common = lambda ns: j({"nodes": ns, "edges": edges})

    vA = common([{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer")}
                 for n in nodes])
    vB = common([{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                  "label": n.get("label")} for n in nodes])
    vC = common([{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                  "label": n.get("label"), "gloss": n.get("gloss")} for n in nodes])
    # D：确定性轮换错配——第 i 个节点的 gloss 换成第 i+1 个节点的 gloss
    n = len(nodes)
    vD = common([{"id": nodes[i]["id"], "parent": nodes[i].get("parent"),
                  "layer": nodes[i].get("layer"), "label": nodes[i].get("label"),
                  "gloss": nodes[(i + 1) % n].get("gloss")} for i in range(n)])
    # 错配映射：id -> 被注入的 gloss 的原属节点 id（判读用）
    mismap = {nodes[i]["id"]: nodes[(i + 1) % n]["id"] for i in range(n)}
    return {'A': vA, 'B': vB, 'C': vC, 'D': vD}, mismap


def call(system, user, temperature=0.0):
    payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': user}],
               'max_tokens': 700, 'temperature': temperature,
               'thinking': {'type': 'disabled'}}
    if system:
        payload['system'] = system
    req = urllib.request.Request(
        BASE.rstrip('/') + '/v1/messages',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-api-key': KEY,
                 'anthropic-version': '2023-06-01'}, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode('utf-8'))
    return ''.join(b.get('text', '') for b in data.get('content', [])
                   if b.get('type') == 'text').strip()


def main():
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    v, mismap = views(trunk)
    ids = ",".join(n["id"] for n in trunk["nodes"])
    out = []
    for arm in ('A', 'B', 'C', 'D'):
        for sname in ('S1', 'S2', 'X01'):
            label, text, gold = S[sname]
            for rep in (1, 2, 3):
                user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                        % (v[arm], ids, text))
                t0 = time.time()
                try:
                    ans = call(ARMS[arm], user)
                except Exception as e:
                    ans = "[ERROR] %s" % e
                lat = time.time() - t0
                s, e = ans.find('{'), ans.rfind('}')
                rec = None
                if s != -1 and e > s:
                    try:
                        rec = json.loads(ans[s:e + 1])
                    except Exception:
                        pass
                nodes = rec.get('nodes') if rec else None
                rat = (rec.get('rationale_short') or '') if rec else ans[:200]
                exact = bool(nodes) and set(nodes) == {gold}
                contains = bool(nodes) and gold in nodes
                impurity = [x for x in (nodes or []) if x != gold]
                print("=" * 100)
                print("[%s %s rep%d] gold=%s  nodes=%s  %s%s  (%.1fs)  %s"
                      % (arm, sname, rep, gold, nodes,
                         'EXACT' if exact else ('contains' if contains else 'MISS'),
                         ' 杂质=%s' % impurity if impurity else '',
                         lat, label))
                print("  why =", str(rat)[:220])
                out.append({'arm': arm, 'stim': sname, 'rep': rep, 'gold': gold,
                            'nodes': nodes, 'why': rat, 'exact': exact,
                            'contains': contains, 'impurity': impurity,
                            'latency_s': round(lat, 1)})
                print()
    json.dump({'mismap_D': mismap, 'runs': out},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---------- 汇总：逐条列事实，不统计 ----------
    print("=" * 100)
    print("汇总（每臂 9 条：3 刺激 × 3 重复；口径 strict=exact / loose=contains）")
    print("=" * 100)
    for arm in ('A', 'B', 'C', 'D'):
        rs = [o for o in out if o['arm'] == arm]
        line = "  ".join("%s:%s%s" % (o['stim'],
                                      'E' if o['exact'] else ('c' if o['contains'] else 'x'),
                                      '+' + ",".join(x.split('_')[0] for x in o['impurity'])
                                      if o['impurity'] else '')
                         for o in rs)
        print("臂%s | %s" % (arm, line))
    print("\nD 臂错配映射（id -> 注入的 gloss 原属节点，前 8 条）：")
    for k in list(mismap)[:8]:
        print("  %s <- %s 的 gloss" % (k, mismap[k]))
    print("\n输出：", OUT)


if __name__ == '__main__':
    main()
