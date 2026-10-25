import json
import tempfile
from pathlib import Path
import unittest

from tools.brightscript import run_brightscript


ROOT = Path(__file__).resolve().parents[1]


class SiloEbookTaskTests(unittest.TestCase):
    def test_catalog_only_returns_ebook_libraries_and_epub_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / "boundary.brs"
            stub.write_text('''
function SessionRevision(provider as String) as Integer
 return 7
end function
function TaskError(code as String) as Object
 return {ok:false,errorCode:code}
end function
function HttpRequest(request as Object, timeout as Integer) as Object
 if Instr(1,request.url,"/libraries") > 0 then return {ok:true,body:FormatJson({items:[{id:"movies",name:"Movies",type:"movies"},{id:"books",name:"Books",type:"ebooks"}]})}
 return {ok:true,body:FormatJson({content_id:"ebook:one",type:"ebook",title:"Example",versions:[{file_id:"42",container:"epub"}]})}
end function
''')
            result = run_brightscript([
                ROOT / "source/adapters/SiloAdapter.brs",
                ROOT / "source/adapters/SiloEbookAdapter.brs",
                ROOT / "components/TaskSiloEbook.brs", stub,
            ], '''
    session={baseUrl:"https://fixture.example",accessToken:"secret",profileId:"reader",sourceId:"silo:one"}
    scope={sourceId:"silo:one",profileId:"reader"}
    libraries=TaskEbookAction(session,"ebook_libraries",{},scope,7)
    detail=TaskEbookAction(session,"ebook_detail",{contentId:"ebook:one"},scope,7)
    print FormatJson({libraries:libraries,detail:detail})
''', root=Path(directory))
        decoded = json.loads(result)
        self.assertEqual(decoded["libraries"]["data"]["entries"], [{"id": "books", "title": "Books"}])
        self.assertEqual(decoded["detail"]["data"]["fileId"], "42")

    def test_auth_refresh_cannot_fetch_for_a_different_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / "boundary.brs"
            stub.write_text('''
function SessionRevision(provider as String) as Integer
 return 7
end function
function TaskError(code as String) as Object
 return {ok:false,errorCode:code}
end function
function HttpRequest(request as Object, timeout as Integer) as Object
 m.calls=m.calls+1
 return {ok:false,errorCode:"auth_required"}
end function
function TaskRefreshSilo(session as Object, revision as Integer) as Object
 session.profileId="other"
 return session
end function
''')
            result = run_brightscript([
                ROOT / "source/adapters/SiloAdapter.brs",
                ROOT / "source/adapters/SiloEbookAdapter.brs",
                ROOT / "components/TaskSiloEbook.brs", stub,
            ], '''
    m.calls=0
    session={baseUrl:"https://fixture.example",accessToken:"secret",profileId:"reader",sourceId:"silo:one"}
    scope={sourceId:"silo:one",profileId:"reader"}
    result=TaskEbookAction(session,"ebook_text_page",{contentId:"ebook:one",fileId:"42",pageIndex:0},scope,7)
    print FormatJson({result:result,calls:m.calls})
''', root=Path(directory))
        decoded = json.loads(result)
        self.assertEqual(decoded["result"]["errorCode"], "session_changed")
        self.assertEqual(decoded["calls"], 1)

    def test_page_fetch_is_profile_fenced_and_projects_authorized_response(self):
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / "boundary.brs"
            stub.write_text('''
function SessionRevision(provider as String) as Integer
 return 7
end function
function TaskError(code as String) as Object
 return {ok:false,errorCode:code}
end function
function HttpRequest(request as Object, timeout as Integer) as Object
 m.calls=m.calls+1
 return {ok:true,body:FormatJson({revision:m.revision,location:"silo-text-v1:"+m.revision+":0:2048",text:"Page two",page_index:1,total_pages:2,previous_page:0,next_page:invalid})}
end function
''')
            result = run_brightscript([
                ROOT / "source/adapters/SiloAdapter.brs",
                ROOT / "source/adapters/SiloEbookAdapter.brs",
                ROOT / "components/TaskSiloEbook.brs", stub,
            ], '''
    m.calls=0:m.revision=String(64,"a")
    session={baseUrl:"https://fixture.example",accessToken:"secret",profileId:"reader",sourceId:"silo:one"}
    params={contentId:"ebook:one",fileId:"42",pageIndex:1}
    denied=TaskEbookAction(session,"ebook_text_page",params,{sourceId:"silo:one",profileId:"other"},7)
    allowed=TaskEbookAction(session,"ebook_text_page",params,{sourceId:"silo:one",profileId:"reader"},7)
    print FormatJson({denied:denied,allowed:allowed,calls:m.calls})
''', root=Path(directory))
        decoded = json.loads(result)
        self.assertEqual(decoded["calls"], 1)
        self.assertEqual(decoded["denied"]["errorCode"], "session_changed")
        self.assertEqual(decoded["allowed"]["data"]["text"], "Page two")


if __name__ == "__main__":
    unittest.main()
