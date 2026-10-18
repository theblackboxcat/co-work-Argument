# -*- coding: utf-8 -*-
"""Experiments that ask whether Skill-V-lite actually strengthens cowrite.

E1 is a live-expansion hook for the laptop. It does not invent dots3 scores.
E2–E5 run offline on the same probe log as eval_ab.py.

The success bar is the string PREREG below. It is written into
results/exp_matrix.md before the measured table. Do not edit it to fit a run.

phi is locked. A failed bar writes results/principle_revision_proposal.md
and does not change a contract.

    python3 eval_exp_suite.py
    python3 eval_exp_suite.py --live --only e1
"""

import argparse
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from skillv.contracts import load, snapshot_phi, with_bounds  # noqa: E402
from skillv.decide import score_episodes  # noqa: E402
from skillv.episodes import dedupe, load_probe  # noqa: E402
from skillv.evolve import evolve  # noqa: E402
from skillv.metrics import desired_silent, round_metrics, worse  # noqa: E402

import eval_live_dots3 as live  # noqa: E402

DEFAULT_PROBE = live.DEFAULT_PROBE
SCORE_SEED = 20261018
REFIT_SEED = 20261019
N_SCORE_PERMS = 200
N_REFIT_PERMS = 100
HELD_MIN = 8
PROPOSAL_MIN = 5
INNER_MIN = 4
AUTOPSY_MIN = 3

# Frozen before the run that fills results/exp_matrix.md. Do not retune.
PREREG = """
## Preregistered success bar

Frozen with the harness. A later run may fill the results. It may not move these sentences.

This is a speak/silence check. It is not a co-address result. phi stays locked. A failed bar proposes a principle change in `principle_revision_proposal.md` and does not edit a contract.

### E1 — live expand (laptop)

Not scored in the offline run. Status stays `pending_laptop` until a laptop report is attached.

The expansion calls dots3 only on deduped turns where the four arms disagree (attention rule, logged, seed gate, revised gate), cap `--max-calls 16` unique prompts, Anthropic `/v1/messages`, thinking disabled. Silence does not call. Same key path as `eval_live_dots3.py`. No invented scores if the preflight fails.

Pass, once the laptop file exists: on that disagreement set, revised-gate `label_agree` hits/scored is at least the logged arm's, and both scored counts are at least 8. Otherwise the live expand fails. Fewer than 8 scored turns is inconclusive, not a pass.

### E2 — leave one session out

Smoke rows excluded, double-fires dropped. For each remaining session, fit on the other sessions only. Split that train by timestamp, first 60% proposal and the rest the inner replay (at least one episode on each side). Evolve the seed library there. Score the untouched held-out session with the logged action, the seed gate, and that fold's revised gate.

A fold counts only if the held-out n is at least 8, the proposal n at least 5, and the inner replay n at least 4.

A fold regresses if `worse(logged, revised)` or `worse(seed, revised)` is set (disc or FNR up, balanced accuracy down, or coverage changed). A fold strengthens if it does not regress, revised disc is strictly below logged disc, and revised disc is less than or equal to seed disc.

E2 passes if no countable fold regresses and at least one strengthens. E2 fails the system if any countable fold regresses. Otherwise E2 is inconclusive.

### E3 — ablation of the two accepted edits

Libraries, gate mode, held replay = the 2026-10-09 session (the same split as `eval_ab.py`):

- seed (neither edit)
- `require_not_mid` only (false → true)
- `planning_ms` only (2000 → 1250)
- both, in that historical order

E3 passes if on the held replay `worse(seed, both)` is empty and both disc is less than or equal to seed disc. E3 fails the system if `both` or `require_not_mid` alone regresses versus seed on that replay. `planning_ms` alone versus seed is reported. It is a warning if it regresses, not a system failure, because that edit was not accepted against the seed by itself. A component is load-bearing when removing it strictly raises held disc.

### E4 — label-shuffle null

Permute `author_feedback` on the deduped non-smoke rows. Episode signals stay put.

E4a: 200 permutations, RNG seed 20261018. Score the frozen seed library and the shipped revised library. One-sided p = (1 + count of null discs less than or equal to the real disc) / (1 + 200). Lower disc is better. E4a passes if the revised library's pooled p is below 0.05.

E4b: 100 refits, RNG seed 20261019. Same session split as `eval_ab.py` (proposal before 2026-10-09, replay that day). Count accepted edits. E4b fails the system if the real accepted count is less than or equal to the median of the null accepted counts.

E4 passes if E4a passes and E4b does not fail. E4 fails the system if E4a fails or E4b fails.

### E5 — withhold autopsy

On the deduped non-smoke rows, W is the set where the revised gate says silence and the attention rule says speak or the log spoke. Compare the share of those rows whose author wanted silence (`should_have_silent`, `silent_right`, `silent_had_nothing`) with the same share among rows the rule would speak or the log spoke.

E5 passes if W has at least 3 rows, the wanted-silence rate in W is at least 0.5, and that rate is strictly above the base rate. E5 fails the system if W has at least 3 rows and the rate is below 0.5. Fewer than 3 rows is inconclusive.

### Suite

The offline suite fails the system if any of E2, E3, E4, E5 fails the system. It passes if all four pass. A mix of passes and inconclusives, with no system failure, is mixed. E1 does not change that offline verdict. Only a system failure writes the principle proposal. phi is not edited in any of these cases.
""".strip()


