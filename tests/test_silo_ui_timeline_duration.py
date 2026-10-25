"""Source duration stays stable while native HLS advertises a partial window."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class TimelineDurationTests(unittest.TestCase):
    def test_pause_transport_scrub_and_completion_use_selected_source_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            stubs = Path(tmp) / 'render.brs'
            stubs.write_text('''sub TransportTrickplayUpdate()
end sub
sub PaintPills(name, focused)
end sub
''')
            output = run_brightscript([
                ROOT/'components/SiloUIPlayer.brs', ROOT/'components/SiloUITransport.brs',
                ROOT/'source/core/SiloUIPlayerPolicy.brs', ROOT/'source/core/SiloUITransportPolicy.brs',
                ROOT/'source/core/SiloUIFormat.brs', stubs,
            ], '''
                m.playPlan={sourceId:"silo",itemId:"film",versionId:"file",timelineOffsetMs:60000}
                m.playVersions=[{sourceId:"silo",itemId:"other",versionId:"file",durationMs:100000},{sourceId:"silo",itemId:"film",versionId:"file",durationMs:6506000}]
                m.playItem={title:"Film",durationMs:0}
                m.video={position:90,duration:753,state:"paused"}
                m.transport={visible:true}:m.transportPreviewMs=invalid:m.transportIndex=0
                m.playerCue={visible:true}:m.transportTitle={}:m.transportTime={}:m.transportProgress={}
                m.transportHint={}:m.transportActions={}
                pills=[]
                for i=0 to 3
                    pills.Push({bg:{},label:{}})
                end for
                m.pillGroups={transportActions:{pills:pills}}
                TransportPaint()
                first=m.transportTime.text
                m.video.duration=484
                TransportPaint()
                m.playMarkers=[]:m.playNext={}:m.upNextDismissed=false
                m.video.position=470
                cue=PlayerCurrentCue()
                print FormatJson({first:first,second:m.transportTime.text,duration:TransportDuration(),completion:PlayerCompletionDurationMs(),upNext:cue.upNext,seek:SiloUITransportSeek(6400000,TransportDuration(),60000,600000,0)})
            ''',root=Path(tmp))
        self.assertEqual(json.loads(output),dict(first='2:30 / 108:26',second='2:30 / 108:26',duration=6506000,completion=6506000,upNext=False,seek=6505000))

    def test_metadata_and_native_fallback_preserve_unknown_and_rebased_timelines(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = run_brightscript([
                ROOT/'components/SiloUIPlayer.brs', ROOT/'source/core/SiloUIFormat.brs',
            ], '''
                m.playPlan={sourceId:"silo",itemId:"film",versionId:"file",timelineOffsetMs:60000}
                m.video={duration:100}:m.playItem={durationMs:6506000}
                catalog=PlayerTimelineDurationMs():completion=PlayerCompletionDurationMs()
                m.playPlan.durationMs=6400000
                plan=PlayerTimelineDurationMs()
                m.playVersions=[{sourceId:"silo",itemId:"film",versionId:"file",durationMs:0}]
                unknown=PlayerTimelineDurationMs()
                m.playVersions.Push({sourceId:"silo",itemId:"film",versionId:"file",durationMs:6506000})
                ambiguous=PlayerTimelineDurationMs()
                m.playVersions=[]:m.playItem={}:m.playPlan.durationMs=0
                native=PlayerTimelineDurationMs()
                m.video.duration=0
                live=PlayerTimelineDurationMs()
                print FormatJson({catalog:catalog,completion:completion,plan:plan,unknown:unknown,ambiguous:ambiguous,native:native,live:live})
            ''',root=Path(tmp))
        self.assertEqual(json.loads(output),dict(catalog=6506000,completion=160000,plan=6400000,unknown=0,ambiguous=0,native=160000,live=0))
