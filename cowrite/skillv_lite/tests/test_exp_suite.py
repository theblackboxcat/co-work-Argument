# -*- coding: utf-8 -*-
"""Experiment suite. No network. The preregistered bar is not refit here."""

import json
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import eval_exp_suite as exp  # noqa: E402
from skillv.contracts import snapshot_phi  # noqa: E402
from skillv.episodes import episode_from_signals  # noqa: E402


PROBE = os.path.join(ROOT, '..', 'Cowrite-test', 'app', 'v3', 'logs', 'probe.jsonl')


class BarTests(unittest.TestCase):
    def test_p_value_formula(self):
        self.assertEqual(exp._p_value(0.2, [0.4, 0.5, 0.6]), (1 + 0) / 4)
        self.assertEqual(exp._p_value(0.5, [0.4, 0.5, 0.6]), (1 + 2) / 4)

    def test_shuffle_keeps_the_label_multiset(self):
        episodes = [{'feedback': 'silent_right', 'event_id': 'a'},
                    {'feedback': 'should_have_spoken', 'event_id': 'b'},
                    {'feedback': 'silent_right', 'event_id': 'c'}]
        shuffled = exp._permute(episodes, random.Random(1))
        self.assertEqual(sorted(ep['feedback'] for ep in shuffled),
                         sorted(ep['feedback'] for ep in episodes))
        self.assertEqual([ep['event_id'] for ep in episodes], ['a', 'b', 'c'])

    def test_ablation_does_not_touch_phi(self):
        libs = exp.ablation_libraries()
        seed_phi = snapshot_phi(libs['seed'])
        self.assertTrue(libs['require_not_mid']['contracts'][3]['bounds']['require_not_mid'])
        self.assertFalse(libs['seed']['contracts'][3]['bounds']['require_not_mid'])
        self.assertEqual(libs['planning_ms']['shared_bounds']['planning_ms'], 1250)
        self.assertEqual(libs['seed']['shared_bounds']['planning_ms'], 2000)
        self.assertEqual(libs['both']['shared_bounds']['planning_ms'], 1250)
        for library in libs.values():
            self.assertEqual(snapshot_phi(library), seed_phi)

    def test_held_out_session_is_not_in_the_fit(self):
        if not os.path.exists(PROBE):
            self.skipTest('probe log not in tree')
        episodes = exp.load_deduped(PROBE)['episodes']
        e2 = exp.run_e2(episodes)
        self.assertGreaterEqual(len(e2['folds']), 2)
        for fold in e2['folds']:
            self.assertTrue(fold['phi_unchanged'])
            overlap = set(fold['held_ids']) & set(fold['train_ids'])
            self.assertEqual(overlap, set())
            if fold['countable']:
                self.assertGreaterEqual(fold['held_n'], exp.HELD_MIN)

    def test_e5_counts_only_exposed_speaks_that_revised_silences(self):
        episodes = exp.load_deduped(PROBE)['episodes'] if os.path.exists(PROBE) else []
        if not episodes:
            self.skipTest('probe log not in tree')
        e5 = exp.run_e5(episodes)
        for row in e5['rows']:
            self.assertFalse(row['revised'])
            self.assertTrue(row['rule'] is True or row['logged'] is True)
            self.assertTrue(row['in_W'])

    def test_suite_writes_the_prereg_and_no_key(self):
        if not os.path.exists(PROBE):
            self.skipTest('probe log not in tree')
        with tempfile.TemporaryDirectory() as tmp:
            report = exp.run_suite(PROBE, n_score=8, n_refit=3, out_dir=tmp)
            matrix = open(os.path.join(tmp, 'exp_matrix.md'), encoding='utf-8').read()
            manifest = json.load(open(os.path.join(tmp, 'e1_live_expand_manifest.json'),
                                       encoding='utf-8'))
            blob = open(os.path.join(tmp, 'exp_matrix.json'), encoding='utf-8').read()
        self.assertIn('Preregistered success bar', matrix)
        self.assertIn('phi stays locked', matrix)
        self.assertEqual(report['e4']['n_score_perms'], 8)
        self.assertEqual(report['e4']['n_refit_perms'], 3)
        self.assertIn(report['offline_verdict'], ('pass', 'system_fail', 'mixed'))
        self.assertEqual(manifest['verdict'], 'pending_laptop')
        self.assertNotIn('"api_key"', blob)
        self.assertNotIn('sk-', blob)
        self.assertFalse(report['phi_edited'])
        # Toy episode still builds. Guards the signal helper import.
        episode_from_signals(
            dict(pause_ms=1000, at_sentence_end=True, doc_chars=100, cursor_offset=100),
            kind='spoke', attn_state='PLANNING', feedback='should_have_spoken',
            event_id='toy')


if __name__ == '__main__':
    unittest.main()
