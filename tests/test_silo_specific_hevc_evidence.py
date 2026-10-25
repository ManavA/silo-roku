"""Unknown-only HEVC aggregation at ordinary runJob/SDK/HTTP boundaries.

Specific typed-positive queries can fill an unknown broad answer, never override
an explicit rejection. Synthetic SDK evidence is not native playback proof.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_silo_compat_continuation as task

FIXTURE = Path(__file__).parent/'fixtures/silo/hdr10_split_0589_source_derived.json'

class SpecificHEVCEvidence(unittest.TestCase):
    def sdk(self, generic=None, main=None, main10=None, exact_reject=False, unknown_output=False, avc_false=False, exact_malformed=False):
        rules=[]
        for profile, answer in ((None,generic), ('main',main), ('main 10',main10)):
            if answer is None: continue
            condition='format.codec="hevc" and format.profile=invalid' if profile is None else 'format.codec="hevc" and format.profile="'+profile+'" and format.level="5.1"'
            rules.append('if '+condition+' then '+answer)
        if avc_false: rules.append('if format.codec="mpeg4 avc" then return {result:false}')
        if exact_malformed:
            rules.append('if format.codec="hevc" and format.container<>invalid then return {result:1}')
        if exact_reject:
            rules.append('if format.codec="hevc" and format.container<>invalid then return {result:false}')
        sdk=task.legacy.BOUNDARIES.replace('if m.rejectMain10 = true', '\n'.join(rules)+'\n        if m.rejectMain10 = true')
        sdk=sdk.replace('DolbyVision:true','DolbyVision:false')
        if unknown_output: sdk=sdk.replace('return "1080p"','return invalid')
        return sdk

    def start(self, legacy=False, lower_anchor=False, **answers):
        def fixture(wire,decision):
            decision.clear();decision.update(json.loads(FIXTURE.read_text()))
            if lower_anchor:
                wire['playback_variants'][0]['default_file_id']='732'
                wire['playback_variants'][0]['parts'][0]['default_file_id']='732'
            if legacy:
                hd=wire['versions'][-1]
                wire['versions']=[hd]
                wire['playback_variants']=[dict(variant_id='native',part_count=1,default_file_id='732',parts=[dict(part_index=1,default_file_id='732',versions=[hd])])]
                p=decision['playback_plan']
                p.update(delivery='server_transcode_hls',requested_media_file_id='732',effective_media_file_id='732',selected_tracks={'audio':{'id':'file:732:audio:0','index':0}})
                p['source']=dict(media_file_id='732',container='mkv',video_codec='h264',width=1920,height=1080,hdr10_plus=False,dv_enhancement_layer='none',audio_codec='aac',audio_channels=2)
                p['effective_recipe']=dict(video_codec='h264',audio_codec='aac',audio_channels=2,dynamic_range='sdr',width=1920,height=1080)
                p['transformations']=[dict(name='video_to_h264',executor='server',recipe_version='2'),dict(name='audio_to_aac',executor='server',recipe_version='4')]
        def replies(responses):
            if legacy:
                caps=json.loads(responses[1]['body']);caps['deliveries']=['original_http','server_transcode_hls'];responses[1]['body']=json.dumps(caps)
        with patch.object(task.legacy,'BOUNDARIES',self.sdk(**answers)):
            return task.CompatContinuation().job(enabled=False,mutate=fixture,features=[] if legacy else ['native_hls_separate_audio_v1'],options={'startPositionMs':0,'fileId':'732' if legacy or lower_anchor else '731'},http=replies)

    def starts(self,result):
        return [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]

    def hdr10_body(self,result):
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        bodies=self.starts(result)
        self.assertEqual(['731'],[b['file_id'] for b in bodies])
        self.assertNotIn('compatContinuation',result['outcome'])
        body=bodies[0];caps=body['client_capabilities'];hls=body['client_playback_context']['deliveries']['hls']
        self.assertIn('hevc',caps['codecs_video']);self.assertIn('hevc',hls['video_codecs'])
        self.assertEqual('2160p',caps.get('max_resolution'));self.assertTrue(caps['hdr'])
        self.assertTrue(hls['hdr_details']['hdr10']);self.assertNotIn(8,hls['hdr_details']['dolby_vision_profiles'])
        return body

    def test_generic_unknown_uses_specific_typed_positive_without_extra_queries(self):
        healthy=self.start();baseline=self.hdr10_body(healthy)
        self.assertEqual({'allow_alternate_versions':False,'client_features':['native_hls_separate_audio_v1'],
                         'file_id':'731','installation_id':'server-install','metered':False,
                         'playback_attempt_id':'roku-10000000-0000-4000-8000-000000000001',
                         'profile_id':'fixture-owner','progress_persistence':'server','protocol_version':3,
                         'quality_preference':'original','start_position':0,'subtitle_fidelity_preference':'preserve'},
                         {key:value for key,value in baseline.items() if key not in ('client_capabilities','client_playback_context')})
        self.assertEqual(['h264','hevc'],baseline['client_capabilities']['codecs_video'])
        self.assertEqual(['aac'],baseline['client_capabilities']['codecs_audio'])
        for delivery in baseline['client_playback_context']['deliveries'].values():
            self.assertEqual([],delivery['validated_claims'])
        self.assertEqual([{'codec':'mpeg4 avc'},{'codec':'hevc'},{'codec':'hevc','profile':'main','level':'5.1'},{'codec':'hevc','profile':'main 10','level':'5.1'}],healthy['videoQueries'][:4])
        for answer in ('throw "synthetic-sdk-error"','return invalid','return {}','return {result:"true"}','return {result:1}'):
            with self.subTest(answer=answer):
                result=self.start(generic=answer)
                self.assertEqual(baseline,self.hdr10_body(result))
                self.assertEqual(healthy['videoQueries'],result['videoQueries'])

    def test_unknown_main_uses_main10_but_explicit_main_false_does_not(self):
        for answer in ('throw "synthetic-sdk-error"','return invalid','return {result:"true"}'):
            with self.subTest(answer=answer):self.hdr10_body(self.start(main=answer))
        result=self.start(main='return {result:false}')
        bodies=self.starts(result);self.assertTrue(bodies)
        self.assertNotIn('max_resolution',bodies[0]['client_capabilities'])

    def test_explicit_generic_false_is_not_overridden_by_specific_success(self):
        result=self.start(generic='return {result:false,updated:{codec:"hevc"}}')
        bodies=self.starts(result);self.assertTrue(bodies)
        self.assertNotIn('hevc',bodies[0]['client_capabilities']['codecs_video'])
        self.assertNotIn('hevc',bodies[0]['client_playback_context']['deliveries']['hls']['video_codecs'])

    def test_unknown_broad_answers_need_one_typed_positive_specific_answer(self):
        result=self.start(generic='return invalid',main='return invalid',main10='return {result:false}')
        for body in self.starts(result):
            self.assertNotIn('hevc',body['client_capabilities']['codecs_video'])
            self.assertNotIn('max_resolution',body['client_capabilities'])
            self.assertFalse(body['client_capabilities'].get('hdr_details',{}).get('hdr10',False))
        self.assertFalse(result['outcome']['ok'])

    def test_unknown_output_cannot_claim_2160_or_promote_4k(self):
        result=self.start(generic='return invalid',unknown_output=True,lower_anchor=True)
        bodies=self.starts(result);self.assertTrue(bodies)
        self.assertTrue(all(b['file_id']!='731' for b in bodies))
        self.assertTrue(all('max_resolution' not in b['client_capabilities'] for b in bodies))

    def test_specific_generic_fallback_does_not_override_exact_file_probe(self):
        result=self.start(generic='return invalid',exact_reject=True)
        bodies=self.starts(result);self.assertTrue(bodies)
        self.assertTrue(all(b['file_id']!='731' for b in bodies))
        self.assertTrue(any(q.get('container') and q['codec']=='hevc' for q in result['videoQueries']))

    def test_unpatched_server_still_uses_existing_h264_sdr_hls(self):
        result=self.start(legacy=True,generic='return invalid')
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        body=self.starts(result)[0]
        self.assertEqual([],body['client_features'])
        self.assertEqual(['h264'],body['client_playback_context']['deliveries']['hls']['video_codecs'])
        self.assertEqual('732',result['outcome']['plan']['versionId'])
        self.assertTrue(any(q['codec']=='hevc' and q.get('profile') is None for q in result['videoQueries']))

    def test_main10_only_positive_works_without_avc_or_main(self):
        result=self.start(generic='return invalid',main='return invalid',avc_false=True)
        body=self.hdr10_body(result)
        self.assertEqual(['hevc'],body['client_capabilities']['codecs_video'])
        self.assertEqual(['hevc'],body['client_playback_context']['deliveries']['hls']['video_codecs'])

    def test_untyped_main10_result_cannot_supply_hdr_or_4k_authority(self):
        for answer in ('return invalid','return {result:1}','return {result:"true"}'):
            with self.subTest(answer=answer):
                result=self.start(generic='return invalid',main='return invalid',main10=answer)
                self.assertNotEqual('task_failed',result['outcome'].get('errorCode'))
                for body in self.starts(result):
                    caps=body['client_capabilities']
                    self.assertNotIn('hevc',caps['codecs_video'])
                    self.assertNotIn('max_resolution',caps)
                    self.assertFalse(caps.get('hdr_details',{}).get('hdr10',False))
                # This fixture has no DV output, so negotiation does not repeat
                # the capability query or turn an untyped answer into authority.
                self.assertEqual(sum(q.get('profile')=='main 10' and q.get('level')=='5.1' for q in result['videoQueries']),1)
                for body in self.starts(result):
                    bounds=body['client_capabilities'].get('hdr_details',{}).get('dolby_vision_profile_levels',[])
                    self.assertTrue(all(bound['max_level']<=7 for bound in bounds))

    def test_replan_assembler_reuses_specific_positive_evidence(self):
        from tests import test_silo_replan_task as recovery
        boundary=recovery.BOUNDARY.replace('outcome=ExecuteApiAction("silo",action,params,scope)', '''job={provider:"silo",action:action,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,requestId:41,params:params}
 m.top=CreateObject("roSGNode","Node"):m.top.AddFields({cancelled:false,job:job,result:{}})
 runJob():outcome=m.top.result''')
        sdk=self.sdk(generic='return invalid',main='return invalid').replace('return "1080p"','return "2160p60"')
        with patch.object(recovery,'BOUNDARY',boundary),patch.object(recovery.legacy,'BOUNDARIES',sdk):
            result=recovery.SiloReplanTaskTests().call(capability_features=['native_hls_separate_audio_v1'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','POST'],[r['method'] for r in result['requests']])
        body=json.loads(result['requests'][-1]['body'])
        self.assertIn('hevc',body['client_capabilities']['codecs_video'])
        self.assertEqual('2160p',body['client_capabilities'].get('max_resolution'))
        self.assertIn('hevc',body['client_playback_context']['deliveries']['hls']['video_codecs'])

    def test_decoder_result_requires_typed_boolean_and_ignores_suggestions(self):
        for raw,expected in [({'result':True},True),({'result':False},False),({'result':'true'},False),({'result':1},False),({},False),(None,False),({'result':False,'updated':{'result':True}},False)]:
            with self.subTest(raw=raw):
                self.assertEqual(expected,task.legacy.SiloPlaybackTaskTests().worker('TaskDecoderResult',[raw]))

    def test_malformed_exact_file_probe_still_refuses_4k_promotion(self):
        result=self.start(generic='return invalid',exact_malformed=True)
        bodies=self.starts(result);self.assertTrue(bodies)
        self.assertTrue(all(b['file_id']!='731' for b in bodies))
        self.assertTrue(any(q.get('container') and q['codec']=='hevc' for q in result['videoQueries']))
