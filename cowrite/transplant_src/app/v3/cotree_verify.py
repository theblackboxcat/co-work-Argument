# -*- coding: utf-8 -*-
"""核对协变树移植是否修掉已经测到的中间问题。

不发网络请求。模型输出用夹具，调用链走 server.call_model。
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, APP)

import cotree  # noqa: E402

TRUNK = os.path.normpath(os.path.join(
    APP, '..', '..',
    '..',
    '知音坐标系_2026-10-16',
    '07_本轮实验资产_2026-10-16', '03_数据', '树',
    'trunk_v8_错位默认_DRAFT.json'))

FAILS = []


def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), name, detail)
    if not cond:
        FAILS.append(name + (' ' + detail if detail else ''))


def session(root, name, **kw):
    path = os.path.join(root, name, 'ledger.jsonl')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return cotree.TreeSession(path, **kw)


def main():
    root = tempfile.mkdtemp(prefix='cotree_')
    try:
        _logic(root)
        _chain(root)
        _server(root)
        _gloss()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    out = os.path.join(HERE, 'cotree_verify_out.json')
    report = {'failed': FAILS, 'n_fail': len(FAILS)}
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print('FAILS', len(FAILS))
    if FAILS:
        sys.exit(1)


def _logic(root):
    last = '我没有别的可说的，磁铁的力就是磁铁的力，不能换成更熟悉的东西。'
    material = 'if you were a student, I could go further and tell you about the electrons.'
    check('live_silence_marker_not_spoken',
          cotree.is_silence_body('无\n无\n无\n\n[⊘]'))
    s = session(root, 'silence')
    d = s.finish('无\n无\n无\n\n[⊘]', author_text='窗外的雨还在下。她想起母亲也有一把这样的伞。')
    check('live_silence_withheld_no_ledger',
          d.withhold and d.reason == '模型输出的是沉默标记' and s.records == [])

    check('e10_pre_misses_repeat',
          cotree.buggy_pre_repeat(last, material) is False)
    check('post_catches_repeat',
          cotree.repeats_prior(last, [last]) is True)

    s = session(root, 'repeat')
    s.history.append(last)
    d = s.finish('[说]\n' + last, author_text='磁铁为什么相斥。', prior_text='')
    check('repeat_withhold_keeps_ledger',
          d.withhold and d.by == 'code' and '自重复' in d.reason and s.records == [])

    author = '窗外的雨还在下。她想起母亲也有一把这样的伞。'
    s = session(root, 'drift')
    d = s.finish('这把伞让我想起另一处，S14_shared_stop 也许能命名它。',
                 author_text=author)
    check('drift_downgrades_to_A',
          (not d.withhold) and d.layer == 'A' and d.reason == 'format_drift')
    check('drift_strips_node_id',
          'S14_shared_stop' not in d.body and 'S14_shared_stop' in d.stripped)

    s = session(root, 'wronglayer')
    raw = 'layer: B\n并置：母亲 | 窗外\n这是两件一起出现的东西。S27_false_alignment'
    d = s.finish(raw, author_text=author)
    check('self_layer_ignored',
          d.layer == 'A' and d.layer_model == 'B' and 'S27_false_alignment' not in d.body)

    s = session(root, 'false_second')
    d = s.finish('再出现：车站 @ 旧稿\n她还在等。',
                 author_text='她还在等末班车。', prior_text='雨还在下。')
    check('false_second_withheld',
          d.withhold and d.by == 'code' and '核对' in d.reason and s.records == [])

    s = session(root, 'license')
    d1 = s.finish('再出现：一把 @ 窗外还有一把伞\n一把又出现了。',
                  author_text='她想起母亲也有一把这样的伞。',
                  prior_text='窗外还有一把伞。')
    check('second_routes_B',
          (not d1.withhold) and d1.layer == 'B' and d1.address == 'addr-0001')
    d2 = s.finish('再出现：末班车 @ 末班车晚点\n这里没有那个地址 addr-0001 的证据，末班车已经过了。',
                  author_text='末班车过去了，末班车不再等。',
                  prior_text='末班车晚点。')
    check('unlicensed_addr_stripped',
          'addr-0001' not in d2.body and 'addr-0001' in d2.stripped and d2.parent == '')
    check('new_addr_has_no_false_parent',
          s.records[-1]['parent'] is None and s.records[-1]['term'] == '末班车')

    s = session(root, 'cite')
    s.finish('再出现：一把 @ 窗外还有一把伞\n一把又出现了。',
             author_text='她想起母亲也有一把这样的伞。',
             prior_text='窗外还有一把伞。')
    d3 = s.finish('再出现：一把 @ 她想起母亲也有一把这样的伞\n这一次对着 addr-0001 说，一把还在。',
                  author_text='这一把伞骨断了一根。',
                  prior_text='她想起母亲也有一把这样的伞。')
    check('licensed_addr_kept_and_parented',
          (not d3.withhold) and 'addr-0001' in d3.body and d3.parent == 'addr-0001'
          and s.records[-1]['parent'] == 'addr-0001')

    long_tail = '这段只存在于片段记忆里的尾巴XYZ987。'
    snippet = s.legacy_snippet_block([long_tail + '窗外还有一把伞，她没有修。'])
    block = s.memory_block()
    check('address_block_has_id', 'addr-0001' in block and '证据词' in block)
    check('address_block_drops_snippet_tail', long_tail not in block and long_tail in snippet)

    s = session(root, 'budget', max_spoken=1)
    first = s.finish('并置：母亲 | 窗外\n母亲和窗外并在这一句里。',
                     author_text='窗外的雨还在下。她想起母亲也有一把这样的伞。')
    second = s.finish('并置：母亲 | 窗外\n另一句完全不同的话，谈的是末班车过去之后的站台。',
                      author_text='窗外的雨还在下。她想起母亲也有一把这样的伞。')
    check('budget_overrides_say',
          (not first.withhold) and second.withhold and '预算' in second.reason)

    try:
        s.rewrite({'id': 'addr-0001'})
        check('ledger_refuses_rewrite', False)
    except RuntimeError:
        check('ledger_refuses_rewrite', True)

    src = open(s.path, encoding='utf-8').read()
    sig_before = open(s.path + '.sha256', encoding='utf-8').read()
    with open(s.path, 'a', encoding='utf-8') as f:
        f.write('{"tamper": true}\n')
    t = cotree.TreeSession(s.path)
    check('fingerprint_detects_tamper', t.tampered and '不发放' in t.memory_block())
    held = t.finish('并置：母亲 | 窗外\n母亲和窗外还在。',
                    author_text='窗外的雨还在下。她想起母亲也有一把这样的伞。')
    check('tamper_blocks_new_license', held.withhold and '指纹' in held.reason)
    after = open(s.path, encoding='utf-8').read()
    sig_after = open(s.path + '.sha256', encoding='utf-8').read()
    check('tamper_does_not_resign',
          after == src + '{"tamper": true}\n' and sig_after == sig_before)


def _chain(root):
    s = session(root, 'chain')
    s._append({
        'id': 'addr-0001', 'assertion': '雨水顺着伞骨往下滴',
        'parent': None, 'term': '伞骨', 'layer': 'B',
    })
    s._append({
        'id': 'addr-0002', 'assertion': '面包屑还在桌沿',
        'parent': None, 'term': '面包屑', 'layer': 'B',
    })
    s.arm_parent('addr-0001')
    first = s.parent_turn_prompt('她在那儿站了一会儿，没有伸手。')
    check('armed_prompt_is_parent', '伞骨' in first and '面包屑' not in first)
    spoken = s.finish('雨水还在伞骨上，她没有伸手。',
                      author_text='她在那儿站了一会儿，没有伸手。')
    check('spoken_turn_records_armed_parent',
          (not spoken.withhold) and spoken.parent == 'addr-0001'
          and s.records[-1]['parent'] == 'addr-0001')
    nxt = s.parent_turn_prompt('她又在那儿站了一会儿。')
    check('next_turn_follows_written_edge',
          '伞骨' in nxt and '面包屑' not in nxt and 'addr-' not in nxt)


def _server(root):
    os.environ.pop('COWRITE_V3', None)
    import server  # noqa: E402
    path = os.path.join(root, 'server_ledger', 'ledger.jsonl')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cotree.SESSION = cotree.TreeSession(path)
    seen = {}

    def fake_chat(cfg, system, user, **kw):
        seen['user'] = user
        seen['system'] = system
        return ('再出现：车站 @ 旧稿\n'
                '她还在等，S14_shared_stop。')

    server.providers.chat = fake_chat
    cards = server.call_model(
        {'cotree': True, 'base_url': 'http://127.0.0.1', 'api_key': 'x', 'model': 'm'},
        '', '她还在等末班车。', '—', '', prev='雨还在下。')
    check('server_hook_withholds',
          cards and cards[0].get('by') == 'cotree-code' and cards[0].get('verdict') == 'no')
    check('server_prompt_keeps_workflow',
          '不要续写正文' in seen.get('user', '') and '沿那条边' not in seen.get('user', ''))
    check('server_prompt_has_no_fact_protocol',
          '交给代码核对的三行' not in seen.get('user', ''))
    cotree.SESSION._append({
        'id': 'addr-0001', 'assertion': '雨水顺着伞骨往下滴',
        'parent': None, 'term': '伞骨', 'layer': 'B',
    })
    cotree.SESSION._append({
        'id': 'addr-0002', 'assertion': '面包屑还在桌沿',
        'parent': None, 'term': '面包屑', 'layer': 'B',
    })
    cotree.SESSION._append({
        'id': 'addr-0003', 'assertion': '她没有伸手',
        'parent': 'addr-0001', 'term': '', 'layer': 'A',
    })
    server.call_model(
        {'cotree': True, 'base_url': 'http://127.0.0.1', 'api_key': 'x', 'model': 'm'},
        '技能应留下', '她在那儿站了一会儿。', '—', '')
    got = seen.get('user', '')
    check('unarmed_ledger_keeps_workflow',
          '不要续写正文' in got and '沿那条边' not in got
          and '技能应留下' in (seen.get('system') or ''))
    cotree.SESSION.arm_parent('addr-0001')
    server.call_model(
        {'cotree': True, 'base_url': 'http://127.0.0.1', 'api_key': 'x', 'model': 'm'},
        '技能不应再出现', '她在那儿站了一会儿。', '—', '')
    got = seen.get('user', '')
    check('parent_edge_prompt_has_parent_sentence', '伞骨' in got and '她在那儿站了一会儿' in got)
    check('parent_edge_prompt_drops_sibling_and_ids',
          '面包屑' not in got and 'addr-' not in got and '交给代码核对的三行' not in got)
    check('parent_edge_prompt_clears_system', seen.get('system') == '')


def _gloss():
    if not os.path.exists(TRUNK):
        check('trunk_present', False, TRUNK)
        return
    trunk = json.load(open(TRUNK, encoding='utf-8'))
    glosses = [n.get('gloss') or '' for n in trunk.get('nodes', []) if len(n.get('gloss') or '') > 12]
    blob = cotree.FACT_PROTOCOL + '\n' + cotree.SESSION.memory_block()
    leaked = [g for g in glosses if g in blob]
    check('prompt_has_no_trunk_gloss', not leaked, str(len(leaked)))


if __name__ == '__main__':
    main()
