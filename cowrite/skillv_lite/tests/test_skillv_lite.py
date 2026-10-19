# -*- coding: utf-8 -*-
"""Skill-V-lite unit tests. No network. No model."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skillv.contracts import PhiLocked, load, phi_digest, with_bounds  # noqa: E402
from skillv.decide import apply_gate, cascade, score_episodes  # noqa: E402
from skillv.episodes import episode_from_signals, from_probe_row, load_probe  # noqa: E402
from skillv.evolve import evolve  # noqa: E402
from skillv.filter import eval_node  # noqa: E402
from skillv.metrics import confusion, worse  # noqa: E402
from skillv.runtime import clear_cache, maybe_apply  # noqa: E402


def _attention():
    path = os.path.join(ROOT, '..', 'transplant_src', 'app', 'v3', 'attention.py')
    spec = importlib.util.spec_from_file_location('cowrite_attention', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ATTN_CASES = [
    ('刚写完一句，停 9 秒', 'PLANNING',
     dict(pause_ms=9000, at_sentence_end=True, chars_recent=48,
          doc_chars=3000, cursor_offset=3000, after_chars=0)),
    ('句中停 4 秒', 'CODING',
     dict(pause_ms=4000, mid_sentence=True, chars_recent=12,
          doc_chars=3000, cursor_offset=3000, after_chars=0)),
    ('停 40 秒没打字', 'STUCK',
     dict(pause_ms=40000, at_paragraph_end=True, chars_recent=0,
          doc_chars=3000, cursor_offset=2900, after_chars=100)),
    ('刚删了五处', 'POLISHING',
     dict(pause_ms=6000, at_sentence_end=True, edits_recent=5, chars_recent=3,
          doc_chars=3000, cursor_offset=2900, after_chars=100)),
    ('往上翻着看', 'REVIEWING',
     dict(pause_ms=12000, moved_up=True, chars_recent=0,
          doc_chars=3000, cursor_offset=400, after_chars=2600)),
    ('空文档', 'NOT_STARTED',
     dict(pause_ms=9000, doc_chars=6, cursor_offset=6, after_chars=0)),
    ('文末·停在句末', 'PLANNING',
     dict(pause_ms=9000, at_sentence_end=True, chars_recent=48,
          doc_chars=3000, cursor_offset=3000, after_chars=0)),
    ('文末·句子写一半', 'CODING',
     dict(pause_ms=9000, mid_sentence=True, chars_recent=48,
          doc_chars=3000, cursor_offset=3000, after_chars=0)),
    ('中间·停在句末', 'RECONTEXT',
     dict(pause_ms=9000, at_sentence_end=True, chars_recent=48, jumps_recent=1,
          doc_chars=3000, cursor_offset=900, after_chars=2100)),
    ('中间·段内后面还有字', 'RECONTEXT',
     dict(pause_ms=9000, at_sentence_end=True, chars_recent=48, jumps_recent=1,
          doc_chars=3000, cursor_offset=900, after_chars=2100,
          after_in_para=True)),
    ('中间·句子写一半', 'CODING',
     dict(pause_ms=9000, mid_sentence=True, chars_recent=48,
          doc_chars=3000, cursor_offset=900, after_chars=2100)),
    ('中间·跳两下没删改', 'RECONTEXT',
     dict(pause_ms=9000, at_sentence_end=True, chars_recent=48, jumps_recent=3,
          edits_recent=0, doc_chars=3000, cursor_offset=900, after_chars=2100)),
    ('跳两下 + 删过一处', 'POLISHING',
     dict(pause_ms=9000, at_sentence_end=True, chars_recent=48, jumps_recent=3,
          edits_recent=1, doc_chars=3000, cursor_offset=900, after_chars=2100)),
]


class ContractTests(unittest.TestCase):
    def test_seed_phi_lock(self):
        lib = load()
        self.assertEqual(len(lib['contracts']), 9)
        for c in lib['contracts']:
            self.assertEqual(lib['phi_lock'][c['id']], phi_digest(c['phi']))
            self.assertTrue(c['protected_phi'])

    def test_revision_cannot_rewrite_phi(self):
        lib = load()
        lib.pop('_source_path', None)
        broken = json.loads(json.dumps(lib))
        broken['contracts'][0]['phi'] = 'rewritten'
        from skillv.contracts import validate
        with self.assertRaises(PhiLocked):
            validate(broken)
        moved = with_bounds(
            lib, [('stuck_speak', 'require_not_mid', True)], reason='tighten')
        self.assertEqual(
            [c['phi'] for c in lib['contracts']],
            [c['phi'] for c in moved['contracts']])
        self.assertTrue(moved['contracts'][3]['bounds']['require_not_mid'])
        self.assertGreater(moved['library_version'], lib['library_version'])


class FilterTests(unittest.TestCase):
    def test_confident_mismatch_is_dropped(self):
        status = eval_node(
            {'field': 'mid_only', 'op': 'eq', 'value': True},
            {'mid_only': False}, {})
        self.assertEqual(status, 'fail')

    def test_missing_field_is_uncertain_not_dropped(self):
        status = eval_node(
            {'field': 'mid_only', 'op': 'eq', 'value': True},
            {}, {})
        self.assertEqual(status, 'uncertain')

    def test_higher_priority_uncertain_abstains(self):
        lib = load()
        lib.pop('_source_path', None)
        # No coordinates and no passage length: NOT_STARTED cannot be judged.
        ep = episode_from_signals(
            {'pause_ms': 9000, 'at_sentence_end': True, 'chars_recent': 10},
            text_len=None)
        ep['doc_chars'] = None
        ep['cursor_offset'] = None
        ep['has_doc_coords'] = False
        ep['text_len'] = None
        decision = cascade(lib, ep)
        self.assertTrue(decision['abstain'])
        self.assertIn('not_started_silence', decision['uncertain'])


class AttentionParityTests(unittest.TestCase):
    def test_seed_matches_attention_fixtures(self):
        attention = _attention()
        lib = load()
        lib.pop('_source_path', None)
        for name, want, sig in ATTN_CASES:
            st, info = attention.infer(sig)
            self.assertEqual(st, want, name)
            ep = episode_from_signals(sig, text_len=80)
            decision = cascade(lib, ep)
            self.assertFalse(decision['abstain'], name)
            self.assertEqual(decision['state'], want, name)
            self.assertEqual(bool(decision['speak']), bool(info['speak']), name)


class GateTests(unittest.TestCase):
    def test_gate_does_not_force_speech(self):
        decision = {'abstain': False, 'speak': True}
        self.assertFalse(apply_gate(False, decision))
        self.assertTrue(apply_gate(True, decision))

    def test_gate_withholds_when_contract_says_silence(self):
        decision = {'abstain': False, 'speak': False}
        self.assertFalse(apply_gate(True, decision))
        self.assertFalse(apply_gate(False, decision))

    def test_flag_off_is_identity(self):
        os.environ.pop('SKILLV_LITE', None)
        info = {'speak': True, 'state': 'PLANNING'}
        self.assertIs(maybe_apply(info, {'pause_ms': 1}), info)

    def test_flag_on_withholds_mid_sentence(self):
        os.environ['SKILLV_LITE'] = '1'
        os.environ['SKILLV_MODE'] = 'gate'
        os.environ['SKILLV_LIBRARY'] = 'seed'
        clear_cache()
        try:
            info = maybe_apply(
                {'speak': True, 'state': 'CODING'},
                {'pause_ms': 4000, 'mid_sentence': True, 'doc_chars': 3000,
                 'cursor_offset': 3000, 'after_chars': 0, 'chars_recent': 12},
                text_len=80)
            self.assertFalse(info['speak'])
            self.assertEqual(info['skillv']['selected'], 'coding_silence')
            self.assertTrue(info['skillv']['enabled'])
        finally:
            os.environ.pop('SKILLV_LITE', None)
            os.environ.pop('SKILLV_MODE', None)
            os.environ.pop('SKILLV_LIBRARY', None)
            clear_cache()


class EvidenceGateTests(unittest.TestCase):
    def test_worse_detects_disc_and_coverage(self):
        base = confusion([(True, True), (False, True)])
        better = confusion([(False, True), (False, True)])
        self.assertIsNone(worse(base, better))
        self.assertIsNotNone(worse(better, base))
        self.assertIn('coverage', worse(base, confusion([(False, True)])))

    def _stuck(self, feedback, session, ts):
        sig = dict(
            pause_ms=20000, mid_sentence=True, chars_recent=0, edits_recent=0,
            jumps_recent=0, doc_chars=3000, cursor_offset=1500, after_chars=80,
            after_in_para=True)
        return episode_from_signals(
            sig, text_len=90, feedback=feedback, kind='spoke',
            attn_state='STUCK', session=session, ts=ts,
            event_id='%s-%s' % (session, feedback))

    def test_gate_rejects_replay_regression(self):
        lib = load()
        lib.pop('_source_path', None)
        evolve_eps = [
            self._stuck('should_have_silent', 'S-20261006-234611', '2026-10-06'),
            self._stuck('should_have_silent', 'S-20261006-234611', '2026-10-06'),
            self._stuck('should_have_spoken', 'S-20261006-234611', '2026-10-06'),
        ]
        replay_eps = [
            self._stuck('should_have_spoken', 'S-20261009-103650', '2026-10-09'),
        ]
        # Give them distinct dedupe-visible text heads so they are real rows.
        for i, ep in enumerate(evolve_eps + replay_eps):
            ep['event_id'] = 'e-%d' % i
        run = evolve(lib, evolve_eps, replay_eps, mode='gate')
        self.assertEqual(run['accepted'], [])
        self.assertTrue(any(r['bound'] == 'require_not_mid' for r in run['rejected']))
        self.assertFalse(run['library']['contracts'][3]['bounds']['require_not_mid'])

    def test_gate_accepts_non_regressive_tighten(self):
        lib = load()
        lib.pop('_source_path', None)
        evolve_eps = [
            self._stuck('should_have_silent', 'S-20261006-234611', '2026-10-06'),
            self._stuck('should_have_silent', 'S-20261006-234611', '2026-10-06'),
        ]
        replay_eps = [
            self._stuck('should_have_silent', 'S-20261009-103650', '2026-10-09'),
        ]
        for i, ep in enumerate(evolve_eps + replay_eps):
            ep['event_id'] = 'ok-%d' % i
        before = score_episodes(lib, replay_eps, mode='gate')
        run = evolve(lib, evolve_eps, replay_eps, mode='gate')
        self.assertTrue(run['accepted'])
        self.assertEqual(run['accepted'][0]['bound'], 'require_not_mid')
        self.assertTrue(run['library']['contracts'][3]['bounds']['require_not_mid'])
        after = score_episodes(run['library'], replay_eps, mode='gate')
        self.assertIsNone(worse(before, after))
        self.assertLess(after['disc'], before['disc'])
        for before_c, after_c in zip(lib['contracts'], run['library']['contracts']):
            self.assertEqual(before_c['phi'], after_c['phi'])


class ProbeLoaderTests(unittest.TestCase):
    def test_smoke_and_unlabeled_are_marked(self):
        row = {
            'kind': 'silence', 'session': 'S-20261006-231325',
            'author_feedback': 'silent_right', 'attn_state': 'CODING',
            'preview': 'a0', 'attn_signals': None, 'event_id': 'x',
        }
        ep = from_probe_row(row)
        self.assertTrue(ep['smoke'])
        self.assertTrue(ep['signals_missing'])
        path = os.path.join(
            ROOT, '..', 'Cowrite-test', 'app', 'v3', 'logs', 'probe.jsonl')
        if not os.path.exists(path):
            self.skipTest('probe log not in tree')
        loaded = load_probe(path)
        self.assertTrue(any(ep['smoke'] for ep in loaded['episodes']))
        self.assertGreater(loaded['skipped_unlabeled'], 0)

    def test_harness_runs_on_real_log(self):
        path = os.path.join(
            ROOT, '..', 'Cowrite-test', 'app', 'v3', 'logs', 'probe.jsonl')
        if not os.path.exists(path):
            self.skipTest('probe log not in tree')
        # Importing eval_ab runs nothing until main().
        import eval_ab
        with tempfile.TemporaryDirectory() as tmp:
            code = eval_ab.main(['--probe', path, '--out', tmp])
            self.assertEqual(code, 0)
            with open(os.path.join(tmp, 'ab_report.json'), encoding='utf-8') as f:
                payload = json.load(f)
        self.assertGreater(payload['sample']['deduped'], 0)
        disc = payload['headline']['logged']['disc']
        self.assertGreaterEqual(disc, 0.0)
        self.assertLessEqual(disc, 1.0)
        self.assertTrue(payload['phi_ok'])
        self.assertIn('not used', payload['dots3'])


if __name__ == '__main__':
    unittest.main()
