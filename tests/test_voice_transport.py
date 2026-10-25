"""Transport ingress and active playback controller boundaries."""
import json
import re
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class VoiceTransportTests(unittest.TestCase):
 def flow(self, body, actual_player=False):
  with tempfile.TemporaryDirectory() as d:
   stub=Path(d)/'boundary.brs'
   stub.write_text('''function SiloUIOwner() as Object
 return {provider:"silo",sourceId:"source",profileId:"profile",generation:1,sessionRevision:0}
end function
function DetailPhotoSessionRevision() as Integer
 return 0
end function
function HomeProgressScope() as String
 return "scope"
end function
sub PlayerClose(finished)
 m.closed=true:m.playPlan=invalid
end sub
function PlayerPositionMs() as Integer
 return 60000
end function
function PlayerSeekTo(target) as Boolean
 m.target=target:return true
end function
''')
   files=[]
   if actual_player:
    text=stub.read_text()
    text=re.sub(r'sub PlayerClose\(.*?\nend sub\n', '', text, flags=re.S)
    text=re.sub(r'function PlayerPositionMs\(.*?\nend function\n', '', text, flags=re.S)
    text=re.sub(r'function PlayerSeekTo\(.*?\nend function\n', '', text, flags=re.S)
    stub.write_text(text)
    files=[ROOT/'components/SiloUIPlayer.brs',ROOT/'source/core/SiloPlaybackPolicy.brs']
   main=Path(d)/'main.brs'
   main.write_text(re.sub(r'sub Main\(.*?\nend sub', '', (ROOT/'source/main.brs').read_text(), count=1, flags=re.S))
   out=run_brightscript([main,ROOT/'components/SiloUIVoice.brs',ROOT/'components/SiloUIAudio.brs',ROOT/'source/core/SiloUIAudioPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',stub]+files,'''
m.top={appFocused:true}:m.view="player":m.playToken=1:m.nativePlaybackToken=1
m.nativePlaybackOwner=SiloUIOwner():m.playPlan={provider:"silo",sessionId:"session",canSeekAnywhere:true,timelineOffsetMs:0}
m.playPlan.cleanupOwner=SiloUIOwner()
m.video={state:"playing",control:"play",position:60,seek:-1}:m.playItem={durationMs:120000}
'''+body,root=Path(d))
   return json.loads(out)
 def test_transport_is_not_a_launch_and_preserves_id_once(self):
  r=self.flow('''input={responses:[],EventResponse:sub(value)
 m.responses.Push(value)
end sub}
scene={launchInput:{old:true},callFunc:function(name,info)
 return {status:"error.generic"}
end function}
MainInput(input,scene,{type:"transport",id:42,command:"next"})
MainInput(input,scene,{type:"transport",id:"0042",command:"pause"})
MainInput(input,scene,{contentId:"movie",mediaType:"movie"})
print FormatJson({responses:input.responses,launch:scene.launchInput})''')
  self.assertEqual([{'id':42,'status':'error.generic'},{'id':'0042','status':'error.generic'}],r['responses'])
  self.assertEqual('movie',r['launch']['contentId'])
 def test_explicit_pause_and_play_are_idempotent(self):
  r=self.flow('''a=handleTransport({command:"play"}):first=m.video.control
b=handleTransport({command:"pause"}):m.video.state="paused"
c=handleTransport({command:"pause"}):paused=m.video.control
d=handleTransport({command:"resume"})
print FormatJson({first:first,paused:paused,last:m.video.control,status:d.status})''')
  self.assertEqual(dict(first='play',paused='pause',last='resume',status='success'),r)
 def test_unowned_busy_and_malformed_commands_have_no_effect(self):
  for setup in ['m.top.appFocused=false','m.nativePlaybackToken=2','m.nativePlaybackOwner.profileId="other"','m.playLoading=true','m.seekReanchor={}','m.video.state="buffering"','m.audioPlan={}','m.playPlan.cleanupOwner.sessionRevision=1']:
   with self.subTest(setup=setup):
    r=self.flow(setup+'\nr=handleTransport({command:"pause"})\nprint FormatJson({status:r.status,control:m.video.control})')
    self.assertEqual(dict(status='error.generic',control='play'),r)
  for command in ['{}','{command:"next"}','{command:"seek",direction:"backward",duration:"3x"}','{command:"seek",direction:"sideways",duration:"30"}']:
   self.assertEqual('error.generic',self.flow('r=handleTransport('+command+')\nprint FormatJson(r)')['status'])
 def test_seek_bounds_and_async_routes(self):
  for command,target,status in [('{command:"seek",direction:"backward",duration:"90"}',0,'success.seek-start'),('{command:"forward"}',90000,'success'),('{command:"seek",direction:"forward",duration:"90"}',119000,'success.seek-end'),('{command:"startover"}',0,'success')]:
   r=self.flow('r=handleTransport('+command+')\nprint FormatJson({status:r.status,target:m.target})')
   self.assertEqual(dict(status=status,target=target),r)
  for setup in ['m.playPlan.transport="silo_compat"','m.playPlan.canSeekAnywhere=false','m.playPlan.timelineOffsetMs=70000']:
   r=self.flow(setup+'\nr=handleTransport({command:"startover"})\nprint FormatJson({status:r.status,target:m.target})')
   self.assertEqual(dict(status='error.generic',target=None),r)
 def test_stop_uses_existing_close(self):
  r=self.flow('r=handleTransport({command:"stop"})\nprint FormatJson({status:r.status,closed:m.closed,plan:m.playPlan})')
  self.assertEqual(dict(status='success',closed=True,plan=None),r)
 def test_audio_global_timeline_and_paused_seek_ownership(self):
  setup='''m.view="audio":m.playPlan=invalid:m.audioOwner=SiloUIOwner():m.audioScope="scope":m.audioToken=7
m.audioPlan={sessionId:"audio",cleanupOwner:SiloUIOwner()}:m.audioQueue=[{offsetMs:0,durationMs:120000},{offsetMs:120000,durationMs:120000}]
m.audioIndex=1:m.audioLocalMs=60000:m.audioNode={state:"paused",position:60,control:"pause"}
'''
  r=self.flow(setup+'''a=handleTransport({command:"rewind"})
m.audioNode.state="playing":m.audioNode.position=30:SiloUIAudioRestoreSeekPause()
paused=m.audioNode.control:b=handleTransport({command:"pause"}):held=SiloUIAudioPausedSeekCurrent()
c=handleTransport({command:"play"}):d=handleTransport({command:"startover"})
print FormatJson({seek:m.audioNode.seek,paused:paused,held:held,control:m.audioNode.control,start:d.status})''')
  self.assertEqual(dict(seek=30,paused='pause',held=True,control='resume',start='error.generic'),r)

 def test_real_seek_dispatch_uses_source_offset_and_refuses_reanchor(self):
  for setup,target in [('m.playPlan.timelineOffsetMs=30000',89),('m.playPlan.canSeekAnywhere=false:m.playPlan.seekWindowStartMs=0:m.playPlan.seekWindowEndMs=80000',-1)]:
   r=self.flow(setup+'\nr=handleTransport({command:"forward"})\nprint FormatJson({status:r.status,seek:m.video.seek})',actual_player=True)
   self.assertEqual(target,r['seek'])
