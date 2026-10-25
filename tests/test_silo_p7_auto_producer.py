"""Real no-audio-choice PlayItem→Task Auto producer contract.

The technical source has synthetic identities. Only SG/HTTP/device SDK leaves
and the existing test-copy compatibility gate are substituted. No UI audio
choice, continuation, chooser, or native receipt validator is fabricated.
"""
import copy
import unittest
from unittest.mock import patch
from tests import test_silo_ui_native_hdr10_scene as scene
from tests import test_silo_p7_producer_flow as explicit


class P7AutoProducer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bridge=scene.OrdinaryNativeHdr10Scene()
        detail_job=bridge.scene()['tasks'][0]['job']
        cls.detail=explicit.task.CompatContinuation().job(enabled=True,scope=detail_job,
            mutate=explicit.fixture,device=explicit.DEVICE)['outcome']
        assert cls.detail['ok'],cls.detail
        execute=scene.run_brightscript
        def launch(files,body,*,root):
            original='print FormatJson({heroCandidateEligible:'
            assert original in body
            body=body.replace(original,'print FormatJson({audioChoicePresent:m.playAudioChoice<>invalid,versionExplicit:m.playVersionExplicit,normalizedFile:m.playSelectedVersion,heroCandidateEligible:',1)
            return execute(files,body,root=root)
        with patch.object(scene,'run_brightscript',side_effect=launch):
            cls.entry=bridge.scene([cls.detail])
        cls.job=cls.entry['tasks'][1]['job']

    def test_real_auto_job_selects_equivalent_ac3_six_before_any_allocation(self):
        self.assertFalse(self.entry['audioChoicePresent'])
        self.assertFalse(self.entry['versionExplicit'])
        self.assertEqual('',self.entry['normalizedFile'])
        params={key.lower():value for key,value in self.job['params'].items()}
        self.assertTrue(params['autoversion'])
        self.assertFalse(any(name in params for name in ('audiotrackid','audiotrackindex','subtitletrackid','subtitletrackindex')))
        version=params['detail']['versions'][0]
        self.assertEqual('truehd',version['audioCodec'])
        self.assertEqual([True,False,False],[track['isDefault'] for track in version['audioTracks']])
        facts=version['autoAudioFacts']
        self.assertEqual(0,facts['preferred_ordinal'])
        result=explicit.task.CompatContinuation().job(enabled=True,scope=copy.deepcopy(self.job),
            mutate=explicit.fixture,device=explicit.DEVICE)
        outcome=result['outcome']
        self.assertEqual('compat_prepare_required',outcome.get('errorCode'),outcome)
        continuation=outcome['compatContinuation']
        self.assertEqual(explicit.KIND,continuation['eligibilityKind'])
        self.assertTrue(continuation['autoVersion'])
        self.assertEqual(('731','file:731:audio:1',1),tuple(continuation[key] for key in ('fileId','audioTrackId','audioTrackIndex')))
        self.assertEqual({'state':'not_allocated'},continuation['nativeClosure'])
        selection=continuation['autoAudioSelection']
        self.assertEqual(('auto','equivalent_fallback',0,1),tuple(selection[key] for key in ('mode','selection','preferred_ordinal','audio_track_index')))
        self.assertEqual(dict(source_ordinal=0,codec='truehd',channels=8,container='mp4',decode=False,passthrough=False),selection['queries'][0])
        self.assertEqual(dict(source_ordinal=1,codec='ac3',channels=6,container='mp4',decode=True,passthrough=False),selection['queries'][1])
        self.assertEqual(facts,selection['basis'])
        self.assertEqual([True,False,False],[track['default'] for track in selection['basis']['tracks']])
        self.assertTrue(any(query.get('codec')=='ac3' and query.get('chcnt')==6 and
                            query.get('container')=='mp4' and query.get('passthru')==0
                            for query in result['audioQueries']))
        self.assertEqual(['GET','GET'],[request['method'] for request in result['requests']])
        self.assertFalse(any('PlaybackInfo' in request['url'] or 'QuickConnect' in request['url'] for request in result['requests']))

    def run_auto(self, *, enabled=True, device=None, mutate=None, features=None, job=None, race=''):
        def source(wire, decision):
            explicit.fixture(wire, decision)
            if mutate:
                mutate(wire, decision)
        return explicit.task.CompatContinuation().job(enabled=enabled,scope=copy.deepcopy(job or self.job),
            mutate=source,device=device or explicit.DEVICE,features=features,race=race)

    def assert_no_auto_handoff(self, result):
        self.assertNotIn('compatContinuation',result['outcome'])
        self.assertNotEqual('task_failed',result['outcome'].get('errorCode'),result['outcome'])
        self.assertFalse(any('PlaybackInfo' in r['url'] for r in result['requests']))

    def aac_qualification(self, job=None):
        job=job or self.job
        return {'schemaVersion':1,'kind':'stock48ae-p7-hdr10-aac2-v1','approved':True,
                'sourceId':job['sourceId'],'profileId':job['profileId'],
                'generation':job['generation'],'sessionRevision':0}

    def aac_only_device(self):
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='if format.container="mp4" and format.codec="aac" and format.chcnt=2 and format.passthru=0 then return {result:true}\n        return {result:false}'
        return device

    def test_qualified_auto_aac_fallback_requires_failed_native_and_copy_lanes(self):
        job=copy.deepcopy(self.job)
        job['params']['instanceQualification']=self.aac_qualification(job)
        result=self.run_auto(job=job,device=self.aac_only_device())
        self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
        continuation=result['outcome']['compatContinuation']
        self.assertEqual('experimental_query_p7_hdr10_aac_fmp4_v1',continuation['eligibilityKind'])
        self.assertEqual(self.aac_qualification(job),continuation['instanceQualification'])
        self.assertIs(True,continuation['autoVersion'])
        self.assertEqual(('731','file:731:audio:0',0),tuple(continuation[key] for key in ('fileId','audioTrackId','audioTrackIndex')))
        self.assertNotIn('playAudioChoice',continuation)
        selection=continuation['autoAudioSelection']
        self.assertEqual(('auto','aac_conversion',0,0),tuple(selection[key] for key in ('mode','selection','preferred_ordinal','audio_track_index')))
        self.assertEqual(self.job['params']['detail']['versions'][0]['autoAudioFacts'],selection['basis'])
        self.assertEqual([False,False,False],[query['decode'] for query in selection['queries']])
        self.assertEqual([False,False,False],[query['passthrough'] for query in selection['queries']])
        self.assertTrue(any(q.get('container')=='ts' and q.get('codec')=='truehd' and q.get('passthru')==0 for q in result['audioQueries']))
        self.assertTrue(any(q.get('container')=='ts' and q.get('codec')=='truehd' and q.get('passthru')==1 for q in result['audioQueries']))

        for invalid_job in (copy.deepcopy(self.job),copy.deepcopy(job)):
            if invalid_job is not self.job and invalid_job['params'].get('instanceQualification'):
                invalid_job['params']['instanceQualification']['profileId']='stale-profile'
            self.assert_no_auto_handoff(self.run_auto(job=invalid_job,device=self.aac_only_device()))

        copied=self.run_auto(job=job,device=explicit.DEVICE)
        copied_continuation=copied['outcome'].get('compatContinuation')
        self.assertIsNotNone(copied_continuation,copied['outcome'])
        self.assertEqual(explicit.KIND,copied_continuation['eligibilityKind'])
        self.assertEqual(1,copied_continuation['audioTrackIndex'])

    def test_chosen_ac3_native_positive_preserves_native_priority_and_source_defaults(self):
        import json
        result=self.run_auto(features=['native_hls_separate_audio_v1'])
        self.assert_no_auto_handoff(result)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        posts=[json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(1,len(posts))
        self.assertEqual(('file:731:audio:1',1),(posts[0]['audio_track_id'],posts[0]['audio_track_index']))
        self.assertFalse(any(r['method']=='DELETE' for r in result['requests']))
        version=result['outcome']['data']['playbackDetail']['versions'][0]
        self.assertEqual('truehd',version['audioCodec'])
        self.assertEqual([True,False,False],[t['isDefault'] for t in version['audioTracks']])
        original=result['outcome']['plan']['autoVersionRequest']
        self.assertTrue(original['autoVersion'])
        self.assertFalse(any(k.lower() in ('audiotrackid','audiotrackindex') for k in original))

    def test_gate_off_caller_flags_cannot_enable_auto_substitution(self):
        baseline=self.run_auto(enabled=False)
        job=copy.deepcopy(self.job)
        job['params'].update(compatPreparationEnabled=True,autoAudioSelection={'audio_track_index':1},eligibilityKind=explicit.KIND)
        attempted=self.run_auto(enabled=False,job=job)
        self.assert_no_auto_handoff(baseline)
        self.assert_no_auto_handoff(attempted)
        self.assertEqual(baseline['requests'],attempted['requests'])

    def test_unknown_preferred_query_and_malformed_or_ambiguous_fresh_facts_do_not_substitute(self):
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='if format.codec="truehd" then return {result:invalid}\n        '+device[key]
        def malformed(wire, decision):
            wire['versions'][0]['effective_audio_track_index']=None
        def ambiguous(wire, decision):
            track=wire['versions'][0]['audio_tracks'][2]
            track['channels']=6
            track['layout']='5.1(side)'
        for result in (self.run_auto(device=device),self.run_auto(mutate=malformed),self.run_auto(mutate=ambiguous)):
            self.assert_no_auto_handoff(result)

    def test_preferred_positive_stays_ordinary_and_pin_or_cap_cannot_handoff(self):
        import json
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='if format.codec="truehd" then return {result:true}\n        '+device[key]
        preferred=self.run_auto(device=device)
        self.assert_no_auto_handoff(preferred)
        for r in preferred['requests']:
            if '/playback/start' in r['url']:
                self.assertNotIn('audio_track_index',json.loads(r['body']))
        job=copy.deepcopy(self.job)
        job['params']['bandwidthCapKbps']=1000
        self.assert_no_auto_handoff(self.run_auto(job=job))
        raced=self.run_auto(race='pin')
        self.assert_no_auto_handoff(raced)
        self.assertFalse(any(r['method']=='POST' for r in raced['requests']))

    def test_mp4_ac3_positive_but_native_ts_six_negative_keeps_nonallocating_handoff(self):
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='if format.container="ts" and format.chcnt=6 then return {result:false}\n        '+device[key]
        result=self.run_auto(device=device,features=['native_hls_separate_audio_v1'])
        self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
        handoff=result['outcome']['compatContinuation']
        self.assertEqual(explicit.KIND,handoff['eligibilityKind'])
        self.assertEqual({'state':'not_allocated'},handoff['nativeClosure'])
        self.assertTrue(handoff['autoVersion'])
        self.assertEqual(1,handoff['audioTrackIndex'])
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])
        for container in ('mp4','ts'):
            self.assertTrue(any(q.get('codec')=='ac3' and q.get('container')==container and
                q.get('chcnt')==6 and q.get('passthru')==0 for q in result['audioQueries']))

    def test_possible_aac_conversion_without_bound_recipe_keeps_proven_mp4_handoff(self):
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='''if format.codec="aac" then return {result:format.passthru=0 and (format.chcnt=invalid or (format.container="ts" and format.chcnt=2))}
        if format.codec="ac3" and format.container="ts" then return {result:false}
        '''+device[key]
        def converted(wire, decision):
            plan=decision['playback_plan']
            plan['effective_recipe'].update(audio_codec='aac',audio_channels=2,audio_layout='stereo')
            plan['claims']['audio'].update(codec='aac',passthrough=False)
            plan['transformations'].append(dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode']))
        result=self.run_auto(device=device,features=['native_hls_separate_audio_v1'],mutate=converted)
        self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
        self.assertEqual(1,result['outcome']['compatContinuation']['audioTrackIndex'])
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])

    def test_exact_ts_support_without_scoped_ac3_admission_cannot_suppress_mp4(self):
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='''if format.codec="aac" then return {result:format.passthru=0 and (format.chcnt=invalid or format.chcnt=2)}
        if format.codec="ac3" and format.container="ts" and format.chcnt=invalid then return {result:false}
        '''+device[key]
        result=self.run_auto(device=device,features=['native_hls_separate_audio_v1'])
        self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])

    def test_preferred_ac3_six_uses_same_pair_for_unproven_native_video(self):
        def preferred(wire,decision):
            wire['versions'][0]['effective_audio_track_index']=1
        bridge=scene.OrdinaryNativeHdr10Scene()
        detail_job=bridge.scene()['tasks'][0]['job']
        def source(wire,decision):
            explicit.fixture(wire,decision)
            preferred(wire,decision)
        detail=explicit.task.CompatContinuation().job(enabled=True,scope=detail_job,
            mutate=source,device=explicit.DEVICE)['outcome']
        job=bridge.scene([detail])['tasks'][1]['job']
        params={k.lower():v for k,v in job['params'].items()}
        self.assertTrue(params['autoversion'])
        self.assertFalse(any(k in params for k in ('audiotrackid','audiotrackindex')))
        result=self.run_auto(job=job,mutate=preferred)
        self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
        handoff=result['outcome']['compatContinuation']
        self.assertEqual(('file:731:audio:1',1),(handoff['audioTrackId'],handoff['audioTrackIndex']))
        choice=handoff['autoAudioSelection']
        self.assertEqual(('preferred',1,1),(choice['selection'],choice['preferred_ordinal'],choice['audio_track_index']))
        self.assertEqual({'state':'present','ordinal':1},choice['basis']['effective_preference'])
        self.assertEqual([True,False,False],[t['default'] for t in choice['basis']['tracks']])
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])

    def test_unknown_or_disabled_native_ts_lane_keeps_known_mp4_route(self):
        key=next(k for k in explicit.DEVICE if 'format.chcnt' in k)
        for guard in ('if format.container="ts" and format.chcnt=6 then return invalid',
                      'if format.container="ts" then return {result:false}'):
            with self.subTest(guard=guard):
                device=dict(explicit.DEVICE)
                device[key]=guard+'\n        '+device[key]
                result=self.run_auto(device=device,features=['native_hls_separate_audio_v1'])
                self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
                self.assertEqual({'state':'not_allocated'},result['outcome']['compatContinuation']['nativeClosure'])
                self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])

    def test_explicit_p7_same_mp4_positive_ts_negative_class_keeps_handoff(self):
        explicit.P7ProducerFlow.setUpClass()
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='if format.container="ts" and format.chcnt=6 then return {result:false}\n        '+device[key]
        result=self.run_auto(job=explicit.P7ProducerFlow.scene_job,device=device,
            features=['native_hls_separate_audio_v1'])
        self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
        handoff=result['outcome']['compatContinuation']
        self.assertFalse(handoff['autoVersion'])
        self.assertEqual(('file:731:audio:1',1),(handoff['audioTrackId'],handoff['audioTrackIndex']))
        self.assertEqual({'state':'not_allocated'},handoff['nativeClosure'])
        self.assertNotIn('autoAudioSelection',handoff)
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])

    def test_unadvertised_passthrough_does_not_override_negative_scoped_decode(self):
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='''if format.codec="ac3" and format.container="ts" and format.chcnt=6 then return {result:format.passthru=1}
        '''+device[key]
        result=self.run_auto(device=device,features=['native_hls_separate_audio_v1'])
        self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])
