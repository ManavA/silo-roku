"""Real worker/registry projections with only HTTP, clock and registry facades."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

C=Path(__file__).resolve().parents[1]
ROOT=C if (C/'tools/brightscript.py').exists() else Path.cwd()
sys.path.insert(0,str(ROOT))
from tools.brightscript import run_function
from importlib.util import spec_from_file_location,module_from_spec
spec=spec_from_file_location('decision_fixture_values',C/'tests/test_decision_preference.py')
values=module_from_spec(spec);spec.loader.exec_module(values)
SCOPE=values.SCOPE;PREF=values.PREF;VIEWER=values.VIEWER;NOW=values.NOW
SESSION={'sourceId':SCOPE['sourceId'],'profileId':'owner','token':'synthetic-provider-secret','baseUrl':'https://provider.example.test','trackPreference':{'sentinel':'preserve'}}
ORIGIN='https://gateway.example.test'
ENABLED={**PREF,'personalized':True,'cloudDecisions':True,'stillWatchingCheck':True,'gatewayOrigin':ORIGIN}
TOKEN={'origin':ORIGIN,'token':'synthetic-install','exp':int(NOW/1000)+200000,'sessionRevision':0}
PARAMS={'requestedAtMs':NOW,'deadlineMs':NOW+800,'viewer':VIEWER}
ANSWER={'answers':{'still_watching':{'type':'noul','noul':.2}},'model':'fixture','latencyMs':10}
INSTALL={'installId':'fixture-install','token':'synthetic-renewed','exp':int(NOW/1000)+2592000}
FAILURE={'ok':False,'errorCode':'decision_unavailable'}

BOUNDARIES='''
function SessionSection(provider as String) as Object
 return {store:m.fixtureRegistry,
  Exists:function(key as String) as Boolean
   return m.store.records.DoesExist(key)
  end function,
  Read:function(key as String) as String
   if not m.store.records.DoesExist(key) then return ""
   return m.store.records[key]
  end function,
  Write:function(key as String,value as String) as Boolean
   if key=m.store.failKey then return false
   m.store.writes.Push(key)
   m.store.records[key]=value
   if key="decisionGatewayToken" and m.store.reviseTokenWrite then m.store.records.revision="1"
   return true
  end function,
  Delete:sub(key as String)
   m.store.deleted.Push(key)
   m.store.records.Delete(key)
  end sub,
  Flush:function() as Boolean
   return not m.store.failFlush
  end function}
end function
function TaskDeviceSession(provider as String,session as Object) as Object
 m.deviceCalls++
 return session
end function
function DecisionNowMs() as Double
 return m.fixtureNow
end function
function DecisionGatewayHttpRequest(request as Object,deadline as Double) as Object
 m.requests.Push(request)
 m.deadlines.Push(deadline)
 if m.responses.Count()=0 then return {ok:false,errorCode:"unexpected_http"}
 raw=m.responses.Shift()
 m.fixtureNow+=TaskValue(raw,"elapsedMs",0)
 if TaskValue(raw,"revisionChange",false) then m.fixtureRegistry.records.revision="1"
 patch=TaskValue(raw,"sessionPatch",{})
 current=DecodeStoredSession(m.fixtureRegistry.records.session)
 for each key in patch
  current[key]=patch[key]
 end for
 m.fixtureRegistry.records.session=FormatJson(current)
 response=HttpResponseBody(request,TaskValue(raw,"statusCode",200),TaskString(raw,"body"))
 if raw.DoesExist("okOverride") then response["ok"]=raw.okOverride
 return response
end function
function HttpRequest(request as Object,timeoutMs=0 as Integer) as Object
 m.providerRequests.Push(request)
 return {ok:false,errorCode:"unexpected_provider_http"}
end function
function RunDecisionJobs(session as Object,jobs as Object,responses as Object,config as Object) as Object
 m.fixtureRegistry={records:{session:FormatJson(session),revision:"0"},writes:[],deleted:[],failKey:TaskValue(config,"failKey",""),
  failFlush:TaskValue(config,"failFlush",false),reviseTokenWrite:TaskValue(config,"reviseTokenWrite",false)}
 token=TaskValue(config,"token",invalid)
 if token<>invalid then m.fixtureRegistry.records["decisionGatewayToken"]=FormatJson(token)
 m.fixtureNow=TaskValue(config,"nowMs",1792000000123#)
 m.requests=[]:m.providerRequests=[]:m.deadlines=[]:m.deviceCalls=0:m.responses=responses
 outcomes=[]
 for each job in jobs
  if job.action="clear"
   outcomes.Push({ok:ClearSession("plex")})
  else
   outcomes.Push(ExecuteApiAction(TaskString(job.scope,"provider"),job.action,job.params,job.scope))
  end if
 end for
 return {outcomes:outcomes,requests:m.requests,providerRequests:m.providerRequests,deadlines:m.deadlines,
  records:m.fixtureRegistry.records,writes:m.fixtureRegistry.writes,deleted:m.fixtureRegistry.deleted,deviceCalls:m.deviceCalls}
end function
'''

class DecisionGatewayWorkerTests(unittest.TestCase):
    def job(self,action='still_watching',params=None,scope=None):
        return {'action':action,'params':copy.deepcopy(PARAMS if params is None else params),'scope':copy.deepcopy(SCOPE if scope is None else scope)}

    def call(self,jobs=None,session=None,responses=None,**config):
        if jobs is None:jobs=[self.job()]
        if session is None:session={**SESSION,'decisionPreferences':[ENABLED]}
        if responses is None:responses=[{'body':json.dumps(ANSWER),'elapsedMs':100}]
        with tempfile.TemporaryDirectory(prefix='silo_ui-decision-worker-') as d:
            p=Path(d);worker=p/'worker.brs'
            worker.write_text((C/'components/ApiTask.brs').read_text().replace('function TaskDeviceSession(','function UnusedTaskDeviceSession(',1))
            store=p/'session-store.brs';store.write_text((C/'source/auth/SessionStore.brs').read_text().replace('function SessionSection(','function UnusedSessionSection(',1))
            boundary=p/'boundary.brs';boundary.write_text(BOUNDARIES)
            http=p/'http.brs';source=(ROOT/'source/network/Http.brs').read_text()
            names=('HttpErrorCode','HttpErrorBodyLimit','HttpErrorBodyWithinLimit','HttpResponseBodyLimit','HttpResponseBody')
            http.write_text('\n'.join(re.search(r'(?ms)^function '+n+r'\(.*?^end function',source).group(0) for n in names))
            files=[ROOT/'source/core/ServerUrlPolicy.brs',ROOT/'source/auth/SessionPolicy.brs',ROOT/'source/core/TrackPreference.brs',
                   ROOT/'source/adapters/PlexAdapter.brs',ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/adapters/MetadataAdapter.brs',store,worker,http]
            for relative in ('source/core/DecisionPreference.brs','source/adapters/DecisionGatewayAdapter.brs','source/auth/DecisionGatewayStore.brs','components/TaskDecisionGateway.brs'):
                f=C/relative
                if f.exists():
                    local=p/f.name
                    local.write_text(f.read_text().replace('function DecisionNowMs(','function UnusedDecisionNowMs(',1).replace('function DecisionGatewayHttpRequest(','function UnusedDecisionGatewayHttpRequest(',1))
                    files.append(local)
            return run_function([*files,boundary],'RunDecisionJobs',[session,jobs,responses,config],root=p)

    def assert_private(self,value):
        public=json.dumps(value['outcomes'])
        for secret in ('synthetic-provider-secret','synthetic-install','synthetic-renewed','fixture-install','Authorization'):
            self.assertNotIn(secret,public)
        self.assertEqual([],value['providerRequests']);self.assertEqual(0,value['deviceCalls'])

    def test_pref_get_default_and_full_set_round_trip_are_local_and_preserve_session(self):
        value=self.call([self.job('decision_pref_get',{}),self.job('decision_pref_set',{'preference':ENABLED}),self.job('decision_pref_get',{})],session=SESSION)
        self.assertEqual([{'ok':True,'data':{'preference':p}} for p in (PREF,ENABLED,ENABLED)],value['outcomes'])
        saved=json.loads(value['records']['session']);self.assertEqual([ENABLED],saved['decisionPreferences'])
        for k,v in SESSION.items():self.assertEqual(v,saved[k])
        self.assertEqual(['session'],value['writes']);self.assertEqual([],value['requests']);self.assert_private(value)

    def test_stored_gates_not_scene_values_control_network_and_default_is_off(self):
        for preference in (None,PREF,{**ENABLED,'personalized':False},{**ENABLED,'cloudDecisions':False},
                           {**ENABLED,'stillWatchingCheck':False},{**ENABLED,'gatewayOrigin':''}):
            session={**SESSION,'decisionPreferences':[] if preference is None else [preference]}
            value=self.call(session=session,token=TOKEN)
            self.assertEqual([FAILURE],value['outcomes']);self.assertEqual([],value['requests']);self.assert_private(value)

    def test_warm_exact_origin_token_sends_only_public_coarse_state(self):
        value=self.call(token=TOKEN)
        self.assertEqual([{'ok':True,'data':{'probability':.2}}],value['outcomes'])
        self.assertEqual([NOW+800],value['deadlines']);self.assertEqual([],value['writes'])
        request=value['requests'][0]
        self.assertEqual(ORIGIN+'/decide',request['url']);self.assertEqual('Bearer synthetic-install',request['headers']['Authorization'])
        self.assertEqual({'kind':'upnext','version':1,'state':{'viewer':VIEWER}},json.loads(request['body']))
        self.assertNotIn('X-Plex-Token',request['headers']);self.assertNotIn('sourceId',request['body']);self.assert_private(value)

    def test_cold_install_uses_separate_private_key_and_never_rewrites_session_json(self):
        value=self.call(responses=[{'body':json.dumps(INSTALL),'elapsedMs':100},{'body':json.dumps(ANSWER),'elapsedMs':100}])
        self.assertEqual([{'ok':True,'data':{'probability':.2}}],value['outcomes'])
        self.assertEqual([ORIGIN+'/install',ORIGIN+'/decide'],[r['url'] for r in value['requests']])
        self.assertEqual(['decisionGatewayToken'],value['writes']);self.assertEqual({**SESSION,'decisionPreferences':[ENABLED]},json.loads(value['records']['session']))
        private=json.loads(value['records']['decisionGatewayToken']);self.assertEqual(ORIGIN,private['origin']);self.assertEqual('synthetic-renewed',private['token'])
        self.assertNotIn('Authorization',value['requests'][0]['headers']);self.assertEqual('{}',value['requests'][0]['body']);self.assert_private(value)
        # A real provider refresh may complete while optional install IO runs.
        # Its credential patch must survive because only the private key is saved.
        scope={**SCOPE,'provider':'silo','sourceId':'silo:fixture'}
        preference={**ENABLED,'sourceId':scope['sourceId']}
        session={'sourceId':scope['sourceId'],'profileId':'owner','accessToken':'synthetic-silo-old',
                 'refreshToken':'synthetic-refresh','profileToken':'synthetic-profile','decisionPreferences':[preference]}
        value=self.call([self.job(scope=scope)],session=session,responses=[
            {'body':json.dumps(INSTALL),'sessionPatch':{'accessToken':'synthetic-silo-refreshed'}},
            {'body':json.dumps(ANSWER)}])
        self.assertTrue(value['outcomes'][0]['ok']);self.assertEqual(['decisionGatewayToken'],value['writes'])
        self.assertEqual('synthetic-silo-refreshed',json.loads(value['records']['session'])['accessToken'])
        self.assertNotIn('synthetic-silo',json.dumps(value['requests']));self.assert_private(value)

    def test_foreign_origin_never_receives_old_install_bearer(self):
        value=self.call(token={**TOKEN,'origin':'https://other.example.test'},responses=[{'body':json.dumps(INSTALL)},{'body':json.dumps(ANSWER)}])
        self.assertTrue(value['outcomes'][0]['ok']);self.assertNotIn('Authorization',value['requests'][0]['headers'])
        self.assertEqual('Bearer synthetic-renewed',value['requests'][1]['headers']['Authorization'])

    def test_renewal_and_single_401_retry_share_one_original_deadline(self):
        near={**TOKEN,'exp':int(NOW/1000)+60}
        value=self.call(token=near,responses=[{'body':json.dumps(INSTALL),'elapsedMs':100},{'body':json.dumps(ANSWER),'elapsedMs':100}])
        self.assertTrue(value['outcomes'][0]['ok']);self.assertEqual('Bearer synthetic-install',value['requests'][0]['headers']['Authorization'])
        value=self.call(token=TOKEN,responses=[{'statusCode':401,'body':'private response','elapsedMs':100},
                       {'body':json.dumps(INSTALL),'elapsedMs':100},{'statusCode':401,'body':'private response','elapsedMs':100}])
        self.assertEqual([FAILURE],value['outcomes']);self.assertEqual(3,len(value['requests']));self.assertEqual([NOW+800]*3,value['deadlines']);self.assert_private(value)

    def test_queue_wait_and_all_install_retry_time_count_against_800ms(self):
        value=self.call(token=TOKEN,nowMs=NOW+800)
        self.assertEqual([FAILURE],value['outcomes']);self.assertEqual([],value['requests'])
        value=self.call(token=TOKEN,nowMs=NOW+600,responses=[{'body':json.dumps(ANSWER),'elapsedMs':200}])
        self.assertEqual([FAILURE],value['outcomes']);self.assertEqual(1,len(value['requests']))
        value=self.call(responses=[{'body':json.dumps(INSTALL),'elapsedMs':800},{'body':json.dumps(ANSWER)}])
        self.assertEqual([FAILURE],value['outcomes']);self.assertEqual(1,len(value['requests']));self.assertEqual([],value['writes'])
        value=self.call(token=TOKEN,responses=[{'statusCode':401,'elapsedMs':500},{'body':json.dumps(INSTALL),'elapsedMs':300},{'body':json.dumps(ANSWER)}])
        self.assertEqual([FAILURE],value['outcomes']);self.assertEqual(2,len(value['requests']))

    def test_expired_fractional_future_and_bad_viewer_requests_never_reach_gateway(self):
        cases=[{**PARAMS,'requestedAtMs':NOW+.5},{**PARAMS,'deadlineMs':NOW+801},
               {**PARAMS,'requestedAtMs':NOW+1,'deadlineMs':NOW+801},{**PARAMS,'deadlineMs':True},
               {**PARAMS,'sourceId':'plex:fixture'},{**PARAMS,'viewer':{**VIEWER,'itemId':'private'}}]
        for params in cases:
            value=self.call([self.job(params=params)],token=TOKEN)
            self.assertEqual([FAILURE],value['outcomes']);self.assertEqual([],value['requests'])

    def test_scope_revision_and_current_preferences_are_rechecked_after_network(self):
        for change in ({'revisionChange':True},{'sessionPatch':{'sourceId':'plex:other'}},{'sessionPatch':{'profileId':'other'}},
                       {'sessionPatch':{'decisionPreferences':[{**ENABLED,'stillWatchingCheck':False}]}},
                       {'sessionPatch':{'decisionPreferences':[{**ENABLED,'gatewayOrigin':'https://other.example.test'}]}}):
            response={'body':json.dumps(ANSWER),**change}
            value=self.call(token=TOKEN,responses=[response])
            self.assertEqual([FAILURE],value['outcomes']);self.assertEqual(1,len(value['requests']));self.assertEqual([],value['writes'])
        for scope in ({**SCOPE,'sourceId':'plex:other'},{**SCOPE,'profileId':'other'}, {**SCOPE,'generation':True}):
            value=self.call([self.job(scope=scope)],token=TOKEN)
            self.assertEqual([FAILURE],value['outcomes']);self.assertEqual([],value['requests'])

    def test_bad_install_answer_and_http_receipts_only_return_fixed_optional_failure(self):
        cases=[{'statusCode':429,'body':'synthetic-private'}, {'body':json.dumps(ANSWER),'okOverride':1},
               {'body':json.dumps({'answers':{'still_watching':{'type':'noul','noul':'0.2'}}})},
               {'body':' '*8193},{'body':'é'*4097}]
        for response in cases:
            value=self.call(token=TOKEN,responses=[response])
            self.assertEqual([FAILURE],value['outcomes']);self.assert_private(value)
        for install in ({**INSTALL,'token':'bad\nheader'},{**INSTALL,'exp':'future'},{**INSTALL,'exp':int(NOW/1000)-1},{**INSTALL,'token':True}):
            value=self.call(responses=[{'body':json.dumps(install)}])
            self.assertEqual([FAILURE],value['outcomes']);self.assertEqual([],value['writes'])

    def test_private_key_write_failure_cannot_forge_a_probability(self):
        value=self.call(failKey='decisionGatewayToken',responses=[{'body':json.dumps(INSTALL)},{'body':json.dumps(ANSWER)}])
        self.assertEqual([FAILURE],value['outcomes']);self.assertEqual(1,len(value['requests']));self.assert_private(value)
        value=self.call(reviseTokenWrite=True,responses=[{'body':json.dumps(INSTALL)},{'body':json.dumps(ANSWER)}])
        self.assertEqual([FAILURE],value['outcomes']);self.assertEqual(1,len(value['requests']))

    def test_pref_set_rejects_partial_unknown_case_collision_and_failed_save(self):
        for record in ({}, {**ENABLED,'personalized':1},{**ENABLED,'token':'synthetic-private'},{**ENABLED,'Personalized':False}):
            value=self.call([self.job('decision_pref_set',{'preference':record})])
            self.assertEqual([{'ok':False,'errorCode':'invalid_request'}],value['outcomes']);self.assertEqual([],value['writes'])
        value=self.call([self.job('decision_pref_set',{'preference':ENABLED})],failKey='session')
        self.assertEqual([{'ok':False,'errorCode':'storage_error'}],value['outcomes'])

    def test_eight_scope_records_and_sign_out_remove_private_key(self):
        records=[{**ENABLED,'profileId':'other-'+str(i)} for i in range(8)]
        value=self.call([self.job('decision_pref_set',{'preference':ENABLED})],session={**SESSION,'decisionPreferences':records},token=TOKEN)
        stored=json.loads(value['records']['session'])['decisionPreferences']
        self.assertEqual(8,len(stored));self.assertEqual(ENABLED,stored[-1]);self.assertEqual(SESSION['trackPreference'],json.loads(value['records']['session'])['trackPreference'])
        value=self.call([self.job('clear',{})],token=TOKEN)
        self.assertEqual([{'ok':True}],value['outcomes']);self.assertNotIn('session',value['records']);self.assertNotIn('decisionGatewayToken',value['records'])

if __name__=='__main__':unittest.main()
