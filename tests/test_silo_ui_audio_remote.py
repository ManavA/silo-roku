"""Audio controls stay reachable without firmware's Options overlay."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class SiloUIAudioRemoteTests(unittest.TestCase):
 def test_up_down_and_options_open_actual_audio_options_without_stopping_audio(self):
  with tempfile.TemporaryDirectory() as d:
   library=Path(d)/'library.brs'
   library.write_text((ROOT/'components/SiloUILibrary.brs').read_text().replace('CreateObject("roSGNode", "Dialog")','FixtureDialog()'))
   boundary=Path(d)/'native.brs';boundary.write_text('''
    function FixtureDialog() as Object
      return {observeField:sub(fieldName,handler)
      end sub}
    end function
   ''')
   files=[ROOT/'components/SiloUIAudio.brs',library,ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs',boundary]
   out=run_brightscript(files,'''
    m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.browseViewToken=2:m.view="audio":m.audioToken=7
    m.audioPlan={sessionId:"lease"}:m.audioIndex=0:m.audioQueue=[{chapters:[{title:"Chapter 1"},{title:"Chapter 2"}]}]
    m.audioNode={state:"playing",control:"play"}:m.top={appFocused:true}
    opened=[]
    for each key in ["up","down","options"]
      m.top.dialog=invalid
      SiloUIAudioKey(key)
      if m.top.dialog=invalid
        opened.Push({key:key,opened:false})
      else
        opened.Push({key:key,opened:true,title:m.top.dialog.title,lastChoice:m.browsePaged.choices[9]})
      end if
    end for
    print FormatJson({opened:opened,control:m.audioNode.control,focused:m.top.appFocused,token:m.audioOptionsToken})
   ''',root=Path(d))
  self.assertEqual(json.loads(out),dict(opened=[dict(key=k,opened=True,title='Audio controls and current-part chapters',lastChoice='Chapter 2') for k in ['up','down','options']],control='play',focused=True,token=7))

 def test_audio_status_and_hint_have_explicit_multiline_bounds(self):
  import xml.etree.ElementTree as ET
  scene=ET.parse(ROOT/'components/SiloUIScene.xml')
  for name in ['audioStatus','audioHint']:
   node=scene.find('.//Label[@id="'+name+'"]')
   self.assertEqual(node.get('wrap'),'true')
   self.assertEqual(node.get('maxLines'),'3')
   self.assertEqual(node.get('width'),'1080')
  self.assertIn('Up / Down:',scene.find('.//Label[@id="audioHint"]').get('text'))

 def test_firmware_focus_loss_still_stops_syncs_and_cleans_up_with_short_status(self):
  with tempfile.TemporaryDirectory() as d:
   boundary=Path(d)/'native.brs';boundary.write_text('''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action)
    end sub
    function FixtureHttpAgent() as Object
      return {}
    end function
   ''')
   audio=Path(d)/'audio.brs';audio.write_text((ROOT/'components/SiloUIAudio.brs').read_text().replace('CreateObject("roHttpAgent")','FixtureHttpAgent()'))
   files=[audio,ROOT/'components/SiloUIRobustness.brs',ROOT/'source/core/SiloUIAudioPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',boundary]
   out=run_brightscript(files,'''
    m.calls=[]:m.view="audio":m.audioPlan={sessionId:"lease",installationId:"install",stopId:"synthetic-stop"}
    m.audioOwner={provider:"silo",sourceId:"silo:synthetic",profileId:"p",generation:1,sessionRevision:0}
    m.audioStarted=true:m.audioPositionReady=true:m.audioToken=1:m.audioSequence=0:m.cleanupTickets={}
    m.audioBook={itemId:"book",durationMs:60000}:m.audioQueue=[{offsetMs:0,durationMs:60000}]
    m.audioIndex=0:m.audioLocalMs=10000:m.audioNode={state:"playing",setHttpAgent:sub(agent)
    end sub}
    m.audioTimer={}:m.top={appFocused:false,label:{},findNode:function(id)
      return m.label
    end function}
    onSiloUIAudioAppFocus()
    print FormatJson({control:m.audioNode.control,cleared:m.audioPlan=invalid,timer:m.audioTimer.control,calls:m.calls,status:m.top.label.text})
   ''',root=Path(d))
  self.assertEqual(json.loads(out,strict=False),dict(control='stop',cleared=True,timer='stop',calls=['audio_sync','playback_progress','playback_stop'],status='Playback stopped while app was inactive.\nPress Back to return.'))
