"""Shipping source-audio controls retain playback ownership and paused intent."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class SiloUIPlaybackChoicesFlowTests(unittest.TestCase):
 def test_source_audio_result_preserves_return_captions_sequence_pause_and_owner(self):
  with tempfile.TemporaryDirectory() as d:
   helper=Path(d)/'boundary.brs';helper.write_text('''
    sub PlayerStart(plan as Object)
     m.playPlan=plan:m.playerReturn={view:"wrong"}:m.savedCaptionMode="wrong"
    end sub
   ''')
   player=Path(d)/'player.brs';player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerStart(', 'sub UnusedPlayerStart(',1))
   actual=run_brightscript([ROOT/'components/SiloUIPlaybackChoices.brs',player,ROOT/'source/core/SiloUIFormat.brs',helper],'''
    m.view="player":m.playToken=4:m.playPlan={sessionId:"lease",planId:"old",versionId:"file",cleanupOwner:{generation:2}}
    m.progressSequence=9:m.playerReturn={view:"detail",zone:"seasons"}:m.savedCaptionMode="Off"
    m.trackPref={}:m.trackPrefLanes={}:m.video={state:"buffering"}:m.playbackChoiceBusy=true:m.recoveringNative=true
    PlaybackAudioResult({ok:true,plan:{sessionId:"lease",planId:"new",versionId:"file"}},{token:4,sessionId:"lease",planId:"old",paused:true,language:"fra",name:"French"})
    print FormatJson({plan:m.playPlan,sequence:m.progressSequence,back:m.playerReturn,captions:m.savedCaptionMode,pause:m.audioRestorePause,busy:m.playbackChoiceBusy,audio:m.trackPref.audio})
   ''',root=Path(d))
  self.assertEqual(json.loads(actual),dict(plan=dict(sessionId='lease',planId='new',versionId='file',cleanupOwner=dict(generation=2)),sequence=9,back=dict(view='detail',zone='seasons'),captions='Off',pause=True,busy=False,audio='fra'))

 def test_audio_selection_captures_real_source_position_before_recovery_mode(self):
  with tempfile.TemporaryDirectory() as d:
   helper=Path(d)/'boundary.brs';helper.write_text('''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.sent=params
    end sub
    function SiloUICleanupUuid() as String
      return "synthetic-request"
    end function
    sub Toast(message as String)
    end sub
   ''')
   actual=run_brightscript([ROOT/'components/SiloUIPlayer.brs',ROOT/'components/SiloUIPlaybackChoices.brs',ROOT/'source/core/SiloUIFormat.brs',helper],'''
    m.view="player":m.playToken=4:m.playPlan={sessionId:"lease",planId:"old",timelineOffsetMs:120000,cleanupOwner:{generation:2}}
    m.video={position:37.5,state:"paused"}:m.recoveringNative=false:m.recoverPositionMs=1234
    PlaybackSelectAudio({index:2,language:"fra",name:"French"})
    print FormatJson({sent:m.sent.positionMs,captured:m.recoverPositionMs,current:PlayerPositionMs(),recovering:m.recoveringNative})
   ''',root=Path(d))
  self.assertEqual(json.loads(actual),dict(sent=157500,captured=157500,current=157500,recovering=True))

 def test_new_native_start_clears_abandoned_audio_change_and_ignores_old_result(self):
  with tempfile.TemporaryDirectory() as d:
   helper=Path(d)/'boundary.brs';helper.write_text('''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action)
    end sub
    function SiloUICleanupUuid() as String
      return "synthetic-request"
    end function
    sub Toast(message as String)
    end sub
   ''')
   import re
   owner=re.search(r'(?ms)^function SiloUIOwner\(.*?^end function',
                   (ROOT/'components/SiloUIRobustness.brs').read_text()).group(0)
   helper.write_text(helper.read_text()+'\n'+owner)
   files=[ROOT/p for p in ['source/core/SiloPlaybackPolicy.brs','components/SiloUIPlayer.brs','components/SiloUISubtitleArtifact.brs','components/SiloUIPlaybackChoices.brs','components/SiloUIDiagnostics.brs','source/core/SiloUIFormat.brs','source/core/SiloUIPlayerPolicy.brs','source/core/SiloUISettingsPolicy.brs','source/core/TrackPreference.brs']]+[helper]
   actual=run_brightscript(files,'''
    m.calls=[]:m.provider="silo":m.playToken=4:m.view="detail":m.zone="detailButtons":m.playbackChoiceBusy=true:m.audioChoice={token:3}
    m.top={findNode:function(name)
      return {visible:true}
    end function}
    m.video={position:5,duration:100,globalCaptionMode:"Off",availableAudioTracks:[],availableSubtitleTracks:[],setFocus:sub(value)
    end sub}
    m.playItem={type:"movie",durationMs:100000,title:"Fixture"}:m.detailEpisodes=[]:m.playMarkers=[]:m.preferences={}:m.trackPref={}:m.trackPrefLanes={}
    m.nav={}:m.toast={}:m.progressTimer={}:m.upNextDismissed=false:m.introDismissed=false
    PlayerStart({sessionId:"new",planId:"new-plan",versionId:"f1",startPositionMs:5000,timelineOffsetMs:0,cleanupOwner:{}},true)
    afterStart=m.playbackChoiceBusy
    PlaybackAudioResult({ok:false},{token:3,sessionId:"old",planId:"old-plan"})
    PlaybackSelectAudio({index:2,language:"fra",name:"French"})
    print FormatJson({afterStart:afterStart,calls:m.calls})
   ''',root=Path(d))
  self.assertEqual(json.loads(actual),dict(afterStart=False,calls=['playback_audio_select']))

 def test_partial_native_inventory_does_not_hide_distinct_catalog_lanes(self):
  with tempfile.TemporaryDirectory() as d:
   actual=run_brightscript([ROOT/'components/SiloUIPlaybackChoices.brs',ROOT/'source/core/SiloPlaybackPolicy.brs',ROOT/'source/core/SiloUIPlayerPolicy.brs',ROOT/'source/core/SiloUIFormat.brs'],'''
    m.provider="silo":m.playPlan={versionId:"f1"}
    m.video={availableAudioTracks:[{Track:"native-a",Language:"eng"},{Track:"native-b",Language:"fra"}]}
    m.playVersions=[{versionId:"f1",audioTracks:[{index:0,language:"eng",codec:"aac",title:"English"},{index:1,language:"fra",codec:"aac",title:"French"},{index:2,language:"jpn",codec:"aac",title:"Japanese"},{index:2,language:"jpn",codec:"aac",title:"Japanese duplicate"}]}]
    choices=PlaybackSourceAudioChoices()
    indices=[]
    for each choice in choices
      indices.Push(choice.index)
    end for
    print FormatJson(indices)
   ''',root=Path(d))
  self.assertEqual(json.loads(actual),[0,1,2])

 def test_close_after_view_transition_clears_pending_audio_intent(self):
  with tempfile.TemporaryDirectory() as d:
   actual=run_brightscript([ROOT/'components/SiloUIPlayer.brs'],'''
    m.view="detail":m.playbackChoiceBusy=true:m.audioChoice={token:3}:m.audioRestorePause=true
    PlayerClose(false)
    print FormatJson({busy:m.playbackChoiceBusy,choice:m.audioChoice,restorePause:m.audioRestorePause})
   ''',root=Path(d))
  self.assertEqual(json.loads(actual),dict(busy=False,choice=None,restorePause=False))
