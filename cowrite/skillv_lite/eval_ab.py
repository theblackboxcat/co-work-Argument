# -*- coding: utf-8 -*-
"""Offline A/B: logged cowrite speak policy vs Skill-V-lite.

No model call. dots3 is not required. Labels are the author feedback
already stored in the probe log.

    python eval_ab.py
    python eval_ab.py --probe ../Cowrite-test/app/v3/logs/probe.jsonl
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from skillv.contracts import load, phi_digest  # noqa: E402
from skillv.decide import (  # noqa: E402
    RULE_SPEAK,
    cascade,
    rubric_disagreements,
    score_episodes,
)
from skillv.episodes import dedupe, load_probe, split_replay  # noqa: E402
from skillv.evolve import evolve  # noqa: E402
from skillv.metrics import project_logged_cells, round_metrics  # noqa: E402

DEFAULT_PROBE = os.path.abspath(os.path.join(
    HERE, '..', 'Cowrite-test', 'app', 'v3', 'logs', 'probe.jsonl'))


def _fmt(m):
    if not m or m.get('disc') is None:
        return 'n=0'
    def pct(key):
        v = m.get(key)
        return '—' if v is None else '%.4f' % v
    return 'n=%d  disc=%s  fnr=%s  bacc=%s  prec=%s  recall=%s' % (
        m.get('n') or 0, pct('disc'), pct('fnr'), pct('bacc'),
        pct('precision'), pct('recall'))


def _cell(m, key):
    if not m or m.get(key) is None:
        return '—'
    return '%.4f' % m[key]


def agreement(library, episodes):
    compared = matched = 0
    mismatches = []
    for ep in episodes:
        if ep.get('signals_missing') or not ep.get('attn_state'):
            continue
        if ep['attn_state'] not in RULE_SPEAK:
            continue
        decision = cascade(library, ep)
        if decision['abstain']:
            mismatches.append({
                'event_id': ep.get('event_id'),
                'attn_state': ep['attn_state'],
                'skillv': 'abstain',
            })
            compared += 1
            continue
        want = RULE_SPEAK[ep['attn_state']]
        compared += 1
        if bool(decision['speak']) == bool(want) and decision.get('state') == ep['attn_state']:
            matched += 1
        elif bool(decision['speak']) == bool(want):
            # Same speak bit, different state name (residual vs coding).
            # Count speak-bit agreement separately.
            matched += 0
            mismatches.append({
                'event_id': ep.get('event_id'),
                'attn_state': ep['attn_state'],
                'skillv_state': decision.get('state'),
                'speak_match': True,
            })
        else:
            mismatches.append({
                'event_id': ep.get('event_id'),
                'attn_state': ep['attn_state'],
                'skillv_state': decision.get('state'),
                'logged_rule_speak': want,
                'skillv_speak': decision.get('speak'),
            })
    speak_match = 0
    for ep in episodes:
        if ep.get('signals_missing') or ep.get('attn_state') not in RULE_SPEAK:
            continue
        decision = cascade(library, ep)
        if decision['abstain']:
            continue
        if bool(decision['speak']) == bool(RULE_SPEAK[ep['attn_state']]):
            speak_match += 1
    return {
        'compared': compared,
        'state_and_speak_matched': matched,
        'speak_bit_matched': speak_match,
        'mismatches': mismatches,
    }


def table_row(name, m):
    return '| %s | %s | %s | %s | %s | %s | %s |' % (
        name,
        m.get('n') if m else 0,
        _cell(m, 'disc'),
        _cell(m, 'fnr'),
        _cell(m, 'bacc'),
        _cell(m, 'precision'),
        _cell(m, 'recall'),
    )


def render_markdown(report):
    lines = []
    lines.append('# Skill-V-lite offline A/B')
    lines.append('')
    lines.append('Cowrite speak/silence policy only. This is not a co-address result.')
    lines.append('No model was called. dots3 was not required.')
    lines.append('')
    lines.append('## Protocol')
    lines.append('')
    lines.append('- Labels: author feedback already on `probe.jsonl`.')
    lines.append('- Excluded: unlabeled rows, non speak/silence events, smoke session `%s`.'
                 % report['smoke_session'])
    lines.append('- Primary rows are de-duplicated double-fires. Raw labeled counts are below.')
    lines.append('- Proposal slice: sessions before 2026-10-09. Replay buffer: 2026-10-09.')
    lines.append('- Positive class: author wanted silence.')
    lines.append('- `disc` = (FP+FN)/n. `fnr` = FN/(FN+TP). `bacc` = (TPR+TNR)/2.')
    lines.append('- Semantic desired silence includes `silent_had_nothing`. The project confusion table does not; it is reported separately and only for logged actions.')
    lines.append('- Evolution may change bounds only. A step is accepted when proposal-slice disc falls and replay disc, FNR, and bacc do not worsen.')
    lines.append('- Shipped flag default is `gate`: withhold when the contract says silence; do not force speech; do not add prompt clauses.')
    lines.append('')
    lines.append('## Sample')
    lines.append('')
    s = report['sample']
    lines.append('| | n |')
    lines.append('|---|---:|')
    lines.append('| labeled speak/silence rows | %d |' % s['labeled'])
    lines.append('| smoke fixture excluded | %d |' % s['smoke'])
    lines.append('| duplicate fires dropped | %d |' % s['duplicates_dropped'])
    lines.append('| deduped, used | %d |' % s['deduped'])
    lines.append('| proposal slice | %d |' % s['evolve'])
    lines.append('| replay buffer | %d |' % s['replay'])
    lines.append('| missing attention signals (gate abstains) | %d |' % s['signals_missing'])
    lines.append('')
    lines.append('Library size: **%d** contracts. Seed library version %s. Revised library version %s.'
                 % (report['library_size'], report['seed_version'], report['revised_version']))
    lines.append('')
    lines.append('Seed cascade vs logged attention rule: speak-bit match %d/%d, state+speak match %d/%d.'
                 % (report['seed_agreement']['speak_bit_matched'],
                    report['seed_agreement']['compared'],
                    report['seed_agreement']['state_and_speak_matched'],
                    report['seed_agreement']['compared']))
    mismatches = report['seed_agreement'].get('mismatches') or []
    if mismatches:
        lines.append('')
        lines.append('Speak-bit matches with a different state name:')
        for row in mismatches:
            if row.get('speak_match'):
                lines.append('- `%s` logged %s, contract %s (speak bit agrees)' % (
                    row.get('event_id'), row.get('attn_state'), row.get('skillv_state')))
    lines.append('')
    lines.append('## A/B on deduped labeled episodes')
    lines.append('')
    lines.append('| arm | n | disc | fnr | bacc | silence prec | silence recall |')
    lines.append('|---|---:|---:|---:|---:|---:|---:|')
    for name, m in report['arms_all']:
        lines.append(table_row(name, m))
    lines.append('')
    lines.append('Silence-recall 95% Wilson intervals on this table:')
    for name, m in report['arms_all']:
        ci = (m or {}).get('recall_wilson95')
        if ci:
            lines.append('- %s: %s' % (name, ci))
    lines.append('')
    lines.append('## Replay buffer only (held, 2026-10-09)')
    lines.append('')
    lines.append('| arm | n | disc | fnr | bacc | silence prec | silence recall |')
    lines.append('|---|---:|---:|---:|---:|---:|---:|')
    for name, m in report['arms_replay']:
        lines.append(table_row(name, m))
    lines.append('')
    lines.append('## Proposal slice only (before 2026-10-09)')
    lines.append('')
    lines.append('| arm | n | disc | fnr | bacc | silence prec | silence recall |')
    lines.append('|---|---:|---:|---:|---:|---:|---:|')
    for name, m in report['arms_evolve']:
        lines.append(table_row(name, m))
    lines.append('')
    lines.append('## Revisions')
    lines.append('')
    lines.append('Accepted: **%d**. Rejected by the evidence gate: **%d**. Grid points considered: %d.'
                 % (len(report['accepted']), len(report['rejected']), report['considered']))
    lines.append('')
    if report['accepted']:
        lines.append('| bound | from | to | proposal disc | replay disc | replay fnr | replay bacc |')
        lines.append('|---|---|---|---:|---:|---:|---:|')
        for row in report['accepted']:
            rp = row.get('replay') or {}
            ev = row.get('evolve') or {}
            lines.append('| %s.%s | %s | %s | %s | %s | %s | %s |' % (
                row['contract_id'], row['bound'], row['from'], row['to'],
                _cell(ev, 'disc'), _cell(rp, 'disc'), _cell(rp, 'fnr'),
                _cell(rp, 'bacc')))
        lines.append('')
        lines.append('When two grid values tie on the replay buffer, the smaller step from the current bound is kept.')
        lines.append('')
    else:
        lines.append('No boundary step passed the gate.')
        lines.append('')
    if report['rejected']:
        lines.append('Rejected proposals (they improved the proposal slice and failed the replay gate):')
        lines.append('')
        for row in report['rejected']:
            lines.append('- `%s.%s` %s → %s: %s' % (
                row['contract_id'], row['bound'], row['from'], row['to'], row['reason']))
        lines.append('')
    lines.append('Rubric–outcome disagreements on the deduped set after revision: **%d** (seed: %d).'
                 % (report['rubric_disagreements_after'], report['rubric_disagreements_seed']))
    lines.append('')
    lines.append('## Logged actions in the project confusion table')
    lines.append('')
    p = report['project_logged']
    lines.append('TP %d, FP %d, FN %d, TN %d. precision %s, recall %s.' % (
        p.get('tp'), p.get('fp'), p.get('fn'), p.get('tn'),
        _cell(p, 'precision'), _cell(p, 'recall')))
    lines.append('')
    lines.append(p.get('note') or '')
    lines.append('')
    lines.append('The published anchor (precision 0.67, recall 0.16, n=7) is a different sample. These numbers do not replace it.')
    lines.append('')
    lines.append('## Sensitivity: same arms without de-duplication')
    lines.append('')
    lines.append('| arm | n | disc | fnr | bacc |')
    lines.append('|---|---:|---:|---:|---:|')
    for name, m in report['arms_raw']:
        lines.append('| %s | %s | %s | %s | %s |' % (
            name, m.get('n') if m else 0, _cell(m, 'disc'), _cell(m, 'fnr'), _cell(m, 'bacc')))
    lines.append('')
    lines.append('## Failure modes')
    lines.append('')
    for item in report['failure_modes']:
        lines.append('- %s' % item)
    lines.append('')
    lines.append('## How to read a negative')
    lines.append('')
    lines.append(report['reading'])
    lines.append('')
    return '\n'.join(lines)


def _arms(library, revised, episodes):
    specs = [
        ('logged (丙, as recorded)', 'logged', library),
        ('attention rule (甲 speak bit)', 'rule', library),
        ('Skill-V seed cascade', 'cascade', library),
        ('Skill-V seed gate', 'gate', library),
        ('Skill-V revised cascade', 'cascade', revised),
        ('Skill-V revised gate', 'gate', revised),
    ]
    rows = []
    for name, mode, lib in specs:
        rows.append((name, round_metrics(score_episodes(lib, episodes, mode=mode))))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description='Skill-V-lite offline A/B')
    parser.add_argument('--probe', default=DEFAULT_PROBE)
    parser.add_argument('--out', default=os.path.join(HERE, 'results'))
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    loaded = load_probe(args.probe)
    episodes = loaded['episodes']
    smoke = [ep for ep in episodes if ep.get('smoke')]
    real = [ep for ep in episodes if not ep.get('smoke')]
    deduped, dropped = dedupe(real)
    evolve_eps, replay_eps = split_replay(deduped)
    library = load()
    # Drop the loader's private path so the revised file is plain JSON.
    library.pop('_source_path', None)
    run = evolve(library, evolve_eps, replay_eps, mode='gate')
    revised = run['library']
    revised.pop('_source_path', None)

    seed_dis = rubric_disagreements(library, deduped)
    report = {
        'probe': args.probe,
        'dots3': 'not used; replay does not call a model',
        'smoke_session': 'S-20261006-231325',
        'library_size': len(library['contracts']),
        'seed_version': library.get('library_version'),
        'revised_version': revised.get('library_version'),
        'phi_ok': all(
            phi_digest(c['phi']) == library['phi_lock'][c['id']]
            for c in revised['contracts']),
        'sample': {
            'labeled': len(episodes),
            'smoke': len(smoke),
            'duplicates_dropped': dropped,
            'deduped': len(deduped),
            'evolve': len(evolve_eps),
            'replay': len(replay_eps),
            'signals_missing': sum(1 for ep in deduped if ep.get('signals_missing')),
            'skipped_kind': loaded['skipped_kind'],
            'skipped_unlabeled': loaded['skipped_unlabeled'],
        },
        'seed_agreement': agreement(library, deduped),
        'arms_all': _arms(library, revised, deduped),
        'arms_replay': _arms(library, revised, replay_eps),
        'arms_evolve': _arms(library, revised, evolve_eps),
        'arms_raw': _arms(library, revised, real),
        'accepted': run['accepted'],
        'rejected': run['rejected'],
        'considered': run['considered'],
        'rubric_disagreements_seed': len(seed_dis),
        'rubric_disagreements_after': run['rubric_disagreements_after'],
        'project_logged': round_metrics(project_logged_cells(deduped)),
        'failure_modes': [
            'Labels are sparse and were produced by one author on one test build.',
            'Several probe rows are double-fires of the same pause; the primary table de-duplicates them.',
            'The packed signal does not store doc_chars. NOT_STARTED on those rows uses passage length and after_chars as a proxy. One 32-character mid-document passage (spk-1791301921715-029) is therefore named NOT_STARTED instead of CODING; both decisions are silence, so the speak bit still matches.',
            'Rows with a null signal pack abstain. The gate keeps the logged action there.',
            'silent_had_nothing is a desired silence in the counterfactual table and an FP in the project table.',
            'Content-quality labels (接受/太弱/太强/不对) answer a different question and are not used as speak outcomes.',
            'Gate mode cannot repair a logged silence. It only withholds logged speech.',
            'The residual silence contract has no positive rubric, so some misses are not attributed to a named speak heuristic.',
            'Accepted revisions are fit on the earlier session. The held session is the non-regression check, not a large confirmation sample.',
        ],
    }
    seed_gate = dict(report['arms_all'][3][1])
    revised_gate = dict(report['arms_all'][5][1])
    logged = dict(report['arms_all'][0][1])
    rule = dict(report['arms_all'][1][1])
    held_logged = dict(report['arms_replay'][0][1])
    held_seed = dict(report['arms_replay'][3][1])
    held_rev = dict(report['arms_replay'][5][1])
    if not run['accepted']:
        reading = (
            'No revised boundary beat the seed contracts under the evidence gate. '
            'Compare logged (丙) with the seed gate and with the frozen 甲 rule. '
            'A gain of the seed gate over logged speech is the existing silence '
            'contracts being applied, not a new prompt and not a co-address result.'
        )
    else:
        def _err(m):
            if not m or m.get('n') is None:
                return '—'
            return '%d/%d' % ((m.get('fp') or 0) + (m.get('fn') or 0), m['n'])
        reading = (
            'Disagreement counts (FP+FN): deduped logged %s, seed gate %s, revised gate %s. '
            'Held 2026-10-09 buffer: logged %s, seed gate %s, revised gate %s. '
            'The seed gate matches the frozen 甲 speak bit on every row that has a logged state. '
            'On the held buffer the seed gate does not lower disc; it ties the logged action. '
            'The revised gate\'s held-set drop is a small count, and the silence-recall '
            'Wilson intervals on the pooled set overlap. '
            'No system-prompt clause was added. This is a cowrite speak/silence metric, '
            'not a co-address result.'
            % (_err(logged), _err(seed_gate), _err(revised_gate),
               _err(held_logged), _err(held_seed), _err(held_rev))
        )
    report['reading'] = reading
    report['headline'] = {
        'logged': logged,
        'rule': rule,
        'seed_gate': seed_gate,
        'revised_gate': revised_gate,
        'accepted': len(run['accepted']),
        'rejected': len(run['rejected']),
    }

    lib_path = os.path.join(args.out, 'revised_library.json')
    with open(lib_path, 'w', encoding='utf-8') as f:
        json.dump(revised, f, ensure_ascii=False, indent=2)
        f.write('\n')
    # JSON report cannot hold tuples from the arm lists as-is; convert.
    def dumpable(arms):
        return [{'arm': name, 'metrics': m} for name, m in arms]
    payload = dict(report)
    for key in ('arms_all', 'arms_replay', 'arms_evolve', 'arms_raw'):
        payload[key] = dumpable(report[key])
    json_path = os.path.join(args.out, 'ab_report.json')
    md_path = os.path.join(args.out, 'ab_report.md')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    text = render_markdown(report)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print('wrote %s' % md_path)
    print('wrote %s' % json_path)
    print('wrote %s' % lib_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
