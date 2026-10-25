"""The accepted experimental plan chooses its budget at native guard creation."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
from tests import test_silo_ui_original_playback as original

ROOT=Path(__file__).resolve().parents[1]

class ExperimentalStartupFlow(unittest.TestCase):
    def test_native_start_uses_longer_budget_only_for_explicit_boolean_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            source=(ROOT/'components/SiloUIPlayer.brs').read_text()
            for kind,name in [('sub','onPlayerTracks'),('sub','PlayerUpdateNativeActions'),
                              ('function','PlayerCurrentCue'),('function','PlayerOriginalOutputFingerprint'),
                              ('function','PlayerOriginalCaptureBinding')]:
                source=source.replace(kind+' '+name+'(',kind+' Unused'+name+'(',1)
            player=folder/'player.brs';player.write_text(source)
            boundary=folder/'boundary.brs';boundary.write_text('''
sub onPlayerTracks(event=invalid as Dynamic)
end sub
sub PlayerUpdateNativeActions(cue as Object)
end sub
function PlayerCurrentCue() as Object
 return {}
end function
function PlayerOriginalOutputFingerprint() as String
 return "display-1"
end function
function PlayerOriginalCaptureBinding() as Dynamic
 return invalid
end function
function SiloUIOwner() as Object
 return {provider:"silo",sourceId:m.proof.sourceId,profileId:m.proof.scope.profileId,generation:2}
end function
''')
            code='m.proof=ParseJson("'+json.dumps(original.descriptor()).replace('"','""')+'")\n'+'''
 answers=[]
 for each flag in [true,false,invalid,"true",1]
  m.originalPlayback=invalid:m.originalGeneration=3:m.playToken=7
  m.provider="silo":m.view="detail":m.zone="detailButtons"
  m.playItem={type:"movie",title:"Fixture"}:m.detailEpisodes=[]
  m.video={state:"buffering",position:0,globalCaptionMode:"Off",content:{identity:"new"},setFocus:sub(value)
  end sub}
  m.top={findNode:function(name)
   return {visible:true}
  end function}
  m.nav={}:m.toast={}:m.progressTimer={}
  plan={provider:"silo",sourceId:m.proof.sourceId,itemId:m.proof.itemId,versionId:m.proof.fileId,sessionId:m.proof.sessionId,planId:m.proof.planId,streamFormat:"mkv",originalPlayback:m.proof}
  if flag<>invalid then plan["experimentalOriginal"]=flag
  PlayerStart(plan,true)
  r=SiloUIOriginalReduce(m.originalPlayback,{kind:"tick",token:7,generation:3,nowMs:40000,nativeState:"buffering"})
  answers.Push({flag:flag,command:r.command,muted:m.video.mute,phase:r.state.phase})
 end for
 print FormatJson(answers)
'''
            files=[player,boundary,ROOT/'source/core/SiloPlaybackPolicy.brs',ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'source/core/SiloUIOriginalPlaybackPolicy.brs',ROOT/'source/core/SiloUIPlayerPolicy.brs',ROOT/'source/core/SiloUIFormat.brs']
            result=json.loads(run_brightscript(files,code,root=folder).strip().splitlines()[-1])
        self.assertIsNone(result[0]['command'])
        self.assertEqual('await_inventory',result[0]['phase'])
        self.assertTrue(all(row['muted'] for row in result))
        for row in result[1:]:
            self.assertEqual(dict(kind='recover',reason='startup_timeout'),row['command'],row)

if __name__=='__main__':unittest.main()
