# -*- coding: utf-8 -*-
"""Live dots3 harness tests. No network. The caller is injected."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import eval_live_dots3 as live  # noqa: E402
from skillv.episodes import episode_from_signals  # noqa: E402


PROBE = os.path.join(
    ROOT, '..', 'Cowrite-test', 'app', 'v3', 'logs', 'probe.jsonl')

# Laptop headline (LAPTOP-32CD28QL, replay n=13). label_agree is hits/scored.
LAPTOP = {
    'rule': dict(speak=10, silence=2, abstain=1, called=10, agree='7/12', rate=0.769),
    'logged': dict(speak=12, silence=1, abstain=0, called=11, agree='8/13', rate=0.923),
    'seed_gate': dict(speak=10, silence=3, abstain=0, called=10, agree='8/13', rate=0.769),
    'revised_gate': dict(speak=7, silence=6, abstain=0, called=7, agree='9/13', rate=0.538),
}


def _planning(event_id, kind='spoke'):
    return episode_from_signals(
        dict(pause_ms=9000, at_sentence_end=True, chars_recent=48,
             doc_chars=3000, cursor_offset=3000, after_chars=0),
        kind=kind, attn_state='PLANNING', feedback='should_have_spoken',
        text_head='窗外的雨还在下。' + event_id, event_id=event_id, mode='P')


def _coding_silence(event_id):
    return episode_from_signals(
        dict(pause_ms=4000, mid_sentence=True, chars_recent=12,
             doc_chars=3000, cursor_offset=3000, after_chars=0),
        kind='silence', attn_state='CODING', feedback='silent_right',
        text_head='她停在半句' + event_id, event_id=event_id, mode='P')


class DecisionTests(unittest.TestCase):
    def test_replay_matches_laptop_speak_counts(self):
        if not os.path.exists(PROBE):
            self.skipTest('probe log not in tree')
        sample = live.load_slice(PROBE, 'replay')
        self.assertEqual(len(sample['episodes']), 13)
        seed, revised = live.libraries()
        calls = []

        def caller(system, user):
            calls.append(1)
            return {'ok': True, 'text': 'ok', 'error': '', 'latency_ms': 10, 'stop': 'end_turn'}

        ran = live.run_arms(
            sample['episodes'], seed, revised, caller,
            max_calls=12, model='dots3-note-prev',
            max_tokens=16, temperature=0.3, thinking='disabled', timeout=5)
        self.assertEqual(ran['unique_calls'], 12)
        self.assertEqual(len(calls), 12)
        by_id = {arm['id']: arm for arm in ran['arms']}
        for arm, expect in LAPTOP.items():
            got = by_id[arm]
            self.assertEqual(got['speak'], expect['speak'], arm)
            self.assertEqual(got['silence'], expect['silence'], arm)
            self.assertEqual(got['abstain'], expect['abstain'], arm)
            self.assertEqual(got['called'], expect['called'], arm)
            self.assertEqual(got['ok'], expect['called'], arm)
            self.assertEqual(got['fail'], 0, arm)
            self.assertEqual(got['label_agree'], expect['agree'], arm)
            self.assertEqual(got['speak_rate'], expect['rate'], arm)
        # Silence never calls. The one unsent speak is the logged arm past the cap.
        for row in ran['decisions']:
            if row['decision'] != 'speak':
                self.assertFalse(row['called'])
        skipped = [row for row in ran['decisions'] if row['cache'] == 'cap']
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]['arm'], 'logged')
        self.assertEqual(skipped[0]['event_id'], 'spk-1791513631141-008')

    def test_committed_report_is_the_laptop_table(self):
        path = os.path.join(ROOT, 'results', 'live_dots3_report.json')
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['provenance']['host'], 'LAPTOP-32CD28QL')
        self.assertEqual(payload['model'], 'dots3-note-prev')
        self.assertEqual(payload['cap']['unique_calls'], 12)
        self.assertEqual(payload['cap']['max_calls'], 12)
        self.assertEqual(payload['dots3_fail'], 0)
        self.assertEqual(payload['calls'], [])
        blob = json.dumps(payload)
        self.assertNotIn('"api_key"', blob)
        self.assertNotRegex(blob, r'sk-[A-Za-z0-9]{8,}')
        by_id = {arm['id']: arm for arm in payload['arms']}
        for arm, expect in LAPTOP.items():
            got = by_id[arm]
            self.assertEqual(got['n'], 13, arm)
            self.assertEqual(got['speak'], expect['speak'], arm)
            self.assertEqual(got['silence'], expect['silence'], arm)
            self.assertEqual(got['abstain'], expect['abstain'], arm)
            self.assertEqual(got['called'], expect['called'], arm)
            self.assertEqual(got['ok'], expect['called'], arm)
            self.assertEqual(got['fail'], 0, arm)
            self.assertEqual(got['label_agree'], expect['agree'], arm)
            self.assertEqual(got['speak_rate'], expect['rate'], arm)


class CallPathTests(unittest.TestCase):
    def test_silence_does_not_call_and_cache_is_shared(self):
        seed, revised = live.libraries()
        episodes = [_coding_silence('sil'), _planning('spk')]
        calls = []

        def caller(system, user):
            calls.append(user)
            return {'ok': True, 'text': '一句', 'error': '', 'latency_ms': 5, 'stop': 'end_turn'}

        ran = live.run_arms(
            episodes, seed, revised, caller, max_calls=8,
            model='dots3-note-prev', max_tokens=16, temperature=0.3,
            thinking='disabled', timeout=5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(ran['unique_calls'], 1)
        # Four arms speak on the planning row; one HTTP call serves all of them.
        planning_hits = [
            row for row in ran['decisions']
            if row['event_id'] == 'spk' and row['called']]
        self.assertEqual(len(planning_hits), 4)
        self.assertEqual(sum(1 for row in planning_hits if row['cache'] == 'miss'), 1)
        coding = [row for row in ran['decisions'] if row['event_id'] == 'sil']
        self.assertTrue(all(row['decision'] == 'silence' and not row['called'] for row in coding))

    def test_cap_skips_without_counting_a_failure(self):
        seed, revised = live.libraries()
        episodes = [_planning('a'), _planning('b')]
        calls = []

        def caller(system, user):
            calls.append(1)
            return {'ok': True, 'text': 'x', 'error': '', 'latency_ms': 3, 'stop': 'end_turn'}

        ran = live.run_arms(
            episodes, seed, revised, caller, max_calls=1,
            model='dots3-note-prev', max_tokens=16, temperature=0.3,
            thinking='disabled', timeout=5)
        self.assertEqual(len(calls), 1)
        rule = ran['arms'][0]
        self.assertEqual(rule['speak'], 2)
        self.assertEqual(rule['called'], 1)
        self.assertEqual(rule['ok'], 1)
        self.assertEqual(rule['fail'], 0)
        self.assertEqual(rule['skipped_cap'], 1)

    def test_preflight_failure_writes_the_error_and_exits_nonzero(self):
        def boom(cfg, timeout):
            return {
                'ok': False, 'url': 'http://note3-prev-api.askdiandian.com/v1/messages',
                'latency_ms': None, 'error': 'URLError: timed out',
                'error_type': 'URLError', 'status': 'unreachable',
            }

        with tempfile.TemporaryDirectory() as tmp:
            code = live.main(
                ['--probe', PROBE, '--out', tmp, '--slice', 'replay', '--max-calls', '12'],
                preflight_fn=boom,
                cfg={'provider': 'dots3', 'api': 'anthropic-messages',
                     'base_url': 'http://note3-prev-api.askdiandian.com',
                     'model': 'dots3-note-prev', 'api_key': 'should-not-leak',
                     'config_source': ''})
            self.assertEqual(code, 2)
            with open(os.path.join(tmp, 'live_dots3_report.json'), encoding='utf-8') as f:
                payload = json.load(f)
            with open(os.path.join(tmp, 'live_dots3_report.md'), encoding='utf-8') as f:
                text = f.read()
        self.assertEqual(payload['status'], 'unreachable')
        self.assertIn('timed out', payload['connectivity']['error'])
        self.assertIn('note3-prev-api.askdiandian.com/v1/messages', payload['endpoint'])
        self.assertIsNone(payload['dots3_ok'])
        self.assertEqual(payload['arms'], [])
        self.assertNotIn('should-not-leak', json.dumps(payload))
        self.assertIn('timed out', text)
        self.assertNotIn('should-not-leak', text)

    def test_call_error_redacts_the_key(self):
        seed, revised = live.libraries()
        secret = 'sk-live-secret-value'

        def caller(system, user):
            raise RuntimeError('upstream said %s' % secret)

        # run_arms expects a dict, so wrap the raise the way make_caller would.
        def safe_caller(system, user):
            try:
                return caller(system, user)
            except Exception as exc:
                message = '%s: %s' % (type(exc).__name__, exc)
                return {
                    'ok': False, 'text': '',
                    'error': live.redact(message, {'api_key': secret}),
                    'latency_ms': 1, 'stop': '',
                }

        ran = live.run_arms(
            [_planning('spk')], seed, revised, safe_caller, max_calls=4,
            model='dots3-note-prev', max_tokens=16, temperature=0.3,
            thinking='disabled', timeout=5)
        blob = json.dumps(ran, ensure_ascii=False)
        self.assertNotIn(secret, blob)
        self.assertIn('[redacted]', blob)
        self.assertEqual(ran['arms'][0]['fail'], 1)

    def test_deepseek_config_key_is_not_sent_to_dots3(self):
        env = {
            'DOTS3_API_KEY': '',
            'DOTS3_BASE_URL': '',
            'DOTS3_MODEL': '',
        }
        # No COWRITE_CONFIG, and there is no dots3 config.json in the tree.
        cfg = live.resolve_config(env)
        self.assertEqual(cfg['base_url'], live.DEFAULT_BASE)
        self.assertEqual(cfg['model'], 'dots3-note-prev')
        self.assertEqual(cfg['api'], 'anthropic-messages')
        self.assertEqual(cfg['api_key'], '')
        self.assertTrue(live._is_dots3({'provider': 'deepseek',
                                        'base_url': 'https://api.deepseek.com',
                                        'api_key': 'deepseek-key'}) is False)


if __name__ == '__main__':
    unittest.main()