PROPOSAL_TEXT = {
    'E2': (
        'A library fit on one session moved a session that never entered the '
        'evidence gate in the wrong direction (disagreement, false-negative '
        'rate, or balanced accuracy). Principle: a bound move is not a skill '
        'until it is non-regressive on a session the gate did not see. '
        'Proposed change: keep `revised_library.json` as an exploratory '
        'artifact and do not treat it as the skill to ship. Further bound '
        'search waits for a third labeled session. Existing phi stays locked. '
        'No contract is added here.'
    ),
    'E3': (
        'The shipped pair, or the first accepted edit on its own, regresses '
        'versus the seed library on the held replay. Principle: a sequential '
        'accept is not self-validating. An edit that does not survive '
        'ablation does not belong in the skill. Proposed change: revert the '
        'regressing edit only after an executor accepts this proposal. This '
        'file does not change the library. Phi stays locked.'
    ),
    'E4': (
        'The revised library is not distinguishable from shuffled labels, or '
        'the evidence gate accepts at least as many coordinate steps on '
        'shuffled labels as on the real ones. Principle: a disc drop on this '
        'probe is not yet evidence that the contracts track the author\'s '
        'silence. Proposed change: stop the bound search. The next change is '
        'the acceptance rule — a strict drop on the replay buffer, and at '
        'least two sessions outside the proposal slice — not a rewrite of phi.'
    ),
    'E5': (
        'Turns the revised gate silences, which the rule or the log would '
        'have spoken, are mostly turns the author wanted spoken. Principle: '
        'a silence contract is withholding outside its claim. Proposed '
        'change: do not add prompt text. The autopsy lists the contract ids. '
        'Only an executor verdict may tighten a bound or narrow '
        'applicability. Do not edit phi. Do not add a contract in this file.'
    ),
}


def _pub(metrics):
    if not metrics:
        return None
    rounded = round_metrics(metrics)
    keep = ('n', 'tp', 'fp', 'fn', 'tn', 'precision', 'recall',
            'fnr', 'bacc', 'disc', 'abstain')
    return {key: rounded.get(key) for key in keep}


def _disc(metrics):
    if not metrics:
        return None
    return metrics.get('disc')


def _clone(episode, feedback):
    out = dict(episode)
    out['feedback'] = feedback
    return out


def load_deduped(path):
    loaded = load_probe(path)
    real = [ep for ep in loaded['episodes'] if not ep.get('smoke')]
    deduped, dropped = dedupe(real)
    return {
        'episodes': deduped,
        'dropped': dropped,
        'labeled': len(loaded['episodes']),
        'smoke': sum(1 for ep in loaded['episodes'] if ep.get('smoke')),
        'probe': path,
    }


def by_session(episodes):
    groups = {}
    for ep in episodes:
        groups.setdefault(ep.get('session') or '', []).append(ep)
    return groups


def inner_split(episodes):
    """First 60% by timestamp is the proposal slice. The rest is the inner replay."""
    ordered = sorted(episodes, key=lambda ep: (ep.get('ts') or '', ep.get('event_id') or ''))
    if len(ordered) < 2:
        return ordered, []
    cut = int(round(len(ordered) * 0.6))
    cut = min(max(cut, 1), len(ordered) - 1)
    return ordered[:cut], ordered[cut:]


def standard_split(episodes):
    proposal, replay = [], []
    for ep in episodes:
        sid = ep.get('session') or ''
        ts = ep.get('ts') or ''
        if '20261009' in sid or ts.startswith('2026-10-09'):
            replay.append(ep)
        else:
            proposal.append(ep)
    return proposal, replay


def fresh_seed():
    library = load()
    library.pop('_source_path', None)
    return library


def shipped_revised():
    library = load(os.path.join(HERE, 'results', 'revised_library.json'))
    library.pop('_source_path', None)
    return library


def ablation_libraries():
    seed = fresh_seed()
    only_mid = with_bounds(
        seed, [('stuck_speak', 'require_not_mid', True)],
        reason='ablation require_not_mid only')
    only_plan = with_bounds(
        seed, [('*shared*', 'planning_ms', 1250)],
        reason='ablation planning_ms only')
    both = with_bounds(
        only_mid, [('*shared*', 'planning_ms', 1250)],
        reason='ablation both accepted edits')
    return {
        'seed': seed,
        'require_not_mid': only_mid,
        'planning_ms': only_plan,
        'both': both,
    }


