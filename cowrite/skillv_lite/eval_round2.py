# -*- coding: utf-8 -*-
"""Round 2: freeze-bounds LOSO (E2b), 200 shuffles (E4b), chrono freeze, third-session hunt.

    python eval_round2.py --probe ../logs/probe.jsonl --out results
"""

from __future__ import print_function

import argparse
import json
import os
import random
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from skillv.contracts import load  # noqa: E402
from skillv.decide import RULE_SPEAK, predict, score_episodes  # noqa: E402
from skillv.episodes import SMOKE_SESSION, dedupe, load_probe, split_replay  # noqa: E402
from skillv.metrics import confusion, desired_silent, round_metrics  # noqa: E402

# reuse helpers from suite
from eval_exp_suite import (  # noqa: E402
    _arm_metrics,
    _cell,
    _label_agree_rows,
    _load_libs,
    _logged_metrics,
    _rule_metrics,
    _write,
)

SEED_LIB = os.path.join(HERE, 'contracts', 'library.json')
REVISED_LIB = os.path.join(HERE, 'results', 'revised_library.json')
DEFAULT_PROBE = os.path.abspath(os.path.join(HERE, '..', 'logs', 'probe.jsonl'))


def run_e2b(seed, revised, deduped, out_dir):
    """Freeze-bounds LOSO: score seed vs frozen revised per session (no re-evolve)."""
    sessions = sorted({ep.get('session') for ep in deduped if ep.get('session')})
    rows = []
    for sid in sessions:
        held = [ep for ep in deduped if ep.get('session') == sid]
        seed_m = _arm_metrics(seed, held, 'gate')
        rev_m = _arm_metrics(revised, held, 'gate')
        logged_m = _logged_metrics(held)
        rule_m = _rule_metrics(held)
        disc_ok = (
            seed_m.get('disc') is not None and rev_m.get('disc') is not None
            and rev_m['disc'] < seed_m['disc'] - 1e-12)
        agree_ok = (
            seed_m.get('label_agree_rate') is not None
            and rev_m.get('label_agree_rate') is not None
            and rev_m['label_agree_rate'] > seed_m['label_agree_rate'] + 1e-12)
        rows.append({
            'held_session': sid,
            'n_held': len(held),
            'arms': {
                'logged': logged_m,
                'rule': rule_m,
                'seed_gate': seed_m,
                'revised_frozen_gate': rev_m,
            },
            'primary': {
                'disc_lower': disc_ok,
                'agree_higher': agree_ok,
                'pass': bool(disc_ok or agree_ok),
                'seed_disc': seed_m.get('disc'),
                'rev_disc': rev_m.get('disc'),
                'seed_agree': seed_m.get('label_agree_rate'),
                'rev_agree': rev_m.get('label_agree_rate'),
                'seed_label_agree': [seed_m.get('label_agree'), seed_m.get('label_n')],
                'rev_label_agree': [rev_m.get('label_agree'), rev_m.get('label_n')],
            },
        })

    n_pass = sum(1 for r in rows if r['primary']['pass'])
    # pooled
    pooled = {
        'seed_gate': _arm_metrics(seed, deduped, 'gate'),
        'revised_frozen_gate': _arm_metrics(revised, deduped, 'gate'),
        'logged': _logged_metrics(deduped),
    }

    report = {
        'experiment': 'E2b',
        'protocol': (
            'Freeze-bounds LOSO: for each session, score seed vs shipped '
            'revised_library.json with NO re-evolve on the complement. '
            'Round-1 re-fit evolve is secondary footnote only.'
        ),
        'sessions': sessions,
        'per_session': rows,
        'n_sessions_pass': n_pass,
        'n_sessions': len(rows),
        'all_sessions_pass': n_pass == len(rows) and len(rows) > 0,
        'pooled_deduped': pooled,
        'footnote_refit': (
            'Round-1 E2 re-fit: hold 10-06 PASS, hold 10-09 FAIL when evolve '
            'accepted recontext content_min. That instability is why freeze '
            'is the primary Round-2 read.'
        ),
    }

    lines = ['# E2b — Freeze-bounds LOSO (primary Round-2 read)', '']
    lines.append(report['protocol'])
    lines.append('')
    for row in rows:
        p = row['primary']
        lines.append('## Held `%s` (n=%d) — **%s**' % (
            row['held_session'], row['n_held'],
            'PASS' if p['pass'] else 'FAIL'))
        lines.append('')
        lines.append('| arm | n | disc | fnr | bacc | label_agree | abstain |')
        lines.append('|---|---:|---:|---:|---:|---:|---:|')
        for name, m in row['arms'].items():
            lines.append('| %s | %s | %s | %s | %s | %s/%s | %s |' % (
                name, m.get('n'), _cell(m, 'disc'), _cell(m, 'fnr'),
                _cell(m, 'bacc'), m.get('label_agree'), m.get('label_n'),
                m.get('abstain')))
        lines.append('')
        lines.append('- disc %s → %s; agree %s → %s' % (
            p['seed_disc'], p['rev_disc'], p['seed_agree'], p['rev_agree']))
        lines.append('')

    lines.append('## Summary')
    lines.append('')
    lines.append('- Sessions passing primary: **%d / %d**' % (n_pass, len(rows)))
    lines.append('- All sessions pass: **%s**' % report['all_sessions_pass'])
    lines.append('- Pooled deduped: seed disc=%s agree=%s/%s; revised disc=%s agree=%s/%s' % (
        _cell(pooled['seed_gate'], 'disc'),
        pooled['seed_gate'].get('label_agree'), pooled['seed_gate'].get('label_n'),
        _cell(pooled['revised_frozen_gate'], 'disc'),
        pooled['revised_frozen_gate'].get('label_agree'),
        pooled['revised_frozen_gate'].get('label_n')))
    lines.append('')
    lines.append('## Footnote (re-fit, secondary)')
    lines.append('')
    lines.append(report['footnote_refit'])
    lines.append('')

    _write(out_dir, 'e2b_freeze_loso', report, '\n'.join(lines))
    return report


