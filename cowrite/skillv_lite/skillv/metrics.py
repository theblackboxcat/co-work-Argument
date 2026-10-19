# -*- coding: utf-8 -*-
"""Speak/silence disagreement metrics.

Positive class = the author wanted silence. That is the probe testkit's
polarity (precision/recall of ⊘), not a new target.

Semantic desired action, used for counterfactual replay:

- silence: should_have_silent, silent_right, silent_had_nothing
- speak:   should_have_spoken, silent_wrong

`silent_had_nothing` ("本来就没什么可说") is a correct silence on this
reading. The probe confusion table instead files it as FP, next to
"太弱". Both numbers are reported. The project table is only meaningful
for the logged action, because those labels were collected on that action.
"""

import math

DESIRED_SILENCE = ('should_have_silent', 'silent_right', 'silent_had_nothing')
DESIRED_SPEAK = ('should_have_spoken', 'silent_wrong')


def desired_silent(feedback):
    if feedback in DESIRED_SILENCE:
        return True
    if feedback in DESIRED_SPEAK:
        return False
    return None


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / float(n)
    d = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / d
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / d
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _div(num, den):
    if not den:
        return None
    return num / float(den)


def confusion(pairs):
    """pairs: iterable of (spoke: bool, desired_silent: bool)."""
    tp = fp = fn = tn = 0
    for spoke, y_silent in pairs:
        if (not spoke) and y_silent:
            tp += 1
        elif (not spoke) and (not y_silent):
            fp += 1
        elif spoke and y_silent:
            fn += 1
        else:
            tn += 1
    n = tp + fp + fn + tn
    tpr = _div(tp, tp + fn)
    tnr = _div(tn, tn + fp)
    prec = _div(tp, tp + fp)
    rec = tpr
    fnr = _div(fn, fn + tp)
    bacc = None if tpr is None or tnr is None else 0.5 * (tpr + tnr)
    disc = None if n == 0 else (fp + fn) / float(n)
    return {
        'n': n,
        'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'precision': prec,
        'recall': rec,
        'fnr': fnr,
        'bacc': bacc,
        'disc': disc,
        'precision_wilson95': wilson(tp, tp + fp),
        'recall_wilson95': wilson(tp, tp + fn),
    }


def project_logged_cells(episodes):
    """Probe CONFUSION on the action that was actually logged.

    Not a counterfactual. silent_had_nothing counts as FP here, matching
    cowrite/transplant_src/app/v3/probe.py.
    """
    tp = fp = fn = tn = 0
    unlabeled = 0
    for ep in episodes:
        kind = ep.get('kind')
        fb = ep.get('feedback')
        if kind == 'silence' and fb == 'silent_right':
            tp += 1
        elif kind == 'silence' and fb in ('silent_wrong', 'silent_had_nothing'):
            fp += 1
        elif kind == 'spoke' and fb == 'should_have_silent':
            fn += 1
        elif kind == 'spoke' and fb == 'should_have_spoken':
            tn += 1
        else:
            unlabeled += 1
    base = confusion(
        [(False, True)] * tp
        + [(False, False)] * fp
        + [(True, True)] * fn
        + [(True, False)] * tn
    )
    base['unlabeled_or_unmapped'] = unlabeled
    base['note'] = (
        'Project cells on logged actions only. '
        'silent_had_nothing is FP in this table and a desired silence '
        'in the semantic counterfactual table.'
    )
    return base


def round_metrics(m, nd=4):
    out = dict(m)
    for k in ('precision', 'recall', 'fnr', 'bacc', 'disc'):
        if isinstance(out.get(k), float):
            out[k] = round(out[k], nd)
    return out


def worse(old, new):
    """Return a reason string if `new` regresses, else None.

    Disc and FNR must not rise. Balanced accuracy must not fall.
    Coverage (n) must stay put so a metric is not improved by dropping rows.
    """
    if old.get('n') != new.get('n'):
        return 'coverage changed (%s -> %s)' % (old.get('n'), new.get('n'))
    for key in ('disc', 'fnr', 'bacc'):
        o = old.get(key)
        n = new.get(key)
        if o is None or n is None:
            if o != n:
                return '%s became undefined' % key
            continue
        if key == 'bacc':
            if n < o - 1e-12:
                return 'bacc worsened (%.4f -> %.4f)' % (o, n)
        elif n > o + 1e-12:
            return '%s worsened (%.4f -> %.4f)' % (key, o, n)
    return None