def _accepted_brief(accepted):
    return [
        {'contract_id': item['contract_id'], 'bound': item['bound'],
         'from': item['from'], 'to': item['to']}
        for item in accepted
    ]


def run_e2(episodes):
    folds = []
    groups = by_session(episodes)
    seed = fresh_seed()
    for held_id, held in sorted(groups.items()):
        train = [ep for sid, rows in groups.items() if sid != held_id for ep in rows]
        proposal, inner = inner_split(train)
        countable = (
            len(held) >= HELD_MIN
            and len(proposal) >= PROPOSAL_MIN
            and len(inner) >= INNER_MIN
        )
        fold = {
            'held_session': held_id,
            'held_n': len(held),
            'train_n': len(train),
            'proposal_n': len(proposal),
            'inner_n': len(inner),
            'countable': countable,
            'held_ids': [ep.get('event_id') for ep in held],
            'train_ids': [ep.get('event_id') for ep in train],
        }
        if not countable:
            fold['verdict'] = 'inconclusive'
            fold['why'] = 'fold below the preregistered size floor'
            folds.append(fold)
            continue
        run = evolve(seed, proposal, inner, mode='gate')
        revised = run['library']
        logged_m = score_episodes(seed, held, mode='logged')
        seed_m = score_episodes(seed, held, mode='gate')
        revised_m = score_episodes(revised, held, mode='gate')
        reasons = []
        logged_worse = worse(logged_m, revised_m)
        seed_worse = worse(seed_m, revised_m)
        if logged_worse:
            reasons.append('vs logged: ' + logged_worse)
        if seed_worse:
            reasons.append('vs seed: ' + seed_worse)
        disc_r = _disc(revised_m)
        disc_l = _disc(logged_m)
        disc_s = _disc(seed_m)
        strengthens = (
            not reasons
            and disc_r is not None and disc_l is not None and disc_s is not None
            and disc_r < disc_l - 1e-12
            and disc_r <= disc_s + 1e-12
        )
        if reasons:
            verdict = 'system_fail'
        elif strengthens:
            verdict = 'pass'
        else:
            verdict = 'inconclusive'
        fold.update({
            'accepted': _accepted_brief(run['accepted']),
            'logged': _pub(logged_m),
            'seed_gate': _pub(seed_m),
            'revised_gate': _pub(revised_m),
            'phi_unchanged': snapshot_phi(revised) == snapshot_phi(seed),
            'verdict': verdict,
            'why': '; '.join(reasons) if reasons else (
                'strengthens' if strengthens else 'no regression and no strict gain'),
        })
        folds.append(fold)
    countable = [fold for fold in folds if fold['countable']]
    if any(fold['verdict'] == 'system_fail' for fold in countable):
        verdict = 'system_fail'
    elif any(fold['verdict'] == 'pass' for fold in countable):
        verdict = 'pass'
    else:
        verdict = 'inconclusive'
    reasons = []
    for fold in folds:
        if fold['verdict'] != 'system_fail':
            continue
        edits = ', '.join(
            '%s.%s->%s' % (item['bound'], item['from'], item['to'])
            for item in fold.get('accepted') or []) or 'none'
        reasons.append('%s: %s (accepted %s)' % (
            fold['held_session'], fold.get('why') or '', edits))
    why = ' | '.join(reasons) if reasons else (
        'at least one held-out session strengthened without a regression'
        if verdict == 'pass' else 'no countable strengthen')
    return {
        'id': 'E2',
        'name': 'leave-one-session-out',
        'verdict': verdict,
        'why': why,
        'folds': folds,
    }


