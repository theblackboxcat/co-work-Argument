# -*- coding: utf-8 -*-
"""Turn probe rows and live attention signals into episode records.

The smoke session S-20261006-231325 is a testkit fixture (reasons s0/s1,
previews a0/b0) and is excluded from the replay buffer. No dialogue is
invented here; rows come from the existing probe log or from the caller.
"""

import json

SMOKE_SESSION = 'S-20261006-231325'
SIGNAL_KEYS = (
    'pause_ms', 'at_sentence_end', 'at_paragraph_end', 'mid_sentence',
    'edits_recent', 'jumps_recent', 'chars_recent', 'moved_up',
    'after_chars', 'after_in_para', 'doc_chars', 'cursor_offset',
)


def _num(v, default=0):
    """Match attention._num: bad or missing values become `default`."""
    if v is None or v == '':
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _opt_num(sig, key):
    """Missing document coordinates stay missing.

    attention._num would turn a missing doc_chars into 0 and then label
    every such row NOT_STARTED. The packed probe signal does not store
    doc_chars, so that default is not evidence.
    """
    if key not in (sig or {}):
        return None
    v = sig.get(key)
    if v is None or v == '' or v == '—':
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _flag(sig, key):
    """attention uses bool(sig.get(key)), so a missing flag is False."""
    if not sig or sig.get(key) is None:
        return False
    return bool(sig.get(key))


def episode_from_signals(sig, mode=None, text_len=None, feedback=None,
                         kind=None, attn_state=None, text_head=None,
                         event_id=None, session=None, ts=None):
    sig = sig or {}
    pause = _num(sig.get('pause_ms'), 0)
    edits = _num(sig.get('edits_recent'), 0)
    jumps = _num(sig.get('jumps_recent'), 0)
    chars = _num(sig.get('chars_recent'), 0)
    after = _num(sig.get('after_chars'), 0)
    mid = _flag(sig, 'mid_sentence')
    at_sentence = _flag(sig, 'at_sentence_end')
    at_para = _flag(sig, 'at_paragraph_end')
    at_boundary = bool(at_sentence or at_para)
    moved_up = _flag(sig, 'moved_up')
    after_in = _flag(sig, 'after_in_para')
    if after <= 0:
        position = 'append'
    elif after_in:
        position = 'within'
    else:
        position = 'insert'
    doc = _opt_num(sig, 'doc_chars')
    cur = _opt_num(sig, 'cursor_offset')
    if text_len is None and 'text_len' in sig:
        text_len = _opt_num(sig, 'text_len')
    return {
        'event_id': event_id,
        'session': session,
        'ts': ts,
        'kind': kind,
        'spoke': True if kind == 'spoke' else (False if kind == 'silence' else None),
        'feedback': feedback,
        'attn_state': attn_state,
        'mode': mode,
        'text_len': text_len,
        'text_head': text_head or '',
        'pause_ms': pause,
        'edits_recent': edits,
        'jumps_recent': jumps,
        'chars_recent': chars,
        'after_chars': after,
        'mid_sentence': mid,
        'at_sentence_end': at_sentence,
        'at_paragraph_end': at_para,
        'at_boundary': at_boundary,
        'mid_only': bool(mid and not at_boundary),
        'moved_up': moved_up,
        'after_in_para': after_in,
        'position': position,
        'doc_chars': doc,
        'cursor_offset': cur,
        'has_doc_coords': doc is not None and cur is not None,
    }


def is_smoke(row):
    if row.get('session') == SMOKE_SESSION:
        return True
    preview = row.get('preview') or ''
    if row.get('attn_signals') is None and preview in (
            'a0', 'a1', 'b0', 'b1', 'b2', 'b3'):
        return True
    return False


def from_probe_row(row):
    # A null signal pack is not a vector of zeros. attention._num would
    # treat it as NOT_STARTED; that is not what the logger recorded.
    raw_sig = row.get('attn_signals')
    sig = raw_sig or {}
    # text_len is a property of the logged passage, not of the signal pack.
    text_len = row.get('text_len')
    if isinstance(text_len, str):
        try:
            text_len = int(text_len)
        except ValueError:
            text_len = None
    ep = episode_from_signals(
        sig,
        mode=row.get('mode'),
        text_len=text_len,
        feedback=row.get('author_feedback'),
        kind=row.get('kind'),
        attn_state=row.get('attn_state'),
        text_head=row.get('text_head') or '',
        event_id=row.get('event_id'),
        session=row.get('session'),
        ts=row.get('ts'),
    )
    ep['smoke'] = is_smoke(row)
    ep['signals_missing'] = not raw_sig
    ep['mode_score'] = row.get('mode_score')
    return ep


def load_probe(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    episodes = []
    skipped_kind = 0
    skipped_label = 0
    for row in rows:
        if row.get('kind') not in ('spoke', 'silence'):
            skipped_kind += 1
            continue
        if not row.get('author_feedback'):
            skipped_label += 1
            continue
        episodes.append(from_probe_row(row))
    return {
        'episodes': episodes,
        'skipped_kind': skipped_kind,
        'skipped_unlabeled': skipped_label,
        'source': path,
    }


def _sig_token(ep):
    return tuple(ep.get(k) for k in (
        'pause_ms', 'at_sentence_end', 'at_paragraph_end', 'mid_sentence',
        'edits_recent', 'jumps_recent', 'chars_recent', 'moved_up',
        'after_chars', 'after_in_para', 'doc_chars', 'cursor_offset',
        'text_len', 'position'))


def dedupe_key(ep):
    head = (ep.get('text_head') or '')[:48]
    return (
        ep.get('feedback'),
        ep.get('attn_state'),
        ep.get('kind'),
        head,
        _sig_token(ep),
    )


def dedupe(episodes):
    """Keep the first copy of a double-fired probe row."""
    seen = set()
    out = []
    dropped = 0
    for ep in episodes:
        key = dedupe_key(ep)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append(ep)
    return out, dropped


def split_replay(episodes):
    """Earlier labeled session is the proposal source.

    The 2026-10-09 session is the held replay buffer. The gate may not
    accept a revision that regresses on that buffer.
    """
    evolve, replay = [], []
    for ep in episodes:
        sid = ep.get('session') or ''
        ts = ep.get('ts') or ''
        if '20261009' in sid or ts.startswith('2026-10-09'):
            replay.append(ep)
        else:
            evolve.append(ep)
    return evolve, replay
