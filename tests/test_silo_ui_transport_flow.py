"""Custom transport preview must not seek until the user commits it."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class SiloUITransportFlowTests(unittest.TestCase):
    def test_back_cancels_preview_and_ok_commits_in_transport_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = (ROOT/'components/SiloUITransport.brs').read_text() if (ROOT/'components/SiloUITransport.brs').exists() else ''
            # Rendering is an OS boundary, not part of timeline behavior.
            import re
            source = re.sub(r'sub TransportPaint\(\).*?\nend sub', 'sub TransportPaint()\nend sub', source, flags=re.S)
            module = Path(tmp)/'transport.brs';module.write_text(source)
            result = run_brightscript([module, ROOT/'source/core/SiloUITransportPolicy.brs', ROOT/'components/SiloUIPlayer.brs', ROOT/'source/core/SiloUIFormat.brs'], '''
                m.transportEnabled = true
                m.transport = {visible:true}
                m.transportPreviewMs = 85000
                m.transportOffsetMs = 60000
                m.video = {seek:-1}
                m.playPlan = {timelineOffsetMs:60000}
                cancelled = TransportKey("back")
                afterCancel = m.video.seek
                m.transport.visible = true
                m.transportPreviewMs = 90000
                committed = TransportKey("OK")
                print FormatJson({cancelled:cancelled,afterCancel:afterCancel,committed:committed,seek:m.video.seek,preview:m.transportPreviewMs})
            ''', root=Path(tmp))
            self.assertEqual(json.loads(result), dict(cancelled=True, afterCancel=-1, committed=True, seek=30, preview=None))

    def test_refused_stock_seek_explains_failure_and_keeps_controls_usable(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            source = (ROOT/'components/SiloUITransport.brs').read_text()
            source = re.sub(r'sub TransportPaint\(\).*?\nend sub', 'sub TransportPaint()\nend sub', source, flags=re.S)
            module = Path(tmp)/'transport.brs'
            module.write_text(source)
            ui = Path(tmp)/'ui.brs'
            ui.write_text('sub Toast(message as String)\n m.notice = message\nend sub')
            result = run_brightscript([module, ROOT/'components/SiloUIPlayer.brs',
                                      ROOT/'components/SiloUICompatPlayback.brs', ui], '''
                m.transportEnabled = true
                m.transport = {visible:true}
                m.transportPreviewMs = 90000
                m.transportIndex = 2
                m.transportRepeats = 4
                m.transportIdle = 5
                m.playPlan = {transport:"silo_compat"}
                m.compatPreparation = {engine:{ready:true},phase:"playing"}
                m.video = {seek:-1,state:"playing"}
                handled = TransportKey("OK")
                after = {handled:handled,notice:m.notice,preview:m.transportPreviewMs,visible:m.transport.visible,index:m.transportIndex,repeats:m.transportRepeats,idle:m.transportIdle,seek:m.video.seek,state:m.video.state}
                back = TransportKey("back")
                print FormatJson({after:after,back:back,visible:m.transport.visible})
            ''', root=Path(tmp))
            self.assertEqual(json.loads(result), dict(
                after=dict(handled=True, notice="Seeking is unavailable for this stream.",
                           preview=None, visible=True, index=2, repeats=0, idle=0,
                           seek=-1, state="playing"), back=True, visible=False))

    def test_custom_controls_own_remote_focus_after_modal_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_brightscript([ROOT/'components/SiloUITransport.brs', ROOT/'components/SiloUIPlayer.brs'], '''
                m.transportEnabled = true
                m.focused = ""
                m.manualFocus = {setFocus:sub(value)
                    m.top.focused = "manual"
                end sub}
                m.video = {setFocus:sub(value)
                    m.top.focused = "video"
                end sub}
                m.manualFocus.top = m
                m.video.top = m
                PlayerPlaybackFocus()
                custom = m.focused
                m.transportEnabled = false
                PlayerPlaybackFocus()
                print FormatJson({custom:custom,native:m.focused})
            ''', root=Path(tmp))
            self.assertEqual(json.loads(result), dict(custom='manual', native='video'))

    def test_still_watching_confirmation_restores_custom_remote_focus(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            source = (ROOT/'components/SiloUIPlayer.brs').read_text()
            source = re.sub(r'sub PlayerAdvance\(.*?\nend sub', 'sub PlayerAdvance(automatic=false as Boolean)\nend sub', source, count=1, flags=re.S)
            module = Path(tmp)/'player.brs';module.write_text(source)
            result = run_brightscript([module], '''
                m.transportEnabled=true:m.focused="":m.view="player":m.bingeToken=4:m.playToken=4
                m.manualFocus={setFocus:sub(value)
                    m.top.focused="manual"
                end sub}
                m.manualFocus.top=m
                m.bingeDialog={buttonSelected:0}
                onPlayerStillWatching()
                print FormatJson({focused:m.focused,dialogClosed:m.bingeDialog=invalid})
            ''',root=Path(tmp))
            self.assertEqual(json.loads(result),dict(focused='manual',dialogClosed=True))
