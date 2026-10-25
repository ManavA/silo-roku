"""An owned experimental restart reselects AC3 without trusting stale playback."""
import json
from pathlib import Path
import tempfile
import unittest
from tests.test_silo_ui_original_playback import descriptor
from tools.brightscript import run_brightscript

ROOT=Path(__file__).resolve().parents[1]

class DTSRestartScene(unittest.TestCase):
    def test_retry_rereads_current_inventory_and_waits_for_actual_ac3_advancement(self):
        proof=descriptor();proof['dolbyVisionProfile']=8
        proof['sourceAudio'][0].update(codec='dts',channels=6,layout='5.1')
        proof['sourceAudio'][1].update(channels=2,layout='stereo')
        proof['audioIdentity'].update(channels=2,layout='stereo')
        raw=[dict(Track='native-dts',Format='DTS Coherent Acoustics',Language='eng'),
             dict(Track='native-ac3',Format='Dolby Digital',Language='eng')]
        payload=json.dumps([proof,raw]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace(
                'function PlayerOriginalOutputFingerprint()', 'function UnusedPlayerOriginalOutputFingerprint()',1))
            boundary=root/'boundary.brs'
            boundary.write_text('function PlayerOriginalOutputFingerprint() as String\n return "output-1"\nend function\n')
            code='values=ParseJson("'+payload+'")\n'+'''
 proof=values[0]
 m.provider="silo":m.sourceId=proof.sourceId:m.profileId="profile-1":m.generation=9:m.playToken=7:m.originalGeneration=3
 node={identity:"content",url:"https://example.invalid/owned",streamFormat:"mkv",isSameNode:function(other as Object) as Boolean
  return m.identity=other.identity
 end function}
 m.originalContent=node:m.originalFreshState=true:m.originalDrained=true:m.originalOldInventory="":m.originalOutputFingerprint="output-1"
 m.video={identity:"video",content:node,state:"buffering",availableAudioTracks:values[1],audioTrack:"",currentAudioTrack:"native-dts",audioFormat:"dts",position:0,mute:true,isSameNode:function(other as Object) as Boolean
  return m.identity=other.identity
 end function,SetFields:function(fields as Object) as Boolean
  m.control=fields.control
  return true
 end function}
 m.playPlan={provider:"silo",sourceId:proof.sourceId,itemId:proof.itemId,versionId:proof.fileId,sessionId:proof.sessionId,planId:proof.planId,url:node.url,streamFormat:"mkv",originalPlayback:proof,experimentalOriginal:true,siloPlayback:{playbackAttemptId:proof.playbackAttemptId}}
 m.originalPlayback=SiloUIOriginalCreate(proof,7,3,0,true)
 m.originalBinding=PlayerOriginalCaptureBinding()
 m.originalClock={nowMs:1000,TotalMilliseconds:function() as Integer
  return m.nowMs
 end function}
 PlayerOriginalObserve():PlayerOriginalInventory(true)
 m.video.state="finished":m.originalClock.nowMs=5000:PlayerOriginalObserve()
 m.video.audioTrack=""
 m.video.state="buffering":m.originalClock.nowMs=6000:PlayerOriginalInventory()
 retried={phase:m.originalPlayback.phase,track:m.video.audioTrack,muted:m.video.mute}
 m.video.state="playing":m.video.position=1:m.originalClock.nowMs=7000:PlayerOriginalObserve()
 wrong={phase:m.originalPlayback.phase,muted:m.video.mute}
 m.video.currentAudioTrack="native-ac3":m.video.audioFormat="ac3":m.video.position=2:m.originalClock.nowMs=8000:PlayerOriginalObserve()
 readback={phase:m.originalPlayback.phase,muted:m.video.mute}
 m.video.position=3:m.originalClock.nowMs=9000:PlayerOriginalObserve()
 print FormatJson({retried:retried,wrong:wrong,readback:readback,final:{phase:m.originalPlayback.phase,muted:m.video.mute,startedMs:m.originalPlayback.startedMs,provenance:m.originalPlayback.mappingProvenance}})
'''
            files=[ROOT/'source/core/SiloUIOriginalPlaybackPolicy.brs',player,boundary,
                   ROOT/'source/core/SiloUIFormat.brs',ROOT/'components/SiloUIRobustness.brs']
            value=json.loads(run_brightscript(files,code,root=root).strip())
        self.assertEqual(dict(phase='selected',track='native-ac3',muted=True),value['retried'])
        self.assertEqual(dict(phase='selected',muted=True),value['wrong'])
        self.assertEqual(dict(phase='selected',muted=True),value['readback'])
        self.assertEqual(dict(phase='verified_playing',muted=False,startedMs=0,provenance='same_content_restart'),value['final'])

if __name__=='__main__':unittest.main()
