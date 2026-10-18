# -*- coding: utf-8 -*-
"""Select one applicable contract and turn it into a speak bit.

Gate mode (the flag default) only withholds. It does not force a speak
the current policy withheld, and it does not add prompt text.
Cascade mode replaces the speak bit with the selected contract. It is an
offline ablation and an explicit SKILLV_MODE=cascade option.
"""

from skillv.contracts import find, merged_bounds
from skillv.filter import judge_contract, rubric_status
from skillv.metrics import confusion, desired_silent

# Logged attn_state -> the speak bit frozen in attention.STATES.
RULE_SPEAK = {
    'CODING': False,
    'PLANNING': True,
    'RECONTEXT': True,
    'STUCK': True,
    'POLISHING': True,
    'REVIEWING': False,
    'NOT_STARTED': False,
}

STATE_OF = {
    'not_started_silence': 'NOT_STARTED',
    'reviewing_silence': 'REVIEWING',
    'polishing_speak': 'POLISHING',
    'stuck_speak': 'STUCK',
    'coding_silence': 'CODING',
    'reprobe_mid_silence': 'CODING',
    'planning_speak': 'PLANNING',
    'recontext_speak': 'RECONTEXT',
    'residual_silence': 'CODING',
}


def cascade(library, episode):
    if episode.get('signals_missing'):
        return _decision(None, True, [], 'no attention signals in the log')
    ordered = sorted(library['contracts'], key=lambda c: c['priority'])
    trace = []
    blocking_uncertain = False
    for contract in ordered:
        bounds = merged_bounds(library, contract)
        status = judge_contract(contract, episode, library, bounds)
        trace.append({
            'id': contract['id'],
            'version': contract.get('version', 1),
            'priority': contract['priority'],
            'status': status,
            'decision': contract['decision'],
        })
        if status == 'inapplicable':
            continue
        if status == 'uncertain':
            blocking_uncertain = True
            continue
        if blocking_uncertain:
            return _decision(None, True, trace, 'higher-priority contract uncertain')
        return _decision(contract, False, trace, 'selected')
    if blocking_uncertain:
        return _decision(None, True, trace, 'only uncertain candidates')
    return _decision(None, True, trace, 'no applicable contract')


def _decision(contract, abstain, trace, why):
    if abstain or contract is None:
        return {
            'abstain': True,
            'speak': None,
            'selected': None,
            'version': None,
            'state': None,
            'why': why,
            'trace': trace,
            'dropped': [t['id'] for t in trace if t['status'] == 'inapplicable'],
            'uncertain': [t['id'] for t in trace if t['status'] == 'uncertain'],
            'applicable': [t['id'] for t in trace if t['status'] == 'applicable'],
        }
    return {
        'abstain': False,
        'speak': contract['decision'] == 'speak',
        'selected': contract['id'],
        'version': contract.get('version', 1),
        'state': STATE_OF.get(contract['id']),
        'why': why,
        'trace': trace,
        'dropped': [t['id'] for t in trace if t['status'] == 'inapplicable'],
        'uncertain': [t['id'] for t in trace if t['status'] == 'uncertain'],
        'applicable': [t['id'] for t in trace if t['status'] == 'applicable'],
    }


def apply_gate(prior_speak, decision):
    """Withhold when the contract says silence. Otherwise keep the prior bit."""
    if prior_speak is None:
        return None
    if not decision or decision.get('abstain') or decision.get('speak') is None:
        return prior_speak
    if decision.get('speak') is False:
        return False
    return prior_speak


def predict(library, episode, mode='gate'):
    decision = cascade(library, episode)
    if mode == 'cascade':
        spoke = None if decision['abstain'] else bool(decision['speak'])
    elif mode == 'gate':
        spoke = apply_gate(episode.get('spoke'), decision)
    elif mode == 'rule':
        state = episode.get('attn_state')
        spoke = RULE_SPEAK.get(state) if state in RULE_SPEAK else None
    elif mode == 'logged':
        spoke = episode.get('spoke')
    else:
        raise ValueError('unknown decision mode %r' % mode)
    return spoke, decision


def score_episodes(library, episodes, mode='gate'):
    pairs = []
    abstain = 0
    missing_label = 0
    by_id = {}
    for ep in episodes:
        y = desired_silent(ep.get('feedback'))
        if y is None:
            missing_label += 1
            continue
        spoke, decision = predict(library, ep, mode=mode)
        if spoke is None:
            abstain += 1
            continue
        pairs.append((bool(spoke), bool(y)))
        if mode in ('gate', 'cascade') and decision and decision.get('selected'):
            sid = decision['selected']
            if decision['speak'] is False and ep.get('spoke') is True and mode == 'gate':
                by_id[sid] = by_id.get(sid, 0) + 1
            if mode == 'cascade':
                by_id[sid] = by_id.get(sid, 0) + 1
    metrics = confusion(pairs)
    metrics['abstain'] = abstain
    metrics['missing_label'] = missing_label
    metrics['selected_counts'] = by_id
    metrics['mode'] = mode
    return metrics


def rubric_disagreements(library, episodes):
    """Count turns whose selected contract's rubric passes and the
    desired action disagrees with that contract's decision.

    Revisions are allowed to move bounds only. This count is the
    disagreement the revision loop is answering.
    """
    rows = []
    for ep in episodes:
        y_silent = desired_silent(ep.get('feedback'))
        if y_silent is None:
            continue
        decision = cascade(library, ep)
        if decision['abstain'] or not decision.get('selected'):
            continue
        contract = find(library, decision['selected'])
        bounds = merged_bounds(library, contract)
        status = rubric_status(contract, ep, bounds)
        if status != 'pass':
            continue
        wanted_speak = not y_silent
        if wanted_speak != decision['speak']:
            rows.append({
                'event_id': ep.get('event_id'),
                'contract': contract['id'],
                'version': contract.get('version', 1),
                'contract_speak': decision['speak'],
                'wanted_speak': wanted_speak,
                'feedback': ep.get('feedback'),
                'attn_state': ep.get('attn_state'),
            })
    return rows
