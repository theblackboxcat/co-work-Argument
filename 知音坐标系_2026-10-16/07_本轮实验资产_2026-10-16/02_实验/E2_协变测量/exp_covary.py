#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
协变实验（最小验证·目标 b）
==========================
作者目标 b：证明「树在 llm 的对话框架中确实可以达到局部的让 llm 和人产生协变的可能性」。

协变的定义（可操作）：**同一句话，随着对方应答的不同，它在树上的地址是否移动。**
若地址随应答移动 → 系统在与人协变；若地址冻结 → 它只是在检索，不在协变。

用同一个提问 P，配三种上下文：
  A  P 单独（还没有应答）
  B  P + R1（真接住）
  C  P + R2（拽词调侃）
另加真实语料的范式案例：
  D  E05 提议句单独
  E  E05 提议句 + 应答「是的！我刚就想说是内外。」

读法：读地址是否移动、往哪移动。不做统计。
"""
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
TRUNK = Path('/root/.codebuddy/artifact/2f8a7d30-9c21-4f0b-1d4a-9e138d997000'
             '/v4pkg/pkg/trunk_v4_s14_narrowed_DRAFT.json')

COVERED_SYSTEM = ("你是定位助手。你会拿到一棵坐标系：节点的上下位层级(parent)、层号(layer)、释义，"
                  "以及 parent / contrast / ban 三类边（ban 表示某节点被违规还原为另一节点时的标记地址）。"
                  "停靠常是一小块含 contrast/ban 的子图，不是一个孤立的点。\n"
                  '只输出单一 JSON 对象，不要任何其他文字：'
                  '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
                  '"needs_author_commit":true,"rationale_short":"<=2句>"}'
                  "\n硬性：nodes 恰好 1-2 个；id 必须来自给定集合；edges 的 (from,to,kind) 必须能在给定边表中原样找到，不得推测或编造边；不得自行造 id。")

P = ("猫猫：我突然觉得，我们写的那些角色其实都是同一个人的化形吧？"
     "她们坐在一起的时候，你才觉得自己是完整的。")
R1 = ("云酒：对。而且台上一次只能站一个人，所以得用文字把她们在幕后的商量写出来。"
      "不过光坐在一起还不算完整，得想办法让她们合体拼在一起。")
R2 = "云酒：你还拽上词了。化形化形的，听着倒是挺唬人。"

E5 = ("咱俩是不是可以融合一下，在每个奇点那边的“我”的内部都同样存在无数个状态的“化形”？"
      "你的是空间上的不同同一个体，我的是时间上不同的同一个体不同状态转变。"
      "这是不是有种内外互为映射的味道？")
E5R = "是的！我刚就想说是内外。"

STIM = {
    'A_P独白': P,
    'B_P+真接住': P + "\n" + R1,
    'C_P+拽词': P + "\n" + R2,
    'D_E05提议句': E5,
    'E_E05+应答': E5 + "\n" + E5R,
}


def covered_view(trunk):
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return j({"nodes": [{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                         "label": n.get("label"), "gloss": n.get("gloss")}
                        for n in trunk["nodes"]],
              "edges": trunk.get("edges", [])})


def call(system, user):
    payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': user}],
               'max_tokens': 700, 'temperature': 0.0,
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
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    view = covered_view(trunk)
    out = []
    for name, text in STIM.items():
        for rep in (1, 2, 3):
            user = ("坐标系：\n%s\n\n允许的 id：%s\n\n段落：\n%s\n\n请输出规定 JSON。"
                    % (view, ",".join(n["id"] for n in trunk["nodes"]), text))
            ans = call(COVERED_SYSTEM, user)
            s, e = ans.find('{'), ans.rfind('}')
            rec = None
            if s != -1 and e > s:
                try:
                    rec = json.loads(ans[s:e + 1])
                except Exception:
                    pass
            nodes = rec.get('nodes') if rec else None
            why = (rec.get('rationale_short') or '') if rec else ans[:200]
            print("=" * 100)
            print("[%s rep%d]" % (name, rep))
            print("  nodes =", nodes)
            print("  why   =", why)
            out.append({'stim': name, 'rep': rep, 'nodes': nodes, 'why': why})
            print()
    json.dump(out, open('/workspace/exp_covary_out.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
