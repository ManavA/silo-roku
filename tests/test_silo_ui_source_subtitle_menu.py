"""Dormant source text menu through actual Scene dialog callbacks."""
import unittest
from tests import test_silo_ui_subtitle_off_flow as flow


class SourceSubtitleMenu(unittest.TestCase):
    scene = flow.SubtitleOffFlow.scene

    def test_strict_gate_keeps_legacy_menu_and_true_projects_canonical_choices(self):
        observed = self.scene('''m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 FixtureInventory(m.playPlan)
 snapshots=[]
 for each enabled in [invalid,false,"true",1,true]
 m.sourceSubtitleMenuEnabled=enabled:m.trackDialog=invalid
 PlayerShowTracks()
 rows=[]
 for rowIndex=0 to m.trackChoices.Count()-1
 row=m.trackChoices[rowIndex]:rows.Push({kind:row.kind,title:row.title,trackId:row.trackId,combinedIndex:row.combinedIndex})
 end for
 snapshots.Push(rows)
 end for
 print FormatJson(snapshots)''', menu=True)
        self.assertEqual([['subtitle']]*4, [[r['kind'] for r in rows] for rows in observed[:4]])
        self.assertEqual(['subtitle','source_subtitle','source_subtitle'], [r['kind'] for r in observed[4]])
        self.assertEqual(['file:f1:subtitle:0','file:f1:subtitle:1'], [r['trackId'] for r in observed[4][1:]])
        self.assertEqual([0,1], [r['combinedIndex'] for r in observed[4][1:]])
        self.assertIn('English', observed[4][1]['title'])

    def test_actual_choice_stops_before_dispatch_and_preserves_native_intent(self):
        observed=self.scene('''m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 FixtureInventory(m.playPlan):m.sourceSubtitleMenuEnabled=true
 m.nativeSubtitleOverride={old:true}:m.subtitleLocalOff={old:true}
 m.video.globalCaptionMode="Off":m.video.subtitleTrack="native-kept"
 PlayerShowTracks():m.trackList.itemSelected=2:onPlayerTrackChoice()
 before={calls:m.calls.Count(),control:m.video.control,pref:m.trackPref.subtitle,override:SpField(m.nativeSubtitleOverride,"old"),localOff:SpField(m.subtitleLocalOff,"old"),mode:m.video.globalCaptionMode,native:m.video.subtitleTrack,dialog:m.trackDialog,rows:m.trackChoices.Count()}
 m.video.state="stopped":onVideoState():onVideoState()
 call={params:{}}:if m.calls.Count()>0 then call=m.calls[0]
 print FormatJson({before:before,count:m.calls.Count(),action:call.action,pair:call.params.subtitleTrackId,index:call.params.subtitleTrackIndex})''',menu=True)
        self.assertEqual(dict(calls=0,control='stop',pref='eng',override=True,localOff=True,mode='Off',native='native-kept',dialog=None,rows=0),observed['before'])
        self.assertEqual((1,'playback_subtitle_select','file:f1:subtitle:1',1),(observed['count'],observed['action'],observed['pair'],observed['index']))

    def test_legacy_or_missing_inventory_falls_back_to_existing_menu(self):
        observed=self.scene('''m.sourceSubtitleMenuEnabled=true
 FixtureInventory(m.playPlan)
 PlayerShowTracks():legacy=m.trackChoices
 m.trackDialog=invalid:m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 m.playPlan.Delete("sourceSubtitleInventory"):PlayerShowTracks()
 print FormatJson({legacy:legacy,missing:m.trackChoices})''',menu=True)
        self.assertEqual(['subtitle'],[r['kind'] for r in observed['legacy']])
        self.assertEqual(['subtitle'],[r['kind'] for r in observed['missing']])

    def test_actual_menu_a_b_off_a_replaces_content_running_and_paused(self):
        for paused in (False,True):
            with self.subTest(paused=paused):
                observed=self.scene('''m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 m.sourceSubtitleMenuEnabled=true
 rows=[]
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
 PlayerShowTracks()
 if ordinal=-1 then m.trackList.itemSelected=0 else m.trackList.itemSelected=ordinal+1
 onPlayerTrackChoice()
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
 observations.Push({fresh:not oldContent.isSameNode(m.video.content),calls:m.calls.Count()-before,mode:m.video.globalCaptionMode,pending:m.subtitleChange,pause:m.audioRestorePause,position:PlayerPositionMs(),sequence:m.progressSequence,rows:m.trackChoices.Count()})
 m.video.state="playing":onVideoState()
 m.video.state="paused":onVideoState()
 end for
 print FormatJson({observations:observations,back:m.playerReturn,captions:m.savedCaptionMode,contentCount:m.contentCount})'''.replace('STATE','paused' if paused else 'playing'),menu=True,actual_results=True,actual_start=True)
                self.assertEqual(4,observed['contentCount'])
                self.assertEqual(dict(view='home',zone='heroButtons'),observed['back'])
                self.assertEqual('On',observed['captions'])
                self.assertEqual([dict(fresh=True,calls=1,mode='Off',pending=None,pause=paused,position=157500,sequence=9,rows=0)]*4,observed['observations'])

    def test_stale_dialog_scope_owner_inventory_content_and_busy_refuse_without_writes(self):
        observed=self.scene('''m.sourceSubtitleMenuEnabled=true
 baseline=FormatJson(m.playPlan):out=[]
 cases=["gate","token","source","profile","generation","revision","session","file","plan","request","attempt","count","owner","inventory","bitmap","content","busy","recovery","cleanup_owner"]
 for caseIndex=0 to cases.Count()-1
 edit=cases[caseIndex]
 m.playPlan=ParseJson(baseline):m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 m.sourceSubtitleMenuEnabled=true:m.playbackChoiceBusy=false:m.recoveringNative=false
 m.sourceId="silo:synthetic":m.profileId="owner":m.generation=7:m.playToken=4
 m.trackDialog=invalid:m.video.control=invalid:m.video.globalCaptionMode="Off":m.video.subtitleTrack="native-untouched"
 m.video.content={id:"original",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}
 FixtureInventory(m.playPlan):PlayerShowTracks():m.trackList.itemSelected=2
 if edit="gate" then m.sourceSubtitleMenuEnabled="true"
 if edit="token" then m.playToken=5
 if edit="source" then m.sourceId="silo:other"
 if edit="profile" then m.profileId="other"
 if edit="generation" then m.generation=8
 if edit="revision" then m.playPlan.siloPlayback["sessionRevision"]=1
 if edit="session" then m.playPlan.siloPlayback["sessionId"]="session-new"
 if edit="file" then m.playPlan.siloPlayback["fileId"]="f2"
 if edit="plan" then m.playPlan.siloPlayback["planId"]="plan-new"
 if edit="request" then m.playPlan.siloPlayback["planAttemptId"]="request-new"
 if edit="attempt" then m.playPlan.siloPlayback["playbackAttemptId"]="attempt-new"
 if edit="count"
 m.playPlan.siloPlayback["attemptCount"]=1
 FixtureInventory(m.playPlan)
 end if
 if edit="owner" then m.playPlan.sourceSubtitleInventory.owner["generation"]=8
 if edit="inventory" then m.playPlan.sourceSubtitleInventory.entries[0]["combinedIndex"]=5
 if edit="bitmap" then m.playPlan.sourceSubtitleInventory.entries[1]["codec"]="hdmv_pgs_subtitle"
 if edit="content" then m.video.content={id:"new"}
 if edit="busy" then m.playbackChoiceBusy=true
 if edit="recovery" then m.recoveringNative=true
 if edit="cleanup_owner" then m.playPlan.cleanupOwner["generation"]=8
 onPlayerTrackChoice()
 out.Push({control:m.video.control,pending:m.subtitleChange<>invalid,calls:m.calls.Count(),native:m.video.subtitleTrack,mode:m.video.globalCaptionMode,pref:m.trackPref.subtitle,dialogOpen:m.trackDialog<>invalid})
 end for
 print FormatJson(out)''',menu=True)
        self.assertEqual([dict(control=None,pending=False,calls=0,native='native-untouched',mode='Off',pref='eng',dialogOpen=True)]*19,observed)

    def test_unsupported_rows_are_truthful_and_metadata_is_bounded(self):
        observed=self.scene('''m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 FixtureInventory(m.playPlan):m.sourceSubtitleMenuEnabled=true
 entries=m.playPlan.sourceSubtitleInventory.entries
 entries[0]["codec"]="hdmv_pgs_subtitle":entries[0]["delivery"]="burn_in_only"
 entries[1]["label"]="":entries[1]["forced"]=true:entries[1]["hearingImpaired"]=true
 PlayerShowTracks():m.trackList.itemSelected=1:onPlayerTrackChoice()
 rows=[]
 for rowIndex=0 to m.trackChoices.Count()-1
 row=m.trackChoices[rowIndex]:rows.Push({kind:row.kind,title:row.title})
 end for
 print FormatJson({rows:rows,calls:m.calls.Count(),control:m.video.control,message:m.message,dialogOpen:m.trackDialog<>invalid})''',menu=True)
        self.assertEqual(['subtitle','source_subtitle_unavailable','source_subtitle'],[r['kind'] for r in observed['rows']])
        self.assertIn('Unavailable',observed['rows'][1]['title'])
        self.assertEqual('Source subtitles: English · SUBRIP · Forced · SDH',observed['rows'][2]['title'])
        self.assertEqual((0,None,True),(observed['calls'],observed['control'],observed['dialogOpen']))
        self.assertIn('unavailable',observed['message'])

    def test_malformed_inventory_preserves_native_audio_subtitle_and_source_audio_menu(self):
        observed=self.scene('''m.playPlan["subtitleMode"]="off":m.playPlan.siloPlayback.selectedTracks.Delete("subtitle")
 m.playPlan["selectedSubtitle"]={kind:"off",mode:"off",renderingReady:false}
 m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 m.sourceSubtitleMenuEnabled=true:FixtureInventory(m.playPlan)
 m.playPlan.sourceSubtitleInventory.entries[1]["forced"]="false"
 m.video.availableAudioTracks=[{Track:"native-audio",Name:"Main",Language:"eng",Codec:"aac"}]
 m.video.availableSubtitleTracks=[{TrackName:"native-subtitle",Description:"French",Language:"fra"}]
 m.playVersions=[{versionId:"f1",audioTracks:[{index:0,title:"English",language:"eng",codec:"aac"}]}]
 PlayerShowTracks()
 kinds=[]:for rowIndex=0 to m.trackChoices.Count()-1:kinds.Push(m.trackChoices[rowIndex].kind):end for
 print FormatJson(kinds)''',menu=True)
        self.assertEqual(['audio','subtitle','subtitle','source_audio'],observed)

    def test_custom_source_label_keeps_language_and_bounded_metadata(self):
        observed=self.scene('''m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 FixtureInventory(m.playPlan):m.sourceSubtitleMenuEnabled=true
 entry=m.playPlan.sourceSubtitleInventory.entries[1]
 entry["label"]="Dialogue":entry["language"]="fra":entry["codec"]="webvtt"
 PlayerShowTracks()
 print FormatJson({title:m.trackChoices[2].title})''',menu=True)
        self.assertEqual('Source subtitles: Dialogue · French · WEBVTT',observed['title'])

    def test_back_and_options_release_captured_rows(self):
        observed=self.scene('''m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 FixtureInventory(m.playPlan):m.sourceSubtitleMenuEnabled=true:out=[]
 for each key in ["back","options"]
 PlayerShowTracks():handled=PlayerKey(key)
 out.Push({handled:handled,dialog:m.trackDialog,rows:m.trackChoices.Count(),calls:m.calls.Count(),control:m.video.control})
 end for
 print FormatJson(out)''',menu=True)
        self.assertEqual([dict(handled=True,dialog=None,rows=0,calls=0,control=None)]*2,observed)

    def test_scope_auth_close_and_reset_release_menu_snapshots(self):
        for action in ('scope','reset','close','auth'):
            with self.subTest(action=action):
                commands={
                    'scope':'ObResetScope()',
                    'reset':'m.trackDialog=invalid:PlayerResetChrome()',
                    'close':'PlayerClose(false,false)',
                    'auth':'''ApiOwned("detail",{},"menu_auth_probe",invalid,m.playPlan.cleanupOwner)
 event={payload:{requestId:1,ok:false,errorCode:"auth_required"},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)'''}
                observed=self.scene('''m.playPlan.siloPlayback["mediaAuthMode"]="api_header_v1"
 FixtureInventory(m.playPlan):m.sourceSubtitleMenuEnabled=true
 PlayerShowTracks()
'''+commands[action]+'''
 print FormatJson({rows:m.trackChoices.Count(),dialog:m.trackDialog})''',menu=True,actual_reset=True,actual_scope=True,actual_results=True)
                self.assertEqual(dict(rows=0,dialog=None),observed)