def run_e4b(seed, revised, deduped, out_dir, n_shuffle=200, rng_seed=20261018):
    """200 label shuffles; same Δdisc = disc_revised − disc_seed as E4."""
    labeled = [ep for ep in deduped if desired_silent(ep.get('feedback')) is not None]
    seed_m = score_episodes(seed, labeled, mode='gate')
    rev_m = score_episodes(revised, labeled, mode='gate')
    obs_delta = None
    if seed_m.get('disc') is not None and rev_m.get('disc') is not None:
        obs_delta = rev_m['disc'] - seed_m['disc']

    rng = random.Random(rng_seed)
    deltas = []
    for _ in range(n_shuffle):
        labels = [desired_silent(ep.get('feedback')) for ep in labeled]
        rng.shuffle(labels)
        patched = []
        for ep, y in zip(labeled, labels):
            ep2 = dict(ep)
            ep2['feedback'] = 'should_have_silent' if y else 'should_have_spoken'
            patched.append(ep2)
        s = score_episodes(seed, patched, mode='gate')
        r = score_episodes(revised, patched, mode='gate')
        if s.get('disc') is None or r.get('disc') is None:
            continue
        deltas.append(r['disc'] - s['disc'])

    if obs_delta is None or not deltas:
        p_two = None
        rank = None
        percentile = None
        n_le = n_ge_abs = None
    else:
        abs_obs = abs(obs_delta)
        n_ge_abs = sum(1 for d in deltas if abs(d) >= abs_obs - 1e-15)
        p_two = (n_ge_abs + 1) / float(len(deltas) + 1)
        sorted_d = sorted(deltas)
        rank = 1 + sum(1 for d in sorted_d if d < obs_delta - 1e-15)
        n_le = sum(1 for d in deltas if d <= obs_delta + 1e-15)
        # percentile of observed among shuffles (0 = most negative)
        percentile = (rank - 1) / float(len(deltas)) * 100.0

    null_pass = bool(
        p_two is not None and p_two <= 0.05
        and obs_delta is not None and obs_delta < 0)

    # one-sided: fraction of shuffles with delta <= observed (favor revised)
    p_one = None
    if obs_delta is not None and deltas:
        p_one = (n_le + 1) / float(len(deltas) + 1)

    report = {
        'experiment': 'E4b',
        'n_labeled': len(labeled),
        'n_shuffle': n_shuffle,
        'rng_seed': rng_seed,
        'seed_disc': seed_m.get('disc'),
        'revised_disc': rev_m.get('disc'),
        'observed_delta': obs_delta,
        'n_deltas': len(deltas),
        'shuffle_mean': (sum(deltas) / len(deltas)) if deltas else None,
        'shuffle_min': min(deltas) if deltas else None,
        'shuffle_max': max(deltas) if deltas else None,
        'shuffle_std': (
            (sum((d - sum(deltas)/len(deltas))**2 for d in deltas) / len(deltas))**0.5
            if deltas else None),
        'empirical_p_two_sided': p_two,
        'empirical_p_one_sided_le_obs': p_one,
        'rank_among_shuffles_ascending': rank,
        'percentile_ascending': percentile,
        'n_abs_ge_obs': n_ge_abs,
        'n_le_obs': n_le,
        'null_pass_extreme_favor_revised_p05': null_pass,
        # keep full list for audit (200 floats is fine)
        'shuffle_deltas': deltas,
        'same_as_e4_definition': True,
        'reading': (
            'Δdisc = disc_revised − disc_seed (negative favors revised). '
            'Same code path as E4; n_shuffle=200.'
        ),
    }

    lines = ['# E4b — Label shuffle null (n=200)', '']
    lines.append(report['reading'])
    lines.append('')
    lines.append('- Labeled n=%d; shuffles=%d; rng_seed=%d' % (
        len(labeled), n_shuffle, rng_seed))
    lines.append('- Seed disc=%s; revised disc=%s; observed Δ=%s' % (
        seed_m.get('disc'), rev_m.get('disc'), obs_delta))
    lines.append('- Shuffle Δ mean=%s std=%s min=%s max=%s' % (
        report['shuffle_mean'], report['shuffle_std'],
        report['shuffle_min'], report['shuffle_max']))
    lines.append('- Rank %s / %s ascending (percentile ≈ %.1f%% from most negative)' % (
        rank, len(deltas), percentile if percentile is not None else -1))
    lines.append('- Empirical two-sided p≈%s (|Δ|≥|obs|: %s/%s)' % (
        p_two, n_ge_abs, len(deltas)))
    lines.append('- Empirical one-sided p(Δ≤obs)≈%s' % p_one)
    lines.append('- Null extreme-favor-revised at α=0.05: **%s**' % (
        'YES' if null_pass else 'NO'))
    lines.append('')
    lines.append('## Histogram (coarse bins)')
    lines.append('')
    if deltas:
        bins = {}
        for d in deltas:
            key = round(d, 3)  # ~0.001 grid; disc steps are multiples of 1/32
            bins[key] = bins.get(key, 0) + 1
        for k in sorted(bins):
            lines.append('- Δ=%+.4f: %d' % (k, bins[k]))
    lines.append('')

    _write(out_dir, 'e4b_shuffle200', report, '\n'.join(lines))
    return report


