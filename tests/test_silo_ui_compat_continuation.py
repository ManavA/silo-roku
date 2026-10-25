"""Real Task envelope → Scene callback → one persistent prepare/unused-close lifetime.

Only SDK factories, fields, HTTP/session and callback scheduling are substituted.
The host shares m while swapping m.top at SDK component callback boundaries;
this is not evidence of native SceneGraph scheduling or media delivery.
"""
import copy,unittest
from tests import test_silo_compat_continuation as native_fixture
from tests import test_silo_compat_playback_task as holder_fixture
SCENE_SDK='''
function FixtureCompatTimer() as Object
 return {control:"stop",duration:1,repeat:true,observeField:sub(field as String,callback as String)
 end sub}
end function

function FixtureSceneRevisionSection() as Object
 return {Exists:function(key as String) as Boolean
 return key="revision"
 end function,Read:function(key as String) as String
 return "0"
 end function}
end function

function FixtureSceneAgent() as Object
 return {headers:{},SetCertificatesFile:sub(path as String)
 end sub,AddHeader:sub(name as String,value as String)
 m.headers[name]=value
 end sub}
end function
sub FixtureVideoSetHttpAgent(agent as Object)
 m.fixtureAgentHeaders=agent.headers
end sub
function FixtureUnusedAgent() as Object
 return {SetCertificatesFile:sub(path as String)
 end sub}
end function
function FixtureDialog() as Object
 return {observeField:sub(field as String,callback as String)
 end sub}
end function
function FixtureHolder() as Object
 m.fixtureHolderCount=NumberOr(m.fixtureHolderCount,0)+1
 if m.sceneData.control="node_failure" then return invalid
 m.fixtureHolder={command:invalid,cancelled:false,result:invalid,observing:false,observeField:sub(field as String,callback as Dynamic)
 m.observing=true
 end sub,unobserveField:sub(field as String)
 m.observing=false
 end sub}
 return m.fixtureHolder
end function
function FixtureSceneEvent(payload as Object) as Object
 return {payload:payload,getData:function() as Object
 return m.payload
 end function}
end function
sub FixtureSecondOwnerProbe(kind as String)
 before=m.requestId
 m.view="detail":m.zone="detailButtons":m.pillGroups={}:m.manualFocus=m.top.createChild("Group")
 for each id in ["home","detail","library","libraries","search","onboarding","audio","audioBrowse","streaming","ebook","ebookBrowse","fadeLeft","fadeBottom","avatarBg"]
  node=m.top.createChild("Group"):node.id=id
 end for
 m.nav=m.top.createChild("Group"):m.backdrop=m.top.createChild("Group"):m.backdropOld=m.top.createChild("Group")
 m.backdropTimer={control:"stop"}:m.backdropFade={control:"stop"}
 for each id in ["audioTitle","audioStatus"]
  node=m.top.createChild("Label"):node.id=id
 end for
 m.audioTimer={control:"stop"}:m.audioToken=0:m.audioQueue=[]
 m.audioNode={state:"stopped",content:invalid,setHttpAgent:sub(agent as Object)
 end sub}
 detail=ScopeCatalogData(DecodeSiloResponse("detail",FormatJson(m.sceneData.wire),{sourceId:m.sourceId}).data,m.sourceId)
 if kind="video" then PlayerPrebuffer(m.playItem,m.playVersions,[],detail)
 if kind="hero"
  m.view="home":m.zone="heroButtons":m.heroItem=m.playItem:m.homeRows=[{sectionType:"continue_watching",items:[m.playItem]}]
  PlayerSyncHeroPrebuffer()
 end if
 if kind="audio_open" then SiloUIAudioOpen("book-fixture")
 if kind="audio_late" or kind="audio_tick"
  m.view="audio":m.audioScope=HomeProgressScope():m.audioSleepMs=0
  queue=[{fileId:"audio-file",durationMs:60000,offsetMs:0}]
  m.audioBook={itemId:"book-fixture",title:"Fixture audio",durationMs:60000}:m.audioQueue=queue
  if kind="audio_late" then SiloUIAudioResult("audio_detail",{ok:true},{itemId:"book-fixture",title:"Fixture audio",queue:queue,resumeMs:0},m.audioToken)
  if kind="audio_tick" then m.audioNext={index:0,localMs:0}
  onSiloUIAudioTick()
 end if
 m.secondOwnerRequests=m.requestId-before
end sub
sub FixtureBeginTransition(action as String)
  m.view="onboarding":m.zone="":m.pillGroups={}
  m.manualFocus=m.top.createChild("Group")
  for each field in ["obEyebrow","obTitle","obBody","obCode"]
   m[field]=m.top.createChild("Label")
  end for
  m.obButtons=m.top.createChild("Group"):m.obButtons.AddFields({content:invalid,numRows:1,jumpToItem:0})
  for each id in ["obChoiceViewport","obMore","avatarBg"]
   node=m.top.createChild("Group"):node.id=id
  end for
  m.keyboard=m.top.createChild("Label"):m.searchTimer={control:"stop"}
  SiloUIBeginTransition({action:action})
end sub
sub FixtureSceneDeliver(payload as Object)
 duplicate=invalid
 if payload.phase="binding" and m.sceneData.control="media_oldgen" and payload.planGeneration=1
  m.fixtureOldBinding=ParseJson(FormatJson(m.fixtureHolder.privateBinding)):m.fixtureOldBindingResult=ParseJson(FormatJson(payload))
 end if
 ' Legacy unused-holder cases now explicitly cancel through the real Player callback.
 if payload.phase="prepared" and Left(m.sceneData.control,5)<>"media" and m.sceneData.control<>"back" and Left(m.sceneData.control,7)<>"second_" and m.sceneData.control<>"signout" and m.sceneData.control<>"switch_profile" and Left(m.sceneData.control,6)<>"retry_"
  PlayerCancelPreparation()
 end if
 if payload.phase="binding" and m.sceneData.control="media_duplicate" then duplicate=ParseJson(FormatJson(m.fixtureHolder.privateBinding))
 if payload.phase="prepared" and (m.sceneData.control="back" or Left(m.sceneData.control,7)="second_")
  PlayerCancelPreparation()
  m.fixtureObserverRetained=m.fixtureHolder.observing and m.compatPreparation<>invalid
  if Left(m.sceneData.control,7)="second_" then FixtureSecondOwnerProbe(Mid(m.sceneData.control,8))
 end if
 if payload.phase="closed" and m.sceneData.control="cancel_cached_prepare"
  payload=ParseJson(FormatJson(payload)):payload.commandId=m.compatPreparation.prepareCommandId:payload.cancelled=true
 end if
 if payload.phase="closed" and m.sceneData.control="malformed_closed"
  payload=ParseJson(FormatJson(payload)):payload.Delete("cleanupUnconfirmed")
 end if
 if payload.phase="prepared" and (m.sceneData.control="signout" or m.sceneData.control="switch_profile" or Left(m.sceneData.control,6)="retry_")
  FixtureBeginTransition(m.sceneData.control.Replace("retry_",""))
  m.fixtureObserverRetained=m.fixtureHolder.observing and m.compatPreparation<>invalid
 end if
 onSiloUICompatResult(FixtureSceneEvent(payload))
 if payload.phase="binding" and m.sceneData.control="media_oldgen" and payload.planGeneration=2
  current=m.video.content
  m.fixtureHolder.privateBinding=m.fixtureOldBinding
  onSiloUICompatResult(FixtureSceneEvent(m.fixtureOldBindingResult))
  m.fixtureOldGenerationPreserved=current.isSameNode(m.video.content) and m.fixtureHolder.privateBinding=invalid
 end if
 if duplicate<>invalid
  before=m.video.content
  m.fixtureHolder.privateBinding=duplicate
  onSiloUICompatResult(FixtureSceneEvent(payload))
  m.fixtureDuplicateRebound=not before.isSameNode(m.video.content)
 end if
 if payload.phase="closed" and payload.cleanupUnconfirmed=false and (m.sceneData.control="new_intent" or m.sceneData.control="postclose_video" or m.sceneData.control="postclose_hero") and not m.fixtureDuplicateDelivered
  m.fixtureDuplicateDelivered=true
  if m.sceneData.control="postclose_video" then FixtureSecondOwnerProbe("video")
  if m.sceneData.control="postclose_hero" then FixtureSecondOwnerProbe("hero")
  m.generation++
  m.upNextTimer={control:"stop"}:m.playerCue=m.top.createChild("Group")
  m.video.AddFields({playbackActionButtons:[]})
  PlayItem(m.playItem,25000)
  child=m.pending["42"].task:FixtureScheduleChild(child):onApiResult(FixtureSceneEvent(child.result))
  onApiResult(FixtureSceneEvent(m.sceneData.duplicateEnvelope))
 end if
 if payload.phase="closed" and payload.cleanupUnconfirmed=false and Left(m.sceneData.control,15)="pending_control"
  action=Mid(m.sceneData.control,17)
  m.pending["control"]={purpose:"audio_select",task:{job:{action:action}}}
  before=m.requestId
  m.upNextTimer={control:"stop"}:m.playerCue=m.top.createChild("Group")
  m.video.AddFields({playbackActionButtons:[]})
  PlayItem(m.playItem,25000)
  m.secondOwnerRequests=m.requestId-before
 end if
 if payload.phase="closed" and payload.cleanupUnconfirmed=false and m.sceneData.control="invalid_selector"
  PlayItem(m.playItem,25000,"",{visit:-99})
 end if
 if payload.phase="closed" and payload.cleanupUnconfirmed=false and m.sceneData.control="duplicate" and not m.fixtureDuplicateDelivered
  m.fixtureDuplicateDelivered=true:m.playLoading=true
  Api("playback_start",m.fixtureNativeParams,"play_start",m.playToken)
  onApiResult(FixtureSceneEvent(m.sceneData.duplicateEnvelope))
 end if
 if payload.cleanupUnconfirmed=true and m.sceneData.control="media_retry_probe" and not m.sceneRetryQueued
  m.sceneRetryBefore=m.fixtureHolder.command.commandId
  m.values.statuses["compat/revocation"]=401:m.values.statuses["compat/stopped"]=401:m.values.statuses["compat/delete"]=401
  ObChoose({action:"cleanup_retry"})
  m.sceneRetryAfter=m.fixtureHolder.command.commandId:m.sceneRetryQueued=true
 end if
 if payload.cleanupUnconfirmed=true and m.sceneData.control="media_retry" and not m.sceneRetryQueued
  m.sceneRetryBefore=m.fixtureHolder.command.commandId
  m.values.statuses["compat/stopped"]=204
  ObChoose({action:"cleanup_retry"})
  m.sceneRetryAfter=m.fixtureHolder.command.commandId
  m.sceneRetryQueued=true
 end if
 if payload.cleanupUnconfirmed=true and m.sceneData.control="failed_second_audio_open"
  PlayerCancelPreparation()
  FixtureSecondOwnerProbe("audio_open")
 end if
 if payload.phase="closed" and payload.cleanupUnconfirmed=false and Left(m.sceneData.control,7)="normal_" then FixtureSecondOwnerProbe(Mid(m.sceneData.control,8))
 if payload.cleanupUnconfirmed=true and Left(m.sceneData.control,6)="retry_" and not m.sceneRetryQueued
  m.sceneRetryBefore=m.fixtureHolder.command.commandId
  ObChoose({action:"cleanup_retry"})
  m.sceneRetryAfter=m.fixtureHolder.command.commandId
  m.sceneRetryQueued=true:m.values.statuses["compat/logout"]=204
 end if
end sub
sub FixtureSceneStart(data as Object)
 m.fixtureDuplicateDelivered=false
 m.provider="silo":m.sourceId="silo:https://silo.example":m.profileId="fixture-owner":m.generation=7
 m.view="detail":m.zone="detailButtons":m.pending={}:m.cleanupTickets={}:m.requestId=40:m.playToken=1:m.playLoading=true
 m.preferences={subtitles:"off",quality:"original"}:m.trackPref={}:m.trackPrefLanes={}:m.playMarkers=[]:m.originalGeneration=0
 m.playItem={itemId:"fixture-item",type:"movie",title:"Fixture",durationMs:7200000}
 detail=ScopeCatalogData(DecodeSiloResponse("detail",FormatJson(data.wire),{sourceId:m.sourceId}).data,m.sourceId)
 m.playClock=CreateObject("roTimespan")
 m.playVersions=detail.versions:m.playSelectedVersion="":m.playAudioChoice=invalid:m.playExperimentalChoice=invalid
 m.top=CreateObject("roSGNode","Group"):m.top.AddFields({dialog:invalid,memoryPressure:0})
 m.sceneTop=m.top:m.video=CreateObject("roSGNode","Node"):m.video.AddFields({content:invalid,control:"",visible:false})
 m.playerStatusPanel=m.top.createChild("Group"):m.playerStatusPanel.id="playerStatusPanel"
 m.playerStatusTitle=m.top.createChild("Label"):m.playerStatusTitle.id="playerStatusTitle"
 m.playerStatusDetail=m.top.createChild("Label"):m.playerStatusDetail.id="playerStatusDetail"
 PlayerSetPlaybackStatus("prepare")
 m.sceneVideo=m.video:m.toast=m.top.createChild("Label"):m.toastTimer={control:"stop"}
 params={itemId:"fixture-item",fileId:"731",detail:detail,autoVersion:true,qualityPreference:"original",qualityExplicit:false,subtitleMode:"off",startPositionMs:25000}
 if data.manualFileId<>invalid
  m.playSelectedVersion=data.manualFileId:m.playVersionExplicit=true:params.autoVersion=false:params.fileId=data.manualFileId
 end if
 if data.audioOrdinal<>invalid
  choices=SiloUIDetailAudioChoices("silo",m.playItem,detail.versions,data.manualFileId)
  m.playAudioChoice=choices[data.audioOrdinal]:m.detailVersions=detail.versions:m.detailToken=1
  m.playAudioChoice.sourceId=m.sourceId:m.playAudioChoice.profileId=m.profileId:m.playAudioChoice.generation=m.generation:m.playAudioChoice.visit=m.detailToken
  if data.staleAudio=true then m.playAudioChoice.generation=6
  params.audioTrackId="file:"+data.manualFileId+":audio:"+data.audioOrdinal.ToStr():params.audioTrackIndex=data.audioOrdinal
  if data.audioOnly=true then m.playVersionExplicit=false
 end if
 if data.control="pending_stop" or data.control="failed_stop" or data.control="late_failed_stop"
  m.requestId=39
  owner=SiloUIOwner()
  if data.control="late_failed_stop" then owner.generation=6
  ApiOwned("playback_stop",{sessionId:"native-fixture",installationId:"server-install",stopId:"10000000-0000-4000-8000-000000000003",persistProgress:false},"play_report",-1,owner)
  if data.control="failed_stop" or data.control="late_failed_stop"
   child=m.pending["40"].task:FixtureScheduleChild(child):onApiResult(FixtureSceneEvent(child.result))
  end if
 end if
 if Left(data.control,5)="media"
  for each id in ["home","detail","library","libraries","search","onboarding","audio","audioBrowse","streaming","ebook","ebookBrowse","fadeLeft","fadeBottom","avatarBg"]
   node=m.top.createChild("Group"):node.id=id
  end for
  m.nav=m.top.createChild("Group"):m.backdrop=m.top.createChild("Group"):m.backdropOld=m.top.createChild("Group")
 m.backdropTimer={control:"stop"}:m.backdropFade={control:"stop"}
  m.manualFocus=m.top.createChild("Group"):m.pillGroups={}
  m.upNextTimer={control:"stop"}:m.playerCue=m.top.createChild("Group")
  m.detailCast=m.top.createChild("Group"):m.detailCast.AddFields({content:invalid})
  m.playerCueText=m.top.createChild("Label"):m.trackList=m.top.createChild("Group"):m.trackList.AddFields({content:invalid})
  for each id in ["playerCueBackground","playerCueTitle","nextStill","playerChapters","playerTracks"]
   node=m.top.createChild("Label"):node.id=id
  end for
  m.progressTimer={control:"stop"}:m.upNextDismissed=false:m.introDismissed=false
  m.video.AddFields({mute:false,globalCaptionMode:"On",position:0.0,duration:7200.0,state:"none",errorCode:-1,availableAudioTracks:[],availableSubtitleTracks:[],currentSubtitleTrack:"",subtitleTrack:"",enableUI:false,playbackActionButtons:[]})
 end if
 if SpBool(data.qualityExplicit) then params.qualityExplicit=data.qualityExplicit
 m.fixtureNativeParams=params
 Api("playback_start",params,"play_start",m.playToken)
 if data.control="stale_token" then m.playToken++
 if data.control="stale_owner" then m.profileId="newer-owner"
 if data.control="transition" then m.transitionIntent={action:"signout"}
 if data.control="prebuffer" then m.prebuf={ready:false}
 if data.control="output" then FixtureSiloDevice().videoMode="1080p"
 if data.control="purpose" then m.pending["41"].purpose="play_prebuf"
 onApiResult(FixtureSceneEvent(data.envelope))
end sub
'''
class SiloUICompatContinuation(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  native=native_fixture.CompatContinuation();cls.envelope=native.job()['outcome'];_,cls.wire,_=native.fixture()
 def scene(self,control='',mutate=None,change=None):
  data=dict(envelope=copy.deepcopy(self.envelope),wire=copy.deepcopy(self.wire),control=control)
  if mutate:mutate(data['envelope'])
  return holder_fixture.CompatPlaybackTask().transcript(scene=data,change=change)
 def test_matching_foreground_continuation_prepares_and_closes_unused_without_binding(self):
  r=self.scene()
  self.assertTrue(r['scene']['holderCreated'],'actual Scene API callback must retain a compatibility holder')
  self.assertEqual(['prepared','closed'],[x['phase'] for x in r['results']])
  self.assertTrue(r['scene']['released']);self.assertFalse(r['scene']['observing']);self.assertFalse(r['scene']['bound'])
  self.assertTrue(r['privateCleared']);self.assertEqual(0,r['mediaRequests'])
  closed=r['results'][-1];self.assertTrue(closed['credentialRevoked']);self.assertTrue(closed['mediaNeverRequested'])
  self.assertEqual(r['scene']['closeCommand']['commandId'],closed['commandId'])

 def test_stale_wrong_purpose_transition_other_owner_and_output_never_prepare(self):
  for control in ('stale_token','transition','prebuffer','output','purpose'):
   with self.subTest(control=control):
    r=self.scene(control);self.assertFalse(r['scene']['holderCreated']);self.assertEqual([],r['requests'])
 def test_missing_revision_or_allocated_closure_cannot_become_unused_prepare(self):
  def revision(e):e['compatContinuation']['owner'].pop('sessionRevision')
  def allocated(e):e['compatContinuation']['nativeClosure']['state']='acknowledged'
  for mutate in (revision,allocated):
   with self.subTest(mutate=mutate.__name__):self.assertFalse(self.scene(mutate=mutate)['scene']['holderCreated'])

 def test_preparation_back_keeps_observer_through_actual_unused_revocation(self):
  r=self.scene('back');self.assertTrue(r['scene']['stickyCancelled']);self.assertTrue(r['scene']['retainedWhileCancelled'])
  self.assertTrue(r['scene']['released']);self.assertFalse(r['scene']['observing']);self.assertTrue(r['results'][-1]['credentialRevoked'])
 def test_missing_cleanup_confirmation_retains_holder_without_fallback(self):
  r=self.scene('malformed_closed');self.assertFalse(r['scene']['released']);self.assertTrue(r['scene']['observing']);self.assertTrue(r['scene']['cleanupPending']);self.assertFalse(r['scene']['bound'])

 def test_failed_owned_logout_keeps_signout_and_profile_transition_pending(self):
  def fail(v):v['statuses']={'compat/logout':503}
  for control in ('signout','switch_profile'):
   with self.subTest(control=control):
    r=self.scene(control,change=fail)
    self.assertTrue(r['scene']['stickyCancelled']);self.assertTrue(r['scene']['retainedWhileCancelled']);self.assertTrue(r['scene']['transitionHeld'])
    self.assertFalse(r['scene']['released']);self.assertTrue(r['scene']['observing']);self.assertTrue(r['scene']['cleanupPending'])
    self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in r['requests']));self.assertFalse(r['scene']['bound'])

 def test_current_ineligible_continuation_ends_preparation_without_starting_an_owner(self):
  r=self.scene('output');self.assertFalse(r['scene']['holderCreated']);self.assertFalse(r['scene']['loading'])

 def test_unavailable_discovery_releases_confirmed_no_auth_holder_without_revocation_claim(self):
  def unavailable(v):v['statuses']={'native/discovery':404}
  r=self.scene(change=unavailable)
  self.assertEqual('refused',r['results'][-1]['phase']);self.assertFalse(r['results'][-1]['credentialRevoked'])
  self.assertFalse(r['results'][-1]['cleanupUnconfirmed']);self.assertTrue(r['scene']['released']);self.assertFalse(r['scene']['observing'])
  self.assertFalse(any('/QuickConnect' in q['url'] or '/Sessions/Logout' in q['url'] for q in r['requests']))

 def test_pre_media_refusal_reports_preparation_failure_after_confirmed_cleanup(self):
  def unavailable(v):v['statuses']={'native/discovery':404}
  envelope=copy.deepcopy(self.envelope);envelope['compatContinuation']['qualityExplicit']=True
  data=dict(envelope=envelope,wire=copy.deepcopy(self.wire),control='',qualityExplicit=True)
  r=holder_fixture.CompatPlaybackTask().transcript(scene=data,change=unavailable)
  self.assertEqual(0,r['mediaRequests'])
  self.assertTrue(r['scene']['released'])
  self.assertEqual("#2001: The server could not find the requested playback endpoint or resource. Check server compatibility and refresh the title.",r['scene']['failureMessage'])

 def test_unknown_preparation_error_never_reaches_the_failure_message(self):
  def unavailable(v):v['statuses']={'native/discovery':404}
  envelope=copy.deepcopy(self.envelope);envelope['compatContinuation']['qualityExplicit']=True
  data=dict(envelope=envelope,wire=copy.deepcopy(self.wire),control='',qualityExplicit=True)
  before=' onSiloUICompatResult(FixtureSceneEvent(payload))'
  after=' if payload.phase="refused" then payload.errorCode="https://private.invalid/?token=hostile"\n'+before
  r=holder_fixture.CompatPlaybackTask().transcript(scene=data,change=unavailable,sdk_overrides={before:after})
  self.assertEqual("#2001: Playback couldn't be prepared. Check your server connection and try again.",r['scene']['failureMessage'])

 def test_prior_pending_or_failed_actual_native_stop_blocks_compatibility_owner(self):
  for control in ('pending_stop','failed_stop'):
   with self.subTest(control=control):self.assertFalse(self.scene(control)['scene']['holderCreated'])

 def test_existing_cleanup_retry_uses_new_owned_command_and_advances_transition_after_revoke(self):
  def fail_once(v):v['statuses']={'compat/logout':503}
  for control in ('retry_signout','retry_switch_profile'):
   with self.subTest(control=control):
    r=self.scene(control,change=fail_once)
    self.assertTrue(r['scene']['released']);self.assertFalse(r['scene']['observing']);self.assertFalse(r['scene']['cleanupPending']);self.assertTrue(r['scene']['transitionAdvanced'])
    self.assertNotEqual(r['scene']['retryBefore'],r['scene']['retryAfter'])
    self.assertEqual(2,sum('/Sessions/Logout' in q['url'] for q in r['requests']));self.assertTrue(r['results'][-1]['credentialRevoked'])
 def test_owned_cancel_terminal_for_known_prepare_command_is_not_lost_after_close_queued(self):
  r=self.scene('cancel_cached_prepare');self.assertTrue(r['scene']['released']);self.assertFalse(r['scene']['observing'])

 def test_unknown_collect_keeps_observer_and_cleanup_fence_without_auth_retry(self):
  def unknown(v):v['exceptions']={'compat/collect':True}
  r=self.scene(change=unknown)
  self.assertFalse(r['scene']['released']);self.assertTrue(r['scene']['observing']);self.assertTrue(r['scene']['cleanupPending']);self.assertFalse(r['scene']['bound'])
  self.assertTrue(r['results'][-1]['cleanupUnconfirmed']);self.assertEqual(1,sum('/AuthenticateWithQuickConnect' in q['url'] for q in r['requests']))
  self.assertFalse(any('/playback/start' in q['url'] or '.m3u8' in q['url'] for q in r['requests']))
 def test_wrong_actual_result_action_cannot_authorize_a_prepare(self):
  def wrong(e):e['action']='detail'
  self.assertFalse(self.scene(mutate=wrong)['scene']['holderCreated'])

 def test_late_failed_stop_from_prior_generation_remains_an_unknown_native_owner(self):
  self.assertFalse(self.scene('late_failed_stop')['scene']['holderCreated'])

 def test_back_cannot_queue_prebuffer_or_audiobook_owners_before_holder_terminal(self):
  for kind in ('video','hero','audio_open','audio_late','audio_tick'):
   with self.subTest(kind=kind):
    r=self.scene('second_'+kind);self.assertEqual(0,r['scene']['secondOwnerRequests']);self.assertTrue(r['scene']['retainedWhileCancelled'])
 def test_consumed_history_holds_speculation_until_new_intent_but_audio_can_resume(self):
  for kind in ('video','hero','audio_open','audio_late','audio_tick'):
   with self.subTest(kind=kind):self.assertEqual(0 if kind in ('video','hero') else 1,self.scene('normal_'+kind)['scene']['secondOwnerRequests'])

 def test_failed_close_still_blocks_audiobook_open_after_back(self):
  def fail(v):v['statuses']={'compat/logout':503}
  r=self.scene('failed_second_audio_open',change=fail)
  self.assertEqual(0,r['scene']['secondOwnerRequests']);self.assertFalse(r['scene']['released']);self.assertTrue(r['scene']['observing'])
