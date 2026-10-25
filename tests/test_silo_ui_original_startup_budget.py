"""The experimental original route has one absolute startup clock."""
import unittest
from pathlib import Path

from tools.brightscript import run_function
from tests.test_silo_ui_original_playback import descriptor, inventory


POLICY = Path(__file__).resolve().parents[1] / 'source/core/SiloUIOriginalPlaybackPolicy.brs'


class OriginalStartupBudget(unittest.TestCase):
    def create(self, experimental=True, proof=None):
        return run_function([POLICY], 'SiloUIOriginalCreate',
                            [descriptor() if proof is None else proof, 7, 3, 0, experimental])

    def reduce(self, state, now, kind='tick', generation=None, **values):
        return run_function([POLICY], 'SiloUIOriginalReduce',
                            [state, dict(kind=kind, token=7,
                                         generation=state['generation'] if generation is None else generation,
                                         nowMs=now, **values)])

    def test_experimental_budget_has_exact_sixty_second_boundary(self):
        state = self.create()
        self.assertEqual(0, state['startedMs'])
        for now in (43707, 59999):
            result = self.reduce(state, now, nativeState='buffering')
            self.assertIsNone(result['command'])
            state = result['state']
        result = self.reduce(state, 60000, nativeState='buffering')
        self.assertEqual({'kind':'recover','reason':'startup_timeout'}, result['command'])

    def test_shipping_budget_and_stall_remain_thirty_seconds(self):
        normal = run_function([POLICY], 'SiloUIOriginalCreate', [descriptor(), 7, 3, 0])
        self.assertIsNone(self.reduce(normal, 29999)['command'])
        self.assertEqual('startup_timeout', self.reduce(normal, 30000)['command']['reason'])
        state = self.reduce(self.create(), 1000, kind='inventory', inventory=inventory())['state']
        state = self.reduce(state, 2000, kind='observation', nativeState='playing',
                            audioTrack='native-random-9', audioFormat='ac3', positionMs=100)['state']
        state = self.reduce(state, 3000, kind='observation', nativeState='playing',
                            audioTrack='native-random-9', audioFormat='ac3', positionMs=1100)['state']
        self.assertEqual('verified_playing', state['phase'])
        self.assertIsNone(self.reduce(state, 32999, nativeState='buffering')['command'])
        self.assertEqual('stall_timeout', self.reduce(state, 33000, nativeState='buffering')['command']['reason'])

    def test_descriptor_cannot_inject_a_deadline(self):
        proof = descriptor()
        proof.update(startupTimeoutMs=999999, startupBudgetMs=999999, deadlineMs=999999)
        experimental = self.create(proof=proof)
        self.assertIsNone(self.reduce(experimental, 59999)['command'])
        self.assertEqual('startup_timeout', self.reduce(experimental, 60000)['command']['reason'])
        normal = run_function([POLICY], 'SiloUIOriginalCreate', [proof, 7, 3, 0])
        self.assertEqual('startup_timeout', self.reduce(normal, 30000)['command']['reason'])

    def test_restart_at_fifty_seconds_does_not_reset_original_clock(self):
        state = self.reduce(self.create(), 1000, kind='observation', nativeState='buffering')['state']
        restart = self.reduce(state, 50000, kind='observation', nativeState='finished')
        self.assertEqual({'kind':'restart'}, restart['command'])
        state = restart['state']
        self.assertEqual(0, state['startedMs'])
        state = self.reduce(state, 50001, kind='observation', nativeState='buffering')['state']
        state = self.reduce(state, 51000, kind='inventory', inventory=inventory(), freshInventory=True)['state']
        self.assertEqual(0, state['startedMs'])
        self.assertIsNone(self.reduce(state, 59999)['command'])
        self.assertEqual('startup_timeout', self.reduce(state, 60000)['command']['reason'])

    def test_cancel_at_deadline_wins_and_late_events_stay_inert(self):
        state = self.create()
        cancelled = self.reduce(state, 60000, kind='cancel')
        self.assertEqual('closed', cancelled['state']['phase'])
        self.assertIsNone(cancelled['command'])
        for kind, values in [('inventory', {'inventory':inventory()}),
                             ('observation', {'nativeState':'playing', 'audioTrack':'native-random-9',
                                              'audioFormat':'ac3', 'positionMs':1000}),
                             ('tick', {})]:
            with self.subTest(kind=kind):
                result = self.reduce(cancelled['state'], 60001, kind=kind, **values)
                self.assertEqual('closed', result['state']['phase'])
                self.assertIsNone(result['command'])

    def test_stale_or_invalid_events_cannot_select_or_recover(self):
        state = self.create()
        events = [dict(kind='inventory', token=6, generation=3, nowMs=60000, inventory=inventory()),
                  dict(kind='inventory', token=7, generation=4, nowMs=60000, inventory=inventory()),
                  dict(kind='inventory', token=7, generation=3, nowMs='invalid', inventory=inventory()),
                  dict(kind='tick', token=7, generation=3, nowMs=-1)]
        for event in events:
            with self.subTest(event=event):
                result = run_function([POLICY], 'SiloUIOriginalReduce', [state, event])
                self.assertEqual(state, result['state'])
                self.assertIsNone(result['command'])

    def test_early_failures_do_not_wait_for_sixty_seconds(self):
        state = self.reduce(self.create(), 1000, kind='observation', nativeState='buffering')['state']
        cases = [(dict(kind='observation', nativeState='error'), 'native_error'),
                 (dict(kind='observation', nativeState='buffering', outputFingerprint='changed'), 'output_changed'),
                 (dict(kind='inventory', inventory=inventory()+[dict(Track='extra',Format='ac3',Language='eng')]), 'audio_unverified')]
        for values, reason in cases:
            with self.subTest(reason=reason):
                kind = values.pop('kind')
                self.assertEqual(reason, self.reduce(state, 5000, kind=kind, **values)['command']['reason'])
        first = self.reduce(state, 5000, kind='observation', nativeState='finished')['state']
        self.assertEqual('restarting', first['phase'])
        first = self.reduce(first, 6000, kind='observation', nativeState='buffering')['state']
        second = self.reduce(first, 7000, kind='observation', nativeState='finished')
        self.assertEqual('startup_failure', second['command']['reason'])


if __name__ == '__main__':
    unittest.main()