def run_chrono(seed, revised, deduped, out_dir):
    """Chronological freeze: fit/score by timestamp if supportable."""
    # Protocol already: evolve before 2026-10-09, replay on 2026-10-09.
    # Also try mid-cut within all deduped by ts.
    sorted_eps = sorted(deduped, key=lambda e: (e.get('ts') or '', e.get('event_id') or ''))
    evolve_eps, replay_eps = split_replay(deduped)

    def pack(name, train, test):
        return {
            'name': name,
            'n_train': len(train),
            'n_test': len(test),
            'seed_test': _arm_metrics(seed, test, 'gate'),
            'revised_test': _arm_metrics(revised, test, 'gate'),
            'note': (
                'Libraries are frozen (seed vs shipped revised); no re-evolve. '
                'Train size is informational only.'
            ),
        }

    cuts = [
        pack('protocol_replay_2026-10-09', evolve_eps, replay_eps),
    ]
    # chronological 70/30 if enough points
    if len(sorted_eps) >= 10:
        cut = max(1, int(len(sorted_eps) * 0.7))
        cuts.append(pack('chrono_70_30', sorted_eps[:cut], sorted_eps[cut:]))
    # split at first 2026-10-09 timestamp boundary already covered;
    # also early half of 10-06 vs late half of 10-06 + all 10-09 as sensitivity
    s0 = [ep for ep in sorted_eps if '20261006' in (ep.get('session') or '')]
    s1 = [ep for ep in sorted_eps if '20261009' in (ep.get('session') or '')]
    if s0 and s1:
        cuts.append(pack('all_10-06_then_10-09', s0, s1))

    primary_checks = []
    for c in cuts:
        sm, rm = c['seed_test'], c['revised_test']
        disc_ok = (
            sm.get('disc') is not None and rm.get('disc') is not None
            and rm['disc'] < sm['disc'] - 1e-12)
        agree_ok = (
            sm.get('label_agree_rate') is not None
            and rm.get('label_agree_rate') is not None
            and rm['label_agree_rate'] > sm['label_agree_rate'] + 1e-12)
        primary_checks.append({
            'cut': c['name'],
            'pass': bool(disc_ok or agree_ok),
            'disc_lower': disc_ok,
            'agree_higher': agree_ok,
            'seed_disc': sm.get('disc'),
            'rev_disc': rm.get('disc'),
            'seed_agree': [sm.get('label_agree'), sm.get('label_n')],
            'rev_agree': [rm.get('label_agree'), rm.get('label_n')],
        })

    report = {
        'experiment': 'E2chrono',
        'timestamps_support': True,
        'cuts': [
            {
                'name': c['name'],
                'n_train': c['n_train'],
                'n_test': c['n_test'],
                'seed_test': c['seed_test'],
                'revised_test': c['revised_test'],
                'note': c['note'],
            }
            for c in cuts
        ],
        'primary_checks': primary_checks,
    }

    lines = ['# Chronological freeze (optional Round-2)', '']
    lines.append('Frozen seed vs revised; score after cut. No re-evolve.')
    lines.append('')
    for c, p in zip(cuts, primary_checks):
        lines.append('## %s (train=%d test=%d) — **%s**' % (
            c['name'], c['n_train'], c['n_test'],
            'PASS' if p['pass'] else 'FAIL'))
        lines.append('')
        lines.append('| arm | n | disc | label_agree |')
        lines.append('|---|---:|---:|---:|')
        for label, m in (('seed_gate', c['seed_test']),
                         ('revised_frozen', c['revised_test'])):
            lines.append('| %s | %s | %s | %s/%s |' % (
                label, m.get('n'), _cell(m, 'disc'),
                m.get('label_agree'), m.get('label_n')))
        lines.append('')

    _write(out_dir, 'e2chrono_freeze', report, '\n'.join(lines))
    return report


