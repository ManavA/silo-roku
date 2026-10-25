"""Actual Task request: source-container audio cannot authorize disabled Original.

Synthetic H264/EAC3 source and server DTOs; SDK/HTTP leaves only. This proves
request-bound conversion policy, not physical audio or hardware qualification.
"""
import unittest
from tests import test_silo_audio_projection as projection


class HLSAudioRouteProjection(unittest.TestCase):
    def test_mkv_only_surround_support_does_not_block_hls_stereo_projection(self):
        probe = '''if format.codec="eac3"
 return {result:(format.container="mkv" and format.chcnt=6 and format.passthru=0) or (format.container="ts" and format.chcnt=invalid and format.passthru=0)}
end if
return {result:format.codec="aac" and format.container="ts" and format.passthru=0 and (format.chcnt=invalid or format.chcnt=2)}'''
        helper = projection.AudioProjection()
        result = helper.start(probe=probe)
        bodies = helper.bodies(result)
        self.assertEqual(1, len(bodies), result['outcome'])
        body = bodies[0]
        deliveries = body['client_playback_context']['deliveries']
        self.assertFalse(deliveries['original_http']['enabled'])
        self.assertFalse(deliveries['original_http']['supported_on_device'])
        self.assertTrue(deliveries['hls']['enabled'])
        self.assertTrue(deliveries['hls']['supported_on_device'])
        self.assertEqual((['aac'], [], 2),
            (deliveries['hls']['audio_decode_codecs'],
             deliveries['hls']['audio_passthrough_codecs'],
             deliveries['hls'].get('max_channels')))
        self.assertEqual(('732','file:732:audio:0',0,'original'),
            tuple(body[key] for key in ('file_id','audio_track_id','audio_track_index','quality_preference')))
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertIn('sourceAudioProjection', result['outcome']['plan'])
        self.assertFalse(any(request['method']=='DELETE' for request in result['requests']))

    def test_exact_ts_surround_support_keeps_native_audio_with_original_disabled(self):
        probe = '''return {result:format.container="ts" and format.passthru=0 and (format.codec="eac3" or (format.codec="aac" and (format.chcnt=invalid or format.chcnt=2)))}'''
        helper = projection.AudioProjection()
        result = helper.start(probe=probe)
        body = helper.bodies(result)[0]
        deliveries = body['client_playback_context']['deliveries']
        self.assertFalse(deliveries['original_http']['enabled'])
        self.assertTrue(deliveries['hls']['enabled'])
        self.assertIn('eac3', deliveries['hls']['audio_decode_codecs'])
        self.assertNotIn('max_channels', deliveries['hls'])
        self.assertNotIn('sourceAudioProjection', result['outcome']['plan'])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
