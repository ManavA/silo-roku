"""Exact native bearer transport qualification, independent of playback eligibility."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]

class NativeBearerTransportTests(unittest.TestCase):
    def test_only_evidenced_identity_and_https_initial_origin_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / 'sdk.brs'
            stub.write_text('''
function NativeFixture(origin as String, model as String, build as Dynamic, major as String) as Boolean
 d={GetModelDetails:function() as Object
 return GetGlobalAA().details
 end function,GetOSVersion:function() as Object
 return GetGlobalAA().os
 end function}
 GetGlobalAA().details={ModelNumber:model}
 GetGlobalAA().os={major:major,minor:"0",revision:"4",build:build}
 return SiloNativeBearerTransportQualified(origin,d)
end function
''')
            cases = [(['https://owned.test','C208X','842','16'],True),
                     (['http://owned.test','C208X','842','16'],False),
                     (['https://owned.test/path','C208X','842','16'],False),
                     (['https://owned.test','C209X','842','16'],False),
                     (['https://owned.test','C208X','843','16'],False),
                     (['https://owned.test','C208X',842,'16'],True),
                     (['https://owned.test','C208X','842','17'],False)]
            for args, expected in cases:
                with self.subTest(args=args):
                    self.assertEqual(expected, run_function([ROOT/'source/core/SiloNativeBearerTransport.brs',stub], 'NativeFixture',args))

    def test_holder_and_engine_recheck_same_policy_and_do_not_qualify_emby(self):
        import re
        from tools.brightscript import run_brightscript
        import json
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            holder = re.search(r'function CompatStockTransportQualified\(.*?end function',
                               (ROOT/'components/SiloCompatTask.brs').read_text(),re.S)[0]
            engine = (ROOT/'tools/experiments/onroku_audio/multi_app/source/StockDescriptor.brs').read_text()
            script = folder/'transport.brs'
            script.write_text((holder+'\n'+engine).replace('CreateObject("roDeviceInfo")','NativeDevice()')+'''
function NativeDevice() as Object
 return {GetModelDetails:function() as Object
 return {ModelNumber:"C208X"}
 end function,GetOSVersion:function() as Object
 return {major:16,minor:0,revision:4,build:GetGlobalAA().firmwareBuild}
 end function}
end function
''')
            out=run_brightscript([ROOT/'source/core/SiloNativeBearerTransport.brs',script],'''
GetGlobalAA().firmwareBuild=842
c={origin:"https://owned.test",routeItemId:"r",mediaSourceId:"m",sessionId:"s",token:"secret",authMode:"bearer",transportPolicy:"native-bearer-origin-scope-v1",transportEvidence:"c208x-16.0.4-842-redirect-chains-v1"}
rows=[CompatStockTransportQualified(c.origin),QaStockContextValid(c),QaStockAuthHeader(c)]
c.authMode="emby":rows.Push(QaStockContextValid(c)):rows.Push(QaStockAuthHeader(c))
c.authMode="bearer":GetGlobalAA().firmwareBuild=843
rows.Push(CompatStockTransportQualified(c.origin)):rows.Push(QaStockContextValid(c))
GetGlobalAA().firmwareBuild=842:c.Delete("transportPolicy"):c.controlledNoRedirect=true
rows.Push(QaStockContextValid(c))
c.Delete("transportEvidence"):rows.Push(QaStockContextValid(c))
print "RESULT:";FormatJson(rows)
''')
            rows=json.loads(next(line[7:] for line in out.splitlines() if line.startswith('RESULT:')))
            self.assertEqual([True,True,{'name':'Authorization','value':'Bearer secret'},False,None,False,False,False,False],rows)
