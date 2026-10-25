"""Actual Task/HTTP seam: source-bound MP4 proof, not model authority."""
import copy,json,unittest
from tests import test_silo_compat_continuation as task
class Mp4Route(unittest.TestCase):
 def start(self,source_change=None,receipt_change=None,audio_probe=None,options=None,all_video=False,race=""):
  def fixture(wire,decision):
   hd=copy.deepcopy(wire['versions'][-1]);hd['container']='mp4'
   wire['versions']=[hd];wire['playback_variants']=[dict(variant_id='native',part_count=1,default_file_id='732',parts=[dict(part_index=1,default_file_id='732',versions=[hd])])]
   plan=decision['playback_plan'];plan.update(delivery='original_http',requested_media_file_id='732',effective_media_file_id='732')
   plan['source'].update(media_file_id='732',video_codec='h264',audio_codec='aac',audio_channels=2,width=1920,height=1080,hdr10_plus=False,dv_enhancement_layer='none',bit_depth=8,dynamic_range='sdr')
   plan['stream'].update(protocol='original_http',container='mp4')
   plan['selected_tracks']={'audio':{'id':'file:732:audio:0','index':0}}
   plan['subtitle']={'mode':'off'}
   if source_change:source_change(hd,wire)
   if receipt_change:receipt_change(plan)
  def replies(responses):
   caps=json.loads(responses[1]['body']);caps.update(deliveries=['original_http'],features=[]);responses[1]['body']=json.dumps(caps)
   if race=='post_refresh_pin':
    responses.insert(2,dict(statusCode=401,body='{}'))
    responses.insert(3,dict(statusCode=200,body=(task.ROOT/'tests/fixtures/silo/refresh.json').read_text()))
  device={'return {result:true}':'return {result:format.codec="mpeg4 avc"}',
   'if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}':'return {result:format.codec="aac" and format.container="mp4" and format.passthru=0 and (format.chcnt=invalid or format.chcnt=2)}'}
  if audio_probe:device['if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}']=audio_probe
  if all_video:device['return {result:true}']='return {result:true}'
  selected=dict(fileId='732',autoVersion=False,startPositionMs=0);selected.update(options or {})
  if race in ('late_pin','late_cancel','post_refresh_pin'):
   from unittest.mock import patch
   change='m.top.cancelled=true' if race=='late_cancel' else 'm.fixtureSession=FixtureDeepClone(m.fixtureSession):m.fixtureSession.profileToken="synthetic-changed-pin"'
   condition='m.requests.Count()=4' if race=='post_refresh_pin' else 'request.method="POST" and Instr(1,request.url,"/playback/start")>0'
   sdk=task.legacy.BOUNDARIES.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if '+condition+' then '+change)
   if race=='post_refresh_pin':sdk=sdk.replace('function LoadSession(provider as String) as Object','function LoadSession(provider as String) as Object\n m.fixtureSession["refreshToken"]="synthetic-refresh"')
   with patch.object(task.legacy,'BOUNDARIES',sdk):
    return task.CompatContinuation().job(enabled=False,options=selected,mutate=fixture,device=device,http=replies,race=race)
  return task.CompatContinuation().job(enabled=False,options=selected,mutate=fixture,device=device,http=replies,race=race)
 def test_selected_mp4_aac2_allocates_without_mkv_or_ts_capability(self):
  result=self.start();requests=[r for r in result['requests'] if '/playback/start' in r['url']]
  self.assertEqual(1,len(requests),result['outcome'])
  body=json.loads(requests[0]['body']);caps=body['client_capabilities'];delivery=body['client_playback_context']['deliveries']
  self.assertEqual(['mp4'],caps['containers']);self.assertEqual(['aac'],caps['codecs_audio'])
  self.assertEqual(['mp4'],delivery['original_http']['containers']);self.assertEqual(['h264'],delivery['original_http']['video_codecs'])
  self.assertEqual(['aac'],delivery['original_http']['audio_decode_codecs']);self.assertEqual(2,delivery['original_http']['max_channels'])
  self.assertFalse(delivery['hls']['enabled']);self.assertFalse(delivery['progressive']['enabled'])
  self.assertTrue(result['outcome']['ok'],result['outcome'])

 def replan(self,wire_index=0,race="",refresh=False,receipt_change=None,expect_ok=True):
  from unittest.mock import patch
  from tests import test_silo_replan_task as recovery
  params=recovery.SiloReplanTaskTests().params();params['qualityPreference']='original'
  params['plan']['siloPlayback']['subtitleOffRequired']=True
  params['plan']['siloPlayback']['selectedTracks']={'audio':{'id':'file:f1:audio:0','index':0}}
  wire=json.loads((recovery.ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
  version=wire['versions'][0];version.update(container='mp4',codec_video='h264',codec_audio='aac',resolution='1080p',hdr=False,bitrate=12000,audio_tracks=[dict(index=wire_index,codec='aac',channels=2,default=True)],video_tracks=[dict(codec='h264',profile='high',level=40,width=1920,height=1080,bit_depth=8,frame_rate='24000/1001',interlaced=False)])
  raw=json.loads((recovery.ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text());plan=raw['playback_plan'];plan['selected_tracks']=copy.deepcopy(params['plan']['siloPlayback']['selectedTracks']);plan['stream']['container']='mp4';plan['subtitle']={'mode':'off'};plan['source'].update(video_codec='h264',audio_codec='aac',audio_channels=2,width=1920,height=1080,bit_depth=8,dynamic_range='sdr',dv_enhancement_layer='none')
  if receipt_change:receipt_change(plan)
  response=json.dumps(dict(statusCode=200,body=json.dumps(wire)))
  boundary=recovery.BOUNDARY.replace('m.requests=[]:m.timeouts=[]:m.responses=responses', 'responses=[responses[0],ParseJson('+('"'+response.replace('"','""')+'"')+'),responses[1]]\n m.requests=[]:m.timeouts=[]:m.responses=responses').replace('outcome=ExecuteApiAction("silo",action,params,scope)', '''job={provider:"silo",action:action,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,requestId:41,params:params}
 m.top=CreateObject("roSGNode","Node"):m.top.AddFields({cancelled:false,job:job,result:{}})
 runJob():outcome=m.top.result''')
  sdk=recovery.legacy.BOUNDARIES.replace('if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}','return {result:format.codec="aac" and format.container="mp4" and format.passthru=0 and (format.chcnt=invalid or format.chcnt=2)}')
  if refresh:
   refresh_reply=json.dumps(dict(statusCode=200,body=(recovery.ROOT/'tests/fixtures/silo/refresh.json').read_text()))
   fresh_literal='ParseJson('+('"'+response.replace('"','""')+'"')+')'
   refresh_literal='ParseJson('+('"'+refresh_reply.replace('"','""')+'"')+')'
   injected='responses=[responses[0],{statusCode:401,body:"{}"},'+refresh_literal+','+fresh_literal+',responses[1]]'
   if refresh=='post':injected='responses=[responses[0],'+fresh_literal+',{statusCode:401,body:"{}"},'+refresh_literal+',responses[1]]'
   boundary=boundary.replace('responses=[responses[0],'+fresh_literal+',responses[1]]',injected)
  if race:
   point=4 if race in ('post_refresh_pin','post_refresh_cancel') else (3 if race in ('refresh_pin','late_pin','late_cancel') else 2)
   change='m.top.cancelled=true' if race in ('cancel','late_cancel','post_refresh_cancel') else 'm.fixtureSession=MergeSessionPatch(m.fixtureSession,{profileToken:"synthetic-new-pin"})'
   sdk=sdk.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if m.requests.Count()='+str(point)+' then '+change)
  boundary=boundary.replace('return {outcome:outcome,requests:', 'return {pinChanged:m.fixtureSession.profileToken="synthetic-new-pin",outcome:outcome,requests:')
  with patch.object(recovery,'BOUNDARY',boundary),patch.object(recovery.legacy,'BOUNDARIES',sdk):
   result=recovery.SiloReplanTaskTests().call(params=params,decision=raw,capability_features=[],capability_deliveries=['original_http'])
  if race or not expect_ok:return result
  expected=['GET','GET','POST','GET','POST'] if refresh else ['GET','GET','POST']
  if refresh=='post':expected=['GET','GET','POST','POST','POST']
  self.assertEqual(expected,[r['method'] for r in result['requests']],result['outcome'])
  self.assertTrue(result['outcome']['ok'],result['outcome'])
  body=json.loads(result['requests'][-1]['body']);self.assertEqual(['mp4'],body['client_capabilities']['containers']);self.assertEqual(2,body['client_playback_context']['deliveries']['original_http']['max_channels'])

 def test_replan_refreshes_same_file_before_mp4_only_original_request(self):
  self.replan()
 def test_replan_matches_audio_ordinal_not_optional_wire_index(self):
  self.replan(wire_index=1)
 def test_wrong_mp4_receipt_is_owned_rejected_without_second_start(self):
  result=self.start(receipt_change=lambda plan:plan['source'].update(audio_channels=6))
  self.assertFalse(result['outcome']['ok'],result['outcome'])
  self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
 def test_unknown_surround_or_nonmp4_source_cannot_borrow_mp4_evidence(self):
  changes=[lambda v,w:v.update(container='mkv'),lambda v,w:v.update(codec_video='hevc'),lambda v,w:v.update(hdr=True),lambda v,w:v['audio_tracks'][0].update(channels=6),lambda v,w:v['video_tracks'][0].pop('profile'),lambda v,w:v['video_tracks'][0].update(width=3840),lambda v,w:v['audio_tracks'].append(dict(codec='aac',channels=2))]
  for change in changes:
   with self.subTest(change=changes.index(change)):
    result=self.start(source_change=change)
    self.assertEqual('unsupported_device',result['outcome']['errorCode'])
    self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))
 def test_aac_codec_only_or_passthrough_result_cannot_claim_stereo_decode(self):
  for probe in ['return {result:format.codec="aac" and format.container="mp4" and format.chcnt=invalid and format.passthru=0}','return {result:format.codec="aac" and format.container="mp4" and format.passthru=1}']:
   result=self.start(audio_probe=probe)
   self.assertEqual('unsupported_device',result['outcome']['errorCode']);self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))

 def test_fresh_mp4_detail_refuses_same_revision_pin_change_or_cancel(self):
  for race in ['pin','cancel']:
   result=self.replan(race=race)
   self.assertFalse(result['outcome']['ok'],result['outcome'])
   self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])
 def test_mp4_detail_refresh_preserves_newer_pin_before_save(self):
  result=self.replan(race='refresh_pin',refresh=True)
  self.assertFalse(result['outcome']['ok'],result['outcome']);self.assertTrue(result['pinChanged'])
  self.assertEqual(0,result['saves']);self.assertEqual(['GET','GET','POST'],[r['method'] for r in result['requests']])
 def test_mp4_detail_unchanged_identity_can_refresh_once(self):
  self.replan(refresh=True)
 def test_missing_raw_hdr_or_filtered_malformed_inventory_is_not_fresh_proof(self):
  changes=[lambda v,w:v.pop('hdr'),lambda v,w:v['audio_tracks'].append(None),lambda v,w:v['video_tracks'].append(None)]
  for change in changes:
   with self.subTest(change=changes.index(change)):
    result=self.start(source_change=change)
    self.assertEqual('unsupported_device',result['outcome'].get('errorCode'))
    self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))

 def test_mp4_projection_does_not_claim_hevc_derived_2160p(self):
  result=self.start(all_video=True)
  body=json.loads(next(r['body'] for r in result['requests'] if '/playback/start' in r['url']))
  self.assertEqual('1080p',body['client_capabilities']['max_resolution'])
 def test_positive_cap_requires_known_nonzero_source_bitrate(self):
  for value in [0,None]:
   result=self.start(source_change=lambda v,w:v.update(bitrate=value),options={'bandwidthCapKbps':15000})
   self.assertEqual('unsupported_device',result['outcome']['errorCode'])
   self.assertFalse(any('/playback/start' in r['url'] for r in result['requests']))
 def test_contradictory_sdr8_receipt_is_owned_rejected(self):
  for change in [lambda p:p['source'].update(bit_depth=10),lambda p:p['source'].update(dynamic_range='hdr10'),lambda p:p['source'].update(dv_enhancement_layer='fel'),lambda p:p.update(effective_recipe=dict(video_codec='hevc',audio_codec='aac',dynamic_range='hdr10',width=1920,height=1080))]:
   with self.subTest(index=id(change)):
    result=self.start(receipt_change=change)
    self.assertFalse(result['outcome']['ok'],result['outcome'])
    self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])

 def test_start_late_identity_change_or_cancel_retires_actual_allocated_lease(self):
  for race in ('late_pin','late_cancel'):
   with self.subTest(race=race):
    result=self.start(race=race)
    self.assertFalse(result['outcome']['ok'],result['outcome'])
    self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
    self.assertNotIn('plan',result['outcome'])
 def test_replan_late_identity_change_or_cancel_retains_new_control_receipt(self):
  for race in ('late_pin','late_cancel'):
   with self.subTest(race=race):
    result=self.replan(race=race)
    self.assertFalse(result['outcome']['ok'],result['outcome'])
    self.assertTrue(result['outcome']['leaseUncertain'])
    self.assertEqual('plan-0002',result['outcome']['controlReceipt']['planId'])
    self.assertEqual(['GET','GET','POST'],[r['method'] for r in result['requests']])

 def test_allocating_start_refresh_never_overwrites_newer_pin_or_retries(self):
  result=self.start(race='post_refresh_pin')
  self.assertFalse(result['outcome']['ok']);self.assertEqual('session_changed',result['outcome']['errorCode']);self.assertTrue(result['pinChanged'])
  self.assertEqual(['GET','GET','POST','POST'],[r['method'] for r in result['requests']])
 def test_allocating_replan_refresh_respects_identity_and_cancel_before_retry(self):
  for race in ('post_refresh_pin','post_refresh_cancel'):
   with self.subTest(race=race):
    result=self.replan(race=race,refresh='post')
    self.assertFalse(result['outcome']['ok']);self.assertTrue(result['outcome']['leaseUncertain'])
    self.assertEqual(['GET','GET','POST','POST'],[r['method'] for r in result['requests']])
    if race=='post_refresh_pin':self.assertTrue(result['pinChanged']);self.assertEqual(0,result['saves'])
 def test_allocating_replan_can_refresh_once_when_identity_is_unchanged(self):
  self.replan(refresh='post')
 def test_legacy_absent_or_empty_enhancement_receipt_remains_accepted(self):
  for change in [lambda p:p['source'].pop('dv_enhancement_layer'),lambda p:p['source'].update(dv_enhancement_layer='')]:
   self.assertTrue(self.start(receipt_change=change)['outcome']['ok'])

 def test_unknown_bitrate_does_not_block_uncapped_proven_mp4_source(self):
  self.assertTrue(self.start(source_change=lambda v,w:v.update(bitrate=0))['outcome']['ok'])
