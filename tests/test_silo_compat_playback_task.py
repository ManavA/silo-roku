"""Actual persistent prepare/close and actual child runJob; SDK seams only."""
import copy,json,re,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from tools.brightscript import run_function
from tests import test_silo_playback_task as legacy
from tests import test_silo_p8_original_transport as p8
ROOT=Path(__file__).resolve().parents[1]
SOURCE='03000000-0000-0000-0000-0000000002db'
TOKEN='synthetic-compat-token'
class CompatPlaybackTask(unittest.TestCase):
 def transcript(self,change=None,cancel_at='',options=None,scope_change_at='',pin_change_at='',reprepare=False,cancel_prepared=False,scene=None,device_overrides=None,sdk_overrides=None,transport_origin=None,subtitle_sdk=False):
  self.assertTrue((ROOT/'components/SiloCompatTask.xml').is_file(),'persistent compatibility Task missing')
  session,wire,_=p8.SiloP8OriginalTransportTests().inputs()
  wire['versions'][0]['audio_tracks']=[dict(index=11,codec='aac',language='en',channels=2,layout='stereo',default=True),dict(index=19,codec='eac3',language='en',channels=6,layout='5.1',default=False)]
  wire['versions'][0]['codec_audio']='eac3'
  if scene:wire=copy.deepcopy(scene['wire'])
  video=wire['versions'][0]['video_tracks'][0]
  streams=[dict(Index=0,Type='Video',Codec='hevc',Width=video['width'],Height=video['height'],BitDepth=10,VideoRangeType='DOVIWithHDR10',AverageFrameRate=24000/1001),dict(Index=1,Type='Audio',Codec='aac',Language='en',Channels=2),dict(Index=2,Type='Audio',Codec='eac3',Language='en',Channels=6)]
  source=dict(Id=SOURCE,MediaStreams=streams,Container='mkv',SupportsDirectPlay=False,SupportsTranscoding=True,DefaultAudioStreamIndex=2,DefaultSubtitleStreamIndex=-1,SiloSeekReanchor=True,TranscodingSubProtocol='hls',TranscodingContainer='ts',TranscodingUrl='/Videos/'+SOURCE+'/remux-ts-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId='+SOURCE,DirectStreamUrl='/private?api_key=do-not-project')
  if scene:
   streams=[streams[0]]+[dict(Index=i+1,Type='Audio',Codec=t['codec'],Language=t['language'],Channels=t['channels']) for i,t in enumerate(wire['versions'][0]['audio_tracks'])]
   source.update(MediaStreams=streams,DefaultAudioStreamIndex=1)
   if scene.get("audioOrdinal") is not None:
    source["DefaultAudioStreamIndex"]=scene["audioOrdinal"]+1
  values=dict(nativecap=json.loads((legacy.FIXTURES/'playback_capabilities.json').read_text()),nativeplan=__import__('tests.test_silo_compat_continuation',fromlist=['CompatContinuation']).CompatContinuation().fixture()[2],detail=wire,discovery=dict(jellyfin=dict(enabled=True,pending_restart=False,public_url='https://compat.example/media',server_name='Fixture'),account=dict(password_login_available=False)),sessions=[dict(Id="play-fixture")],system=dict(Id='fixture-server',ProductName='Jellyfin Server',Version='10.11.0',StartupWizardCompleted=True),initiate=dict(Authenticated=False,Secret='opaque-secret',Code='482177'),approve=dict(status='approved'),collect=dict(AccessToken=TOKEN,ServerId='fixture-server',User=dict(Id='opaque-user')),metadata=dict(MediaSources=[copy.deepcopy(source)]),playback=dict(PlaySessionId='play-fixture',MediaSources=[source]),logout='',revocation='')
  values["nativecap"]["installation_id"]="server-install"
  values["nativecap"]["features"]=[]
  if change:change(values)
  replacements=[]
  for generation in (2,3):
   response=copy.deepcopy(values['playback']);response['PlaySessionId']='play-fixture-'+str(generation)
   response['MediaSources'][0]['TranscodingUrl']=response['MediaSources'][0]['TranscodingUrl'].replace('PlaySessionId=play-fixture&','PlaySessionId='+response['PlaySessionId']+'&')
   replacements.append(('compat/playback'+str(generation),response))
  routes=[('native/reanchor_detail',values.get('reanchorDetail',values['detail'])),('native/caps',values['nativecap']),('native/start',values['nativeplan']),('native/detail',values['detail']),('native/discovery',values['discovery']),('compat/system',values['system']),('compat/initiate',values['initiate']),('native/approve',values['approve']),('compat/collect',values['collect']),('compat/metadata',values['metadata']),('compat/playback',values['playback']),('compat/sessions',values['sessions']),('compat/playing',''),('compat/progress',''),('compat/stopped',''),('compat/delete',''),('compat/logout',values['logout']),('compat/revocation',values['revocation'])]+replacements
  if scene and scene['control']=='media_native_stopfailure':
   routes.append(('native/stop',dict(outcome='stopped')))
   values.setdefault('statuses',{})['native/stop']=503
  # URL-keyed server responses make early-refusal cleanup visible without shifting a script.
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);files=[];seen=set()
   for xml in (('components/SiloCompatTask.xml','components/ApiTask.xml','components/SiloUIScene.xml') if scene else ('components/SiloCompatTask.xml','components/ApiTask.xml')):
    for script in ET.parse(ROOT/xml).getroot().findall('script'):
     name=script.get('uri').removeprefix('pkg:/')
     if name in seen:continue
     seen.add(name);text=(ROOT/name).read_text()
     text=text.replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()')
     if name=='components/SiloUIScene.brs':text=text.replace('sub init()', 'sub FixtureSceneInit()',1).replace('CreateObject("roSGNode", "ApiTask")','FixtureChild()')
     text=text.replace('CreateObject("roSGNode", "SiloCompatTask")','FixtureHolder()')
     if scene:text=text.replace('CreateObject("roSGNode","Timer")','FixtureCompatTimer()').replace('CreateObject("roSGNode","HomeCacheTask")','FixtureChild()').replace('AppRegistrySection("silo")','FixtureSceneRevisionSection()').replace('m.video.SetHttpAgent(agent)','FixtureVideoSetHttpAgent(agent)').replace('CreateObject("roSGNode", "Dialog")','FixtureDialog()').replace('CreateObject("roHttpAgent")','FixtureSceneAgent()')
     if scene and scene.get('realEntry'):
      # Cold entry uses the existing ordinary SDK field-observation boundary.
      # Task producer results arrive from independent interpreter invocations.
      text=re.sub(r'm\.[A-Za-z0-9_.]+\.observeField\(', 'FixtureObserveField(', text)
      text=text.replace('m.top.findNode("video").observeField(', 'FixtureObserveField(')
     if name=='components/ApiTask.brs':text=text.replace('function TaskRokuSiloContext(','function UnusedTaskRokuSiloContext(',1).replace('sub init()','sub FixtureChildInit()',1).replace('sub runJob()','sub FixtureChildRunJob()',1)
     if name=='components/SiloCompatTask.brs':text=text.replace('CreateObject("roSGNode","ApiTask")','FixtureChild()').replace('child.control = "RUN"','child.control = "RUN"\n    FixtureScheduleChild(child)').replace('CreateObject("roMessagePort")','FixturePort()').replace('wait(250,m.compatPort)','FixtureWait()')
     if name=='source/network/Http.brs':text=text.replace('function HttpRequest(','function UnusedHttpRequest(',1)
     if name=='source/auth/SessionStore.brs':text=text.replace('function LoadSession(','function UnusedLoadSession(',1).replace('function SessionRevision(','function UnusedSessionRevision(',1)
     if name=='components/SiloCompatTask.brs' and transport_origin is not None:
      text=text.replace('function CompatStockTransportQualified(', 'function UnusedCompatStockTransportQualified(',1)
      text+='\nfunction CompatStockTransportQualified(baseUrl as Dynamic) as Boolean\n return baseUrl="'+transport_origin+'"\nend function\n'
     if subtitle_sdk and name=='components/SiloUIPlayer.brs':
      text=text.replace('content = CreateObject("roSGNode", "ContentNode")','content = FixtureCaptionContentNode()')
     if subtitle_sdk and name=='components/TaskSiloSubtitleFetch.brs':
      for helper in ('SiloSubtitleClock','SiloSubtitleUuid','SiloSubtitleFileSystem','SiloSubtitleRead','SiloSubtitleNewPort','SiloSubtitleNewTransfer','SiloSubtitleWait','SiloSubtitleEventType'):
       text=text.replace('function '+helper+'(', 'function Unused'+helper+'(',1)
     target=root/Path(name).name;target.write_text(text);files.append(target)
   device=legacy.BOUNDARIES[legacy.BOUNDARIES.index('function FixtureSiloDevice()'):legacy.BOUNDARIES.index('function RunSiloCapabilities')]
   device=device.replace('return m.uuids.Shift()', 'if m.uuidCounter=invalid then m.uuidCounter=0\n m.uuidCounter++\n return "10000000-0000-4000-8000-"+Right("000000000000"+m.uuidCounter.ToStr(),12)').replace('return "1080p"','return "2160p60"').replace('major:"15",minor:"3",revision:"4",build:"2402"','major:"16",minor:"0",revision:"4",build:"834"').replace('format.chcnt<=2 and format.codec="aac"','format.chcnt<=6 and (format.codec="aac" or format.codec="eac3")')
   for old,new in (device_overrides or {}).items():device=device.replace(old,new)
   clone=legacy.BOUNDARIES[legacy.BOUNDARIES.index('function TaskRokuSiloContext('):legacy.BOUNDARIES.index('function RunSiloPlaybackEvent(')]
   sdk=root/'SDK.brs';sdk.write_text(device+clone+'''
function LoadSession(provider as String) as Object
 return ParseJson(FormatJson(m.fixtureSession))
end function
function SessionRevision(provider as String) as Integer
 return 0
end function
function FixtureAttemptObservation() as Dynamic
 if m.compatPlayAttempt=invalid then return invalid
 a=m.compatPlayAttempt
 return {owner:a.owner,playToken:a.playToken,itemId:a.itemId,fileId:a.fileId,requestId:a.requestId,playbackAttemptId:a.playbackAttemptId,compatibilityAttempted:a.compatibilityAttempted,phase:a.phase,resumeConsumed:a.resumeConsumed,nativeAttemptedFileIds:a.nativeAttemptedFileIds}
end function
function FixturePort() as Object
 return {}
end function
function FixtureChild() as Object
 return {observeField:sub(field as String,port as Dynamic)
 end sub,unobserveField:sub(field as String)
 end sub,result:invalid}
end function
sub FixtureScheduleChild(child as Object)
 parent=m.top:m.top=child:FixtureChildRunJob():m.top=parent
end sub
function FixtureWait() as Dynamic
 if m.sceneData<>invalid
  parent=m.top:m.top=m.sceneTop
  FixtureSceneDeliver(parent.result)
  m.top=parent
 end if
 m.results.Push(ParseJson(FormatJson(m.top.result)))
 if m.cancelPrepared and m.top.result.phase="prepared"
  m.top.cancelled=true:m.sentPreparedCancel=true
  if m.results.Count()>3 then m.fixtureBoundaryEnded=true:throw "finite SDK cancellation transcript ended"
  return invalid
 end if
 if m.sceneData<>invalid
  if m.sceneData.control="media_local_timeout_retry" and m.fixtureCloseSent=true and m.fixtureLateStopRetry<>true
   m.fixtureLateStopRetry=true
   parent=m.top:m.top=m.sceneTop:m.video.state="stopped":m.video.position=0
   ObChoose({action:"cleanup_retry"}):m.top=parent:return invalid
  end if
 end if
 if m.sceneData<>invalid and Left(m.sceneData.control,5)="media" and m.video.content<>invalid
  if m.sceneData.control="media_startup" and not m.fixtureStartupSent
   m.fixtureStartupSent=true
   parent=m.top:m.top=m.sceneTop:m.video.state="buffering"
   clock={TotalMilliseconds:function() as Integer
    return 15000
   end function}
   m.compatPreparation.landingClock=clock:m.compatPreparation.startupClock=clock
   onSiloUICompatTick():m.fixtureStartupPhase=m.compatPreparation.phase:m.top=parent
   m.fixtureBoundaryEnded=true:throw "finite SDK startup checkpoint ended"
  end if
  if m.playPlan.planGeneration>m.fixturePlayingGeneration
   m.fixturePlayingObserved=true:m.fixturePlayingGeneration=m.playPlan.planGeneration
   parent=m.top:m.top=m.sceneTop:m.video.state="playing":m.markerLookupStarted=true:onVideoState()
   m.fixtureGenerationContents.Push(m.video.content)
   if m.playPlan.planGeneration>1
    m.fixtureBeforeLandingControl=m.video.control
    m.video.position=m.playPlan.startPositionMs/1000#+0.2:onPlayerPosition()
    if m.compatPreparation.startPaused=true then m.video.state="paused":onVideoState():onPlayerPosition()
    m.fixtureRestoredMute=m.video.mute
   end if
   m.top=parent
   return invalid
  end if
  if (m.sceneData.control="media_progress" or m.sceneData.control="media_resume" or (m.sceneData.control="media_close" or m.sceneData.control="media_unknown" or m.sceneData.control="media_retry" or m.sceneData.control="media_retry_probe" or m.sceneData.control="media_local_timeout" or m.sceneData.control="media_local_timeout_retry")) and not m.fixtureProgressSent
   m.fixtureProgressSent=true
   parent=m.top:m.top=m.sceneTop
   if m.sceneData.control="media_resume"
    m.video.position=0.0
   else
    m.video.position=25.2:onPlayerPosition():m.video.position=30.0
   end if
   m.video.state="paused":PlayerReport("playback_progress"):m.top=parent
   return invalid
  end if
  if (m.sceneData.control="media_close" or m.sceneData.control="media_unknown" or m.sceneData.control="media_retry" or m.sceneData.control="media_retry_probe" or m.sceneData.control="media_local_timeout" or m.sceneData.control="media_local_timeout_retry") and not m.fixtureCloseSent
   m.fixtureCloseSent=true:m.fixtureOldContent=m.video.content
   parent=m.top:m.top=m.sceneTop:PlayerClose(false,false)
   if m.sceneData.control="media_local_timeout" or m.sceneData.control="media_local_timeout_retry"
    m.compatPreparation.stopClock={TotalMilliseconds:function() as Integer
     return 6000
    end function}
    onSiloUICompatTick()
   else
    m.video.state="stopped":onVideoState()
   end if
   m.top=parent
   return invalid
  end if
  if (m.sceneData.control="media_seek" or m.sceneData.control="media_roundtrip" or m.sceneData.control="media_oldgen" or m.sceneData.control="media_changed_source" or m.sceneData.control="media_seek_back" or m.sceneData.control="media_seek_profile") and not m.fixtureSeekSent
   m.fixtureSeekSent=true
   parent=m.top:m.top=m.sceneTop:m.video.state="paused"
   m.transport=CreateObject("roSGNode","Group"):m.transport.visible=false:m.transportTimer={control:"stop"}:m.transportEnabled=true:m.transportPreviewMs=900000:m.transportOffsetMs=0
   ignored=TransportKey("OK")
   m.video.state="stopped":onVideoState():m.top=parent
   return invalid
  end if
  if m.sceneData.control="media_roundtrip" and m.playPlan.planGeneration=2 and m.compatPreparation.activeConfirmed=true and not m.fixtureReverseSent
   m.fixtureReverseSent=true
   parent=m.top:m.top=m.sceneTop:m.transportPreviewMs=120000:ignored=TransportKey("OK")
   m.video.state="stopped":onVideoState():m.top=parent:return invalid
  end if
  if m.sceneData.control="media_roundtrip" and m.playPlan.planGeneration=3 and m.compatPreparation.activeConfirmed=true
   m.fixtureCloseSent=true:m.fixtureOldContent=m.video.content
   parent=m.top:m.top=m.sceneTop:PlayerClose(false,false):m.video.state="stopped":onVideoState():m.top=parent:return invalid
  end if
  if m.sceneData.control="media_roundtrip" then return invalid
  if (m.sceneData.control="media_seek" or m.sceneData.control="media_oldgen") and m.playPlan.planGeneration<2 then return invalid
  if (m.sceneData.control="media_next" or m.sceneData.control="media_shuffle_next") and not m.fixtureNextSent
   m.fixtureNextSent=true
   parent=m.top:m.top=m.sceneTop
   m.playNext={sourceId:m.sourceId,itemId:"next-item",type:"episode",title:"Next fixture",durationMs:7200000}
   before=m.requestId
   if m.sceneData.control="media_shuffle_next"
    m.shuffle={current:m.playNext}:ShufflePlayCurrent(false)
   else
    PlayerAdvance()
   end if
   m.fixtureNextBeforeTerminal=m.requestId-before
   m.video.state="stopped":onVideoState():m.top=parent:return invalid
  end if
  if m.sceneData.control="media_transition" and m.fixtureTransitionSent<>true
   m.fixtureTransitionSent=true
   parent=m.top:m.top=m.sceneTop
   FixtureBeginTransition("signout")
   m.fixtureObserverRetained=m.fixtureHolder.observing and m.compatPreparation<>invalid
   m.video.state="stopped":onVideoState():m.top=parent:return invalid
  end if
  if m.sceneData.control="media_finished" and not m.fixtureFinishSent
   m.fixtureFinishSent=true
   parent=m.top:m.top=m.sceneTop:m.video.position=25.2:onPlayerPosition():m.video.position=7199.5:onPlayerPosition()
   m.video.state="finished":onVideoState():m.video.state="stopped":onVideoState():m.top=parent:return invalid
  end if
  if m.sceneData.control="media_controls" and not m.fixtureControlSent
   m.fixtureControlSent=true
   parent=m.top:m.top=m.sceneTop
   m.transport=CreateObject("roSGNode","Group"):m.transport.visible=false:m.transportTimer={control:"stop"}:m.memoryHigh=true
   TransportStart():m.fixtureMemoryNative=m.video.enableUI
   m.transportEnabled=true:m.transport.visible=true:m.video.globalCaptionMode="On":onTransportVisibility():m.fixtureCaptionNative=m.video.enableUI
   m.transportEnabled=true:m.transport.visible=true:m.transportIndex=3:ignored=TransportKey("OK"):m.fixtureButtonNative=m.video.enableUI
   PlayerShowTracks():m.fixtureTrackDialog=m.trackDialog<>invalid
   m.top=parent
  end if
  if (m.sceneData.control="media_failure" or m.sceneData.control="media_native_stopfailure") and not m.fixtureFailureSent
   m.fixtureFailureSent=true
   parent=m.top:m.top=m.sceneTop:m.video.position=25.2:onPlayerPosition():m.video.position=42.0:onPlayerPosition()
   m.video.state="error":onVideoState():m.video.state="stopped":onVideoState():m.top=parent:return invalid
  end if
  if (m.sceneData.control="media_replaced" or m.sceneData.control="media_replaced_finished") and not m.fixtureReplacementSent
   m.fixtureReplacementSent=true
   parent=m.top:m.top=m.sceneTop
   if m.sceneData.control="media_replaced_finished" then m.video.position=25.2:onPlayerPosition():m.video.position=7199.5:onPlayerPosition()
   replacement=CreateObject("roSGNode","ContentNode"):replacement.url="https://example.invalid/replacement"
   m.video.content=replacement:m.video.control="play":m.video.state="error"
   if m.sceneData.control="media_replaced_finished" then m.video.state="finished"
   onVideoState():m.top=parent
  end if
  m.fixtureBoundaryEnded=true:throw "finite SDK bound transcript ended"
 end if
 if m.results.Count()>24 then m.fixtureBoundaryEnded=true:throw "finite SDK command transcript ended"
 if m.top.result.cleanupUnconfirmed=true
  if m.sceneRetryQueued and not m.sceneRetryConsumed then m.sceneRetryConsumed=true:return invalid
  if m.cancelPrepared
   m.cancelFailureIdle++
   if m.cancelFailureIdle<3 then return invalid
  end if
  if m.reprepare and not m.reprepared
   m.reprepared=true:m.top.command={action:"prepare",commandId:"prepare-2",holderId:"holder-1",attemptId:"attempt-1",owner:m.owner,params:{}}
   return invalid
  end if
  m.fixtureBoundaryEnded=true:throw "finite SDK command transcript ended"
 end if
 if m.sceneData=invalid and m.top.result.phase="prepared" then m.top.command={action:"close",commandId:"close-1",holderId:"holder-1",attemptId:"attempt-1",owner:m.owner}
 return invalid
end function
function HttpRequest(request as Object,timeoutMs=0 as Integer) as Object
 m.requests.Push(request)
 url=request.url:key=""
 if request.method="DELETE" and Instr(1,url,"/api/v2/playback/")>0 then key="native/stop"
 if Instr(1,url,"/api/v2/catalog/items/")>0 then key="native/detail"
 if Instr(1,url,"/api/v2/playback/capabilities")>0 then key="native/caps"
 if Instr(1,url,"/api/v2/playback/start")>0 then key="native/start"
 if Instr(1,url,"/compat/connect-info")>0 then key="native/discovery"
 if Instr(1,url,"/System/Info/Public")>0 then key="compat/system"
 if Instr(1,url,"/QuickConnect/Initiate")>0 then key="compat/initiate"
 if Instr(1,url,"/approve-handoff")>0 then key="native/approve"
 if Instr(1,url,"/AuthenticateWithQuickConnect")>0 then key="compat/collect"
 if Instr(1,url,"/Items/")>0 then key="compat/metadata"
 if Instr(1,url,"/PlaybackInfo")>0 then key="compat/playback"
 if Instr(1,url,"/Sessions/Logout")>0 then key="compat/logout"
 if Right(url,9)="/Sessions"
  key="compat/sessions"
  if m.fixtureLoggedOut=true then key="compat/revocation"
 end if
 if Right(url,17)="/Sessions/Playing" then key="compat/playing"
 if Right(url,26)="/Sessions/Playing/Progress" then key="compat/progress"
 if Right(url,25)="/Sessions/Playing/Stopped" then key="compat/stopped"
 if Instr(1,url,"/Videos/ActiveEncodings?PlaySessionId=")>0 then key="compat/delete"
 if key="" then throw "unexpected request"
 status=200
 if key="compat/playing" or key="compat/progress" or key="compat/stopped" or key="compat/delete" then status=204
 if key="compat/stopped" then m.values["compat/sessions"]=[]
 if key="compat/logout" then status=204:m.fixtureLoggedOut=true
 if key="compat/revocation" then status=401
 if m.values[key]=invalid then status=404
 body=""
 if m.values[key]<>invalid
  if type(m.values[key])="String" then body=m.values[key] else body=FormatJson(m.values[key])
 end if
 if SiloObject(m.values.statuses) and m.values.statuses.DoesExist(key) then status=m.values.statuses[key]
 if key="compat/sessions" and m.values.sessionSequence<>invalid
  if m.values.sessionSequence.Count()>0 then body=FormatJson(m.values.sessionSequence.Shift())
 end if
 if key="compat/playing" and m.fixtureAutoActive=true
  report=ParseJson(request.body):m.values["compat/sessions"]=[{Id:report.PlaySessionId}]
 end if
 if key="compat/playback"
  m.fixturePlaybackCount++
  if m.fixturePlaybackCount>1
   body=FormatJson(m.values["compat/playback"+m.fixturePlaybackCount.ToStr()])
   if m.sceneData<>invalid
    if m.sceneData.control="media_seek_back" or m.sceneData.control="media_seek_profile"
     parent=m.top:m.top=m.sceneTop
     if m.sceneData.control="media_seek_back" then PlayerClose(false,false) else FixtureBeginTransition("switch_profile")
     m.fixtureObserverRetained=m.fixtureHolder.observing and m.compatPreparation<>invalid
     m.top=parent
    end if
   end if
  end if
 end if
 if key="native/detail"
  m.fixtureDetailCount++
  if m.fixtureDetailCount>1 then body=FormatJson(m.values["native/reanchor_detail"])
 end if
 if key="compat/logout" then m.negotiationCaptured=m.compatPlaySession<>""
 if SiloObject(m.values.exceptions) and m.values.exceptions.DoesExist(key) then throw "synthetic SDK transport exception"
 if key=m.cancelAt then m.fixtureTop.cancelled=true
 if key=m.scopeChangeAt then m.fixtureSession["profileId"]="different-profile"
 if key=m.pinChangeAt then m.fixtureSession["profileToken"]="synthetic-new-pin"
 return HttpResponse(request,status,body)
end function
function RunCompatFixture(session as Object,values as Object,cancelAt as String,options as Object,scopeChangeAt as String,pinChangeAt as String,reprepare as Boolean,cancelPrepared as Boolean,sceneData as Dynamic) as Object
 m.fixtureNativeResults=[]:m.fixturePlaybackCount=0:m.fixtureDetailCount=0:m.fixtureNextSent=false:m.fixtureFinishSent=false:m.fixtureStartupSent=false:m.fixtureReplacementSent=false:m.fixtureFailureSent=false:m.fixtureControlSent=false:m.fixtureReverseSent=false:m.fixturePlayingGeneration=0:m.fixtureGenerationContents=[]:m.fixtureSeekSent=false:m.fixtureCloseSent=false:m.fixtureOldContent=invalid:m.fixtureProgressSent=false:m.fixturePlayingObserved=false:m.sceneRetryQueued=false:m.sceneRetryConsumed=false:m.sceneData=sceneData:m.fixtureSession=session:m.values=values:m.requests=[]:m.results=[]:m.cancelAt=cancelAt:m.scopeChangeAt=scopeChangeAt:m.pinChangeAt=pinChangeAt:m.reprepare=reprepare:m.reprepared=false:m.cancelPrepared=cancelPrepared:m.sentPreparedCancel=false:m.cancelFailureIdle=0
 m.owner={provider:"silo",sourceId:session.sourceId,profileId:session.profileId,generation:7,sessionRevision:0}
 params={itemId:"fixture-item",fileId:"731",audioTrackId:"file:731:audio:1",audioTrackIndex:1,subtitleMode:"off",qualityPreference:"original",startPositionMs:25000}
 for each key in options
  params[key]=options[key]
 end for
 m.top={command:{action:"prepare",commandId:"prepare-1",holderId:"holder-1",attemptId:"attempt-1",owner:m.owner,params:params},cancelled:false,result:invalid,observeField:sub(field as String,port as Object)
 end sub}
 if sceneData<>invalid
  FixtureSceneStart(sceneData)
  if m.fixtureHolder=invalid then return {scene:{holderCreated:false,loading:m.playLoading,statusVisible:m.playerStatusPanel.visible,tickets:m.cleanupTickets.Count(),attempt:m.compatPlayAttempt},results:[],requests:m.requests}
  if sceneData.control="media_prepare_timeout"
   m.compatPreparation.prepareClock={TotalMilliseconds:function() as Integer
    return 120001
   end function}
   onSiloUICompatTick()
   return {scene:{phase:m.compatPreparation.phase,loading:m.playLoading,retained:m.compatPreparation<>invalid,observing:m.fixtureHolder.observing,cancelled:m.fixtureHolder.cancelled,cleanupPending:m.cleanupFailed=true},requests:m.requests}
  end if
  m.top=m.fixtureHolder:m.owner=m.top.command.owner
 end if
 m.fixtureTop=m.top:m.fixtureBoundaryEnded=false:m.negotiationCaptured=false:m.fixtureAutoActive=m.values["compat/sessions"].Count()>0
 try
  runCompat()
 catch exception
  if not m.fixtureBoundaryEnded then return {fixtureError:exception}
 end try
 if not m.fixtureBoundaryEnded then m.results.Push(m.top.result)
 if sceneData<>invalid
  parent=m.top:m.top=m.sceneTop:FixtureSceneDeliver(parent.result)
  if m.sceneData.control="media_failure" or m.sceneData.control="media_native_stopfailure" or m.sceneData.control="media_noauth" or m.sceneData.control="media_finished"
   for each key in m.pending
    child=m.pending[key].task
    if child.job.action="playback_start"
     FixtureScheduleChild(child):m.fixtureNativeResults.Push(child.result):onApiResult(FixtureSceneEvent(child.result))
    end if
   end for
   if m.sceneData.control="media_native_stopfailure"
    m.video.state="playing":onVideoState():m.video.position=60.0:onPlayerPosition():PlayerClose(false,false)
    for each key in m.pending
     child=m.pending[key].task
     if child.job.action="playback_stop" then FixtureScheduleChild(child):onApiResult(FixtureSceneEvent(child.result))
    end for
    before=m.requestId:PlayItem(m.playItem,60000):m.fixtureBlockedStartDelta=m.requestId-before
   end if
  end if
  m.top=parent
  contentHeaders=invalid:retiredHeaders=invalid:generationHeaders=[]:failureMessage="":nextJob=invalid:resumeJobs=[]
  for each key in m.pending
   pendingJob=m.pending[key].task.job
   if pendingJob.action="playback_start" then resumeJobs.Push(pendingJob)
   if pendingJob.action="detail" and pendingJob.params.itemId="next-item" then nextJob=pendingJob
  end for
  if m.playbackFailureDialog<>invalid then failureMessage=m.playbackFailureDialog.message
  for each owned in m.fixtureGenerationContents
   generationHeaders.Push(owned.HttpHeaders)
  end for
  if m.sceneVideo.content<>invalid then contentHeaders=m.sceneVideo.content.HttpHeaders
  if m.fixtureOldContent<>invalid then retiredHeaders=m.fixtureOldContent.HttpHeaders
  return {scene:{holderCreated:true,holderCount:m.fixtureHolderCount,loading:m.playLoading,attempt:FixtureAttemptObservation(),released:m.compatPreparation=invalid,closeCommand:m.fixtureHolder.command,observing:m.fixtureHolder.observing,stickyCancelled:m.fixtureHolder.cancelled,retainedWhileCancelled:m.fixtureObserverRetained,cleanupPending:m.cleanupFailed=true,transitionHeld:m.transitionIntent<>invalid,secondOwnerRequests:m.secondOwnerRequests,retryBefore:m.sceneRetryBefore,retryAfter:m.sceneRetryAfter,transitionAdvanced:m.transitionReplaying=false and m.transitionIntent=invalid and m.sceneRetryConsumed=true,bound:m.sceneVideo.content<>invalid,plan:m.playPlan,privatePayloadCleared:m.fixtureHolder.privateBinding=invalid,contentHeaders:contentHeaders,agentHeaders:m.fixtureAgentHeaders,retiredHeaders:retiredHeaders,retainedContentCleared:m.nativeSubtitleContent=invalid,generationHeaders:generationHeaders,returnView:m.view,captionMode:m.video.globalCaptionMode,muted:m.video.mute,nativeControl:m.video.control,nativeControls:[m.fixtureMemoryNative,m.fixtureCaptionNative,m.fixtureButtonNative],trackDialogOpened:m.fixtureTrackDialog,failureDialog:m.playbackFailureDialog<>invalid,failureMessage:failureMessage,nextJob:nextJob,resumeJobs:resumeJobs,nextBeforeTerminal:m.fixtureNextBeforeTerminal,oldGenerationPreserved:m.fixtureOldGenerationPreserved,blockedStartDelta:m.fixtureBlockedStartDelta,startupPhase:m.fixtureStartupPhase,beforeLandingControl:m.fixtureBeforeLandingControl,restoredMute:m.fixtureRestoredMute,watched:m.playItem.watched,duplicateRebound:m.fixtureDuplicateRebound,nativeResults:m.fixtureNativeResults},results:m.results,requests:m.requests,privateCleared:m.compatToken="" and m.compatSecret="",mediaRequests:m.compatMediaRequests}
 end if
 return {results:m.results,requests:m.requests,privateCleared:m.compatToken="" and m.compatSecret="",mediaRequests:m.compatMediaRequests,negotiationCaptured:m.negotiationCaptured,credentialHeld:m.compatToken<>""}
end function
'''+(self.scene_sdk() if scene else ''))
   for old,new in (sdk_overrides or {}).items():
    text=sdk.read_text()
    self.assertTrue(old in text,"SDK scheduling override did not match")
    sdk.write_text(text.replace(old,new))
   if subtitle_sdk:
    from tests.test_silo_selected_subtitle_fetch import SDK_BOUNDARIES
    boundary=SDK_BOUNDARIES[SDK_BOUNDARIES.index('function SiloSubtitleClock('):SDK_BOUNDARIES.index('function RunSubtitleSdkFixture(')]
    boundary += '\nfunction FixtureCaptionContentNode() as Object\n node=CreateObject("roSGNode","Node")\n node.AddFields({url:"",streamFormat:"",title:"",playStart:0.0,Length:0.0,SubtitleTracks:[],SubtitleConfig:{},HttpHeaders:[],HttpCertificatesFile:""})\n return node\nend function\n'
    boundary += '\nfunction FixtureCaptionBody() as Dynamic\n if m.playPlan.compatCaptionUri=invalid then return invalid\n return SiloSubtitleRead(m.playPlan.compatCaptionUri)\nend function\n'
    sdk.write_text(sdk.read_text()+boundary)
   files.append(sdk)
   return run_function(files,'RunCompatFixture',[session,dict(routes,statuses=values.get('statuses',{}),exceptions=values.get('exceptions',{}),sessionSequence=values.get('sessionSequence')),cancel_at,options or {},scope_change_at,pin_change_at,reprepare,cancel_prepared,scene],root=root)
 def scene_sdk(self):
  from tests.test_silo_ui_compat_continuation import SCENE_SDK
  return SCENE_SDK
 def test_actual_persistent_prepare_close_keeps_media_private_and_revokes_unused_credential(self):
  r=self.transcript();self.assertEqual(['prepared','closed'],[x['phase'] for x in r['results']]);self.assertTrue(all(x['ok'] for x in r['results']),r['results'])
  closed=r['results'][-1];self.assertTrue(closed['credentialRevoked']);self.assertTrue(closed['mediaNeverRequested']);self.assertFalse(closed['pendingNegotiationDeleted']);self.assertTrue(r['privateCleared']);self.assertEqual(0,r['mediaRequests'])
  self.assertFalse(any('.m3u8' in q['url'] or q['method']=='DELETE' for q in r['requests']));self.assertNotIn(TOKEN,json.dumps(r['results']));self.assertNotIn('master.m3u8',json.dumps(r['results']));self.assertNotIn('DirectStream',json.dumps(r['results']))
  playback=next(x for x in r['requests'] if '/PlaybackInfo' in x['url']);body=json.loads(playback['body']);self.assertEqual((SOURCE,2,-1),(body['MediaSourceId'],body['AudioStreamIndex'],body['SubtitleStreamIndex']));self.assertEqual(250000000,body['StartTimeTicks'])

 def test_refused_allocated_recipe_or_collect_envelope_keeps_owned_revocation(self):
  def bad_recipe(v):v['playback']['MediaSources'][0]['TranscodingUrl']='/media/Videos/'+SOURCE+'/master.m3u8?PlaySessionId=play-fixture&MediaSourceId='+SOURCE
  def bad_envelope(v):v['collect']['User']=[]
  def wrong_server(v):v['collect']['ServerId']='different-server'
  for change in (bad_recipe,bad_envelope,wrong_server):
   with self.subTest(change=change):
    r=self.transcript(change=change);last=r['results'][-1];self.assertFalse(last['ok']);self.assertTrue(last['credentialRevoked']);self.assertTrue(last['mediaNeverRequested']);self.assertFalse(last['pendingNegotiationDeleted']);self.assertTrue(r['privateCleared'])
    self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in r['requests']))
    if change==bad_recipe:self.assertTrue(r['negotiationCaptured'])
 def test_cancel_after_native_approval_or_negotiation_collects_only_for_owned_revoke(self):
  for stage in ('native/approve','compat/playback'):
   with self.subTest(stage=stage):
    r=self.transcript(cancel_at=stage);last=r['results'][-1];self.assertTrue(last['credentialRevoked']);self.assertTrue(last['mediaNeverRequested']);self.assertEqual(0,r['mediaRequests']);self.assertTrue(r['privateCleared'])
    self.assertEqual(1,sum('/AuthenticateWithQuickConnect' in q['url'] for q in r['requests']))
    if stage=='native/approve':self.assertFalse(any('/PlaybackInfo' in q['url'] for q in r['requests']))
 def test_unsupported_actual_routes_never_release_media_or_claim_a_revoked_credential(self):
  def html(v):v['system']='<html>not this protocol</html>'
  def disabled(v):v['discovery']['jellyfin']['enabled']=False
  def no_handoff(v):v['statuses']={'native/approve':404,'compat/collect':404}
  for change in (html,disabled,no_handoff):
   with self.subTest(change=change):
    r=self.transcript(change=change);last=r['results'][-1];self.assertFalse(last['ok']);self.assertFalse(last['credentialRevoked']);self.assertTrue(last['mediaNeverRequested']);self.assertFalse(any('/PlaybackInfo' in q['url'] for q in r['requests']))
 def test_unknown_collect_or_still_valid_old_token_never_claims_confirmed_cleanup(self):
  def unknown_token(v):v['collect']={'User':[]}
  def still_valid(v):v['statuses']={'compat/revocation':200};v['revocation']=[]
  for change in (unknown_token,still_valid):
   with self.subTest(change=change):
    r=self.transcript(change=change);last=r['results'][-1];self.assertTrue(last['cleanupUnconfirmed']);self.assertFalse(last['credentialRevoked']);self.assertFalse(last['ok']);self.assertTrue(last['mediaNeverRequested']);self.assertFalse(last['pendingNegotiationDeleted'])
    self.assertEqual(1,sum('/AuthenticateWithQuickConnect' in q['url'] for q in r['requests']))
    if change==still_valid:self.assertTrue(r['credentialHeld'])

 def test_user_quality_cap_and_subtitle_intent_are_never_silently_replaced(self):
  for options in (dict(qualityPreference='1080p'),dict(subtitleMode='always'),dict(bandwidthCapKbps=1000),dict(audioTrackId='file:731:audio:0',audioTrackIndex=0)):
   with self.subTest(options=options):
    r=self.transcript(options=options);self.assertFalse(r['results'][-1]['ok']);self.assertFalse(any('compat.example' in q['url'] for q in r['requests']));self.assertEqual(0,r['mediaRequests'])

 def test_transport_exception_retains_unconfirmed_cleanup_authority(self):
  for stage in ('compat/collect','compat/logout'):
   with self.subTest(stage=stage):
    def failure(v):v['exceptions']={stage:True}
    r=self.transcript(change=failure);last=r['results'][-1];self.assertTrue(last['cleanupUnconfirmed']);self.assertFalse(last['credentialRevoked']);self.assertTrue(last['mediaNeverRequested'])
    if stage=='compat/logout':self.assertTrue(r['credentialHeld'])

 def test_stale_profile_or_pin_at_approval_and_collection_revoke_without_prepared_publication(self):
  for stage in ('native/approve','compat/collect'):
   for change in ('scope_change_at','pin_change_at'):
    with self.subTest(stage=stage,change=change):
     r=self.transcript(**{change:stage});last=r['results'][-1];self.assertFalse(last['ok']);self.assertTrue(last['credentialRevoked']);self.assertTrue(last['mediaNeverRequested']);self.assertTrue(r['privateCleared']);self.assertFalse(any(x['phase']=='prepared' for x in r['results']));self.assertFalse(any('/PlaybackInfo' in q['url'] for q in r['requests']));self.assertEqual('fixture-owner',last['owner']['profileId'])

 def test_unknown_collect_remains_unconfirmed_when_a_second_prepare_is_refused(self):
  def unknown(v):v['collect']={'User':[]}
  r=self.transcript(change=unknown,reprepare=True);self.assertTrue(r['results'][-1]['cleanupUnconfirmed']);self.assertFalse(r['results'][-1]['ok']);self.assertEqual(1,sum('/AuthenticateWithQuickConnect' in q['url'] for q in r['requests']))

 def test_prepared_cancelled_field_without_close_command_owns_revocation(self):
  r=self.transcript(cancel_prepared=True);self.assertEqual(['prepared','closed'],[x['phase'] for x in r['results']]);last=r['results'][-1];self.assertTrue(last['cancelled']);self.assertTrue(last['ok']);self.assertTrue(last['credentialRevoked']);self.assertTrue(last['mediaNeverRequested']);self.assertFalse(last['pendingNegotiationDeleted']);self.assertTrue(r['privateCleared']);self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in r['requests']))
 def test_prepared_cancel_failure_keeps_authority_and_does_not_repeat_logout_on_idle(self):
  def failure(v):v['statuses']={'compat/logout':500}
  r=self.transcript(change=failure,cancel_prepared=True);last=r['results'][-1];self.assertEqual('closed',last['phase']);self.assertTrue(last['cleanupUnconfirmed']);self.assertFalse(last['credentialRevoked']);self.assertTrue(r['credentialHeld']);self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in r['requests']))
