"""Scrub worker binds authenticated manifest reads to the captured file/session."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]

class TrickplayTaskTests(unittest.TestCase):
    def flow(self, body, scripted=False):
        with tempfile.TemporaryDirectory() as tmp:
            worker=ROOT/'components/SiloUITrickplayTask.brs'
            if scripted:
                source=worker.read_text()
                for name in ['TrickplayNow','TrickplayDownload','TrickplayInspect']:
                    source=source.replace('function '+name+'(', 'function Unused'+name+'(',1)
                source=source.replace('sub TrickplayDelete(', 'sub UnusedTrickplayDelete(',1)
                worker=Path(tmp)/'task.brs';worker.write_text(source)
            boundary=Path(tmp)/'boundary.brs'
            boundary.write_text('''function LoadSession(provider as String) as Object
return m.session
end function
function SessionRevision(provider as String) as Integer
return m.revision
end function
function HttpRequest(request as Object, timeoutMs as Integer) as Object
m.calls.Push(request)
if m.responses <> invalid then return m.responses.Shift()
return {ok:false,statusCode:404}
end function'''+('''
function TrickplayNow() as Double
return 1893450000
end function
function TrickplayDownload(url as String) as Integer
m.downloads.Push(url)
return 403
end function
function TrickplayInspect(manifest as Object) as Boolean
return true
end function
sub TrickplayDelete()
m.tpPath=""
end sub
''' if scripted else ''))
            return json.loads(run_brightscript([worker,ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/core/ServerUrlPolicy.brs',ROOT/'source/core/ArtworkPolicy.brs',ROOT/'source/core/SiloUITrickplayPolicy.brs',boundary],'''
            m.revision=7:m.calls=[]
            m.session={baseUrl:"https://media.example",sourceId:"silo:one",profileId:"profile",accessToken:"fixture-access",profileToken:"fixture-profile"}
            m.top={cancelled:false,job:{sourceId:"silo:one",profileId:"profile",sessionRevision:7,itemId:"movie:one",fileId:"42",sequence:1}}
            '''+body,root=Path(tmp)))

    def test_missing_previews_fall_back_after_one_exact_scoped_request(self):
        actual=self.flow('''TrickplayRun()
        print FormatJson({calls:m.calls,result:m.top.result,session:m.tpSession,path:m.tpPath})''')
        self.assertEqual(1,len(actual['calls']))
        request=actual['calls'][0]
        self.assertEqual('https://media.example/api/v2/watch/movie%3Aone/trickplay?file_id=42',request['url'])
        self.assertEqual('Bearer fixture-access',request['headers']['Authorization'])
        self.assertEqual('fixture-profile',request['headers']['X-Profile-Token'])
        self.assertEqual(65536,request['responsebodylimit'])
        self.assertEqual(({},None,''),(actual['result'],actual['session'],actual['path']))

    def test_changed_session_revision_or_profile_performs_no_request(self):
        for change in ['m.revision=8','m.session.profileId="other"','m.top.cancelled=true']:
            actual=self.flow(change+'''\nTrickplayRun()
            print FormatJson({calls:m.calls,result:m.top.result})''')
            self.assertEqual(dict(calls=[],result={}),actual)

    def test_expired_signatures_refresh_once_then_fall_back(self):
        from tests.test_silo_ui_trickplay import TrickplayTests
        raw=json.dumps(TrickplayTests().manifest()).replace('"','""')
        actual=self.flow('m.responses=[{ok:true,body:"'+raw+'"},{ok:true,body:"'+raw+'"}]:m.downloads=[]:m.top.targetMs=10000\nTrickplayRun()\nprint FormatJson({calls:m.calls.Count(),downloads:m.downloads.Count(),result:m.top.result,path:m.tpPath})',scripted=True)
        self.assertEqual(dict(calls=2,downloads=2,result={},path=''),actual)
