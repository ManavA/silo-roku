"""Provider Subtitle Off waits for native stop and retains its logical owner."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_brightscript
from tests.test_silo_playback_policy import plan, SCOPE

ROOT = Path(__file__).resolve().parents[1]


class SubtitleOffFlow(unittest.TestCase):
    def scene(self, body, actual_results=False, actual_start=False, menu=False, actual_reset=False, actual_scope=False, actual_owned=False, seed_plan=None, returned_plan=None, actual_transport=False, actual_cue=False, actual_diagnostics=False, actual_report=False, actual_onboarding_ui=False):
        if actual_onboarding_ui: actual_scope=True; actual_transport=True
        value = plan()
        value.update(planId='plan-0001', subtitleMode='burn_in', timelineOffsetMs=120000)
        value['cleanupOwner'] = dict(SCOPE, sessionRevision=0)
        value['siloPlayback']['selectedTracks']['subtitle'] = dict(id='file:f1:subtitle:0', index=0)
        accepted = copy.deepcopy(value)
        accepted.update(planId='plan-0002', subtitleMode='off')
        accepted['siloPlayback']['planId'] = 'plan-0002'
        accepted['siloPlayback']['planAttemptKey'] = 'plan-key-0002'
        del accepted['siloPlayback']['selectedTracks']['subtitle']
        if seed_plan is not None: value = copy.deepcopy(seed_plan)
        if returned_plan is not None: accepted = copy.deepcopy(returned_plan)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = (ROOT/'components/SiloUIPlayer.brs').read_text()
            for name in (['PlayerStart'] if not actual_start else []) + ([] if actual_reset else ['PlayerResetChrome']) + ([] if actual_report else ['PlayerReport']) + [
                         'PlayerPaintCue', 'PlayerUpdateNativeActions']:
                source = re.sub(r'(?m)^sub '+name+r'\(', 'sub Unused'+name+'(', source, count=1)
            if not actual_cue:
                source = re.sub(r'(?m)^function PlayerCurrentCue\(',
                                'function UnusedPlayerCurrentCue(', source, count=1)
            if actual_start:
                source=source.replace('CreateObject("roSGNode", "ContentNode")', 'FixtureContent()')
                source=source.replace('CreateObject("roHttpAgent")', 'FixtureAgent()')
                source=source.replace('CreateObject("roSGNode", "Dialog")', 'FixtureDialog()')
                source += '\n' + '''function FixtureContent() as Object
 m.contentCount=NumberOr(m.contentCount,0)+1
 return {id:"fresh-"+m.contentCount.ToStr(),isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}
end function
function FixtureDialog() as Object
 return {observeField:sub(name as String, callback as String)
 end sub}
end function
function FixtureAgent() as Object
 return {SetCertificatesFile:sub(path as String)
 end sub,AddHeader:sub(name as String,value as String)
 end sub}
end function
'''
            if menu:
                menu_start=source.index('sub PlayerShowTracks()')
                menu_end=source.index('\nend sub',menu_start)
                source=source[:menu_start]+source[menu_start:menu_end].replace('CreateObject("roSGNode", "ContentNode")','FixtureMenuContent()').replace('FixtureContent()','FixtureMenuContent()')+source[menu_end:]
                source += '\n' + '''function FixtureMenuContent() as Object
 return {children:[],createChild:function(kind as String) as Object
 child={}:m.children.Push(child):return child
 end function}
end function
'''
            player = folder/'Player.brs'
            player.write_text(source)
            boundary = folder/'Boundary.brs'
            boundary.write_text('''sub HomeCacheYield()
end sub
sub HomeCacheRetire()
end sub
sub ApiOwned(action as String, params as Object, purpose as String, extra as Dynamic, owner as Object)
 m.requestId=NumberOr(m.requestId,0)+1
 m.calls.Push({action:action,params:params,purpose:purpose,extra:extra,owner:owner})
 m.pending[m.requestId.ToStr()]={purpose:purpose,extra:extra,owner:owner,generation:owner.generation,task:{unobserveField:sub(field as String)
 end sub}}
end sub
function SiloUIOwner() as Object
 return {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
end function
function SiloUICleanupUuid() as String
 return "subtitle-request-0001"
end function
sub Toast(message as String)
 m.message=message
end sub
sub PlayerStart(plan as Object, bound=false as Boolean)
 if m.simulateBindingRetire = true then SiloUISubtitleRetireBound()
 m.starts.Push(plan):m.playPlan=plan:m.recoveringNative=false:m.video.state="buffering":m.video.control="play"
end sub
sub PlayerReport(action as String,positionMs=invalid as Dynamic,finalSample=invalid as Dynamic)
 if positionMs=invalid then positionMs=PlayerPositionMs()
 m.reportedPlan=m.playPlan
 m.stops.Push({action:action,position:positionMs})
end sub
sub PlayerResetChrome()
end sub
sub SiloUICancelPendingPlayback()
end sub
sub ShowView(view as String)
 m.view=view
end sub
sub HomeRefreshHero()
end sub
sub HomeUpdateProgress(item as Object, scope as Dynamic)
end sub
sub SetZone(zone as String)
 m.zone=zone
end sub
function PlayerCurrentCue() as Object
 return {upNext:false,introEndMs:0,skipLabel:""}
end function
sub PlayerUpdateNativeActions(cue as Object)
end sub
sub PlayerPaintCue(upNext as Boolean)
end sub
sub ObScreen(a as String,b as String,c as String,d as String,e as Object)
end sub
sub ObChoose(choice as Object)
 m.transitionChoices=NumberOr(m.transitionChoices,0)+1
 m.generation=m.generation+1:m.sourceId="silo:next"
end sub
sub FixtureDeleteFile(uri as Dynamic)
 m.deleted.Push(uri)
end sub
sub FixtureInventory(plan as Object)
 context=SiloPlaybackContext(plan,SiloUIOwner())
 rows=[]
 for ordinal=0 to 1
 rows.Push({track_id:"file:f1:subtitle:"+ordinal.ToStr(),combined_index:ordinal,source:"external",codec:"subrip",language:"eng",label:"English",forced:false,default:false,hearing_impaired:false,delivery:"sidecar"})
 end for
 raw={plan_id:context.planId,plan_attempt_key:context.planAttemptKey,session_id:context.sessionId,effective_media_file_id:context.fileId,subtitle:{inventory:rows}}
 plan["sourceSubtitleInventory"]=SiloSourceSubtitleInventory(raw,plan,SiloUIOwner())
end sub
''')
            if actual_report:
                boundary.write_text(re.sub(r'(?ms)^sub PlayerReport\(.*?^end sub\n','',boundary.read_text()))
            if actual_cue:
                boundary.write_text(re.sub(r'(?ms)^function PlayerCurrentCue\(.*?^end function\n','',boundary.read_text()))
            if actual_start:
                boundary.write_text(re.sub(r'(?ms)^sub PlayerStart\(.*?^end sub\n','',boundary.read_text()))
            if actual_reset:
                boundary.write_text(re.sub(r'(?ms)^sub PlayerResetChrome\(.*?^end sub\n','',boundary.read_text())+'''sub DiagnosticsClose()
end sub
''')
            if actual_results:
                boundary_source=boundary.read_text()
                for name in ('SiloUIOwner','SiloUICleanupUuid','SiloUICancelPendingPlayback'):
                    boundary_source=re.sub(r'(?ms)^(?:sub|function) '+name+r'\(.*?^end (?:sub|function)\n', '',boundary_source)
                boundary.write_text(boundary_source)
            if actual_owned:
                boundary.write_text(re.sub(r'(?ms)^sub ApiOwned\(.*?^end sub\n','',boundary.read_text())+'''\nfunction FixtureApiTask() as Object
 if m.resetAtTaskBoundary=true and m.video.control="stop" then m.video.state="stopped":m.video.position=0
 task={nativeControl:m.video.control,observeField:sub(field as String,callback as String)
 end sub,unobserveField:sub(field as String)
 end sub}
 if m.fixtureTasks=invalid then m.fixtureTasks=[]
 m.fixtureTasks.Push(task)
 return task
end function
''')
            setup = '''m.requestId=0
 m.provider="silo":m.sourceId="silo:synthetic":m.profileId="owner":m.generation=7
 m.deleted=[]:m.pending={}:m.view="player":m.playToken=4:m.calls=[]:m.starts=[]:m.stops=[]:m.trackPref={subtitle:"eng"}
 m.playbackChoiceBusy=false:m.recoveringNative=false:m.recoverPositionMs=1234
 m.playPlan=ParseJson(''' + '"' + json.dumps(value).replace('"', '""') + '"' + ''')
 acceptedPlan=ParseJson(''' + '"' + json.dumps(accepted).replace('"', '""') + '"' + ''')
 m.video={id:"video-1",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function,state:"paused",position:37.5,setFocus:sub(value as Boolean)
 end sub,content:{id:"content-1",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}}
 m.subtitleChangeTimer={}:m.progressTimer={}:m.upNextTimer={}:m.progressSequence=9
 m.playerCue={visible:false}:m.markerLookupStarted=true
 m.top={findNode:function(id as String) as Object
 return {uri:""}
 end function}
 m.playerReturn={view:"home",zone:"heroButtons"}:m.savedCaptionMode="On"
'''
            artifact=folder/'SubtitleArtifact.brs'
            artifact.write_text((ROOT/'components/SiloUISubtitleArtifact.brs').read_text().replace('DeleteFile(uri)','FixtureDeleteFile(uri)',1))
            files = [player, artifact, *([ROOT/'components/SiloUISeekReanchor.brs'] if (ROOT/'components/SiloUISeekReanchor.brs').exists() else []), ROOT/'components/SiloUICompatPlayback.brs', ROOT/'components/SiloUIPlaybackChoices.brs',
                     ROOT/'source/adapters/SiloAdapter.brs', ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'source/core/SiloUIPlaybackChoicesPolicy.brs', ROOT/'source/core/SiloUIFormat.brs', boundary]
            if actual_report: files += [ROOT/'source/core/SiloUIPlexPolicy.brs']
            if actual_diagnostics:
                files += [ROOT/'components/SiloUIDiagnostics.brs',ROOT/'source/core/SiloUIDiagnosticsPolicy.brs']
            if actual_transport:
                transport_file=folder/'Transport.brs'
                transport_file.write_text((ROOT/'components/SiloUITransport.brs').read_text().replace('CreateObject("roSGNode", "ContentNode")','FixtureChapterRoot()'))
                files += [transport_file,ROOT/'components/SiloUITrickplay.brs',ROOT/'source/core/SiloUITransportPolicy.brs']
                boundary.write_text(boundary.read_text()+'''function FixtureChapterRoot() as Object
 return {children:[],createChild:function(kind as String) as Object
 node={addFields:sub(fields as Object)
 for each key in fields
 m[key]=fields[key]
 end for
 end sub}
 m.children.Push(node):return node
 end function,getChildCount:function() as Integer
 return m.children.Count()
 end function,getChild:function(index as Integer) as Object
 return m.children[index]
 end function}
end function
''')
            if actual_start:
                files += [ROOT/'source/core/SiloUIPlayerPolicy.brs',ROOT/'source/core/SiloUISettingsPolicy.brs',ROOT/'source/core/TrackPreference.brs']
                setup += '''m.playItem={type:"movie",title:"Synthetic",durationMs:200000}:m.detailEpisodes=[]:m.playVersions=[]
 m.preferences={}:m.trackPrefLanes={}:m.nav={}:m.toast={}:m.subtitleBindingGeneration=0
 m.video.availableAudioTracks=[]:m.video.availableSubtitleTracks=[]
 m.video.SetHttpAgent=sub(agent as Object)
 end sub
'''
            if menu:
                setup += '''m.trackDialog=invalid:m.trackList={setFocus:sub(value as Boolean)
 end sub}:m.trackPrefLanes={}
 m.video.availableAudioTracks=[]:m.video.availableSubtitleTracks=[]
 m.playVersions=[]
'''
                if not actual_start:
                    files += [ROOT/'source/core/SiloUIPlayerPolicy.brs',ROOT/'source/core/TrackPreference.brs']
            if actual_results:
                scene_source=(ROOT/'components/SiloUIScene.brs').read_text()
                for name in (('SetZone','ShowView','Toast') if actual_owned else ('ApiOwned','SetZone','ShowView','Toast')) + (('PlexClearImages',) if actual_scope else ()):
                    if actual_onboarding_ui and name == 'ShowView': continue
                    scene_source=re.sub(r'(?m)^sub '+name+r'\(', 'sub Unused'+name+'(',scene_source,count=1)
                if actual_owned:scene_source=scene_source.replace('CreateObject("roSGNode", "ApiTask")','FixtureApiTask()')
                scene_file=folder/'Scene.brs';scene_file.write_text(scene_source)
                files += [scene_file,ROOT/'components/SiloUIRobustness.brs']
            if actual_scope:
                onboarding=(ROOT/'components/SiloUIOnboarding.brs').read_text()
                for name in ('ObScreen','ObChoose','PlexClearImages'):
                    if actual_onboarding_ui and name == 'ObScreen': continue
                    onboarding=re.sub(r'(?m)^sub '+name+r'\(', 'sub Unused'+name+'(',onboarding,count=1)
                if actual_onboarding_ui:
                    onboarding=onboarding.replace('CreateObject("roSGNode", "ContentNode")','FixtureChapterRoot()')
                scope_file=folder/'Onboarding.brs'
                scope_file.write_text(onboarding)
                files += [scope_file]
                boundary.write_text(boundary.read_text()+'''sub PlexClearImages()
end sub
sub DetailPhotosClear()
end sub
''')
                setup += 'm.keyboard={}:m.searchTimer={}:m.pollTimer={}\n'
            if actual_onboarding_ui:
                files += [ROOT/'components/SiloUILan.brs']
                ui_boundary=boundary.read_text()
                for name in ('ShowView','ObScreen','HomeCacheYield','HomeCacheRetire'):
                    ui_boundary=re.sub(r'(?ms)^sub '+name+r'\(.*?^end sub\n','',ui_boundary)
                boundary.write_text(ui_boundary)
                home_source=(ROOT/'components/SiloUIHome.brs').read_text()
                for name in ('HomeRefreshHero','HomeUpdateProgress'):
                    home_source=re.sub(r'(?m)^sub '+name+r'\(', 'sub Unused'+name+'(',home_source,count=1)
                home_file=folder/'Home.brs';home_file.write_text(home_source);files += [home_file]
                setup += '''m.backdrop={}:m.backdropOld={}:m.backdropTimer={}:m.backdropFade={}
 m.obEyebrow={}:m.obTitle={}:m.obCode={}:m.obButtons={}
 m.obBody={boundingRect:function() as Object
 return {height:80}
 end function}
'''
            output = run_brightscript(files, setup+body, root=folder)
            return json.loads(output.strip().splitlines()[-1])

    def test_source_selection_resolves_pair_before_stop_and_dispatches_once(self):
        result=self.scene('''context=SiloPlaybackContext(m.playPlan,SiloUIOwner())
 raw={plan_id:context.planId,plan_attempt_key:context.planAttemptKey,session_id:context.sessionId,effective_media_file_id:context.fileId,subtitle:{inventory:[{track_id:"file:f1:subtitle:0",combined_index:0,source:"external",codec:"subrip",language:"eng",label:"English",forced:false,default:false,hearing_impaired:false,delivery:"sidecar"}]}}
 m.playPlan["sourceSubtitleInventory"]=SiloSourceSubtitleInventory(raw,m.playPlan,SiloUIOwner())
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:0",combinedIndex:1})
 invalidControl=m.video.control
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:0",combinedIndex:0})
 before=m.calls.Count():m.video.state="stopped":onVideoState():onVideoState()
 print FormatJson({invalidControl:invalidControl,before:before,count:m.calls.Count(),action:m.calls[0].action,pair:{id:m.calls[0].params.subtitleTrackId,index:m.calls[0].params.subtitleTrackIndex},position:m.calls[0].params.positionMs,request:m.subtitleChange.apiRequestId})''')
        self.assertEqual(dict(invalidControl=None,before=0,count=1,action='playback_subtitle_select',pair=dict(id='file:f1:subtitle:0',index=0),position=157500,request=1),result)

    def test_positive_failed_caption_fetch_keeps_av_and_clears_off_only_on_accept(self):
        result=self.scene('''context=SiloPlaybackContext(m.playPlan,SiloUIOwner())
 raw={plan_id:context.planId,plan_attempt_key:context.planAttemptKey,session_id:context.sessionId,effective_media_file_id:context.fileId,subtitle:{inventory:[{track_id:"file:f1:subtitle:0",combined_index:0,source:"external",codec:"subrip",language:"eng",label:"English",forced:false,default:false,hearing_impaired:false,delivery:"sidecar"}]}}
 m.playPlan["sourceSubtitleInventory"]=SiloSourceSubtitleInventory(raw,m.playPlan,SiloUIOwner())
 m.subtitleLocalOff={old:true}:m.nativeSubtitleOverride={old:true}:m.trackPref.subtitle="off"
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:0",combinedIndex:0})
 before=m.trackPref.subtitle
 m.video.state="stopped":onVideoState()
 acceptedPlan["subtitleMode"]="render":acceptedPlan.siloPlayback.selectedTracks.subtitle={id:"file:f1:subtitle:0",index:0}
 raw.plan_id=acceptedPlan.siloPlayback.planId:raw.plan_attempt_key=acceptedPlan.siloPlayback.planAttemptKey
 acceptedPlan["sourceSubtitleInventory"]=SiloSourceSubtitleInventory(raw,acceptedPlan,SiloUIOwner())
 acceptedPlan.selectedSubtitle={kind:"fetch_failed",mode:"render",trackId:"file:f1:subtitle:0",combinedIndex:0,renderingReady:false,language:"eng"}
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},m.calls[0].extra)
 print FormatJson({before:before,starts:m.starts.Count(),pref:m.trackPref.subtitle,localOff:m.subtitleLocalOff,native:m.nativeSubtitleOverride,paused:m.audioRestorePause,busy:m.playbackChoiceBusy,sequence:m.progressSequence,mode:m.video.globalCaptionMode})''')
        self.assertEqual(dict(before='off',starts=1,pref='',localOff=None,native=None,paused=True,busy=False,sequence=9,mode=None),result)

    def test_actual_api_generation_drop_drains_accepted_lease(self):
        result=self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 m.generation=8:m.view="home":m.playPlan=invalid
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({starts:m.starts.Count(),calls:m.calls.Count(),action:m.calls[1].action,owner:m.calls[1].owner,session:m.calls[1].params.sessionId})''',actual_results=True)
        self.assertEqual(dict(starts=0,calls=2,action='playback_stop',owner=dict(SCOPE,sessionRevision=0),session='session-0001'),result)

    def test_actual_refused_control_receipt_closes_advanced_authority(self):
        result=self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:false,leaseUncertain:true,controlReceipt:acceptedPlan.siloPlayback},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({starts:m.starts.Count(),stops:m.stops.Count(),view:m.view,plan:m.reportedPlan.planId,key:m.reportedPlan.siloPlayback.planAttemptKey,pref:m.trackPref.subtitle})''',actual_results=True)
        self.assertEqual(dict(starts=0,stops=1,view='home',plan='plan-0002',key='plan-key-0002',pref='eng'),result)

    def test_actual_late_receipt_never_stops_new_plan_on_same_lease(self):
        result=self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 m.playToken=5:m.playPlan["planId"]="new-plan-0003":m.playPlan.siloPlayback["planId"]="new-plan-0003"
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({starts:m.starts.Count(),stops:m.stops.Count(),calls:m.calls.Count(),plan:m.playPlan.planId,view:m.view})''',actual_results=True)
        self.assertEqual(dict(starts=0,stops=0,calls=1,plan='new-plan-0003',view='player'),result)

    def test_response_deadline_is_enforced_before_watchdog_tick(self):
        result=self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 m.subtitleChange.clock={TotalMilliseconds:function()
 return 60000
 end function}
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},m.calls[0].extra)
 print FormatJson({starts:m.starts.Count(),stops:m.stops.Count(),view:m.view})''')
        self.assertEqual(dict(starts=0,stops=1,view='home'),result)

    def test_actual_player_replacements_a_b_off_a_use_fresh_content_and_pause_guard(self):
        for paused in (False,True):
            with self.subTest(paused=paused):
                result=self.scene('''rows=[]
 for ordinal=0 to 1
 rows.Push({track_id:"file:f1:subtitle:"+ordinal.ToStr(),combined_index:ordinal,source:"external",codec:"subrip",language:"eng",label:"English",forced:false,default:false,hearing_impaired:false,delivery:"sidecar"})
 end for
 context=SiloPlaybackContext(m.playPlan,SiloUIOwner())
 raw={plan_id:context.planId,plan_attempt_key:context.planAttemptKey,session_id:context.sessionId,effective_media_file_id:context.fileId,subtitle:{inventory:rows}}
 m.playPlan["sourceSubtitleInventory"]=SiloSourceSubtitleInventory(raw,m.playPlan,SiloUIOwner())
 observations=[]
 for each ordinal in [0,1,-1,0]
 m.video.state="STATE"
 oldContent=m.video.content
 if ordinal=-1
 PlaybackSubtitleOff()
 else
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:"+ordinal.ToStr(),combinedIndex:ordinal})
 end if
 before=m.calls.Count():m.video.state="stopped":onVideoState()
 attempt=m.calls[m.calls.Count()-1].extra
 nextPlan=ParseJson(FormatJson(attempt.plan))
 nextPlan["planId"]="plan-new-"+m.requestId.ToStr()
 nextContext=nextPlan.siloPlayback:nextTracks=nextContext.selectedTracks
 nextContext["planId"]=nextPlan.planId
 nextContext["planAttemptKey"]="plan-key-new-"+m.requestId.ToStr()
 nextPlan["startPositionMs"]=37500:nextPlan["timelineOffsetMs"]=120000
 nextPlan.Delete("subtitleArtifact"):nextPlan.Delete("selectedSubtitle")
 raw.plan_id=nextPlan.planId:raw.plan_attempt_key=nextPlan.siloPlayback.planAttemptKey
 nextPlan["sourceSubtitleInventory"]=SiloSourceSubtitleInventory(raw,nextPlan,SiloUIOwner())
 if ordinal=-1
 nextPlan["subtitleMode"]="off":nextTracks.Delete("subtitle")
 nextContext["subtitleOffRequired"]=true
 else
 nextPlan["subtitleMode"]="render":nextContext.Delete("subtitleOffRequired")
 nextTracks["subtitle"]={id:"file:f1:subtitle:"+ordinal.ToStr(),index:ordinal}
 nextPlan["selectedSubtitle"]={kind:"sidecar_ready",mode:"render",renderingReady:true,trackId:"file:f1:subtitle:"+ordinal.ToStr(),combinedIndex:ordinal,language:"eng",format:"vtt",mimeType:"text/vtt"}
 nextPlan["subtitleArtifact"]={uri:"tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt",format:"vtt",mimeType:"text/vtt",timingOriginSeconds:0,owner:{sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,requestId:m.requestId,sessionRevision:0,sessionId:nextPlan.sessionId,planAttemptKey:nextPlan.siloPlayback.planAttemptKey,fileId:"f1",selectedOrdinal:ordinal,timelineOffsetMs:120000}}
 end if
 event={payload:{requestId:m.requestId,ok:true,plan:nextPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 observations.Push({fresh:not oldContent.isSameNode(m.video.content),calls:m.calls.Count()-before,mode:m.video.globalCaptionMode,pending:m.subtitleChange,pause:m.audioRestorePause,position:PlayerPositionMs(),sequence:m.progressSequence})
 m.video.state="playing":onVideoState()
 m.video.state="paused":onVideoState()
 end for
 print FormatJson({observations:observations,back:m.playerReturn,captions:m.savedCaptionMode,contentCount:m.contentCount})'''.replace('STATE','paused' if paused else 'playing'),actual_results=True,actual_start=True)
                self.assertEqual(4,result['contentCount'])
                self.assertEqual(dict(view='home',zone='heroButtons'),result['back'])
                self.assertEqual('On',result['captions'])
                self.assertEqual([dict(fresh=True,calls=1,mode='Off',pending=None,pause=paused,position=157500,sequence=9)]*4,result['observations'])

    def test_positive_selection_refuses_stale_inventory_busy_audio_and_recovery_before_stop(self):
        for edit in ('m.playbackChoiceBusy=true','m.recoveringNative=true',
                     'm.playPlan.siloPlayback["planAttemptKey"]="changed-key"',
                     'm.playPlan.cleanupOwner["generation"]=8'):
            result=self.scene('''FixtureInventory(m.playPlan)
'''+edit+'''
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:1",combinedIndex:1})
 print FormatJson({calls:m.calls.Count(),pending:m.subtitleChange<>invalid,control:m.video.control})''')
            self.assertEqual(dict(calls=0,pending=False,control=None),result)

    def test_actual_positive_back_drains_accepted_plan_before_and_after_dispatch(self):
        for dispatch in (False,True):
            result=self.scene('''FixtureInventory(m.playPlan)
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:1",combinedIndex:1})
'''+('m.video.state="stopped":onVideoState()' if dispatch else '')+'''
 PlayerKey("back")
'''+('''event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
''' if dispatch else '')+'''
 print FormatJson({starts:m.starts.Count(),reports:m.stops.Count(),calls:m.calls.Count(),view:m.view,pending:m.subtitleChange,pref:m.trackPref.subtitle})''',actual_results=True)
            self.assertEqual(dict(starts=0,reports=1,calls=2 if dispatch else 0,view='home',pending=None,pref='eng'),result)

    def test_stop_ack_deadline_boundaries_do_not_wait_for_timer(self):
        for elapsed in (4999,5000):
            result=self.scene('''PlaybackSubtitleOff()
 m.subtitleChange.clock={TotalMilliseconds:function()
 return ELAPSED
 end function}
 m.video.state="stopped":onVideoState()
 print FormatJson({calls:m.calls.Count(),stops:m.stops.Count(),view:m.view})'''.replace('ELAPSED',str(elapsed)))
            self.assertEqual(dict(calls=1 if elapsed<5000 else 0,stops=0 if elapsed<5000 else 1,view='player' if elapsed<5000 else 'home'),result)

    def test_actual_positive_wrong_artifact_owner_pair_and_inventory_are_never_installed(self):
        for edit in ('acceptedPlan.subtitleArtifact.owner["requestId"]=42',
                     'acceptedPlan.subtitleArtifact.owner["timelineOffsetMs"]=0',
                     'acceptedPlan.selectedSubtitle["trackId"]="file:f1:subtitle:1"',
                     'acceptedPlan.sourceSubtitleInventory.owner["planAttemptKey"]="old-key"',
                     'acceptedPlan["subtitleMode"]="burn_in"',
                     'acceptedPlan.selectedSubtitle["renderingReady"]="true"'):
            result=self.scene('''FixtureInventory(m.playPlan)
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:0",combinedIndex:0})
 m.video.state="stopped":onVideoState()
 acceptedPlan["subtitleMode"]="render"
 acceptedPlan.siloPlayback.selectedTracks["subtitle"]={id:"file:f1:subtitle:0",index:0}
 FixtureInventory(acceptedPlan)
 acceptedPlan["selectedSubtitle"]={kind:"sidecar_ready",mode:"render",renderingReady:true,trackId:"file:f1:subtitle:0",combinedIndex:0,language:"eng",format:"vtt",mimeType:"text/vtt"}
 acceptedPlan["subtitleArtifact"]={uri:"tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt",format:"vtt",mimeType:"text/vtt",timingOriginSeconds:0,owner:{sourceId:m.sourceId,profileId:m.profileId,generation:7,requestId:1,sessionRevision:0,sessionId:acceptedPlan.sessionId,planAttemptKey:"plan-key-0002",fileId:"f1",selectedOrdinal:0,timelineOffsetMs:120000}}
'''+edit+'''
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({starts:m.starts.Count(),stops:m.stops.Count(),view:m.view,pref:m.trackPref.subtitle,plan:m.reportedPlan.planId})''',actual_results=True)
            self.assertEqual(dict(starts=0,stops=1,view='home',pref='eng',plan='plan-0002'),result)

    def test_actual_source_switch_drains_old_positive_artifact_and_exact_owner(self):
        result=self.scene('''FixtureInventory(m.playPlan)
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:0",combinedIndex:0})
 m.video.state="stopped":onVideoState()
 acceptedPlan["subtitleMode"]="render"
 acceptedPlan["selectedSubtitle"]={kind:"sidecar_ready",mode:"render",renderingReady:true,trackId:"file:f1:subtitle:0",combinedIndex:0,language:"eng",format:"vtt",mimeType:"text/vtt"}
 acceptedPlan["subtitleArtifact"]={uri:"tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt",format:"vtt",mimeType:"text/vtt",timingOriginSeconds:0,owner:{sourceId:m.sourceId,profileId:m.profileId,generation:7,requestId:1,sessionRevision:0,sessionId:acceptedPlan.sessionId,planAttemptKey:"plan-key-0002",fileId:"f1",selectedOrdinal:0,timelineOffsetMs:120000}}
 m.sourceId="silo:other":m.generation=8:m.playToken=5
 m.playPlan["cleanupOwner"]={provider:"silo",sourceId:"silo:other",profileId:"owner",generation:8,sessionRevision:0}
 m.playPlan["planId"]="other-plan"
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({starts:m.starts.Count(),stops:m.stops.Count(),calls:m.calls.Count(),cleanupOwner:m.calls[1].owner,deleted:m.deleted,active:m.playPlan.planId})''',actual_results=True)
        self.assertEqual(dict(starts=0,stops=0,calls=2,cleanupOwner=dict(SCOPE,sessionRevision=0),deleted=['tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt'],active='other-plan'),result)

    def test_burned_off_refusal_never_falls_back_to_local_caption_off(self):
        result=self.scene('''m.playPlan.cleanupOwner["generation"]=8
 m.trackDialog={visible:true}:m.trackList={itemSelected:0}
 m.trackChoices=[{kind:"subtitle",trackId:"",language:"",name:""}]
 onPlayerTrackChoice()
 print FormatJson({calls:m.calls.Count(),pending:m.subtitleChange<>invalid,pref:m.trackPref.subtitle,mode:m.video.globalCaptionMode,control:m.video.control})''')
        self.assertEqual(dict(calls=0,pending=False,pref='eng',mode=None,control=None),result)

    def test_actual_off_to_embedded_render_refuses_unqualified_native_mapping(self):
        result=self.scene('''m.playPlan["subtitleMode"]="off":m.playPlan.siloPlayback.selectedTracks.Delete("subtitle")
 FixtureInventory(m.playPlan)
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:0",combinedIndex:0})
 m.video.state="stopped":onVideoState()
 acceptedPlan["subtitleMode"]="render"
 acceptedPlan.siloPlayback.selectedTracks["subtitle"]={id:"file:f1:subtitle:0",index:0}
 FixtureInventory(acceptedPlan)
 acceptedPlan["selectedSubtitle"]={kind:"embedded_render",mode:"render",renderingReady:false,trackId:"file:f1:subtitle:0",combinedIndex:0}
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({starts:m.starts.Count(),stops:m.stops.Count(),view:m.view,plan:SpField(m.reportedPlan,"planId")})''',actual_results=True)
        self.assertEqual(dict(starts=0,stops=1,view='home',plan='plan-0002'),result)

    def test_actual_source_transition_waits_for_subtitle_result_and_cleanup_ack(self):
        for selection in (False,True):
            result=self.scene('''FixtureInventory(m.playPlan)
'''+('PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:0",combinedIndex:0})' if selection else 'PlaybackSubtitleOff()')+'''
 m.video.state="stopped":onVideoState()
 PlayerClose(false)
 SiloUIBeginTransition({action:"source_switch"})
 before={generation:m.generation,pending:m.pending.Count(),cancelled:m.pending["1"].task.cancelled}
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 afterReplacement={generation:m.generation,pending:m.pending.Count(),tickets:m.cleanupTickets.Count()}
 event.payload={requestId:2,ok:true}
 onApiResult(event)
 print FormatJson({before:before,afterReplacement:afterReplacement,generation:m.generation,source:m.sourceId,choices:m.transitionChoices,pending:m.pending.Count(),tickets:m.cleanupTickets.Count()})''',actual_results=True)
            self.assertEqual(dict(before=dict(generation=7,pending=1,cancelled=True),afterReplacement=dict(generation=7,pending=1,tickets=1),generation=8,source='silo:next',choices=1,pending=0,tickets=0),result)

    def test_selected_sidecar_off_uses_provider_receipt_and_native_stop(self):
        result=self.scene('''m.playPlan["subtitleMode"]="render"
 handled=PlaybackSubtitleOff()
 before=m.calls.Count():m.video.state="stopped":onVideoState()
 action=""
 if m.calls.Count()>0 then action=m.calls[0].action
 print FormatJson({handled:handled,before:before,count:m.calls.Count(),busy:m.playbackChoiceBusy,action:action})''')
        self.assertEqual(dict(handled=True,before=0,count=1,busy=True,action='playback_subtitle_off'),result)

    def test_stops_before_request_and_dispatches_once_with_captured_position(self):
        result = self.scene('''handled=PlaybackSubtitleOff()
 before=m.calls.Count():control=m.video.control
 m.video.state="stopped":onVideoState():onVideoState()
 print FormatJson({handled:handled,before:before,control:control,count:m.calls.Count(),action:m.calls[0].action,position:m.calls[0].params.positionMs,owner:m.calls[0].owner,paused:m.subtitleChange.paused})''')
        self.assertEqual(dict(handled=True, before=0, control='stop', count=1,
                              action='playback_subtitle_off', position=157500,
                              owner=dict(SCOPE, sessionRevision=0), paused=True), result)

    def test_accepted_off_preserves_owner_position_sequence_return_and_paused_intent(self):
        result = self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 nextPlan=acceptedPlan
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:nextPlan},m.calls[0].extra)
 print FormatJson({starts:m.starts.Count(),owner:m.playPlan.cleanupOwner,sequence:m.progressSequence,back:m.playerReturn,captions:m.savedCaptionMode,pause:m.audioRestorePause,pref:m.trackPref.subtitle,busy:m.playbackChoiceBusy,pending:m.subtitleChange,timer:m.subtitleChangeTimer.control,mode:m.video.globalCaptionMode,stops:m.stops.Count()})''')
        self.assertEqual(dict(starts=1,owner=dict(SCOPE,sessionRevision=0),sequence=9,
                              back=dict(view='home',zone='heroButtons'),captions='On',pause=True,
                              pref='off',busy=False,pending=None,timer='stop',mode='Off',stops=0),result)

    def test_accepted_off_retires_old_local_caption_when_native_already_stopped(self):
        result = self.scene('''m.simulateBindingRetire=true
 m.subtitleBinding={uri:"tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt",content:m.video.content,bindingGeneration:1}
 m.subtitleRetired=[]
 PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},m.calls[0].extra)
 print FormatJson({starts:m.starts.Count(),retired:m.subtitleRetired.Count(),binding:m.subtitleBinding,content:m.video.content})''')
        self.assertEqual(1, result['starts'])
        self.assertEqual(0, result['retired'])
        self.assertIsNone(result['binding'])
        self.assertIsNone(result['content'])

    def test_paused_off_waits_for_native_start_position_before_pausing(self):
        result = self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 acceptedPlan.startPositionMs=10000:acceptedPlan.timelineOffsetMs=0
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},m.calls[0].extra)
 m.video.position=0:m.video.state="playing":onVideoState()
 atZero={control:m.video.control,mute:m.video.mute,intent:m.audioRestorePause}
 m.video.position=10:onPlayerPosition()
 atTarget={control:m.video.control,mute:m.video.mute,intent:m.audioRestorePause}
 m.video.state="paused":onVideoState()
 print FormatJson({atZero:atZero,atTarget:atTarget,afterAck:{control:m.video.control,mute:m.video.mute,intent:m.audioRestorePause}})''')
        self.assertEqual({'control':'play','mute':True,'intent':True}, result['atZero'])
        self.assertEqual({'control':'pause','mute':True,'intent':False}, result['atTarget'])
        self.assertEqual({'control':'pause','mute':False,'intent':False}, result['afterAck'])

    def test_paused_off_accepts_zero_native_start_for_rebased_hls(self):
        result = self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 acceptedPlan.startPositionMs=0:acceptedPlan.timelineOffsetMs=10000
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},m.calls[0].extra)
 m.video.position=0:m.video.state="playing":onVideoState()
 atZero={control:m.video.control,mute:m.video.mute,intent:m.audioRestorePause}
 m.video.state="paused":onVideoState()
 print FormatJson({atZero:atZero,afterAck:{control:m.video.control,mute:m.video.mute,intent:m.audioRestorePause}})''')
        self.assertEqual({'control':'pause','mute':True,'intent':False}, result['atZero'])
        self.assertEqual({'control':'pause','mute':False,'intent':False}, result['afterAck'])

    def test_back_cancels_before_or_after_dispatch_and_never_installs_late_result(self):
        for dispatch in [False, True]:
            with self.subTest(dispatch=dispatch):
                result = self.scene('''PlaybackSubtitleOff()
 extra=m.subtitleChange
''' + ('m.video.state="stopped":onVideoState()\n' if dispatch else '') + '''PlayerKey("back")
 PlaybackSubtitleChangeResult({ok:false},extra)
 print FormatJson({calls:m.calls.Count(),starts:m.starts.Count(),stops:m.stops,view:m.view,pending:m.subtitleChange,busy:m.playbackChoiceBusy,pref:m.trackPref.subtitle})''')
                self.assertEqual(dict(calls=int(dispatch),starts=0,stops=[dict(action='playback_stop',position=157500)],
                                      view='home',pending=None,busy=False,pref='eng'),result)

    def test_stop_deadline_is_bounded_without_dispatch_or_false_completion(self):
        result = self.scene('''PlaybackSubtitleOff()
 m.subtitleChange.clock={TotalMilliseconds:function()
 return 5001
 end function}
 onSubtitleChangeTimer()
 print FormatJson({calls:m.calls.Count(),stops:m.stops,pending:m.subtitleChange,view:m.view,pref:m.trackPref.subtitle})''')
        self.assertEqual(dict(calls=0,stops=[dict(action='playback_stop',position=157500)],pending=None,view='home',pref='eng'),result)

    def test_real_off_menu_uses_provider_transition_for_burned_captions(self):
        result = self.scene('''m.trackDialog={visible:true}:m.trackList={itemSelected:0}
 m.trackChoices=[{kind:"subtitle",trackId:"",language:"",name:""}]
 onPlayerTrackChoice()
 print FormatJson({control:m.video.control,calls:m.calls.Count(),pending:m.subtitleChange<>invalid,pref:m.trackPref.subtitle,dialog:m.trackDialog})''')
        self.assertEqual(dict(control='stop',calls=0,pending=True,pref='eng',dialog=None),result)

    def test_native_caption_off_remains_local_and_unknown_mode_does_not_claim_off(self):
        for mode in ['off','unknown']:
            with self.subTest(mode=mode):
                result = self.scene('''m.playPlan["subtitleMode"]="''' + mode + '''"
 m.trackDialog={visible:true}:m.trackList={itemSelected:0}
 m.trackChoices=[{kind:"subtitle",trackId:"",language:"",name:""}]
 onPlayerTrackChoice()
 print FormatJson({calls:m.calls.Count(),pending:m.subtitleChange<>invalid,pref:m.trackPref.subtitle,mode:m.video.globalCaptionMode})''')
                self.assertEqual(dict(calls=0,pending=False,pref='eng' if mode=='unknown' else 'off',
                                      mode=None if mode=='unknown' else 'Off'),result)

    def test_refused_or_changed_receipts_stop_once_without_committing_off(self):
        for change in ['unsupported','burn','subtitle','audio','file','quality']:
            edits = {
                'unsupported':'response={requestId:1,ok:false,errorCode:"unsupported_playback_protocol"}',
                'burn':'acceptedPlan["subtitleMode"]="burn_in"',
                'subtitle':'acceptedPlan.siloPlayback.selectedTracks["subtitle"]={id:"file:f1:subtitle:0",index:0}',
                'audio':'acceptedPlan.siloPlayback.selectedTracks["audio"]={id:"file:f1:audio:1",index:1}',
                'file':'acceptedPlan["versionId"]="other"',
                'quality':'acceptedPlan.siloPlayback["qualityPreference"]="720p"',
            }
            with self.subTest(change=change):
                result = self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 response={requestId:1,ok:true,plan:acceptedPlan}
''' + edits[change] + '''
 PlaybackSubtitleChangeResult(response,m.calls[0].extra)
 print FormatJson({starts:m.starts.Count(),stops:m.stops.Count(),view:m.view,pref:m.trackPref.subtitle,pending:m.subtitleChange})''')
                self.assertEqual(dict(starts=0,stops=1,view='home',pref='eng',pending=None),result)

    def test_request_deadline_and_superseded_content_never_install_late_response(self):
        for superseded in [False,True]:
            with self.subTest(superseded=superseded):
                edit = 'm.video.content={id:"other"}' if superseded else ''
                result = self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 extra=m.calls[0].extra
 m.subtitleChange.clock={TotalMilliseconds:function()
 return 60001
 end function}
''' + edit + '''
 onSubtitleChangeTimer()
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},extra)
 print FormatJson({starts:m.starts.Count(),stops:m.stops.Count(),pending:m.subtitleChange,pref:m.trackPref.subtitle})''')
                self.assertEqual(dict(starts=0,stops=1,pending=None,pref='eng'),result)


    def test_lost_native_binding_closes_owned_attempt_and_releases_busy_flags(self):
        for dispatched in (False, True):
            for content in ('invalid', '{id:"replacement"}'):
                with self.subTest(dispatched=dispatched,content=content):
                    result=self.scene('''PlaybackSubtitleOff()
 extra=m.subtitleChange
'''+('m.video.state="stopped":onVideoState()\n' if dispatched else '')+'''
 m.video.content='''+content+'''
 onSubtitleChangeTimer()
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},extra)
 print FormatJson({view:m.view,busy:m.playbackChoiceBusy,recovering:m.recoveringNative,pending:m.subtitleChange,starts:m.starts.Count(),stops:m.stops,pref:m.trackPref.subtitle})''')
                    self.assertEqual(dict(view='home',busy=False,recovering=False,pending=None,starts=0,
                                          stops=[dict(action='playback_stop',position=157500)],pref='eng'),result)

    def test_new_playback_owner_is_not_closed_when_old_content_is_gone(self):
        result=self.scene('''PlaybackSubtitleOff()
 m.playToken=5:m.playPlan["sessionId"]="new-session":m.video.content={id:"new"}
 onSubtitleChangeTimer()
 print FormatJson({view:m.view,starts:m.starts.Count(),stops:m.stops.Count(),pending:m.subtitleChange,session:m.playPlan.sessionId})''')
        self.assertEqual(dict(view='player',starts=0,stops=0,pending=None,session='new-session'),result)


    def test_back_before_paused_seek_lands_keeps_captured_resume(self):
        result=self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 acceptedPlan["startPositionMs"]=157500:acceptedPlan["timelineOffsetMs"]=0
 acceptedPlan["originalResumeMs"]=157500
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},m.calls[0].extra)
 m.video.position=0:m.video.state="playing":onVideoState()
 PlayerKey("back")
 print FormatJson({view:m.view,stops:m.stops})''')
        self.assertEqual(dict(view='home',stops=[dict(action='playback_stop',position=157500)]),result)


    def test_unlanded_paused_seek_stops_with_captured_position_at_deadline(self):
        result=self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 acceptedPlan["startPositionMs"]=157500:acceptedPlan["timelineOffsetMs"]=0
 acceptedPlan["originalResumeMs"]=157500
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},m.calls[0].extra)
 m.video.position=0:m.video.state="playing":onVideoState()
 m.pauseRestoreClock={TotalMilliseconds:function()
 return 10001
 end function}
 onProgressTimer()
 print FormatJson({view:m.view,stops:m.stops,restore:m.audioRestorePause})''')
        self.assertEqual(dict(view='home',stops=[dict(action='playback_stop',position=157500)],restore=False),result)


    def test_pending_paused_seek_does_not_report_progress_before_landing(self):
        result=self.scene('''PlaybackSubtitleOff():m.video.state="stopped":onVideoState()
 acceptedPlan["startPositionMs"]=157500:acceptedPlan["timelineOffsetMs"]=0
 acceptedPlan["originalResumeMs"]=157500
 PlaybackSubtitleChangeResult({requestId:1,ok:true,plan:acceptedPlan},m.calls[0].extra)
 m.video.position=0:m.video.state="playing":onVideoState()
 onProgressTimer()
 print FormatJson({view:m.view,reports:m.stops,restore:m.audioRestorePause})''')
        self.assertEqual(dict(view='player',reports=[],restore=True),result)


if __name__ == '__main__':
    unittest.main()
