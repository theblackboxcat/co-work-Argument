# -*- coding: utf-8 -*-
"""Offline boundary revision with a non-regression evidence gate.

A proposal is one coordinate step on an existing bound. It is accepted
only when it strictly lowers disagreement on the proposal slice and does
not worsen disc, FNR, or balanced accuracy on the held replay buffer.
phi is never edited.
"""

from skillv.contracts import find, with_bounds
from skillv.decide import rubric_disagreements, score_episodes
from skillv.metrics import round_metrics, worse

# Order is part of the protocol: earlier accepts are visible to later ones.
COORDINATES = (
    ('stuck_speak', 'require_not_mid', (False, True)),
    ('stuck_speak', 'content_min', (0, 30, 40, 60, 80)),
    ('*shared*', 'stuck_ms', (10000, 12000, 15000, 20000, 30000, 45000)),
    ('coding_silence', 'release_after_ms', (None, 3000, 5000, 8000, 15000)),
    ('reprobe_mid_silence', 'release_after_ms', (None, 8000, 15000, 30000)),
    ('planning_speak', 'content_min', (0, 30, 40, 60)),
    ('recontext_speak', 'content_min', (0, 30, 40, 60, 80)),
    ('polishing_speak', 'content_min', (0, 40, 80)),
    ('*shared*', 'planning_ms', (1000, 1250, 1500, 2000, 3000, 5000, 8000)),
    ('*shared*', 'review_hold_ms', (4000, 8000, 12000)),
    ('*paired*', 'not_started_chars', (20, 40, 80)),
)


def _current_value(library, contract_id, name):
    if contract_id == '*shared*':
        return library['shared_bounds'][name]
    return find(library, contract_id)['bounds'][name]


def _edits_for(contract_id, name, value):
    if contract_id == '*paired*' and name == 'not_started_chars':
        return [
            ('*shared*', 'doc_chars_lt', value),
            ('*shared*', 'cursor_lt', value),
        ]
    return [(contract_id, name, value)]


def _value_now(library, contract_id, name):
    if contract_id == '*paired*' and name == 'not_started_chars':
        return library['shared_bounds']['doc_chars_lt']
    return _current_value(library, contract_id, name)


def _distance(old, new):
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return abs(new - old)
    return 0 if old == new else 1


def _rank(item):
    """Prefer a better replay, then a better proposal slice, then the smaller edit."""
    replay = item['replay']
    evolve = item['evolve']
    return (
        replay.get('disc') if replay.get('disc') is not None else 9,
        replay.get('fnr') if replay.get('fnr') is not None else 9,
        -(replay.get('bacc') or 0),
        evolve.get('disc') if evolve.get('disc') is not None else 9,
        _distance(item['from'], item['to']),
        item['index'],
    )


def evolve(library, evolve_eps, replay_eps, mode='gate'):
    """Greedy coordinate search. Returns the gated library and the log."""
    current = library
    accepted = []
    rejected = []
    considered = 0
    for contract_id, name, grid in COORDINATES:
        base_ev = score_episodes(current, evolve_eps, mode=mode)
        base_rp = score_episodes(current, replay_eps, mode=mode)
        best = None
        current_value = _value_now(current, contract_id, name)
        for index, value in enumerate(grid):
            if value == current_value:
                continue
            considered += 1
            trial = with_bounds(
                current,
                _edits_for(contract_id, name, value),
                reason='proposal %s.%s -> %r' % (contract_id, name, value),
            )
            ev = score_episodes(trial, evolve_eps, mode=mode)
            if ev.get('disc') is None or base_ev.get('disc') is None:
                rejected.append(_row(
                    contract_id, name, current_value, value, ev, None,
                    'evolve disc undefined'))
                continue
            if not (ev['disc'] < base_ev['disc'] - 1e-12):
                continue
            rp = score_episodes(trial, replay_eps, mode=mode)
            reason = worse(base_rp, rp)
            if reason:
                rejected.append(_row(
                    contract_id, name, current_value, value, ev, rp, reason))
                continue
            item = _row(contract_id, name, current_value, value, ev, rp, 'passes gate')
            item['index'] = index
            item['library'] = trial
            if best is None or _rank(item) < _rank(best):
                best = item
        if best is None:
            continue
        best.pop('index', None)
        current = best.pop('library')
        accepted.append(best)
    disagreements = rubric_disagreements(current, list(evolve_eps) + list(replay_eps))
    return {
        'library': current,
        'accepted': accepted,
        'rejected': rejected,
        'considered': considered,
        'rubric_disagreements_after': len(disagreements),
        'mode': mode,
    }


def _row(contract_id, name, old, new, evolve_m, replay_m, reason):
    return {
        'contract_id': contract_id,
        'bound': name,
        'from': old,
        'to': new,
        'evolve': round_metrics(evolve_m) if evolve_m else None,
        'replay': round_metrics(replay_m) if replay_m else None,
        'reason': reason,
    }