def run_e3(episodes):
    libs = ablation_libraries()
    proposal, replay = standard_split(episodes)
    slices = {'proposal': proposal, 'replay': replay, 'pooled': episodes}
    table = {}
    for name, library in libs.items():
        table[name] = {slice_name: _pub(score_episodes(library, rows, mode='gate'))
                       for slice_name, rows in slices.items()}
    shipped = shipped_revised()
    shipped_replay = _pub(score_episodes(shipped, replay, mode='gate'))
    both_replay = table['both']['replay']
    seed_replay_m = score_episodes(libs['seed'], replay, mode='gate')
    both_m = score_episodes(libs['both'], replay, mode='gate')
    mid_m = score_episodes(libs['require_not_mid'], replay, mode='gate')
    plan_m = score_episodes(libs['planning_ms'], replay, mode='gate')
    reasons = []
    both_worse = worse(seed_replay_m, both_m)
    mid_worse = worse(seed_replay_m, mid_m)
    plan_worse = worse(seed_replay_m, plan_m)
    if both_worse:
        reasons.append('both vs seed: ' + both_worse)
    if mid_worse:
        reasons.append('require_not_mid vs seed: ' + mid_worse)
    both_disc = _disc(both_m)
    seed_disc = _disc(seed_replay_m)
    disc_ok = (both_disc is not None and seed_disc is not None
               and both_disc <= seed_disc + 1e-12)
    if not reasons and disc_ok:
        verdict = 'pass'
    elif reasons:
        verdict = 'system_fail'
    else:
        verdict = 'system_fail'
        reasons.append('both disc rose above seed without tripping worse()')
    load = {}
    for component, other_disc in (
            ('require_not_mid', _disc(plan_m)),
            ('planning_ms', _disc(mid_m))):
        # Removing the component leaves the other library. Load-bearing if
        # the pair's disc is strictly below that remainder.
        load[component] = (
            both_disc is not None and other_disc is not None
            and both_disc < other_disc - 1e-12
        )
    return {
        'id': 'E3',
        'name': 'ablation of the two accepted edits',
        'verdict': verdict,
        'why': '; '.join(reasons) if reasons else 'pair does not regress versus seed on the held replay',
        'warning': ('planning_ms alone regresses versus seed: ' + plan_worse) if plan_worse else '',
        'load_bearing': load,
        'table': table,
        'shipped_revised_replay': shipped_replay,
        'shipped_matches_both_disc': (
            shipped_replay and both_replay
            and shipped_replay.get('disc') == both_replay.get('disc')
            and shipped_replay.get('n') == both_replay.get('n')
        ),
        'phi_unchanged': all(
            snapshot_phi(library) == snapshot_phi(libs['seed'])
            for library in libs.values()),
    }


def _permute(episodes, rng):
    labels = [ep.get('feedback') for ep in episodes]
    rng.shuffle(labels)
    return [_clone(ep, label) for ep, label in zip(episodes, labels)]


def _p_value(real, nulls):
    if real is None or not nulls:
        return None
    n_le = sum(1 for value in nulls if value is not None and value <= real + 1e-12)
    return (1 + n_le) / float(1 + len(nulls))


def run_e4(episodes, n_score, n_refit):
    seed = fresh_seed()
    revised = shipped_revised()
    real_revised = score_episodes(revised, episodes, mode='gate')
    real_seed = score_episodes(seed, episodes, mode='gate')
    proposal, replay = standard_split(episodes)
    real_fit = evolve(seed, proposal, replay, mode='gate')
    score_rng = random.Random(SCORE_SEED)
    revised_null = []
    seed_null = []
    for _ in range(n_score):
        shuffled = _permute(episodes, score_rng)
        revised_null.append(_disc(score_episodes(revised, shuffled, mode='gate')))
        seed_null.append(_disc(score_episodes(seed, shuffled, mode='gate')))
    refit_rng = random.Random(REFIT_SEED)
    accepted_null = []
    for _ in range(n_refit):
        shuffled = _permute(episodes, refit_rng)
        prop, rep = standard_split(shuffled)
        fit = evolve(fresh_seed(), prop, rep, mode='gate')
        accepted_null.append(len(fit['accepted']))
    p_revised = _p_value(_disc(real_revised), revised_null)
    p_seed = _p_value(_disc(real_seed), seed_null)
    e4a_pass = p_revised is not None and p_revised < 0.05
    median_null = statistics.median(accepted_null) if accepted_null else None
    real_accepted = len(real_fit['accepted'])
    e4b_fail = median_null is not None and real_accepted <= median_null
    if e4a_pass and not e4b_fail:
        verdict = 'pass'
    else:
        verdict = 'system_fail'
    why = []
    if not e4a_pass:
        why.append('revised pooled disc is not below the shuffle 5 percent bar (p=%s)' % p_revised)
    if e4b_fail:
        why.append(
            'real accepted count %s is at or below the shuffle median %s '
            '(fixed-library revised p=%s; that half of the bar is separate)'
            % (real_accepted, median_null, None if p_revised is None else round(p_revised, 4)))
    return {
        'id': 'E4',
        'name': 'label-shuffle null',
        'verdict': verdict,
        'why': '; '.join(why) if why else 'revised disc beats the shuffle and the gate accepts fewer steps on noise',
        'n_score_perms': n_score,
        'n_refit_perms': n_refit,
        'score_seed': SCORE_SEED,
        'refit_seed': REFIT_SEED,
        'real_revised': _pub(real_revised),
        'real_seed': _pub(real_seed),
        'p_revised': None if p_revised is None else round(p_revised, 4),
        'p_seed': None if p_seed is None else round(p_seed, 4),
        'e4a_pass': e4a_pass,
        'revised_null_disc': [None if v is None else round(v, 4) for v in revised_null],
        'seed_null_disc': [None if v is None else round(v, 4) for v in seed_null],
        'real_accepted': real_accepted,
        'real_accepted_edits': _accepted_brief(real_fit['accepted']),
        'null_accepted_counts': accepted_null,
        'null_accepted_median': median_null,
        'e4b_system_fail': e4b_fail,
        'phi_unchanged': snapshot_phi(revised) == snapshot_phi(seed),
    }


