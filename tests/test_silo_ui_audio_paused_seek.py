"""Actual audio callbacks preserve the latest paused seek through native resume."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class PausedAudioSeekTests(unittest.TestCase):
 def flow(self,body):
  with tempfile.TemporaryDirectory() as d:
   stub=Path(d)/'boundary.brs';stub.write_text('''
function HomeProgressScope() as String
 return "owner"
end function
sub ApiOwned(action,params,purpose,extra,owner)
 if action="playback_progress" then m.lastAudioProgress=params
end sub
sub Toast(message)
end sub
function FixtureHttpAgent() as Object
 return {SetCertificatesFile:sub(path)
 end sub}
end function
function FixtureContent() as Object
 return {}
end function
''')
   audio=Path(d)/'audio.brs'
   audio.write_text((ROOT/'components/SiloUIAudio.brs').read_text().replace('CreateObject("roHttpAgent")','FixtureHttpAgent()').replace('CreateObject("roSGNode","ContentNode")','FixtureContent()'))
   out=run_brightscript([ROOT/'components/SiloUIRobustness.brs',audio,ROOT/'components/SiloUILibrary.brs',ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIAudioPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',stub],'''
    m.view="audio":m.audioScope="owner":m.audioToken=7:m.audioSleepMs=0
    m.audioQueue=[{offsetMs:0,durationMs:120000}]:m.audioIndex=0:m.audioLocalMs=36784
    m.audioBook={durationMs:120000}:m.audioPlan={startPositionMs:0}:m.audioStarted=true:m.audioDidSeek=true:m.audioTicks=0
    m.audioTimer={}:m.audioNode={state:"paused",position:36.784,control:"pause",setHttpAgent:sub(agent)
    end sub}
    m.top={label:{},findNode:function(id)
     return m.label
    end function}
   '''+body,root=Path(d))
  return json.loads(out)
 def test_native_playing_and_tick_restore_pause_only_at_latest_seek(self):
  r=self.flow('''
    m.provider="silo":m.sourceId="silo:a":m.profileId="p":m.generation=1
    m.audioOptionsToken=7:m.audioOptionChapters=[{start_seconds:30}]
    node={id:1,buttonSelected:8,isSameNode:function(other)
     return m.id=other.id
    end function}
    m.top.dialog=node:m.browseDialog=node
    m.browsePaged={handler:"onSiloUIAudioOption",previous:-1,nextPage:-1,count:9,start:0}
    BrowseBindDialog(node,"onSiloUIAudioOption")
    event={node:node,getRoSGNode:function()
     return m.node
    end function}
    onSiloUIAudioOption(event)
    m.audioNode.state="playing":m.audioNode.control="play"
    onSiloUIAudioState()
    before=m.audioNode.control
    m.audioNode.position=30:onSiloUIAudioState()
    chapterPaused=m.audioNode.control
    SiloUIAudioSeek(60000)
    m.audioNode.control="play"
    m.audioNode.position=30:onSiloUIAudioTick()
    stale=m.audioNode.control
    m.audioNode.position=60:onSiloUIAudioTick()
    print FormatJson({before:before,chapterPaused:chapterPaused,stale:stale,after:m.audioNode.control,local:m.audioLocalMs})
  ''')
  self.assertEqual(r,dict(before='play',chapterPaused='pause',stale='play',after='pause',local=60000))
 def test_explicit_play_cancels_pending_pause_and_stale_owner_cannot_pause(self):
  r=self.flow('''
    SiloUIAudioSeek(30000)
    m.audioNode.state="playing":m.audioNode.position=30
    SiloUIAudioKey("play")
    onSiloUIAudioState()
    explicit=m.audioNode.control
    m.audioNode.state="paused":SiloUIAudioSeek(60000)
    m.audioToken=8:m.audioNode.state="playing":m.audioNode.position=60:m.audioNode.control="play"
    onSiloUIAudioState()
    print FormatJson({explicit:explicit,stale:m.audioNode.control})
  ''')
  self.assertEqual(r,dict(explicit='resume',stale='play'))

 def test_cross_part_seek_carries_pause_through_release_and_new_start(self):
  r=self.flow('''
    m.audioPlan=invalid
    m.audioQueue.Push({offsetMs:120000,durationMs:120000})
    SiloUIAudioRequestPart(1,30000)
    carried=m.audioPartPaused
    m.audioNext=invalid
    SiloUIAudioResult("audio_start",{ok:true,plan:{startPositionMs:30000,headers:{},cleanupOwner:{}}},{},m.audioToken)
    m.audioNode.state="playing":m.audioNode.position=30
    onSiloUIAudioState()
    paused=m.audioNode.control
    m.audioPlan=invalid:SiloUIAudioRelease()
    print FormatJson({carried:carried,paused:paused,cleared:m.audioPausedSeek=invalid,partCleared:m.audioPartPaused=false})
  ''')
  self.assertEqual(r,dict(carried=True,paused='pause',cleared=True,partCleared=True))

 def test_play_during_cross_part_allocation_cancels_pause(self):
  r=self.flow('''
    m.audioPlan=invalid
    SiloUIAudioRequestPart(0,30000)
    SiloUIAudioKey("play")
    SiloUIAudioResult("audio_start",{ok:true,plan:{startPositionMs:30000,headers:{},cleanupOwner:{}}},{},m.audioToken)
    m.audioNode.state="playing":m.audioNode.position=30
    onSiloUIAudioState()
    print FormatJson({control:m.audioNode.control,pending:m.audioPausedSeek<>invalid})
  ''')
  self.assertEqual(r,dict(control='play',pending=False))

 def test_paused_target_sample_does_not_cancel_intent_before_delayed_playing(self):
  for target in [36784,38000]:
   with self.subTest(target=target):
    r=self.flow('''
     SiloUIAudioSeek(TARGET)
     m.audioNode.position=TARGET/1000#
     onSiloUIAudioState()
     onSiloUIAudioTick()
     pending=m.audioPausedSeek<>invalid
     m.audioNode.state="playing":m.audioNode.control="play"
     onSiloUIAudioState()
     first=m.audioNode.control
     m.audioNode.state="paused":onSiloUIAudioState()
     m.audioNode.state="playing":m.audioNode.control="play"
     onSiloUIAudioTick()
     print FormatJson({pending:pending,first:first,late:m.audioNode.control})
    '''.replace('TARGET',str(target)))
    self.assertEqual(r,dict(pending=True,first='pause',late='pause'))
