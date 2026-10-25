"""Native subtitle transport publication through actual runJob and SDK seams."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_silo_playback_task as playback
from tests import test_silo_selected_subtitle_prepare as prepare
from tests import test_silo_replan_task as replan
from tests.test_silo_selected_subtitle_receipt import selected
from tests.test_silo_selected_subtitle_worker import decision_with_selected

ROOT = Path(__file__).resolve().parents[1]
HEADER = 'header_authenticated_media_v1'


class SiloSubtitleTransportWorkerTests(unittest.TestCase):
    def job(self):
        session = playback.SiloPlaybackTaskTests().session()
        return {'provider': 'silo', 'action': 'playback_start', 'sourceId': session['sourceId'],
                'profileId': session['profileId'], 'generation': 7, 'requestId': 12,
                'params': {'itemId': 'fixture-item', 'fileId': 'f1', 'startPositionMs': 0,
                           'mediaAuthMode': 'api_header_v1'}}

    def run_job(self, *, raw=None, scenario=None):
        cap = json.loads((ROOT / 'tests/fixtures/silo/playback_capabilities.json').read_text())
        cap['installation_id'] = 'server-install'
        cap['features'].append(HEADER)
        if raw is None:
            raw = decision_with_selected()
        raw['playback_plan']['stream']['url'] = '/api/v2/stream/' + raw['session_id']
        responses = [{'statusCode': 200, 'body': json.dumps(cap)},
                     {'statusCode': 200, 'body': json.dumps(raw)}]
        return prepare.SelectedSubtitlePreparationTests().run_job(
            job_override=self.job(), responses_override=responses, scenario=scenario)

    def test_actual_worker_publishes_pending_native_transport_without_foreground_fetch(self):
        result = self.run_job()
        self.assertTrue(result['outcome']['ok'], result)
        plan = result['outcome']['plan']
        self.assertEqual('sidecar_pending', plan['selectedSubtitle']['kind'])
        self.assertFalse(plan['selectedSubtitle']['renderingReady'])
        transport = plan['subtitleTransport']
        self.assertEqual('api_header_v1', transport['authMode'])
        self.assertEqual((7, 12, 'f1', 1), tuple(transport['owner'][key] for key in
                                              ('generation', 'requestId', 'fileId', 'selectedOrdinal')))
        self.assertIn('/api/v2/stream/sess-1/subtitles/1.vtt?', transport['uri'])
        self.assertNotIn('position=', transport['uri'])
        self.assertNotIn('duration=', transport['uri'])
        self.assertNotIn('headers', transport)
        self.assertNotIn('token', json.dumps(transport).lower())
        self.assertNotIn('subtitleArtifact', plan)
        self.assertEqual([], result['downloads'])
        self.assertEqual([], result['files'])
        self.assertIsNone(result['agent'])

    def test_canceled_start_never_allocates_video_or_publishes_transport(self):
        wrapper = prepare.WRAPPER.replace('m.top={job:job,cancelled:false,result:invalid}',
                                          'm.top={job:job,cancelled:true,result:invalid}')
        self.assertNotEqual(prepare.WRAPPER, wrapper)
        with patch.object(prepare, 'WRAPPER', wrapper):
            result = self.run_job()
        self.assertFalse(result['outcome']['ok'], result)
        self.assertEqual('cancelled', result['outcome']['errorCode'])
        self.assertNotIn('plan', result['outcome'])
        self.assertTrue(all(request['method'] == 'GET' for request in result['requests']))
        self.assertEqual([], result['downloads'])
        self.assertEqual([], result['files'])
        self.assertIsNone(result['agent'])
        self.assertIsNone(result['binding'])

    def test_unusable_optional_caption_receipt_keeps_owned_video_without_io(self):
        raw = decision_with_selected()
        url = raw['playback_plan']['subtitle']['artifact']['url'] + '&token=caption-secret'
        raw['playback_plan']['subtitle']['artifact']['url'] = url
        raw['playback_plan']['subtitle']['inventory'][1]['url'] = url
        result = self.run_job(raw=raw)
        self.assertTrue(result['outcome']['ok'], result)
        plan = result['outcome']['plan']
        self.assertEqual('api_header_v1', plan['siloPlayback']['mediaAuthMode'])
        self.assertNotIn('subtitleTransport', plan)
        self.assertNotIn('subtitleArtifact', plan)
        self.assertFalse(plan['selectedSubtitle']['renderingReady'])
        self.assertNotIn('caption-secret', json.dumps(plan))
        self.assertEqual([], result['downloads'])
        self.assertEqual([], result['files'])

    def test_explicit_mode_srt_retains_existing_bounded_local_path(self):
        raw = decision_with_selected()
        artifact = raw['playback_plan']['subtitle']['artifact']
        artifact.update(format='srt', mime_type='application/x-subrip',
                        url='/api/v2/stream/sess-1/subtitles/1.srt?file_id=f1')
        raw['playback_plan']['subtitle']['inventory'][1]['url'] = artifact['url']
        result = self.run_job(raw=raw, scenario={'headers': {'Content-Type': 'application/x-subrip'},
            'body': '1\n00:00:00,000 --> 00:00:05,000\nFixture\n'})
        self.assertTrue(result['outcome']['ok'], result)
        plan = result['outcome']['plan']
        self.assertEqual('sidecar_ready', plan['selectedSubtitle']['kind'])
        self.assertNotIn('subtitleTransport', plan)
        self.assertTrue(plan['subtitleArtifact']['uri'].endswith('.srt'))
        self.assertEqual(1, len(result['downloads']))

    def test_replan_publishes_current_request_owner_without_fetching(self):
        params = replan.SiloReplanTaskTests().params()
        params['plan']['siloPlayback']['mediaAuthMode'] = 'api_header_v1'
        params['plan']['siloPlayback']['selectedTracks']['subtitle'] = {'id': 'file:f1:subtitle:1', 'index': 1}
        raw = decision_with_selected('session-0001')
        raw['session_id'] = 'session-0001'
        raw['playback_plan'].update(plan_id='plan-0002', plan_attempt_key='plan-key-0002')
        raw['playback_plan']['stream']['url'] = '/api/v2/stream/session-0001'
        session = {'baseUrl': 'https://silo.example', 'sourceId': 'silo:synthetic', 'profileId': 'owner',
                   'deviceId': 'fixture-device', 'accessToken': 'synthetic-access', 'profileToken': 'synthetic-profile'}
        job = {'provider': 'silo', 'action': 'playback_replan', 'sourceId': session['sourceId'],
               'profileId': session['profileId'], 'generation': 7, 'requestId': 13, 'params': params}
        cap = json.loads((ROOT / 'tests/fixtures/silo/playback_capabilities.json').read_text())
        cap.update(installation_id='install-0001', features=[HEADER])
        result = prepare.SelectedSubtitlePreparationTests().run_job(
            job_override=job, session_override=session, responses_override=[
                {'statusCode': 200, 'body': json.dumps(cap)}, {'statusCode': 200, 'body': json.dumps(raw)}])
        self.assertTrue(result['outcome']['ok'], result)
        transport = result['outcome']['plan']['subtitleTransport']
        self.assertEqual((13, 'plan-key-0002'), (transport['owner']['requestId'], transport['owner']['planAttemptKey']))
        self.assertEqual(transport['uri'], result['binding']['uri'])
        self.assertEqual([], result['downloads'])

    def test_automatic_audio_publishes_only_final_native_receipt_without_fetching(self):
        class CaptureScenario(playback.SiloPlaybackTaskTests):
            def worker(self, function, arguments, **kwargs):
                if function == 'RunSiloNativeBestStart':
                    return arguments
                return super().worker(function, arguments, **kwargs)
        session, params, responses, *_ = CaptureScenario().native_best_start(compatible_audio=True)
        params['mediaAuthMode'] = 'api_header_v1'
        selected_responses = []
        for response in responses:
            raw = json.loads(response['body'])
            if 'protocol_versions' in raw:
                raw['features'].append(HEADER)
            if 'playback_plan' in raw:
                receipt = selected(file_id='f2', session=raw['session_id'])
                raw['playback_plan']['subtitle'] = receipt['subtitle']
                raw['playback_plan']['selected_tracks']['subtitle'] = receipt['selected_tracks']['subtitle']
                raw['playback_plan']['stream']['url'] = '/api/v2/stream/' + raw['session_id']
                selected_responses.append((response, raw))
            response['body'] = json.dumps(raw)
        response, final = selected_responses[-1]
        subtitle = final['playback_plan']['subtitle']
        subtitle['artifact']['url'] += '&external_subtitle_key=' + 'a' * 64
        subtitle['inventory'][1]['url'] = subtitle['artifact']['url']
        response['body'] = json.dumps(final)
        job = self.job()
        job['params'] = params
        result = prepare.SelectedSubtitlePreparationTests().run_job(
            job_override=job, session_override=session, responses_override=responses)
        self.assertTrue(result['outcome']['ok'], result)
        plan = result['outcome']['plan']
        transport = plan['subtitleTransport']
        self.assertEqual('plan-key-0002', transport['owner']['planAttemptKey'])
        self.assertEqual(1, transport['owner']['selectedOrdinal'])
        self.assertIn('external_subtitle_key=' + 'a' * 64, transport['uri'])
        self.assertEqual('sidecar_pending', plan['selectedSubtitle']['kind'])
        self.assertFalse(plan['selectedSubtitle']['renderingReady'])
        self.assertEqual('api_header_v1', plan['autoVersionRequest']['mediaAuthMode'])
        self.assertEqual(transport['uri'], result['binding']['uri'])
        self.assertEqual([], result['downloads'])
        self.assertEqual([], result['files'])


if __name__ == '__main__':
    unittest.main()
