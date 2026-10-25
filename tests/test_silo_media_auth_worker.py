"""Opted-in media auth through actual worker HTTP/session/device boundaries."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_silo_playback_task as playback
from tests import test_silo_replan_task as replan

ROOT = Path(__file__).resolve().parents[1]
MODE = 'api_header_v1'
HEADER = 'header_authenticated_media_v1'


def decision(session_id='sess-1'):
    raw = json.loads((ROOT / 'tests/fixtures/silo/playback_decision_plan.json').read_text())
    raw['session_id'] = session_id
    raw['playback_plan']['stream']['url'] = '/api/v2/stream/' + session_id
    raw['playback_plan']['selected_tracks'] = {'audio': {'id': 'file:f1:audio:0', 'index': 0}}
    return raw


def hls_decision(session_id='sess-1'):
    raw = decision(session_id)
    raw['playback_plan'].update(delivery='server_transcode_hls',
        effective_recipe={'video_codec': 'h264', 'audio_codec': 'aac', 'audio_channels': 2, 'dynamic_range': 'sdr', 'width': 1280, 'height': 720},
        transformations=[{'name': 'video_to_h264', 'executor': 'server', 'recipe_version': '2'},
                         {'name': 'audio_to_aac', 'executor': 'server', 'recipe_version': '4'}])
    raw['playback_plan']['stream'].update(protocol='hls', container='hls',
        url='/api/v2/playback/transcode/' + session_id + '/master.m3u8?file_id=f1')
    return raw


class SiloMediaAuthWorkerTests(unittest.TestCase):
    def start(self, **changes):
        options = {'params': {'itemId': 'fixture-item', 'fileId': 'f1', 'startPositionMs': 0,
                              'mediaAuthMode': MODE},
                   'decision': decision(), 'capability_features': [HEADER]}
        options.update(changes)
        return playback.SiloPlaybackTaskTests().run_start(**options)

    def test_fresh_start_opts_in_only_explicitly_and_retains_transport_mode(self):
        result = self.start()
        self.assertTrue(result['outcome']['ok'], result)
        request = result['requests'][1]
        self.assertEqual([HEADER], json.loads(request['body'])['client_features'])
        self.assertEqual(MODE, result['outcome']['plan']['siloPlayback']['mediaAuthMode'])
        self.assertEqual('synthetic-profile-token', request['headers']['X-Profile-Token'])
        self.assertEqual('fixture-owner', request['headers']['X-Profile-Id'])

    def test_start_media_headers_require_owned_api_route_and_credential_free_query(self):
        for url in ('/api/v2/stream/sess-1',
                    'https://silo.example:443/api/v2/stream/sess-1?file_id=f1&seek=12.5'):
            with self.subTest(url=url):
                raw = decision()
                raw['playback_plan']['stream']['url'] = url
                result = self.start(decision=raw)
                self.assertTrue(result['outcome']['ok'], result)
                self.assertEqual({'Authorization': 'Bearer synthetic-access-token'},
                                 result['outcome']['plan']['headers'])
        for url in ('https://foreign.example/api/v2/stream/sess-1',
                    'https://silo.example:444/api/v2/stream/sess-1',
                    'https://user:secret@silo.example/api/v2/stream/sess-1',
                    '/api/v2/stream/other', '/api/v2/other/sess-1',
                    '/api/v2/stream/sess-1?st=synthetic',
                    '/api/v2/stream/sess-1?%73t=synthetic',
                    '/api/v2/stream/sess-1?file_id=other',
                    '/api/v2/stream/sess-1?seek=604801',
                    '/api/v2/stream/sess-1?seek=NaN',
                    '/api/v2/stream/sess-1?seek=1&seek=2',
                    '/api/v2/stream/sess-1?file_id=f1&&seek=1',
                    '/api/v2/stream/sess-1?file_id=f1&',
                    '/api/v2/stream/sess-1#private',
                    '/api/v2/stream/sess-1\t'):
            with self.subTest(rejected=url):
                raw = decision()
                raw['playback_plan']['stream']['url'] = url
                result = self.start(decision=raw)
                self.assertFalse(result['outcome']['ok'], result)
                self.assertEqual(['GET', 'POST', 'DELETE'], [r['method'] for r in result['requests']])
                self.assertNotIn('headers', result['outcome'].get('plan', {}))

    def test_start_refuses_invalid_mode_or_missing_capability_without_start_mutation(self):
        for value in (None, True, False, '', 'other', 'API_HEADER_V1', 1, {}, []):
            with self.subTest(mode=value):
                result = self.start(params={'itemId': 'fixture-item', 'fileId': 'f1', 'mediaAuthMode': value})
                self.assertFalse(result['outcome']['ok'], result)
                self.assertEqual([], result['requests'])
        result = self.start(capability_features=[])
        self.assertFalse(result['outcome']['ok'], result)
        self.assertEqual(['GET'], [request['method'] for request in result['requests']])
        legacy = self.start(params={'itemId': 'fixture-item', 'fileId': 'f1'})
        self.assertTrue(legacy['outcome']['ok'], legacy)
        self.assertEqual([], json.loads(legacy['requests'][1]['body'])['client_features'])
        self.assertNotIn('mediaAuthMode', legacy['outcome']['plan']['siloPlayback'])
        self.assertEqual('synthetic-profile-token', legacy['outcome']['plan']['headers']['X-Profile-Token'])

    def test_opted_in_start_requires_retained_context_and_legacy_does_not(self):
        raw = decision()
        del raw['playback_plan']['available_qualities']
        refused = self.start(decision=raw)
        self.assertFalse(refused['outcome']['ok'], refused)
        self.assertEqual(['GET', 'POST', 'DELETE'], [r['method'] for r in refused['requests']])
        legacy = self.start(decision=raw, params={'itemId': 'fixture-item', 'fileId': 'f1'})
        self.assertTrue(legacy['outcome']['ok'], legacy)
        self.assertNotIn('siloPlayback', legacy['outcome']['plan'])

    def test_start_rejects_raw_token_controls_instead_of_trimming_them_into_media_headers(self):
        session = playback.SiloPlaybackTaskTests().session()

        class WithSession(playback.SiloPlaybackTaskTests):
            def session(self):
                return session

        for token in ('synthetic-access-token\t', ' synthetic-access-token'):
            session['accessToken'] = token
            result = WithSession().run_start(
                params={'itemId': 'fixture-item', 'fileId': 'f1', 'mediaAuthMode': MODE},
                decision=decision(), capability_features=[HEADER])
            self.assertFalse(result['outcome']['ok'], result)
            self.assertEqual(['GET', 'POST', 'DELETE'], [r['method'] for r in result['requests']])

    def test_replan_uses_captured_mode_and_preserves_control_headers(self):
        worker = replan.SiloReplanTaskTests()
        params = worker.params()
        params['plan']['siloPlayback']['mediaAuthMode'] = MODE
        result = worker.call(params=params, decision=decision('session-0001'), capability_features=[HEADER])
        self.assertTrue(result['outcome']['ok'], result)
        request = result['requests'][1]
        self.assertEqual([HEADER], json.loads(request['body'])['client_features'])
        self.assertEqual(MODE, result['outcome']['plan']['siloPlayback']['mediaAuthMode'])
        self.assertEqual({'Authorization': 'Bearer synthetic-access'}, result['outcome']['plan']['headers'])
        self.assertEqual('synthetic-profile', request['headers']['X-Profile-Token'])
        self.assertEqual('owner', request['headers']['X-Profile-Id'])

    def test_replan_capability_loss_preserves_old_lease_and_legacy_never_upgrades(self):
        worker = replan.SiloReplanTaskTests()
        params = worker.params()
        params['plan']['siloPlayback']['mediaAuthMode'] = MODE
        refused = worker.call(params=params, decision=decision('session-0001'), capability_features=[])
        self.assertFalse(refused['outcome']['ok'], refused)
        self.assertEqual(['GET'], [r['method'] for r in refused['requests']])
        legacy = worker.call(decision=decision('session-0001'), capability_features=[HEADER])
        self.assertTrue(legacy['outcome']['ok'], legacy)
        self.assertEqual([], json.loads(legacy['requests'][1]['body'])['client_features'])
        self.assertNotIn('mediaAuthMode', legacy['outcome']['plan']['siloPlayback'])
        self.assertEqual('synthetic-profile', legacy['outcome']['plan']['headers']['X-Profile-Token'])

    def test_replan_rejects_foreign_or_signed_media_without_deleting_current_lease(self):
        worker = replan.SiloReplanTaskTests()
        params = worker.params()
        params['plan']['siloPlayback']['mediaAuthMode'] = MODE
        for url in ('https://foreign.example/api/v2/stream/session-0001',
                    '/api/v2/stream/session-0001?st=synthetic',
                    '/api/v2/stream/other', '/api/v2/stream/session-0001\t'):
            with self.subTest(url=url):
                raw = decision('session-0001')
                raw['playback_plan']['stream']['url'] = url
                result = worker.call(params=params, decision=raw, capability_features=[HEADER])
                self.assertFalse(result['outcome']['ok'], result)
                self.assertTrue(result['outcome']['leaseUncertain'])
                self.assertEqual(MODE, result['outcome']['controlReceipt']['mediaAuthMode'])
                self.assertEqual(['GET', 'POST'], [r['method'] for r in result['requests']])

    def test_mode_survives_failure_track_off_and_user_audio_replans(self):
        worker = replan.SiloReplanTaskTests()
        failure = worker.params()
        failure['plan']['siloPlayback']['mediaAuthMode'] = MODE
        failure['failureClassification'] = 'decoder_failure'
        off = worker.subtitle_params()
        off['plan']['siloPlayback']['mediaAuthMode'] = MODE
        off_decision = decision('session-0001')
        off_decision['playback_plan']['subtitle'] = {'mode': 'off', 'inventory': []}
        audio = worker.params()
        audio['plan']['siloPlayback']['mediaAuthMode'] = MODE
        cases = [dict(params=failure, decision=decision('session-0001')),
                 dict(params=off, decision=off_decision, subtitle_off=True),
                 dict(params=audio, decision=hls_decision('session-0001'), audio_index=1)]
        for options in cases:
            with self.subTest(options=list(options)):
                result = worker.call(capability_features=[HEADER], **options)
                self.assertTrue(result['outcome']['ok'], result)
                posted = [r for r in result['requests'] if r['method'] == 'POST']
                self.assertEqual([HEADER], json.loads(posted[-1]['body'])['client_features'])
                self.assertEqual(MODE, result['outcome']['plan']['siloPlayback']['mediaAuthMode'])
                self.assertEqual({'Authorization': 'Bearer synthetic-access'}, result['outcome']['plan']['headers'])

    def test_header_mode_admits_owned_hls_master_without_claiming_native_qualification(self):
        raw = hls_decision()
        result = self.start(decision=raw, capability_deliveries=['server_transcode_hls'])
        self.assertTrue(result['outcome']['ok'], result)
        self.assertEqual({'Authorization': 'Bearer synthetic-access-token'}, result['outcome']['plan']['headers'])
        for url in ('/api/v2/playback/transcode/other/master.m3u8',
                    '/api/v2/playback/transcode/sess-1/master.m3u8?seek=1'):
            raw['playback_plan']['stream']['url'] = url
            self.assertFalse(self.start(decision=raw, capability_deliveries=['server_transcode_hls'])['outcome']['ok'])

    def test_automatic_compatible_audio_keeps_mode_in_start_and_replacement(self):
        class CaptureScenario(playback.SiloPlaybackTaskTests):
            def worker(self, function, arguments, **kwargs):
                if function == 'RunSiloNativeBestStart':
                    return arguments
                return super().worker(function, arguments, **kwargs)
        arguments = CaptureScenario().native_best_start(compatible_audio=True)
        arguments[1]['mediaAuthMode'] = MODE
        for response in arguments[2]:
            raw = json.loads(response['body'])
            if 'protocol_versions' in raw:
                raw['features'].append(HEADER)
            if 'playback_plan' in raw:
                raw['playback_plan']['stream']['url'] = '/api/v2/stream/' + raw['session_id']
            response['body'] = json.dumps(raw)
        result = playback.SiloPlaybackTaskTests().worker('RunSiloNativeBestStart', arguments)
        self.assertTrue(result['outcome']['ok'], result)
        posted = [json.loads(r['body']) for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual(2, len(posted))
        for body in posted:
            self.assertIn(HEADER, body['client_features'])
            self.assertNotIn('authorized_media_origins_v1', body['client_features'])
        self.assertEqual(MODE, result['outcome']['plan']['siloPlayback']['mediaAuthMode'])
        self.assertEqual({'Authorization': 'Bearer synthetic-access-token'}, result['outcome']['plan']['headers'])

    def test_provider_off_keeps_current_quality_when_server_menu_omits_equivalent_rung(self):
        worker = replan.SiloReplanTaskTests()
        params = worker.subtitle_params()
        params['plan']['siloPlayback'].update(mediaAuthMode=MODE, qualityPreference='1080p',
            availableQualities=[{'label': 'original', 'preservesSource': True}])
        raw = decision('session-0001')
        raw['playback_plan']['subtitle'] = {'mode': 'off', 'inventory': []}
        result = worker.call(params=params, decision=raw, subtitle_off=True, capability_features=[HEADER])
        self.assertTrue(result['outcome']['ok'], result)
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual(('track_change', '1080p'), (body['operation'], body['quality_preference']))
        self.assertNotIn('subtitle', body['selected_tracks'])
        self.assertEqual('1080p', result['outcome']['plan']['siloPlayback']['qualityPreference'])

    def test_automatic_audio_preserves_requested_quality_omitted_from_returned_menu(self):
        class CaptureScenario(playback.SiloPlaybackTaskTests):
            def worker(self, function, arguments, **kwargs):
                if function == 'RunSiloNativeBestStart':
                    return arguments
                return super().worker(function, arguments, **kwargs)
        arguments = CaptureScenario().native_best_start(compatible_audio=True)
        arguments[1].update(mediaAuthMode=MODE, qualityPreference='1080p', qualityExplicit=True)
        for response in arguments[2]:
            raw = json.loads(response['body'])
            if 'protocol_versions' in raw:
                raw['features'].append(HEADER)
            if 'playback_plan' in raw:
                raw['playback_plan']['available_qualities'] = [{'label': 'original', 'preserves_source': True}]
                raw['playback_plan']['stream']['url'] = '/api/v2/stream/' + raw['session_id']
            response['body'] = json.dumps(raw)
        result = playback.SiloPlaybackTaskTests().worker('RunSiloNativeBestStart', arguments)
        self.assertTrue(result['outcome']['ok'], result)
        posted = [json.loads(r['body']) for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual(['1080p', '1080p'], [body['quality_preference'] for body in posted])
        self.assertEqual('track_change', posted[-1]['operation'])
        self.assertEqual(1, posted[-1]['selected_tracks']['audio']['index'])
        self.assertEqual([{'label': 'original', 'preservesSource': True}],
                         result['outcome']['plan']['siloPlayback']['availableQualities'])

    def test_user_audio_keeps_current_quality_when_server_menu_omits_equivalent_rung(self):
        worker = replan.SiloReplanTaskTests()
        params = worker.params()
        params['plan']['siloPlayback'].update(mediaAuthMode=MODE, qualityPreference='1080p',
            availableQualities=[{'label': 'original', 'preservesSource': True}])
        result = worker.call(params=params, decision=hls_decision('session-0001'), audio_index=1,
                             capability_features=[HEADER])
        self.assertTrue(result['outcome']['ok'], result)
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual(('track_change', '1080p'), (body['operation'], body['quality_preference']))
        self.assertEqual(1, body['selected_tracks']['audio']['index'])

    def test_unlisted_quality_requires_explicit_choice_or_exact_retained_failure_intent(self):
        worker = replan.SiloReplanTaskTests()
        for failure in (False, True):
            params = worker.params()
            params['plan']['siloPlayback'].update(mediaAuthMode=MODE, qualityPreference='1080p',
                availableQualities=[{'label': 'original', 'preservesSource': True}])
            params['qualityPreference'] = '1080p'
            if failure:
                params['failureClassification'] = 'decoder_failure'
                params['qualityPreference'] = '720p'  # Unlisted quality changes remain forbidden.
            result = worker.call(params=params, decision=decision('session-0001'), capability_features=[HEADER])
            self.assertFalse(result['outcome']['ok'], result)
            self.assertEqual('invalid_request', result['outcome']['errorCode'])
            self.assertEqual([], result['requests'])

    def test_internal_audio_detail_never_authorizes_a_failure_or_null_failure_request(self):
        boundary = '''
function RunAudioDetailFailure(session as Object, params as Object, scope as Object, raw as String) as Object
 m.requests=[]:m.timeouts=[]:m.responses=[]:m.fixtureRevision=0:m.fixtureSession=session
 decoded=DecodeSiloResponse("detail",raw,{sourceId:scope.sourceId,itemId:params.plan.itemId})
 detail=ScopeCatalogData(decoded.data,scope.sourceId)
 outcome=TaskReplanSiloPlayback(session,params,scope,0,detail)
 return {outcome:outcome,requests:m.requests}
end function
'''
        worker = replan.SiloReplanTaskTests()
        session = {'baseUrl': 'https://silo.example', 'sourceId': 'silo:synthetic', 'profileId': 'owner',
                   'deviceId': 'fixture-device', 'accessToken': 'synthetic-access'}
        raw = (ROOT / 'tests/fixtures/silo/catalog_item_detail_movie.json').read_text()
        for failure in ('decoder_failure', None):
            params = worker.params()
            params.update(qualityPreference='original', failureClassification=failure)
            with patch.object(playback, 'BOUNDARIES', playback.BOUNDARIES + boundary):
                result = playback.SiloPlaybackTaskTests().worker('RunAudioDetailFailure',
                    [session, params, replan.values.SCOPE, raw])
            self.assertFalse(result['outcome']['ok'], result)
            self.assertEqual('invalid_request', result['outcome']['errorCode'])
            self.assertEqual([], result['requests'])


if __name__ == '__main__':
    unittest.main()
