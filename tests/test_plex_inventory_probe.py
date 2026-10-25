"""Diagnostic inventory reads never acknowledge Plex cleanup or reveal values."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlsplit
from tools.brightscript import ROOT,run_function
BASE=Path(os.environ.get('SILO_PLEX_PROBE_ROOT',str(ROOT)))
TASK=BASE/'components/ApiTask.brs';ADAPTER=BASE/'source/adapters/PlexAdapter.brs';HTTP=BASE/'source/network/Http.brs'
SCOPE={'provider':'plex','sourceId':'plex:fixture','profileId':'owner','generation':7}
OWNER={'scope':SCOPE,'attemptId':'app-1','versionId':'plex:fixture:1:2:3','transcodeSessionId':'fixture-session','clipId':4,'sessionRevision':2}
SESSION={'clientId':'fixture-client','sourceId':'plex:fixture','profileId':'owner','accountId':'fixture-account','baseUrl':'https://server.example.test','token':'synthetic-server-token','local':False}
HELPERS='''
function TaskDeviceSession(provider as String,session as Object) as Object
    return session
end function
function LoadSession(provider as String) as Object
    return m.fixtureSession
end function
function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function
function HttpRequest(request as Object,timeoutMs=9000 as Integer) as Object
    m.requests.Push(request)
    m.timeouts.Push(timeoutMs)
    response = m.responses.Shift()
    if m.changeRevision then m.fixtureRevision++
    if m.changeProfile then m.fixtureSession["profileId"] = "other"
    if type(m.afterPatch) = "roAssociativeArray"
        for each key in m.afterPatch
            m.fixtureSession[key] = m.afterPatch[key]
        end for
    end if
    return HttpResponse(request,response.statusCode,response.body,response.headers)
end function
function ProbeFixture(job as Object,session as Object,responses as Object,changeRevision as Boolean,changeProfile as Boolean,afterPatch=invalid as Dynamic) as Object
    m.fixtureSession = session
    m.fixtureRevision = 2
    m.responses = responses
    m.requests = []
    m.timeouts = []
    m.changeRevision = changeRevision
    m.changeProfile = changeProfile
    m.afterPatch = afterPatch
    m.top = {job:job,result:invalid}
    runJob()
    return {outcome:m.top.result,requests:m.requests,timeouts:m.timeouts}
end function
function ShapesFixture(responses as Object) as Object
    results = []
    for each response in responses
        results.Push(TaskPlexInventoryDiagnostic(response,"fixture-session","rendered",true))
    end for
    return results
end function
function HeaderFixture(request as Object,headers as Dynamic) as Object
    return HttpResponse(request,200,"{}",headers)
end function
function NativeProbeType(value as Dynamic) as String
    kind = type(value)
    if kind = "Integer" or kind = "roInt" then return m.nativeAlias
    return kind
end function
function NativeShapesFixture(responses as Object) as Object
    output = []
    for each alias in ["roInteger","roLongInteger"]
        m.nativeAlias = alias
        output.Push(ShapesFixture(responses))
    end for
    return output
end function
'''
def response(body,status=200,headers=None):
    return {'statusCode':status,'body':json.dumps(body) if not isinstance(body,str) else body,'headers':headers or []}
def canonical(rows,size=None,total=None,offset=0):
    data={'size':len(rows) if size is None else size,'offset':offset,'TranscodeSession':rows}
    if total is not None:data['totalSize']=total
    return {'MediaContainer':data}
class PlexInventoryProbeTests(unittest.TestCase):
    def call(self,name,args,native=False):
        with tempfile.TemporaryDirectory(prefix='silo-plex-probe-fixture-') as d:
            p=Path(d);files=[]
            for original in (TASK,ADAPTER,HTTP):
                target=p/original.name;source=original.read_text()
                if original==TASK:source=source.replace('function TaskDeviceSession(','function UnusedTaskDeviceSession(',1)
                if original==HTTP:source=source.replace('function HttpRequest(','function UnusedHttpRequest(',1)
                if native:source=re.sub(r'\btype\s*\(','NativeProbeType(',source,flags=re.I)
                target.write_text(source);files.append(target)
            helper=p/'boundaries.brs';helper.write_text(HELPERS)
            return run_function([ROOT/'source/auth/SessionPolicy.brs',BASE/'components/TaskSiloReplan.brs',*files,helper],name,args,root=p)
    def probe(self,responses,*,params=None,owner=None,scope=None,provider='plex',change_revision=False,change_profile=False,action='transcode_probe'):
        job={**(scope or SCOPE),'provider':provider,'action':action,'requestId':'probe-1',
             'params':params or {'transcodeSessionId':'fixture-session','sessionRevision':2,'stage':'rendered'},
             'inventoryOwner':OWNER if owner is None else owner}
        return self.call('ProbeFixture',[job,SESSION,responses,change_revision,change_profile])
    def test_scoped_explicit_action_reads_once_with_private_headers_and_bounds(self):
        result=self.probe([response(canonical([{'key':'fixture-session','id':'fixture-session'}],total=1))])
        self.assertTrue(result['outcome']['ok'])
        self.assertEqual(1,len(result['requests']))
        req=result['requests'][0]
        self.assertEqual('/transcode/sessions',urlsplit(req['url']).path)
        self.assertEqual('',urlsplit(req['url']).query)
        self.assertEqual(('GET',32768,True),(req['method'],req['responseBodyLimit'],req['capturePlexContainerHeaders']))
        self.assertEqual('synthetic-server-token',req['headers']['X-Plex-Token'])
        self.assertEqual([2000],result['timeouts'])
        diag=result['outcome']['inventoryDiagnostic']
        self.assertTrue(diag['expectedIdMatch']);self.assertTrue(diag['expectedKeyMatch'])
        self.assertTrue(diag['fullnessKnown']);self.assertFalse(diag['absenceTrusted'])
        public=json.dumps(result['outcome'])
        for value in ('fixture-session','private-title','synthetic-server-token','server.example.test','plex:fixture:1:2:3'):self.assertNotIn(value,public)
        self.assertNotIn('plan',result['outcome']);self.assertNotIn('data',result['outcome'])
    def test_canonical_complete_empty_response_remains_diagnostic_only(self):
        result=self.probe([response(canonical([],total=0))])
        diag=result['outcome']['inventoryDiagnostic']
        self.assertEqual((0,True,False,False),(diag['recordsCount'],diag['fullnessKnown'],diag['expectedIdMatch'],diag['absenceTrusted']))
        self.assertNotIn('saved',json.dumps(result['outcome']))
    def test_private_or_unknown_schema_names_values_and_identity_paths_are_not_exposed(self):
        bodies=[{'private-token-key':'secret','MediaContainer':{'size':1,'totalSize':1,'offset':0,'TranscodeSession':[{'key':'/transcode/sessions/fixture-session','token':'private-token','url':'https://private.test','title':'private-title'}]}},
                canonical([{'key':'https://private.test/transcode/sessions/fixture-session?token=private-token','id':'fixture-session-other'}],total=1),
                {'MediaContainer':{'size':0,'totalSize':0,'offset':0,'Metadata':[{'title':'private-title'}]}}]
        result=self.call('ShapesFixture',[[{'ok':True,**response(body)} for body in bodies]])
        public=json.dumps(result)
        for value in ('private-token-key','private-token','private-title','private.test','fixture-session'):self.assertNotIn(value,public)
        self.assertTrue(result[0]['expectedKeyMatch'])
        self.assertFalse(result[1]['expectedKeyMatch'])
        self.assertTrue(all(not x['absenceTrusted'] for x in result))
    def test_partial_conflicting_alias_and_oversized_shapes_fail_closed(self):
        cases=[canonical([],total=2),canonical([],total=0,offset=1),canonical([{'key':'fixture-session'}],size=0,total=0),
               canonical([{'key':'fixture-session','KEY':'other'}],total=1),
               canonical([{'id':'fixture-session','key':'different'}],total=1),
               {'MediaContainer':{'size':'0','totalSize':0,'offset':0,'TranscodeSession':[]}},
               canonical([{'key':str(i)} for i in range(65)],total=65),'{', '<MediaContainer size="0"/>','x'*32769]
        results=self.call('ShapesFixture',[[{'ok':True,**response(body)} for body in cases]])
        self.assertTrue(all(not d['fullnessKnown'] or not d['completeShape'] for d in results))
        self.assertTrue(all(not d['absenceTrusted'] for d in results))
        self.assertEqual(('invalid_json','xml','body_budget'),tuple(d['format'] for d in results[-3:]))
    def test_scope_revision_owner_and_provider_mismatches_make_no_read(self):
        cases=[{'params':{'transcodeSessionId':'fixture-session','sessionRevision':1,'stage':'rendered'}},
               {'params':{'transcodeSessionId':'fixture-session','sessionRevision':2,'stage':'other'}},
               {'owner':{**OWNER,'transcodeSessionId':'other'}},
               {'owner':{**OWNER,'scope':{**SCOPE,'generation':8}}},
               {'scope':{**SCOPE,'profileId':'other'}}, {'provider':'silo'}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                result=self.probe([],**kwargs)
                self.assertFalse(result['outcome']['ok']);self.assertEqual([],result['requests'])
    def test_changes_during_read_discard_identity_and_fullness_flags(self):
        for changes in ({'change_revision':True},{'change_profile':True}):
            result=self.probe([response(canonical([{'key':'fixture-session'}],total=1))],**changes)
            self.assertEqual('session_changed',result['outcome']['errorCode'])
            diag=result['outcome']['inventoryDiagnostic']
            self.assertFalse(diag['scopeValid']);self.assertFalse(diag['expectedKeyMatch']);self.assertFalse(diag['fullnessKnown'])
    def test_stop_404_probe_preserves_the_original_required_failure(self):
        params={'itemId':'1','sessionId':'fixture-session','transcodeSessionId':'fixture-session','positionMs':12000,'durationMs':100000,'state':'stopped'}
        job={**SCOPE,'requestId':'stop-1','action':'playback_stop','params':params,'inventoryProbeOwner':OWNER}
        result=self.call('ProbeFixture',[job,SESSION,[response({},200),response('',404),response(canonical([],total=0))],False,False])
        out=result['outcome']
        self.assertEqual((False,'not_found',404,'transcode_stop'),(out['ok'],out['errorCode'],out['statusCode'],out['deliveryPhase']))
        self.assertFalse(out['inventoryDiagnostic']['absenceTrusted'])
        self.assertEqual(['/:/timeline','/video/:/transcode/universal/stop','/transcode/sessions'],[urlsplit(r['url']).path for r in result['requests']])
        self.assertEqual([5000,5000,2000],result['timeouts'])
        job['params']={**params,'persistProgress':False}
        result=self.call('ProbeFixture',[job,SESSION,[response('',404),response(canonical([],total=0))],False,False])
        self.assertFalse(result['outcome']['ok']);self.assertEqual(2,len(result['requests']))
    def test_timeline_failure_and_missing_owner_do_not_become_success(self):
        params={'itemId':'1','sessionId':'fixture-session','transcodeSessionId':'fixture-session','positionMs':0,'state':'stopped'}
        job={**SCOPE,'requestId':'stop-1','action':'playback_stop','params':params,'inventoryProbeOwner':OWNER}
        result=self.call('ProbeFixture',[job,SESSION,[response('',401),response('',404),response(canonical([],total=0))],False,False])
        self.assertEqual((False,'auth_required','timeline'),(result['outcome']['ok'],result['outcome']['errorCode'],result['outcome']['deliveryPhase']))
        del job['inventoryProbeOwner']
        result=self.call('ProbeFixture',[job,SESSION,[response({},200),response('',404)],False,False])
        self.assertEqual(2,len(result['requests']));self.assertNotIn('inventoryDiagnostic',result['outcome'])
    def test_native_numeric_aliases_keep_real_status_size_and_offset(self):
        result=self.call('NativeShapesFixture',[[{'ok':True,**response(canonical([{'id':'fixture-session'}],total=1))}]],native=True)
        for values in result:
            diag=values[0];self.assertEqual((200,1,0),(diag['httpStatus'],diag['size'],diag['offset']))
            self.assertTrue(diag['fullnessKnown']);self.assertFalse(diag['absenceTrusted'])
    def test_optional_header_projection_accepts_only_two_documented_numeric_headers(self):
        headers=[{'Set-Cookie':'private-token'},{'X-Plex-Container-Total-Size':'1'},{'x-plex-container-start':'0'},{'Location':'https://private.test'}]
        result=self.call('HeaderFixture',[{'capturePlexContainerHeaders':True},headers])
        self.assertEqual({'valid':True,'totalSize':1,'offset':0},result['plexContainerHeaders'])
        self.assertNotIn('private',json.dumps(result))
        ordinary=self.call('HeaderFixture',[{},headers]);self.assertNotIn('plexContainerHeaders',ordinary)
        for bad in (headers+[{'X-PLEX-CONTAINER-START':'0'}], [{'X-Plex-Container-Total-Size':'-1'}], [{'X-Plex-Container-Total-Size':'2147483648'}], [{'X-Plex-Container-Start':True}],headers*17):
            result=self.call('HeaderFixture',[{'capturePlexContainerHeaders':True},bad])
            self.assertFalse(result['plexContainerHeaders']['valid'])
    def test_header_completeness_and_body_conflicts_remain_untrusted(self):
        results=self.call('ShapesFixture',[[{'ok':True,**response(canonical([],total=None)), 'plexContainerHeaders':{'valid':True,'totalSize':0,'offset':0}},
                                           {'ok':True,**response(canonical([],total=0)),'plexContainerHeaders':{'valid':True,'totalSize':1,'offset':0}},
                                           {'ok':True,**response(canonical([],total=0)),'plexContainerHeaders':{'valid':False,'totalSize':0,'offset':0}}]])
        self.assertTrue(results[0]['fullnessKnown']);self.assertFalse(results[1]['fullnessKnown']);self.assertFalse(results[2]['fullnessKnown'])
        self.assertTrue(all(not d['absenceTrusted'] for d in results))
    def test_same_revision_credential_or_route_mutation_invalidates_probe_snapshot(self):
        job={**SCOPE,'action':'transcode_probe','requestId':'probe-1','params':{'transcodeSessionId':'fixture-session','sessionRevision':2,'stage':'rendered'},'inventoryOwner':OWNER}
        for patch in ({'token':'changed-private-token'},{'baseUrl':'https://foreign.example.test'}):
            result=self.call('ProbeFixture',[job,SESSION,[response(canonical([],total=0))],False,False,patch])
            self.assertEqual('session_changed',result['outcome']['errorCode'])
            self.assertFalse(result['outcome']['inventoryDiagnostic']['scopeValid'])
    def test_unknown_container_or_entry_shapes_do_not_claim_known_fullness(self):
        bodies=[{'MediaContainer':{'size':0,'totalSize':0,'offset':0,'private-extra':'hidden'}},
                canonical([{'key':'fixture-session','private-extra':'hidden'}],total=1)]
        values=self.call('ShapesFixture',[[{'ok':True,**response(body)} for body in bodies]])
        self.assertTrue(all(not d['completeShape'] and not d['fullnessKnown'] for d in values))
    def test_successful_stop_skips_inventory_read_and_keeps_existing_receipt(self):
        params={'itemId':'1','sessionId':'fixture-session','transcodeSessionId':'fixture-session','positionMs':0,'state':'stopped'}
        job={**SCOPE,'requestId':'stop-1','action':'playback_stop','params':params,'inventoryProbeOwner':OWNER}
        result=self.call('ProbeFixture',[job,SESSION,[response({},200),response({},200)],False,False])
        self.assertTrue(result['outcome']['ok']);self.assertEqual(2,len(result['requests']))
        self.assertNotIn('inventoryDiagnostic',result['outcome'])
if __name__=='__main__':unittest.main()
