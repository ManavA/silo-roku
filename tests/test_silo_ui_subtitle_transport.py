"""Scene-only selected-caption transport ownership and native binding."""
import copy
import unittest
from pathlib import Path

from tools.brightscript import run_function
from tests.test_silo_ui_selected_subtitle_scene import ready_plan


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'components/SiloUISubtitleArtifact.brs'
CAPTION = ('https://silo.example/api/v2/stream/sess-1/subtitles/1.vtt?file_id=f1')


def transport_plan():
    plan = ready_plan()
    plan.pop('subtitleArtifact')
    plan['selectedSubtitle']['kind'] = 'sidecar_pending'
    plan['selectedSubtitle']['renderingReady'] = False
    plan['siloPlayback']['mediaAuthMode'] = 'api_header_v1'
    plan['url'] = 'https://silo.example/api/v2/stream/sess-1?file_id=f1'
    plan['headers'] = {'Authorization': 'Bearer synthetic-access-token'}
    plan['subtitleTransport'] = {
        'uri': CAPTION, 'format': 'vtt', 'mimeType': 'text/vtt',
        'timingOriginSeconds': 0.5, 'apiOrigin': 'https://silo.example:443',
        'authMode': 'api_header_v1',
        'owner': {'sourceId': 'silo:synthetic', 'profileId': 'profile',
                  'generation': 7, 'requestId': 42, 'sessionRevision': 2,
                  'sessionId': 'sess-1', 'planAttemptKey': 'attempt-1',
                  'fileId': 'f1', 'selectedOrdinal': 1, 'timelineOffsetMs': 0},
    }
    return plan


