"""Native HLS is accepted only after explicit, fresh recipe negotiation."""
import copy
import os
import json
from pathlib import Path
import unittest
from tools.brightscript import interpreter_available, run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / 'source/adapters/SiloAdapter.brs']
TS = 'native_hls_mpegts_v1'
SPLIT = 'native_hls_separate_audio_v1'
DV = 'server_dv7_to_dv81_v1'

class SiloNativeHLS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not interpreter_available():
            message = 'install runtime tests: npm ci --prefix tools/brightscript --ignore-scripts'
            if os.environ.get('SILO_REQUIRE_BRS') == '1':
                raise RuntimeError(message)
            raise unittest.SkipTest(message)

    def call(self, name, *args):
        return run_function(FILES, name, list(args))

    def plan(self, packaging='hls_separate_audio', dynamic_range='hdr10'):
        return {'delivery': 'server_remux_hls', 'effective_recipe': {
            'video_codec': 'hevc', 'audio_codec': 'eac3',
            'video_sample_entry': 'dvh1' if dynamic_range == 'dolby_vision' else 'hvc1',
            'dynamic_range': dynamic_range}, 'transformations': [
            {'name': packaging, 'executor': 'server', 'recipe_version': '1'}]}

    def test_old_server_has_no_native_format_opt_in(self):
        for features in (None, [], ['seek_reanchor_v1'], ['header_authenticated_media_v1']):
            self.assertEqual([], self.call('SiloNegotiatedNativeFeatures', features, True))

    def test_dv_requires_separate_audio_and_device_permission(self):
        self.assertEqual([TS], self.call('SiloNegotiatedNativeFeatures', [TS, DV], True))
        self.assertEqual([SPLIT], self.call('SiloNegotiatedNativeFeatures', [SPLIT, DV], False))
        self.assertEqual([TS, SPLIT, DV], self.call('SiloNegotiatedNativeFeatures', [DV, TS, SPLIT, SPLIT], True))

    def test_only_negotiated_known_hls_recipe_is_accepted(self):
        plan = self.plan()
        self.assertFalse(self.call('SiloNativeHLSPlanSupported', plan, []))
        self.assertTrue(self.call('SiloNativeHLSPlanSupported', plan, [SPLIT]))
        for transform in ({'name': 'hls_separate_audio', 'executor': 'client', 'recipe_version': '1'},
                          {'name': 'hls_separate_audio', 'executor': 'server', 'recipe_version': '2'},
                          {'name': 'unknown', 'executor': 'server', 'recipe_version': '1'}):
            changed = copy.deepcopy(plan)
            changed['transformations'].append(transform)
            self.assertFalse(self.call('SiloNativeHLSPlanSupported', changed, [SPLIT]))

    def test_ts_cannot_preserve_dv_or_enable_legacy_muxed_hls(self):
        self.assertTrue(self.call('SiloNativeHLSPlanSupported', self.plan('hls_mpegts'), [TS]))
        self.assertFalse(self.call('SiloNativeHLSPlanSupported', self.plan('hls_mpegts', 'dolby_vision'), [TS, SPLIT, DV]))
        plan = self.plan()
        plan['transformations'] = []
        self.assertFalse(self.call('SiloNativeHLSPlanSupported', plan, [TS, SPLIT]))

    def test_server_dv_conversion_requires_additional_opt_in(self):
        plan = self.plan(dynamic_range='dolby_vision')
        plan['transformations'].append({'name': 'server_dv7_to_dv81', 'executor': 'server', 'recipe_version': '1'})
        self.assertFalse(self.call('SiloNativeHLSPlanSupported', plan, [SPLIT]))
        self.assertTrue(self.call('SiloNativeHLSPlanSupported', plan, [SPLIT, DV]))

    def test_original_dv_guard_refuses_malformed_transform_inventory(self):
        plan = self.plan(dynamic_range='dolby_vision')
        plan.update(delivery='original_http', source=dict(dolby_vision_profile=5,
                    dolby_vision_level=6, dv_bl_compat_id=0), transformations=[])
        context={'deliveries':{'original_http':dict(enabled=True,supported_on_device=True,
            hdr_details=dict(dolby_vision_profiles=[5],dolby_vision_profile_levels=[
                dict(profile=5,max_level=9,bl_compatibility_ids=[0])]))}}
        self.assertTrue(self.call('SiloNativeDVReceiptSupported',plan,context))
        for transforms in (None, 'invalid', [None], [4], [{}]):
            with self.subTest(transforms=transforms):
                changed=copy.deepcopy(plan);changed['transformations']=transforms
                self.assertFalse(self.call('SiloNativeDVReceiptSupported',changed,context))
        plan.pop('transformations')
        self.assertFalse(self.call('SiloNativeDVReceiptSupported',plan,context))

    def test_unpatched_h264_sdr_transcode_requires_explicit_native_delivery(self):
        plan = {'delivery': 'server_transcode_hls', 'effective_recipe': {
            'video_codec': 'h264', 'audio_codec': 'aac', 'dynamic_range': 'sdr', 'width':1920, 'height':1080},
            'transformations': [
                {'name': 'video_to_h264', 'executor': 'server', 'recipe_version': '2'},
                {'name': 'audio_to_aac', 'executor': 'server', 'recipe_version': '2'},
                {'name': 'hdr_to_sdr_tonemap', 'executor': 'server', 'recipe_version': '1'}]}
        self.assertFalse(self.call('SiloNativeHLSPlanSupported', plan, []))
        self.assertTrue(self.call('SiloNativeHLSPlanSupported', plan, ['native_hls_playback_v1']))
        plan['effective_recipe']['video_codec'] = 'hevc'
        self.assertFalse(self.call('SiloNativeHLSPlanSupported', plan, ['native_hls_playback_v1']))

    def test_validated_timestamp_normalized_aac_v4_is_accepted_for_both_native_routes(self):
        remux = self.plan()
        remux['effective_recipe']['audio_codec']='aac'
        remux['transformations'].append({'name':'audio_to_aac','executor':'server','recipe_version':'4'})
        self.assertTrue(self.call('SiloNativeHLSPlanSupported',remux,[SPLIT]))
        transcode = {'delivery':'server_transcode_hls','effective_recipe':{'video_codec':'h264','audio_codec':'aac','dynamic_range':'sdr','width':1920,'height':1080},
                     'transformations':[{'name':'video_to_h264','executor':'server','recipe_version':'2'},
                                        {'name':'audio_to_aac','executor':'server','recipe_version':'4'}]}
        self.assertTrue(self.call('SiloNativeHLSPlanSupported',transcode,['native_hls_playback_v1']))

    def test_current_native_adaptation_exhaustion_is_a_terminal_not_malformed_plan(self):
        decision = {'protocol_version':3,'outcome':'adaptation_unavailable',
                    'terminal':{'reason':'adaptation_exhausted','message':'private server text','retryable':False}}
        value = self.call('SiloPlaybackPlan',decision,{'baseUrl':'https://silo.example'},[])
        self.assertEqual('playback_terminal',value['errorCode'])
        self.assertEqual('adaptation_exhausted',value['reason'])
        self.assertNotIn('private server text',json.dumps(value))
        self.assertTrue(self.call('DecodeSiloResponse','playback_start',json.dumps(decision),{})['ok'])

    def test_h264_fallback_does_not_accept_a_4k_encode(self):
        plan={'delivery':'server_transcode_hls','effective_recipe':{'video_codec':'h264','audio_codec':'aac','dynamic_range':'sdr','width':3840,'height':2160},
              'transformations':[{'name':'video_to_h264','executor':'server','recipe_version':'2'}, {'name':'audio_to_aac','executor':'server','recipe_version':'4'}]}
        self.assertFalse(self.call('SiloNativeHLSPlanSupported',plan,['native_hls_playback_v1']))
        self.assertTrue(self.call('SiloNativeH264Oversized',plan))

    def test_context_features_never_enable_unimplemented_authentication(self):
        context = {'deliveries': {'hls': {'enabled': True, 'supported_on_device': True,
                   'features': ['native_hls_playback_v1', SPLIT, DV, 'header_authenticated_media_v1']}}}
        self.assertEqual([SPLIT, DV], self.call('SiloClientNativeFeatures', context))
        context['deliveries']['hls']['enabled'] = False
        self.assertEqual([], self.call('SiloClientNativeFeatures', context))

    def test_negotiated_hls_plan_reaches_native_player_with_account_headers(self):
        plan = self.plan()
        plan.update(stream={'url': '/api/v2/playback/transcode/fixture/master.m3u8?st=synthetic',
                            'protocol': 'hls', 'container': 'hls', 'header_refresh': 'none'},
                    timeline={'player_start_seconds': 0, 'timeline_offset_seconds': 0, 'can_seek_anywhere': True})
        decision = {'protocol_version': 3, 'outcome': 'playable', 'playback_plan': plan}
        session = {'baseUrl': 'https://silo.example', 'accessToken': 'synthetic-access', 'profileId': 'qa'}
        result = self.call('SiloPlaybackPlan', decision, session, [SPLIT])
        self.assertTrue(result['ok'])
        self.assertEqual('hls', result['streamFormat'])
        self.assertEqual('Bearer synthetic-access', result['headers']['Authorization'])
        refused = self.call('SiloPlaybackPlan', decision, session)
        self.assertFalse(refused['ok'])

    def test_start_body_echoes_only_implemented_negotiated_features(self):
        params = json.loads((ROOT / 'tests/fixtures/silo/roku_start_input.json').read_text())
        params['clientPlaybackContext']['deliveries']['hls'] = {
            'enabled': True, 'supported_on_device': True,
            'features': ['native_hls_playback_v1', SPLIT, DV, 'header_authenticated_media_v1']}
        result = self.call('SiloStartBody', {'profileId': 'qa'}, params)
        self.assertTrue(result['ok'])
        self.assertEqual([SPLIT, DV], result['body']['client_features'])

if __name__ == '__main__':
    unittest.main()