def run_e5(episodes):
    seed, revised = fresh_seed(), shipped_revised()
    rows = []
    speak_pool = []
    for ep in episodes:
        rule, _ = live.decide_arm('rule', ep, seed, revised)
        logged, _ = live.decide_arm('logged', ep, seed, revised)
        revised_bit, detail = live.decide_arm('revised_gate', ep, seed, revised)
        wanted = desired_silent(ep.get('feedback'))
        exposed = (rule is True) or (logged is True)
        withheld = exposed and (revised_bit is False)
        if detail.get('cascade_speak') is False:
            via = 'silence_contract'
        else:
            via = 'gate_kept_prior'
        record = {
            'event_id': ep.get('event_id'),
            'session': ep.get('session'),
            'feedback': ep.get('feedback'),
            'wanted_silent': wanted,
            'rule': None if rule is None else bool(rule),
            'logged': None if logged is None else bool(logged),
            'revised': None if revised_bit is None else bool(revised_bit),
            'selected': detail.get('selected'),
            'withhold_via': via,
            'in_W': withheld,
        }
        if exposed and wanted is not None:
            speak_pool.append(wanted is True)
        if withheld:
            rows.append(record)
    def rate(flags):
        if not flags:
            return None
        return sum(1 for flag in flags if flag) / float(len(flags))
    w_flags = [row['wanted_silent'] is True for row in rows if row['wanted_silent'] is not None]
    w_rate = rate(w_flags)
    base = rate(speak_pool)
    n_w = len(rows)
    if n_w < AUTOPSY_MIN:
        verdict = 'inconclusive'
        why = 'fewer than %d withheld rows' % AUTOPSY_MIN
    elif w_rate is None or base is None:
        verdict = 'inconclusive'
        why = 'wanted-silence label missing'
    elif w_rate < 0.5:
        verdict = 'system_fail'
        why = 'wanted-silence rate in W is below 0.5'
    elif w_rate > base + 1e-12 and w_rate >= 0.5:
        verdict = 'pass'
        why = 'withholds are enriched for turns the author wanted silent'
    else:
        verdict = 'inconclusive'
        why = 'rate is at least 0.5 but not above the base rate of exposed speaks'
    by_contract = {}
    kept_prior = 0
    for row in rows:
        if row.get('withhold_via') != 'silence_contract':
            kept_prior += 1
            continue
        key = row.get('selected') or '(none)'
        by_contract[key] = by_contract.get(key, 0) + 1
    return {
        'id': 'E5',
        'name': 'withhold autopsy',
        'verdict': verdict,
        'why': why,
        'n_W': n_w,
        'wanted_silent_in_W': sum(1 for flag in w_flags if flag),
        'wanted_silent_rate': None if w_rate is None else round(w_rate, 4),
        'base_exposed_n': len(speak_pool),
        'base_wanted_silent_rate': None if base is None else round(base, 4),
        'by_contract': by_contract,
        'gate_kept_prior': kept_prior,
        'rows': rows,
        'phi_unchanged': snapshot_phi(revised) == snapshot_phi(seed),
    }


def run_e1_manifest(episodes):
    seed, revised = fresh_seed(), shipped_revised()
    rows = []
    for ep in episodes:
        bits = {}
        for arm, _name in live.ARMS:
            bit, _detail = live.decide_arm(arm, ep, seed, revised)
            bits[arm] = None if bit is None else bool(bit)
        kinds = {'abstain' if value is None else value for value in bits.values()}
        if len(kinds) > 1:
            rows.append({
                'event_id': ep.get('event_id'),
                'session': ep.get('session'),
                'feedback': ep.get('feedback'),
                'arms': bits,
            })
    return {
        'id': 'E1',
        'name': 'live expand',
        'verdict': 'pending_laptop',
        'why': 'Hook only. The laptop executor fills results/e1_live_expand_report.json.',
        'n_disagreement': len(rows),
        'max_calls': 16,
        'endpoint': live.DEFAULT_BASE + '/v1/messages',
        'model': live.DEFAULT_MODEL,
        'thinking': 'disabled',
        'api': 'anthropic-messages',
        'command': 'python3 eval_exp_suite.py --live --only e1',
        'fallback_command': 'python3 eval_live_dots3.py --slice replay --max-calls 12',
        'pass_bar': (
            'On this disagreement set, revised-gate label_agree >= logged '
            'label_agree and both scored n >= 8. Not judged until the laptop file exists.'
        ),
        'turns': rows,
    }


