"""Stock seek through the existing compat runtime seam; SDK/device authority only stubbed."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class StockSeek(unittest.TestCase):
 def scene(self,body):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'compat.brs'
   text=(ROOT/'components/SiloUICompatPlayback.brs').read_text()
   for name in ['SiloUICompatCurrent','SiloUICompatDuration','SiloUICompatWatch']:
    text=text.replace(name+'(',name+'(') # retain calls, substitute only platform boundaries
    text=text.replace('function '+name+'(','function '+name+'Device(').replace('sub '+name+'(','sub '+name+'Device(')
   path.write_text(text)
   player=Path(td)/'player.brs'
   player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerBind(','sub PlayerBindDevice(').replace('sub PlayerStart(','sub PlayerStartDevice('))
   stub=Path(td)/'sdk.brs';stub.write_text('''
function SiloUICompatCurrent(state as Object) as Boolean
 return state.token=m.playToken
end function
function SiloUICompatDuration() as Double
 return 60000
end function
sub SiloUICompatWatch(state as Object)
end sub
sub Toast(message as String)
end sub
sub SiloUISubtitleDrainRetired()
end sub
sub PlayerBind(payload as Object,title as String)
 m.video.content=TestNode("replacement")
 m.video.content.playStart=payload.startPositionMs/1000#
end sub
sub PlayerStart(plan as Object,bound=false as Boolean)
 m.playPlan=plan
 m.video.control="play"
end sub
function TestEvent(node as Object,data=invalid as Dynamic) as Object
 return {node:node,data:data,getData:function() as Dynamic
 return m.data
 end function,getRoSGNode:function() as Object
 return m.node
 end function}
end function
function TestNode(id as String) as Object
 return {id:id,observeField:sub(field as String,callback as String)
 end sub,isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}
end function
''')
   out=run_brightscript([ROOT/'source/core/SiloNativeBearerTransport.brs',ROOT/'source/core/SiloPlaybackPolicy.brs',ROOT/'source/core/SiloOriginalPlaybackPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/adapters/SiloAdapter.brs',path,player,stub],'''
m.playItem={title:"Film"}:m.playToken=9:m.transitionIntent=invalid:m.video=TestNode("video"):m.video.state="playing":m.video.position=20:m.video.content=TestNode("old")
state={phase:"playing",activeConfirmed:true,engine:TestNode("engine"),content:m.video.content,token:9,holderId:"h",attemptId:"a",planGeneration:1,task:{cancelled:false},owner:{provider:"silo",sourceId:"silo:s",profileId:"p",generation:1,sessionRevision:1}}
m.compatPreparation=state
'''+body,root=Path(td))
   return json.loads(next(x[7:] for x in out.splitlines() if x.startswith('RESULT:')))
 def test_bookmark_prepares_target_before_first_native_bind(self):
  self.assertEqual(dict(before=None,request=17875000,accepted='accept',after='replacement',offset=2,phase='playing',stage='loading',title=17875),self.scene('''
state.phase="stock_starting":state.content=invalid:m.video.content=invalid
state.intent={startPositionMs:17875,itemId:"i",fileId:"f"}:state.stockDurationMs=60000
SiloUICompatStockResumeBegin(state):before=m.video.content
p={requestId:1,generationId:2,requestedTitleUs:17875000&,titleOriginUs:15875000&,offsetUs:2000000&,sourceStartIndex:4,revision:1,binding:"asset"}
o={status:"offered",requestId:1,generationId:2,previousGenerationId:1,plan:p,localMasterUrl:"http://127.0.0.1:34831/g2/master.m3u8"}
SiloUICompatStockSeekOffer(state,o):accepted=state.engine.seekAck.action
o.status="active":SiloUICompatStockSeekOffer(state,o)
print "RESULT:";FormatJson({before:before,request:state.engine.seekRequest.targetTitleUs,accepted:accepted,after:m.video.content.id,offset:m.video.content.playStart,phase:state.phase,stage:state.stockSeek.stage,title:PlayerPositionMs()})
'''))
 def test_initial_resume_pressure_retires_without_a_native_decoder(self):
  self.assertEqual(dict(ack='quiesced',control=None,content=None,accepted='accept',stage='loading'),self.scene('''
state.phase="stock_starting":state.content=invalid:m.video.content=invalid
state.intent={startPositionMs:17875,itemId:"i",fileId:"f"}:state.stockDurationMs=60000
SiloUICompatStockResumeBegin(state)
p={requestId:1,generationId:2,requestedTitleUs:17875000&,titleOriginUs:15875000&,offsetUs:2000000&,sourceStartIndex:4,revision:1,binding:"asset"}
o={status:"quiesce",requestId:1,generationId:2,previousGenerationId:1,plan:p,localMasterUrl:"http://127.0.0.1:34831/g2/master.m3u8"}
SiloUICompatStockSeekOffer(state,o):ack=state.engine.seekAck.action:control=m.video.control:content=m.video.content
o.status="offered":o.previousRetired=true:SiloUICompatStockSeekOffer(state,o):accepted=state.engine.seekAck.action
o.status="active":SiloUICompatStockSeekOffer(state,o)
print "RESULT:";FormatJson({ack:ack,control:control,content:content,accepted:accepted,stage:state.stockSeek.stage})
'''))
 def test_initial_resume_cancel_error_and_timeout_drain_engine_without_native_bind(self):
  for action,failed in [('SiloUICompatCancel()',None),('state.engine.failed=true:onSiloUICompatStockEngine(TestEvent(state.engine))',True),('SiloUICompatStockSeekOffer(state,{requestId:1,status:"failed",generationId:0})',True),('onSiloUICompatTick()',True)]:
   with self.subTest(action=action):
    self.assertEqual(dict(phase='stock_stopping',stop=True,content=None,failed=failed),self.scene('''
state.phase="stock_starting":state.content=invalid:m.video.content=invalid
state.intent={startPositionMs:17875}:SiloUICompatStockResumeBegin(state)
state.engineClock={TotalMilliseconds:function()
 return 120000
end function}
ACTION
print "RESULT:";FormatJson({phase:state.phase,stop:state.engine.stopRequested,content:m.video.content,failed:state.failurePending})
'''.replace('ACTION',action)))
 def test_initial_resume_qualifies_actual_clock_then_reports_mapped_title_and_releases(self):
  self.assertEqual(dict(playing=True,reported=16125,title=16375,action='release_previous',sequence=2,stage='running'),self.scene('''
state.phase="stock_starting":state.content=invalid:m.video.content=invalid
state.intent={startPositionMs:17875,itemId:"i",fileId:"f"}:state.stockDurationMs=60000
SiloUICompatStockResumeBegin(state)
p={requestId:1,generationId:2,requestedTitleUs:17875000&,titleOriginUs:15875000&,offsetUs:2000000&,sourceStartIndex:4,revision:1,binding:"asset"}
o={status:"offered",requestId:1,generationId:2,previousGenerationId:1,plan:p,localMasterUrl:"http://127.0.0.1:34831/g2/master.m3u8"}
SiloUICompatStockSeekOffer(state,o):o.status="active":SiloUICompatStockSeekOffer(state,o)
m.video.state="playing":onVideoState()
onSiloUICompatStockSeekBuffer(TestEvent(m.video,{actualStart:0}))
m.video.positionInfo={epoch:0}:m.video.position=0.125:SiloUICompatStockSeekPosition()
m.video.position=0.25:SiloUICompatStockSeekPosition():reported=state.task.command.positionMs
m.video.position=0.5:SiloUICompatStockSeekPosition()
print "RESULT:";FormatJson({playing:state.playingSent,reported:reported,title:PlayerPositionMs(),action:state.engine.seekAck.action,sequence:state.engine.playbackUpdate.sequence,stage:state.stockSeek.stage})
'''))
 def test_initial_resume_rejects_stale_ownership_without_binding_any_content(self):
  for change in ['m.playToken++','state.owner.sessionRevision++','state.engine=TestNode("other")','m.video.content=TestNode("other")','state.intent.startPositionMs++','state.intent.fileId="other"','state.intent.audioTrackIndex=2','m.transitionIntent={}']:
   with self.subTest(change=change):
    self.assertEqual(dict(ack=None,control=None),self.scene('''
state.phase="stock_starting":state.content=invalid:m.video.content=invalid
state.intent={startPositionMs:17875}:SiloUICompatStockResumeBegin(state)
CHANGE
p={requestId:1,generationId:2,requestedTitleUs:17875000&,titleOriginUs:15875000&,offsetUs:2000000&,sourceStartIndex:4,revision:1,binding:"asset"}
SiloUICompatStockSeekOffer(state,{status:"offered",requestId:1,generationId:2,previousGenerationId:1,plan:p,localMasterUrl:"http://127.0.0.1:34831/g2/master.m3u8"})
print "RESULT:";FormatJson({ack:state.engine.seekAck,control:m.video.control})
'''.replace('CHANGE',change)))
 def test_initial_resume_ignores_native_state_until_it_owns_a_decoder(self):
  self.assertEqual(dict(phase='stock_resuming',failed=None,stage='waiting_offer'),self.scene('''
state.phase="stock_starting":state.content=invalid:m.video.content=invalid
state.intent={startPositionMs:17875}:SiloUICompatStockResumeBegin(state)
m.video.state="error":onVideoState()
print "RESULT:";FormatJson({phase:state.phase,failed:state.failurePending,stage:state.stockSeek.stage})
'''))
 def test_initial_resume_requires_exact_bookmark_in_holder_qualification(self):
  self.assertEqual(dict(accepted=17875,mismatch=None,malformed=None),self.scene('''
state.eligibilityKind="experimental_query_p7_hdr10_fmp4_v1":state.intent={startPositionMs:17875,fileId:"f",audioTrackIndex:1}
q={schemaVersion:1,kind:"stock-p7-ac3-root-v1",approved:true,sourceId:"silo:s",profileId:"p",generation:1,sessionRevision:1,holderId:"h",attemptId:"a",planGeneration:1,origin:"https://fixture.invalid",transportPolicy:"controlled-fixture-v1",transportEvidence:"private-controlled-fixture",rootListenerRequired:true,fileId:"f",mediaSourceId:"media",audioOrdinal:1,audioStreamIndex:2,requestedStartPositionMs:17875}
a=SiloUICompatStockQualification(state,{stockQualification:q}):q.requestedStartPositionMs=17000
b=SiloUICompatStockQualification(state,{stockQualification:q}):q.requestedStartPositionMs=true
c=SiloUICompatStockQualification(state,{stockQualification:q})
print "RESULT:";FormatJson({accepted:a.requestedStartPositionMs,mismatch:b,malformed:c})
'''))
 def test_ordinary_seek_allocates_owned_engine_request_without_stopping_old_video(self):
  self.assertEqual(dict(accepted=True,request=dict(requestId=1,targetTitleUs=17875000),control=None,generation=1),self.scene('''
a=SiloUICompatSeek(17875)
print "RESULT:";FormatJson({accepted:a,request:state.engine.seekRequest,control:m.video.control,generation:state.planGeneration})
'''))
 def test_offer_and_active_must_match_before_decoder_stop(self):
  self.assertEqual(dict(stale=None,accepted='accept',before=None,after='stop',stage='stopping'),self.scene('''
a=SiloUICompatSeek(17875)
p={requestId:1,generationId:2,requestedTitleUs:17875000&,titleOriginUs:15875000&,offsetUs:2000000&,sourceStartIndex:4,revision:1,binding:"asset"}
o={status:"offered",requestId:2,generationId:2,previousGenerationId:1,plan:p,localMasterUrl:"http://127.0.0.1:34831/g2/master.m3u8"}
SiloUICompatStockSeekOffer(state,o):stale=state.engine.seekAck
o.requestId=1:SiloUICompatStockSeekOffer(state,o):accepted=state.engine.seekAck.action
before=m.video.control:o.status="active":SiloUICompatStockSeekOffer(state,o)
print "RESULT:";FormatJson({stale:stale,accepted:accepted,before:before,after:m.video.control,stage:state.stockSeek.stage})
'''))

 def test_replacement_waits_for_observed_stop_then_uses_local_offset(self):
  self.assertEqual(dict(before="old",after="replacement",offset=2,stage="loading",release=None),self.scene('''
a=SiloUICompatSeek(17875)
s=state.stockSeek:s.stage="stopping":s.generationId=2:s.url="http://127.0.0.1:34831/g2/master.m3u8":s.plan={offsetUs:2000000&,titleOriginUs:15875000&}
onVideoState():before=m.video.content.id
m.video.state="stopped":onVideoState()
print "RESULT:";FormatJson({before:before,after:m.video.content.id,offset:m.video.content.playStart,stage:s.stage,release:state.engine.seekAck})
'''))
 def test_only_post_playing_zero_epoch_advancing_clock_maps_actual_fragment_landing(self):
  self.assertEqual(dict(before=20000,first=20000,position=16125,bind='bind_clock',update=250000,release='release_previous',paused='pause'),self.scene('''
a=SiloUICompatSeek(17875):s=state.stockSeek
s.stage="qualifying":s.actualStart=0:s.generationId=2:s.epoch=1:s.retired=true:s.paused=true:s.plan={titleOriginUs:15875000&,offsetUs:2000000&}
m.video.positionInfo={epoch:0}:m.video.bufferingStatus={actualStart:0}:m.video.position=20
SiloUICompatStockSeekPosition():before=s.positionMs
m.video.position=0.125:SiloUICompatStockSeekPosition():first=s.positionMs
m.video.position=0.25:SiloUICompatStockSeekPosition():bind=state.engine.seekAck.action
SiloUICompatStockSeekPosition()
print "RESULT:";FormatJson({before:before,first:first,position:s.positionMs,bind:bind,update:state.engine.playbackUpdate.nativeUs,release:state.engine.seekAck.action,paused:m.video.control})
'''))
 def test_unqualified_or_reordered_samples_cannot_advance_title_progress(self):
  for epoch,start in [(1,0),(0,2),(0,None)]:
   with self.subTest(epoch=epoch,start=start):
    self.assertEqual(dict(position=20000,update=None,stage='qualifying'),self.scene('''
a=SiloUICompatSeek(17875):s=state.stockSeek:s.stage="qualifying":s.generationId=2:s.epoch=1:s.retired=true:s.plan={titleOriginUs:15875000&}
s.actualStart=START:m.video.positionInfo={epoch:EPOCH}:m.video.position=0.125
SiloUICompatStockSeekPosition():m.video.position=0.25:SiloUICompatStockSeekPosition()
print "RESULT:";FormatJson({position:s.positionMs,update:state.engine.playbackUpdate,stage:s.stage})
'''.replace('EPOCH',str(epoch)).replace('START','invalid' if start is None else str(start))))
 def test_owner_engine_content_and_token_drift_cannot_accept_an_offer(self):
  for change in ['m.playToken++','state.owner.sessionRevision++','state.engine=TestNode("other")','m.video.content=TestNode("other")','m.transitionIntent={}']:
   with self.subTest(change=change):
    self.assertEqual(dict(ack=None,control=None),self.scene('''
a=SiloUICompatSeek(17875)
CHANGE
p={requestId:1,generationId:2,requestedTitleUs:17875000&,titleOriginUs:15875000&,offsetUs:2000000&,sourceStartIndex:4,revision:1,binding:"asset"}
SiloUICompatStockSeekOffer(state,{status:"offered",requestId:1,generationId:2,previousGenerationId:1,plan:p,localMasterUrl:"http://127.0.0.1:34831/g2/master.m3u8"})
print "RESULT:";FormatJson({ack:state.engine.seekAck,control:m.video.control})
'''.replace('CHANGE',change)))
 def test_cancel_during_preparation_or_replacement_stops_without_releasing_previous(self):
  for stage in ['waiting_offer','await_active','stopping','quiescing','quiesced','loading']:
   with self.subTest(stage=stage):
    self.assertEqual(dict(phase='local_stopping',control='stop',seek=None,release=False),self.scene('''
a=SiloUICompatSeek(17875):state.stockSeek.stage="STAGE":state.stockSeek.generationId=2
SiloUICompatCancel()
print "RESULT:";FormatJson({phase:state.phase,control:m.video.control,seek:state.stockSeek,release:state.engine.seekAck.action="release_previous"})
'''.replace('STAGE',stage)))
 def test_repeat_seek_uses_engine_generation_two_and_keeps_holder_generation_one(self):
  self.assertEqual(dict(accepted=True,request=2,previous=2,holder=1),self.scene('''
a=SiloUICompatSeek(17875):s=state.stockSeek:s.stage="running":s.released=true:state.stockGeneration=2:state.stockPositionMs=16125
b=SiloUICompatSeek(2000)
print "RESULT:";FormatJson({accepted:b,request:state.engine.seekRequest.requestId,previous:state.stockSeek.previousGenerationId,holder:state.planGeneration})
'''))
 def test_stop_timeout_fails_closed_without_content_rebinding_or_release(self):
  self.assertEqual(dict(phase='local_stopping',content='old',release=None,control='stop'),self.scene('''
a=SiloUICompatSeek(17875):s=state.stockSeek:s.stage="stopping"
s.clock={TotalMilliseconds:function()
 return 5000
end function}
onSiloUICompatTick()
print "RESULT:";FormatJson({phase:state.phase,content:m.video.content.id,release:state.engine.seekAck,control:m.video.control})
'''))
 def test_native_error_during_replacement_fails_immediately(self):
  for stage in ['loading','qualifying']:
   with self.subTest(stage=stage):
    self.assertEqual(dict(phase='local_stopping',failed=True),self.scene('''
a=SiloUICompatSeek(17875):state.stockSeek.stage="STAGE":m.video.state="error"
onVideoState()
print "RESULT:";FormatJson({phase:state.phase,failed:state.failurePending})
'''.replace('STAGE',stage)))
 def test_engine_failure_and_real_short_failure_offer_fail_immediately(self):
  for failure in ['state.engine.failed=true:onSiloUICompatStockEngine(TestEvent(state.engine))','SiloUICompatStockSeekOffer(state,{requestId:1,generationId:0,status:"failed",plan:invalid})']:
   with self.subTest(failure=failure):
    self.assertEqual(dict(phase='local_stopping',failed=True),self.scene('''
a=SiloUICompatSeek(17875)
FAILURE
print "RESULT:";FormatJson({phase:state.phase,failed:state.failurePending})
'''.replace('FAILURE',failure)))
 def test_pressure_quiesces_once_only_after_observed_stop_and_binds_after_activation(self):
  self.assertEqual(dict(before=None,content='old',ack='quiesced',previous=1,waiting='quiesced',duplicate=None,accepted='accept',after='replacement',stage='loading',paused=True),self.scene('''
m.video.state="paused":a=SiloUICompatSeek(17875)
p={requestId:1,generationId:2,requestedTitleUs:17875000&,titleOriginUs:15875000&,offsetUs:2000000&,sourceStartIndex:4,revision:1,binding:"asset"}
o={status:"quiesce",requestId:1,generationId:2,previousGenerationId:1,plan:p,localMasterUrl:"http://127.0.0.1:34831/g2/master.m3u8"}
SiloUICompatStockSeekOffer(state,o):before=state.engine.seekAck
onVideoState():content=m.video.content.id
m.video.state="stopped":onVideoState():ack=state.engine.seekAck.action:previous=state.engine.seekAck.previousGenerationId:waiting=state.stockSeek.stage
state.engine.seekAck=invalid:onVideoState():SiloUICompatStockSeekOffer(state,o):duplicate=state.engine.seekAck
o.status="offered":o.previousRetired=true:SiloUICompatStockSeekOffer(state,o):accepted=state.engine.seekAck.action
o.status="active":SiloUICompatStockSeekOffer(state,o)
print "RESULT:";FormatJson({before:before,content:content,ack:ack,previous:previous,waiting:waiting,duplicate:duplicate,accepted:accepted,after:m.video.content.id,stage:state.stockSeek.stage,paused:state.stockSeek.paused})
'''))
 def test_pressure_offer_rejects_wrong_identity_plan_url_and_active_retirement_claim(self):
  for change in ['o.requestId=2','o.previousGenerationId=0','o.plan.offsetUs=1','o.localMasterUrl="http://localhost/master.m3u8"','o.status="offered":o.previousRetired=true']:
   with self.subTest(change=change):
    self.assertEqual(dict(ack=None,control=None,stage='waiting_offer'),self.scene('''
a=SiloUICompatSeek(17875)
p={requestId:1,generationId:2,requestedTitleUs:17875000&,titleOriginUs:15875000&,offsetUs:2000000&,sourceStartIndex:4,revision:1,binding:"asset"}
o={status:"quiesce",requestId:1,generationId:2,previousGenerationId:1,plan:p,localMasterUrl:"http://127.0.0.1:34831/g2/master.m3u8"}
CHANGE
SiloUICompatStockSeekOffer(state,o)
print "RESULT:";FormatJson({ack:state.engine.seekAck,control:m.video.control,stage:state.stockSeek.stage})
'''.replace('CHANGE',change)))

 def test_pressure_wait_timeout_fails_closed_and_never_rebinds_old_content(self):
  for stage,timeout in [('quiescing',5000),('quiesced',120000)]:
   with self.subTest(stage=stage):
    self.assertEqual(dict(phase='local_stopping',content='old',control='stop'),self.scene('''
a=SiloUICompatSeek(17875):s=state.stockSeek:s.stage="STAGE":s.generationId=2
s.clock={TotalMilliseconds:function()
 return TIMEOUT
end function}
onSiloUICompatTick()
print "RESULT:";FormatJson({phase:state.phase,content:m.video.content.id,control:m.video.control})
'''.replace('STAGE',stage).replace('TIMEOUT',str(timeout))))
 def test_replacement_uses_seek_deadline_instead_of_expired_initial_landing_clock(self):
  self.assertEqual(dict(phase='playing',stage='loading',failed=None),self.scene('''
a=SiloUICompatSeek(17875):s=state.stockSeek:s.stage="stopping":s.generationId=2:s.url="http://127.0.0.1:34831/g2/master.m3u8":s.plan={offsetUs:2000000&,titleOriginUs:15875000&}
state.playingSent=true:state.landed=true
state.landingClock={TotalMilliseconds:function()
 return 14000
end function}
m.video.state="stopped":onVideoState()
onSiloUICompatTick()
print "RESULT:";FormatJson({phase:state.phase,stage:s.stage,failed:state.failurePending})
'''))
 def test_initial_landing_and_seek_replacement_keep_their_bounded_deadlines(self):
  for setup in ['state.landingClock=expired','a=SiloUICompatSeek(17875):state.stockSeek.stage="loading":state.stockSeek.clock=expired']:
   with self.subTest(setup=setup):
    self.assertEqual(dict(phase='local_stopping',failed=True),self.scene('''
state.playingSent=true:state.landed=false:state.intent={startPositionMs:0}
expired={TotalMilliseconds:function()
 return 120000
end function}
SETUP
m.video.state="stopped":onSiloUICompatTick()
print "RESULT:";FormatJson({phase:state.phase,failed:state.failurePending})
'''.replace('SETUP',setup)))