def hunt_third_session(probe_path, out_dir, extra_paths=None):
    """Search probes for labeled sessions beyond the two known."""
    known_real = {'S-20261006-234611', 'S-20261009-103650'}
    smoke = {SMOKE_SESSION}
    paths = [probe_path] + list(extra_paths or [])
    findings = []
    for p in paths:
        if not p or not os.path.isfile(p):
            findings.append({'path': p, 'exists': False})
            continue
        sessions_all = Counter()
        labeled = Counter()
        unlabeled_speak = Counter()
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            sid = r.get('session') or '?'
            sessions_all[sid] += 1
            if r.get('kind') in ('spoke', 'silence'):
                if r.get('author_feedback'):
                    labeled[sid] += 1
                else:
                    unlabeled_speak[sid] += 1
        extra_labeled = {s: c for s, c in labeled.items()
                         if s not in known_real and s not in smoke}
        findings.append({
            'path': p,
            'exists': True,
            'labeled_sessions': dict(labeled),
            'extra_labeled_beyond_two': extra_labeled,
            'unlabeled_speak_silence_sessions': dict(unlabeled_speak),
            'all_sessions': dict(sessions_all),
        })

    any_extra = any(f.get('extra_labeled_beyond_two') for f in findings if f.get('exists'))
    report = {
        'experiment': 'E2c',
        'third_session_found': bool(any_extra),
        'known_real_sessions': sorted(known_real),
        'smoke_session': SMOKE_SESSION,
        'searched': findings,
    }

    if any_extra:
        lines = ['# E2c — Third session found', '', json.dumps(report, ensure_ascii=False, indent=2)]
        _write(out_dir, 'e2c_third_session', report, '\n'.join(lines))
        return report

    lines = []
    lines.append('# E2c — Need a third labeled session')
    lines.append('')
    lines.append('**No third labeled speak/silence session found** on laptop or box probes.')
    lines.append('')
    lines.append('## What was searched')
    lines.append('')
    for f in findings:
        if not f.get('exists'):
            lines.append('- `%s` — missing' % f.get('path'))
            continue
        lines.append('- `%s`' % f['path'])
        lines.append('  - labeled: %s' % f['labeled_sessions'])
        lines.append('  - unlabeled speak/silence rows by session: %s' %
                     f['unlabeled_speak_silence_sessions'])
    lines.append('')
    lines.append('## Known real labeled sessions (only two)')
    lines.append('')
    lines.append('- `S-20261006-234611`')
    lines.append('- `S-20261009-103650`')
    lines.append('- Smoke fixture excluded: `%s`' % SMOKE_SESSION)
    lines.append('')
    lines.append('Other sessions exist in the probe but **lack `author_feedback`** '
                 '(e.g. `S-20261006-231622`, `S-20261006-235323`, `S-20261008-*`, '
                 '`S-20261009-112609`). They cannot enter holdout tables.')
    lines.append('')
    lines.append('## Required log format for a third session')
    lines.append('')
    lines.append('Append rows to `probe.jsonl` (JSONL, UTF-8), one object per line, with:')
    lines.append('')
    lines.append('```json')
    lines.append('{')
    lines.append('  "ts": "2026-10-XXT..",')
    lines.append('  "session": "S-YYYYMMDD-HHMMSS",')
    lines.append('  "kind": "spoke" | "silence",')
    lines.append('  "event_id": "spk-... or sil-...",')
    lines.append('  "attn_state": "CODING|PLANNING|STUCK|...",')
    lines.append('  "attn_signals": { "pause_ms": ..., "mid_sentence": ..., "...": ... },')
    lines.append('  "author_feedback": "should_have_silent|should_have_spoken|silent_right|silent_wrong|silent_had_nothing",')
    lines.append('  "text_len": 123,')
    lines.append('  "text_head": "optional preview"')
    lines.append('}')
    lines.append('```')
    lines.append('')
    lines.append('Constraints:')
    lines.append('')
    lines.append('- `kind` must be `spoke` or `silence`.')
    lines.append('- `author_feedback` must be one of the five semantic labels above '
                 '(content-quality labels like 接受/太弱 are **not** speak outcomes).')
    lines.append('- Prefer a **new** `session` id not equal to the two known real sessions.')
    lines.append('- Include `attn_signals` when possible so the gate does not abstain.')
    lines.append('- After logging ≥8–12 labeled rows on a new day/session, re-run '
                 '`eval_round2.py` / E2b to strengthen or weaken the freeze-LOSO claim.')
    lines.append('')

    _write(out_dir, 'e2c_need_third_session', report, '\n'.join(lines))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', default=DEFAULT_PROBE)
    ap.add_argument('--out', default=os.path.join(HERE, 'results'))
    ap.add_argument('--shuffles', type=int, default=200)
    ap.add_argument('--extra-probe', action='append', default=[])
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    loaded = load_probe(args.probe)
    real = [ep for ep in loaded['episodes'] if not ep.get('smoke')]
    deduped, dropped = dedupe(real)
    seed, revised = _load_libs()

    print('deduped', len(deduped), 'dropped', dropped)

    e2b = run_e2b(seed, revised, deduped, args.out)
    e4b = run_e4b(seed, revised, deduped, args.out, n_shuffle=args.shuffles)
    chrono = run_chrono(seed, revised, deduped, args.out)

    # default extra search paths (box mirrors); harmless if missing on laptop
    extras = list(args.extra_probe)
    for p in (
        os.path.join(HERE, '..', '..', 'repro_repo_candidate', 'cowrite',
                     'Cowrite-test', 'app', 'v3', 'logs', 'probe.jsonl'),
        r'C:\Users\lenovo\AppData\Local\Temp\skillv_live\skillv_live_bundle\logs\probe.jsonl',
    ):
        if p not in extras:
            extras.append(p)
    e2c = hunt_third_session(args.probe, args.out, extras)

    index = {
        'round': 2,
        'e2b': {
            'n_pass': e2b['n_sessions_pass'],
            'n_sessions': e2b['n_sessions'],
            'all_pass': e2b['all_sessions_pass'],
            'per_session': [
                {'held': r['held_session'], 'pass': r['primary']['pass'],
                 'seed_disc': r['primary']['seed_disc'],
                 'rev_disc': r['primary']['rev_disc'],
                 'seed_agree': r['primary']['seed_label_agree'],
                 'rev_agree': r['primary']['rev_label_agree']}
                for r in e2b['per_session']
            ],
        },
        'e4b': {
            'observed_delta': e4b['observed_delta'],
            'p_two': e4b['empirical_p_two_sided'],
            'p_one': e4b['empirical_p_one_sided_le_obs'],
            'percentile': e4b['percentile_ascending'],
            'null_pass_p05': e4b['null_pass_extreme_favor_revised_p05'],
            'n_shuffle': e4b['n_shuffle'],
        },
        'chrono': chrono['primary_checks'],
        'e2c_third_found': e2c['third_session_found'],
    }
    path = os.path.join(args.out, 'round2_index.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('wrote', path)
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
