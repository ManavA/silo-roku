"""Benchmark reports must retain failures and compare like-for-like trials."""
import unittest
from tools.roku_benchmark import summarize, compare

class RokuBenchmarkTests(unittest.TestCase):
    def test_failed_trials_remain_visible_beside_successful_timings(self):
        result = summarize([5043, None, 3977, 4073])
        self.assertEqual(result, {'trials': 4, 'successes': 3, 'failures': 1,
                                 'median_ms': 4073, 'min_ms': 3977, 'max_ms': 5043})

    def test_comparison_reports_latency_and_failure_regressions(self):
        before = {'scenario': 'home_restart', 'conditions': 'same', 'samples_ms': [1000, 1200, 1100]}
        after = dict(before, samples_ms=[1500, None, 1700])
        result = compare(before, after)
        self.assertEqual(result['median_delta_ms'], 500)
        self.assertAlmostEqual(result['median_delta_percent'], 45.4545, places=3)
        self.assertEqual(result['failure_delta'], 1)
        with self.assertRaises(ValueError):
            compare(before, dict(after, conditions='different'))

    def test_total_failure_is_not_reported_as_zero_latency(self):
        result = summarize([None, None])
        self.assertIsNone(result['median_ms'])
        self.assertEqual(result['failures'], 2)
