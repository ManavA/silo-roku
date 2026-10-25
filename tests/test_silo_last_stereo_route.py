"""105 last request-only AAC2 HLS path, actual Task/SDK/HTTP seam."""
import json,unittest
from tests import test_silo_audio_projection as audio
EXACT='return {result:format.codec="aac" and format.container="ts" and format.chcnt=2 and format.passthru=0}'
class LastStereo(unittest.TestCase):
 def test_exact_stereo_is_last_start_route_after_generic_and_direct_fail(self):
  r=audio.AudioProjection().start(probe=EXACT)
  self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']],r['outcome'])
  b=audio.AudioProjection().bodies(r)[0];self.assertEqual(['hls'],b['client_capabilities']['containers'])
  self.assertEqual(['aac'],b['client_capabilities']['codecs_audio']);hls=b['client_playback_context']['deliveries']['hls']
  self.assertEqual((['aac'],[],2),(hls['audio_decode_codecs'],hls['audio_passthrough_codecs'],hls['max_channels']))
  self.assertEqual(('732','file:732:audio:0',0,'original',50000),(b['file_id'],b['audio_track_id'],b['audio_track_index'],b['quality_preference'],b['bandwidth_cap_kbps']))
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
 def test_last_stereo_replan_keeps_lease_and_adds_no_detail_read(self):
  r=audio.AudioProjection().replan(probe=EXACT,quality='720p',hint=None)
  self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']],r['outcome'])
  body=json.loads(r['requests'][-1]['body']);self.assertEqual(['hls'],body['client_capabilities']['containers'])
  self.assertEqual(2,body['client_playback_context']['deliveries']['hls']['max_channels'])
  self.assertEqual(('720p',12.5,50000),(body['quality_preference'],body['position_seconds'],body['bandwidth_cap_kbps']))
  self.assertEqual({'audio':{'id':'file:f1:audio:0','index':0}},body['selected_tracks'])
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual('session-0001',r['outcome']['plan']['sessionId']);self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
 def test_normal_and_direct_mp4_routes_bypass_last_stereo_query(self):
  from tests.test_silo_mp4_route import Mp4Route
  r=Mp4Route().start();b=audio.AudioProjection().bodies(r)[0]
  self.assertEqual(['mp4'],b['client_capabilities']['containers']);self.assertFalse(b['client_playback_context']['deliveries']['hls']['enabled'])
  self.assertFalse(any(q.get('codec')=='aac' and q.get('container')=='ts' and q.get('chcnt')==2 for q in r['audioQueries']))
  positive='if format.chcnt <> invalid then return {result:format.codec="eac3" and format.chcnt=6 and format.passthru=1}\n'+audio.EXACT_GENERIC
  r=audio.AudioProjection().start(probe=positive);b=audio.AudioProjection().bodies(r)[0]
  self.assertTrue(b['client_playback_context']['deliveries']['original_http']['enabled']);self.assertNotIn('max_channels',b['client_playback_context']['deliveries']['hls'])
  # Generic discovery already authorized allocation; only the delivered AAC2 receipt is probed.
  receipt_queries=[q for q in r['audioQueries'] if q.get('codec')=='aac' and q.get('container')=='ts' and q.get('chcnt')==2]
  self.assertEqual([0,1],[q['passthru'] for q in receipt_queries])
 def test_false_string_or_missing_stereo_result_never_allocates(self):
  for probe in ('return {result:false}','return {result:"true"}','return {}'):
   with self.subTest(probe=probe):
    r=audio.AudioProjection().start(probe=probe);self.assertEqual('unsupported_device',r['outcome']['errorCode'])
    self.assertEqual(['GET','GET'],[q['method'] for q in r['requests']])
 def test_missing_hls_or_video_authority_cannot_be_created_from_stereo(self):
  r=audio.AudioProjection().start(probe=EXACT,features=[])
  self.assertEqual('unsupported_device',r['outcome']['errorCode']);self.assertEqual(['GET','GET'],[q['method'] for q in r['requests']])
  from unittest.mock import patch
  sdk=audio.task.legacy.BOUNDARIES.replace('return {result:true}','return {result:false}')
  with patch.object(audio.task.legacy,'BOUNDARIES',sdk):r=audio.AudioProjection().start(probe=EXACT)
  self.assertEqual('unsupported_device',r['outcome']['errorCode']);self.assertEqual(['GET','GET'],[q['method'] for q in r['requests']])
 def test_wrong_or_unknown_stereo_output_is_owned_refused(self):
  changes=[lambda p:p['effective_recipe'].pop('audio_channels'),lambda p:p['effective_recipe'].update(audio_channels=1),lambda p:p['effective_recipe'].update(audio_channels=6),lambda p:p['effective_recipe'].update(audio_layout='5.1'),lambda p:p['selected_tracks']['audio'].update(id='opaque-audio')]
  for change in changes:
   with self.subTest(change=changes.index(change)):
    r=audio.AudioProjection().start(probe=EXACT,receipt=change);self.assertFalse(r['outcome']['ok']);self.assertNotIn('plan',r['outcome'])
    self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
 def test_known_stereo_copy_needs_no_invented_audio_conversion(self):
  def source(v):v['codec_audio']='aac';v['audio_tracks'][0].update(codec='aac',channels=2,layout='stereo')
  def receipt(p):p['transformations']=[p['transformations'][0]];p['source']['audio_codec']='aac';p['source']['audio_channels']=2
  r=audio.AudioProjection().start(probe=EXACT,source=source,receipt=receipt,options={'audioTrackId':None,'audioTrackIndex':None})
  self.assertTrue(r['outcome']['ok'],r['outcome']);b=audio.AudioProjection().bodies(r)[0]
  self.assertNotIn('audio_track_id',b);self.assertNotIn('audio_track_index',b);self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
  self.assertEqual({'audio':{'id':'file:732:audio:0','index':0}},r['outcome']['plan']['siloPlayback']['selectedTracks'])
 def test_accepted_adapted_output_keeps_the_servers_selected_source_program(self):
  def source(v):v['audio_tracks'].append(dict(codec='aac',channels=2,language='en',layout='stereo',default=False))
  r=audio.AudioProjection().start(probe=EXACT,source=source,options={'audioTrackId':None,'audioTrackIndex':None})
  self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']],r['outcome'])
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual({'audio':{'id':'file:732:audio:0','index':0}},r['outcome']['plan']['siloPlayback']['selectedTracks'])
 def test_unmapped_selected_pair_uses_existing_admission_without_a_new_equation(self):
  def receipt(p):p['selected_tracks']['audio']={'id':'file:732:audio:0','index':1}
  r=audio.AudioProjection().start(probe=EXACT,receipt=receipt,options={'audioTrackId':None,'audioTrackIndex':None})
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual({'audio':{'id':'file:732:audio:0','index':1}},r['outcome']['plan']['siloPlayback']['selectedTracks'])
  self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
 def test_late_pin_and_cancel_keep_allocated_cleanup_authority(self):
  for race in ('post_pin','post_cancel'):
   with self.subTest(race=race):
    r=audio.AudioProjection().start(probe=EXACT,race=race)
    self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
    from unittest.mock import patch
    from tests import test_silo_replan_task as replan
    # Existing SDK event injection point2 is the allocation (there is no Detail).
    sdk=replan.legacy.BOUNDARIES.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if m.requests.Count()=2 then '+('m.top.cancelled=true' if race=='post_cancel' else 'm.fixtureSession=MergeSessionPatch(m.fixtureSession,{profileToken:"synthetic-new-pin"})'))
    with patch.object(replan.legacy,'BOUNDARIES',sdk):r=audio.AudioProjection().replan(probe=EXACT,quality='720p',hint=None)
    self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']]);self.assertEqual('plan-0002',r['outcome']['controlReceipt']['planId']);self.assertTrue(r['outcome']['leaseUncertain'])
 def test_legacy_mux_refusal_keeps_existing_acknowledged_fallback(self):
  r=audio.AudioProjection().start(probe=EXACT,features=[],fallback=True,options={'qualityExplicit':False})
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(['GET','GET','POST','DELETE','GET','GET','POST'],[q['method'] for q in r['requests']])
  self.assertEqual(['original','1080p'],[b['quality_preference'] for b in audio.AudioProjection().bodies(r)]);self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
 def test_replan_fallback_reprobes_stereo_without_mutating_cached_generic_discovery(self):
  from unittest.mock import patch
  from tests import test_silo_replan_task as replan
  boundary=replan.BOUNDARY.replace('return {outcome:outcome,requests:', 'return {audioQueries:FixtureSiloDevice().audioQueries,outcome:outcome,requests:')
  with patch.object(replan,'BOUNDARY',boundary):r=audio.AudioProjection().replan(probe=EXACT,hint=None,fallback=True)
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(['GET','POST','POST'],[q['method'] for q in r['requests']])
  bodies=[json.loads(q['body']) for q in r['requests'] if q['method']=='POST'];self.assertEqual(['plan-0001','plan-0002'],[b['failed_plan_id'] for b in bodies]);self.assertEqual(2,bodies[-1]['attempt_count'])
  self.assertEqual(['plan-key-0001','plan-key-0002'],bodies[-1]['attempted_plan_keys']);self.assertTrue(all(b['client_capabilities']['containers']==['hls'] for b in bodies))
  # Each allocation probes rescue decode, then the admitted receipt probes decode.
  self.assertEqual(4,sum(q.get('codec')=='aac' and q.get('container')=='ts' and q.get('chcnt')==2 for q in r['audioQueries']))
  self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
 def test_failed_stop_after_unsupported_mux_blocks_another_start(self):
  from unittest.mock import patch
  sdk=audio.task.legacy.BOUNDARIES.replace('response = m.responses.Shift()','response = m.responses.Shift()\n if request.method="DELETE" then response={statusCode:500,body:"{}"}')
  with patch.object(audio.task.legacy,'BOUNDARIES',sdk):r=audio.AudioProjection().start(probe=EXACT,features=[],fallback=True,options={'qualityExplicit':False})
  self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']]);self.assertEqual('sess-1',r['outcome']['plan']['sessionId'])

 def test_unknown_source_count_requires_actual_known_output_not_source_fabrication(self):
  def source(v):v['audio_tracks'][0].pop('channels')
  r=audio.AudioProjection().start(probe=EXACT,source=source,receipt=lambda p:p['source'].update(audio_channels=0),options={'audioTrackId':None,'audioTrackIndex':None})
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
  def unknown_copy(p):p['transformations']=[p['transformations'][0]];p['source'].update(audio_codec='aac',audio_channels=0);p['effective_recipe'].pop('audio_channels')
  def aac_source(v):v['codec_audio']='aac';v['audio_tracks'][0]['codec']='aac';v['audio_tracks'][0].pop('channels')
  r=audio.AudioProjection().start(probe=EXACT,source=aac_source,receipt=unknown_copy,options={'audioTrackId':None,'audioTrackIndex':None})
  self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
 def test_old_source_hint_and_surround_answer_cannot_upgrade_minimum_rescue(self):
  from unittest.mock import patch
  from tests import test_silo_replan_task as replan
  # SDK transcript has caps+plan only; a105 source Detail read is forbidden.
  boundary=replan.BOUNDARY.replace('m.requests=[]:', 'm.requests=[] :',1)
  probe='return {result:format.codec="aac" and format.container="ts" and (format.chcnt=2 or format.chcnt=6) and format.passthru=0}'
  with patch.object(replan,'BOUNDARY',boundary):r=audio.AudioProjection().replan(probe=probe,quality='720p',hint='current')
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']]);self.assertEqual(2,json.loads(r['requests'][-1]['body'])['client_playback_context']['deliveries']['hls']['max_channels'])
  self.assertNotIn('sourceAudioProjection',r['outcome']['plan'])
 def test_explicit_experimental_original_does_not_enter_hls_rescue(self):
  r=audio.AudioProjection().start(probe=EXACT,options={'experimentalOriginal':True})
  self.assertFalse(r['outcome']['ok']);self.assertFalse(any(q['method']=='POST' for q in r['requests']))
  self.assertFalse(any(q.get('codec')=='aac' and q.get('container')=='ts' and q.get('chcnt')==2 for q in (r.get('audioQueries') or [])))

 def test_unusable_allocated_lease_cannot_authorize_a_second_start(self):
  from unittest.mock import patch
  sdk=audio.task.legacy.BOUNDARIES.replace('response = m.responses.Shift()', '''response = m.responses.Shift()
    if request.method="POST" and Instr(1,request.url,"/playback/start")>0 and m.requests.Count()=3
        decision=ParseJson(response.body)
        decision.Delete("session_id"):decision.playback_plan.Delete("session_id")
        response.body=FormatJson(decision)
        unusedStop=m.responses.Shift()
    end if''')
  with patch.object(audio.task.legacy,'BOUNDARIES',sdk):r=audio.AudioProjection().start(probe=EXACT,features=[],fallback=True,options={'qualityExplicit':False})
  self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome'].get('leaseUncertain'))
  self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']]);self.assertEqual(1,len(audio.AudioProjection().bodies(r)))
 def test_oversized_hls_delivery_with_contradictory_protocol_and_no_lease_never_retries(self):
  from unittest.mock import patch
  sdk=audio.task.legacy.BOUNDARIES.replace('response = m.responses.Shift()', '''response = m.responses.Shift()
    if request.method="POST" and Instr(1,request.url,"/playback/start")>0 and m.requests.Count()=3
        decision=ParseJson(response.body)
        decision.Delete("session_id"):decision.playback_plan.Delete("session_id")
        decision.playback_plan.stream.protocol="http"
        decision.playback_plan.effective_recipe.width=3840
        response.body=FormatJson(decision)
        unusedStop=m.responses.Shift()
    end if''')
  with patch.object(audio.task.legacy,'BOUNDARIES',sdk):r=audio.AudioProjection().start(probe=EXACT,features=[],fallback=True,options={'qualityExplicit':False})
  self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome'].get('leaseUncertain'))
  self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']]);self.assertEqual(1,len(audio.AudioProjection().bodies(r)))
 def test_replan_unknown_output_retains_latest_control_receipt(self):
  r=audio.AudioProjection().replan(probe=EXACT,quality='720p',hint=None,receipt=lambda p:p['effective_recipe'].update(audio_channels=6))
  self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome']['leaseUncertain']);self.assertEqual('plan-0002',r['outcome']['controlReceipt']['planId'])
  self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']])
