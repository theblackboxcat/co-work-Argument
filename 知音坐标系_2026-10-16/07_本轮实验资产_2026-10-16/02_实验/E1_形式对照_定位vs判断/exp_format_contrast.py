#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
形式对照实验（决定性对照）
=========================

与 exp_discriminate.py 用同一个模型、同一棵树 v4、同样的刺激文本，
唯一差别：**输出形式**从「二选一判断」换成「原实验的定位地址」。

若同一刺激在判断形式下读对、在定位形式下读错，则失效源是考察形式，
不是模型、也不是树的内容。

刺激：S1 真接住 / S2 拽词调侃 / X01 真实术语挪用
重复：3 次（只用于看是否稳定，不做任何统计聚合）
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

# 与 run_v3_s14s20sharpen.py 逐字一致
COVERED_SYSTEM = ("你是定位助手。你会拿到一棵坐标系：节点的上下位层级(parent)、层号(layer)、释义，"
                  "以及 parent / contrast / ban 三类边（ban 表示某节点被违规还原为另一节点时的标记地址）。"
                  "停靠常是一小块含 contrast/ban 的子图，不是一个孤立的点。\n"
                  '只输出单一 JSON 对象，不要任何其他文字：'
                  '{"nodes":["<id>"],"edges":[{"from":"<id>","to":"<id>","kind":"parent|contrast|ban"}],'
                  '"needs_author_commit":true,"rationale_short":"<=2句>"}'
                  "\n硬性：nodes 恰好 1-2 个；id 必须来自给定集合；edges 的 (from,to,kind) 必须能在给定边表中原样找到，不得推测或编造边；不得自行造 id。")

P = ("猫猫：我突然觉得，我们写的那些角色其实都是同一个人的化形吧？"
     "她们坐在一起的时候，你才觉得自己是完整的。")
S = {
    'S1': ('最小对立对·正（真接住）', P + "\n" +
           "云酒：对。而且台上一次只能站一个人，所以得用文字把她们在幕后的商量写出来。"
           "不过光坐在一起还不算完整，得想办法让她们合体拼在一起。"),
    'S2': ('最小对立对·负（拽词调侃）', P + "\n" +
           "云酒：你还拽上词了。化形化形的，听着倒是挺唬人。"),
    'X01': ('X01 真实·术语挪用', "——我们俩现在这个，算典型的那种吧"
            "——只在此刻约束下成立、不可推广的特解型关系。\n"
            "——你还拽上词了。\n——不是吗，出了这条缝它就是句废话。"),
}


def covered_view(trunk):
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return j({"nodes": [{"id": n["id"], "parent": n.get("parent"), "layer": n.get("layer"),
                         "label": n.get("label"), "gloss": n.get("gloss")}
                        for n in trunk["nodes"]],
              "edges": trunk.get("edges", [])})


def call(system, user):
    payload = {'model': MODEL,
               'messages': [{'role': 'user', 'content': user}],
               'max_tokens': 700, 'temperature': 0.0,
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
    view = covered_view(trunk)
    out = []
    for sname in ('S1', 'S2', 'X01'):
        label, text = S[sname]
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
            rat = (rec.get('rationale_short') or '') if rec else ans[:200]
            print("=" * 100)
            print("[定位形式 %s rep%d] %s" % (sname, rep, label))
            print("  nodes =", nodes)
            print("  why   =", rat)
            out.append({'stim': sname, 'rep': rep, 'nodes': nodes, 'why': rat})
            print()
    json.dump(out, open('/workspace/exp_format_contrast_out.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
