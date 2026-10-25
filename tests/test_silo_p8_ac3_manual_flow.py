"""Explicit Experimental Play keeps duplicate AC3 selection out of Original."""
import json,unittest
from tests import test_silo_compat_continuation as native
from tests.test_silo_modern_compat_flow import modern_device
from tests.test_silo_p8_ac3_compat_policy import KIND

class ManualAC3Flow(unittest.TestCase):
 def start(self,options=None,race=''):
  def source(wire,decision):
   v=wire['versions'][0]
   v['audio_tracks']=[dict(codec=codec,channels=channels,language='en',default=i==0) for i,(codec,channels) in enumerate([('truehd',8),('ac3',6),('ac3',6)])]
  device=modern_device()
  device['format.chcnt<=2 and format.codec="aac"']='(format.chcnt<=2 and format.codec="aac") or (format.codec="ac3" and format.chcnt=6)'
  opts=dict(experimentalOriginal=True,autoVersion=False,audioTrackIndex=1,audioTrackId='file:731:audio:1')
  opts.update(options or {})
  return native.CompatContinuation().job(options=opts,mutate=source,device=device,race=race,p7_enabled=None,automatic_hdr10=None)
 def test_explicit_duplicate_ac3_produces_exact_pinned_continuation_without_native_allocation(self):
  r=self.start();c=r['outcome'].get('compatContinuation')
  self.assertIsNotNone(c,r['outcome'])
  self.assertEqual(KIND,c['eligibilityKind'])
  self.assertEqual(('731',1,'file:731:audio:1',False),(c['fileId'],c['audioTrackIndex'],c['audioTrackId'],c['autoVersion']))
  self.assertEqual(['GET','GET'],[q['method'] for q in r['requests']])
 def test_normal_play_caller_kind_and_stale_owner_cannot_enable_manual_route(self):
  for opts,race in [({'experimentalOriginal':False,'eligibilityKind':KIND},''),({'autoVersion':True},''),({'audioTrackIndex':0,'audioTrackId':'file:731:audio:0'},''),({},'revision'),({},'pin')]:
   with self.subTest(opts=opts,race=race):
    self.assertNotIn('compatContinuation',self.start(opts,race)['outcome'])
 def test_probe_advertises_explicit_duplicate_ac3_with_gets_only(self):
  r=self.start({'probeOnly':True})
  self.assertTrue(r['outcome']['data']['available'],r)
  self.assertEqual(['GET','GET'],[q['method'] for q in r['requests']])
 def scene(self,stale=False,preferences=None,request=None,control='',envelope=None,callback_change='',start_ms=0,statuses=None,playing_callback="",transport=None,scope_change_at="",session_sequence=None):
  from tests.test_silo_compat_playback_task import CompatPlaybackTask
  from tests.test_silo_p8_ac3_compat_policy import P8AC3Policy
  _,wire,_=native.CompatContinuation().fixture()
  wire['versions'][0]['audio_tracks']=[dict(codec=codec,channels=channels,language='en',default=i==0) for i,(codec,channels) in enumerate([('truehd',8),('ac3',6),('ac3',6)])]
  wire['versions'][0]['duration']=60
  data=dict(envelope=self.start()['outcome'],wire=wire,control=control)
  if control.startswith('media'):
   data['envelope']['compatContinuation']['startPositionMs']=start_ms
  if envelope:data['envelope'].update(envelope)
  insert='''
 m.backdropTimer={control:"stop"}:m.backdropFade={control:"stop"}
 node=m.top.createChild("Group"):node.id="libraries"
 m.detailToken=4:m.detailSelectedVersion="731":m.detailVersions=detail.versions
 m.playSelectedVersion="731"
 choices=SiloUIDetailAudioChoices("silo",m.playItem,detail.versions,"731")
 choice=choices[1]:choice.visit=4:choice.sourceId=m.sourceId:choice.profileId=m.profileId:choice.generation=m.generation
 m.playAudioChoice=choice:m.detailAudioChoice=choice
 m.playExperimentalChoice={kind:"experimental_original",visit:4,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,itemId:"fixture-item",fileId:"731",audioSignature:FormatJson(choice),probe:1}
 params.autoVersion=false:params.experimentalOriginal=true:params.audioTrackIndex=1:params.audioTrackId="file:731:audio:1"
'''
  def change(values):
   if statuses:values['statuses']=statuses
   if session_sequence is not None:values['sessionSequence']=session_sequence
   values['metadata']=P8AC3Policy().metadata()
   values['playback']=P8AC3Policy().metadata(True)
  device=modern_device();device['format.codec="eac3"']='format.codec="ac3"'
  if control.startswith('media'):insert+='\n params.startPositionMs='+str(start_ms)+'\n'
  if preferences:
   insert+='\n m.preferences='+json.dumps(preferences).replace('"quality":','quality:').replace('"subtitles":','subtitles:')+'\n'
  for key,value in (request or {}).items():
   insert+='\n params.'+key+'='+json.dumps(value)+'\n'
  if stale:insert+='\n m.playExperimentalChoice.audioSignature="changed"\n'
  callback = '\n if payload.phase="prepared" then '+callback_change+'\n' if callback_change else ''
  overrides={'sub FixtureSceneDeliver(payload as Object)':'sub FixtureSceneDeliver(payload as Object)'+callback,
   'bound:m.sceneVideo.content<>invalid,':'bound:m.sceneVideo.content<>invalid,nativePlayStart:m.fixtureNativePlayStart,currentAfterPlayer:m.fixtureCurrentAfterPlayer,currentWithRetiredDetail:m.fixtureCurrentRetiredDetail,',
   'm.fixtureGenerationContents.Push(m.video.content)':'m.fixtureGenerationContents.Push(m.video.content):m.fixtureNativePlayStart=m.video.content.playStart:m.fixtureCurrentAfterPlayer=SiloUICompatCurrent(m.compatPreparation):m.detailToken++:m.detailAudioChoice=invalid:m.fixtureCurrentRetiredDetail=SiloUICompatCurrent(m.compatPreparation)',
   ' m.fixtureNativeParams=params':insert+'\n m.fixtureNativeParams=params','scene:{holderCreated:true,':'scene:{preferences:m.preferences,holderCreated:true,','scene:{holderCreated:false,':'scene:{failureMessage:m.playbackFailureMessage,failureDialog:m.playbackFailureDialog<>invalid,holderCreated:false,'}
  if transport:
   overrides[' return HttpResponse(request,status,body)']=' if key="compat/playing" then return {ok:false,errorCode:"'+transport+'"}\n return HttpResponse(request,status,body)'
  if control=='media_ack':
   overrides[' onSiloUICompatResult(FixtureSceneEvent(payload))']=' onSiloUICompatResult(FixtureSceneEvent(payload))\n if payload.phase="playing" and m.compatPreparation<>invalid\n'+playing_callback+'\n  if m.compatPreparation.phase="local_stopping" then m.video.state="stopped":onVideoState()\n end if'
  return CompatPlaybackTask().transcript(scene=data,change=change,device_overrides=device,sdk_overrides=overrides,scope_change_at=scope_change_at)
 def test_scene_admits_exact_experimental_ticket_and_prepares_existing_holder(self):
  r=self.scene()
  self.assertNotIn('fixtureError',r,r)
  self.assertTrue(r['scene']['holderCreated'],r)
  self.assertEqual(['prepared','closed'],[v['phase'] for v in r['results']],r)
  self.assertEqual('copied_p8_hdr10_ac3_fmp4',r['results'][0]['class'])
 def test_stale_experimental_audio_ticket_creates_no_holder(self):
  r=self.scene(stale=True)
  self.assertNotIn('fixtureError',r,r)
  self.assertFalse(r['scene']['holderCreated'],r)

 def test_manual_attempt_overrides_saved_playback_preferences_without_changing_them(self):
  for quality,subtitles in [('1080p','auto'),('original','always'),('720p','off'),('480p','forced'),('1080p','on')]:
   with self.subTest(quality=quality,subtitles=subtitles):
    preferences=dict(quality=quality,subtitles=subtitles)
    r=self.scene(preferences=preferences)
    self.assertNotIn('fixtureError',r,r)
    self.assertTrue(r['scene']['holderCreated'],r)
    self.assertEqual(['prepared','closed'],[v['phase'] for v in r['results']],r)
    self.assertEqual(preferences,r['scene']['preferences'])

 def test_conflicting_preferences_cannot_admit_stale_or_nonexperimental_requests(self):
  for stale,request in [(True,{}),(False,{'qualityPreference':'1080p'}),(False,{'subtitleMode':'auto'}),(False,{'experimentalOriginal':False})]:
   with self.subTest(stale=stale,request=request):
    r=self.scene(stale=stale,preferences=dict(quality='1080p',subtitles='auto'),request=request)
    self.assertNotIn('fixtureError',r,r)
    self.assertFalse(r['scene']['holderCreated'],r)
    self.assertEqual([],r['requests'])

 def test_current_rejected_experimental_selection_shows_numbered_failure(self):
  r=self.scene(stale=True)
  self.assertFalse(r['scene']['holderCreated'],r)
  self.assertFalse(r['scene']['loading'],r)
  self.assertFalse(r['scene']['statusVisible'],r)
  self.assertTrue(r['scene']['failureDialog'],r)
  self.assertEqual('#1005: Experimental selection could not be validated. Choose the version and audio again.',r['scene']['failureMessage'])

 def test_stale_or_transitioning_experimental_reply_leaves_new_loading_untouched(self):
  for control in ['stale_token','stale_owner','transition']:
   with self.subTest(control=control):
    r=self.scene(stale=True,control=control)
    self.assertNotIn('fixtureError',r,r)
    self.assertFalse(r['scene']['holderCreated'],r)
    self.assertTrue(r['scene']['loading'],r)
    self.assertTrue(r['scene']['statusVisible'],r)
    self.assertFalse(r['scene']['failureDialog'],r)

 def test_accepted_experimental_holder_has_no_failure_dialog(self):
  r=self.scene()
  self.assertNotIn('fixtureError',r,r)
  self.assertTrue(r['scene']['holderCreated'],r)
  self.assertFalse(r['scene']['failureDialog'],r)

 def test_ordinary_playback_failure_keeps_existing_error(self):
  r=self.scene(envelope={'errorCode':'unsupported_stream'})
  self.assertNotIn('fixtureError',r,r)
  self.assertFalse(r['scene']['holderCreated'],r)
  self.assertFalse(r['scene']['loading'],r)
  self.assertTrue(r['scene']['failureDialog'],r)
  self.assertEqual('#2008: This playback stream is unsupported.',r['scene']['failureMessage'])

 def test_prepared_manual_holder_binds_owned_plan_through_real_callback(self):
  r=self.scene(control='media_duplicate',preferences=dict(quality='1080p',subtitles='auto'))
  self.assertNotIn('fixtureError',r,r)
  self.assertTrue(r['scene']['bound'],r)
  self.assertEqual(('silo_compat','731',1),(r['scene']['plan']['transport'],r['scene']['plan']['versionId'],r['scene']['plan']['planGeneration']))
  self.assertTrue(r['scene']['privatePayloadCleared'],r)
  self.assertTrue(r['scene']['currentAfterPlayer'],r)
  self.assertTrue(r['scene']['currentWithRetiredDetail'],r)
  self.assertEqual(1,len(r['scene']['generationHeaders']),r)
  self.assertEqual(r['scene']['attempt']['playbackAttemptId'],r['scene']['plan']['attemptId'])
  self.assertIn('binding',[v['phase'] for v in r['results']],r)

 def test_prepared_manual_holder_rejects_stale_consent_and_scope_before_binding(self):
  for change in ['m.playToken++','m.profileId="changed"','m.playExperimentalChoice.audioSignature="changed"','m.playSelectedVersion="other"','m.compatPreparation.intent.audioTrackIndex=2','m.compatPreparation.snapshot.videoMode="1080p"','m.compatPreparation.intent.autoVersion=true']:
   with self.subTest(change=change):
    r=self.scene(control='media_duplicate',callback_change=change)
    self.assertNotIn('fixtureError',r,r)
    self.assertFalse(r['scene']['bound'],r)
    self.assertEqual(0,r['mediaRequests'],r)
    self.assertTrue(r['privateCleared'],r)
    self.assertTrue(r['results'][-1]['credentialRevoked'],r)

 def test_manual_resume_preserves_existing_server_start_and_native_timeline(self):
  r=self.scene(control='media_duplicate',start_ms=25000)
  self.assertNotIn('fixtureError',r,r)
  self.assertTrue(r['scene']['bound'],r)
  self.assertEqual((25000,0),(r['scene']['plan']['startPositionMs'],r['scene']['plan']['timelineOffsetMs']))
  self.assertEqual(25,r['scene']['nativePlayStart'])
  playback=next(q for q in r['requests'] if '/PlaybackInfo' in q['url'])
  self.assertEqual(250000000,json.loads(playback['body'])['StartTimeTicks'])
  self.assertTrue(r['scene']['currentAfterPlayer'],r)

 def test_playing_ack_refusal_closes_owned_media_as_session_failure(self):
  r=self.scene(control='media_ack',statuses={'compat/playing':503})
  self.assertNotIn('fixtureError',r,r)
  playing=next(v for v in r['results'] if v['phase']=='playing')
  self.assertFalse(playing['ok'],playing)
  self.assertTrue(r['scene']['released'],r)
  self.assertTrue(r['results'][-1]['credentialRevoked'],r)
  self.assertIn('#3004',r['scene']['failureMessage'])
  self.assertIn('playing_ack',r['scene']['failureMessage'])
  self.assertIn('invalid_compat_response',r['scene']['failureMessage'])
  self.assertIn('HTTP 503',r['scene']['failureMessage'])

 def test_playing_confirmation_preserves_transport_lookup_and_owner_failures_after_cleanup(self):
  cases=[
   ({'transport':'network_timeout'},'playing_ack','network_timeout'),
   ({'transport':'network_error'},'playing_ack','network_error'),
   ({'session_sequence':[[{'Id':'bad/id'}],[]]},'active_session','invalid_compat_response'),
   ({'scope_change_at':'compat/playing'},'playing_ack','session_changed'),
   ({'scope_change_at':'compat/sessions'},'active_session','session_changed'),
  ]
  for options,phase,error in cases:
   with self.subTest(phase=phase,error=error,options=options):
    r=self.scene(control='media_ack',**options)
    self.assertNotIn('fixtureError',r,r)
    playing=next(v for v in r['results'] if v['phase']=='playing')
    self.assertEqual((False,phase,error),(playing['ok'],playing['compatFailurePhase'],playing['errorCode']))
    self.assertTrue(r['scene']['released'],r)
    self.assertTrue(r['results'][-1]['credentialRevoked'],r)
    message=r['scene']['failureMessage']
    self.assertIn('#3004',message)
    self.assertIn(phase,message)
    self.assertIn(error,message)
    self.assertNotIn('session changed',message)
    self.assertNotIn('Bearer',message)
    self.assertNotIn('https://',message)

 def test_missing_active_session_preserves_reason_after_later_confirmed_cleanup(self):
  r=self.scene(control='media_ack',session_sequence=[[],[{'Id':'play-fixture'}],[]])
  self.assertNotIn('fixtureError',r,r)
  playing=next(v for v in r['results'] if v['phase']=='playing')
  self.assertEqual('active_unconfirmed',playing['errorCode'])
  self.assertTrue(r['scene']['released'],r)
  self.assertTrue(r['results'][-1]['credentialRevoked'],r)
  self.assertIn('active_session: active_unconfirmed',r['scene']['failureMessage'])

 def test_actual_start_playing_confirmation_and_progress_keep_manual_owner(self):
  r=self.scene(control='media_progress')
  self.assertNotIn('fixtureError',r,r)
  self.assertEqual(['prepared','binding','playing','progress'],[v['phase'] for v in r['results']])
  self.assertTrue(r['results'][2]['activeConfirmed'])
  self.assertTrue(r['results'][3]['ok'])
  self.assertEqual('player',r['scene']['returnView'])
  self.assertEqual('play',r['scene']['nativeControl'])
  self.assertTrue(r['scene']['currentAfterPlayer'])
  self.assertTrue(r['scene']['privatePayloadCleared'])
  self.assertFalse(r['scene']['failureDialog'])

 def test_actual_decoder_callback_preserves_native_failure_after_cleanup(self):
  r=self.scene(control='media_ack',playing_callback='  m.video.state="error":onVideoState()')
  self.assertNotIn('fixtureError',r,r)
  self.assertTrue(r['results'][2]['activeConfirmed'])
  self.assertTrue(r['results'][-1]['credentialRevoked'])
  self.assertIn('#3001',r['scene']['failureMessage'])

 def test_actual_buffering_deadline_preserves_timeout_after_cleanup(self):
  callback='  m.video.state="buffering"\n  m.playWaitClock={TotalMilliseconds:function() as Integer\n   return 120001\n  end function}\n  onProgressTimer()'
  r=self.scene(control='media_ack',playing_callback=callback)
  self.assertNotIn('fixtureError',r,r)
  self.assertTrue(r['results'][-1]['credentialRevoked'])
  self.assertIn('#3002',r['scene']['failureMessage'])
