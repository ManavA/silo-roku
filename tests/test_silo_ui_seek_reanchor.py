"""Actual shipping custom seek dispatch; lifecycle fix belongs to plan tasks4–6."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class SiloUISeekReanchorTests(unittest.TestCase):
 def scene(self,body):
  with tempfile.TemporaryDirectory() as d:
   t=Path(d);transport=t/'transport.brs'
   transport.write_text(re.sub(r'sub TransportPaint\(\).*?\nend sub','sub TransportPaint()\nend sub',(ROOT/'components/SiloUITransport.brs').read_text(),flags=re.S))
   notice=t/'notice.brs';notice.write_text('sub Toast(message as String)\n m.message=message\nend sub')
   source='''m.transportEnabled=true:m.transport={visible:true}:m.transportOffsetMs=0:m.transportRepeats=0
m.transportPreviewMs=invalid:m.video={seek:-1,position:10}:m.playItem={durationMs:7200000}
m.playPlan={provider:"silo",canSeekAnywhere:false,timelineOffsetMs:0}:m.view="player"
'''+body
   return json.loads(run_brightscript([notice,transport,ROOT/'components/SiloUIPlayer.brs',ROOT/'components/SiloUISeekReanchor.brs',ROOT/'source/core/SiloUITransportPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/core/SiloPlaybackPolicy.brs'],source,root=t))
 def test_restricted_future_preview_commit_never_writes_native_seek(self):
  v=self.scene('''m.transportPreviewMs=120000
accepted=TransportKey("OK")
print FormatJson({seek:m.video.seek})''')
  self.assertEqual(-1,v['seek'])
 def test_chapter_before_resumed_origin_never_writes_negative_native_seek(self):
  v=self.scene('''m.playPlan.timelineOffsetMs=60000:m.chapterOpen=true
m.chapterList={itemSelected:0,content:{getChild:function(index)
 return {positionMs:20000}
end function}}
m.top={findNode:function(id)
 return {visible:true}
end function}
m.manualFocus={setFocus:sub(value)
end sub}
onTransportChapter()
print FormatJson({seek:m.video.seek})''')
  self.assertEqual(-1,v['seek'])
 def test_seekable_vod_retains_native_relative_seek(self):
  v=self.scene('''m.playPlan.canSeekAnywhere=true:m.playPlan.timelineOffsetMs=60000
accepted=PlayerSeekTo(90000)
print FormatJson({accepted:accepted,seek:m.video.seek})''')
  self.assertEqual({'accepted':True,'seek':30},v)


 def test_complete_authoritative_window_only_and_finite_source_bounds(self):
  for target,window,expected in [(90000,'m.playPlan.seekWindowStartMs=60000:m.playPlan.seekWindowEndMs=100000',30),
                                 (110000,'m.playPlan.seekWindowStartMs=60000:m.playPlan.seekWindowEndMs=100000',-1),
                                 (90000,'m.playPlan.seekWindowStartMs=60000',-1),
                                 (-1,'',-1),('"90000"','',-1),(7200001,'',-1)]:
   with self.subTest(target=target,window=window):
    v=self.scene('m.playPlan.timelineOffsetMs=60000:'+window+'\naccepted=PlayerSeekTo('+str(target)+')\nprint FormatJson({seek:m.video.seek})')
    self.assertEqual(expected,v['seek'])


 def test_restricted_known_window_cannot_seek_during_another_mutation(self):
  v=self.scene('m.playbackChoiceBusy=true:m.playPlan.seekWindowStartMs=0:m.playPlan.seekWindowEndMs=100000\naccepted=PlayerSeekTo(90000)\nprint FormatJson({accepted:accepted,seek:m.video.seek})')
  self.assertEqual(dict(accepted=False,seek=-1),v)


class SiloUISeekLifecycleTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from tests.test_silo_seek_reanchor_task import SiloSeekReanchorTaskTests
  value=SiloSeekReanchorTaskTests().run_seek()
  cls.seed=value['start'];cls.returned=value['outcome']['plan']
  cls.seed['cleanupOwner']={'provider':'silo','sourceId':'silo:synthetic','profileId':'owner','generation':7,'sessionRevision':0}
 def scene(self,body,**kwargs):
  from tests.test_silo_ui_subtitle_off_flow import SubtitleOffFlow
  return SubtitleOffFlow().scene('m.seekReanchorEnabled=true:m.seekReanchorTimer={}:m.manualFocus={setFocus:sub(value as Boolean)\n end sub}\n'+body,
      seed_plan=self.seed,returned_plan=self.returned,actual_results=True,actual_start=True,**kwargs)
 def test_stop_ack_dispatches_exactly_once_and_consumes_play(self):
  v=self.scene('''accepted=PlayerSeekTo(125375)
 before=m.calls.Count():control=m.video.control
 PlayerKey("play"):duplicate=PlayerSeekTo(150000)
 m.video.state="stopped":onVideoState():onVideoState()
 action="":target=invalid
 if m.calls.Count()>0 then action=m.calls[0].action:target=m.calls[0].params.positionMs
 print FormatJson({accepted:accepted,before:before,control:control,duplicate:duplicate,count:m.calls.Count(),action:action,target:target})''')
  self.assertTrue(v['accepted'],v)
  self.assertEqual((0,'stop',False,1),(v['before'],v['control'],v['duplicate'],v['count']))
  self.assertEqual('playback_seek_reanchor',v['action'])
  self.assertEqual(125375,v['target'])
 def test_owned_response_binds_fresh_content_and_requires_direct_landing_pause_ack(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 old=m.video.content
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 fresh=not old.isSameNode(m.video.content)
 m.video.position=0:m.video.state="playing":onVideoState()
 shortPending=m.seekReanchor<>invalid:shortControl=m.video.control
 synthetic=PlayerPositionMs()
 onProgressTimer():onPlayerPosition()
 m.video.position=1.375:onPlayerPosition()
 landingControl=m.video.control:landingPending=m.seekReanchor<>invalid
 m.video.state="paused":onVideoState()
 print FormatJson({fresh:fresh,shortPending:shortPending,shortControl:shortControl,synthetic:synthetic,landingControl:landingControl,landingPending:landingPending,done:m.seekReanchor=invalid,muted:m.video.mute,sequence:m.progressSequence,reports:m.stops})''')
  self.assertEqual(dict(fresh=True,shortPending=True,shortControl='play',synthetic=125375,landingControl='pause',landingPending=True,done=True,muted=False,sequence=9,reports=[]),v)
 def test_subsecond_local_start_requires_fresh_position_before_landing(self):
  v=self.scene('''acceptedPlan["startPositionMs"]=787.4584:acceptedPlan["timelineOffsetMs"]=4212.5417
 m.playPlan.seekWindowEndMs=invalid
 m.video.state="playing":PlayerSeekTo(5000):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 bound=m.seekReanchor<>invalid
 m.video.position=0:m.video.state="playing":onVideoState():onSeekReanchorTimer():onPlayerPosition()
 zero={pending:m.seekReanchor<>invalid,trusted:m.playLastPositionMs}
 m.video.position=0.7874584:onVideoState():onSeekReanchorTimer()
 stateOnly=m.seekReanchor<>invalid
 onPlayerPosition()
 print FormatJson({bound:bound,zero:zero,stateOnly:stateOnly,done:m.seekReanchor=invalid,trusted:m.playLastPositionMs})''')
  self.assertTrue(v["bound"],v)
  self.assertEqual(dict(zero=dict(pending=True,trusted=37500),stateOnly=True,done=True),{k:v[k] for k in ('zero','stateOnly','done')})
  self.assertAlmostEqual(5000,v['trusted'],places=2)

 def test_fresh_landing_accounts_for_only_observed_playing_time(self):
  v=self.scene('''acceptedPlan["startPositionMs"]=787.4584:acceptedPlan["timelineOffsetMs"]=4212.5417
 m.video.state="playing":PlayerSeekTo(5000):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.position=0:m.video.state="playing":onVideoState()
 m.seekReanchor.playingClock={TotalMilliseconds:function()
 return 2600
 end function}
 m.video.position=3.3874584:onPlayerPosition()
 print FormatJson({done:m.seekReanchor=invalid,trusted:m.playLastPositionMs})''')
  self.assertTrue(v['done'],v)
  self.assertAlmostEqual(7600,v['trusted'],places=1)

 def test_zero_local_start_excludes_buffering_and_preserves_pause_intent(self):
  v=self.scene('''acceptedPlan["startPositionMs"]=0:acceptedPlan["timelineOffsetMs"]=5000
 PlayerSeekTo(5000):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.position=0:m.video.state="playing":onVideoState():onPlayerPosition()
 zeroPending=m.seekReanchor<>invalid
 m.seekReanchor.playingClock={TotalMilliseconds:function()
 return 500
 end function}
 m.video.state="buffering":onVideoState()
 m.seekReanchor.bindingClock={TotalMilliseconds:function()
 return 80000
 end function}:onSeekReanchorTimer()
 m.video.state="playing":onVideoState()
 m.seekReanchor.playingClock={TotalMilliseconds:function()
 return 1500
 end function}
 m.video.position=2:onPlayerPosition()
 beforePause={pending:m.seekReanchor<>invalid,control:m.video.control,trusted:m.playLastPositionMs}
 m.video.state="paused":onVideoState()
 print FormatJson({zeroPending:zeroPending,beforePause:beforePause,done:m.seekReanchor=invalid,trusted:m.playLastPositionMs,muted:m.video.mute})''')
  self.assertEqual(dict(zeroPending=True,beforePause=dict(pending=True,control='pause',trusted=37500),done=True,trusted=7000,muted=False),v)

 def test_response_and_native_position_do_not_stack_landing_tolerances(self):
  v=self.scene('''acceptedPlan["timelineOffsetMs"]=124900
 PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.position=0:m.video.state="playing":onVideoState()
 m.video.position=2.275:onPlayerPosition()
 overshoot={phase:m.seekReanchor.phase,trusted:m.playLastPositionMs}
 m.video.position=0.475:onPlayerPosition()
 m.video.state="paused":onVideoState()
 print FormatJson({overshoot:overshoot,done:m.seekReanchor=invalid,trusted:m.playLastPositionMs})''')
  self.assertEqual(dict(overshoot=dict(phase='binding',trusted=37500),done=True),{k:v[k] for k in ('overshoot','done')})
  self.assertAlmostEqual(125375,v['trusted'],places=1)

 def test_observed_native_overshoot_stays_unqualified_until_binding_timeout(self):
  v=self.scene('''acceptedPlan["startPositionMs"]=787.4584:acceptedPlan["timelineOffsetMs"]=4212.5417
 m.video.state="playing":PlayerSeekTo(5000):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.position=0:m.video.state="playing":onVideoState()
 m.seekReanchor.playingClock={TotalMilliseconds:function()
 return 2600
 end function}
 m.video.position=6.567:onPlayerPosition()
 rejected={pending:m.seekReanchor<>invalid,trusted:m.playLastPositionMs}
 m.seekReanchor.bindingClock={TotalMilliseconds:function()
 return 120000
 end function}:onSeekReanchorTimer()
 print FormatJson({rejected:rejected,view:m.view,position:m.calls[1].params.positionMs})''')
  self.assertEqual(dict(rejected=dict(pending=True,trusted=37500),view='home',position=37500),v)

 def test_first_position_cannot_credit_unknown_time_since_binding(self):
  v=self.scene('''acceptedPlan["startPositionMs"]=787.4584:acceptedPlan["timelineOffsetMs"]=4212.5417
 m.video.state="playing":PlayerSeekTo(5000):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.seekReanchor.bindingClock={TotalMilliseconds:function()
 return 2600
 end function}
 m.video.state="playing":m.video.position=3.3874584:onPlayerPosition()
 print FormatJson({pending:m.seekReanchor<>invalid,trusted:m.playLastPositionMs})''')
  self.assertEqual(dict(pending=True,trusted=37500),v)

 def test_back_before_landing_stops_at_trusted_source_position(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 m.video.position=0:m.video.state="playing":onVideoState():PlayerKey("back")
 print FormatJson({view:m.view,position:m.calls[1].params.positionMs,pending:m.seekReanchor=invalid})''')
  self.assertEqual(dict(view='home',position=37500,pending=True),v)
 def test_source_transition_waits_for_mutation_then_cleanup_ack(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 PlayerClose(false):SiloUIBeginTransition({action:"source_switch"})
 before={generation:m.generation,pending:m.pending.Count(),cancelled:m.pending["1"].task.cancelled}
 event={payload:{requestId:1,ok:false,leaseUncertain:true,knownLease:acceptedPlan.siloPlayback},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 after={generation:m.generation,pending:m.pending.Count(),tickets:m.cleanupTickets.Count()}
 event.payload={requestId:2,ok:true}:onApiResult(event)
 print FormatJson({before:before,after:after,generation:m.generation,source:m.sourceId,tickets:m.cleanupTickets.Count()})''')
  self.assertEqual(dict(before=dict(generation=7,pending=2,cancelled=True),after=dict(generation=7,pending=1,tickets=1),generation=8,source='silo:next',tickets=0),v)
 def test_pending_close_blocks_new_play_until_result_and_replayed_cleanup(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState():PlayerClose(false)
 blocked=SiloUIPlaybackAdmissionBlocked()
 print FormatJson({blocked:blocked,cancelled:m.pending["1"].task.cancelled})''')
  self.assertEqual(dict(blocked=True,cancelled=True),v)
 def test_pending_seek_cannot_start_generic_recovery(self):
  v=self.scene('''PlayerSeekTo(125375)
 recovered=PlayerRecoverNativeFailure("decoder_failure")
 print FormatJson({recovered:recovered,calls:m.calls.Count(),phase:m.seekReanchor.phase})''')
  self.assertEqual(dict(recovered=False,calls=0,phase='stopping'),v)
 def test_failed_seek_final_stop_is_owned_trusted_and_exactly_replayed(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState():PlayerKey("back")
 count=m.calls.Count():params=invalid
 if count>1 then params=m.calls[1].params
 print FormatJson({count:count,params:params,tickets:m.cleanupTickets<>invalid,blocked:SiloUIPlaybackAdmissionBlocked()})''')
  self.assertEqual(2,v['count'])
  self.assertTrue(v['blocked']);self.assertTrue(v['tickets'])
  self.assertEqual(37500,v['params']['positionMs']);self.assertEqual(10,v['params']['sequence'])
  self.assertTrue(v['params']['persistProgress']);self.assertTrue(v['params']['stopId'])
 def test_fresh_binding_clock_ignores_old_control_deadline_and_never_resets_on_buffer(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 m.seekReanchor.clock={TotalMilliseconds:function()
 return 59000
 end function}
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.seekReanchor.clock={TotalMilliseconds:function()
 return 999999
 end function}
 m.seekReanchor.bindingClock={TotalMilliseconds:function()
 return 119999
 end function}
 m.video.state="buffering":onVideoState():onSeekReanchorTimer()
 alive=m.view="player"
 m.seekReanchor.bindingClock={TotalMilliseconds:function()
 return 120000
 end function}
 onVideoState():onSeekReanchorTimer()
 print FormatJson({alive:alive,view:m.view,position:m.calls[1].params.positionMs,pending:m.seekReanchor=invalid,timer:m.seekReanchorTimer.control})''')
  self.assertEqual(dict(alive=True,view='home',position=37500,pending=True,timer='stop'),v)
 def test_far_overshoot_is_not_landing_and_pause_ack_has_own_ten_seconds(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.position=90:m.video.state="playing":onVideoState()
 farPhase=m.seekReanchor.phase
 m.video.position=1.375:onPlayerPosition()
 m.seekReanchor.pauseClock={TotalMilliseconds:function()
 return 9999
 end function}:onSeekReanchorTimer()
 alive=m.view="player"
 m.seekReanchor.pauseClock={TotalMilliseconds:function()
 return 10000
 end function}:onSeekReanchorTimer()
 print FormatJson({farPhase:farPhase,alive:alive,view:m.view,position:m.calls[1].params.positionMs,muted:m.video.mute})''')
  self.assertEqual(dict(farPhase='binding',alive=True,view='home',position=37500,muted=False),v)
 def test_refused_marker_does_not_consume_undo_or_history(self):
  v=self.scene('''m.seekReanchorEnabled=false:m.transportOffsetMs=0:m.transportSkipped=[]
 TransportSkip(125375)
 print FormatJson({undo:m.skipUndoMs,ticks:m.skipUndoTicks,dismissed:m.playerCue.visible,history:m.transportSkipped,calls:m.calls.Count()})''',actual_transport=True)
  self.assertEqual(dict(undo=None,ticks=None,dismissed=False,history=[],calls=0),v)
 def test_pending_timer_cannot_expire_undo_before_ack(self):
  v=self.scene('''m.skipUndoMs=10000:m.skipUndoTicks=1:m.transportEnabled=true:m.transport={visible:false}
 PlayerSeekTo(125375):onTransportTimer()
 print FormatJson({undo:m.skipUndoMs,ticks:m.skipUndoTicks})''',actual_transport=True)
  self.assertEqual(dict(undo=10000,ticks=1),v)
 def test_control_receipt_loss_retries_identical_final_stop_and_blocks_transition(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState():PlayerKey("back")
 first=SpCopy(m.calls[1].params)
 event={payload:{requestId:1,ok:false,leaseUncertain:true},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 event.payload={requestId:2,ok:false}:onApiResult(event)
 blocked=SiloUIPlaybackAdmissionBlocked()
 SiloUIRetryCleanup():second=m.calls[2].params
 event.payload={requestId:3,ok:true}:onApiResult(event)
 print FormatJson({same:SiloSeekEqual(first,second),blocked:blocked,after:SiloUIPlaybackAdmissionBlocked(),calls:m.calls.Count(),sequence:second.sequence,position:second.positionMs})''')
  self.assertEqual(dict(same=True,blocked=True,after=False,calls=3,sequence=10,position=37500),v)
 def test_no_request_at_stop_deadline_or_after_current_context_changes(self):
  for mutation in ['m.seekReanchor.clock={TotalMilliseconds:function()\n return 5000\n end function}',
                   'm.playPlan.siloPlayback.selectedTracks.audio.index=1']:
   with self.subTest(mutation=mutation):
    v=self.scene('''PlayerSeekTo(125375)
 '''+mutation+'''
 m.video.state="stopped":onVideoState()
 action="":if m.calls.Count()>0 then action=m.calls[0].action
 print FormatJson({view:m.view,action:action,pending:m.seekReanchor=invalid})''')
    self.assertEqual(dict(view='home',action='playback_stop',pending=True),v)
 def test_pending_state_suppresses_auto_next_countdown(self):
  v=self.scene('''PlayerSeekTo(125375)
 m.upNextActive=true:m.upNextDismissed=false:m.upNextSeconds=20:m.video.state="playing"
 onUpNextTick()
 print FormatJson({seconds:m.upNextSeconds,calls:m.calls.Count()})''')
  self.assertEqual(dict(seconds=20,calls=0),v)
 def test_other_pause_restoration_cannot_start_second_mutation(self):
  v=self.scene('''m.audioRestorePause=true:m.playbackChoiceBusy=false:m.recoveringNative=false
 accepted=PlayerSeekTo(125375)
 print FormatJson({accepted:accepted,control:m.video.control,calls:m.calls.Count(),pending:m.seekReanchor<>invalid})''')
  self.assertEqual(dict(accepted=False,control=None,calls=0,pending=False),v)
 def test_late_result_and_timer_never_close_newer_same_lease_content(self):
  for callback in ['onApiResult(event)','onSeekReanchorTimer()']:
   with self.subTest(callback=callback):
    v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 m.playPlan["planId"]="new-plan":m.playPlan.siloPlayback["planId"]="new-plan"
 m.video.content={id:"new-content",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 '''+callback+'''
 print FormatJson({view:m.view,plan:SpField(m.playPlan,"planId"),calls:m.calls.Count(),content:SpField(m.video.content,"id"),retired:m.seekReanchor=invalid})''')
    self.assertEqual(dict(view='player',plan='new-plan',calls=1,content='new-content',retired=True),v)
 def test_negotiated_preview_and_chapters_can_reach_before_returned_origin(self):
  v=self.scene('''m.playPlan=acceptedPlan:m.playPlan.cleanupOwner={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,sessionRevision:0}
 m.video.position=6:m.transport={visible:false}:m.transportEnabled=true:m.transportOffsetMs=124000
 m.transportRepeats=0:m.transportIdle=0:m.transportPreviewMs=invalid
 m.transportTitle={}:m.transportTime={}:m.transportProgress={}:m.transportHint={}:m.transportActions={}
 pills=[]:for index=0 to 3
 pills.Push({label:{},bg:{}})
 end for
 m.pillGroups={transportActions:{index:0,pills:pills}}
 TransportKey("rewind")
 print FormatJson({preview:m.transportPreviewMs})''',actual_transport=True)
  self.assertEqual(dict(preview=120000),v)
 def test_native_paused_skip_waits_stopped_and_never_resumes_or_dismisses_pending(self):
  v=self.scene('''m.transportEnabled=false:m.introDismissed=false:m.upNextDismissed=false
 m.playMarkers=[{kind:"intro",startMs:0,endMs:125375}]
 m.video.playbackActionButtonSelected=1:m.playerCue.visible=true
 onPlayerNativeAction()
 before={control:m.video.control,dismissed:m.introDismissed,cue:m.playerCue.visible,calls:m.calls.Count()}
 onPlayerNativeAction()
 m.video.state="stopped":onVideoState()
 print FormatJson({before:before,calls:m.calls.Count(),target:m.calls[0].params.positionMs})''',actual_cue=True)
  self.assertEqual(dict(before=dict(control='stop',dismissed=False,cue=True,calls=0),calls=1,target=125375),v)
 def test_paused_binding_is_muted_before_native_http_agent_bind(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 m.video.SetHttpAgent=sub(agent as Object)
 m.bindMuted=m.mute
 end sub
 m.manualFocus={setFocus:sub(value as Boolean)
 if m.top.video.control="play" then m.top.video.playMuted=m.top.video.mute
 end sub}:m.manualFocus.top=m
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 print FormatJson({atBind:m.video.bindMuted,atPlayFocus:m.video.playMuted,after:m.video.mute,control:m.video.control})''')
  self.assertEqual(dict(atBind=True,atPlayFocus=True,after=True,control='play'),v)
 def test_noncustom_marker_ok_preserves_cue_until_owned_ack_or_refusal(self):
  for enabled in [True,False]:
   with self.subTest(enabled=enabled):
    v=self.scene('''m.seekReanchorEnabled=ENABLED:m.transportEnabled=false:m.introEndMs=125375:m.upNextActive=false
 m.playerCue.visible=true:PlayerKey("OK")
 print FormatJson({cue:m.playerCue.visible,pending:m.seekReanchor<>invalid})'''.replace('ENABLED','true' if enabled else 'false'))
    self.assertEqual(dict(cue=True,pending=enabled),v)
 def test_pin_auth_busy_unknown_and_foreign_receipt_close_only_captured_lease(self):
  for response in ['{requestId:1,ok:false,errorCode:"profile_pin_required"}',
                   '{requestId:1,ok:false,errorCode:"auth_required",leaseUncertain:true}',
                   '{requestId:1,ok:false,errorCode:"playback_busy"}',
                   '{requestId:1,ok:false,leaseUncertain:true}',
                   '{requestId:1,ok:true,plan:acceptedPlan}']:
   with self.subTest(response=response):
    v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 acceptedPlan["sessionId"]="foreign-session":acceptedPlan.siloPlayback["sessionId"]="foreign-session"
 event={payload:RESPONSE,getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 print FormatJson({view:m.view,count:m.calls.Count(),session:m.calls[1].params.sessionId,position:m.calls[1].params.positionMs,pending:m.seekReanchor=invalid})'''.replace('RESPONSE',response))
    self.assertEqual(dict(view='home',count=2,session='session-0001',position=37500,pending=True),v)
 def test_profile_generation_source_revision_and_request_fences_block_publication(self):
  for mutation in ['m.profileId="other"','m.sourceId="silo:other"','m.generation=8','m.playToken=5',
                   'm.playPlan.cleanupOwner["sessionRevision"]=1']:
   with self.subTest(mutation=mutation):
    v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 old=m.video.content
 '''+mutation+'''
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 print FormatJson({fresh:old.isSameNode(m.video.content),pending:m.seekReanchor=invalid})''')
    self.assertEqual(dict(fresh=True,pending=True),v)
 def test_transition_during_binding_closes_trusted_sample_before_advancing_scope(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 SiloUIBeginTransition({action:"source_switch"})
 before={generation:m.generation,pending:m.pending.Count(),position:invalid}
 if m.calls.Count()>1 then before.position=m.calls[1].params.positionMs
 print FormatJson(before)''')
  self.assertEqual(dict(generation=7,pending=1,position=37500),v)
 def test_pending_up_diagnostics_and_first_back_are_nonmutating(self):
  v=self.scene('''m.diagnostics={visible:false}:m.diagnosticsText={}:m.diagnosticsTimer={}
 PlayerSeekTo(125375)
 m.seekReanchor.clock={elapsed:1234,TotalMilliseconds:function()
 return m.elapsed
 end function}
 clock=m.seekReanchor.clock
 PlayerKey("up"):shown=m.diagnostics.visible
 PlayerKey("back")
 first={view:m.view,pending:m.seekReanchor<>invalid,visible:m.diagnostics.visible,calls:m.calls.Count(),control:m.video.control,elapsed:clock.TotalMilliseconds()}
 PlayerKey("back")
 print FormatJson({shown:shown,first:first,closed:m.view="home"})''',actual_diagnostics=True)
  self.assertEqual(dict(shown=True,first=dict(view='player',pending=True,visible=False,calls=0,control='stop',elapsed=1234),closed=True),v)
 def test_known_invalid_protocol_target_or_observed_position_never_stops_transport(self):
  for target,position in [(604800001,37.5),(125375,604801),(-1,37.5),('"125375"',37.5)]:
   with self.subTest(target=target,position=position):
    v=self.scene('''m.playItem["durationMs"]=720000000:m.video.position=POSITION
 accepted=PlayerSeekTo(TARGET)
 print FormatJson({accepted:accepted,control:m.video.control,calls:m.calls.Count()})'''.replace('POSITION',str(position)).replace('TARGET',str(target)))
    self.assertEqual(dict(accepted=False,control=None,calls=0),v)
 def test_binding_native_error_closes_without_generic_recovery(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.state="error":onVideoState()
 print FormatJson({view:m.view,calls:m.calls.Count(),target:PlayerPositionMs()})''')
  self.assertEqual('home',v['view']);self.assertEqual(2,v['calls'])
 def test_marker_history_and_undo_commit_only_after_landed_pause_ack(self):
  v=self.scene('''m.transportOffsetMs=0:m.transportSkipped=[]:m.playerCue.visible=true
 TransportSkip(125375,true)
 before={undo:m.skipUndoMs,history:m.transportSkipped.Count(),cue:m.playerCue.visible}
 m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.state="playing":m.video.position=1.375:onVideoState():onPlayerPosition()
 landing={undo:m.skipUndoMs,history:m.transportSkipped.Count()}
 m.video.state="paused":onVideoState()
 print FormatJson({before:before,landing:landing,undo:m.skipUndoMs,history:m.transportSkipped,cue:m.playerCue.visible,done:m.seekReanchor=invalid})''',actual_transport=True)
  self.assertEqual(dict(before=dict(undo=None,history=0,cue=True),landing=dict(undo=None,history=0),undo=37500,history=[125375],cue=False,done=True),v)
 def test_undo_remains_available_through_owned_bind_until_pause_ack(self):
  v=self.scene('''m.skipUndoMs=125375:m.skipUndoTicks=6:m.transportSkipped=[]
 m.transportEnabled=true:m.transport={visible:false}:m.transportTimer={}
 m.video.hasField=function(name as String) as Boolean
 return name="enableTrickPlay"
 end function
 TransportKey("back")
 before=m.skipUndoMs
 m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 afterBind=m.skipUndoMs
 m.video.state="playing":m.video.position=1.375:onVideoState():onPlayerPosition()
 m.video.state="paused":onVideoState()
 print FormatJson({before:before,afterBind:afterBind,undo:m.skipUndoMs,done:m.seekReanchor=invalid})''',actual_transport=True)
  self.assertEqual(dict(before=125375,afterBind=125375,undo=None,done=True),v)
 def test_paused_ack_at_wrong_native_position_cannot_commit_requested_target(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.state="playing":m.video.position=1.375:onVideoState():onPlayerPosition()
 phase=m.seekReanchor.phase
 m.video.position=80:m.video.state="paused":onVideoState()
 print FormatJson({phase:phase,pending:m.seekReanchor<>invalid,trusted:m.playLastPositionMs})''')
  self.assertEqual(dict(phase="pausing",pending=True,trusted=37500),v)
 def test_actual_chapter_inventory_and_selection_before_nonzero_origin(self):
  v=self.scene('''m.playPlan=acceptedPlan:m.playPlan["cleanupOwner"]={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,sessionRevision:0}
 m.video.position=6:m.transportOffsetMs=124000:m.playChapters=[{positionMs:20000,title:"Earlier"},{positionMs:140000,title:"Later"}]
 m.transport={visible:false}
 m.chapterList={setFocus:sub(value as Boolean)
 end sub}
 TransportShowChapters()
 count=m.chapterList.content.getChildCount()
 m.chapterList.itemSelected=0:onTransportChapter()
 before=m.calls.Count():m.video.state="stopped":onVideoState()
 print FormatJson({count:count,before:before,target:m.calls[0].params.positionMs,seek:m.video.seek,control:m.video.control})''',actual_transport=True)
  self.assertEqual(dict(count=2,before=0,target=20000,seek=None,control='stop'),v)
 def test_stale_track_callback_cannot_mutate_native_tracks_during_seek(self):
  v=self.scene('''PlayerSeekTo(125375)
 m.trackDialog={visible:true}:m.trackList={itemSelected:0}
 m.trackChoices=[{kind:"audio",trackId:"audio-2",language:"fra",name:"French"}]
 onPlayerTrackChoice()
 print FormatJson({track:m.video.audioTrack,pref:m.trackPref.audio,calls:m.calls.Count()})''')
  self.assertEqual(dict(track=None,pref=None,calls=0),v)
 def test_pending_native_mode_bind_keeps_peer_focus_and_consumes_play(self):
  v=self.scene('''m.focusEvents=[]:m.transportEnabled=false
 m.manualFocus={setFocus:sub(value as Boolean)
 m.top.focusEvents.Push("peer")
 end sub}:m.manualFocus.top=m
 m.video.setFocus=sub(value as Boolean)
 m.top.focusEvents.Push("video")
 end sub:m.video.top=m
 PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 PlayerKey("play")
 print FormatJson({events:m.focusEvents,control:m.video.control,calls:m.calls.Count()})''')
  self.assertNotIn('video',v['events']);self.assertEqual('play',v['control']);self.assertEqual(1,v['calls'])
 def test_missing_peer_refuses_reanchor_before_native_stop(self):
  v=self.scene('''m.manualFocus=invalid
 accepted=PlayerSeekTo(125375)
 print FormatJson({accepted:accepted,control:m.video.control,calls:m.calls.Count()})''')
  self.assertEqual(dict(accepted=False,control=None,calls=0),v)
 def test_actual_source_progress_and_normal_stop_resume_after_ack_with_monotonic_sequence(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 m.video.position=0:m.video.state="playing":onVideoState():onProgressTimer()
 before=m.calls.Count()
 m.video.position=1.375:onPlayerPosition():m.video.state="paused":onVideoState()
 m.video.position=2.375:onProgressTimer():PlayerClose(false)
 print FormatJson({before:before,progress:m.calls[1].params,stop:m.calls[2].params,progressAction:m.calls[1].action,stopAction:m.calls[2].action})''',actual_report=True)
  self.assertEqual(1,v['before']);self.assertEqual('playback_progress',v['progressAction']);self.assertEqual('playback_stop',v['stopAction'])
  self.assertEqual((126375,10),(v['progress']['positionMs'],v['progress']['sequence']))
  self.assertEqual((126375,11),(v['stop']['positionMs'],v['stop']['sequence']))
 def test_auth_expiry_retains_exact_seek_stop_and_blocks_new_play(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState():PlayerKey("back")
 first=SpCopy(m.calls[1].params)
 event={payload:{requestId:1,ok:false,leaseUncertain:true},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 event.payload={requestId:2,ok:false,errorCode:"auth_required"}:onApiResult(event)
 blocked=SiloUIPlaybackAdmissionBlocked():retained=m.cleanupTickets.Count()
 beforePlay=m.calls.Count():PlayItem(m.playItem,0):playBlocked=m.calls.Count()=beforePlay
 SiloUIRetryCleanup()
 replay=invalid:if m.calls.Count()>2 then replay=m.calls[2].params
 event.payload={requestId:3,ok:true}:onApiResult(event)
 print FormatJson({blocked:blocked,retained:retained,same:SiloSeekEqual(first,replay),playBlocked:playBlocked,after:SiloUIPlaybackAdmissionBlocked()})''',actual_scope=True)
  self.assertEqual(dict(blocked=True,retained=1,same=True,playBlocked=True,after=False),v)
 def test_missing_content_has_no_active_same_lease_owner_and_drains_captured_lease(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 m.video.content=invalid
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 session="":if m.calls.Count()>1 then session=m.calls[1].params.sessionId
 print FormatJson({calls:m.calls.Count(),session:session,pending:m.seekReanchor=invalid,view:m.view})''')
  self.assertEqual(dict(calls=2,session='session-0001',pending=True,view='home'),v)
 def test_auth_expiry_during_binding_captures_final_ticket_before_epoch_retirement(self):
  v=self.scene('''PlayerSeekTo(125375):m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 Api("home",{},"home",-1)
 event.payload={requestId:2,ok:false,errorCode:"auth_required"}:onApiResult(event)
 print FormatJson({blocked:SiloUIPlaybackAdmissionBlocked(),tickets:m.cleanupTickets.Count(),position:m.calls[2].params.positionMs,generation:m.generation,pending:m.seekReanchor=invalid})''',actual_scope=True)
  self.assertEqual(dict(blocked=True,tickets=1,position=37500,generation=8,pending=True),v)
 def test_actual_onboarding_view_transition_waits_for_captured_seek_stop_ack(self):
  for binding in (False,True):
   with self.subTest(binding=binding):
    v=self.scene('''PlayerSeekTo(125375)
 BIND
 SiloUIBeginTransition({action:"source_switch"})
 position=invalid:action=""
 if m.calls.Count()>0 then position=m.calls[m.calls.Count()-1].params.positionMs:action=m.calls[m.calls.Count()-1].action
 before={generation:m.generation,view:m.view,pending:m.pending.Count(),position:position,action:action,retired:m.seekReanchor=invalid}
 event={payload:{requestId:m.requestId,ok:true},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)
 tickets=0:if m.cleanupTickets<>invalid then tickets=m.cleanupTickets.Count()
 print FormatJson({before:before,generation:m.generation,tickets:tickets,view:m.view})'''.replace('BIND','''m.video.state="stopped":onVideoState()
 event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}:onApiResult(event)''' if binding else ''),actual_onboarding_ui=True)
    self.assertEqual(dict(before=dict(generation=7,view='onboarding',pending=1,position=37500,action='playback_stop',retired=True),generation=8,tickets=0,view='onboarding'),v)
