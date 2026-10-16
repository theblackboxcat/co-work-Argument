# -*- coding: utf-8 -*-
"""Jev 判定层的接入适配器（可选 · 失败开放 · 默认关）。

Jev 是**外部**判定服务（localhost:8791 → Ollama qwen2:7b），跟本系统既有的
判定（v3/judge.py、classifier.py，以及 metrics 里那几条确定性护栏）有三点不同：

  1. 它可能不在——服务没起、Ollama 没开、或者换了一台机器（便携包里就没有它）；
  2. 它的判定是概率的，不是确定性的，会随模型而变；
  3. 它跑一次要 100–400ms，这个延迟只能花在值得的地方。

所以接入必须守三条：**失败开放**（不在＝当作没有它，行为与今天完全一致）、
**可关**（默认关，关着一次 HTTP 都不发）、**可留痕**（判定只追加进日志）。

默认只"看"不改：verdict 写进 v3/logs/jev.jsonl，不动 cards、不动召回。
要让它真的拦，得在 params.json 的 jev 块里显式打开 block_*。

用法（server.py）：

    import jev_gate as _jev
    g = _jev.check_writing(body0, context=text)   # g['verdict'] ∈ 通过/小改/回炉
    if g['ok'] and g['verdict'] == '回炉' and _jev.blocking('writing'):
        ...  # 见 block_writing_action：rewrite（与既有护栏同款）或 silence

四个接口与 local-jev/jev_client.py 一一对应，返回值一律归一化成：
    {'ok': bool, 'verdict': str|None, 'detail': dict, 'ms': int, 'raw': dict, 'error': str|None}
ok=False 表示"没判成"（服务不在 / 超时 / 置信度不足），此时 verdict 是**安全默认值**
——召回=保留、续写=通过、意图=None，也就是"什么都别做"。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = os.path.join(HERE, 'params.json')
LOGDIR = os.path.join(HERE, 'logs')
LOG = os.path.join(LOGDIR, 'jev.jsonl')

DEFAULT_PATH = r'%DSH_ROOT%\local-jev'

DEFAULT_CFG = {
    'enabled': False,        # 总闸。False 时一次 HTTP 都不发：零延迟、零行为变化。
    'path': DEFAULT_PATH,    # jev_client.py 所在目录
    'mode': 'advisory',      # advisory=只记不看；block=按 block_* 决定拦不拦
    'timeout': 30,
    'block_recall': False,   # 召回：判"丢弃"的素材真的不进上下文
    'block_writing': False,  # 续写：判"回炉"时真的动 cards
    # 回炉时怎么动：rewrite＝带禁令重写一次（与 opening/verbatim 护栏同款做法）；
    # silence＝⊘ 不说话。**默认 rewrite**：沉默会打断她，而 D9 与 author_final_veto
    # 都指向"别替她把话收走"；要让外部模型闭嘴，得是她亲自选的。
    'block_writing_action': 'rewrite',
    'threshold': 0.7,
    'log': True,             # 每次判定落一条 jsonl（只追加）
    'status_ttl': 60,        # 可用性缓存秒数，别每个请求都去探一次
}

# 判定失败时的安全默认值：**一律放行**，绝不能因为外部服务不在而让她少看到东西。
SAFE = {'recall': '保留', 'writing': '通过', 'gate': '通过', 'intent': None}

_cfg_cache = {'mtime': -1, 'cfg': None}
_client_cache = {'path': None, 'mod': None, 'tried': False}
_status_cache = {'t': 0, 'ok': None}


# ---------------------------------------------------------------- 配置

def cfg():
    """读 params.json 的 jev 块，缺的用默认值补。文件改了自动重读。"""
    try:
        mtime = os.path.getmtime(PARAMS)
    except OSError:
        mtime = -1
    if _cfg_cache['cfg'] is not None and _cfg_cache['mtime'] == mtime:
        return _cfg_cache['cfg']
    c = dict(DEFAULT_CFG)
    try:
        with open(PARAMS, encoding='utf-8') as f:
            got = (json.load(f) or {}).get('jev') or {}
        if isinstance(got, dict):
            c.update(got)
    except Exception:
        pass
    _cfg_cache['mtime'] = mtime
    _cfg_cache['cfg'] = c
    return c


def enabled():
    """总闸。没开就什么都别做——这是让它"默认不存在"的唯一开关。"""
    return bool(cfg().get('enabled'))


def blocking(kind):
    """某一种拦截是否真的生效：要总闸开 + mode=block + 对应 block_* 开。"""
    c = cfg()
    if not c.get('enabled'):
        return False
    if c.get('mode') != 'block':
        return False
    return bool(c.get('block_%s' % kind))


# ---------------------------------------------------------------- 客户端

def _client():
    """惰性 import jev_client。路径可配，失败返回 None（失败开放）。"""
    c = cfg()
    path = c.get('path') or DEFAULT_PATH
    if _client_cache['mod'] is not None and _client_cache['path'] == path:
        return _client_cache['mod']
    if _client_cache['tried'] and _client_cache['path'] == path:
        return _client_cache['mod']
    mod = None
    try:
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
        import jev_client as _m  # noqa: WPS433
        mod = _m
        try:
            mod.TIMEOUT = int(c.get('timeout') or 30)
        except Exception:
            pass
    except Exception:
        mod = None
    _client_cache['path'] = path
    _client_cache['mod'] = mod
    _client_cache['tried'] = True
    return mod


def available(force=False):
    """Jev 服务在不在。结果缓存 status_ttl 秒，避免每请求一次握手。"""
    now = time.time()
    if not force and _status_cache['ok'] is not None \
            and now - _status_cache['t'] < float(cfg().get('status_ttl') or 60):
        return _status_cache['ok']
    ok = False
    m = _client()
    if m is not None:
        try:
            ok = bool(m.is_available())
        except Exception:
            ok = False
    _status_cache['t'] = now
    _status_cache['ok'] = ok
    return ok


# ---------------------------------------------------------------- 留痕

def _log(kind, payload):
    if not cfg().get('log'):
        return
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        row = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'kind': kind}
        row.update(payload)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _run(kind, fn_name, args, safe_verdict, verdict_key='verdict'):
    """统一的调用壳：任何异常都退化成 ok=False + 安全默认值。"""
    out = {'ok': False, 'verdict': safe_verdict, 'detail': {},
           'ms': 0, 'raw': None, 'error': None}
    if not enabled():
        out['error'] = 'disabled'
        return out
    m = _client()
    if m is None:
        out['error'] = 'jev_client 不可用（路径：%s）' % cfg().get('path')
        return out
    if not available():
        out['error'] = 'Jev 服务未就绪（:8791）'
        return out
    fn = getattr(m, fn_name, None)
    if fn is None:
        out['error'] = 'jev_client 没有 %s' % fn_name
        return out
    t0 = time.time()
    try:
        raw = fn(*args)
    except Exception as e:
        out['error'] = '%s: %s' % (type(e).__name__, e)
        _log(kind, out)
        return out
    out['ms'] = int((time.time() - t0) * 1000)
    out['raw'] = raw
    if isinstance(raw, dict) and raw.get('error'):
        out['error'] = raw['error']
        _log(kind, out)
        return out
    act = (raw or {}).get('action') or {} if isinstance(raw, dict) else {}
    v = act.get(verdict_key)
    if v:
        out['verdict'] = v
        out['ok'] = True
        out['detail'] = {k: act.get(k) for k in
                         ('issues', 'uncertain', 'relevant_count', 'need_recall')
                         if k in act}
    else:
        out['error'] = '返回里没有 action.%s' % verdict_key
    _log(kind, out)
    return out


# ---------------------------------------------------------------- 四个接口

def filter_recall(text, context=''):
    """召回素材过筛。返回 verdict ∈ 保留 / 降级使用 / 丢弃。"""
    return _run('recall', 'filter_recall',
                (text, context, float(cfg().get('threshold') or 0.7)),
                SAFE['recall'])


def check_writing(text, context=''):
    """续写质量校验。返回 verdict ∈ 通过 / 小改 / 回炉。"""
    return _run('writing', 'check_writing',
                (text, context, float(cfg().get('threshold') or 0.7)),
                SAFE['writing'])


def route_intent(text, context=''):
    """用户意图路由。返回 verdict=intent 字符串，detail['need_recall'] 是布尔。"""
    return _run('intent', 'route_intent', (text, context),
                SAFE['intent'], verdict_key='intent')


def quick_gate(text):
    """最快的一道门（单条判定）。返回 verdict ∈ 通过 / 需小改 / 需回炉。"""
    return _run('gate', 'quick_gate', (text,), SAFE['gate'])


def block_writing_action():
    return cfg().get('block_writing_action') or 'rewrite'
