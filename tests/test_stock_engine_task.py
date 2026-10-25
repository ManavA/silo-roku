"""Stock-only Task start and terminal drain contract on the real Task source."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_brightscript


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tools/experiments/onroku_audio/multi_app/components/LocalHttpTask.brs"
DESCRIPTOR = ROOT / "tools/experiments/onroku_audio/multi_app/source/StockDescriptor.brs"
REMOTE = ROOT / "tools/experiments/onroku_audio/multi_app/source/RemoteIngest.brs"


class StockEngineTaskTests(unittest.TestCase):
    def test_bookmark_request_waits_for_index_without_native_content(self):
        source = ROOT / "tools/experiments/onroku_audio/multi_app/source"
        with tempfile.TemporaryDirectory() as directory:
            out = run_brightscript([source / "SeekPolicy.brs", source / "SeekHandoff.brs"], '''
 m.top={}:m.rolling={generation:1}:m.stopLocal=false
 m.clock={TotalMilliseconds:function() as Double
  return 1000
 end function}
 QaSeekHandleField("seekRequest",{requestId:1,targetTitleUs:17875000&})
 print "RESULT:";FormatJson({status:m.top.seekOffer.status,target:m.seek.request.requestedTitleUs,deadline:m.seek.deadline,content:m.top.content,generation:m.rolling.generation})
''', root=Path(directory))
        result = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual(dict(status="waiting_index",target=17875000,deadline=31000,content=None,generation=1),result)

    def test_host_vm_does_not_hide_missing_engine_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "components").mkdir()
            (root / "components/SiloStockEngineTask.xml").write_bytes(
                (ROOT / "components/SiloStockEngineTask.xml").read_bytes())
            script = root / "probe.brs"
            script.write_text("sub Probe()\nend sub\n")
            with self.assertRaisesRegex(RuntimeError, "RemoteIngest.brs"):
                run_brightscript(script, 'print "RESULT:ok"', root=root)

    def test_cleanup_publishes_drained_or_uncertain_from_io_census(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host = root / "task.brs"
            host.write_text(TASK.read_text() + '''
sub QaRemoteCancel()
end sub
''')
            out = run_brightscript([ROOT / "tools/experiments/onroku_audio/multi_app/source/Rolling.brs", host], '''
rows=[]
for each present in [false,true]
 GetGlobalAA().filePresent=present
 m.clients={}:m.listener=invalid:m.rolling=invalid:m.rollingSession=invalid
 m.audioPaths=["tmp:/owned"]:m.stopObserved=false
 m.fs={Delete:function(path as String) as Boolean
  return not GetGlobalAA().filePresent
 end function,Stat:function(path as String) as Dynamic
  if GetGlobalAA().filePresent then return {size:1}
  return invalid
 end function}
 m.top={stockOnly:true,stockContext:{token:"private"},drainState:"pending",failed:false,ready:false}
 cleanupServer()
 rows.Push({state:m.top.drainState,failed:m.top.failed,context:m.top.stockContext})
end for
print "RESULT:";FormatJson(rows)
''', root=root)
        rows = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual(rows, [
            {"state": "drained", "failed": False, "context": None},
            {"state": "uncertain", "failed": True, "context": None},
        ])

    def test_stock_only_refuses_missing_or_invalid_context_before_fixture_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            out = run_brightscript([REMOTE, DESCRIPTOR, TASK], '''
m.top={stockOnly:true,stockContext:invalid}
rows=[StockEngineContextValid()]
m.top.stockContext={playlist:"http://owned.test/master.m3u8"}
rows.Push(StockEngineContextValid())
m.top.stockContext={origin:"http://owned.test",routeItemId:"r",mediaSourceId:"m",sessionId:"s",token:"secret",controlledNoRedirect:true,fixtureOnly:true,playlist:"http://owned.test/Videos/r/remux-dv-v1/hls/s/stream.m3u8?MediaSourceId=m&PlaySessionId=s"}
rows.Push(StockEngineContextValid())
m.top.stockContext.playlist="http://other.test/Videos/r/remux-dv-v1/hls/s/stream.m3u8?MediaSourceId=m&PlaySessionId=s"
rows.Push(StockEngineContextValid())
print "RESULT:";FormatJson(rows)
''', root=Path(directory))
        rows = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual(rows, [False, False, True, False])

    def test_terminal_drain_requires_no_clients_writers_or_owned_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out = run_brightscript([ROOT / "tools/experiments/onroku_audio/multi_app/source/Rolling.brs", TASK], '''
m.clients={}:m.listener=invalid:m.rolling=invalid:m.rollingSession={generations:[{cancelledIdentity:invalid,pendingCleanup:false,owned:{}}]}:m.audioPaths=[]:m.top={stockContext:invalid}
GetGlobalAA().filePresent=false
m.fs={Stat:function(path as String) as Dynamic
 if GetGlobalAA().filePresent then return {size:1}
 if GetGlobalAA().emptyStat=true then return {}
 return invalid
end function}
rows=[StockEngineDrainComplete()]
m.rollingSession.generations[0].cancelledIdentity=42
rows.Push(StockEngineDrainComplete())
m.rollingSession.generations[0].cancelledIdentity=invalid
m.rollingSession.generations[0].owned["tmp:/x"]=true
GetGlobalAA().filePresent=true
rows.Push(StockEngineDrainComplete())
GetGlobalAA().filePresent=false
rows.Push(StockEngineDrainComplete())
m.top.stockContext={token:"private"}
rows.Push(StockEngineDrainComplete())
m.top.stockContext=invalid
m.rollingSession=invalid
m.rolling={cancelledIdentity:7,pendingCleanup:false,owned:{},stock:{token:""}}
rows.Push(StockEngineDrainComplete())
m.rolling.cancelledIdentity=invalid
m.rolling.stock.token="private"
rows.Push(StockEngineDrainComplete())
m.rolling.stock.token=""
m.rolling.owned["tmp:/held"]=true
GetGlobalAA().filePresent=true
rows.Push(StockEngineDrainComplete())
GetGlobalAA().filePresent=false
GetGlobalAA().emptyStat=true
m.audioPaths=["tmp:/audio"]
rows.Push(StockEngineDrainComplete())
print "RESULT:";FormatJson(rows)
''', root=Path(directory))
        rows = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual(rows, [True, False, False, True, False, False, False, False, True])


if __name__ == "__main__":
    unittest.main()
