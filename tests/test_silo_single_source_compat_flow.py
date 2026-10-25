"""Single-source compatibility through real Task/Scene and SDK/HTTP seams.

Only the existing test-copy rollout gate is enabled. No private policy helpers
or continuation receipts are stubbed; all identities and HTTP fixtures synthetic.
"""
import json,unittest
from tests import test_silo_compat_playback_task as holder
from tests import test_silo_compat_continuation as task
from tests.test_silo_modern_compat_flow import modern_device,KIND


def single_source(wire,decision):
    del wire['versions'][1:]


class SingleSourceCompatFlow(unittest.TestCase):
    def test_single_fresh_source_hands_off_without_native_start_or_stop(self):
        result=task.CompatContinuation().job(device=modern_device(),mutate=single_source)
        self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
        continuation=result['outcome']['compatContinuation']
        self.assertEqual('native_source_unproven',continuation['reason'])
        self.assertEqual('731',continuation['fileId'])
        self.assertEqual(KIND,continuation['eligibilityKind'])
        self.assertEqual({'state':'not_allocated'},continuation['nativeClosure'])
        self.assertFalse(any('/playback/start' in q['url'] or q['method']=='DELETE' for q in result['requests']))
        self.assertTrue(any(q.get('container')=='ts' and q.get('profile')=='main 10' and q.get('level')=='5.0' for q in result['videoQueries']))

    def scene(self,control='media_close',mutate=None,change=None,sdk_overrides=None,duplicate=None):
        envelope=task.CompatContinuation().job(device=modern_device(),mutate=single_source)['outcome']
        self.assertEqual('compat_prepare_required',envelope.get('errorCode'))
        _,wire,decision=task.CompatContinuation().fixture()
        single_source(wire,decision)
        if mutate:mutate(envelope,wire)
        return holder.CompatPlaybackTask().transcript(scene=dict(envelope=envelope,wire=wire,control=control,duplicateEnvelope=duplicate),device_overrides=modern_device(),change=change,sdk_overrides=sdk_overrides)

    def test_single_source_scene_binds_and_back_closes_exact_owned_media(self):
        result=self.scene()
        self.assertTrue(result['scene']['holderCreated'])
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Sessions/Playing/Stopped' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Videos/ActiveEncodings?PlaySessionId=play-fixture' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))

    def test_single_source_failure_revokes_then_consumes_one_same_file_native_resume(self):
        # Observe the queued native job at the SDK scheduling boundary before it executes.
        capture='if child.job.action="playback_start" then m.fixtureResumeJob=ParseJson(FormatJson(child.job))\n '
        result=self.scene(control='media_failure',sdk_overrides={
            'parent=m.top:m.top=child:FixtureChildRunJob():m.top=parent':capture+'parent=m.top:m.top=child:FixtureChildRunJob():m.top=parent',
            'resumeJobs:resumeJobs,':'resumeJob:m.fixtureResumeJob,resumeJobs:resumeJobs,'})
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['loading'])
        self.assertTrue(result['scene']['failureDialog'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertEqual(1,result['scene']['holderCount'])
        self.assertTrue(result['scene']['attempt']['compatibilityAttempted'])
        self.assertEqual('native_resume',result['scene']['attempt']['phase'])
        self.assertTrue(result['scene']['attempt']['resumeConsumed'])
        self.assertEqual([],result['scene']['attempt']['nativeAttemptedFileIds'])
        job=result['scene']['resumeJob']
        self.assertEqual('playback_start',job['action'])
        self.assertEqual('731',job['params']['fileId'])
        self.assertEqual([],job['params']['excludedVersionIds'])
        self.assertEqual(['731'],job['params']['compatExcludedFileIds'])
        starts=[(i,json.loads(q['body'])) for i,q in enumerate(result['requests']) if '/playback/start' in q['url']]
        self.assertEqual(1,len(starts))
        self.assertEqual('731',starts[0][1]['file_id'])
        self.assertLess(next(i for i,q in enumerate(result['requests']) if '/Sessions/Logout' in q['url']),starts[0][0])
        self.assertFalse(result['scene']['cleanupPending'])
        self.assertEqual(1,sum('/QuickConnect/Initiate' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))

    def test_source_bound_level50_hdr10_remains_native_ahead_of_compatibility(self):
        import json
        from pathlib import Path
        def fixture(wire,decision):
            single_source(wire,decision)
            video=wire['versions'][0]['video_tracks'][0]
            for key in list(video):
                if key.startswith('dv_'):del video[key]
            video['video_range_type']='hdr10'
            decision.clear()
            decision.update(json.loads((Path(__file__).parent/'fixtures/silo/hdr10_split_0589_source_derived.json').read_text()))
            plan=decision['playback_plan'];plan['source']['dynamic_range']='hdr10'
            for key in list(plan['source']):
                if key.startswith('dv_') or key.startswith('dolby_vision_'):del plan['source'][key]
            plan['source']['dv_enhancement_layer']='none'
            plan['transformations']=[t for t in plan['transformations'] if t['name']=='hls_separate_audio']
        device=modern_device();device['return "2160p60"']='return "2160p30"'
        result=task.CompatContinuation().job(automatic_hdr10=True,device=device,mutate=fixture,features=['native_hls_separate_audio_v1'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertNotIn('compatContinuation',result['outcome'])
        starts=[json.loads(q['body']) for q in result['requests'] if '/playback/start' in q['url']]
        self.assertEqual(['731'],[q['file_id'] for q in starts])
        self.assertFalse(any(q['method']=='DELETE' for q in result['requests']))

    def test_ambiguous_or_multiple_unproven_sources_never_get_singleton_handoff(self):
        import copy
        def multiple(w,d):
            single_source(w,d)
            extra=copy.deepcopy(w['versions'][0]);extra['file_id']='733';w['versions'].append(extra)
        def ambiguous(w,d):
            single_source(w,d)
            w['playback_variants'].append(copy.deepcopy(w['playback_variants'][0]))
        for mutate in (multiple,ambiguous):
            with self.subTest(mutate=mutate.__name__):
                result=task.CompatContinuation().job(device=modern_device(),mutate=mutate)
                self.assertNotIn('compatContinuation',result['outcome'])

    def test_gate_off_callers_and_changed_owner_cannot_authorize_handoff(self):
        baseline=task.CompatContinuation().job(enabled=False,device=modern_device(),mutate=single_source)
        for settings in ({'enabled':False,'options':{'compatPreparationEnabled':True,'eligibilityKind':KIND}}, {'race':'revision'},{'race':'pin'}):
            with self.subTest(settings=settings):
                result=task.CompatContinuation().job(device=modern_device(),mutate=single_source,**settings)
                self.assertNotIn('compatContinuation',result['outcome'])
                if settings.get('enabled') is False:self.assertEqual(baseline['requests'],result['requests'])

    def test_scene_singleton_reason_rejects_changed_source_identity_or_inventory(self):
        import copy
        def identity(e,w):e['compatContinuation']['nativeSelectedFileId']='732'
        def multiple(e,w):
            extra=copy.deepcopy(w['versions'][0]);extra['file_id']='733';w['versions'].append(extra)
        def ambiguous(e,w):w['playback_variants'].append(copy.deepcopy(w['playback_variants'][0]))
        for mutate in (identity,multiple,ambiguous):
            with self.subTest(mutate=mutate.__name__):
                result=self.scene(mutate=mutate)
                self.assertFalse(result['scene']['holderCreated'])
                self.assertFalse(result['scene']['loading'])
                self.assertEqual([],result['requests'])

    def test_fresh_duplicate_envelope_after_owned_close_cannot_create_second_holder(self):
        device=modern_device();device['"10000000-0000-4000-8000-"']='"20000000-0000-4000-8000-"'
        second=task.CompatContinuation().job(device=device,mutate=single_source,scope={'requestId':42})['outcome']
        self.assertEqual('compat_prepare_required',second.get('errorCode'))
        result=self.scene(control='duplicate',duplicate=second)
        self.assertEqual(1,result['scene']['holderCount'])
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['loading'])
        self.assertEqual(41,result['scene']['attempt']['requestId'])
        self.assertTrue(result['scene']['attempt']['compatibilityAttempted'])
        self.assertEqual(1,sum('/QuickConnect/Initiate' in q['url'] for q in result['requests']))
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))

    def test_missing_source_facts_cap_and_explicit_audio_cannot_bypass_proof(self):
        def unknown(w,d):
            single_source(w,d);w['versions'][0]['video_tracks'][0].pop('dv_bl_compat_id')
        for mutate,options in ((unknown,{}),(single_source,{'bandwidthCapKbps':1000}),(single_source,{'audioTrackId':'file:731:audio:0','audioTrackIndex':0})):
            with self.subTest(options=options,mutate=mutate.__name__):
                result=task.CompatContinuation().job(device=modern_device(),mutate=mutate,options=options)
                self.assertNotIn('compatContinuation',result['outcome'])
