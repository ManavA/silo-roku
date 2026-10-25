"""Explicit media header authentication stays separate from native HLS support."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function
from tests.test_silo_playback_policy import SCOPE, context, plan

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloPlaybackPolicy.brs'
ADAPTER = ROOT / 'source/adapters/SiloAdapter.brs'
MODE = 'api_header_v1'
HEADER = 'header_authenticated_media_v1'
NATIVE = ['native_hls_mpegts_v1', 'native_hls_separate_audio_v1', 'server_dv7_to_dv81_v1']


class SiloMediaAuthPolicyTests(unittest.TestCase):
    def call(self, function, *arguments):
        with tempfile.TemporaryDirectory() as directory:
            return run_function([POLICY, ADAPTER], function, list(arguments), root=Path(directory))

    def test_explicit_media_auth_context_survives_recovery_without_changing_legacy(self):
        legacy = plan()
        self.assertEqual(context(), self.call('SiloPlaybackContext', legacy, SCOPE))
        captured = copy.deepcopy(legacy)
        captured['siloPlayback']['mediaAuthMode'] = MODE
        retained = self.call('SiloPlaybackContext', captured, SCOPE)
        self.assertEqual(captured['siloPlayback'], retained)
        for failure in (None, 'decoder_failure'):
            params = {'qualityPreference': '720p', 'positionMs': 12500,
                      'replanRequestId': 'request-0001'}
            if failure is not None:
                params['failureClassification'] = failure
            result = self.call('SiloPlaybackReplanBody', retained, params, {}, {})
            self.assertTrue(result['ok'], result)
            self.assertEqual(MODE, result['context']['mediaAuthMode'])
        for value in (None, True, False, '', 'API_HEADER_V1', 'legacy', 1, {}, []):
            with self.subTest(value=value):
                bad = copy.deepcopy(captured)
                bad['siloPlayback']['mediaAuthMode'] = value
                self.assertIsNone(self.call('SiloPlaybackContext', bad, SCOPE))

    def test_header_feature_is_explicit_and_independent_of_hls_device_support(self):
        playback = {'deliveries': {'hls': {'enabled': True, 'supported_on_device': True,
                    'features': ['native_hls_playback_v1', *NATIVE]}}}
        self.assertEqual(NATIVE, self.call('SiloClientPlaybackFeatures', playback))
        self.assertEqual([*NATIVE, HEADER], self.call('SiloClientPlaybackFeatures', playback, MODE))
        playback['deliveries']['hls']['enabled'] = False
        self.assertEqual([], self.call('SiloClientPlaybackFeatures', playback))
        self.assertEqual([HEADER], self.call('SiloClientPlaybackFeatures', playback, MODE))
        playback['deliveries']['hls']['enabled'] = True
        playback['deliveries']['hls']['supported_on_device'] = False
        self.assertEqual([HEADER], self.call('SiloClientPlaybackFeatures', playback, MODE))
        for value in (True, False, '', 'API_HEADER_V1', 'authorized_media_origins_v1', 1, {}, []):
            with self.subTest(mode=value):
                self.assertIsNone(self.call('SiloClientPlaybackFeatures', playback, value))

    def test_advertised_features_keep_legacy_projection_even_with_explicit_mode(self):
        for requested in ([NATIVE[0], NATIVE[0], 'future_feature'],
                          ['native_hls_playback_v1', HEADER, 'authorized_media_origins_v1', NATIVE[0]],
                          [True, None, 1, NATIVE[0]]):
            with self.subTest(features=requested):
                playback = {'deliveries': {'hls': {'enabled': True, 'supported_on_device': True,
                            'features': requested}}}
                self.assertEqual([NATIVE[0]], self.call('SiloClientPlaybackFeatures', playback))
                self.assertEqual([NATIVE[0], HEADER], self.call('SiloClientPlaybackFeatures', playback, MODE))

    def test_start_opt_in_adds_only_top_level_feature_and_absence_is_legacy(self):
        params = json.loads((ROOT / 'tests/fixtures/silo/roku_start_input.json').read_text())
        session = {'profileId': 'p1'}
        legacy = self.call('SiloStartBody', session, params)
        self.assertTrue(legacy['ok'], legacy)
        self.assertEqual([], legacy['body']['client_features'])
        explicit = copy.deepcopy(params)
        explicit['mediaAuthMode'] = MODE
        explicit['clientPlaybackContext']['deliveries']['hls']['enabled'] = False
        result = self.call('SiloStartBody', session, explicit)
        self.assertTrue(result['ok'], result)
        self.assertEqual([HEADER], result['body']['client_features'])
        self.assertEqual(explicit['clientPlaybackContext'], result['body']['client_playback_context'])
        self.assertNotIn('mediaAuthMode', result['body'])
        for value in (None, True, False, '', 'API_HEADER_V1', 'other', 1, {}, []):
            with self.subTest(mode=value):
                bad = copy.deepcopy(params)
                bad['mediaAuthMode'] = value
                self.assertFalse(self.call('SiloStartBody', session, bad)['ok'])
        self.assertEqual({'installation_id': 'server-install', 'protocol_version': 3,
                          'client_features': [], 'file_id': 'f1', 'profile_id': 'p1',
                          'playback_attempt_id': 'attempt-1', 'quality_preference': 'original',
                          'subtitle_fidelity_preference': 'preserve', 'metered': False,
                          'client_capabilities': params['clientCapabilities'],
                          'client_playback_context': params['clientPlaybackContext'],
                          'progress_persistence': 'server', 'allow_alternate_versions': False,
                          'start_position': 12.5}, legacy['body'])

    def test_replan_wire_accepts_header_with_three_native_features_and_rejects_unproven_features(self):
        params = json.loads((ROOT / 'tests/fixtures/silo/roku_start_input.json').read_text())
        built = self.call('SiloPlaybackReplanBody', context(),
                          {'qualityPreference': '720p', 'positionMs': 12500,
                           'replanRequestId': 'request-0001'},
                          params['clientCapabilities'], params['clientPlaybackContext'])
        legacy = built['body']
        self.assertTrue(self.call('SiloReplanBodyValid', legacy))
        for requested in ([HEADER], [*NATIVE, HEADER], NATIVE):
            body = copy.deepcopy(legacy)
            body['client_features'] = requested
            self.assertTrue(self.call('SiloReplanBodyValid', body), requested)
        for requested in ([HEADER, HEADER], [NATIVE[0], NATIVE[0]],
                          [*NATIVE, HEADER, 'unknown'], ['authorized_media_origins_v1'],
                          ['unknown'], [None], [True], [1], HEADER):
            with self.subTest(features=requested):
                body = copy.deepcopy(legacy)
                body['client_features'] = requested
                self.assertFalse(self.call('SiloReplanBodyValid', body))
        self.assertEqual([], legacy['client_features'])

    def test_internal_track_change_can_preserve_only_the_captured_unlisted_quality(self):
        current = context()
        current.update(qualityPreference='1080p',
                       availableQualities=[{'label': 'original', 'preservesSource': True}])
        params = {'qualityPreference': '1080p', 'positionMs': 12500,
                  'replanRequestId': 'track-request-0001'}
        result = self.call('SiloPlaybackReplanBody', current, params, {}, {}, True)
        self.assertTrue(result['ok'], result)
        self.assertEqual(('track_change', '1080p'),
                         (result['body']['operation'], result['body']['quality_preference']))
        self.assertEqual(current['availableQualities'], result['context']['availableQualities'])
        self.assertFalse(self.call('SiloPlaybackReplanBody', current, params, {}, {})['ok'])
        for changed in ({**params, 'qualityPreference': '720p'},
                        {**params, 'qualityPreference': 'original'},
                        {**params, 'failureClassification': 'decoder_failure'},
                        {**params, 'failureClassification': None}):
            self.assertFalse(self.call('SiloPlaybackReplanBody', current, changed, {}, {}, True)['ok'])


if __name__ == '__main__':
    unittest.main()