def judge_suite(e2, e3, e4, e5):
    experiments = (e2, e3, e4, e5)
    if any(item['verdict'] == 'system_fail' for item in experiments):
        return 'system_fail'
    if all(item['verdict'] == 'pass' for item in experiments):
        return 'pass'
    return 'mixed'


def render_matrix(report):
    lines = []
    lines.append('# Skill-V-lite experiment matrix')
    lines.append('')
    lines.append('Primary validation path, with the live dots3 harness. The offline A/B in `eval_ab.py` stays available and is not this matrix.')
    lines.append('')
    lines.append(PREREG)
    lines.append('')
    lines.append('## This run')
    lines.append('')
    lines.append('- Offline verdict: `%s`' % report['offline_verdict'])
    lines.append('- E1: `%s`' % report['e1']['verdict'])
    lines.append('- Probe: `%s`' % report['sample']['probe'])
    lines.append('- Deduped n: %d (sessions: %s)' % (
        report['sample']['deduped'],
        ', '.join('%s=%d' % (sid, n) for sid, n in report['sample']['sessions'])))
    lines.append('- phi edited: no')
    lines.append('')
    lines.append('| experiment | verdict | why |')
    lines.append('|---|---|---|')
    for item in (report['e1'], report['e2'], report['e3'], report['e4'], report['e5']):
        why = (item.get('why') or '').replace('|', '/')
        lines.append('| %s %s | `%s` | %s |' % (item['id'], item['name'], item['verdict'], why))
    lines.append('')
    lines.append('### E2 folds')
    lines.append('')
    lines.append('| held session | n | countable | revised disc | logged disc | seed disc | accepted | verdict |')
    lines.append('|---|---:|---|---:|---:|---:|---|---|')
    for fold in report['e2']['folds']:
        def cell(block):
            if not block or block.get('disc') is None:
                return '—'
            return '%.4f' % block['disc']
        accepted = ', '.join(
            '%s.%s→%s' % (item['bound'], item['from'], item['to'])
            for item in fold.get('accepted') or []) or '—'
        lines.append('| %s | %d | %s | %s | %s | %s | %s | `%s` |' % (
            fold['held_session'], fold['held_n'], 'yes' if fold['countable'] else 'no',
            cell(fold.get('revised_gate')), cell(fold.get('logged')),
            cell(fold.get('seed_gate')), accepted, fold['verdict']))
    lines.append('')
    lines.append('### E3 held replay (2026-10-09)')
    lines.append('')
    lines.append('| library | n | disc | fnr | bacc | load-bearing |')
    lines.append('|---|---:|---:|---:|---:|---|')
    for name in ('seed', 'require_not_mid', 'planning_ms', 'both'):
        block = report['e3']['table'][name]['replay'] or {}
        def num(key):
            value = block.get(key)
            return '—' if value is None else '%.4f' % value
        bearing = report['e3']['load_bearing'].get(name)
        bearing_txt = '—' if bearing is None else ('yes' if bearing else 'no')
        lines.append('| %s | %s | %s | %s | %s | %s |' % (
            name, block.get('n'), num('disc'), num('fnr'), num('bacc'), bearing_txt))
    if report['e3'].get('warning'):
        lines.append('')
        lines.append('Warning: %s' % report['e3']['warning'])
    lines.append('')
    lines.append('### E4 null')
    lines.append('')
    e4 = report['e4']
    lines.append('- Real revised disc %s, p=%s (pass bar p<0.05). Real seed disc %s, p=%s.' % (
        (e4['real_revised'] or {}).get('disc'), e4['p_revised'],
        (e4['real_seed'] or {}).get('disc'), e4['p_seed']))
    lines.append('- Real accepted edits: %d. Shuffle median accepted: %s. E4b system-fail: %s.' % (
        e4['real_accepted'], e4['null_accepted_median'], e4['e4b_system_fail']))
    lines.append('- Permutations: score %d (seed %d), refit %d (seed %d).' % (
        e4['n_score_perms'], e4['score_seed'], e4['n_refit_perms'], e4['refit_seed']))
    lines.append('')
    lines.append('### E5 withhold set')
    lines.append('')
    e5 = report['e5']
    lines.append('- |W|=%d. Wanted silence in W: %s/%d (rate %s). Base rate on rule-or-logged speaks: %s (n=%d).' % (
        e5['n_W'], e5['wanted_silent_in_W'], e5['n_W'], e5['wanted_silent_rate'],
        e5['base_wanted_silent_rate'], e5['base_exposed_n']))
    if e5['by_contract']:
        lines.append('- Silence contracts that withheld: %s. Gate kept a logged silence while the rule said speak: %d.' % (
            ', '.join('%s=%d' % (key, count) for key, count in sorted(e5['by_contract'].items())) or '—',
            e5.get('gate_kept_prior') or 0))
    lines.append('')
    lines.append('### E1 live expand')
    lines.append('')
    e1 = report['e1']
    lines.append('- Disagreement turns: %d. Cap %d unique calls.' % (
        e1['n_disagreement'], e1['max_calls']))
    lines.append('- Laptop command: `%s`' % e1['command'])
    lines.append('- Endpoint: `%s` model `%s`, thinking disabled.' % (e1['endpoint'], e1['model']))
    lines.append('- %s' % e1['pass_bar'])
    if report.get('principle_proposal'):
        lines.append('')
        lines.append('Principle proposal written: `%s`' % report['principle_proposal'])
    lines.append('')
    return '\n'.join(lines) + '\n'


