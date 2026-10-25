"""Selected-source AAC2 projection at actual runJob/SDK/HTTP boundaries.

Synthetic official V3 DTOs: source EAC3/6 stays selected; audio_to_aac v4
changes only output audio. No physical sound or resolution claim is made.
"""
import copy,json,unittest
from tests import test_silo_compat_continuation as task

EXACT_GENERIC='if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}'
class AudioProjection(unittest.TestCase):
 def start(self,source=None,receipt=None,probe=None,options=None,race='',features=None,fallback=False):
  def fixture(wire,decision):
   v=copy.deepcopy(wire['versions'][-1]);v.update(container='mkv',codec_audio='eac3',effective_audio_track_index=0,audio_tracks=[dict(codec='eac3',channels=6,layout='5.1',language='en',default=True)])
   if source:source(v)
   wire['versions']=[v];wire['playback_variants']=[dict(variant_id='native',part_count=1,default_file_id='732',parts=[dict(part_index=1,default_file_id='732',versions=[v])])]
   p=decision['playback_plan'];p.update(delivery='server_remux_hls',decision_reason='server_remux',selected_tracks={'audio':{'id':'file:732:audio:0','index':0}})
   p['source'].update(container='mkv',video_codec='h264',audio_codec=v['audio_tracks'][0].get('codec','eac3'),audio_channels=v['audio_tracks'][0].get('channels',6),width=1920,height=1080,bit_depth=8,dynamic_range='sdr',dv_enhancement_layer='none')
   p['effective_recipe']=dict(video_codec='h264',audio_codec='aac',audio_channels=2,audio_layout='stereo',width=1920,height=1080,dynamic_range='sdr')
   p['transformations']=[dict(name='hls_mpegts',executor='server',recipe_version='1',validated_claims=None),dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode'])]
   p['stream'].update(protocol='hls',container='hls');p['subtitle']={'mode':'off','inventory':[]}
   if receipt:receipt(p)
  def replies(responses):
   if not fallback:return
   caps=json.loads(responses[1]['body']);caps['deliveries'].append('server_transcode_hls');responses[1]['body']=json.dumps(caps)
   final=json.loads(responses[2]['body']);p=final['playback_plan']
   p.update(delivery='server_transcode_hls',plan_id='plan-fixture-02',plan_attempt_key='plan-key-fixture-02',transformations=[dict(name='video_to_h264',executor='server',recipe_version='2',validated_claims=None),dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode'])])
   # 102 requalifies the lower plain request: only AAC2 is proven here.
   p['effective_recipe'].update(audio_channels=2,audio_layout='stereo')
   responses.extend([copy.deepcopy(responses[0]),copy.deepcopy(responses[1]),dict(statusCode=200,body=json.dumps(final))])
  device={EXACT_GENERIC:probe or 'if format.chcnt <> invalid then return {result:format.codec="aac" and format.chcnt=2 and format.container="ts" and format.passthru=0}\n'+EXACT_GENERIC}
  selected=dict(fileId='732',autoVersion=False,qualityPreference='original',qualityExplicit=True,audioTrackId='file:732:audio:0',audioTrackIndex=0,bandwidthCapKbps=50000)
  selected.update(options or {})
  if race in ('post_pin','post_cancel'):
   from unittest.mock import patch
   effect='m.top.cancelled=true' if race=='post_cancel' else 'm.fixtureSession=MergeSessionPatch(m.fixtureSession,{profileToken:"synthetic-new-pin"})'
   sdk=task.legacy.BOUNDARIES.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if request.method="POST" and Instr(1,request.url,"/playback/start")>0 then '+effect)
   with patch.object(task.legacy,'BOUNDARIES',sdk):
    return task.CompatContinuation().job(enabled=False,options=selected,mutate=fixture,features=['native_hls_mpegts_v1'] if features is None else features,device=device,http=replies)
  return task.CompatContinuation().job(enabled=False,options=selected,mutate=fixture,features=['native_hls_mpegts_v1'] if features is None else features,device=device,race=race,http=replies)
 def bodies(self,r):return [json.loads(q['body']) for q in r['requests'] if q['method']=='POST' and '/playback/start' in q['url']]
 def test_unsupported_selected_surround_posts_aac2_and_accepts_same_program_copy_recipe(self):
  r=self.start();b=self.bodies(r);self.assertEqual(1,len(b),r['outcome']);body=b[0]
  self.assertEqual(['aac'],body['client_capabilities']['codecs_audio'])
  hls=body['client_playback_context']['deliveries']['hls']
  self.assertEqual((['aac'],[],2),(hls['audio_decode_codecs'],hls['audio_passthrough_codecs'],hls.get('max_channels')))
  self.assertFalse(body['client_playback_context']['deliveries']['original_http']['enabled'])
  self.assertEqual(('732','file:732:audio:0',0,'original',50000),(body['file_id'],body['audio_track_id'],body['audio_track_index'],body['quality_preference'],body['bandwidth_cap_kbps']))
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual('732',r['outcome']['plan']['versionId'])
  self.assertFalse(any(q['method']=='DELETE' for q in r['requests']))
  self.assertEqual({'fileId':'732','container':'mkv','audio':{'id':'file:732:audio:0','index':0,'codec':'eac3','channels':6}},r['outcome']['plan']['sourceAudioProjection'])
 def replan(self,source=None,receipt=None,probe=None,race='',hint='current',fallback=False,quality='original'):
  from unittest.mock import patch
  from tests import test_silo_replan_task as recovery
  p=recovery.SiloReplanTaskTests().params();p['qualityPreference']=quality
  p['plan']['siloPlayback']['bandwidthCapKbps']=50000
  if fallback:
   p['failureClassification']='decoder_failure';p['plan']['allowQualityFallback']=True
   p['plan']['siloPlayback']['availableQualities'].append({'label':'1080p','preservesSource':False,'height':1080,'bitrateKbps':8000})
  if hint is not None:p['plan']['sourceAudioProjection']={'fileId':'f1','container':'mkv','audio':{'id':'file:f1:audio:0' if hint=='current' else 'file:f1:audio:1','index':0 if hint=='current' else 1,'codec':'eac3','channels':6}}
  wire=json.loads((recovery.ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
  v=wire['versions'][0];v.update(container='mkv',codec_video='h264',codec_audio='eac3',resolution='1080p',hdr=False,bitrate=12000,audio_tracks=[dict(codec='eac3',channels=6,layout='5.1',language='en',default=True)],video_tracks=[dict(codec='h264',profile='high',level=40,width=1920,height=1080,bit_depth=8,frame_rate='24000/1001',interlaced=False)])
  if source:source(v)
  raw=json.loads((recovery.ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text());plan=raw['playback_plan']
  plan['selected_tracks']=copy.deepcopy(p['plan']['siloPlayback']['selectedTracks'])
  plan.update(delivery='server_remux_hls',decision_reason='server_remux')
  plan['source'].update(container='mkv',video_codec='h264',audio_codec=v['audio_tracks'][0].get('codec','eac3'),audio_channels=v['audio_tracks'][0].get('channels',6),width=1920,height=1080,bit_depth=8,dynamic_range='sdr',dv_enhancement_layer='none')
  plan['effective_recipe']=dict(video_codec='h264',audio_codec='aac',audio_channels=2,audio_layout='stereo',width=1920,height=1080,dynamic_range='sdr')
  plan['stream'].update(protocol='hls',container='hls');plan['subtitle']={'mode':'off','inventory':[]}
  plan['transformations']=[dict(name='hls_mpegts',executor='server',recipe_version='1',validated_claims=None),dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode'])]
  if fallback:
   plan['available_qualities']=[{'label':'original','preserves_source':True},{'label':'1080p','preserves_source':False,'height':1080,'bitrate_kbps':8000}]
  if receipt:receipt(plan)
  response=json.dumps(dict(statusCode=200,body=json.dumps(wire)))
  literal='ParseJson('+('"'+response.replace('"','""')+'"')+')'
  boundary=recovery.BOUNDARY.replace('m.requests=[]:m.timeouts=[]:m.responses=responses', 'responses=[responses[0],'+literal+',responses[1]]\n m.requests=[]:m.timeouts=[]:m.responses=responses').replace('outcome=ExecuteApiAction("silo",action,params,scope)', '''job={provider:"silo",action:action,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,requestId:41,params:params}
 m.top=CreateObject("roSGNode","Node"):m.top.AddFields({cancelled:false,job:job,result:{}})
 runJob():outcome=m.top.result''')
  if hint!='current':boundary=boundary.replace('responses=[responses[0],'+literal+',responses[1]]', 'responses=responses')
  if fallback:boundary=boundary.replace('responses=[responses[0],'+literal+',responses[1]]','responses=[responses[0],'+literal+',responses[1],responses[2]]')
  sdk=recovery.legacy.BOUNDARIES.replace(EXACT_GENERIC,probe or 'if format.chcnt <> invalid then return {result:format.codec="aac" and format.chcnt=2 and format.container="ts" and format.passthru=0}\n'+EXACT_GENERIC)
  if race:
   point=2 if race=='detail_pin' else 3
   change='m.top.cancelled=true' if race=='post_cancel' else 'm.fixtureSession=MergeSessionPatch(m.fixtureSession,{profileToken:"synthetic-new-pin"})'
   sdk=sdk.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if m.requests.Count()='+str(point)+' then '+change)
  with patch.object(recovery,'BOUNDARY',boundary),patch.object(recovery.legacy,'BOUNDARIES',sdk):
   final=copy.deepcopy(raw) if fallback else None
   if final:
    final['session_id']='session-0001'
    final['playback_plan']['effective_recipe'].update(audio_channels=2,audio_layout='stereo')
    final['playback_plan'].update(plan_id='plan-0003',plan_attempt_key='plan-key-0003',delivery='server_transcode_hls',transformations=[dict(name='video_to_h264',executor='server',recipe_version='2',validated_claims=None),dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode'])])
   return recovery.SiloReplanTaskTests().call(params=p,decision=raw,capability_features=[] if fallback else ['native_hls_mpegts_v1'],followup=final,advance_current=fallback)
 def test_replan_projects_fresh_selected_surround_without_replacing_lease(self):
  r=self.replan();self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']],r['outcome'])
  self.assertTrue(r['outcome']['ok'],r['outcome'])
  body=json.loads(r['requests'][-1]['body']);hls=body['client_playback_context']['deliveries']['hls']
  self.assertEqual((['aac'],[],2),(hls['audio_decode_codecs'],hls['audio_passthrough_codecs'],hls.get('max_channels')))
  self.assertEqual('original',body['quality_preference']);self.assertEqual(50000,body['bandwidth_cap_kbps']);self.assertEqual(12.5,body['position_seconds'])
  self.assertEqual({'audio':{'id':'file:f1:audio:0','index':0}},body['selected_tracks'])
  self.assertEqual('session-0001',r['outcome']['plan']['sessionId'])
 def test_supported_source_decode_or_passthrough_never_projects_stereo(self):
  for codec,mode,container in [('eac3',0,'ts'),('eac3',1,'mkv'),('ac3',1,'ts')]:
   with self.subTest(codec=codec,mode=mode,container=container):
    probe='if format.chcnt <> invalid then return {result:(format.codec="aac" and format.chcnt=2 and format.passthru=0) or (format.codec="'+codec+'" and format.chcnt=6 and format.passthru='+str(mode)+' and format.container="'+container+'")}\n'+EXACT_GENERIC
    r=self.start(source=lambda v:v['audio_tracks'][0].update(codec=codec),probe=probe)
    hls=self.bodies(r)[0]['client_playback_context']['deliveries']['hls']
    self.assertNotIn('max_channels',hls);self.assertEqual(['eac3'],hls['audio_passthrough_codecs'])
    self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']])
 def test_known_conversion_codecs_preserve_source_program_and_force_aac2(self):
  for codec in ['aac','dts','truehd']:
   with self.subTest(codec=codec):
    r=self.start(source=lambda v:v['audio_tracks'][0].update(codec=codec))
    self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(1,len(self.bodies(r)))
    self.assertEqual(2,self.bodies(r)[0]['client_playback_context']['deliveries']['hls']['max_channels'])
 def test_unknown_source_and_missing_aac_output_proof_do_not_project(self):
  cases=[dict(source=lambda v:v['audio_tracks'][0].pop('channels')),dict(source=lambda v:v['audio_tracks'][0].update(channels=0)),dict(source=lambda v:v['audio_tracks'][0].update(channels=1)),dict(source=lambda v:v['audio_tracks'][0].pop('codec')),dict(source=lambda v:v['audio_tracks'][0].update(codec='unknown')),dict(probe='if format.chcnt <> invalid then return {result:false}\n'+EXACT_GENERIC),dict(probe='if format.chcnt <> invalid then return {result:"true"}\n'+EXACT_GENERIC),dict(options={'qualityPreference':'1080p_high'})]
  for case in cases:
   with self.subTest(case=cases.index(case)):
    r=self.start(**case);b=self.bodies(r)
    self.assertEqual(1,len(b),r['outcome']);self.assertNotIn('max_channels',b[0]['client_playback_context']['deliveries']['hls'])
 def test_single_source_is_eligible_but_unselected_multi_program_is_unchanged(self):
  r=self.start(options={'audioTrackId':None,'audioTrackIndex':None});self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual(2,self.bodies(r)[0]['client_playback_context']['deliveries']['hls']['max_channels'])
  def multi(v):v['audio_tracks'].append(dict(codec='eac3',channels=6,language='fr',default=False))
  r=self.start(source=multi,options={'audioTrackId':None,'audioTrackIndex':None})
  self.assertNotIn('max_channels',self.bodies(r)[0]['client_playback_context']['deliveries']['hls'])
 def test_wrong_returned_source_pair_or_output_is_owned_refused(self):
  changes=[lambda p:p['selected_tracks']['audio'].update(index=1,id='file:732:audio:1'),lambda p:p['source'].update(audio_codec='ac3'),lambda p:p['source'].update(audio_channels=8),lambda p:p['effective_recipe'].update(audio_channels=6),lambda p:p['effective_recipe'].update(audio_layout='5.1'),lambda p:p.update(transformations=[p['transformations'][0]])]
  for change in changes:
   with self.subTest(change=changes.index(change)):
    r=self.start(receipt=change);self.assertFalse(r['outcome']['ok']);self.assertNotIn('plan',r['outcome'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']]);self.assertEqual(1,len(self.bodies(r)))
 def test_unknown_source_query_is_not_a_positive_route_but_output_must_be_positive(self):
  probe='if format.chcnt <> invalid\n if format.codec="aac" and format.chcnt=2 and format.container="ts" and format.passthru=0 then return {result:true}\n return {}\n end if\n'+EXACT_GENERIC
  r=self.start(probe=probe);self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(2,self.bodies(r)[0]['client_playback_context']['deliveries']['hls']['max_channels'])
 def test_ordinary_replan_without_matching_hint_adds_no_inventory_request(self):
  for hint in (None,'stale'):
   with self.subTest(hint=hint):
    r=self.replan(hint=hint);self.assertTrue(r['outcome']['ok'],r['outcome'])
    self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']])
    body=json.loads(r['requests'][-1]['body']);self.assertNotIn('max_channels',body['client_playback_context']['deliveries']['hls'])
    self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
 def test_replan_new_positive_source_drops_prior_stereo_hint(self):
  probe='if format.chcnt <> invalid then return {result:(format.codec="eac3" and format.chcnt=6 and format.passthru=1) or (format.codec="aac" and format.chcnt=2 and format.passthru=0)}\n'+EXACT_GENERIC
  r=self.replan(probe=probe);self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertNotIn('max_channels',json.loads(r['requests'][-1]['body'])['client_playback_context']['deliveries']['hls'])
  self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
 def test_replan_wrong_audio_receipt_retains_returned_control_without_delete(self):
  r=self.replan(receipt=lambda p:p['effective_recipe'].update(audio_channels=6))
  self.assertFalse(r['outcome']['ok']);self.assertNotIn('plan',r['outcome']);self.assertTrue(r['outcome']['leaseUncertain'])
  self.assertEqual('plan-0002',r['outcome']['controlReceipt']['planId'])
  self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']])
 def test_late_pin_or_cancel_keeps_allocated_cleanup_authority(self):
  for race in ['post_pin','post_cancel']:
   with self.subTest(race=race):
    r=self.start(race=race);self.assertFalse(r['outcome']['ok']);self.assertNotIn('plan',r['outcome'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
    r=self.replan(race=race);self.assertFalse(r['outcome']['ok']);self.assertNotIn('plan',r['outcome']);self.assertTrue(r['outcome']['leaseUncertain'])
    self.assertEqual('plan-0002',r['outcome']['controlReceipt']['planId']);self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']])
 def test_no_fork_feature_never_authorizes_native_remux_receipt(self):
  r=self.start(features=[]);self.assertFalse(r['outcome']['ok']);self.assertNotIn('plan',r['outcome'])
  self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
 def test_replan_fresh_detail_pin_change_cannot_post(self):
  r=self.replan(race='detail_pin');self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','GET'],[q['method'] for q in r['requests']]);self.assertNotIn('plan',r['outcome'])
 def test_uppercase_raw_container_accepts_lowercase_actual_source_receipt(self):
  for action in ('start','replan'):
   for container in ('MKV','MOV','M4V'):
    with self.subTest(action=action,container=container):
     r=getattr(self,action)(source=lambda v:v.update(container=container),receipt=lambda p:p['source'].update(container=container.lower()))
     self.assertTrue(r['outcome']['ok'],r['outcome'])
     self.assertEqual(container.lower(),r['outcome']['plan']['sourceAudioProjection']['container'])
     if action=='start' and container!='MKV':
      self.assertTrue(any(q.get('codec')=='eac3' and q.get('chcnt')==6 and q.get('container')=='mp4' for q in r['audioQueries']))
 def test_projected_legacy_refusal_keeps_acknowledged_start_quality_fallback(self):
  r=self.start(features=[],fallback=True,options={'qualityExplicit':False})
  self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual(['GET','GET','POST','DELETE','GET','GET','POST'],[q['method'] for q in r['requests']])
  bodies=self.bodies(r);self.assertEqual(['original','1080p'],[b['quality_preference'] for b in bodies])
  self.assertEqual(2,bodies[-1]['client_playback_context']['deliveries']['hls']['max_channels'])
  self.assertEqual(['732','732'],[b['file_id'] for b in bodies]);self.assertTrue(all(b['audio_track_id']=='file:732:audio:0' for b in bodies))
 def test_projected_replan_refusal_keeps_newest_control_for_existing_quality_fallback(self):
  r=self.replan(fallback=True);self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual(['GET','GET','POST','POST'],[q['method'] for q in r['requests']])
  bodies=[json.loads(q['body']) for q in r['requests'] if q['method']=='POST']
  self.assertEqual(['original','1080p'],[b['quality_preference'] for b in bodies])
  self.assertEqual(2,bodies[-1]['client_playback_context']['deliveries']['hls']['max_channels'])
  self.assertEqual(['plan-0001','plan-0002'],[b['failed_plan_id'] for b in bodies]);self.assertEqual(2,bodies[-1]['attempt_count'])
  self.assertEqual(['plan-key-0001','plan-key-0002'],bodies[-1]['attempted_plan_keys'])
  self.assertEqual('session-0001',r['outcome']['plan']['sessionId']);self.assertEqual({'fileId','container','audio'},set(r['outcome']['plan']['sourceAudioProjection']))
