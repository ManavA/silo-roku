"""Per-query SDK failures through ordinary real runJob Start/recovery.

Synthetic 4660X/SDK combinations, not measured device capabilities. HTTP, session,
SDK and Task thread boundaries only; no rollout, eligibility or receipt overrides.
"""
import copy
import json
import unittest
from unittest.mock import patch
from tests import test_silo_compat_continuation as task
from tests import test_silo_replan_task as recovery


class OptionalSDKResilience(unittest.TestCase):
    def sdk(self, fault):
        sdk = task.legacy.BOUNDARIES
        sdk = sdk.replace('return "C000X"', 'return "4660X"').replace('return "TV"', 'return "STB"').replace('ModelNumber:"C208X"', 'ModelNumber:"4660X"')
        video = {
            'hevc': 'format.codec="hevc"',
            'main10': 'format.codec="hevc" and format.profile="main 10"',
            'main': 'format.codec="hevc" and format.profile="main"',
            'late_hevc': 'format.codec="hevc" and format.container<>invalid',
            'avc': 'format.codec="mpeg4 avc"',
            'all_video': 'true',
        }
        if fault in video:
            sdk = sdk.replace('if m.rejectMain10 = true', 'if '+video[fault]+' then throw "synthetic-sdk-error"\n        if m.rejectMain10 = true')
        if fault == 'avc':
            sdk = sdk.replace('return {result:true}', 'return {result:format.codec="mpeg4 avc"}')
        if fault == 'avc_missing':
            sdk = sdk.replace('CanDecodeVideo:function', 'MissingDecodeVideo:function')
        audio_fault = {
            'dts': 'format.codec="dts"', 'opus': 'format.codec="opus"',
            'passthrough': 'format.passthru=1', 'aac': 'format.codec="aac"',

        }.get(fault)
        insertion = ('if '+audio_fault+' then throw "synthetic-sdk-error"\n        ') if audio_fault else ''
        sdk = sdk.replace('if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}',
            insertion+'return {result:format.codec="aac" and format.passthru=0 and (format.chcnt=invalid or format.chcnt=2)}')
        display = {'display_throw':'throw "synthetic-sdk-error"', 'display_invalid':'return invalid', 'display_scalar':'return "true"'}.get(fault, 'return {Hdr10:true,Hdr10Plus:true,HLG:true,DolbyVision:false}' if fault in ('hevc','main10') else 'return {Hdr10:false,Hdr10Plus:false,HLG:false,DolbyVision:false}')
        sdk = sdk.replace('return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}', display)
        mode = {'mode_throw':'throw "synthetic-sdk-error"', 'mode_invalid':'return invalid', 'mode_scalar':'return 2160'}.get(fault)
        if mode:
            sdk = sdk.replace('return "1080p"', mode)
        return sdk

    def start(self, fault='', *, original=False, mixed=False):
        def fixture(wire, decision):
            hd = copy.deepcopy(wire['versions'][-1])
            hd.update(container='mp4', codec_audio='aac', audio_tracks=[dict(codec='aac', channels=2, layout='stereo', default=True)])
            versions = [hd]
            if mixed:
                high = copy.deepcopy(wire['versions'][0])
                high['video_tracks'] = [dict(codec='hevc',profile='main 10',level=150,width=3840,height=2160,bit_depth=10,frame_rate='24000/1001',interlaced=False,color_transfer='bt709')]
                high.update(hdr=False,codec_audio='aac',audio_tracks=[dict(codec='aac',channels=2,layout='stereo',default=True)])
                versions.insert(0,high)
            wire['versions'] = versions
            wire['playback_variants'] = [dict(variant_id='native',part_count=1,default_file_id='732',parts=[dict(part_index=1,default_file_id='732',versions=versions)])]
            p = decision['playback_plan']
            p.update(delivery='original_http' if original else 'server_transcode_hls', requested_media_file_id='732',effective_media_file_id='732',selected_tracks={'audio':{'id':'file:732:audio:0','index':0}},available_qualities=[])
            p['source'] = dict(media_file_id='732',container='mp4',video_codec='h264',video_profile='high',video_level=40,width=1920,height=1080,bit_depth=8,hdr10_plus=False,dv_enhancement_layer='none',dynamic_range='sdr',audio_codec='aac',audio_channels=2,audio_layout='stereo')
            p['stream'].update(protocol='http_progressive' if original else 'hls',container='mp4' if original else 'hls',url='/api/v2/playback/synthetic/stream.mp4' if original else '/api/v2/playback/transcode/synthetic/master.m3u8')
            p['effective_recipe'] = dict(video_codec='h264',audio_codec='aac',dynamic_range='sdr',width=1920,height=1080,audio_channels=2)
            p['transformations'] = [] if original else [dict(name='video_to_h264',executor='server',recipe_version='2'),dict(name='audio_to_aac',executor='server',recipe_version='4')]
        def replies(responses):
            cap = json.loads(responses[1]['body'])
            cap['deliveries'] = ['original_http','server_transcode_hls']
            responses[1]['body'] = json.dumps(cap)
        with patch.object(task.legacy, 'BOUNDARIES', self.sdk(fault)):
            return task.CompatContinuation().job(enabled=False, options=dict(fileId='732',startPositionMs=0),mutate=fixture,features=[],http=replies)

    def start_body(self, result):
        starts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(1, len(starts), result['outcome'])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertNotIn('compatContinuation', result['outcome'])
        self.assertEqual(('732','original'), (starts[0]['file_id'], starts[0]['quality_preference']))
        self.assertEqual([], starts[0]['client_features'])
        return starts[0]

    def test_optional_video_queries_cannot_abort_proven_h264_hls(self):
        for fault in ('hevc','main','main10'):
            with self.subTest(fault=fault):
                body = self.start_body(self.start(fault))
                caps = body['client_capabilities']
                self.assertIn('h264', caps['codecs_video'])
                self.assertFalse(caps['hdr'])
                if fault == 'hevc': self.assertNotIn('hevc', caps['codecs_video'])
                if fault == 'hevc': self.assertNotIn('max_resolution', caps)
                # Unknown Main5.1 now retains positive Main10/5.1 + 2160p evidence.
                if fault == 'main': self.assertEqual('2160p', caps.get('max_resolution'))

    def test_display_and_output_unknown_keep_h264_without_inventing_claims(self):
        for fault in ('display_throw','display_invalid','display_scalar','mode_throw','mode_invalid','mode_scalar'):
            with self.subTest(fault=fault):
                body = self.start_body(self.start(fault))
                caps = body['client_capabilities']
                self.assertFalse(caps['hdr'])
                if fault.startswith('display'): self.assertNotIn('hdr_details', caps)
                if fault.startswith('mode'): self.assertNotIn('max_resolution', caps)
                for delivery in body['client_playback_context']['deliveries'].values():
                    self.assertEqual([], delivery.get('hdr_details',{}).get('dolby_vision_profiles',[]))

    def test_optional_audio_queries_leave_independent_aac_decode_available(self):
        for fault in ('dts','opus','passthrough'):
            with self.subTest(fault=fault):
                body = self.start_body(self.start(fault))
                self.assertEqual(['aac'], body['client_capabilities']['codecs_audio'])
                self.assertEqual(['aac'],body['client_playback_context']['deliveries']['hls']['audio_decode_codecs'])
                self.assertEqual([],body['client_playback_context']['deliveries']['hls']['audio_passthrough_codecs'])

    def test_failed_required_queries_never_invent_h264_or_aac(self):
        for fault in ('avc','avc_missing','aac','all_video'):
            with self.subTest(fault=fault):
                result = self.start(fault)
                self.assertFalse(result['outcome']['ok'])
                self.assertNotEqual('task_failed', result['outcome'].get('errorCode'))
                self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))

    def test_original_h264_stays_native_first_and_later_hevc_candidate_is_isolated(self):
        for original, mixed, fault in ((True,False,'opus'), (False,True,'late_hevc'), (False,True,'mode_invalid')):
            with self.subTest(original=original,fault=fault):
                result = self.start(fault,original=original,mixed=mixed)
                self.start_body(result)
                self.assertEqual('mp4' if original else 'hls', result['outcome']['plan']['streamFormat'])
                self.assertEqual(0,sum(r['method']=='DELETE' for r in result['requests']))
                if fault == 'mode_invalid':
                    self.assertNotIn('max_resolution', self.start_body(result)['client_capabilities'])
                if fault == 'late_hevc':
                    self.assertTrue(any(q['codec']=='hevc' and q.get('container') for q in result['videoQueries']), result['videoQueries'])

    def test_recovery_uses_same_isolated_discovery_without_new_start(self):
        raw = json.loads((recovery.ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
        p = raw['playback_plan']
        p.update(delivery='server_transcode_hls',effective_recipe=dict(video_codec='h264',audio_codec='aac',audio_channels=2,dynamic_range='sdr',width=1280,height=720),transformations=[dict(name='video_to_h264',executor='server',recipe_version='2'),dict(name='audio_to_aac',executor='server',recipe_version='4')],selected_tracks=copy.deepcopy(recovery.values.TRACKS))
        p['stream'].update(protocol='hls',container='hls')
        boundary = recovery.BOUNDARY.replace('outcome=ExecuteApiAction("silo",action,params,scope)', '''job={provider:"silo",action:action,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,requestId:41,params:params}
 m.top=CreateObject("roSGNode","Node"):m.top.AddFields({cancelled:false,job:job,result:{}})
 runJob():outcome=m.top.result''')
        for fault in ('display_throw','hevc','opus','mode_invalid'):
            with self.subTest(fault=fault), patch.object(recovery,'BOUNDARY',boundary), patch.object(recovery.legacy,'BOUNDARIES',self.sdk(fault)):
                result = recovery.SiloReplanTaskTests().call(decision=raw,capability_features=[],capability_deliveries=['original_http','server_transcode_hls'])
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                self.assertEqual(['GET','POST'],[r['method'] for r in result['requests']])
                self.assertTrue(result['requests'][-1]['url'].endswith('/playback/session-0001/replan'))

    def test_exact_surround_query_throw_keeps_proven_aac2_projection(self):
        from tests import test_silo_audio_projection as audio
        probe = 'if format.chcnt=invalid then return {result:format.codec="aac" and format.passthru=0}\n if format.chcnt<>invalid and format.chcnt=6 then throw "synthetic-sdk-error"\n return {result:format.codec="aac" and format.container="ts" and format.chcnt=2 and format.passthru=0}'
        result = audio.AudioProjection().start(probe=probe)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertTrue(any(q.get('chcnt')==6 for q in result['audioQueries']), result['audioQueries'])
        body = audio.AudioProjection().bodies(result)[0]
        hls = body['client_playback_context']['deliveries']['hls']
        self.assertEqual((['aac'],[],2),(hls['audio_decode_codecs'],hls['audio_passthrough_codecs'],hls['max_channels']))
