"""Pure owned P7 receipt to experimental stock engine handoff."""
import copy
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import _execute
from tests import test_silo_p7_hdr10_compat_policy as p7
literal=p7.literal

ORIGIN='http://fixture.invalid'
TOKEN='fixture-token'

class SiloStockContextTests(unittest.TestCase):
 def setUp(self):
  self.policy=p7.P7HDR10Policy()
  self.case=self.policy.data()
  self.case['receipt']=self.policy.receipt()
  self.owner=dict(self.case['owner'],holderId='holder-1',attemptId='attempt-1',planGeneration=1)
  self.qualification=dict(schemaVersion=1,kind='stock-p7-ac3-root-v1',approved=True,origin=ORIGIN,transportPolicy="controlled-fixture-v1",transportEvidence="private-controlled-fixture",rootListenerRequired=True,**{key:self.owner[key] for key in ('sourceId','profileId','generation','sessionRevision','holderId','attemptId','planGeneration')})
 def run_cases(self,cases):
  body='answers=[]\nfor each c in '+literal(cases)+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind)\nif c.DoesExist("canonicalStock") then p=SiloCompatStockPreparation(p,c.canonicalStock,c.params.startPositionMs)\nif c.DoesExist("proofStartOverride") then p.startTicks=c.proofStartOverride\nhandoff=SiloCompatStockContext(c.receipt,p,c.baseUrl,c.observedChildUrl,c.audioIndex,c.token,c.handoffOwner,c.qualification)\nif handoff=invalid then answers.Push(invalid) else answers.Push({upstreamStartTicks:p.startTicks,handoff:handoff,engineValid:QaStockContextValid(handoff.context),reference:QaStockMediaReference(handoff.context.playlist,handoff.context.playlist,handoff.context.origin,handoff.context.routeItemId,handoff.context.mediaSourceId,handoff.context.sessionId)})\nend for\nprint FormatJson(answers)'
  with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
   folder=Path(directory);sdk=folder/'sdk.brs';sdk.write_text(p7.modern.SDK)
   prefix,expression=body.rsplit('print FormatJson(',1)
   exp=p7.ROOT/'tools/experiments/onroku_audio/multi_app/source'
   return _execute([*p7.modern.FILES,p7.ROOT/'source/adapters/SiloCompatAdapter.brs',sdk,exp/'RemoteIngest.brs',exp/'StockDescriptor.brs'],prefix,folder,expression[:-1])['result']
 def valid(self):
  source='03000000-0000-0000-0000-0000000002db'
  child=ORIGIN+'/Videos/'+source+'/remux-dv-v1/hls/play-fixture/stream.m3u8?MediaSourceId='+source+'&PlaySessionId=play-fixture'
  return dict(self.case,baseUrl=ORIGIN,observedChildUrl=child,audioIndex=2,token=TOKEN,handoffOwner=self.owner,qualification=self.qualification)
 def test_bookmark_is_owned_separately_from_canonical_zero_upstream(self):
  c=copy.deepcopy(self.valid());c['params']['startPositionMs']=17875;c['canonicalStock']=True
  c['qualification']['requestedStartPositionMs']=17875
  result=self.run_cases([c])[0]
  self.assertEqual(17875,result['handoff']['startPositionMs'])
  self.assertEqual(0,result['upstreamStartTicks'])
  self.assertTrue(result['engineValid'])
  c['qualification']['requestedStartPositionMs']=17000
  self.assertEqual([None],self.run_cases([c]))
 def test_nonstock_preparation_preserves_server_bookmark(self):
  case=copy.deepcopy(self.case);case['params']['startPositionMs']=17875
  proof=self.policy.candidates([case])[0]
  with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
   folder=Path(directory);sdk=folder/'sdk.brs';sdk.write_text(p7.modern.SDK)
   out=_execute([*p7.modern.FILES,sdk], 'p=SiloCompatStockPreparation('+literal(proof)+',false,17875)',folder,'p')['result']
  self.assertEqual(178750000,out['startTicks'])
  self.assertNotIn('requestedStartPositionMs',out)
 def test_master_parser_observes_one_variant_and_rejects_foreign_or_malformed_data(self):
  case=self.valid();master=ORIGIN+'/Videos/03000000-0000-0000-0000-0000000002db/remux-dv-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId=03000000-0000-0000-0000-0000000002db'
  child=case['observedChildUrl'];path=child.removeprefix(ORIGIN+'/Videos/03000000-0000-0000-0000-0000000002db/remux-dv-v1/')
  bodies=['#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n'+path+'\n','#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nhttps://foreign.invalid/stream.m3u8\n','#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n'+path+'\n#EXT-X-STREAM-INF:BANDWIDTH=2000\n'+path+'\n','not a playlist',None,False,{}]
  # Run the public parser through the same pure BrightScript policy seam.
  script='answers=[]\nfor each body in '+literal(bodies)+'\nanswers.Push(SiloCompatStockMasterChild(body,'+literal(master)+'))\nend for\nprint FormatJson(answers)'
  with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
   folder=Path(directory);sdk=folder/'sdk.brs';sdk.write_text(p7.modern.SDK)
   prefix,expr=script.rsplit('print FormatJson(',1)
   result=_execute([*p7.modern.FILES,p7.ROOT/'source/adapters/SiloCompatAdapter.brs',sdk],prefix,folder,expr[:-1])['result']
  self.assertEqual(child,result[0]);self.assertEqual([None]*6,result[1:])
 def stock_task_case(self,body=None,status=200,qualification=None,generation=1,cancel_after=False,scope_after=False,proof_start=None,changed="",bookmark=None):
  case=self.valid();proof=self.policy.candidates([self.case])[0]
  master=ORIGIN+'/Videos/'+proof['mediaSourceId']+'/remux-dv-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId='+proof['mediaSourceId']
  if body is None:body='#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n'+case['observedChildUrl'].removeprefix(ORIGIN+'/Videos/'+proof['mediaSourceId']+'/remux-dv-v1/')+'\n'
  if proof_start is not None:proof['startTicks']=proof_start
  if bookmark is not None:proof['requestedStartPositionMs']=bookmark
  sdk='''
function SessionRevision(provider as String) as Integer
 return 0
end function
function LoadSession(provider as String) as Object
 return m.fixtureSession
end function
function HttpRequest(request as Object,timeoutMs=0 as Integer) as Object
 m.fetchSawUncertain=m.compatBindingReleased and m.compatEverReleased and m.compatStartUncertain
 m.fetchUrl=request.url:m.fetchAuthorization=request.headers.Authorization
 if m.fixtureCancelAfter then m.top.cancelled=true
 if m.fixtureScopeAfter then m.fixtureSession.profileId="other"
 return {ok:m.fixtureStatus=200,statusCode:m.fixtureStatus,body:m.fixtureBody}
end function
'''
  script='''
m.compatOwner=ParseJson("OWNER")
m.compatHolder="holder-1":m.compatAttempt="attempt-1":m.compatGeneration=1
m.compatProof=ParseJson("PROOF"):m.compatReceipt=ParseJson("RECEIPT")
m.compatAudioIndex=2:m.compatBinding={url:"MASTER"}
m.compatSession={sourceId:m.compatOwner.sourceId,profileId:m.compatOwner.profileId,baseUrl:"BASE",profileToken:"pin",compatConnectInfo:{publicUrl:"BASE"}}
m.fixtureSession={sourceId:m.compatOwner.sourceId,profileId:m.compatOwner.profileId,baseUrl:"BASE",profileToken:"pin"}
m.compatToken="fixture-token":m.compatSecret="":m.compatCollectUncertain=false:m.compatLogoutAcknowledged=false
m.compatPrepared=true:m.compatBindingReleased=false:m.compatEverReleased=false:m.compatStartUncertain=false:m.compatMediaRetired=false
m.compatPlaySession="play-fixture":m.fixtureBody="BODY":m.fixtureStatus=STATUS:m.fixtureCancelAfter=CANCEL:m.fixtureScopeAfter=SCOPE
m.top={cancelled:false,privateStockContext:invalid,privateBinding:invalid}
GetGlobalAA().config=ParseJson("CONFIG"):GetGlobalAA().queries=[]
m.compatProof.snapshot=SiloCompatSnapshotForKind(Device(),m.compatProof.audio,SpField(m.compatProof,"eligibilityKind"),m.compatProof.video)
command={planGeneration:GENERATION,qualification:CompatStockQualification()}
if ParseJson("QUAL")<>invalid then command.qualification=ParseJson("QUAL")
CHANGED
outcome=CompatPrepareStockContext(command)
observed={outcome:outcome,fetchSawUncertain:m.fetchSawUncertain,fetchUrl:m.fetchUrl,fetchAuthorization:m.fetchAuthorization,privateContext:m.top.privateStockContext,everReleased:m.compatEverReleased}
closed=CompatClose()
observed["close"]=closed
observed["privateClearedAfterClose"]=m.top.privateStockContext=invalid
observed["credentialHeld"]=m.compatToken<>""
print FormatJson(observed)
'''
  import json
  for key,value in {'OWNER':self.owner,'PROOF':proof,'RECEIPT':self.case['receipt'],'QUAL':qualification,'CONFIG':self.policy.config()}.items():script=script.replace('ParseJson("'+key+'")',literal(value))
  script=script.replace('"MASTER"',literal(master)).replace('"BASE"',literal(ORIGIN)).replace('"BODY"',literal(body))
  script=script.replace('CHANGED',changed)
  script=script.replace('STATUS',str(status)).replace('CANCEL','true' if cancel_after else 'false').replace('SCOPE','true' if scope_after else 'false').replace('GENERATION',str(generation))
  with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
   folder=Path(directory);sdkfile=folder/'sdk.brs';sdkfile.write_text(p7.modern.SDK+sdk)
   prefix,expr=script.rsplit('print FormatJson(',1)
   task=folder/'task.brs';task.write_text((p7.ROOT/'components/SiloCompatTask.brs').read_text().replace('CreateObject("roDeviceInfo")','Device()').replace('transportPolicy:"native-bearer-origin-scope-v1"','transportPolicy:"controlled-fixture-v1"').replace('transportEvidence:"c208x-16.0.4-842-redirect-chains-v1"','transportEvidence:"private-controlled-fixture"').replace('function CompatStockTransportQualified(', 'function UnusedCompatStockTransportQualified(',1)+'\nfunction CompatStockTransportQualified(baseUrl as Dynamic) as Boolean\n return baseUrl="'+ORIGIN+'"\nend function\n')
   result=_execute([*p7.modern.FILES,p7.ROOT/'source/adapters/SiloCompatAdapter.brs',task,sdkfile],prefix,folder,expr.strip()[:-1])['result']
  return result
 def test_task_retains_bookmark_in_qualified_private_handoff(self):
  result=self.stock_task_case(bookmark=17875)
  self.assertTrue(result['outcome']['ok'],result)
  self.assertEqual(17875,result['privateContext']['startPositionMs'])
 def test_owned_master_fetch_marks_media_uncertain_before_request_and_close(self):
  result=self.stock_task_case()
  self.assertTrue(result['outcome']['ok'],result)
  self.assertNotIn(TOKEN,str(result['outcome']))
  self.assertNotIn('master.m3u8',str(result['outcome']))
  self.assertTrue(result['fetchSawUncertain']);self.assertIn('/master.m3u8?',result['fetchUrl'])
  self.assertEqual('Bearer fixture-token',result['fetchAuthorization'])
  self.assertEqual('bearer',result['privateContext']['context']['authMode'])
  self.assertFalse(result['close']['ok']);self.assertTrue(result['close']['cleanupUnconfirmed'])
  self.assertFalse(result['close']['mediaNeverRequested']);self.assertTrue(result['credentialHeld'])
  self.assertTrue(result['privateClearedAfterClose'])
 def test_owned_master_refusals_preserve_media_cleanup_or_skip_fetch(self):
  foreign='#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nhttps://foreign.invalid/stream.m3u8\n'
  wrong='#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nhls/wrong/stream.m3u8\n'
  after=[dict(status=500),dict(body='bad master'),dict(body=foreign),dict(body=wrong),dict(cancel_after=True),dict(scope_after=True)]
  for settings in after:
   with self.subTest(settings=settings):
    result=self.stock_task_case(**settings)
    self.assertFalse(result['outcome']['ok']);self.assertTrue(result['fetchSawUncertain'])
    self.assertIsNone(result['privateContext']);self.assertTrue(result['outcome']['cleanupUnconfirmed'])
    self.assertFalse(result['close']['ok']);self.assertFalse(result['close']['mediaNeverRequested']);self.assertTrue(result['credentialHeld'])
    self.assertTrue(result['privateClearedAfterClose'])
  malformed=copy.deepcopy(self.qualification);malformed['approved']=1
  before=[dict(generation=2),dict(qualification=malformed),dict(proof_start=False)]
  for settings in before:
   with self.subTest(settings=settings):
    result=self.stock_task_case(**settings)
    self.assertFalse(result['outcome']['ok']);self.assertIsNone(result['fetchUrl'])
    self.assertFalse(result['everReleased']);self.assertTrue(result['close']['mediaNeverRequested'])
 def test_runtime_authority_rechecks_source_owner_origin_selected_audio_and_capabilities(self):
  for mutation in ['m.compatProof.ownerBinding.profileId="other"','m.compatProof.ownerBinding.sessionRevision=1','m.fixtureSession.sourceId="other"','m.compatSession.compatConnectInfo.publicUrl="http://other.invalid"','m.compatAudioIndex=3','GetGlobalAA().config.display={hdr10:false}']:
   with self.subTest(mutation=mutation):
    result=self.stock_task_case(changed=mutation)
    self.assertFalse(result['outcome']['ok'])
    self.assertIsNone(result['fetchUrl'])
    self.assertIsNone(result['privateContext'])
 def test_canonical_receipt_yields_bound_bearer_context_and_child_playlist(self):
  result=self.run_cases([self.valid()])[0]
  self.assertTrue(result['engineValid'])
  out=result['handoff']
  self.assertEqual(out['context']['playlist'],result['reference'])
  self.assertEqual('bearer',out['context']['authMode'])
  self.assertEqual(TOKEN,out['context']['token'])
  self.assertEqual(out['context']['routeItemId'],out['context']['mediaSourceId'])
  self.assertEqual('play-fixture',out['context']['sessionId'])
  self.assertEqual(self.owner,out['owner'])
  self.assertEqual(2,out['audioStreamIndex'])
  self.assertEqual(0,out['startPositionMs'])
  self.assertEqual(ORIGIN+'/Videos/'+out['context']['mediaSourceId']+'/remux-dv-v1/hls/play-fixture/stream.m3u8?MediaSourceId='+out['context']['mediaSourceId']+'&PlaySessionId=play-fixture',out['context']['playlist'])
  self.assertNotIn(TOKEN,out['context']['playlist'])
 def test_observed_child_accepts_engine_supported_query_order(self):
  case=self.valid()
  case['observedChildUrl']=case['observedChildUrl'].replace('?MediaSourceId=03000000-0000-0000-0000-0000000002db&PlaySessionId=play-fixture','?PlaySessionId=play-fixture&MediaSourceId=03000000-0000-0000-0000-0000000002db')
  result=self.run_cases([case])[0]
  self.assertTrue(result['engineValid'])
  self.assertEqual(case['observedChildUrl'],result['handoff']['context']['playlist'])
  self.assertEqual(case['observedChildUrl'],result['reference'])
 def test_refuses_scope_audio_session_origin_start_and_unqualified_contracts(self):
  cases=[]
  def changed(fn):
   c=copy.deepcopy(self.valid());fn(c);cases.append(c)
  for malformed in (False,None,'0'):
   changed(lambda c,value=malformed:c.update(proofStartOverride=value))
  changed(lambda c:c['qualification'].update(profileId='other'))
  changed(lambda c:c['handoffOwner'].update(profileId='other'))
  changed(lambda c:c.update(observedChildUrl=c['observedChildUrl'].replace('stream.m3u8','other.m3u8')))
  changed(lambda c:c.update(observedChildUrl=c['observedChildUrl'].replace('play-fixture','other')))
  changed(lambda c:c['qualification'].update(approved=1))
  changed(lambda c:c['qualification'].update(schemaVersion=True))
  changed(lambda c:c['qualification'].update(sourceId='silo:other'))
  changed(lambda c:c['qualification'].update(attemptId='other'))
  changed(lambda c:c['qualification'].update(planGeneration=2))
  changed(lambda c:c.update(audioIndex=3))
  changed(lambda c:c['receipt'].update(PlaySessionId='other'))
  changed(lambda c:c.update(baseUrl='http://other.invalid'))
  changed(lambda c:c['params'].update(startPositionMs=1000))
  changed(lambda c:c['qualification'].update(rootListenerRequired=False))
  changed(lambda c:c['qualification'].update(transportPolicy="unqualified"))
  changed(lambda c:c['qualification'].update(kind='unknown'))
  changed(lambda c:c['qualification'].update(version='48ae'))
  changed(lambda c:c.update(token='bad\r\nheader'))
  changed(lambda c:c.update(baseUrl=ORIGIN+'/prefix'))
  changed(lambda c:c.update(kind='experimental_query_p7_hdr10_aac_fmp4_v1'))
  self.assertEqual([None]*len(cases),self.run_cases(cases))