def write_proposal(path, failed, report):
    lines = []
    lines.append('# Principle revision proposal')
    lines.append('')
    lines.append('The preregistered bar failed. This file proposes the principle change. It does not edit phi, bounds, or prompt text. Implement only after an executor verdict.')
    lines.append('')
    lines.append('Offline verdict: `%s`.' % report['offline_verdict'])
    lines.append('')
    for item in failed:
        lines.append('## %s — %s' % (item['id'], item['name']))
        lines.append('')
        lines.append(PROPOSAL_TEXT[item['id']])
        lines.append('')
        lines.append('Measured: %s' % (item.get('why') or ''))
        lines.append('')
    lines.append('phi lock: unchanged. No API key is involved in this proposal.')
    lines.append('')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines))


def _json_ready(report):
    """Drop bulky null vectors from the markdown companion only if asked.

    The JSON keeps the null lists so the p-value can be recomputed.
    """
    return report


def run_suite(path, n_score, n_refit, out_dir, live_run=False, caller=None, preflight_fn=None):
    os.makedirs(out_dir, exist_ok=True)
    loaded = load_deduped(path)
    episodes = loaded['episodes']
    sessions = sorted((sid, len(rows)) for sid, rows in by_session(episodes).items())
    e1 = run_e1_manifest(episodes)
    e2 = run_e2(episodes)
    e3 = run_e3(episodes)
    e4 = run_e4(episodes, n_score, n_refit)
    e5 = run_e5(episodes)
    offline = judge_suite(e2, e3, e4, e5)
    report = {
        'offline_verdict': offline,
        'prereg': PREREG,
        'sample': {
            'probe': path,
            'labeled': loaded['labeled'],
            'smoke': loaded['smoke'],
            'duplicates_dropped': loaded['dropped'],
            'deduped': len(episodes),
            'sessions': sessions,
        },
        'e1': e1,
        'e2': e2,
        'e3': e3,
        'e4': e4,
        'e5': e5,
        'phi_edited': False,
        'principle_proposal': '',
    }
    if live_run:
        report['e1'] = _run_live_expand(e1, episodes, caller, preflight_fn, out_dir)
    # Stop rule: a principle proposal is written only when the iteration
    # verdict is stop. Round-1 is a conditional keep, which is not a stop.
    # A cloud-harness system_fail does not by itself create that file.
    if offline == 'stop':
        failed = [item for item in (e2, e3, e4, e5) if item['verdict'] == 'system_fail']
        proposal_path = os.path.join(out_dir, 'principle_revision_proposal.md')
        write_proposal(proposal_path, failed, report)
        report['principle_proposal'] = 'principle_revision_proposal.md'
    manifest_path = os.path.join(out_dir, 'e1_live_expand_manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as handle:
        json.dump(e1, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    matrix_path = os.path.join(out_dir, 'exp_matrix.md')
    json_path = os.path.join(out_dir, 'exp_matrix.json')
    text = render_matrix(report)
    with open(matrix_path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    with open(json_path, 'w', encoding='utf-8') as handle:
        json.dump(_json_ready(report), handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    return report


def _run_live_expand(manifest, episodes, caller, preflight_fn, out_dir):
    """Call dots3 on the disagreement turns. Refuse to invent scores."""
    cfg = live.resolve_config()
    check = preflight_fn or live.preflight
    conn = check(cfg, 20)
    result = dict(manifest)
    result['connectivity'] = {
        'ok': bool(conn.get('ok')),
        'url': conn.get('url') or manifest['endpoint'],
        'error': conn.get('error') or '',
        'error_type': conn.get('error_type') or '',
        'latency_ms': conn.get('latency_ms'),
    }
    result['key_present'] = bool(cfg.get('api_key'))
    if not conn.get('ok'):
        result['verdict'] = 'pending_laptop'
        result['why'] = 'Preflight failed. No live scores invented. ' + (conn.get('error') or '')
        _write_e1_report(out_dir, result)
        return result
    wanted = {row['event_id'] for row in manifest['turns']}
    selected = [ep for ep in episodes if ep.get('event_id') in wanted]
    live_caller = caller or live.make_caller(
        cfg, timeout=120, max_tokens=live.DEFAULT_MAX_TOKENS,
        temperature=0.3, thinking='disabled')
    ran = live.run_arms(
        selected, fresh_seed(), shipped_revised(), live_caller,
        max_calls=manifest['max_calls'], model=cfg.get('model') or live.DEFAULT_MODEL,
        max_tokens=live.DEFAULT_MAX_TOKENS, temperature=0.3,
        thinking='disabled', timeout=120)
    result['live'] = {
        'unique_calls': ran['unique_calls'],
        'arms': ran['arms'],
        'calls_preview_omitted': False,
        'calls': [
            {key: call.get(key) for key in ('event_id', 'arm', 'ok', 'latency_ms', 'stop', 'error', 'chars')}
            for call in ran['calls']
        ],
    }
    by_id = {arm['id']: arm for arm in ran['arms']}
    revised_arm = by_id.get('revised_gate') or {}
    logged_arm = by_id.get('logged') or {}
    result['live_judge'] = {
        'revised_label_agree': revised_arm.get('label_agree'),
        'logged_label_agree': logged_arm.get('label_agree'),
        'revised_scored': revised_arm.get('label_agree_scored'),
        'logged_scored': logged_arm.get('label_agree_scored'),
    }
    rev_s = revised_arm.get('label_agree_scored') or 0
    log_s = logged_arm.get('label_agree_scored') or 0
    rev_h = revised_arm.get('label_agree_hits') or 0
    log_h = logged_arm.get('label_agree_hits') or 0
    if rev_s < 8 or log_s < 8:
        result['verdict'] = 'inconclusive'
        result['why'] = 'live disagreement set scored fewer than 8 turns'
    elif log_s and rev_s and (rev_h / float(rev_s)) + 1e-12 >= (log_h / float(log_s)):
        result['verdict'] = 'pass'
        result['why'] = 'revised-gate label agreement is at least the logged arm'
    else:
        result['verdict'] = 'system_fail'
        result['why'] = 'revised-gate label agreement is below the logged arm on the live expand'
    _write_e1_report(out_dir, result)
    return result


def _write_e1_report(out_dir, result):
    path = os.path.join(out_dir, 'e1_live_expand_report.json')
    blob = json.dumps(result, ensure_ascii=False, indent=2)
    key_markers = ('"api_key"',)
    for marker in key_markers:
        if marker in blob:
            raise RuntimeError('refusing to write a live report that contains an api key field')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(blob)
        handle.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Skill-V-lite experiment suite')
    parser.add_argument('--probe', default=DEFAULT_PROBE)
    parser.add_argument('--out', default=os.path.join(HERE, 'results'))
    parser.add_argument('--perms', type=int, default=N_SCORE_PERMS)
    parser.add_argument('--refit-perms', type=int, default=N_REFIT_PERMS)
    parser.add_argument('--only', default='',
                        help='comma list of e1,e2,e3,e4,e5. Default runs all offline.')
    parser.add_argument('--live', action='store_true',
                        help='E1 actually calls dots3. Without this flag E1 is a manifest.')
    args = parser.parse_args(argv)
    only = {part.strip().lower() for part in args.only.split(',') if part.strip()}
    # Partial selection still builds every offline result the prereg needs,
    # except when the caller asks for E1 alone during a live attempt.
    if only == {'e1'}:
        loaded = load_deduped(args.probe)
        e1 = run_e1_manifest(loaded['episodes'])
        os.makedirs(args.out, exist_ok=True)
        manifest_path = os.path.join(args.out, 'e1_live_expand_manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as handle:
            json.dump(e1, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        if not args.live:
            print('E1 manifest: %d disagreement turns' % e1['n_disagreement'])
            print('wrote %s' % manifest_path)
            print('Laptop: %s' % e1['command'])
            return 0
        result = _run_live_expand(e1, loaded['episodes'], None, None, args.out)
        print('E1 %s' % result['verdict'])
        print(result.get('why') or '')
        return 0 if result['verdict'] != 'pending_laptop' else 2
    report = run_suite(
        args.probe, args.perms, args.refit_perms, args.out, live_run=args.live)
    text_path = os.path.join(args.out, 'exp_matrix.md')
    print(open(text_path, encoding='utf-8').read())
    print('offline verdict: %s' % report['offline_verdict'])
    if args.live and report['e1'].get('verdict') == 'pending_laptop' and report['e1'].get('connectivity'):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
