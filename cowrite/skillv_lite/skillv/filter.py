# -*- coding: utf-8 -*-
"""Applicability filter.

Semantically nearby is not the same as currently applicable.
A candidate is dropped only when a predicate fails on observed fields.
Missing evidence stays uncertain and is not treated as a confident mismatch.
"""


def eval_node(node, episode, bounds):
    """Return 'pass', 'fail', or 'uncertain'."""
    if not node:
        return 'pass'
    if 'all' in node:
        saw_uncertain = False
        for child in node['all']:
            status = eval_node(child, episode, bounds)
            if status == 'fail':
                return 'fail'
            if status == 'uncertain':
                saw_uncertain = True
        return 'uncertain' if saw_uncertain else 'pass'
    if 'any' in node:
        saw_uncertain = False
        for child in node['any']:
            status = eval_node(child, episode, bounds)
            if status == 'pass':
                return 'pass'
            if status == 'uncertain':
                saw_uncertain = True
        return 'uncertain' if saw_uncertain else 'fail'
    return _eval_leaf(node, episode, bounds)


def _field(episode, name):
    if name not in episode:
        return None, False
    return episode.get(name), True


def _bound(bounds, node):
    key = node.get('bound')
    if not key:
        raise KeyError('predicate missing bound')
    if key not in bounds:
        raise KeyError('unknown bound %s' % key)
    return bounds[key]


def _eval_leaf(node, episode, bounds):
    op = node.get('op')
    if op == 'not_started':
        return _not_started(episode, bounds)
    if op == 'blocked_when':
        return _blocked_when(node, episode, bounds)
    if op == 'lt_bound_or_skip':
        return _lt_bound_or_skip(node, episode, bounds)
    if op == 'ge_bound_or_vacuous_zero':
        return _ge_bound_or_vacuous_zero(node, episode, bounds)

    value, present = _field(episode, node.get('field'))
    if not present or value is None:
        return 'uncertain'
    if op == 'eq':
        return 'pass' if value == node.get('value') else 'fail'
    if op == 'ne':
        return 'pass' if value != node.get('value') else 'fail'
    if op == 'le':
        return 'pass' if value <= node.get('value') else 'fail'
    if op == 'lt':
        return 'pass' if value < node.get('value') else 'fail'
    if op == 'ge':
        return 'pass' if value >= node.get('value') else 'fail'
    if op == 'gt':
        return 'pass' if value > node.get('value') else 'fail'
    if op == 'ge_bound':
        target = _bound(bounds, node)
        if target is None or value is None:
            return 'uncertain'
        return 'pass' if value >= target else 'fail'
    if op == 'le_bound':
        target = _bound(bounds, node)
        if target is None:
            return 'uncertain'
        return 'pass' if value <= target else 'fail'
    raise ValueError('unknown predicate op %r' % op)


def _not_started(episode, bounds):
    doc_lt = bounds.get('doc_chars_lt')
    cur_lt = bounds.get('cursor_lt')
    if doc_lt is None or cur_lt is None:
        return 'uncertain'
    if episode.get('has_doc_coords'):
        doc = episode.get('doc_chars')
        cur = episode.get('cursor_offset')
        if doc is None or cur is None:
            return 'uncertain'
        if doc < doc_lt and cur < cur_lt:
            return 'pass'
        return 'fail'
    # No document coordinates in the log. A long passage, or characters
    # already sitting after the cursor, is confident evidence the draft
    # has started. A short passage with nothing after it matches the
    # logged NOT_STARTED openings. Anything else stays uncertain.
    text_len = episode.get('text_len')
    if text_len is None:
        return 'uncertain'
    after = episode.get('after_chars')
    if after is None:
        return 'uncertain'
    if text_len < doc_lt and after <= 0:
        return 'pass'
    return 'fail'


def _blocked_when(node, episode, bounds):
    """If the bound flag is off the predicate passes.

    If the flag is on, the contract is inapplicable when `field == equals`.
    Used to tighten STUCK so a mid-sentence stall is no longer covered,
    without rewriting the contract's phi.
    """
    if not bounds.get(node.get('bound')):
        return 'pass'
    value, present = _field(episode, node.get('field'))
    if not present or value is None:
        return 'uncertain'
    if value == node.get('equals', True):
        return 'fail'
    return 'pass'


def _lt_bound_or_skip(node, episode, bounds):
    """Upper cap. A null cap means the contract imposes no upper bound."""
    cap = _bound(bounds, node)
    if cap is None:
        return 'pass'
    value, present = _field(episode, node.get('field'))
    if not present or value is None:
        return 'uncertain'
    return 'pass' if value < cap else 'fail'


def _ge_bound_or_vacuous_zero(node, episode, bounds):
    """Content floor. Zero means the floor is not in force."""
    floor = _bound(bounds, node)
    if floor is None or floor <= 0:
        return 'pass'
    value, present = _field(episode, node.get('field'))
    if not present or value is None:
        return 'uncertain'
    return 'pass' if value >= floor else 'fail'


def judge_contract(contract, episode, library, bounds):
    status = eval_node(contract.get('applicability') or {}, episode, bounds)
    if status == 'pass':
        return 'applicable'
    if status == 'fail':
        return 'inapplicable'
    return 'uncertain'


def rubric_status(contract, episode, bounds):
    """Executable rubric. Empty criteria do not claim the turn."""
    criteria = (contract.get('rubric') or {}).get('criteria') or []
    if not criteria:
        return 'no-criteria'
    saw_uncertain = False
    for crit in criteria:
        status = eval_node(crit, episode, bounds)
        if status == 'fail':
            return 'fail'
        if status == 'uncertain':
            saw_uncertain = True
    return 'uncertain' if saw_uncertain else 'pass'
