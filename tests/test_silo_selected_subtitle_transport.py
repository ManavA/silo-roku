"""Task-only native VTT transport admission; no HTTP or Scene publication."""
import copy
import unittest

from tests.test_silo_selected_subtitle_fetch import (ADAPTER, HELPER, OWNER, POLICY,
                                                      SESSION, receipt)
from tests.test_silo_selected_subtitle_receipt import selected, BASE
from tools.brightscript import run_function


def av_plan(url=None, **changes):
    plan = {'url': url or BASE + '/api/v2/stream/session-0001',
            'headers': {'Authorization': 'Bearer fake-access-only'},
            'sessionId': OWNER['sessionId'], 'versionId': OWNER['fileId'],
            'sourceId': OWNER['sourceId'], 'planAttemptKey': OWNER['planAttemptKey'],
            'timelineOffsetMs': OWNER['timelineOffsetMs'],
            'siloPlayback': {'mediaAuthMode': 'api_header_v1',
                             'sourceId': OWNER['sourceId'], 'profileId': OWNER['profileId'],
                             'fileId': OWNER['fileId'], 'sessionId': OWNER['sessionId'],
                             'sessionRevision': OWNER['sessionRevision'],
                             'planAttemptKey': OWNER['planAttemptKey']}}
    plan.update(changes)
    return plan


class SubtitleTransportTests(unittest.TestCase):
    def plan(self, selected_receipt=None, session=None, owner=None, av=None):
        return run_function([POLICY, ADAPTER, HELPER], 'SiloSubtitleTransportPlan',
                            [receipt() if selected_receipt is None else selected_receipt,
                             SESSION if session is None else session,
                             OWNER if owner is None else owner,
                             av_plan() if av is None else av])

    def test_exact_owned_vtt_and_api_bearer_admit_private_pending_descriptor(self):
        for url in (BASE + '/api/v2/stream/session-0001',
                    BASE + '/api/v2/playback/transcode/session-0001/master.m3u8'):
            with self.subTest(url=url):
                result = self.plan(av=av_plan(url))
                self.assertTrue(result['ok'], result)
                transport = result['transport']
                self.assertEqual('api_header_v1', transport['authMode'])
                self.assertEqual('https://silo.example:443', transport['apiOrigin'])
                self.assertEqual(BASE + '/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42', transport['uri'])
                self.assertEqual(('vtt', 'text/vtt', 0),
                                 (transport['format'], transport['mimeType'], transport['timingOriginSeconds']))
                self.assertEqual(OWNER, transport['owner'])
                self.assertNotIn('token', str(transport).lower())
                self.assertNotIn('renderingReady', str(transport))

    def test_missing_or_wrong_mode_and_any_non_bearer_header_refuse(self):
        for mode in (None, '', 'other', True):
            with self.subTest(mode=mode):
                self.assertFalse(self.plan(av=av_plan(siloPlayback={'mediaAuthMode': mode}))['ok'])
        self.assertFalse(self.plan(av=av_plan(siloPlayback={}))['ok'])
        for headers in ({}, {'Authorization': 'Bearer wrong'},
                        {'Authorization': 'Bearer fake-access-only', 'X-Profile-Id': 'p1'},
                        {'Authorization': 'Bearer fake-access-only', 'Cookie': 'x'},
                        {'authorization': 'Bearer fake-access-only'}):
            with self.subTest(headers=headers):
                self.assertFalse(self.plan(av=av_plan(headers=headers))['ok'])

    def test_av_route_origin_owner_and_query_are_exact(self):
        for url in ('https://foreign.example/api/v2/stream/session-0001',
                    BASE + '/api/v2/stream/other', BASE + '/api/v2/stream/session-0001/extra',
                    BASE + '/api/v2/stream/session-0001?st=secret',
                    BASE + '/api/v2/stream/session-0001?file_id=42x',
                    BASE + '/api/v2/stream/session-0001?seek=1&seek=2',
                    BASE + '/api/v2/playback/transcode/session-0001/master.m3u8?seek=1',
                    BASE + '/api/v2/stream/session-0001#fragment'):
            with self.subTest(url=url):
                self.assertFalse(self.plan(av=av_plan(url))['ok'])
        for change in ({'sessionId': 'other'}, {'versionId': '99'},
                       {'sourceId': 'silo:other'}, {'planAttemptKey': 'other'},
                       {'timelineOffsetMs': 1000}):
            self.assertFalse(self.plan(av=av_plan(**change))['ok'])
        for field, value in (('sourceId', 'silo:other'), ('profileId', 'other'),
                             ('fileId', '99'), ('sessionId', 'other'),
                             ('sessionRevision', 4), ('planAttemptKey', 'other')):
            context = dict(av_plan()['siloPlayback'], **{field: value})
            with self.subTest(contextField=field):
                self.assertFalse(self.plan(av=av_plan(siloPlayback=context))['ok'])

    def test_ambiguous_path_owner_and_caption_credentials_refuse(self):
        for value in ('../session', 'session/other', 'session%2fother', 'session:other'):
            with self.subTest(session=value):
                self.assertFalse(self.plan(owner=dict(OWNER, sessionId=value))['ok'])
        for value in ('../42', '42/other', '42%2fother', '42:other'):
            with self.subTest(file=value):
                self.assertFalse(self.plan(owner=dict(OWNER, fileId=value))['ok'])
        invalid = copy.deepcopy(receipt())
        invalid['privateArtifact']['url'] += '&access_token=secret'
        self.assertFalse(self.plan(selected_receipt=invalid)['ok'])

    def test_srt_native_transport_declines_for_local_fetch_fallback(self):
        raw = selected()
        url = '/api/v2/stream/session-0001/subtitles/1.srt?file_id=42&original=1'
        raw['subtitle']['artifact'].update(url=url, format='srt', mime_type='application/x-subrip')
        raw['subtitle']['inventory'][1]['url'] = url
        candidate = run_function([POLICY, ADAPTER], 'SiloSelectedSubtitleReceipt',
                                 [raw, BASE, OWNER['sessionId']])
        self.assertTrue(candidate['ok'], candidate)
        result = self.plan(selected_receipt=candidate)
        self.assertFalse(result['ok'])
        self.assertEqual('subtitle_native_unsupported', result['errorCode'])


if __name__ == '__main__':
    unittest.main()
