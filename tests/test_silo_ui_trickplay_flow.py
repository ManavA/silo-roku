"""One thumbnail follows current scrub ownership without changing playback."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]

class TrickplayFlowTests(unittest.TestCase):
    def flow(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            module=Path(tmp)/'preview.brs'
            source=(ROOT/'components/SiloUITrickplay.brs').read_text()
            source=re.sub(r'function TransportTrickplayCreateTask\(\).*?\nend function', '''function TransportTrickplayCreateTask() as Object
                m.created++
                return {state:"RUN",cancelled:false,result:{},observeField:sub(a,b)
                end sub}
                end function''',source,flags=re.S)
            module.write_text(source)
            boundary=Path(tmp)/'boundary.brs';boundary.write_text('''function DetailPhotoSessionRevision() as Integer
return 7
end function
function EventNode() as Object
return m.node
end function
function SameNode(other as Object) as Boolean
return true
end function''')
            value=run_brightscript([module,boundary,ROOT/'source/core/ArtworkPolicy.brs',ROOT/'source/core/SiloUITrickplayPolicy.brs',ROOT/'source/core/SiloUIFormat.brs'],'''
            m.created=0:m.tpSequence=0:m.tpAttempted=false:m.memoryHigh=false:m.view="player":m.provider="silo":m.sourceId="silo:server":m.profileId="profile":m.generation=2:m.playToken=5
            m.nativePlaybackToken=5:m.nativePlaybackOwner={sourceId:m.sourceId,profileId:m.profileId,generation:2}
            m.playPlan={provider:"silo",versionId:"42",itemId:"movie:one"}:m.playItem={itemId:"movie:one"}
            m.transport={visible:true}:m.transportEnabled=true:m.tpPoster={uri:"",loadStatus:"ready"}:m.tpClip={visible:false}
            m.transportPreviewMs=invalid
            '''+body,root=Path(tmp))
            return json.loads(value)

    def test_only_actual_scrub_starts_one_worker_and_commit_cancels_it(self):
        actual=self.flow('''TransportTrickplayUpdate():before=m.created
        m.transportPreviewMs=10000:TransportTrickplayUpdate():TransportTrickplayUpdate()
        worker=m.tpTask:m.transportPreviewMs=invalid:TransportTrickplayUpdate()
        print FormatJson({before:before,created:m.created,cancelled:worker.cancelled,uri:m.tpPoster.uri,visible:m.tpClip.visible})''')
        self.assertEqual(actual,dict(before=0,created=1,cancelled=True,uri='',visible=False))

    def test_wrong_owner_file_or_memory_falls_back_immediately(self):
        for change in ['m.profileId="other"','m.sourceId="silo:other"','m.generation=3','m.playToken=6','m.playPlan.versionId="43"','m.playPlan.itemId="movie:two"','m.memoryHigh=true','m.transport.visible=false']:
            with self.subTest(change=change):
                actual=self.flow('''m.transportPreviewMs=10000:TransportTrickplayUpdate():worker=m.tpTask
                m.tpPoster.uri="tmp:/scrub-1-1.jpg":m.tpClip.visible=true
                '''+change+'''
                TransportTrickplayUpdate()
                print FormatJson({cancelled:worker.cancelled,uri:m.tpPoster.uri,visible:m.tpClip.visible})''')
                self.assertEqual(actual,dict(cancelled=True,uri='',visible=False))

    def test_only_current_sheet_is_shown_and_tile_tracks_latest_target(self):
        actual=self.flow('''m.transportPreviewMs=10000:TransportTrickplayUpdate()
        m.tpTask.result={ok:true,uri:"tmp:/scrub-1-1.jpg",sheet:0,intervalMs:10000,width:300,height:126,columns:10,rows:10,count:102,sheetWidth:3000,sheetHeight:1260,expires:2000000000}
        TransportTrickplayUpdate():TransportTrickplayUpdate()
        first={visible:m.tpClip.visible,translation:m.tpPoster.translation}
        m.transportPreviewMs=250000:TransportTrickplayUpdate()
        moved={visible:m.tpClip.visible,translation:m.tpPoster.translation}
        m.transportPreviewMs=1000000:TransportTrickplayUpdate()
        print FormatJson({first:first,moved:moved,visible:m.tpClip.visible,uri:m.tpPoster.uri})''')
        self.assertEqual(actual,dict(first=dict(visible=True,translation=[-240,0]),moved=dict(visible=True,translation=[-1200,-201.6]),visible=False,uri=''))

    def test_expired_sheet_is_hidden_without_mutating_seek_target(self):
        actual=self.flow('''m.transportPreviewMs=10000:TransportTrickplayUpdate()
        m.tpTask.result={ok:true,uri:"tmp:/scrub-1-1.jpg",expires:1}
        m.tpPoster.uri="tmp:/scrub-1-1.jpg":m.tpClip.visible=true
        TransportTrickplayUpdate()
        print FormatJson({visible:m.tpClip.visible,uri:m.tpPoster.uri,target:m.transportPreviewMs})''')
        self.assertEqual(actual,dict(visible=False,uri='',target=10000))

    def test_cancelled_worker_finishes_before_next_scrub_can_start(self):
        actual=self.flow('''m.transportPreviewMs=10000:TransportTrickplayUpdate():old=m.tpTask
        m.transportPreviewMs=invalid:TransportTrickplayUpdate()
        m.transportPreviewMs=20000:TransportTrickplayUpdate():during=m.created
        old.state="STOP":TransportTrickplayUpdate()
        print FormatJson({during:during,created:m.created,target:m.tpTask.targetMs,cancelled:m.tpTask.cancelled})''')
        self.assertEqual(actual,dict(during=1,created=2,target=20000,cancelled=False))
