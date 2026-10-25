"""Generic runJob refresh authority, real TaskSavePatch/SaveSession, SDK I/O only."""
import copy,json,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from tools.brightscript import run_function
from tests import test_silo_playback_task as playback
from tests import test_silo_auth_task as auth
from tests.test_silo_compat_discovery import advertised
ROOT=Path(__file__).resolve().parents[1]
class GenericRefreshIdentity(unittest.TestCase):
 def job(self,action='profiles',race='',field='profileToken'):
  session=copy.deepcopy(auth.SESSION)
  final=advertised() if action=='compat_connect_info' else json.loads((ROOT/'tests/fixtures/silo/profiles.json').read_text())
  if action=='compat_handoff_approve':final={'status':'approved'}
  responses=[{'statusCode':401,'body':'{}'},{'statusCode':200,'body':json.dumps({'access_token':'synthetic-new-access','refresh_token':'synthetic-new-refresh','expires_in':3600})},{'statusCode':200,'body':json.dumps(final)}]
  sdk=playback.BOUNDARIES.replace('function TaskUniqueId(','function FixtureUnusedTaskUniqueId(',1)
  sdk=sdk.replace('return m.fixtureSession','return ParseJson(FormatJson(m.fixtureSession),"i")',1)
  sdk=sdk.replace('response = m.responses.Shift()', '''response = m.responses.Shift()
 if (m.race="at401" and m.requests.Count()=1) or (m.race="duringRefresh" and Instr(1,request.url,"/auth/refresh")>0)
  changed=ParseJson(FormatJson(m.fixtureSession),"i")
  changed[m.changedField]="synthetic-changed-value"
  m.fixtureSession=changed
 end if
 if m.race="revision" and Instr(1,request.url,"/auth/refresh")>0 then m.fixtureRevision++
 if m.race="cancel" and Instr(1,request.url,"/auth/refresh")>0 then m.top.cancelled=true
 if m.race="cancelAt401" and m.requests.Count()=1 then m.top.cancelled=true''')
  sdk+='''
function FixtureRegistrySection() as Object
 return {Write:function(key as String,value as String) as Boolean
  root=GetGlobalAA()["registryRoot"]
  if key="session" then root["fixtureSession"]=DecodeStoredSession(value):root["writes"]=root["writes"]+1
  return true
 end function,Flush:function() as Boolean
  return true
 end function}
end function
function RunGenericRefresh(session as Object,responses as Object,action as String,race as String,field as String) as Object
 m.fixtureSession=session:m.fixtureRevision=0:m.requests=[]:m.timeouts=[]:m.responses=responses:m.changeRevision=false:m.writes=0:m.race=race:m.changedField=field
 GetGlobalAA()["registryRoot"]=m
 params={}
 if action="compat_handoff_approve" then params={code:"482177"}
 m.top=CreateObject("roSGNode","Node")
 m.top.AddFields({cancelled:false,job:{provider:"silo",action:action,params:params,sourceId:session.sourceId,profileId:session.profileId,generation:3,requestId:41}})
 runJob()
 return {outcome:m.top.result,requests:m.requests,writes:m.writes,changed:m.fixtureSession[field]="synthetic-changed-value",newToken:m.fixtureSession.accessToken="synthetic-new-access",sameProfile:m.fixtureSession.profileId=session.profileId}
end function
'''
  with tempfile.TemporaryDirectory() as td:
   folder=Path(td);files=[]
   for script in ET.parse(ROOT/'components/ApiTask.xml').getroot().findall('script'):
    p=ROOT/script.get('uri').removeprefix('pkg:/');text=p.read_text().replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()')
    if p.name=='ApiTask.brs':text=text.replace('function TaskRokuSiloContext(','function FixtureUnusedTaskRokuSiloContext(',1)
    if p.name=='Http.brs':text=text.replace('function HttpRequest(','function FixtureUnusedHttpRequest(',1)
    if p.name=='SessionStore.brs':text=text.replace('function LoadSession(','function FixtureUnusedLoadSession(',1).replace('function SessionRevision(','function FixtureUnusedSessionRevision(',1).replace('AppRegistrySection(provider)','FixtureRegistrySection()')
    target=folder/p.name;target.write_text(text);files.append(target)
   boundary=folder/'sdk.brs';boundary.write_text(sdk);files.append(boundary)
   return run_function(files,'RunGenericRefresh',[session,responses,action,race,field],root=folder)
 def test_pin_changed_during_refresh_is_not_restored_or_retried(self):
  r=self.job(race='duringRefresh');self.assertFalse(r['outcome']['ok'])
  self.assertEqual('session_changed',r['outcome']['errorCode']);self.assertTrue(r['changed']);self.assertEqual(0,r['writes'])
  self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']])
 def test_changed_pin_at_401_never_refreshes_or_expires_new_profile(self):
  for action in ('profiles','compat_connect_info'):
   with self.subTest(action=action):
    r=self.job(action=action,race='at401');self.assertEqual('session_changed',r['outcome']['errorCode'])
    self.assertTrue(r['changed']);self.assertEqual(0,r['writes']);self.assertEqual(['GET'],[q['method'] for q in r['requests']])
 def test_discovery_pin_changed_during_refresh_is_preserved(self):
  r=self.job(action='compat_connect_info',race='duringRefresh');self.assertEqual('session_changed',r['outcome']['errorCode'])
  self.assertTrue(r['changed']);self.assertEqual(0,r['writes']);self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']])
 def test_normal_refresh_rotates_once_and_retries_with_current_profile(self):
  for action in ('profiles','compat_connect_info'):
   with self.subTest(action=action):
    r=self.job(action=action);self.assertTrue(r['outcome']['ok'],r['outcome'])
    self.assertTrue(r['newToken']);self.assertTrue(r['sameProfile']);self.assertEqual(1,r['writes']);self.assertEqual(['GET','POST','GET'],[q['method'] for q in r['requests']])
    self.assertEqual('Bearer synthetic-new-access',r['requests'][-1]['headers']['Authorization'])
    if action=='compat_connect_info':self.assertTrue(r['outcome']['data']['available'])
 def test_source_profile_and_base_drift_at_401_never_refresh(self):
  for field in ('sourceId','profileId','baseUrl'):
   with self.subTest(field=field):
    r=self.job(race='at401',field=field);self.assertEqual('session_changed',r['outcome']['errorCode'])
    self.assertTrue(r['changed']);self.assertEqual(0,r['writes']);self.assertEqual(['GET'],[q['method'] for q in r['requests']])
 def test_revision_and_cancel_during_refresh_cannot_retry_generic_get(self):
  for race,error in [('revision','session_changed'),('cancel','cancelled')]:
   with self.subTest(race=race):
    r=self.job(race=race);self.assertEqual(error,r['outcome']['errorCode']);self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']])
    if race=='revision':self.assertEqual(0,r['writes'])

 def test_cancel_at_401_does_not_start_refresh_or_expire_session(self):
  r=self.job(race='cancelAt401');self.assertEqual('cancelled',r['outcome']['errorCode'])
  self.assertEqual(0,r['writes']);self.assertEqual(['GET'],[q['method'] for q in r['requests']])

 def test_strict_handoff_access_token_race_is_session_changed_not_auth_required(self):
  for race,methods in [('at401',['POST']),('duringRefresh',['POST','POST'])]:
   with self.subTest(race=race):
    r=self.job(action='compat_handoff_approve',race=race,field='accessToken')
    self.assertEqual('session_changed',r['outcome']['errorCode']);self.assertTrue(r['changed']);self.assertEqual(0,r['writes'])
    self.assertEqual(methods,[q['method'] for q in r['requests']])
 def test_strict_handoff_own_successful_refresh_updates_token_authority(self):
  r=self.job(action='compat_handoff_approve');self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertTrue(r['outcome']['data']['approved']);self.assertTrue(r['newToken']);self.assertEqual(1,r['writes'])
  self.assertEqual(['POST','POST','POST'],[q['method'] for q in r['requests']]);self.assertEqual('Bearer synthetic-new-access',r['requests'][-1]['headers']['Authorization'])