class SubtitleTransportPolicyTests(unittest.TestCase):
    def binding(self, plan):
        return run_function([POLICY], 'SiloUISubtitleBinding', [plan, 7, 42])

    def test_owned_original_transport_reuses_native_binding_contract(self):
        plan = transport_plan()
        bound = self.binding(plan)
        self.assertIsNotNone(bound)
        self.assertEqual(CAPTION, bound['uri'])
        self.assertEqual('vtt', bound['format'])
        self.assertEqual('eng', bound['language'])
        self.assertEqual(1, bound['selectedOrdinal'])
        self.assertEqual(plan['subtitleTransport']['owner'], bound['owner'])
        self.assertNotIn('Bearer', str(bound))
        self.assertNotIn('https:', bound['description'])
        inventory = [{'TrackName': 'native-7', 'Description': bound['description'],
                      'Language': 'en'}]
        self.assertEqual('native-7', run_function([POLICY],
                         'SiloUISubtitleNativeCandidate', [bound, inventory]))
        self.assertTrue(run_function([POLICY], 'SiloUISubtitleCurrentMatches',
                                     [bound, 'native-7', inventory]))

    def test_prior_request_inventory_cannot_match_new_owner(self):
        old = self.binding(transport_plan())
        plan = transport_plan()
        plan['subtitleTransport']['owner']['requestId'] = 43
        current = run_function([POLICY], 'SiloUISubtitleBinding', [plan, 7, 43])
        self.assertIsNotNone(current)
        self.assertNotEqual(old['description'], current['description'])
        stale = [{'TrackName': 'native-7', 'Description': old['description'],
                  'Language': 'en'}]
        self.assertIsNone(run_function([POLICY], 'SiloUISubtitleNativeCandidate',
                                        [current, stale]))
        self.assertFalse(run_function([POLICY], 'SiloUISubtitleCurrentMatches',
                                      [current, 'native-7', stale]))

    def test_owned_hls_manifest_and_bounded_seek_are_accepted(self):
        for url in ('https://silo.example/api/v2/playback/transcode/sess-1/master.m3u8',
                    'https://silo.example/api/v2/playback/transcode/sess-1/master.m3u8?file_id=f1',
                    'https://silo.example/api/v2/stream/sess-1?file_id=f1&seek=10.123456789',
                    'https://silo.example:443/api/v2/stream/sess-1?seek=10.25'):
            with self.subTest(url=url):
                plan = transport_plan()
                plan['url'] = url
                self.assertIsNotNone(self.binding(plan))

    def test_ipv6_default_port_and_empty_profile_remain_valid(self):
        plan = transport_plan()
        plan['url'] = plan['url'].replace('silo.example', '[::1]')
        plan['subtitleTransport']['uri'] = CAPTION.replace('silo.example', '[::1]')
        plan['subtitleTransport']['apiOrigin'] = 'https://[::1]:443'
        plan['siloPlayback']['profileId'] = ''
        plan['subtitleTransport']['owner']['profileId'] = ''
        self.assertIsNotNone(self.binding(plan))

    def test_local_binding_is_preserved_and_malformed_transport_cannot_fall_back(self):
        local = ready_plan()
        self.assertEqual(local['subtitleArtifact']['uri'], self.binding(local)['uri'])
        local['subtitleTransport'] = {'uri': 'https://silo.example/subtitle.vtt'}
        self.assertIsNone(self.binding(local))

    def test_owner_and_mode_mismatch_refuse_remote_binding(self):
        mutations = (
            lambda p: p['siloPlayback'].pop('mediaAuthMode'),
            lambda p: p['siloPlayback'].update(mediaAuthMode='other'),
            lambda p: p['subtitleTransport'].update(authMode='other'),
            lambda p: p['subtitleTransport']['owner'].update(generation=8),
            lambda p: p['subtitleTransport']['owner'].update(requestId=43),
            lambda p: p['subtitleTransport']['owner'].update(profileId='other'),
            lambda p: p['subtitleTransport']['owner'].update(fileId='f2'),
            lambda p: p['subtitleTransport']['owner'].update(sessionRevision=3),
            lambda p: p['subtitleTransport']['owner'].update(planAttemptKey='other'),
            lambda p: p['subtitleTransport']['owner'].update(timelineOffsetMs=1000),
            lambda p: p['selectedSubtitle'].update(trackId='file:f1:subtitle:0'),
            lambda p: p['selectedSubtitle'].update(renderingReady=True),
            lambda p: p.update(subtitleMode='off'),
        )
        for mutate in mutations:
            plan = transport_plan()
            mutate(plan)
            with self.subTest(mutate=mutate):
                self.assertIsNone(self.binding(plan))

    def test_credential_or_foreign_origin_never_reaches_video_binding(self):
        mutations = (
            lambda p: p['headers'].update(**{'X-Profile-Token': 'synthetic'}),
            lambda p: p['headers'].update(Authorization='Basic synthetic'),
            lambda p: p['headers'].update(Authorization='Bearer '),
            lambda p: p['subtitleTransport'].update(apiOrigin='https://foreign.example:443'),
            lambda p: p['subtitleTransport'].update(apiOrigin=None),
            lambda p: p['subtitleTransport'].update(uri=CAPTION.replace('silo.example', 'foreign.example')),
            lambda p: p.update(url=p['url'].replace('silo.example', 'foreign.example')),
            lambda p: p.update(url='https://user@silo.example/api/v2/stream/sess-1'),
            lambda p: p.update(url=p['url'] + '#fragment'),
            lambda p: p.update(url=p['url'] + '&st=secret'),
            lambda p: p.update(url='https://silo.example:444/api/v2/stream/sess-1'),
        )
        for mutate in mutations:
            plan = transport_plan()
            mutate(plan)
            with self.subTest(mutate=mutate):
                self.assertIsNone(self.binding(plan))

    def test_only_owned_v2_routes_and_caption_query_fields_bind(self):
        bad_av = (
            'https://silo.example/api/v1/stream/sess-1?file_id=f1',
            'https://silo.example/api/v2/stream/other?file_id=f1',
            'https://silo.example/api/v2/stream/sess-1?file_id=f2',
            'https://silo.example/api/v2/stream/sess-1?seek=999999',
            'https://silo.example/api/v2/playback/transcode/sess-1/master.m3u8?st=x',
            'https://silo.example/api/v2/playback/transcode/sess-1/master.m3u8?seek=10',
        )
        for url in bad_av:
            plan = transport_plan()
            plan['url'] = url
            with self.subTest(url=url):
                self.assertIsNone(self.binding(plan))

    def test_session_id_must_be_a_single_literal_path_segment(self):
        for session in ('a/b', '.', '..', 'a%2fb', 'a%2Eb', 'a\\b',
                        'a#b', 'a?b', 'a b', 'a\nb'):
            plan = transport_plan()
            plan['sessionId'] = session
            plan['siloPlayback']['sessionId'] = session
            plan['subtitleTransport']['owner']['sessionId'] = session
            plan['url'] = f'https://silo.example/api/v2/stream/{session}?file_id=f1'
            plan['subtitleTransport']['uri'] = (
                f'https://silo.example/api/v2/stream/{session}/subtitles/1.vtt?file_id=f1')
            with self.subTest(session=session):
                self.assertIsNone(self.binding(plan))
        bad_caption = (
            CAPTION.replace('/subtitles/1.vtt', '/subtitles/0.vtt'),
            CAPTION.replace('file_id=f1', 'file_id=f2'),
            CAPTION + '&api_key=secret',
            CAPTION + '&file_id=f1',
            CAPTION + '&position=0',
        )
        for uri in bad_caption:
            plan = transport_plan()
            plan['subtitleTransport']['uri'] = uri
            with self.subTest(uri=uri):
                self.assertIsNone(self.binding(plan))


if __name__ == '__main__':
    unittest.main()
