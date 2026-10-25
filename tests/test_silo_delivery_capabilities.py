"""Independent delivery proof through actual runJob/HTTP and SDK boundaries.

These are synthetic capability combinations, not recorded4660 query results.
The official4660X model label is deliberately NOT playback authority. Positive
H264/TS/AAC query results, not a model allowlist, must authorize the HLS path.
"""
import copy,json,unittest
from tests import test_silo_compat_continuation as task

class IndependentDeliveryCapabilities(unittest.TestCase):
    def start(self, audio='mp4_and_ts', video=True, server=True, source_container='mp4', features=None):
        def fixture(wire,decision):
            hd=copy.deepcopy(wire['versions'][-1]);hd['container']=source_container
            wire['versions']=[hd]
            wire['playback_variants']=[dict(variant_id='native',part_count=1,default_file_id='732',parts=[dict(part_index=1,default_file_id='732',versions=[hd])])]
            plan=decision['playback_plan']
            plan.update(delivery='server_transcode_hls',requested_media_file_id='732',effective_media_file_id='732')
            plan['source'].update(media_file_id='732',video_codec='h264',width=1920,height=1080,hdr10_plus=False,dv_enhancement_layer='')
            plan['stream'].update(protocol='hls',container='hls',url='/api/v2/playback/transcode/fixture/master.m3u8?st=synthetic')
            # This source-shaped stereo AAC encode publishes its actual target count
            # (stock plan_v3 sets EffectiveRecipe.AudioChannels for AAC output).
            plan['effective_recipe']=dict(video_codec='h264',audio_codec='aac',dynamic_range='sdr',width=1920,height=1080,audio_channels=2)
            plan['transformations']=[dict(name='video_to_h264',executor='server',recipe_version='2'),dict(name='audio_to_aac',executor='server',recipe_version='2')]
        def replies(responses):
            caps=json.loads(responses[1]['body']);caps['deliveries']=['server_transcode_hls'] if server else ['original_http'];responses[1]['body']=json.dumps(caps)
        supported={
            'mp4_and_ts':'format.codec="aac" and format.passthru=0 and (format.container="mp4" or format.container="ts")',
            'mp4_only':'format.codec="aac" and format.passthru=0 and format.container="mp4"',
            'ts_ac3':'format.codec="ac3" and format.passthru=0 and format.container="ts"',
            'ts_aac_passthrough':'format.codec="aac" and format.passthru=1 and format.container="ts"',
        }.get(audio,'false')
        device={'return "C000X"':'return "4660X"','return "TV"':'return "STB"','ModelNumber:"C208X"':'ModelNumber:"4660X"',
                'return "2160p60"':'return "1080p"','return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}':'return {hdr10:false,hdr10Plus:false,hlg:false,DolbyVision:false}',
                'return {result:true}':'return {result:format.codec="mpeg4 avc"}' if video else 'return {result:false}',
                'if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}':'return {result:'+supported+'}'}
        return task.CompatContinuation().job(enabled=False,options=dict(fileId='732',startPositionMs=0),mutate=fixture,device=device,http=replies,features=features)

    def test_positive_ts_h264_aac_reaches_start_despite_unproven_mkv_audio(self):
        result=self.start()
        starts=[r for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(1,len(starts),result['outcome'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        body=json.loads(starts[0]['body']);delivery=body['client_playback_context']['deliveries']
        self.assertFalse(delivery['original_http']['enabled'])
        self.assertTrue(delivery['hls']['enabled'])
        self.assertEqual(['h264'],delivery['hls']['video_codecs'])
        self.assertEqual(['aac'],delivery['hls']['audio_decode_codecs'])
        self.assertEqual([],delivery['hls']['audio_passthrough_codecs'])
        self.assertNotIn('hdr_details',delivery['hls'])
        self.assertEqual('hls',result['outcome']['plan']['streamFormat'])

    def test_no_ts_aac_does_not_allocate(self):
        result=self.start(audio='mp4_only',source_container='mkv')
        self.assertEqual('unsupported_device',result['outcome']['errorCode'])
        self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))

    def test_no_avc_does_not_allocate(self):
        result=self.start(video=False)
        self.assertEqual('unsupported_device',result['outcome']['errorCode'])
        self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))

    def test_no_server_hls_does_not_allocate(self):
        result=self.start(server=False,source_container='mkv')
        self.assertEqual('unsupported_device',result['outcome']['errorCode'])
        self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))

    def test_legacy_hls_requires_aac_decode_not_other_audio_evidence(self):
        for audio in ('ts_ac3','ts_aac_passthrough'):
            with self.subTest(audio=audio):
                result=self.start(audio=audio)
                self.assertEqual('unsupported_device',result['outcome']['errorCode'])
                self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))

    def test_recovery_independently_negotiates_ts_hls_before_rejecting_device(self):
        # Dispatch the replan fixture through the real runJob entry point.
        from unittest.mock import patch
        from tests import test_silo_replan_task as recovery
        boundary=recovery.BOUNDARY.replace('outcome=ExecuteApiAction("silo",action,params,scope)', '''job={provider:"silo",action:action,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,requestId:41,params:params}
 m.top=CreateObject("roSGNode","Node"):m.top.AddFields({cancelled:false,job:job,result:{}})
 runJob():outcome=m.top.result''')
        sdk=recovery.legacy.BOUNDARIES.replace(
            'if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}',
            'return {result:format.codec="aac" and format.passthru=0 and (format.container="mp4" or format.container="ts")}')
        raw=json.loads((recovery.ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
        plan=raw['playback_plan']
        plan.update(delivery='server_transcode_hls',effective_recipe=dict(video_codec='h264',audio_codec='aac',dynamic_range='sdr',width=1280,height=720,audio_channels=2),transformations=[dict(name='video_to_h264',executor='server',recipe_version='2'),dict(name='audio_to_aac',executor='server',recipe_version='2')])
        plan['stream'].update(protocol='hls',container='hls')
        plan['selected_tracks']=copy.deepcopy(recovery.values.TRACKS)
        with patch.object(recovery,'BOUNDARY',boundary),patch.object(recovery.legacy,'BOUNDARIES',sdk):
            result=recovery.SiloReplanTaskTests().call(decision=raw,capability_features=[],capability_deliveries=['original_http','server_transcode_hls'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','POST'],[r['method'] for r in result['requests']])
        body=json.loads(result['requests'][1]['body']);delivery=body['client_playback_context']['deliveries']
        self.assertFalse(delivery['original_http']['enabled'])
        self.assertTrue(delivery['hls']['enabled'])
        self.assertEqual(['aac'],delivery['hls']['audio_decode_codecs'])
        self.assertEqual('hls',result['outcome']['plan']['streamFormat'])
        self.assertEqual([6000,90000],result['timeouts'])
