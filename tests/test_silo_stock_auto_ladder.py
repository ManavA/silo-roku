"""Host replay of two stock responses; no server calls or Roku qualification."""
import json
import unittest
from tests import test_silo_compat_continuation as continuation
from tests import test_silo_cross_profile_negotiation as profile
from tests.test_silo_playback_task import FIXTURES


class StockAutoLadder(unittest.TestCase):
    def stock_job(self, host_http=None):
        fixture = json.loads((FIXTURES / 'stock_auto_1080_ladder.json').read_text())

        class Stock(continuation.CompatContinuation):
            def fixture(self):
                session, _, _ = super().fixture()
                session.pop('profileToken', None)
                return session, fixture['detail'], fixture['fallback_response']['decision']

        sdk = dict(profile.STB, **profile.AAC_ONLY)
        sdk['DolbyVision:true'] = 'DolbyVision:false'
        sdk['if m.rejectMain10 = true and format.profile = "main 10" then return {result:false}\n        return {result:true}'] = '''if format.codec="mpeg4 avc" or format.codec="h264"
            if format.profile<>invalid and format.profile<>"main" and format.profile<>"high" then return {result:false}
            if format.level<>invalid and format.level<>"3.0" and format.level<>"3.1" and format.level<>"3.2" and format.level<>"4.0" and format.level<>"4.1" and format.level<>"4.2" then return {result:false}
            return {result:true}
        end if
        if format.codec="hevc"
            if format.profile<>invalid and format.profile<>"main 10" then return {result:false}
            if format.level<>invalid and format.level<>"4.0" and format.level<>"4.1" and format.level<>"5.0" and format.level<>"5.1" then return {result:false}
            return {result:true}
        end if
        return {result:false}'''

        def transcript(responses):
            replies = []
            for response in ('original_response', 'fallback_response'):
                replies.extend([
                    {'statusCode': 200, 'body': json.dumps(fixture['detail'])},
                    {'statusCode': 200, 'body': json.dumps(fixture['capabilities'])},
                    {'statusCode': fixture[response]['status'],
                     'body': json.dumps(fixture[response]['decision'])},
                ])
            responses[:] = replies

        return Stock().job(enabled=None, p7_enabled=None, automatic_hdr10=None,
            options={'startPositionMs': 0}, device=sdk, http=transcript, host_http=host_http)

    def test_auto_advances_same_source_from_failed_original_to_validated_1080p(self):
        result = self.stock_job()
        requests = result['requests']
        self.assertEqual(['GET', 'GET', 'POST', 'GET', 'GET', 'POST'],
                         [r['method'] for r in requests])
        starts = [json.loads(r['body']) for r in requests if r['method'] == 'POST']
        self.assertEqual(['original', '1080p'], [s['quality_preference'] for s in starts])
        self.assertEqual(['731', '731'], [s['file_id'] for s in starts])
        self.assertNotEqual(starts[0]['playback_attempt_id'], starts[1]['playback_attempt_id'])
        self.assertEqual([r['url'] for r in requests[:2]], [r['url'] for r in requests[3:5]])
        self.assertEqual(starts[0]['client_capabilities'], starts[1]['client_capabilities'])
        self.assertNotIn('max_resolution', starts[1]['client_capabilities'])
        self.assertEqual(starts[0]['client_playback_context'], starts[1]['client_playback_context'])
        self.assertNotIn('max_resolution', starts[1])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        plan = result['outcome']['plan']
        self.assertEqual('hls', plan['streamFormat'])
        self.assertEqual('fixture-plan', plan['planId'])
        self.assertEqual('fixture-session', plan['sessionId'])
