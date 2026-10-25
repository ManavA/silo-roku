"""The custom transport reserves caption space without changing caption mode."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class TransportCaptionTests(unittest.TestCase):
    def test_native_caption_area_moves_above_transport_and_restores_on_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_brightscript([ROOT/'components/SiloUITrickplay.brs',ROOT/'components/SiloUITransport.brs'], '''
                m.transportEnabled = true
                m.transport = {visible:true}
                m.video = {globalCaptionMode:"On",hasField:function(name)
                    return name = "captionRenderArea"
                end function}
                onTransportVisibility()
                during = m.video.captionRenderArea
                m.transport.visible = false
                onTransportVisibility()
                print FormatJson({during:during,after:m.video.captionRenderArea,mode:m.video.globalCaptionMode})
            ''', root=Path(tmp))
        self.assertEqual(json.loads(result), {'during': {'mode':'override','overridePlacement':True,'scaleFonts':'off','keepSafeMargins':True,'x':0,'y':0,'width':1280,'height':500}, 'after': {'mode':'fullscreen'}, 'mode':'On'})

    def test_older_firmware_uses_native_controls_for_active_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp)/'notice.brs'
            stub.write_text('sub Toast(message as String)\n m.notice=message\nend sub')
            result = run_brightscript([ROOT/'components/SiloUITrickplay.brs',ROOT/'components/SiloUITransport.brs', ROOT/'components/SiloUIPlayer.brs', stub], '''
                m.transportEnabled = true
                m.transport = {visible:true}
                m.top = {findNode:function(name)
                    return {visible:false}
                end function}
                m.transportTimer = {control:"start"}
                m.video = {globalCaptionMode:"On",enableUI:false,hasField:function(name)
                    return false
                end function,setFocus:sub(value)
                    m.focused=value
                end sub}
                onTransportVisibility()
                print FormatJson({custom:m.transportEnabled,native:m.video.enableUI,focused:m.video.focused,visible:m.transport.visible,caption:m.video.globalCaptionMode})
            ''', root=Path(tmp))
        self.assertEqual(json.loads(result), dict(custom=False,native=True,focused=True,visible=False,caption='On'))

    def native_modes(self, body, supported=True):
        with tempfile.TemporaryDirectory() as tmp:
            stub=Path(tmp)/'notice.brs';stub.write_text('sub Toast(message as String)\n m.notice=message\nend sub')
            output=run_brightscript([ROOT/'components/SiloUITrickplay.brs',ROOT/'components/SiloUITransport.brs',ROOT/'components/SiloUIPlayer.brs',ROOT/'source/core/SiloUIFormat.brs',stub],'''
 m.transport={visible:false}:m.transportTimer={}
 m.top={findNode:function(name)
 return {visible:false}
 end function}
 m.manualFocus={setFocus:sub(value)
 m.focused=value
 end sub}
 m.playPlan={provider:"silo",canSeekAnywhere:false}:m.playItem={durationMs:7200000}
 m.video={enableUI:false,globalCaptionMode:"On",hasField:function(name)
 return name="enableTrickPlay" and SUPPORTED
 end function,setFocus:sub(value)
 m.focused=value
 end sub}
 '''.replace('SUPPORTED','true' if supported else 'false')+body,root=Path(tmp))
            return json.loads(output)

    def test_restricted_memory_and_manual_native_ui_disable_trickplay_each_bind(self):
        v=self.native_modes('''m.memoryHigh=true:TransportStart()
 first={ui:m.video.enableUI,trick:m.video.enableTrickPlay,caption:m.video.globalCaptionMode}
 m.playPlan.canSeekAnywhere=true:TransportStart()
 second={ui:m.video.enableUI,trick:m.video.enableTrickPlay}
 m.playPlan.canSeekAnywhere=false:m.memoryHigh=false:TransportStart()
 m.transport.visible=true:m.transportIndex=3:TransportKey("OK")
 print FormatJson({first:first,second:second,manual:{ui:m.video.enableUI,trick:m.video.enableTrickPlay}})''')
        self.assertEqual(dict(first=dict(ui=True,trick=False,caption='On'),second=dict(ui=True,trick=True),manual=dict(ui=True,trick=False)),v)

    def test_restricted_missing_sdk_field_keeps_lightweight_peer_and_captions(self):
        v=self.native_modes('''m.memoryHigh=true:TransportStart():PlayerPlaybackFocus()
 m.transport.visible=true:onTransportVisibility()
 print FormatJson({custom:m.transportEnabled,ui:m.video.enableUI,caption:m.video.globalCaptionMode,peer:m.manualFocus.focused,visible:m.transport.visible})''',supported=False)
        self.assertEqual(dict(custom=True,ui=False,caption='On',peer=True,visible=False),v)
