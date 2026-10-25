"""Transport seeks use the source timeline and cannot escape a remux offset."""
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]

class SiloUITransportPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory() as tmp:
            return run_function([ROOT/'source/core/SiloUITransportPolicy.brs'], name, list(args), root=Path(tmp))

    def test_preview_clamps_to_playable_offset_and_end(self):
        self.assertEqual(self.call('SiloUITransportSeek', 61000, 120000, 60000, -10000, 1), 60000)
        self.assertEqual(self.call('SiloUITransportSeek', 110000, 120000, 60000, 10000, 4), 119000)
        self.assertEqual(self.call('SiloUITransportSeek', 70000, 0, 60000, 10000, 1), 70000)

    def test_hold_accelerates_but_stays_bounded(self):
        self.assertEqual(self.call('SiloUITransportSeek', 10000, 1000000, 0, 10000, 1), 20000)
        self.assertEqual(self.call('SiloUITransportSeek', 10000, 1000000, 0, 10000, 8), 40000)
        self.assertEqual(self.call('SiloUITransportSeek', 10000, 1000000, 0, 10000, 100), 70000)

    def test_chapters_reject_invalid_timeline_and_keep_readable_titles(self):
        raw = [{'start_seconds': 0, 'end_seconds': 20, 'title': 'Opening'},
               {'start_seconds': -2, 'end_seconds': 10, 'title': 'Bad'},
               {'start_seconds': 20, 'end_seconds': 40, 'title': ''},
               {'start_seconds': 5, 'end_seconds': 20, 'title': 'Out of order'}]
        result = self.call('SiloUITransportChapters', raw, 60000)
        self.assertEqual(result, [{'positionMs': 0, 'title': 'Opening'}, {'positionMs': 20000, 'title': 'Chapter 2'}])

    def test_transport_time_preserves_seconds_and_zero(self):
        self.assertEqual(self.call('SiloUITransportTime', 0), '0:00')
        self.assertEqual(self.call('SiloUITransportTime', 3661000), '61:01')

    def test_playing_skip_supports_recap_and_credits_and_respects_never_intro(self):
        markers = [{'kind':'intro','startMs':0,'endMs':5000},
                   {'kind':'recap','startMs':5000,'endMs':10000},
                   {'kind':'credits','startMs':80000,'endMs':90000}]
        self.assertIsNone(self.call('SiloUITransportSkipCue', markers, 1000, 'never'))
        self.assertEqual(self.call('SiloUITransportSkipCue', markers, 7000, 'ask'), {'endMs':10000,'label':'skip recap'})
        self.assertEqual(self.call('SiloUITransportSkipCue', markers, 85000, 'ask'), {'endMs':90000,'label':'skip credits'})
        self.assertIsNone(self.call('SiloUITransportSkipCue', markers, 90000, 'ask'))
