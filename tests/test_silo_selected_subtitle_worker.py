"""Public Task start/replan plans retain only non-rendering subtitle evidence."""
import copy
import json
import unittest
from pathlib import Path

from tests import test_silo_playback_task as start_helpers
from tests import test_silo_replan_task as replan_helpers
from tests.test_silo_playback_policy import TRACKS
from tests.test_silo_selected_subtitle_receipt import selected

ROOT = Path(__file__).resolve().parents[1]


def decision_with_selected(session='sess-1'):
    decision = json.loads((ROOT / 'tests/fixtures/silo/playback_decision_plan.json').read_text())
    selection = selected(file_id='f1', session=session)
    decision['playback_plan'].update(selection)
    decision['playback_plan']['selected_tracks']['audio'] = copy.deepcopy(TRACKS['audio'])
    return decision


class SelectedSubtitleWorkerTests(unittest.TestCase):
    def test_start_retains_sanitized_receipt_without_remote_artifact(self):
        worker = start_helpers.SiloPlaybackTaskTests()
        result = worker.run_start(decision=decision_with_selected())
        self.assertTrue(result['outcome']['ok'], result)
        plan = result['outcome']['plan']
        self.assertEqual('sidecar_pending', plan['selectedSubtitle']['kind'])
        self.assertFalse(plan['selectedSubtitle']['renderingReady'])
        self.assertNotIn('/api/v2/stream/sess-1/subtitles/1.vtt', json.dumps(plan))
        self.assertNotIn('privateArtifact', plan)

    def test_replan_refreshes_selected_receipt_and_preserves_off(self):
        worker = replan_helpers.SiloReplanTaskTests()
        params = worker.params()
        params['plan']['siloPlayback']['selectedTracks']['subtitle'] = {
            'id': 'file:f1:subtitle:1', 'index': 1}
        selected_decision = decision_with_selected('session-0001')
        result = worker.call(params=params, decision=selected_decision)
        self.assertTrue(result['outcome']['ok'], result)
        plan = result['outcome']['plan']
        self.assertEqual('sidecar_pending', plan['selectedSubtitle']['kind'])
        self.assertNotIn('/api/v2/stream/session-0001/subtitles/1.vtt', json.dumps(plan))

        off = worker.subtitle_decision()
        off_result = worker.call(params=worker.subtitle_params(), decision=off, subtitle_off=True)
        self.assertTrue(off_result['outcome']['ok'], off_result)
        self.assertEqual('off', off_result['outcome']['plan']['selectedSubtitle']['kind'])
        self.assertTrue(off_result['outcome']['plan']['siloPlayback']['subtitleOffRequired'])

    def test_long_server_label_does_not_block_playable_start_or_replan(self):
        worker = start_helpers.SiloPlaybackTaskTests()
        start = decision_with_selected()
        start['playback_plan']['subtitle']['inventory'][1]['label'] = 'x' * 129
        result = worker.run_start(decision=start)
        self.assertTrue(result['outcome']['ok'], result)
        self.assertEqual('unsupported', result['outcome']['plan']['selectedSubtitle']['kind'])
        self.assertNotIn('url', json.dumps(result['outcome']['plan']['selectedSubtitle']).lower())

        replan = decision_with_selected('session-0001')
        replan['playback_plan']['subtitle']['inventory'][1]['label'] = 'x' * 129
        replan_worker = replan_helpers.SiloReplanTaskTests()
        params = replan_worker.params()
        params['plan']['siloPlayback']['selectedTracks']['subtitle'] = {
            'id': 'file:f1:subtitle:1', 'index': 1}
        replan_result = replan_worker.call(params=params, decision=replan)
        self.assertTrue(replan_result['outcome']['ok'], replan_result)
        self.assertEqual('unsupported', replan_result['outcome']['plan']['selectedSubtitle']['kind'])

    def test_foreign_session_artifact_never_becomes_pending_or_blocks_video(self):
        decision = decision_with_selected()
        foreign = '/api/v2/stream/other-session/subtitles/1.vtt?file_id=99'
        decision['playback_plan']['subtitle']['artifact']['url'] = foreign
        decision['playback_plan']['subtitle']['inventory'][1]['url'] = foreign
        result = start_helpers.SiloPlaybackTaskTests().run_start(decision=decision)
        self.assertTrue(result['outcome']['ok'], result)
        self.assertEqual('unsupported', result['outcome']['plan']['selectedSubtitle']['kind'])
        self.assertNotIn(foreign, json.dumps(result['outcome']['plan']))


if __name__ == '__main__':
    unittest.main()
