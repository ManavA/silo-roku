"""Actual runJob→fresh selection→HTTP seam; dormant rollout is the only policy override."""
import copy,json,re,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from tools.brightscript import run_function
from tests import test_silo_playback_task as legacy
from tests import test_silo_p8_original_transport as p8
ROOT=Path(__file__).resolve().parents[1]
class CompatContinuation(unittest.TestCase):
 def fixture(self):
  session,wire,_=p8.SiloP8OriginalTransportTests().inputs()
  hd=copy.deepcopy(wire['versions'][0]);hd.update(file_id='732',codec_video='h264',codec_audio='aac',resolution='1080p',hdr=False,bitrate=12000,audio_tracks=[dict(codec='aac',language='en',channels=2,layout='stereo',default=True)],video_tracks=[dict(codec='h264',profile='high',level=40,width=1920,height=1080,bit_depth=8,frame_rate='24000/1001',interlaced=False)])
  wire['versions'].append(hd)
  wire['playback_variants']=[dict(variant_id='native',part_count=1,default_file_id='731',parts=[dict(part_index=1,default_file_id='731',versions=wire['versions'])])]
  decision=json.loads((legacy.FIXTURES/'playback_decision_plan.json').read_text());raw=decision['playback_plan'];raw.update(requested_media_file_id='732',effective_media_file_id='732');raw['source']['media_file_id']='732'
  return session,wire,decision
 def job(self,enabled=True,options=None,mutate=None,device=None,features=None,scope=None,race="",http=None,qualification=False,automatic_hdr10=False,p7_enabled=True,aac_enabled=None,host_http=None):
  session,wire,decision=self.fixture()
  if mutate:mutate(wire,decision)
  cap=json.loads((legacy.FIXTURES/'playback_capabilities.json').read_text());cap.update(installation_id='server-install',features=features or [])
  if features:cap['deliveries'].append('server_remux_hls')
  responses=[dict(statusCode=200,body=json.dumps(x)) for x in (wire,cap,decision)]+[dict(statusCode=200,body='{"outcome":"stopped"}')]
  if http:http(responses) # SDK HTTP fixture transcript only.
  sdk=re.sub(r'function TaskUniqueId\([^\n]*\n.*?end function\n','',legacy.BOUNDARIES,count=1,flags=re.S)
  sdk=sdk.replace('return {major:"15",minor:"3",revision:"4",build:"2402"}','return {major:"16",minor:"0",revision:"4",build:"834"}').replace('return "1080p"','return "2160p60"').replace('return m.uuids.Shift()','if m.uuidCounter=invalid then m.uuidCounter=0\n m.uuidCounter++\n return "10000000-0000-4000-8000-"+Right("000000000000"+m.uuidCounter.ToStr(),12)')
  sdk=sdk.replace('    response = m.responses.Shift()','''    if Instr(1,request.url,"/capabilities") > 0
        if m.race="revision" then m.fixtureRevision++
        if m.race="pin"
            changed=FixtureDeepClone(m.fixtureSession):changed.profileToken="synthetic-changed-pin":m.fixtureSession=changed
        end if
    end if
    response = m.responses.Shift()''')
  sdk=sdk.replace('    response = m.responses.Shift()', '\n    if request.method="POST" and Instr(1,request.url,"/playback/start")>0 and m.race="start_output" then FixtureSiloDevice().videoMode="1080p"\n    response = m.responses.Shift()')
  sdk=sdk.replace('    response = m.responses.Shift()', '\n    if request.method="DELETE"\n     if m.race="stop_cancel" then m.top.cancelled=true\n     if m.race="stop_revision" then m.fixtureRevision++\n     if m.race="stop_pin" or m.race="stop_profile"\n      changed=FixtureDeepClone(m.fixtureSession)\n      if m.race="stop_pin" then changed.profileToken="synthetic-new-pin" else changed.profileId="other-profile"\n      m.fixtureSession=changed\n     end if\n    end if\n    response = m.responses.Shift()')
  sdk=sdk.replace('    return m.fixtureSession','    if m.race="before_fetch" and (m.siloPrivateLegacyStartIssued=true or m.siloPrivateLegacyStartPending=true) then m.top.cancelled=true\n    return m.fixtureSession')
  for old,new in (device or {}).items():sdk=sdk.replace(old,new)
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);files=[]
   paths=[ROOT/x.get('uri').removeprefix('pkg:/') for x in ET.parse(ROOT/'components/ApiTask.xml').getroot().findall('script')]
   # Before076 this public policy exists on070 but is not loaded by ApiTask.
   extra=ROOT/'source/core/SiloCompatPlaybackPolicy.brs'
   if extra not in paths:paths.append(extra)
   for path in paths:
    text=path.read_text().replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()')
    if path.name=='ApiTask.brs':text=text.replace('function TaskRokuSiloContext(','function UnusedTaskRokuSiloContext(',1)
    if path.name=='Http.brs':text=text.replace('function HttpRequest(','function UnusedHttpRequest(',1)
    if path.name=='SessionStore.brs':text=text.replace('function LoadSession(','function UnusedLoadSession(',1).replace('function SessionRevision(','function UnusedSessionRevision(',1)
    if qualification:text=text.replace('function SiloOfficialLegacyHDR10QualificationEnabled(','function ShippingSiloOfficialLegacyHDR10QualificationEnabled(',1)
    if automatic_hdr10 is not None:text=text.replace('function SiloP8HDR10AutomaticPreparationEnabled(','function ShippingAutomaticHDR10PreparationEnabled(',1)
    if p7_enabled is not None:
     for gate in ('SiloP7CompatPreparationEnabled','SiloP7AACPreparationEnabled'):
      text=text.replace('function '+gate+'(','function Shipping'+gate+'(',1)
    if enabled is not None:text=text.replace('function SiloCompatPreparationEnabled(','function ShippingSiloCompatPreparationEnabled(',1)
    file=root/path.name;file.write_text(text);files.append(file)
   if automatic_hdr10 is not None:sdk+='\nfunction SiloP8HDR10AutomaticPreparationEnabled() as Boolean\n return '+str(automatic_hdr10).lower()+'\nend function\n'
   if enabled is not None:sdk+='\nfunction SiloCompatPreparationEnabled() as Boolean\n return '+str(enabled).lower()+'\nend function\n'
   if p7_enabled is not None:
    for gate in ('SiloP7CompatPreparationEnabled','SiloP7AACPreparationEnabled'):
     value=p7_enabled if gate=='SiloP7CompatPreparationEnabled' or aac_enabled is None else aac_enabled
     sdk+='\nfunction '+gate+'() as Boolean\n return '+str(value).lower()+'\nend function\n'
   if qualification:sdk+='\nfunction SiloOfficialLegacyHDR10QualificationEnabled() as Boolean\n return true\nend function\n'
   sdk+='''
function RunCompatContinuation(session as Object,wire as Object,responses as Object,options as Object,jobChanges as Object,race as String) as Object
 m.race=race:m.fixtureSession=session:m.fixtureRevision=0:m.requests=[]:m.timeouts=[]:m.responses=responses:m.changeRevision=false
 detail=ScopeCatalogData(DecodeSiloResponse("detail",FormatJson(wire),{sourceId:session.sourceId}).data,session.sourceId)
 params={itemId:"fixture-item",fileId:"731",detail:detail,autoVersion:true,qualityPreference:"original",qualityExplicit:false,subtitleMode:"off",startPositionMs:25000}
 for each key in options
  if options[key]=invalid then params.Delete(key) else params[key]=options[key]
 end for
 jobValue={provider:"silo",action:"playback_start",sourceId:session.sourceId,profileId:session.profileId,generation:7,requestId:41,params:params}
 if options.probeOnly=true
  jobValue.action="experimental_playback_probe"
  jobValue.params={itemId:params.itemId,fileId:params.fileId,detail:params.detail}
  for each key in ["audioTrackId","audioTrackIndex"]
   if params.DoesExist(key) then jobValue.params[key]=params[key]
  end for
 end if
 for each key in jobChanges
  if jobChanges[key]=invalid then jobValue.Delete(key) else jobValue[key]=jobChanges[key]
 end for
 m.top=CreateObject("roSGNode","Node")
 m.top.AddFields({cancelled:false,job:jobValue,result:{}})
 runJob()
 if options.privateControlCheck=true and m.top.result.ok=true
  accepted=m.top.result.plan
  control=TaskReplanSiloPlayback(session,{sessionId:accepted.sessionId,plan:accepted,qualityPreference:"original",positionMs:1000,replanRequestId:"private-control-01",failureClassification:"decoder_failure"},SpScope(jobValue),0)
  return {outcome:control,requests:m.requests}
 end if
 return {pinChanged:m.fixtureSession.profileToken="synthetic-changed-pin",outcome:m.top.result,requests:m.requests,videoQueries:FixtureSiloDevice().videoQueries,audioQueries:FixtureSiloDevice().audioQueries,originalFlag:SiloOriginalActivationEnabled(),p8Flag:SiloP8OriginalActivationEnabled()}
end function
'''
   if host_http is not None:
    sdk=re.sub(r'function HttpRequest\([^\n]*\n.*?end function\n','''function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    response=HostHttpRequest(request,timeoutMs)
    return HttpResponse(request,response.statusCode,response.body)
end function
''',sdk,count=1,flags=re.S)
   file=root/'SDK.brs';file.write_text(sdk);file.chmod(0o600);files.append(file)
   kwargs={'root':root}
   if host_http is not None:kwargs['host_http']=host_http
   return run_function(files,'RunCompatContinuation',[session,wire,responses,options or {},scope or {},race],**kwargs)
 def test_auto_retains_pinned_4k_compat_intent_before_any_native_start(self):
  r=self.job();starts=[(q['method'],json.loads(q['body']).get('file_id')) for q in r['requests'] if '/playback/start' in q['url']]
  self.assertEqual([],starts,'continuation must precede native allocation')
  o=r['outcome'];self.assertFalse(o['ok']);self.assertEqual('compat_prepare_required',o['errorCode']);self.assertNotIn('plan',o)
  c=o['compatContinuation'];self.assertEqual((1,'native_selection_lower_resolution','fixture-item','731'),(c['schemaVersion'],c['reason'],c['itemId'],c['fileId']));self.assertEqual(dict(state='not_allocated'),c['nativeClosure'])
  self.assertEqual(dict(provider='silo',sourceId='silo:https://silo.example',profileId='fixture-owner',generation=7,sessionRevision=0),c['owner']);self.assertEqual(41,c['requestId']);self.assertRegex(c['playbackAttemptId'],r'^roku-[0-9a-f-]{36}$')
  self.assertEqual(('file:731:audio:0',0,25000,'original','off'),(c['audioTrackId'],c['audioTrackIndex'],c['startPositionMs'],c['qualityPreference'],c['subtitleMode']))
  self.assertNotIn('synthetic',json.dumps(c));self.assertNotIn('mediaSourceId',c);self.assertNotIn('sessionId',c);self.assertFalse(r['originalFlag']);self.assertFalse(r['p8Flag'])
 def test_compat_failed_source_stays_available_to_normal_native_selection(self):
  r=self.job(options={'compatExcludedFileIds':['731'],'excludedVersionIds':[]})
  self.assertNotIn('compatContinuation',r['outcome'])
  self.assertEqual(['732'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])

 def test_single_compat_failed_source_gets_one_normal_native_start(self):
  def single(w,d):
   w['versions']=w['versions'][:1];w['playback_variants'][0]['parts'][0]['versions']=w['versions']
   d['playback_plan'].update(requested_media_file_id='731',effective_media_file_id='731')
   d['playback_plan']['source']['media_file_id']='731'
  r=self.job(options={'compatExcludedFileIds':['731'],'excludedVersionIds':[]},mutate=single)
  self.assertNotIn('compatContinuation',r['outcome'])
  self.assertEqual(['731'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])

 def test_compat_exclusion_is_validated_without_erasing_native_exclusion(self):
  for ids in ([],['missing'],['731','731'],[True],['731']*8):
   with self.subTest(ids=ids):
    r=self.job(options={'compatExcludedFileIds':ids})
    self.assertEqual('invalid_request',r['outcome']['errorCode'])
    self.assertFalse(any('/playback/start' in q['url'] for q in r['requests']))
  r=self.job(options={'compatExcludedFileIds':['731'],'excludedVersionIds':['731']})
  self.assertEqual(['732'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])

 def test_repeated_source_refusal_cannot_reenter_compat_and_keeps_native_alternate(self):
  from tests.test_silo_compat_owned_refusal import OwnedRefusal
  r=OwnedRefusal().start(options={'compatExcludedFileIds':['731'],'excludedVersionIds':[]})
  self.assertNotIn('compatContinuation',r['outcome'])
  self.assertEqual(['731','732'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])

 def test_default_off_is_exact_legacy_even_with_caller_enable(self):
  baseline=self.job(enabled=False)
  attempted=self.job(enabled=False,options={'compatPreparationEnabled':True})
  self.assertEqual(baseline['requests'],attempted['requests'])
  self.assertNotIn('compatContinuation',baseline['outcome'])
  self.assertEqual(['732'],[json.loads(q['body'])['file_id'] for q in baseline['requests'] if '/playback/start' in q['url']])
 def test_explicit_quality_cap_subtitle_and_prebuffer_stay_native(self):
  for options in ({'qualityPreference':'720p'},{'bandwidthCapKbps':1000},{'subtitleMode':'on'},{'speculativePrebuffer':True},{'autoVersion':False},{'audioTrackIndex':0,'audioTrackId':'file:731:audio:0'}):
   with self.subTest(options=options):self.assertNotIn('compatContinuation',self.job(options=options)['outcome'])
 def test_unsupported_output_and_scope_never_mint_continuation(self):
  for device in ({'return "2160p60"':'return "1080p"'},{'ModelNumber:"C208X"':'ModelNumber:""'}):
   with self.subTest(device=device):self.assertNotIn('compatContinuation',self.job(device=device)['outcome'])
  for scope in ({'generation':None},{'sourceId':None},{'profileId':None},{'requestId':None}):
   with self.subTest(scope=scope):self.assertNotIn('compatContinuation',self.job(scope=scope)['outcome'])
 def test_unknown_or_ambiguous_source_audio_and_presentation_stay_native(self):
  def no_default(w,d):w['versions'][0]['audio_tracks'][0]['default']=False
  def ambiguous(w,d):w['playback_variants'].append(copy.deepcopy(w['playback_variants'][0]))
  def unknown(w,d):w['versions'][0]['video_tracks'][0].pop('dv_profile',None)
  for mutate in (no_default,ambiguous,unknown):
   with self.subTest(mutate=mutate.__name__):self.assertNotIn('compatContinuation',self.job(mutate=mutate)['outcome'])
 def test_proven_native_4k_sdr_remains_native(self):
  def sdr(w,d):
   v=w['versions'][0];v['hdr']=False
   v['video_tracks']=[dict(codec='hevc',profile='main 10',level=153,width=3840,height=2160,bit_depth=10,frame_rate='24000/1001',interlaced=False)]
  self.assertNotIn('compatContinuation',self.job(mutate=sdr)['outcome'])

 def test_negotiated_native_4k_copy_and_excluded_candidate_remain_native(self):
  r=self.job(features=['native_hls_separate_audio_v1'],device={'major:"16",minor:"0",revision:"4",build:"834"':'major:"15",minor:"3",revision:"4",build:"2402"'})
  self.assertNotIn('compatContinuation',r['outcome'])
  self.assertEqual('731',json.loads(next(q['body'] for q in r['requests'] if '/playback/start' in q['url']))['file_id'])
  self.assertNotIn('compatContinuation',self.job(options={'excludedVersionIds':['731']})['outcome'])
 def test_qualified_explicit_ac3_original_is_not_intercepted(self):
  from tests.test_silo_ordinary_p8_original import OrdinaryP8Original
  def qualified(w,d):
   _,original,decision=OrdinaryP8Original().inputs()
   w['versions'][0]=original['versions'][0];w['playback_variants'][0]['parts'][0]['versions']=w['versions']
   d.clear();d.update(decision)
  r=self.job(mutate=qualified,options={'audioTrackId':'file:731:audio:1','audioTrackIndex':1},device={'(format.codec="aac" and format.passthru=0)':'((format.codec="aac" or format.codec="ac3") and format.passthru=0)','format.chcnt<=2 and format.codec="aac"':'format.chcnt<=2 and (format.codec="aac" or format.codec="ac3")'})
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertNotIn('compatContinuation',r['outcome'])
  self.assertEqual('p8_explicit_ac3_stereo_v1',r['outcome']['plan']['originalPlayback']['qualifiedRoute'])

 def test_fresh_scope_or_pin_drift_before_selection_cannot_publish_intent(self):
  for race in ('revision','pin'):
   with self.subTest(race=race):self.assertNotIn('compatContinuation',self.job(race=race)['outcome'])
