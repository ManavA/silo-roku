"""Ordinary Start retry authority through actual runJob and SDK HTTP receipts.

Server source pins 48ae561d8427467cb786b5268cd3fed275d6acfb,
a434bbc2f23f8e424856c4b717f0a9bd2cec5661 and
0589b3348c29f0cd0f93a5b85f6d997e189387e0 all return HTTP 201 for
/api/v2/playback/start, including nonallocating terminals: internal/apiv2/
playback.go:312,365 and contracts/api/v2/openapi.json. Legacy synthetic
HTTP 200 remains supported. Status alone never establishes retry authority.
"""
import json,unittest
from unittest.mock import patch
from tests import test_silo_audio_projection as audio

class StartRetryAuthority(unittest.TestCase):
 def start(self,mutate=None,stop=None,race='',status=200):
  def source(v):v['codec_audio']='aac';v['audio_tracks'][0].update(codec='aac',channels=2,layout='stereo')
  sdk=audio.task.legacy.BOUNDARIES
  if mutate:
   # Substitute only the first allocated HTTP DTO; no unused stop response when
   # no safe lease exists. Subsequent responses remain the actual fallback DTO.
   sdk=sdk.replace('response = m.responses.Shift()', '''response = m.responses.Shift()
 if request.method="POST" and Instr(1,request.url,"/playback/start")>0 and m.requests.Count()=3
  decision=ParseJson(response.body)
  '''+mutate+'''
  response.body=FormatJson(decision)
 end if''')
  effects={'post_pin':'changed=FixtureDeepClone(m.fixtureSession):changed.profileToken="synthetic-new-pin":m.fixtureSession=changed','post_profile':'changed=FixtureDeepClone(m.fixtureSession):changed.profileId="other-profile":m.fixtureSession=changed','post_source':'changed=FixtureDeepClone(m.fixtureSession):changed.sourceId="other-source":m.fixtureSession=changed','post_revision':'m.fixtureRevision++','post_cancel':'m.top.cancelled=true','post_request':'changed=FixtureDeepClone(m.top.job):changed.requestId=99:m.top.job=changed','stop_source':'changed=FixtureDeepClone(m.fixtureSession):changed.sourceId="other-source":m.fixtureSession=changed'}
  if race in effects:
   when='request.method="DELETE"' if race=='stop_source' else 'request.method="POST" and m.requests.Count()=3'
   sdk=sdk.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if '+when+' then '+effects[race])
  if status!=200:sdk=sdk.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if request.method="POST" and m.requests.Count()=3 then response={statusCode:'+str(status)+',body:response.body}')
  if stop:sdk=sdk.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if request.method="DELETE" then response='+stop)
  with patch.object(audio.task.legacy,'BOUNDARIES',sdk):
   return audio.AudioProjection().start(source=source,probe='return {result:format.codec="aac" and format.passthru=0}',features=[],fallback=True,options={'qualityExplicit':False},race=race)
 def test_failed_start_has_bounded_request_snapshot_of_dispatched_attempt(self):
  r=self.start(stop='{statusCode:503,body:"{}"}')
  f=r['outcome']['startRequestFacts']
  self.assertEqual('original',f['quality']);self.assertEqual('manual',f['selection'])
  self.assertEqual('h264',f['videoCodec']);self.assertEqual('aac',f['audioCodec'])
  self.assertNotIn('732',json.dumps(f));self.assertNotIn('startRequestFacts',json.dumps(r['requests']))
 def test_retry_snapshot_describes_final_quality_without_initial_request_facts(self):
  r=self.start()
  self.assertTrue(r['outcome']['ok'])
  self.assertEqual('1080p',r['outcome']['plan']['startRequestFacts']['quality'])
  self.assertEqual(['original','1080p'],[json.loads(q['body'])['quality_preference'] for q in r['requests'] if q['method']=='POST'])
 def test_missing_lease_on_ordinary_hls_refusal_cannot_allocate_again(self):
  r=self.start('decision.Delete("session_id"):decision.playback_plan.Delete("session_id"):unusedStop=m.responses.Shift()')
  self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome'].get('leaseUncertain'))
  self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']])
 def test_actual_schema_nonallocating_terminal_keeps_existing_fallback_without_stop(self):
  terminal='decision={protocol_version:3,server_features:["future_feature"],outcome:"adaptation_unavailable",terminal:{reason:"adaptation_exhausted",message:"synthetic-private-message",retryable:false}}:unusedStop=m.responses.Shift()'
  r=self.start(terminal)
  self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual(['GET','GET','POST','GET','GET','POST'],[q['method'] for q in r['requests']])
  self.assertEqual(['original','1080p'],[json.loads(q['body'])['quality_preference'] for q in r['requests'] if q['method']=='POST'])
  self.assertNotIn('synthetic-private-message',json.dumps(r['outcome']))
 def test_all_real_stop_outcomes_allow_existing_hls_and_oversized_fallback(self):
  for outcome,mutation in [('stopped',None),('applied','decision.playback_plan.effective_recipe.width=3840'),('replayed',None)]:
   with self.subTest(outcome=outcome):
    r=self.start(mutation,stop='{statusCode:200,body:"{""outcome"":""'+outcome+'""}"}')
    self.assertTrue(r['outcome']['ok'],r['outcome'])
    self.assertEqual(['GET','GET','POST','DELETE','GET','GET','POST'],[q['method'] for q in r['requests']])
    delete=next(q for q in r['requests'] if q['method']=='DELETE')
    self.assertNotIn('position',json.loads(delete['body']));self.assertNotIn('sequence',json.loads(delete['body']))
 def test_failed_or_unverified_stop_keeps_exact_lease_and_never_retries(self):
  for stop in ('{statusCode:503,body:"{}"}','{statusCode:408,body:"{}"}','{statusCode:204,body:""}','{statusCode:200,body:"{}"}','{statusCode:200,body:"{""outcome"":""unknown""}"}'):
   with self.subTest(stop=stop):
    r=self.start(stop=stop);self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome']['leaseUncertain'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
    self.assertEqual('sess-1',r['outcome']['plan']['sessionId']);self.assertFalse(r['outcome']['plan']['persistProgress'])
 def test_conflicting_or_unusable_lease_cannot_turn_one_ack_into_retry_authority(self):
  mutations=['decision.playback_plan.session_id=decision.session_id:decision.session_id="other-session"','decision.playback_plan.session_id=decision.session_id:decision.session_id=""','decision.playback_plan.session_id="https://invalid.example/lease"']
  for mutate in mutations:
   with self.subTest(mutate=mutate):
    r=self.start(mutate);self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome']['leaseUncertain'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
 def test_stop_ack_cannot_authorize_obsolete_profile_pin_revision_or_cancel(self):
  for race in ('stop_pin','stop_profile','stop_revision','stop_cancel'):
   with self.subTest(race=race):
    r=self.start(race=race);self.assertFalse(r['outcome']['ok'])
    self.assertEqual('cancelled' if race=='stop_cancel' else 'session_changed',r['outcome']['errorCode'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']]);self.assertNotIn('plan',r['outcome'])
 def test_allocation_races_and_stop_source_change_preserve_cleanup_without_retry(self):
  for race in ('post_pin','post_profile','post_source','post_revision','post_cancel','stop_source'):
   with self.subTest(race=race):
    r=self.start(race=race);self.assertFalse(r['outcome']['ok'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']]);self.assertNotIn('plan',r['outcome'])
 def test_legacy_terminal_with_lease_requires_real_ack(self):
  legacy='decision.Delete("playback_plan"):decision.outcome="terminal":decision.terminal={reason:"no_playable_source",message:"synthetic-private-message",retryable:false}'
  r=self.start(legacy);self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(['GET','GET','POST','DELETE','GET','GET','POST'],[q['method'] for q in r['requests']])
  r=self.start(legacy,stop='{statusCode:503,body:"{}"}');self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome']['leaseUncertain']);self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
 def test_malformed_or_mixed_terminal_is_not_a_no_owner_assertion(self):
  base='decision={protocol_version:3,server_features:[],outcome:"adaptation_unavailable",terminal:{reason:"adaptation_exhausted",message:"synthetic-private-message",retryable:false}}:'
  changes=['decision.terminal.Delete("message")','decision.terminal.retryable="false"','decision.terminal.reason=""','decision.server_features=[3]','decision.outcome="terminal"','decision.outcome="future_outcome"','decision.session_id=invalid','decision.session_id=""','decision.playback_plan=invalid']
  for change in changes:
   with self.subTest(change=change):
    r=self.start(base+change+':unusedStop=m.responses.Shift()');self.assertFalse(r['outcome']['ok'])
    self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']]);self.assertNotIn('synthetic-private-message',json.dumps(r['outcome']))
  # Mixed terminal/plan carries a real cleanup identity but no terminal authority.
  r=self.start('decision.outcome="adaptation_unavailable":decision.terminal={reason:"adaptation_exhausted",message:"",retryable:false}')
  self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
 def test_ordinary_accepted_playback_remains_one_start(self):
  r=audio.AudioProjection().start(source=lambda v:v['audio_tracks'][0].update(codec='aac',channels=2),probe='return {result:format.codec="aac" and format.passthru=0}')
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']])

 def test_ack_owner_must_match_the_request_captured_before_allocation(self):
  r=self.start(race='post_request');self.assertFalse(r['outcome']['ok'])
  self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])

 def test_undocumented_status_terminal_cannot_grant_retry_authority(self):
  terminal='decision={protocol_version:3,server_features:[],outcome:"adaptation_unavailable",terminal:{reason:"adaptation_exhausted",message:"",retryable:false}}:unusedStop=m.responses.Shift()'
  for status in (202,204,400,403,408):
   with self.subTest(status=status):
    r=self.start(terminal,status=status);self.assertFalse(r['outcome']['ok'])
    if status in (202,204):self.assertEqual('playback_terminal',r['outcome']['errorCode'])
    elif status==408:self.assertEqual('network_timeout',r['outcome']['errorCode'])
    self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']])
 def refresh(self,stage='stop',change_pin=True):
  from pathlib import Path
  original_read=Path.read_text
  def sdk_read(path,*args,**kwargs):
   text=original_read(path,*args,**kwargs)
   if path.name=='SessionStore.brs':text=text.replace('AppRegistrySection(provider)','FixtureRetryRegistry()')
   return text
  sdk=audio.task.legacy.BOUNDARIES.replace('    return m.fixtureSession','''    if GetGlobalAA()["retryStored"]<>invalid then m.fixtureSession=GetGlobalAA()["retryStored"]
    return m.fixtureSession''',1)
  condition='request.method="DELETE" and m.requests.Count()=4' if stage=='stop' else 'request.method="GET" and Instr(1,request.url,"/playback/capabilities")>0 and m.requests.Count()=2'
  sdk=sdk.replace('response = m.responses.Shift()', '''if m.requests.Count()=1 then m.fixtureSession["refreshToken"]="synthetic-refresh"
 response = m.responses.Shift()
 if '''+condition+'''
  m.responses.Unshift(response)
  m.responses.Unshift({statusCode:200,body:"{""access_token"":""synthetic-fresh-access"",""refresh_token"":""synthetic-fresh-refresh"",""expires_in"":3600}"})
  response={statusCode:401,body:"{}"}
 end if
 '''+('if Instr(1,request.url,"/auth/refresh")>0 then GetGlobalAA()["retryStored"]=MergeSessionPatch(m.fixtureSession,{profileToken:"synthetic-changed-pin"})' if change_pin else ''))
  # Real SaveSession/TaskSavePatch execute; only the registry SDK write is emulated.
  sdk+='''
function FixtureRetryRegistry() as Object
 return {Write:function(key as String,value as String) as Boolean
  if key="session" then GetGlobalAA()["retryStored"]=DecodeStoredSession(value)
  return true
 end function,Flush:function() as Boolean
  return true
 end function}
end function
'''
  with patch.object(Path,'read_text',sdk_read),patch.object(audio.task.legacy,'BOUNDARIES',sdk):return self.start()
 def test_stop_refresh_cannot_restore_old_pin_or_authorize_another_start(self):
  r=self.refresh();self.assertFalse(r['outcome']['ok']);self.assertTrue(r['pinChanged'])
  self.assertEqual(['GET','GET','POST','DELETE','POST'],[q['method'] for q in r['requests']])
  self.assertEqual('sess-1',r['outcome']['plan']['sessionId'])
 def test_discovery_refresh_cannot_restore_old_pin_before_allocation(self):
  r=self.refresh(stage='discovery');self.assertFalse(r['outcome']['ok']);self.assertTrue(r['pinChanged'])
  self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']]);self.assertFalse(any('/playback/start' in q['url'] for q in r['requests']))
 def test_current_identity_refresh_keeps_existing_stop_and_discovery_success(self):
  for stage in ('stop','discovery'):
   with self.subTest(stage=stage):
    r=self.refresh(stage=stage,change_pin=False);self.assertTrue(r['outcome']['ok'],r['outcome'])
    self.assertEqual(2,sum('/playback/start' in q['url'] for q in r['requests']))
    self.assertEqual(1,sum('/auth/refresh' in q['url'] for q in r['requests']))
    deletes=[q for q in r['requests'] if q['method']=='DELETE']
    if stage=='stop':self.assertEqual(2,len(deletes));self.assertEqual(deletes[0]['body'],deletes[1]['body'])

 def test_known_cleanup_fact_requires_retained_consistent_identity(self):
  r=self.start(stop='{statusCode:503,body:"{}"}')
  self.assertIs(True,r['outcome'].get('cleanupLeaseKnown'))
  for mutation,stop in [('decision.Delete("session_id"):decision.playback_plan.Delete("session_id"):unusedStop=m.responses.Shift()',None),('decision.playback_plan.session_id=decision.session_id:decision.session_id="other-session"','{statusCode:503,body:"{}"}'),('decision.playback_plan.session_id=decision.session_id:decision.session_id="other-session"',None)]:
   with self.subTest(mutation=mutation,stop=stop):
    r=self.start(mutation,stop=stop)
    self.assertNotIn('cleanupLeaseKnown',r['outcome'])

 def test_rejected_start_facts_are_flat_private_free_and_use_start_http_status(self):
  r=self.start('decision.Delete("session_id"):decision.playback_plan.session_id=invalid',stop='{statusCode:503,body:"{}"}',status=201)
  facts=r['outcome'].get('startResponseFacts')
  self.assertEqual({'httpStatus':201,'protocol':'v3','outcome':'plan','sessionId':'missing','playbackPlanPresent':True,'playbackPlanObject':True,'planSessionId':'null','terminalShapeValid':False},facts)
  self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']])
  r=self.start(stop='{statusCode:503,body:"{}"}')
  self.assertEqual(200,r['outcome']['startResponseFacts']['httpStatus'])
  self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])

 def test_start_facts_distinguish_missing_null_empty_invalid_without_values(self):
  for mutation,protocol,outcome,top,nested,present,obj in [
   ('decision.Delete("protocol_version"):decision.Delete("outcome"):decision.session_id=invalid:decision.playback_plan=invalid','missing','missing','null','unavailable',True,False),
   ('decision.protocol_version=invalid:decision.outcome=invalid:decision.session_id="":decision.Delete("playback_plan")','null','null','empty','unavailable',False,False),
   ('decision.protocol_version="private-secret":decision.outcome={token:"private-secret"}:decision.session_id=17:decision.playback_plan.session_id="https://private-secret"','invalid','invalid','invalid','invalid',True,True),
   ('decision.protocol_version=4:decision.outcome="private-secret":decision.session_id="valid-id":decision.playback_plan.session_id=""','other','other','valid','empty',True,True)]:
   with self.subTest(mutation=mutation):
    r=self.start(mutation,stop='{statusCode:503,body:"{}"}')
    f=r['outcome']['startResponseFacts']
    self.assertEqual([protocol,outcome,top,nested,present,obj],[f[k] for k in ('protocol','outcome','sessionId','planSessionId','playbackPlanPresent','playbackPlanObject')])
    self.assertFalse(f['terminalShapeValid']);self.assertNotIn('private-secret',json.dumps(f));self.assertFalse(r['outcome']['ok'])
    self.assertEqual(1,sum('/playback/start' in q['url'] for q in r['requests']))

 def test_terminal_shape_facts_do_not_authorize_202_retry_or_create_408_facts(self):
  terminal='decision={protocol_version:3,server_features:[],outcome:"adaptation_unavailable",terminal:{reason:"adaptation_exhausted",message:"private-secret",retryable:false}}:unusedStop=m.responses.Shift()'
  r=self.start(terminal,status=202)
  self.assertEqual(True,r['outcome']['startResponseFacts']['terminalShapeValid']);self.assertEqual(202,r['outcome']['startResponseFacts']['httpStatus'])
  self.assertFalse(r['outcome']['ok']);self.assertEqual(1,sum('/playback/start' in q['url'] for q in r['requests']))
  self.assertNotIn('startResponseFacts',self.start(terminal,status=408)['outcome'])

 def test_fact_protocol_and_http_classification_are_strictly_typed(self):
  import xml.etree.ElementTree as ET
  from pathlib import Path
  from tools.brightscript import run_function
  root=Path(__file__).resolve().parents[1]
  files=[root / x.attrib['uri'].removeprefix('pkg:/') for x in ET.parse(root/'components/ApiTask.xml').getroot().findall('script')]
  for protocol,status,expected_protocol,expected_status in [(3.5,200.5,'invalid','unknown'),(-1,99,'invalid','unknown'),('3',600,'invalid','unknown'),(True,'200','invalid','unknown'),(4,599,'other',599),(3,100,'v3',100)]:
   with self.subTest(protocol=protocol,status=status):
    f=run_function(files,'TaskSiloStartResponseFacts',[{'protocol_version':protocol,'outcome':'plan'},status])
    self.assertEqual(expected_protocol,f['protocol']);self.assertEqual(expected_status,f['httpStatus'])

 def test_transport_unparsed_and_preflight_failures_do_not_add_start_facts(self):
  for args in ({'status':503},{'mutate':'decision=invalid:unusedStop=m.responses.Shift()'},{'race':'post_cancel'}):
   with self.subTest(args=args):
    r=self.start(**args);self.assertFalse(r['outcome']['ok']);self.assertNotIn('startResponseFacts',r['outcome'])


 def test_documented_201_nonallocating_terminal_allows_existing_fallback(self):
  terminal='decision={protocol_version:3,server_features:["future_feature"],outcome:"adaptation_unavailable",terminal:{reason:"adaptation_exhausted",message:"synthetic-private-message",retryable:false}}:unusedStop=m.responses.Shift()'
  r=self.start(terminal,status=201)
  self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual(['GET','GET','POST','GET','GET','POST'],[q['method'] for q in r['requests']])
  self.assertEqual(['original','1080p'],[json.loads(q['body'])['quality_preference'] for q in r['requests'] if q['method']=='POST'])
  self.assertNotIn('synthetic-private-message',json.dumps(r['outcome']))

 def test_documented_201_allocated_refusal_requires_exact_stop_ack(self):
  r=self.start(status=201,stop='{statusCode:200,body:"{""outcome"":""replayed""}"}')
  self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual(['GET','GET','POST','DELETE','GET','GET','POST'],[q['method'] for q in r['requests']])
  # An acknowledged stop cannot bless conflicting identities in the Start DTO.
  r=self.start('decision.playback_plan.session_id=decision.session_id:decision.session_id="other-session"',status=201)
  self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome']['leaseUncertain'])
  self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])

 def test_documented_201_malformed_terminal_never_authorizes_retry(self):
  base='decision={protocol_version:3,server_features:[],outcome:"adaptation_unavailable",terminal:{reason:"adaptation_exhausted",message:"synthetic-private-message",retryable:false}}:'
  for mutation in ['decision.terminal.Delete("message")','decision.Delete("server_features")','decision.session_id=invalid']:
   with self.subTest(mutation=mutation):
    r=self.start(base+mutation+':unusedStop=m.responses.Shift()',status=201)
    self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome']['leaseUncertain'])
    self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']])

 def test_documented_201_stop_failure_retains_owner_without_retry(self):
  for stop in ('{statusCode:503,body:"{}"}','{statusCode:200,body:"{}"}','{statusCode:204,body:""}'):
   with self.subTest(stop=stop):
    r=self.start(status=201,stop=stop)
    self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome']['leaseUncertain'])
    self.assertEqual('sess-1',r['outcome']['plan']['sessionId'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])

 def test_undocumented_status_allocated_refusal_never_retries(self):
  for status in (202,204,400,403):
   with self.subTest(status=status):
    r=self.start(status=status)
    self.assertFalse(r['outcome']['ok'])
    self.assertEqual(1,sum('/playback/start' in q['url'] for q in r['requests']))

 def test_documented_201_preserves_cancellation_scope_and_identity_fences(self):
  for race in ('post_cancel','post_source','post_request','stop_pin'):
   with self.subTest(race=race):
    r=self.start(status=201,race=race)
    self.assertFalse(r['outcome']['ok'])
    if race=='post_request':
     # The stop receipt belongs to the changed request, so it cannot grant
     # retry authority and the original refusal remains the reported error.
     self.assertEqual('unsupported_stream',r['outcome']['errorCode'])
     self.assertTrue(r['outcome']['leaseUncertain'])
     self.assertNotIn('cleanupLeaseClosed',r['outcome'])
    else:self.assertEqual('cancelled' if race=='post_cancel' else 'session_changed',r['outcome']['errorCode'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
