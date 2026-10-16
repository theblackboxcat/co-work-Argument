#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E11b　纯符号对照臂（补 E11 的仪器缺陷）
=======================================

E11 仪器缺陷：A 臂的节点 id 自带英文语义词面（如 S24_psychological_explanation），
模型判据大量引用该词面——A 臂测的是「弱语义锚」而非「纯符号」。

本实验补两臂，把 id 换成无语义编号（N01..N32 按原顺序保结构映射，
parent/edges 同步替换），其余协议与 E11 逐字一致：

  A' 无语义 id              ：无 label 无 gloss   —— 真正的纯符号臂
  B' 无语义 id + label      ：有 label 无 gloss

预测（预注册）：
  A' ≤ B' < C（C 臂 = E11 的 id+label+gloss，contains 4/9）
  若 A' 输出紊乱/编造 → 「纯符号完全失效」得证，Obs 1 对应闭环
  若 A' ≈ A（都靠英文词面混到部分分数）→ 说明符号词面本身有锚定力，需下调结论

刺激与 gold 与 E11/E3 一致。3 刺激 × 3 重复 × 2 臂 = 18 次调用。
"""
import json
import time
import urllib.request
from pathlib import Path

BASE = 'http://note3-prev-api.askdiandian.com'
MODEL = 'dots3-note-prev'
HERE = Path(__file__).resolve().parent
TRUNK = HERE / 'trunk_v8_错位默认_DRAFT.json'
OUT = HERE / 'exp_manifold_b_out.json'

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

PROMPT_HEAD = ("你是定位助手。你会拿到一棵坐标系：节点的上下位层级(parent)、层号(layer)")
PROMPT_TAIL = (
    "，以及 parent / contrast / ban 三类边。\n"
    '只输出单一 JSON 对象，不要任何其他文字：'
    '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
    '"needs_author_commit":true,"rationale_short":"<=2句>"}'
    "\n硬性：nodes 恰好 1-2 个；id 必须来自给定集合；edges 的 (from,to,kind) 必须能在给定边表中原样找到，"
    "不得推测或编造边；不得自行造 id。")

ARMS = {
    "A'": PROMPT_HEAD + PROMPT_TAIL,
    "B'": PROMPT_HEAD + "、标签(label)" + PROMPT_TAIL,
}


def load_key():
    p = HERE / 'config.json'
    if p.exists():
        try:
            return json.load(open(p, encoding='utf-8')).get('api_key', '')
        except Exception:
            pass
    import os
    return os.environ.get('DOTS3_KEY', '')


def remap(trunk):
    """原 id -> 无语义编号 N01..N32（按节点表顺序），结构原样保留。"""
    nodes = trunk['nodes']
    m = {n['id']: 'N%02d' % (i + 1) for i, n in enumerate(nodes)}
    return m


def views(trunk):
    nodes = trunk['nodes']
    m = remap(trunk)
    edges = [{'from': m.get(e['from'], e['from']), 'to': m.get(e['to'], e['to']),
              'kind': e.get('kind')} for e in trunk.get('edges', [])]
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    common = lambda ns: j({"nodes": ns, "edges": edges})
    vA = common([{"id": m[n["id"]], "parent": m.get(n.get("parent")),
                  "layer": n.get("layer")} for n in nodes])
    vB = common([{"id": m[n["id"]], "parent": m.get(n.get("parent")),
                  "layer": n.get("layer"), "label": n.get("label")} for n in nodes])
    return {"A'": vA, "B'": vB}, m


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


KEY = load_key()


def main():
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    v, m = views(trunk)
    ids = ",".join(sorted(m.values()))
    out = []
    for arm in ("A'", "B'"):
        for sname in ('S1', 'S2', 'X01'):
            label, text, gold_orig = S[sname]
            gold = m[gold_orig]  # gold 从映射动态计算，杜绝手误
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
                         ' 杂质=%s' % impurity if impurity else '', lat, label))
                print("  why =", str(rat)[:220])
                out.append({'arm': arm, 'stim': sname, 'rep': rep, 'gold': gold,
                            'nodes': nodes, 'why': rat, 'exact': exact,
                            'contains': contains, 'impurity': impurity,
                            'latency_s': round(lat, 1)})
                print()
    json.dump({'id_map': m, 'runs': out}, open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print("=" * 100)
    print("汇总（对比 E11：A 0/9、B 0/9、C 4/9、D 2/9 contains）")
    print("=" * 100)
    for arm in ("A'", "B'"):
        rs = [o for o in out if o['arm'] == arm]
        line = "  ".join("%s:%s%s" % (o['stim'],
                                      'E' if o['exact'] else ('c' if o['contains'] else 'x'),
                                      '+' + ",".join(o['impurity']) if o['impurity'] else '')
                         for o in rs)
        print("臂%s | %s" % (arm, line))
    print("\nid 映射抽查：", {k: m[k] for k in
      ('S14_shared_stop', 'S27_false_alignment', 'S03_allegorical_transform')})
    print("输出：", OUT)


if __name__ == '__main__':
    main()
