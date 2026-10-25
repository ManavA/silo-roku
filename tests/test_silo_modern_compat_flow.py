"""HOST-only modern P8 TS query branch through real producer/holder/Scene.

SDK, HTTP/session and SG scheduling seams only. Preparation is test-enabled in
producer copies; shipping preparation and Original flags remain untouched.
The optional kind is provenance within this retained attempt, not a signature.
"""
import copy
import json
import unittest
from tests import test_silo_compat_continuation as native
from tests import test_silo_compat_playback_task as holder

KIND='experimental_query_p8_ts_v1'

def modern_device(model='4850X', main51=False):
    return {'return "C000X"':'return "'+model+'"',
            'ModelNumber:"C208X"':'ModelNumber:"'+model+'"',
            'return "TV"':'return "STB"',
            'if m.rejectMain10 = true':'if format.codec="hevc" and format.profile="main 10" and format.level="5.1" then return {result:'+('true' if main51 else 'false')+'}\n        if m.rejectMain10 = true'}

class ModernCompatFlow(unittest.TestCase):
    def continuation(self,model='4850X',**changes):
        device=changes.pop('device',modern_device(model))
        return native.CompatContinuation().job(device=device,**changes)

    def test_gated_producer_mints_modern_kind_from_exact_level50_ts_proof(self):
        for model in ('4850X','3820X','future-fixture'):
            with self.subTest(model=model):
                result=self.continuation(model)
                self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
                c=result['outcome']['compatContinuation']
                self.assertEqual(KIND,c.get('eligibilityKind'))
                self.assertEqual(('731','file:731:audio:0',0), (c['fileId'],c['audioTrackId'],c['audioTrackIndex']))
                self.assertEqual({'state':'not_allocated'},c['nativeClosure'])
                self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))
                self.assertTrue(any(q.get('container')=='ts' and q.get('profile')=='main 10' and q.get('level')=='5.0' for q in result['videoQueries']))

    def scene(self,control='media_close',mutate=None,change=None,device=None,**options):
        envelope=self.continuation()['outcome']
        self.assertEqual('compat_prepare_required',envelope.get('errorCode'))
        _,wire,_=native.CompatContinuation().fixture()
        data=dict(envelope=copy.deepcopy(envelope),wire=wire,control=control)
        if mutate:mutate(data['envelope'])
        overrides=modern_device();overrides.update(device or {})
        return holder.CompatPlaybackTask().transcript(scene=data,change=change,device_overrides=overrides,**options)

    def assert_owned_logout(self,result,media=False):
        self.assertTrue(result['privateCleared'])
        self.assertTrue(result['results'][-1]['credentialRevoked'],result['results'])
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))
        for q in result['requests']:
            if 'compat.example' in q['url'] and '/PlaybackInfo' in q['url']:
                self.assertEqual('Bearer '+holder.TOKEN,q['headers'].get('Authorization'))
                self.assertNotIn(holder.TOKEN,q['url'])
        if media:
            self.assertEqual(1,sum('/Sessions/Playing/Stopped' in q['url'] for q in result['requests']))
            self.assertEqual(1,sum('/Videos/ActiveEncodings?PlaySessionId=play-fixture' in q['url'] for q in result['requests']))
        self.assertNotIn(holder.TOKEN,json.dumps(result['results']))

    def test_default_off_and_caller_flags_keep_exact_ordinary_request(self):
        baseline=self.continuation(enabled=False)
        for options in ({'compatPreparationEnabled':True},{'eligibilityKind':KIND},{'eligibilityKind':'wrong-kind'}):
            with self.subTest(options=options):
                result=self.continuation(enabled=False,options=options)
                self.assertEqual(baseline['requests'],result['requests'])
                self.assertNotIn('compatContinuation',result['outcome'])
        result=self.continuation(enabled=False,options={'experimentalOriginal':True})
        self.assertNotIn('compatContinuation',result['outcome'])
        self.assertEqual('invalid_request',result['outcome'].get('errorCode'))

    def test_modern_holder_unused_prepare_revokes_without_media_release(self):
        result=holder.CompatPlaybackTask().transcript(options={'eligibilityKind':KIND},device_overrides=modern_device())
        self.assertEqual(['prepared','closed'],[r['phase'] for r in result['results']])
        self.assert_owned_logout(result)
        self.assertTrue(result['results'][-1]['mediaNeverRequested'])
        playback=next(q for q in result['requests'] if '/PlaybackInfo' in q['url'])
        body=json.loads(playback['body'])
        self.assertEqual((holder.SOURCE,2,-1,250000000),(body['MediaSourceId'],body['AudioStreamIndex'],body['SubtitleStreamIndex'],body['StartTimeTicks']))

    def test_modern_scene_binds_then_back_drains_exact_owner(self):
        result=self.scene()
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertEqual([],result['scene']['retiredHeaders'])
        self.assertEqual({},result['scene']['agentHeaders'])
        self.assert_owned_logout(result,media=True)
        plays=[json.loads(q['body']) for q in result['requests'] if q['url'].endswith('/Sessions/Playing')]
        self.assertEqual(1,len(plays))
        self.assertEqual(('play-fixture',1,-1),(plays[0]['PlaySessionId'],plays[0]['AudioStreamIndex'],plays[0]['SubtitleStreamIndex']))

    def test_scene_missing_or_wrong_modern_kind_cannot_prepare(self):
        for value in (None,'wrong-kind',False):
            with self.subTest(value=value):
                def mutate(e):
                    if value is None:e['compatContinuation'].pop('eligibilityKind')
                    else:e['compatContinuation']['eligibilityKind']=value
                result=self.scene(mutate=mutate)
                self.assertFalse(result['scene']['holderCreated'])
                self.assertFalse(result['scene']['loading'])
                self.assertFalse(result['scene']['statusVisible'])
                self.assertEqual([],result['requests'])

    def test_prepare_rejects_wrong_kind_and_selected_audio_without_auth(self):
        for options in ({'eligibilityKind':'wrong-kind'},{'eligibilityKind':KIND,'audioTrackIndex':0,'audioTrackId':'file:731:audio:0'}):
            with self.subTest(options=options):
                result=holder.CompatPlaybackTask().transcript(options=options,device_overrides=modern_device())
                self.assertFalse(result['results'][-1]['ok'])
                self.assertFalse(any('compat.example' in q['url'] for q in result['requests']))

    def test_pin_cancel_and_profile_change_preserve_owned_revocation(self):
        for options in ({'pin_change_at':'native/approve'},{'scope_change_at':'compat/collect'},{'cancel_at':'compat/playback'}):
            with self.subTest(options=options):
                result=holder.CompatPlaybackTask().transcript(options={'eligibilityKind':KIND},device_overrides=modern_device(),**options)
                self.assert_owned_logout(result)
                self.assertFalse(any(r.get('phase')=='prepared' for r in result['results']))

    def test_wrong_ts_video_or_audio_receipt_retires_owned_unused_credential(self):
        def wrong_ts(v):v['playback']['MediaSources'][0]['TranscodingContainer']='mp4'
        def wrong_video(v):v['metadata']['MediaSources'][0]['MediaStreams'][0]['Width']=1920
        def wrong_audio(v):v['playback']['MediaSources'][0]['DefaultAudioStreamIndex']=1
        for change in (wrong_ts,wrong_video,wrong_audio):
            with self.subTest(change=change.__name__):
                result=holder.CompatPlaybackTask().transcript(options={'eligibilityKind':KIND},device_overrides=modern_device(),change=change)
                self.assertFalse(result['results'][-1]['ok'])
                self.assert_owned_logout(result)
                self.assertTrue(result['results'][-1]['mediaNeverRequested'])

    def test_modern_seek_uses_same_kind_and_exact_selected_source(self):
        result=self.scene(control='media_seek')
        self.assertTrue(result['scene']['bound'])
        self.assertEqual(2,result['scene']['plan']['planGeneration'])
        infos=[json.loads(q['body']) for q in result['requests'] if '/PlaybackInfo' in q['url']]
        self.assertEqual([250000000,9000000000],[q['StartTimeTicks'] for q in infos])
        self.assertTrue(all(q['MediaSourceId']==holder.SOURCE and q['AudioStreamIndex']==1 and q['SubtitleStreamIndex']==-1 for q in infos))
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))

    def test_seek_fresh_source_drift_closes_without_second_negotiation(self):
        def change(v):
            v['reanchorDetail']=copy.deepcopy(v['detail'])
            v['reanchorDetail']['versions'][0]['video_tracks'][0]['level']=153
        result=self.scene(control='media_changed_source',change=change)
        self.assertFalse(result['scene']['bound'])
        self.assertTrue(result['scene']['released'])
        self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
        self.assert_owned_logout(result,media=True)

    def test_lost_bind_command_kind_refuses_release_but_preserves_owned_logout(self):
        boundary=' onSiloUICompatResult(FixtureSceneEvent(payload))\n'
        changed=boundary+''' if payload.phase="prepared" and m.fixtureHolder.command.action="bind"
  command=ParseJson(FormatJson(m.fixtureHolder.command)):command.Delete("eligibilityKind")
  m.fixtureHolder.command=command
 end if
'''
        result=self.scene(sdk_overrides={boundary:changed})
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertTrue(any(r['phase']=='binding_refused' for r in result['results']))
        self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
        self.assertFalse(any(q['url'].endswith('/Sessions/Playing') for q in result['requests']))
        self.assert_owned_logout(result)

    def test_still_eligible_output_change_after_prepare_prevents_bind_and_revokes(self):
        boundary=' onSiloUICompatResult(FixtureSceneEvent(payload))\n'
        changed=' if payload.phase="prepared" then FixtureSiloDevice().videoMode="2160p30"\n'+boundary
        result=self.scene(sdk_overrides={boundary:changed})
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertFalse(any(q['url'].endswith('/Sessions/Playing') for q in result['requests']))
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))
        self.assert_owned_logout(result)

    def test_modern_failure_drains_then_reuses_one_native_h264_start(self):
        result=self.scene(control='media_failure')
        self.assert_owned_logout(result,media=True)
        requests=result['requests']
        starts=[(i,json.loads(q['body'])) for i,q in enumerate(requests) if '/playback/start' in q['url']]
        self.assertEqual(1,len(starts))
        ordinal,body=starts[0]
        self.assertEqual('732',body['file_id'])
        self.assertEqual('original',body['quality_preference'])
        self.assertGreaterEqual(body['start_position'],42)
        self.assertLess(next(i for i,q in enumerate(requests) if '/Sessions/Logout' in q['url']),ordinal)
        self.assertEqual(1,sum('/QuickConnect/Initiate' in q['url'] for q in requests))

    def test_documented_dv_and_b10_output_modes_reach_real_modern_producer(self):
        for mode in ('2160p60b10','2160p60Dv'):
            with self.subTest(mode=mode):
                device=modern_device();device['return "2160p60"']='return "'+mode+'"'
                result=self.continuation(device=device)
                self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'))
                self.assertEqual(KIND,result['outcome']['compatContinuation'].get('eligibilityKind'))
                self.assertTrue(any(q.get('container')=='ts' and q.get('profile')=='main 10' and q.get('level')=='5.0' for q in result['videoQueries']))
                self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))

    def test_lost_seek_command_kind_closes_owned_media_without_reallocation(self):
        boundary='   m.video.state="stopped":onVideoState():m.top=parent\n   return invalid\n  end if\n  if m.sceneData.control="media_roundtrip"'
        changed='''   m.video.state="stopped":onVideoState():m.top=parent
   if parent.command.action<>"seek" then throw "SDK expected actual seek command"
   altered=ParseJson(FormatJson(parent.command)):altered.Delete("eligibilityKind")
   parent.command=altered
   if parent.command.DoesExist("eligibilityKind") then throw "SDK marker removal failed"
   return invalid
  end if
  if m.sceneData.control="media_roundtrip"'''
        result=self.scene(control='media_seek',sdk_overrides={boundary:changed})
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertTrue(any(r['phase']=='seek_refused' for r in result['results']))
        self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))
        self.assert_owned_logout(result,media=True)

    def test_fresh_decline_hides_preparing_panel_but_stale_callback_preserves_it(self):
        def wrong(e):e['compatContinuation']['eligibilityKind']='wrong-kind'
        for control,visible in (('media_close',False),('stale_token',True),('stale_owner',True)):
            with self.subTest(control=control):
                result=self.scene(control=control,mutate=wrong)
                self.assertFalse(result['scene']['holderCreated'])
                self.assertEqual(visible,result['scene']['statusVisible'])
                self.assertEqual(visible,result['scene']['loading'])
                self.assertEqual([],result['requests'])

    def test_failed_owned_logout_blocks_native_resume(self):
        def change(v):v['statuses']={'compat/logout':503}
        result=self.scene(control='media_failure',change=change)
        self.assertTrue(result['results'][-1]['cleanupUnconfirmed'])
        self.assertFalse(result['results'][-1]['credentialRevoked'])
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Sessions/Playing/Stopped' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Videos/ActiveEncodings?PlaySessionId=play-fixture' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))

    def test_proven_native_hdr10_precedes_modern_compatibility(self):
        from tests.test_silo_native_hdr10 import NativeHdr10
        for model in ('4850X','3820X'):
            with self.subTest(model=model):
                result=NativeHdr10().start(device=modern_device(model,main51=True))
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                self.assertNotIn('compatContinuation',result['outcome'])
                starts=[json.loads(q['body']) for q in result['requests'] if '/playback/start' in q['url']]
                self.assertEqual(['731'],[q['file_id'] for q in starts])
                self.assertEqual('hls',result['outcome']['plan']['streamFormat'])
                self.assertFalse(any(q['method']=='DELETE' for q in result['requests']))

    def test_still_eligible_output_change_during_seek_closes_without_reallocation(self):
        boundary='   m.video.state="stopped":onVideoState():m.top=parent\n   return invalid\n  end if\n  if m.sceneData.control="media_roundtrip"'
        changed='   m.video.state="stopped":onVideoState():m.top=parent\n   if parent.command.action<>"seek" then throw "SDK expected actual seek command"\n   FixtureSiloDevice().videoMode="2160p30"\n   return invalid\n  end if\n  if m.sceneData.control="media_roundtrip"'
        result=self.scene(control='media_seek',sdk_overrides={boundary:changed})
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertTrue(any(r['phase']=='seek_refused' for r in result['results']))
        self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
        self.assert_owned_logout(result,media=True)

    def test_expired_credential_cannot_bind_or_start_native_before_owned_cleanup(self):
        def change(v):v['statuses']={'compat/playing':401}
        result=self.scene(change=change)
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))
        self.assert_owned_logout(result,media=True)
