# -*- coding: utf-8 -*-
"""Live dots3 eval of Skill-V-lite speak/silence.

For each arm, decide speak or silence. Call dots3 only when the arm says
speak. Silence does not open a socket. Arms share one cache: the same
prompt is sent once, and a later arm reuses that reply.

This is the speak/silence path plus the model call. It is not a co-address
result. Content-quality labels (接受/太弱/太强/不对) are reported only when
a probe row already carries them. They are not invented.

    python3 eval_live_dots3.py --slice replay --max-calls 12

The key is read the way server.py already reads it (config.json / env).
It is never written into the report. If the endpoint cannot be reached,
the report records the URL and the error and the process exits non-zero.
No latency and no model text are filled in after a failed preflight.

Cloud VMs time out on http://note3-prev-api.askdiandian.com. Run this on
the author's laptop (LAPTOP-32CD28QL), which can reach that host.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from skillv.contracts import load  # noqa: E402
from skillv.decide import RULE_SPEAK, predict  # noqa: E402
from skillv.episodes import dedupe, load_probe, split_replay  # noqa: E402
from skillv.metrics import desired_silent  # noqa: E402

DEFAULT_PROBE = os.path.abspath(os.path.join(
    HERE, '..', 'Cowrite-test', 'app', 'v3', 'logs', 'probe.jsonl'))
DEFAULT_BASE = 'http://note3-prev-api.askdiandian.com'
DEFAULT_MODEL = 'dots3-note-prev'
# One shared budget for the whole run, not per arm. The held replay has
# 13 episodes; 12 leaves the eval real and bounded. The laptop run used
# this budget and recorded 12/12 unique calls.
DEFAULT_MAX_CALLS = 12
DEFAULT_MAX_TOKENS = 256

ARMS = (
    ('rule', 'attention rule (甲)'),
    ('logged', 'logged (丙)'),
    ('seed_gate', 'Skill-V seed gate'),
    ('revised_gate', 'Skill-V revised gate'),
)

CONTENT_LABELS = ('接受', '太弱', '太强', '不对')


def _app_dirs():
    return [
        os.path.abspath(os.path.join(HERE, '..', 'Cowrite-test', 'app')),
        os.path.abspath(os.path.join(HERE, '..', 'transplant_src', 'app')),
    ]


def _is_dots3(cfg):
    if not cfg:
        return False
    provider = (cfg.get('provider') or '').strip().lower()
    base = cfg.get('base_url') or ''
    model = cfg.get('model') or ''
    if provider == 'dots3':
        return True
    if 'note3-prev-api' in base or '<API_HOST>' in base:
        return True
    if str(model).startswith('dots3'):
        return True
    return False


def _read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def resolve_config(env=None):
    """Build a dots3 config. Never returns a key that belongs to another host.

    Order: COWRITE_CONFIG, then config.json beside either cowrite app, then
    DOTS3_API_KEY / DOTS3_BASE_URL / DOTS3_MODEL. A DeepSeek config.json is
    ignored so its key is not sent to dots3.
    """
    env = os.environ if env is None else env
    cfg = {}
    source = ''
    explicit = (env.get('COWRITE_CONFIG') or '').strip()
    candidates = [explicit] if explicit else []
    if not explicit:
        candidates = [os.path.join(app, 'config.json') for app in _app_dirs()]
    for path in candidates:
        if path and os.path.isfile(path):
            loaded = _read_json(path)
            if explicit or _is_dots3(loaded):
                cfg = loaded
                source = path
                break
    if not _is_dots3(cfg) and not explicit:
        cfg = {}
        source = ''
    base = (env.get('DOTS3_BASE_URL') or cfg.get('base_url') or '').strip()
    if (not base) or ('<API_HOST>' in base):
        base = DEFAULT_BASE
    model = (env.get('DOTS3_MODEL') or cfg.get('model') or DEFAULT_MODEL).strip()
    key = (env.get('DOTS3_API_KEY') or '').strip()
    if not key and _is_dots3(cfg):
        key = (cfg.get('api_key') or '').strip()
    out = {
        'provider': 'dots3',
        'api': 'anthropic-messages',
        'base_url': base.rstrip('/'),
        'model': model or DEFAULT_MODEL,
        'api_key': key,
        'config_source': source,
    }
    return out


def endpoint_url(cfg):
    return (cfg.get('base_url') or DEFAULT_BASE).rstrip('/') + '/v1/messages'


def redact(text, cfg):
    text = '' if text is None else str(text)
    key = (cfg or {}).get('api_key') or ''
    if key and key in text:
        text = text.replace(key, '[redacted]')
    return text


def load_slice(path, which):
    """Same episodes as eval_ab: drop smoke, drop duplicate fires, then slice."""
    loaded = load_probe(path)
    real = [ep for ep in loaded['episodes'] if not ep.get('smoke')]
    deduped, dropped = dedupe(real)
    proposal, replay = split_replay(deduped)
    which = (which or 'replay').strip().lower()
    if which == 'replay':
        episodes = replay
    elif which == 'proposal':
        episodes = proposal
    elif which in ('all', 'deduped'):
        episodes = deduped
    else:
        raise SystemExit('unknown --slice %r (replay, proposal, all)' % which)
    return {
        'episodes': episodes,
        'slice': which,
        'probe': path,
        'labeled': len(loaded['episodes']),
        'smoke': sum(1 for ep in loaded['episodes'] if ep.get('smoke')),
        'duplicates_dropped': dropped,
        'deduped': len(deduped),
        'proposal_n': len(proposal),
        'replay_n': len(replay),
    }


def libraries():
    seed = load()
    revised_path = os.path.join(HERE, 'results', 'revised_library.json')
    revised = load(revised_path)
    return seed, revised


def decide_arm(arm, episode, seed, revised):
    """Return (speak bit or None for abstain, detail).

    seed_gate and revised_gate use the offline gate: the logged speak bit
    is the prior, and a silence contract can withhold it. A speak contract
    does not force a logged silence. When the cascade abstains, the prior
    is kept, so the bit is silence or speak, not a third abstain. The rule
    arm abstains when the log has no attention state.
    """
    if arm == 'rule':
        state = episode.get('attn_state')
        if state not in RULE_SPEAK:
            return None, {'why': 'no logged attention state'}
        return bool(RULE_SPEAK[state]), {
            'why': 'frozen attention speak bit',
            'state': state,
        }
    if arm == 'logged':
        spoke = episode.get('spoke')
        if spoke is None:
            return None, {'why': 'kind was neither spoke nor silence'}
        return bool(spoke), {'why': 'logged action'}
    if arm not in ('seed_gate', 'revised_gate'):
        raise ValueError('unknown arm %r' % arm)
    lib = seed if arm == 'seed_gate' else revised
    spoke, decision = predict(lib, episode, mode='gate')
    return spoke, {
        'why': 'gate withholds only; prior is the logged speak bit',
        'selected': (decision or {}).get('selected'),
        'cascade_abstain': bool((decision or {}).get('abstain')),
        'cascade_speak': (decision or {}).get('speak'),
    }


def content_labels(episode):
    found = []
    for key in ('content_label', 'quality', 'author_quality'):
        val = episode.get(key)
        if val in CONTENT_LABELS:
            found.append(val)
    return found


def _bit_name(bit):
    if bit is None:
        return 'abstain'
    return 'speak' if bit else 'silence'


def _policy():
    """Lazy import of v3 policy. None if the skill file cannot be loaded."""
    for app in _app_dirs():
        v3 = os.path.join(app, 'v3')
        skill = os.path.join(v3, 'SKILL_v3.md')
        if not os.path.isfile(skill):
            continue
        if v3 not in sys.path:
            sys.path.insert(0, v3)
        try:
            import policy  # noqa: WPS433
        except Exception:
            continue
        return policy
    return None


def build_prompt(episode, policy=None):
    """Same prompt for every arm, so the cache can be shared.

    delegate stays false: the arm already decided to speak, and the model
    is not asked to re-answer [说]/[不说].
    """
    text = (episode.get('text_head') or '').strip()
    if not text:
        text = '（探针没有留下这一拍的正文）'
    facts = []
    if episode.get('attn_state'):
        facts.append('记录里的注意力状态=%s' % episode['attn_state'])
    if episode.get('pause_ms') is not None:
        facts.append('停顿 %d ms' % int(episode['pause_ms']))
    if episode.get('mode') in ('P', 'M', 'S'):
        facts.append('作者选定的模式=%s' % episode['mode'])
    fact_line = '；'.join(facts)
    pol = policy if policy is not None else _policy()
    if pol is not None:
        mode = episode.get('mode') if episode.get('mode') in ('P', 'M', 'S') else None
        try:
            system, _meta = pol.build_system(text, mode=mode, delegate=False)
            user = pol.build_user(
                text, facts=fact_line, anchor=text, delegate=False)
            return system, user, 'policy.build_system/build_user delegate=false'
        except Exception as exc:
            fallback_why = 'policy import failed: %s' % exc
    else:
        fallback_why = 'policy module not loaded'
    system = '你是伴写。只针对作者刚停下的这段说话。不要续写她的正文。'
    user = '【作者刚刚停下的段落】\n%s' % text
    if fact_line:
        user += '\n\n【她此刻的状态：这些是事实，不是结论】\n' + fact_line
    return system, user, fallback_why


def prompt_key(model, system, user):
    raw = json.dumps([model or '', system or '', user or ''], ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _blank():
    return {
        'n': 0, 'speak': 0, 'silence': 0, 'abstain': 0,
        'called': 0, 'ok': 0, 'fail': 0, 'skipped_cap': 0,
        'agree': 0, 'scored': 0, 'content_labels': 0,
        'latencies': [],
    }


def _finalize(row):
    n = row['n']
    lats = row.pop('latencies')
    speak_rate = None if not n else round(row['speak'] / float(n), 3)
    withhold_rate = None if not n else round(
        (row['silence'] + row['abstain']) / float(n), 3)
    agree = '—' if not row['scored'] else '%d/%d' % (row['agree'], row['scored'])
    mean = None
    if lats:
        mean = round(sum(lats) / float(len(lats)), 1)
    row.update({
        'speak_rate': speak_rate,
        'withhold_rate': withhold_rate,
        'label_agree': agree,
        'label_agree_hits': row['agree'],
        'label_agree_scored': row['scored'],
        'lat_ms_mean': mean,
        'lat_ms_min': round(min(lats), 1) if lats else None,
        'lat_ms_max': round(max(lats), 1) if lats else None,
        'dots3_ok': row['ok'],
        'dots3_fail': row['fail'],
    })
    return row


def run_arms(episodes, seed, revised, caller, max_calls, model,
             max_tokens, temperature, thinking, timeout, policy=None):
    """Walk arms in ARMS order. Shared cache. Silence never calls.

    `caller(system, user)` returns a dict with ok, text, error, latency_ms,
    stop. Tests inject this. The real caller is dots3 via providers.chat.
    """
    cache = {}
    unique = 0
    calls = []
    per = {arm: _blank() for arm, _name in ARMS}
    decisions = []
    prompt_note = ''
    for arm, _name in ARMS:
        for ep in episodes:
            bit, detail = decide_arm(arm, ep, seed, revised)
            bucket = per[arm]
            bucket['n'] += 1
            name = _bit_name(bit)
            bucket[name] += 1
            labels = content_labels(ep)
            bucket['content_labels'] += len(labels)
            y = desired_silent(ep.get('feedback'))
            agreed = None
            if bit is not None and y is not None:
                bucket['scored'] += 1
                agreed = (not bool(bit)) == bool(y)
                if agreed:
                    bucket['agree'] += 1
            row = {
                'event_id': ep.get('event_id'),
                'arm': arm,
                'decision': name,
                'label_agree': agreed,
                'feedback': ep.get('feedback'),
                'called': False,
                'cache': '',
                'ok': None,
            }
            if bit is not True:
                decisions.append(row)
                continue
            system, user, prompt_note = build_prompt(ep, policy=policy)
            key = prompt_key(model, system, user)
            if key in cache:
                cached = cache[key]
                row.update({
                    'called': True,
                    'cache': 'hit',
                    'ok': cached.get('ok'),
                    'latency_ms': cached.get('latency_ms'),
                    'stop': cached.get('stop') or '',
                    'error': cached.get('error') or '',
                    'preview': cached.get('preview') or '',
                })
                bucket['called'] += 1
                if cached.get('ok'):
                    bucket['ok'] += 1
                    if cached.get('latency_ms') is not None:
                        bucket['latencies'].append(cached['latency_ms'])
                else:
                    bucket['fail'] += 1
                decisions.append(row)
                continue
            if unique >= max_calls:
                row.update({'called': False, 'cache': 'cap', 'ok': None})
                bucket['skipped_cap'] += 1
                decisions.append(row)
                continue
            result = caller(system, user)
            unique += 1
            preview = (result.get('text') or '').replace('\n', ' ')[:80]
            stored = {
                'ok': bool(result.get('ok')),
                'latency_ms': result.get('latency_ms'),
                'stop': result.get('stop') or '',
                'error': result.get('error') or '',
                'preview': preview,
            }
            cache[key] = stored
            call_row = {
                'event_id': ep.get('event_id'),
                'arm': arm,
                'ok': stored['ok'],
                'latency_ms': stored['latency_ms'],
                'stop': stored['stop'],
                'error': stored['error'],
                'preview': preview,
                'chars': len(result.get('text') or ''),
            }
            calls.append(call_row)
            row.update({
                'called': True,
                'cache': 'miss',
                'ok': stored['ok'],
                'latency_ms': stored['latency_ms'],
                'stop': stored['stop'],
                'error': stored['error'],
                'preview': preview,
            })
            bucket['called'] += 1
            if stored['ok']:
                bucket['ok'] += 1
                if stored['latency_ms'] is not None:
                    bucket['latencies'].append(stored['latency_ms'])
            else:
                bucket['fail'] += 1
            decisions.append(row)
    arms = []
    for arm, name in ARMS:
        item = _finalize(per[arm])
        item['id'] = arm
        item['name'] = name
        arms.append(item)
    return {
        'arms': arms,
        'calls': calls,
        'decisions': decisions,
        'unique_calls': unique,
        'max_calls': max_calls,
        'prompt': prompt_note,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'thinking': thinking,
        'timeout_sec': timeout,
    }


def make_caller(cfg, timeout, max_tokens, temperature, thinking):
    """providers.chat, the same Anthropic /v1/messages path server.py uses."""
    app = _app_dirs()[0]
    for candidate in _app_dirs():
        if os.path.isfile(os.path.join(candidate, 'providers.py')):
            app = candidate
            break
    if app not in sys.path:
        sys.path.insert(0, app)
    import providers  # noqa: WPS433

    def caller(system, user):
        t0 = time.perf_counter()
        try:
            text = providers.chat(
                cfg, system, user,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                thinking=thinking)
            stop = (providers.last_stop() or {}).get('reason') or ''
            return {
                'ok': True,
                'text': text or '',
                'error': '',
                'latency_ms': round((time.perf_counter() - t0) * 1000.0, 1),
                'stop': stop,
            }
        except providers.EmptyReplyError as exc:
            return {
                'ok': True,
                'text': '',
                'error': redact(exc, cfg),
                'latency_ms': round((time.perf_counter() - t0) * 1000.0, 1),
                'stop': (providers.last_stop() or {}).get('reason') or '',
            }
        except Exception as exc:
            return {
                'ok': False,
                'text': '',
                'error': redact('%s: %s' % (type(exc).__name__, exc), cfg),
                'latency_ms': round((time.perf_counter() - t0) * 1000.0, 1),
                'stop': '',
            }

    return caller


def preflight(cfg, timeout):
    """One real POST to /v1/messages.

    providers.chat raises before dialing when the key is empty. This POST
    still goes out, so a timeout is distinguishable from a missing key.
    """
    url = endpoint_url(cfg)
    payload = {
        'model': cfg.get('model') or DEFAULT_MODEL,
        'messages': [{'role': 'user', 'content': '只回复两个字：正常'}],
        'system': '你是连通性测试。',
        'max_tokens': 16,
        'temperature': 0,
        'thinking': {'type': 'disabled'},
    }
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': cfg.get('api_key') or '',
        'anthropic-version': '2023-06-01',
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'replace')
        elapsed = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            'ok': True,
            'url': url,
            'latency_ms': elapsed,
            'error': '',
            'error_type': '',
            'status': 'ok',
            'body_preview': redact(raw[:120], cfg),
        }
    except urllib.error.HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode('utf-8', 'replace')[:300]
        except Exception:
            body = ''
        elapsed = round((time.perf_counter() - t0) * 1000.0, 1)
        message = 'HTTP %s: %s' % (exc.code, body or exc.reason)
        status = 'auth' if exc.code in (401, 403) else 'http_error'
        return {
            'ok': False,
            'url': url,
            'latency_ms': elapsed,
            'error': redact(message, cfg),
            'error_type': 'HTTPError',
            'status': status,
        }
    except Exception as exc:
        message = '%s: %s' % (type(exc).__name__, exc)
        timed_out = isinstance(exc, TimeoutError) or 'timed out' in message.lower()
        return {
            'ok': False,
            'url': url,
            'latency_ms': None,
            'error': redact(message, cfg),
            'error_type': type(exc).__name__,
            'status': 'unreachable' if timed_out else 'error',
        }


def _fmt_rate(value):
    if value is None:
        return '—'
    return '%.3f' % value


def _fmt_lat(value, approx=False):
    if value is None:
        return '—'
    text = '%d' % int(round(value)) if abs(value - round(value)) < 0.05 else '%.1f' % value
    return '~%s' % text if approx else text


def render_markdown(report):
    lines = []
    lines.append('# Skill-V-lite live dots3')
    lines.append('')
    lines.append('Speak/silence decision, then a dots3 call only when the arm says speak.')
    lines.append('This is not a co-address result. No 知音 metric is computed here.')
    lines.append('')
    prov = report.get('provenance') or {}
    lines.append('## Run')
    lines.append('')
    lines.append('- Status: `%s`' % report.get('status'))
    lines.append('- Slice: `%s` (n=%s)' % (
        report.get('slice'), (report.get('sample') or {}).get('n')))
    lines.append('- Model: `%s`' % report.get('model'))
    lines.append('- Endpoint: `%s`' % report.get('endpoint'))
    if prov.get('host'):
        lines.append('- Host: `%s`' % prov['host'])
    if prov.get('source'):
        lines.append('- Source: %s' % prov['source'])
    conn = report.get('connectivity') or {}
    if conn:
        if conn.get('ok'):
            lines.append('- Connectivity: ok, latency %s ms' % _fmt_lat(
                conn.get('latency_ms'), conn.get('approx')))
        else:
            lines.append('- Connectivity: failed')
            lines.append('- Error type: `%s`' % (conn.get('error_type') or ''))
            lines.append('- Error: `%s`' % (conn.get('error') or ''))
    cap = report.get('cap') or {}
    if cap:
        lines.append('- Call cap: %s unique calls / budget %s. %s' % (
            cap.get('unique_calls'), cap.get('max_calls'), cap.get('note') or ''))
    lines.append('- Key written: no. `key_present=%s`.' % report.get('key_present'))
    lines.append('')
    if report.get('status') != 'ok':
        lines.append('No model scores are filled in. A failed preflight is not a result.')
        lines.append('')
    if report.get('note'):
        lines.append(report['note'])
        lines.append('')
    arms = report.get('arms') or []
    if arms:
        lines.append('## Arms')
        lines.append('')
        lines.append('| arm | n | speak | silence | abstain | called | ok | fail | speak_rate | label_agree | lat_ms_mean |')
        lines.append('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
        for arm in arms:
            lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
                arm.get('name'), arm.get('n'), arm.get('speak'), arm.get('silence'),
                arm.get('abstain'), arm.get('called'), arm.get('ok'), arm.get('fail'),
                _fmt_rate(arm.get('speak_rate')), arm.get('label_agree'),
                _fmt_lat(arm.get('lat_ms_mean'), arm.get('lat_ms_mean_approx'))))
        lines.append('')
        lines.append('`label_agree` is the arm bit versus the author speak/silence feedback already on the row. Abstain is not scored. `called` counts speak turns that received a reply, including a shared-cache hit. `fail` is a transport or API error. A speak left unsent because the budget was full is not a failure.')
        lines.append('')
        labels = report.get('content_labels_present')
        lines.append('Content-quality labels already on these turns (接受/太弱/太强/不对): %s.'
                     % labels)
        lines.append('')
    if report.get('what_this_is'):
        lines.append(report['what_this_is'])
        lines.append('')
    return '\n'.join(lines)


def write_report(out_dir, report):
    os.makedirs(out_dir, exist_ok=True)
    # Belt: a key must not land in either file.
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    md_path = os.path.join(out_dir, 'live_dots3_report.md')
    json_path = os.path.join(out_dir, 'live_dots3_report.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(blob)
        f.write('\n')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(render_markdown(report))
    return md_path, json_path


def _sampling(max_tokens):
    temperature = 0.3
    thinking = 'disabled'
    tokens = DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
    pol = _policy()
    if pol is not None:
        try:
            samp = pol.sampling()
            temperature = float(samp.get('temperature', 0.3))
            thinking = samp.get('thinking', 'disabled') or 'disabled'
            if tokens == 0:
                tokens = int(samp.get('max_tokens', 2048))
        except Exception:
            if tokens == 0:
                tokens = 2048
    elif tokens == 0:
        tokens = 2048
    return temperature, thinking, tokens


def main(argv=None, caller=None, preflight_fn=None, cfg=None):
    parser = argparse.ArgumentParser(description='Skill-V-lite live dots3 eval')
    parser.add_argument('--probe', default=DEFAULT_PROBE)
    parser.add_argument('--out', default=os.path.join(HERE, 'results'))
    parser.add_argument('--slice', default='replay',
                        help='replay (held 2026-10-09), proposal, or all')
    parser.add_argument('--max-calls', type=int, default=DEFAULT_MAX_CALLS,
                        help='shared unique dots3 calls across arms (default 12)')
    parser.add_argument('--timeout', type=int, default=120,
                        help='per-call timeout in seconds')
    parser.add_argument('--probe-timeout', type=int, default=20,
                        help='connectivity preflight timeout in seconds')
    parser.add_argument('--max-tokens', type=int, default=DEFAULT_MAX_TOKENS,
                        help='output cap. 0 uses v3 params.json (2048)')
    args = parser.parse_args(argv)

    sample = load_slice(args.probe, args.slice)
    cfg = resolve_config() if cfg is None else cfg
    temperature, thinking, max_tokens = _sampling(args.max_tokens)
    seed, revised = libraries()
    check = preflight if preflight_fn is None else preflight_fn
    conn = check(cfg, args.probe_timeout)
    base = {
        'slice': sample['slice'],
        'model': cfg.get('model') or DEFAULT_MODEL,
        'endpoint': conn.get('url') or endpoint_url(cfg),
        'key_present': bool(cfg.get('api_key')),
        'config_source': cfg.get('config_source') or '',
        'sample': {
            'n': len(sample['episodes']),
            'labeled': sample['labeled'],
            'smoke': sample['smoke'],
            'duplicates_dropped': sample['duplicates_dropped'],
            'deduped': sample['deduped'],
            'proposal_n': sample['proposal_n'],
            'replay_n': sample['replay_n'],
            'probe': sample['probe'],
        },
        'cap': {
            'max_calls': args.max_calls,
            'unique_calls': 0,
            'note': ('Shared across arms. One HTTP call per distinct prompt. '
                     'Silence does not call. A speak past the budget is skipped, not failed.'),
        },
        'content_labels_present': 0,
        'what_this_is': (
            'Speak/silence plus the dots3 call path. Not co-address. '
            'label_agree uses author_feedback already stored on the probe row '
            '(should_have_silent, should_have_spoken, silent_right, silent_wrong, '
            'silent_had_nothing). 接受/太弱/太强/不对 are a different question and '
            'are counted only when a row already has one.'
        ),
        'calls': [],
    }
    if not conn.get('ok'):
        status = conn.get('status') or 'error'
        if status not in ('unreachable', 'auth', 'no_key', 'http_error'):
            status = 'error'
        if not cfg.get('api_key') and status == 'auth':
            status = 'no_key'
        report = dict(base)
        report.update({
            'status': status,
            'connectivity': {
                'ok': False,
                'latency_ms': conn.get('latency_ms'),
                'error': conn.get('error') or '',
                'error_type': conn.get('error_type') or '',
                'approx': False,
            },
            'arms': [],
            'dots3_ok': None,
            'dots3_fail': None,
            'note': ('Preflight failed. No speak turn was sent and no score was invented. '
                     'On LAPTOP-32CD28QL, put the key where server.py loads it '
                     '(Cowrite-test/app/config.json, or COWRITE_CONFIG, or DOTS3_API_KEY) '
                     'and run: python3 eval_live_dots3.py --slice replay --max-calls %d'
                     % args.max_calls),
        })
        md_path, json_path = write_report(args.out, report)
        print(render_markdown(report))
        print('wrote %s' % md_path)
        print('wrote %s' % json_path)
        return 2

    live_caller = caller if caller is not None else make_caller(
        cfg, args.timeout, max_tokens, temperature, thinking)
    ran = run_arms(
        sample['episodes'], seed, revised, live_caller, args.max_calls,
        cfg.get('model') or DEFAULT_MODEL, max_tokens, temperature, thinking,
        args.timeout)
    fails = sum(arm['fail'] for arm in ran['arms'])
    oks = sum(arm['ok'] for arm in ran['arms'])
    report = dict(base)
    report.update({
        'status': 'ok' if fails == 0 else 'partial',
        'connectivity': {
            'ok': True,
            'latency_ms': conn.get('latency_ms'),
            'error': '',
            'error_type': '',
            'approx': False,
        },
        'arms': ran['arms'],
        'calls': ran['calls'],
        'decisions': ran['decisions'],
        'prompt': ran['prompt'],
        'max_tokens': ran['max_tokens'],
        'temperature': ran['temperature'],
        'thinking': ran['thinking'],
        'dots3_ok': oks,
        'dots3_fail': fails,
        'content_labels_present': sum(a['content_labels'] for a in ran['arms']),
    })
    report['cap']['unique_calls'] = ran['unique_calls']
    md_path, json_path = write_report(args.out, report)
    print(render_markdown(report))
    print('wrote %s' % md_path)
    print('wrote %s' % json_path)
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
