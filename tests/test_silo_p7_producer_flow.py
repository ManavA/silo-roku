"""P7 producer from real Detail audio intent through actual runJob.

Parsed technical metadata has synthetic identities. Scene/Task SDK and HTTP
leaves are faked; source, selector, native-priority and candidate policy are real.
This slice does not admit a Scene continuation or allocate a compatibility holder.
"""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_silo_ui_native_hdr10_scene as scene
from tests import test_silo_compat_continuation as task

ROOT = Path(__file__).resolve().parents[1]
TECHNICAL = json.loads((ROOT / 'tests/fixtures/silo/stock_p7_hdr10_technical_metadata.json').read_text())
KIND = 'experimental_query_p7_hdr10_fmp4_v1'
DEVICE = {
    'return "C000X"': 'return "4850X"',
    'ModelNumber:"C208X"': 'ModelNumber:"4850X"',
    'return "TV"': 'return "STB"',
    'return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}': 'return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:false}',
    'if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}': 'return {result:format.codec="ac3" and format.passthru=0 and (format.chcnt=invalid or format.chcnt=6)}',
}


def fixture(wire, decision):
    version = copy.deepcopy(TECHNICAL['native_version'])
    version['file_id'] = '731'
    wire.clear()
    wire.update(content_id='fixture-item', type='movie', title='Synthetic P7', versions=[version],
                playback_variants=[dict(variant_id='native', part_count=1, default_file_id='731',
                                       parts=[dict(part_index=1, default_file_id='731', versions=[version])])])
    response = json.loads((ROOT / 'tests/fixtures/silo/hdr10_split_0589_source_derived.json').read_text())
    plan = response['playback_plan']
    plan['source'].update(video_level=153, frame_rate=23.976, bitrate_kbps=62830,
                          dolby_vision_profile=7, dv_bl_compat_id=6, dv_enhancement_layer='unknown',
                          audio_codec='ac3', audio_channels=6)
    plan['effective_recipe'].update(audio_codec='ac3', frame_rate=23.976, bitrate_kbps=62830)
    plan['selected_tracks']['audio'] = dict(id='file:731:audio:1', index=1)
    plan['claims']['audio'].update(codec='ac3', passthrough=False)
    decision.clear()
    decision.update(response)


