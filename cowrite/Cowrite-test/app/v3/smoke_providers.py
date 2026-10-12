# -*- coding: utf-8 -*-
"""provider 适配层冒烟：兼容性、错误分类、探活。

用法： python v3/smoke_providers.py
重点测的是**契约**，不是网络——真实端点不可达时自动跳过而不是判失败。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import providers  # noqa: E402

ok = 0
fail = []


def check(name, cond, extra=''):
    global ok
    if cond:
        ok += 1
        print('  ok   %s %s' % (name, extra))
    else:
        fail.append(name)
        print('  FAIL %s %s' % (name, extra))


print('── 一、向后兼容：老配置进来必须和以前一样 ──────────────')
old = {'base_url': 'http://<API_HOST>',
       'api_key': 'ak_abc123456789xy', 'model': 'dots3-note-prev',
       'api': 'anthropic-messages'}
r = providers.resolve(old)
check('老配置四个字段原样保留',
      r['base_url'] == old['base_url'] and r['model'] == old['model']
      and r['api_key'] == old['api_key'] and r['api'] == old['api'])
check('老配置能被认出是 dots3', r['provider'] == 'dots3', r['provider'])
check('resolve 不改原对象', old.get('provider') is None)

print('\n── 二、预设：只给 provider 就能补全 ────────────────────')
d = providers.resolve({'provider': 'dots3'})
check('dots3 是默认', providers.DEFAULT_ID == 'dots3')
check('dots3 走 anthropic 协议', d['api'] == 'anthropic-messages')
check('dots3 模型名正确', d['model'] == 'dots3-note-prev')
o = providers.resolve({'provider': 'ollama'})
check('ollama 自动补占位 key', o['api_key'] == 'ollama', repr(o['api_key']))
check('ollama 走 openai 协议', o['api'] == 'openai-completions')

print('\n── 三、清单与打码：不能有密钥漏出去 ────────────────────')
lst = providers.list_providers()
check('清单非空', len(lst) >= 8, '%d 条' % len(lst))
check('清单里没有 api_key 字段', not any('api_key' in p for p in lst))
check('清单里没有密钥值漏出',
      not any(('sk-' in str(p)) or ('ak_' in str(p)) for p in lst))
check('每条都有 id/label/api', all(p.get('id') and p.get('label') and p.get('api')
                                   for p in lst))
check('打码保留首尾', providers.mask_key('ak_abc123456789xy') == 'ak_a…89xy')
check('空 key 打码为空', providers.mask_key('') == '')
check('短 key 不泄露长度', providers.mask_key('abc') == '••••')

print('\n── 四、错误分类：故障 ≠ 没有 ────────────────────────────')
check('EmptyReplyError 是 ProviderError 的子类',
      issubclass(providers.EmptyReplyError, providers.ProviderError))
check('configured：没 key 不算通', providers.configured({}) is False)
check('configured：有 key 有端点才算通',
      providers.configured({'base_url': 'http://x', 'api_key': 'k'}) is True)

print('\n── 五、探活：不通要说得清为什么 ─────────────────────────')
bad = {'provider': 'custom-openai', 'base_url': 'http://127.0.0.1:9/v1',
       'api_key': 'x', 'model': 'm'}
okk, msg = providers.probe(bad, timeout=6)
check('连不上的端点 → False', okk is False, msg[:60])
check('原因里说得出是哪一步', bool(msg), msg[:60])
miss = {'provider': 'deepseek', 'base_url': 'https://api.deepseek.com', 'model': 'm'}
okk2, msg2 = providers.probe(miss, timeout=6)
check('没填 key → False 且提示环境变量',
      okk2 is False and 'DEEPSEEK_API_KEY' in msg2, msg2[:70])

print('\n── 六、真实端点（不可达则跳过，不算失败） ───────────────')
try:
    cfg = providers.resolve(__import__('json').load(
        open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'config.json'), encoding='utf-8')))
except Exception:
    cfg = {}
if providers.configured(cfg):
    good, m = providers.probe(cfg, timeout=25)
    print('  %s %s' % ('ok  ' if good else '跳过', m[:80]))
    if good:
        ok += 1
    else:
        print('  （当前端点不可达，不作失败）')
else:
    print('  （config.json 未配置，跳过）')

print('\n%d 通过，%d 失败 %s' % (ok, len(fail), fail if fail else ''))
sys.exit(1 if fail else 0)
