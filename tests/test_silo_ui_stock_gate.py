"""Runtime authority at the Scene's compatibility holder boundary."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_brightscript


ROOT = Path(__file__).resolve().parents[1]


class SiloUIStockGate(unittest.TestCase):
    def test_ready_callback_binds_local_playlist_through_player(self):
        # Keep the real coordinator callback; substitute device policy and SG
        # factories that the host VM cannot execute. Receipt policy has its
        # own fixture tests in test_silo_stock_context.py.
        with tempfile.TemporaryDirectory() as directory:
            source = (ROOT / "components/SiloUICompatPlayback.brs").read_text()
            source = source.replace("function SiloUICompatCurrent(", "function SiloUICompatCurrentOnDevice(")
            source = source.replace("sub SiloUICompatWatch(", "sub SiloUICompatWatchOnDevice(")
            coordinator = Path(directory) / "coordinator.brs"
            coordinator.write_text(source)
            stub = Path(directory) / "ready_stub.brs"
            stub.write_text('''
function SiloUICompatCurrent(state as Object) as Boolean
 return true
end function
function SpCopy(raw as Dynamic) as Dynamic
 return raw
end function
sub SiloUICompatWatch(state as Object)
end sub
function SiloPlaybackFile(detail as Dynamic,source as String,item as String,file as String,position as Dynamic) as Object
 return {durationMs:7200000}
end function
function TextOr(value as Dynamic) as String
 return value
end function
sub PlayerBind(payload as Object,title as String)
 m.bound=payload
 m.video.content={id:"local"}
end sub
sub PlayerStart(plan as Object,autoplay as Boolean)
 m.started=plan
end sub
function TestReadyEngine() as Object
 return {ready:true,failed:false,drainState:"pending",isSameNode:function(other as Object) as Boolean
  return m.id=other.id
 end function,id:"engine"}
end function
function TestReadyEvent(engine as Object) as Object
 return {engine:engine,getRoSGNode:function() as Object
  return m.engine
 end function}
end function
''')
            out = run_brightscript([ROOT / "source/core/SiloNativeBearerTransport.brs",coordinator, stub], '''
engine=TestReadyEngine()
m.playToken=9:m.playItem={title:"Film"}:m.video={content:invalid}
m.compatPlayAttempt={phase:"preparing"}
m.compatPreparation={engine:engine,phase:"stock_starting",task:{cancelled:false},token:9,planGeneration:1,owner:{sourceId:"source"},intent:{itemId:"item",fileId:"file",startPositionMs:0},holderId:"holder",attemptId:"attempt",detail:{}}
onSiloUICompatStockEngine(TestReadyEvent(engine))
print "RESULT:";FormatJson({bound:m.bound,started:m.started,phase:m.compatPreparation.phase})
''', root=Path(directory))
        row = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual("playing", row["phase"])
        self.assertEqual("http://127.0.0.1:34831/g1/master.m3u8", row["bound"]["url"])
        self.assertEqual({}, row["bound"]["headers"])
        self.assertEqual("silo_compat", row["started"]["transport"])

    def test_landing_keeps_stock_position_watch_alive(self):
        script = [ROOT / "source/core/SiloNativeBearerTransport.brs", ROOT / "source/core/SiloPlaybackPolicy.brs",
                  ROOT / "components/SiloUICompatPlayback.brs"]
        out = run_brightscript(script, '''
watch={control:"start"}
state={watchdog:watch,pendingPause:false,engine:{ready:true}}
SiloUICompatLandingWatch(state)
stock=watch.control
state.engine=invalid
SiloUICompatLandingWatch(state)
print "RESULT:";FormatJson({stock:stock,native:watch.control})
''')
        row = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual({"stock": "start", "native": "stop"}, row)

    def test_ready_stock_binding_is_local_and_credential_free(self):
        script = [ROOT / "source/core/SiloNativeBearerTransport.brs", ROOT / "source/core/SiloPlaybackPolicy.brs",
                  ROOT / "components/SiloUICompatPlayback.brs"]
        out = run_brightscript(script, '''
state={owner:{sourceId:"source"},intent:{itemId:"item",fileId:"file",startPositionMs:0},holderId:"holder",attemptId:"attempt",planGeneration:1,engine:{ready:true,failed:false,drainState:"pending"}}
accepted=SiloUICompatStockLocalBinding(state)
state.engine.ready=false
refused=SiloUICompatStockLocalBinding(state)
print "RESULT:";FormatJson({accepted:accepted,refused:refused})
''')
        row = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertIsNone(row["refused"])
        self.assertEqual("http://127.0.0.1:34831/g1/master.m3u8", row["accepted"]["payload"]["url"])
        self.assertEqual({}, row["accepted"]["payload"]["headers"])
        self.assertEqual("silo_compat", row["accepted"]["plan"]["transport"])
        self.assertNotIn("token", json.dumps(row["accepted"]).lower())

    def test_engine_drain_blocks_remote_close_until_exact_node_reports_drained(self):
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / "stock_stub.brs"
            stub.write_text('''
sub SiloUIDrainMaybeDone()
end sub
sub Toast(message as String)
end sub
sub PlayerSetPlaybackStatus(message as String)
end sub
function TestEngine(id as String) as Object
 return {id:id,drainState:"pending",failed:false,ready:false,stopRequested:false,isSameNode:function(other as Object) as Boolean
  return m.id=other.id
 end function,unobserveField:sub(field as String)
 end sub}
end function
function TestEvent(node as Object) as Object
 return {node:node,getRoSGNode:function() as Object
  return m.node
 end function}
end function
''')
            script = [ROOT / "source/core/SiloNativeBearerTransport.brs", ROOT / "source/core/SiloPlaybackPolicy.brs",
                      ROOT / "components/SiloUICompatPlayback.brs", stub]
            out = run_brightscript(script, '''
m.playToken=8:m.cleanupFailed=false:m.speculationDisabled=false
engine=TestEngine("current")
task={command:invalid,privateStockContext:invalid}
m.compatPreparation={engine:engine,phase:"stock_stopping",task:task,holderId:"holder",attemptId:"attempt",owner:{provider:"silo",sourceId:"source",profileId:"profile",generation:1,sessionRevision:1},planGeneration:1,closeSequence:0,localRetired:true,intent:{startPositionMs:0},positionMs:1000,isPaused:false,token:7}
onSiloUICompatStockEngine(TestEvent(TestEngine("stale")))
stale=task.command
onSiloUICompatStockEngine(TestEvent(engine))
pending=task.command
engine.drainState="uncertain"
onSiloUICompatStockEngine(TestEvent(engine))
uncertain={command:task.command,failed:m.cleanupFailed,phase:m.compatPreparation.phase}
SiloUICompatRetry()
retry=task.command
m.cleanupFailed=false:m.compatPreparation.phase="stock_stopping":engine.drainState="drained"
m.compatPreparation.localRetired=false:m.compatPreparation.content={}
onSiloUICompatStockEngine(TestEvent(engine))
unretired={command:task.command,phase:m.compatPreparation.phase}
m.video={content:{},state:"stopped"}
m.compatPreparation.content={isSameNode:function(other as Object) as Boolean
 return false
end function}
SiloUICompatRetry()
readerRetry=task.command
m.compatPreparation.localRetired=true:m.compatPreparation.phase="stock_stopping"
onSiloUICompatStockEngine(TestEvent(engine))
print "RESULT:";FormatJson({stale:stale,pending:pending,uncertain:uncertain,retry:retry,unretired:unretired,readerRetry:readerRetry,closed:task.command,retired:m.compatPreparation.localRetired})
''')
        row = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertIsNone(row["stale"])
        self.assertIsNone(row["pending"])
        self.assertEqual({"command": None, "failed": True, "phase": "cleanup_pending"}, row["uncertain"])
        self.assertIsNone(row["retry"])
        self.assertEqual({"command": None, "phase": "cleanup_pending"}, row["unretired"])
        self.assertIsNone(row["readerRetry"])
        self.assertEqual("close", row["closed"]["action"])
        self.assertTrue(row["closed"]["localRetired"])
        self.assertTrue(row["retired"])

    def test_prepared_callback_requests_stock_context_without_scene_qa_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = Path(directory) / "coordinator.brs"
            coordinator.write_text((ROOT / "components/SiloUICompatPlayback.brs").read_text().replace("function SiloUICompatCurrent(", "function SiloUICompatCurrentOnDevice("))
            stub = Path(directory) / "stub.brs"
            stub.write_text('''
function SiloUICompatCurrent(state as Object) as Boolean
 return true
end function
function CallbackEvent(data as Object) as Object
 return {data:data,getData:function() as Object
 return m.data
 end function}
end function
''')
            out = run_brightscript([ROOT / "source/core/SiloNativeBearerTransport.brs",ROOT / "source/core/SiloPlaybackPolicy.brs", ROOT / "source/core/SiloOriginalPlaybackPolicy.brs", ROOT / "source/core/SiloCompatPlaybackPolicy.brs", coordinator, stub], '''
owner={provider:"silo",sourceId:"silo:fixture",profileId:"p",generation:3,sessionRevision:4}
qualification={schemaVersion:1,kind:"stock-p7-ac3-root-v1",approved:true,sourceId:"silo:fixture",profileId:"p",generation:3,sessionRevision:4,holderId:"h",attemptId:"a",planGeneration:1,origin:"https://fixture.invalid",transportPolicy:"controlled-fixture-v1",transportEvidence:"private-controlled-fixture",rootListenerRequired:true,fileId:"731",mediaSourceId:"media",audioOrdinal:1,audioStreamIndex:2}
m.stockQaQualification=invalid
m.compatPreparation={owner:owner,holderId:"h",attemptId:"a",commandId:"prepare",phase:"preparing",planGeneration:1,eligibilityKind:"experimental_query_p7_hdr10_fmp4_v1",intent:{startPositionMs:0,fileId:"731",audioTrackIndex:1},task:{cancelled:false}}
result={holderId:"h",attemptId:"a",commandId:"prepare",owner:owner,phase:"prepared",ok:true,class:"copied_p7_hdr10_fmp4",mediaNeverRequested:true,fileMatched:true,audioMatched:true,planGeneration:1,stockQualification:qualification}
onSiloUICompatResult(CallbackEvent(result))
print "RESULT:";FormatJson({phase:m.compatPreparation.phase,command:m.compatPreparation.task.command})
''', root=Path(directory))
        row = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual("stock_preparing", row["phase"])
        self.assertEqual("prepare_stock_context", row["command"]["action"])
        self.assertEqual("731", row["command"]["qualification"]["fileId"])

    def test_only_exact_current_controlled_owner_can_request_stock_context(self):
        script = [ROOT / "source/core/SiloNativeBearerTransport.brs", ROOT / "source/core/SiloPlaybackPolicy.brs",
                  ROOT / "components/SiloUICompatPlayback.brs"]
        out = run_brightscript(script, '''
m.stockQaQualification=invalid
state={owner:{provider:"silo",sourceId:"s",profileId:"p",generation:3,sessionRevision:4},holderId:"h",attemptId:"a",planGeneration:1,eligibilityKind:"experimental_query_p7_hdr10_fmp4_v1",intent:{startPositionMs:0,fileId:"731",audioTrackIndex:1}}
prepared=invalid
rows=[SiloUICompatStockQualification(state,prepared)]
m.stockQaQualification={schemaVersion:1,kind:"stock-p7-ac3-root-v1",approved:true,sourceId:"s",profileId:"p",generation:3,sessionRevision:4,holderId:"h",attemptId:"a",planGeneration:1,origin:"https://qa.example",transportPolicy:"controlled-fixture-v1",transportEvidence:"private-controlled-fixture",rootListenerRequired:true}
prepared={stockQualification:m.stockQaQualification}
prepared.stockQualification.fileId="731":prepared.stockQualification.mediaSourceId="media":prepared.stockQualification.audioOrdinal=1:prepared.stockQualification.audioStreamIndex=2
rows.Push(SiloUICompatStockQualification(state,prepared))
m.stockQaQualification.holderId="other"
rows.Push(SiloUICompatStockQualification(state,prepared))
prepared.stockQualification.holderId="h"
for each key in ["fileId","audioOrdinal","sourceId","profileId","sessionRevision","origin"]
 saved=prepared.stockQualification[key]
 prepared.stockQualification[key]=invalid
 rows.Push(SiloUICompatStockQualification(state,prepared))
 prepared.stockQualification[key]=saved
end for
print "RESULT:";FormatJson(rows)
''')
        rows = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertIsNone(rows[0])
        self.assertEqual("stock-p7-ac3-root-v1", rows[1]["kind"])
        self.assertEqual([None]*7,rows[2:])


if __name__ == "__main__":
    unittest.main()
