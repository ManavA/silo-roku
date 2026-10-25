"""Dedicated native HTTP facade honors the captured deadline, not Http's floor."""
from pathlib import Path
import re
import sys
import tempfile
import unittest

C=Path(__file__).resolve().parents[1]
ROOT=C if (C/'tools/brightscript.py').exists() else Path.cwd()
sys.path.insert(0,str(ROOT))
from tools.brightscript import run_function
NOW=1792000000123

FACADE='''
function DecisionNowMs() as Double
 return m.fixtureNow
end function
function DecisionGatewayTransfer() as Object
 return {native:m.native,
  SetMessagePort:sub(port as Object)
  end sub,
  SetUrl:sub(url as String)
   m.native.url=url
  end sub,
  SetCertificatesFile:sub(path as String)
   m.native.certificates=path
  end sub,
  EnablePeerVerification:sub(value as Boolean)
   m.native.peer=value
  end sub,
  EnableHostVerification:sub(value as Boolean)
   m.native.host=value
  end sub,
  RetainBodyOnError:sub(value as Boolean)
   m.native.retain=value
  end sub,
  AddHeader:sub(name as String,value as String)
   m.native.headers[name]=value
  end sub,
  AsyncPostFromString:function(body as String) as Boolean
   m.native.body=body
   m.native.started++
   return m.native.startOk
  end function,
  GetIdentity:function() as Integer
   return 7
  end function,
  AsyncCancel:sub()
   m.native.cancels++
  end sub}
end function
function DecisionGatewayPort() as Object
 return {}
end function
function FixtureDecisionTimer() as Object
 return {clock:m,startedAt:m.fixtureNow,
  Mark:sub()
   m.startedAt=m.clock.fixtureNow
  end sub,
  TotalMilliseconds:function() as Integer
   return Int(m.clock.fixtureNow-m.startedAt)
  end function}
end function
function FixtureDecisionType(value as Dynamic) as String
 if Type(value)="roAssociativeArray"
  if value.DoesExist("fixtureEvent") then return "roUrlEvent"
 end if
 return Type(value)
end function
function DecisionGatewayWait(milliseconds as Integer,port as Object) as Dynamic
 m.waits.Push(milliseconds)
 m.fixtureNow+=milliseconds
 if m.events.Count()=0 then return invalid
 raw=m.events.Shift()
 if raw=invalid then return invalid
 return {fixtureEvent:true,source:raw.source,status:raw.status,body:raw.body,
  GetSourceIdentity:function() as Integer
   return m.source
  end function,
  GetResponseCode:function() as Integer
   return m.status
  end function,
  GetString:function() as String
   return m.body
  end function}
end function
function RunDecisionTransport(nowMs as Double,deadlineMs as Double,events as Object,changes as Object) as Object
 m.fixtureNow=nowMs:m.events=events:m.waits=[]
 m.native={headers:{},body:"",url:"",certificates:"",peer:false,host:false,retain:true,started:0,cancels:0,startOk:true}
 request=BuildDecisionGatewayRequest("decide","https://gateway.example.test","synthetic-install",{daypart:"late",weekend:false,device:"tv",session:{minutes:140,episodes_in_row:3}})
 for each key in changes
  request[key]=changes[key]
 end for
 result=DecisionGatewayHttpRequest(request,deadlineMs)
 return {result:result,native:m.native,waits:m.waits,nowMs:m.fixtureNow}
end function
'''

class DecisionGatewayTransportTests(unittest.TestCase):
    def call(self,now=NOW,deadline=NOW+800,events=None,changes=None):
        helper=C/'components/TaskDecisionGateway.brs'
        self.assertTrue(helper.exists(),'dedicated gateway transport is missing')
        if events is None:events=[]
        with tempfile.TemporaryDirectory(prefix='silo_ui-decision-transport-') as d:
            p=Path(d);worker=p/'helper.brs';source=helper.read_text()
            for name in ('DecisionGatewayTransfer','DecisionGatewayPort','DecisionGatewayWait'):
                source=source.replace('function '+name+'(','function Unused'+name+'(',1)
            source=source.replace('type(','FixtureDecisionType(')
            source=source.replace('CreateObject("roTimespan")','FixtureDecisionTimer()')
            worker.write_text(source)
            adapter=p/'adapter.brs';adapter.write_text((C/'source/adapters/DecisionGatewayAdapter.brs').read_text().replace('function DecisionNowMs(','function UnusedDecisionNowMs(',1))
            facade=p/'facade.brs';facade.write_text(FACADE)
            http=p/'http.brs';raw=(ROOT/'source/network/Http.brs').read_text()
            names=('HttpErrorCode','HttpErrorBodyLimit','HttpErrorBodyWithinLimit','HttpResponseBodyLimit','HttpResponseBody')
            http.write_text('\n'.join(re.search(r'(?ms)^function '+n+r'\(.*?^end function',raw).group(0) for n in names))
            files=[ROOT/'source/core/ServerUrlPolicy.brs',C/'source/core/DecisionPreference.brs',adapter,worker,http,facade]
            return run_function(files,'RunDecisionTransport',[now,deadline,events,changes or {}],root=p)

    def test_native_wait_uses_only_remaining_subsecond_budget_and_cancels(self):
        v=self.call(now=NOW+700)
        self.assertFalse(v['result']['ok']);self.assertEqual(NOW+800,v['nowMs'])
        self.assertEqual([100],v['waits']);self.assertEqual(1,v['native']['cancels'])
        v=self.call()
        self.assertEqual(800,sum(v['waits']));self.assertLessEqual(max(v['waits']),100)
        self.assertEqual('common:/certs/ca-bundle.crt',v['native']['certificates'])
        self.assertTrue(v['native']['peer']);self.assertTrue(v['native']['host']);self.assertFalse(v['native']['retain'])

    def test_expired_or_extended_deadline_does_not_start_native_http(self):
        for now,deadline in ((NOW+800,NOW+800),(NOW,NOW+801)):
            v=self.call(now=now,deadline=deadline)
            self.assertFalse(v['result']['ok']);self.assertEqual(0,v['native']['started'])

    def test_only_matching_event_completes_and_late_success_is_discarded(self):
        event={'source':7,'status':200,'body':'{"answers":{"still_watching":{"type":"noul","noul":0.2}}}'}
        v=self.call(events=[{**event,'source':8},event])
        self.assertTrue(v['result']['ok']);self.assertEqual(2,len(v['waits']))
        v=self.call(now=NOW+700,events=[event])
        self.assertFalse(v['result']['ok']);self.assertEqual(1,v['native']['cancels'])

    def test_native_transport_does_not_forward_provider_headers_or_oversized_body(self):
        v=self.call(changes={'headers':{'Accept':'application/json','Content-Type':'application/json','X-Plex-Token':'synthetic-provider'}})
        self.assertFalse(v['result']['ok']);self.assertEqual(0,v['native']['started'])
        v=self.call(events=[{'source':7,'status':200,'body':'é'*4097}])
        self.assertFalse(v['result']['ok'])
        v=self.call(changes={'body':'x'*4097})
        self.assertFalse(v['result']['ok']);self.assertEqual(0,v['native']['started'])

if __name__=='__main__':unittest.main()
