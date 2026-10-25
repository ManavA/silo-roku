"""Actual runJob resilience at optional DV identity SDK/HTTP boundaries.

Synthetic Ultra answers prove host policy only, not physical model playback.
No compatibility, Original, receipt or allocation policy is overridden.
"""
import json
import unittest
from unittest.mock import patch

from tests import test_silo_compat_continuation as task
from tests import test_silo_optional_sdk_resilience as optional


class OptionalDVIdentity(unittest.TestCase):
    def start(self, fault='', *, hdr10=False):
        helper = optional.OptionalSDKResilience()
        sdk = helper.sdk('').replace('4660X', '4850X')
        sdk = sdk.replace('return {Hdr10:false,Hdr10Plus:false,HLG:false,DolbyVision:false}', 'return {Hdr10:false,Hdr10Plus:false,HLG:false,DolbyVision:true}')
        if hdr10:
            sdk = sdk.replace('return {Hdr10:false,Hdr10Plus:false,HLG:false,DolbyVision:true}', 'return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}')
        if fault:
            signature = {'details': 'GetModelDetails:function() as Object', 'type': 'GetModelType:function() as String', 'os': 'GetOSVersion:function() as Object'}[fault]
            self.assertIn(signature, sdk)
            sdk = sdk.replace(signature, signature + '\n        if m.videoQueries<>invalid\n            m.videoQueries.Push({identityProbe:"' + fault + '"})\n            throw "synthetic-optional-identity"\n        end if', 1)
        actual_job = task.CompatContinuation.job

        def job(instance, **kwargs):
            kwargs['features'] = ['native_hls_separate_audio_v1', 'server_dv7_to_dv81_v1']
            replies = kwargs['http']

            def http(responses):
                replies(responses)
                cap = json.loads(responses[1]['body'])
                cap['deliveries'].append('server_remux_hls')
                responses[1]['body'] = json.dumps(cap)
            kwargs['http'] = http
            return actual_job(instance, **kwargs)

        with patch.object(helper, 'sdk', return_value=sdk), patch.object(task.CompatContinuation, 'job', job):
            return helper.start()

    def assert_playable_without_dv(self, result, fault, *, hdr10=False):
        queries = result['videoQueries']
        marker = next(i for i, q in enumerate(queries) if q.get('identityProbe') == fault)
        self.assertGreaterEqual(sum(q == dict(codec='hevc', profile='main 10', level='5.1') for q in queries[:marker]), 2, queries)
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertNotIn('compatContinuation', result['outcome'])
        posts = [r for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual(1, len(posts))
        self.assertFalse(any(r['method'] == 'DELETE' for r in result['requests']))
        body = json.loads(posts[0]['body'])
        self.assertEqual('732', body['file_id'])
        self.assertIn('h264', body['client_capabilities']['codecs_video'])
        self.assertEqual(hdr10, body['client_capabilities']['hdr'])
        hls = body['client_playback_context']['deliveries']['hls']
        self.assertTrue(hls['enabled'])
        self.assertEqual(['aac'], hls['audio_decode_codecs'])
        self.assertEqual(hdr10, hls['hdr_details']['hdr10'])
        self.assertEqual([], hls['hdr_details']['dolby_vision_profiles'])
        self.assertIn('native_hls_separate_audio_v1', hls['features'])
        self.assertNotIn('server_dv7_to_dv81_v1', hls['features'])
        self.assertEqual('hls', result['outcome']['plan']['streamFormat'])
        self.assertFalse(result['originalFlag'])
        self.assertFalse(result['p8Flag'])

    def test_model_details_failure_withholds_dv_without_losing_h264(self):
        self.assert_playable_without_dv(self.start('details'), 'details')

    def test_model_type_failure_withholds_dv_without_losing_h264(self):
        self.assert_playable_without_dv(self.start('type'), 'type')

    def test_os_version_failure_withholds_dv_without_losing_h264(self):
        self.assert_playable_without_dv(self.start('os'), 'os')

    def test_optional_identity_failure_preserves_independent_hdr10_evidence(self):
        self.assert_playable_without_dv(self.start('details', hdr10=True), 'details', hdr10=True)

    def test_healthy_identity_retains_exact_existing_dv_profile_bounds(self):
        result = self.start()
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        posts = [r for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual(1, len(posts))
        body = json.loads(posts[0]['body'])
        expected = dict(hdr10=False, hdr10_plus=False, hlg=False,
                        dolby_vision_profiles=[5],
                        dolby_vision_profile_levels=[dict(profile=5, max_level=9, bl_compatibility_ids=[0])])
        self.assertEqual(expected, body['client_capabilities']['hdr_details'])
        self.assertEqual(expected, body['client_playback_context']['deliveries']['hls']['hdr_details'])
        self.assertTrue(body['client_capabilities']['hdr'])
        self.assertEqual('732', body['file_id'])
        self.assertFalse(any('identityProbe' in q for q in result['videoQueries']))
