"""Bound stock credentials on the experimental rolling request seam."""
from pathlib import Path
import json
import tempfile
import unittest

from tools.brightscript import run_brightscript


SOURCE = Path(__file__).resolve().parents[1] / "tools/experiments/onroku_audio/multi_app/source"


class StockAuth(unittest.TestCase):
    def test_mode_validation_and_exact_header(self):
        out = run_brightscript(SOURCE / "StockDescriptor.brs", '''
c={origin:"http://owned.test",routeItemId:"r",mediaSourceId:"m",sessionId:"s",token:"secret",controlledNoRedirect:true,fixtureOnly:true}
rows=[{valid:QaStockContextValid(c),header:QaStockAuthHeader(c)}]
for each mode in ["emby","bearer","other",true,12,invalid]
 c.authMode=mode
 rows.Push({valid:QaStockContextValid(c),header:QaStockAuthHeader(c)})
end for
print "RESULT:";FormatJson(rows)
''')
        rows = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual([
            {"valid": True, "header": {"name": "X-Emby-Token", "value": "secret"}},
            {"valid": True, "header": {"name": "X-Emby-Token", "value": "secret"}},
            {"valid": True, "header": {"name": "Authorization", "value": "Bearer secret"}},
            {"valid": False, "header": None},
            {"valid": False, "header": None},
            {"valid": False, "header": None},
            {"valid": False, "header": None},
        ], rows)

    def test_rejected_header_never_launches_and_context_wipes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rolling.brs"
            path.write_text((SOURCE / "Rolling.brs").read_text() + '''
function QaRemoteTransfer() as Object
 return {SetMessagePort:sub(port as Dynamic)
 end sub,SetUrl:sub(url as String)
 end sub,RetainBodyOnError:sub(retain as Boolean)
 end sub,AddHeader:function(name as String,value as String) as Boolean
  GetGlobalAA().headers.Push({name:name,value:value})
  return GetGlobalAA().acceptHeader
 end function,AsyncGetToFile:function(path as String) as Boolean
  GetGlobalAA().launched=true
  return true
 end function}
end function
function QaRemoteReference(base as String, reference as String) as Dynamic
 return reference.Split("?")[0]
end function
function QaRemoteTimer() as Dynamic
 return invalid
end function
''')
            out = run_brightscript([SOURCE / "StockDescriptor.brs", path], '''
g=GetGlobalAA():g.headers=[]:g.acceptHeader=false:g.launched=false
m.upstreamPort=invalid:m.top={stockContext:invalid}
rows=[]
for each mode in ["default","bearer","reject"]
 g.headers=[]:g.launched=false:g.acceptHeader=mode<>"reject"
 c={origin:"http://owned.test",routeItemId:"r",mediaSourceId:"m",sessionId:"s",token:"secret",controlledNoRedirect:true,fixtureOnly:true}
 if mode<>"default" then c.authMode="bearer"
 base=c.origin+"/Videos/r/remux-dv-v1/hls/s/stream.m3u8?MediaSourceId=m&PlaySessionId=s"
 r=QaRollingState(base):r.stock=c
 ok=QaRollingBegin(r,base,"tmp:/source",1024#)
 headers=g.headers
 launched=g.launched
 owned=r.owned.Count()
 transfer=r.transfer=invalid
 QaRollingClearContext(r)
 rows.Push({ok:ok,headers:headers,launched:launched,owned:owned,transfer:transfer,token:c.token})
end for
print "RESULT:";FormatJson(rows)
''', root=Path(directory))
        rows = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        self.assertEqual([
            {"ok": True, "headers": [{"name": "X-Emby-Token", "value": "secret"}], "launched": True, "owned": 2, "transfer": False, "token": ""},
            {"ok": True, "headers": [{"name": "Authorization", "value": "Bearer secret"}], "launched": True, "owned": 2, "transfer": False, "token": ""},
            {"ok": False, "headers": [{"name": "Authorization", "value": "Bearer secret"}], "launched": False, "owned": 0, "transfer": True, "token": ""},
        ], rows)