class P7ProducerFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bridge = scene.OrdinaryNativeHdr10Scene()
        detail_job = bridge.scene()['tasks'][0]['job']
        detail = task.CompatContinuation().job(enabled=False, scope=detail_job, mutate=fixture, device=DEVICE)['outcome']
        assert detail['ok'], detail
        execute = scene.run_brightscript
        encoded = json.dumps(detail['data']['versions']).replace('"', '""')

        def launch(files, body, *, root):
            entry = '''m.view="detail":m.detailToken=4
 m.detailVersions=ParseJson("''' + encoded + '''")
 choices=SiloUIDetailAudioChoices("silo",item,m.detailVersions,"")
 choice=choices[1]:choice.visit=m.detailToken:choice.sourceId=m.sourceId:choice.profileId=m.profileId:choice.generation=m.generation
 PlayItem(item,0,"",choice)'''
            assert body.count('  PlayItem(item,0)') == 1
            body = body.replace('  PlayItem(item,0)', entry, 1)
            body = body.replace('print FormatJson({heroCandidateEligible:', 'print FormatJson({versionExplicit:m.playVersionExplicit,heroCandidateEligible:', 1)
            return execute(files, body, root=root)
        with patch.object(scene, 'run_brightscript', side_effect=launch):
            selected = bridge.scene([detail])
        assert selected['versionExplicit'] is False
        cls.scene_job = selected['tasks'][1]['job']

    def run_task(self, *, enabled=True, job=None, mutate=None, features=None, http=None, race=""):
        def source(wire, decision):
            fixture(wire, decision)
            if mutate:
                mutate(wire, decision)
        return task.CompatContinuation().job(enabled=enabled, scope=job or copy.deepcopy(self.scene_job),
                                             mutate=source, device=DEVICE, features=features, http=http, race=race)

    def test_real_audio_only_job_mints_p7_handoff_without_native_allocation(self):
        params = {k.lower(): v for k, v in self.scene_job['params'].items()}
        self.assertFalse(params['autoversion'])
        self.assertEqual(('731', 'file:731:audio:1', 1), (params['fileid'], params['audiotrackid'], params['audiotrackindex']))
        self.assertEqual('truehd', params['detail']['versions'][0]['audioTracks'][0]['codec'])
        self.assertTrue(params['detail']['versions'][0]['audioTracks'][0]['isDefault'])
        result = self.run_task()
        self.assertEqual('compat_prepare_required', result['outcome'].get('errorCode'), result['outcome'])
        handoff = result['outcome']['compatContinuation']
        self.assertEqual(KIND, handoff['eligibilityKind'])
        self.assertFalse(handoff['autoVersion'])
        self.assertEqual(('731', 'file:731:audio:1', 1), (handoff['fileId'], handoff['audioTrackId'], handoff['audioTrackIndex']))
        self.assertEqual('native_source_unproven', handoff['reason'])
        self.assertEqual(dict(state='not_allocated'), handoff['nativeClosure'])
        self.assertEqual(['GET', 'GET'], [request['method'] for request in result['requests']])
        self.assertFalse(any('compat' in request['url'] or 'PlaybackInfo' in request['url'] for request in result['requests']))

    def test_selected_ac3_native_proof_keeps_native_start_and_original_defaults(self):
        result = self.run_task(features=['native_hls_separate_audio_v1'])
        self.assertNotIn('compatContinuation', result['outcome'])
        posts = [json.loads(request['body']) for request in result['requests'] if '/playback/start' in request['url']]
        self.assertEqual(1, len(posts), result['outcome'])
        self.assertEqual(('731', 'file:731:audio:1', 1), (posts[0]['file_id'], posts[0].get('audio_track_id'), posts[0].get('audio_track_index')))
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertTrue(any(q.get('codec') == 'ac3' and q.get('container') == 'mkv' and q.get('passthru') == 0 for q in result['audioQueries']))
        source = result['outcome']['data']['playbackDetail']['versions'][0]
        self.assertEqual('truehd', source['audioCodec'])
        self.assertTrue(source['audioTracks'][0]['isDefault'])
        self.assertEqual(('ac3', False), (source['audioTracks'][1]['codec'], source['audioTracks'][1]['isDefault']))
        self.assertFalse(any(request['method'] == 'DELETE' for request in result['requests']))

    def changed_job(self, **changes):
        job = copy.deepcopy(self.scene_job)
        for name, value in changes.items():
            for key in list(job['params']):
                if key.lower() == name.lower():
                    del job['params'][key]
            if value is not None:
                job['params'][name] = value
        return job

    def assert_no_handoff(self, result):
        self.assertNotIn('compatContinuation', result['outcome'])
        self.assertNotEqual('task_failed', result['outcome'].get('errorCode'))
        self.assertFalse(any('PlaybackInfo' in request['url'] or 'QuickConnect' in request['url'] for request in result['requests']))

    def test_gate_off_caller_flags_leave_the_ordinary_explicit_audio_request_unchanged(self):
        baseline = self.run_task(enabled=False)
        self.assert_no_handoff(baseline)
        attempt = self.run_task(enabled=False, job=self.changed_job(compatPreparationEnabled=True, eligibilityKind=KIND))
        self.assert_no_handoff(attempt)
        self.assertEqual(baseline['requests'], attempt['requests'])
        post = next(json.loads(r['body']) for r in baseline['requests'] if '/playback/start' in r['url'])
        self.assertEqual(('file:731:audio:1', 1), (post['audio_track_id'], post['audio_track_index']))
        self.assertFalse(baseline['originalFlag'])
        self.assertFalse(baseline['p8Flag'])

    def test_changed_fresh_ac3_identity_refuses_before_allocation(self):
        def changed(wire, decision):
            wire['versions'][0]['audio_tracks'][1]['codec'] = 'eac3'
        result = self.run_task(mutate=changed)
        self.assert_no_handoff(result)
        self.assertEqual('invalid_audio_selection', result['outcome']['errorCode'])
        self.assertFalse(any(r['method'] in ('POST', 'DELETE') for r in result['requests']))

    def test_missing_mismatched_or_duplicate_selector_pair_never_mints_p7(self):
        jobs = [self.changed_job(audioTrackId=None), self.changed_job(audioTrackIndex=None),
                self.changed_job(audioTrackId='file:731:audio:2')]
        duplicate = copy.deepcopy(self.scene_job)
        duplicate['params']['audioTrackIndex'] = 1
        jobs.append(duplicate)
        for job in jobs:
            with self.subTest(keys=list(job['params'])):
                self.assert_no_handoff(self.run_task(job=job))

    def test_malformed_serialized_audio_selector_refuses_before_requests(self):
        for selectors in (dict(audioTrackIndex=[]), dict(audioTrackIndex={}),
                          dict(audioTrackIndex=True), dict(audioTrackIndex='1'),
                          dict(audioTrackId={}), dict(audioTrackId=True),
                          dict(audioTrackIndex=[], audioTrackId=None),
                          dict(audioTrackId={}, audioTrackIndex=None)):
            with self.subTest(selectors=selectors):
                result = self.run_task(job=self.changed_job(**selectors))
                self.assertEqual('invalid_request', result['outcome'].get('errorCode'), result['outcome'])
                self.assertEqual([], result['requests'])
                self.assertNotIn('compatContinuation', result['outcome'])

    def test_multiple_fresh_sources_and_user_cap_cannot_authorize_p7(self):
        def multiple(wire, decision):
            extra = copy.deepcopy(wire['versions'][0])
            extra['file_id'] = '733'
            wire['versions'].append(extra)
        self.assert_no_handoff(self.run_task(mutate=multiple))
        self.assert_no_handoff(self.run_task(job=self.changed_job(bandwidthCapKbps=1000)))

    def test_speculative_and_changed_pin_requests_cannot_allocate_compatibility(self):
        for result in (self.run_task(job=self.changed_job(speculativePrebuffer=True)),
                       self.run_task(race='pin')):
            self.assert_no_handoff(result)
            self.assertFalse(any(r['method'] == 'POST' for r in result['requests']))

    def test_failed_owned_native_stop_blocks_a_later_compatibility_handoff(self):
        sdk = task.legacy.BOUNDARIES.replace(
            'return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}',
            'if m.nativePosted<>true then return {Hdr10:false,DolbyVision:false}\n        return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}')
        sdk = sdk.replace('    response = m.responses.Shift()',
            '    if request.method="POST" and Instr(1,request.url,"/playback/start")>0 then FixtureSiloDevice().nativePosted=true\n    response = m.responses.Shift()')
        def failed_start(responses):
            responses[3] = dict(statusCode=503, body='{}')
        with patch.object(task.legacy, 'BOUNDARIES', sdk):
            result = self.run_task(http=failed_start)
        self.assert_no_handoff(result)
        self.assertFalse(result['outcome']['ok'])
        self.assertTrue(result['outcome'].get('leaseUncertain'), result['outcome'])
        self.assertEqual(1, sum('/playback/start' in r['url'] for r in result['requests']))
        deletes = [r for r in result['requests'] if r['method'] == 'DELETE']
        self.assertEqual(1, len(deletes))
        self.assertTrue(deletes[0]['url'].endswith('/playback/session-fixture-01'))
        self.assertEqual('server-install', json.loads(deletes[0]['body'])['installation_id'])
