"""Native Silo JSON encoding negotiation at the shipping HTTP boundary."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]

NATIVE = '''
function FixtureTransfer()
 return {state:m.native,
 SetMessagePort:sub(port)
 end sub,
 SetUrl:sub(url)
  m.state.url=url
 end sub,
 RetainBodyOnError:sub(value)
  m.state.retain=value
 end sub,
 SetCertificatesFile:sub(path)
 end sub,
 EnablePeerVerification:sub(value)
 end sub,
 EnableHostVerification:sub(value)
 end sub,
 EnableEncodings:function(value)
  m.state.encodings.Push(value)
  return m.state.encodingOk
 end function,
 AddHeader:sub(name,value)
  m.state.headers[name]=value
 end sub,
 AsyncGetToString:function()
  m.state.starts++
  return true
 end function,
 AsyncPostFromString:function(body)
  m.state.starts++
  return true
 end function,
 SetRequest:sub(method)
 end sub,
 GetIdentity:function()
  return 7
 end function,
 AsyncCancel:sub()
  m.state.cancels++
 end sub}
end function
function FixtureClock()
 return {state:m.native,Mark:sub()
 end sub,TotalMilliseconds:function()
 return m.state.elapsed
 end function}
end function
function FixtureType(value)
 if Type(value)="roAssociativeArray"
  if value.DoesExist("fixtureEvent") then return "roUrlEvent"
 end if
 return Type(value)
end function
function FixtureWait(milliseconds,port)
 m.native.elapsed+=milliseconds
 if m.events.Count()=0 then return invalid
 event=m.events.Shift()
 return {fixtureEvent:true,status:event.status,body:event.body,headers:event.headers,
 GetSourceIdentity:function()
  return 7
 end function,
 GetResponseCode:function()
  return m.status
 end function,
 GetString:function()
  return m.body
 end function,
 GetResponseHeadersArray:function()
  return m.headers
 end function}
end function
'''

class HttpGzipTests(unittest.TestCase):
    def call(self, body, native_source=NATIVE):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            source=(ROOT/'source/network/Http.brs').read_text()
            source=source.replace('CreateObject("roUrlTransfer")','FixtureTransfer()')
            source=source.replace('CreateObject("roMessagePort")','{}')
            source=source.replace('CreateObject("roTimespan")','FixtureClock()')
            source=source.replace('event = wait(250, port)','event = FixtureWait(250, port)')
            source=source.replace('type(event) = "roUrlEvent"','FixtureType(event) = "roUrlEvent"')
            http=root/'http.brs';http.write_text(source)
            native=root/'native.brs';native.write_text(native_source)
            runner=root/'runner.brs'
            runner.write_text('function RunHttpFixture() as Object\n'+'''
                m.native={encodings:[],encodingOk:true,headers:{},starts:0,cancels:0,elapsed:0}
                m.events=[{status:200,body:"{}",headers:[]}]
                session={baseUrl:"https://fixture.example",accessToken:"synthetic",profileId:"p"}
                request=BuildSiloRequest("home",session,{})
            '''+body.replace('print FormatJson(', 'return (')+'\nend function')
            return run_function([ROOT/'source/adapters/SiloAdapter.brs',http,native,runner], 'RunHttpFixture', [], root=root)

    def test_silo_json_uses_native_decoding_without_manual_encoding_headers(self):
        r=self.call('''
            result=HttpRequest(request)
            print FormatJson({native:m.native,result:result})
        ''')
        self.assertEqual(r['native']['encodings'],[True])
        self.assertEqual(r['native']['starts'],1)
        self.assertNotIn('Accept-Encoding',r['native']['headers'])
        self.assertEqual(r['result'],{'ok':True,'statusCode':200,'body':'{}'})

    def test_explicit_encoding_ranges_etags_and_non_json_requests_remain_plain(self):
        r=self.call('''
            results=[]
            for each changes in [{headers:{Accept:"application/json","aCcEpT-EnCoDiNg":"identity"}},{headers:{Accept:"application/json",rAnGe:"bytes=0-5"}},{headers:{Accept:"image/jpeg"}},{headers:{Accept:"application/json","If-None-Match":Chr(34)+"rev"+Chr(34)}},{captureETag:true},{enableGzip:false},{enableGzip:"true"},{headers:{}},{method:"HEAD"}]
                nextRequest={}
                for each key in request
                    nextRequest[key]=request[key]
                end for
                for each key in changes
                    nextRequest[key]=changes[key]
                end for
                m.native.encodings=[]:m.native.elapsed=0
                m.events=[{status:200,body:"{}",headers:[]}]
                result=HttpRequest(nextRequest)
                results.Push(m.native.encodings)
            end for
            print FormatJson(results)
        ''')
        self.assertEqual(r,[[]]*9)

    def test_optional_native_setup_failure_keeps_plain_post_without_retry(self):
        r=self.call('''
            request.method="POST":request.body="{}"
            m.native.encodingOk=false
            result=HttpRequest(request)
            print FormatJson({result:result,native:m.native})
        ''')
        self.assertTrue(r['result']['ok'])
        self.assertEqual(r['result']['body'],'{}')
        self.assertEqual(r['native']['starts'],1)
        self.assertEqual(r['native']['encodings'],[True])
        self.assertNotIn('Accept-Encoding',r['native']['headers'])

    def test_auth_error_body_etag_and_timeout_contracts_survive_negotiation(self):
        r=self.call('''
            m.events=[{status:401,body:"{}",headers:[]}]
            auth=HttpRequest(request)
            m.native.elapsed=0
            m.events=[{status:200,body:"{}",headers:[{ETag:Chr(34)+"rev"+Chr(34)}]}]
            request.captureETag=true
            etag=HttpRequest(request)
            m.native.elapsed=0:m.events=[]
            timeout=HttpRequest(request,1000)
            print FormatJson({auth:auth,etag:etag,timeout:timeout,native:m.native})
        ''')
        self.assertEqual(r['auth'],{'ok':False,'statusCode':401,'errorCode':'auth_required','body':'{}'})
        self.assertEqual(r['etag'],{'ok':True,'statusCode':200,'body':'{}','etag':'"rev"'})
        self.assertEqual(r['timeout'],{'ok':False,'errorCode':'network_timeout'})
        self.assertEqual(r['native']['cancels'],1)
        self.assertEqual(r['native']['starts'],3)
        self.assertEqual(r['native']['encodings'],[True])
        self.assertTrue(r['native']['retain'])

    def test_non_opted_in_json_or_media_probe_keeps_its_existing_wire_behavior(self):
        r=self.call('''
            request.Delete("enableGzip")
            request.headers.Range="bytes=0-31"
            m.events=[{status:206,body:"probe",headers:[]}]
            result=HttpRequest(request)
            print FormatJson({result:result,native:m.native})
        ''')
        self.assertEqual(r['native']['encodings'],[])
        self.assertEqual({k.lower():v for k,v in r['native']['headers'].items()}['range'],'bytes=0-31')
        self.assertEqual(r['result'],{'ok':True,'statusCode':206,'body':'probe'})

    def test_required_tls_setup_failure_never_launches_or_attaches_bearer(self):
        for failed in ('SetCertificatesFile','EnablePeerVerification','EnableHostVerification'):
            native = NATIVE
            for name, argument in (('SetCertificatesFile','path'),('EnablePeerVerification','value'),('EnableHostVerification','value')):
                native = native.replace(name+':sub('+argument+')\n end sub',name+':function('+argument+')\n return '+('false' if name == failed else 'true')+'\n end function')
            with self.subTest(failed=failed):
                result=self.call('''
request={ok:true,url:"https://owned.test/master.m3u8",method:"GET",headers:{Authorization:"Bearer synthetic"},requireVerifiedTls:true}
result=HttpRequest(request)
print FormatJson({result:result,starts:m.native.starts,headers:m.native.headers})
''',native)
                self.assertEqual({'ok':False,'errorCode':'tls_setup_failed'},result['result'])
                self.assertEqual(0,result['starts'])
                self.assertEqual({},result['headers'])
