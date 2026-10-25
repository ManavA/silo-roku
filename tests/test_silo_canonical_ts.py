"""Upstream copy-TS negotiation through the native API start seam."""
import unittest
from tests import test_silo_native_hdr10 as native

CANONICAL = 'hls_copy_mpegts_v1'

class CanonicalTS(unittest.TestCase):
 def start(self, features=None, change=None, **kwargs):
  def receipt(raw):
   raw['effective_recipe'].pop('video_sample_entry',None)
   raw['effective_recipe']['segment_container']='mpegts'
   raw['transformations']=[t for t in raw['transformations'] if t['name']!='hls_separate_audio']
   if change:change(raw)
  return native.NativeHdr10().start(features=[CANONICAL] if features is None else features,receipt=receipt,**kwargs)
 def test_canonical_start_negotiates_delivery_without_fork_opt_in(self):
  r=self.start();starts=native.NativeHdr10().starts(r)
  self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual('731',starts[0]['file_id'])
  hls=starts[0]['client_playback_context']['deliveries']['hls']
  self.assertIn(CANONICAL,hls['features'])
  self.assertNotIn(CANONICAL,starts[0]['client_features'])

 def test_canonical_start_requires_actual_ts_hevc_decode(self):
  r=self.start(device={'m.videoQueries.Push(format)':'m.videoQueries.Push(format)\n if format.codec="hevc" and format.container="ts" then return {result:false}'})
  self.assertFalse(r['outcome']['ok'],r['outcome'])

 def test_canonical_receipt_needs_ts_decode_even_when_split_is_available(self):
  r=self.start(features=[CANONICAL,'native_hls_separate_audio_v1'],device={'m.videoQueries.Push(format)':'m.videoQueries.Push(format)\n if format.codec="hevc" and format.container="ts" then return {result:false}'})
  self.assertFalse(r['outcome']['ok'],r['outcome'].get('errorCode'))

 def test_capability_absent_and_fork_only_never_accept_canonical_receipt(self):
  for features in ([],['native_hls_mpegts_v1'],['native_hls_separate_audio_v1']):
   with self.subTest(features=features):
    r=self.start(features=features,options={'autoVersion':False,'qualityExplicit':True})
    self.assertFalse(r['outcome']['ok'])
    self.assertNotIn('plan',r['outcome'])
 def test_fork_receipts_keep_their_own_negotiation_with_both_features(self):
  for features in (['native_hls_separate_audio_v1'],[CANONICAL,'native_hls_separate_audio_v1']):
   with self.subTest(features=features):
    r=native.NativeHdr10().start(features=features)
    self.assertTrue(r['outcome']['ok'],r['outcome'].get('errorCode'))
    self.assertEqual(CANONICAL in features,r['outcome']['plan']['startRequestFacts']['copyMpegts'])
 def test_canonical_start_rejects_malformed_or_unrequested_byte_recipes(self):
  changes=[lambda raw:raw['effective_recipe'].pop('segment_container'),
   lambda raw:raw['effective_recipe'].update(segment_container='fmp4'),
   lambda raw:raw['effective_recipe'].update(segment_container=4),
   lambda raw:raw['effective_recipe'].update(video_sample_entry='hvc1'),
   lambda raw:raw['effective_recipe'].update(dynamic_range='dolby_vision'),
   lambda raw:raw['transformations'].append(dict(name='hls_mpegts',executor='server',recipe_version='1')),
   lambda raw:raw['transformations'].append(dict(name='server_dv7_to_dv81',executor='server',recipe_version='1'))]
  for index,change in enumerate(changes):
   with self.subTest(index=index):
    r=self.start(change=change,options={'autoVersion':False,'qualityExplicit':True})
    self.assertFalse(r['outcome']['ok'])
    self.assertNotIn('plan',r['outcome'])

 def test_canonical_missing_source_refuses_without_worker_failure(self):
  r=self.start(change=lambda raw:raw.pop('source'),options={'autoVersion':False,'qualityExplicit':True})
  self.assertFalse(r['outcome']['ok'])
  self.assertNotEqual('task_failed',r['outcome'].get('errorCode'))

 def test_canonical_copy_requires_matching_safe_source_video(self):
  changes=[lambda source:source.pop('video_codec'),
   lambda source:source.update(video_codec='h264'),
   lambda source:source.update(video_codec=4),
   lambda source:source.update(video_copy_unsafe=True)]
  for index,change in enumerate(changes):
   with self.subTest(index=index):
    r=self.start(change=lambda raw:change(raw['source']),options={'autoVersion':False,'qualityExplicit':True})
    self.assertFalse(r['outcome']['ok'])
    self.assertNotIn('plan',r['outcome'])
 def test_canonical_hdr10_strip_recipe_two_remains_supported(self):
  def strip(raw):
   raw['transformations']=[dict(name='server_dv7_to_hdr10',executor='server',recipe_version='2')]
   raw['source'].update(dolby_vision_profile=7,dv_bl_compat_id=6,dv_enhancement_layer='unknown')
  r=self.start(change=strip,video={'dv_profile':7,'dv_bl_compat_id':6},options={'autoVersion':False,'qualityExplicit':True})
  self.assertTrue(r['outcome']['ok'],r['outcome'].get('errorCode'))
  self.assertEqual('hdr10',r['outcome']['plan']['playbackDiagnostics']['recipeRange'])

class CanonicalTSControl(unittest.TestCase):
 def scenario(self, *, features=None, change=None, action=None):
  from tests import test_silo_seek_reanchor_task as seek
  fixture=seek.SiloSeekReanchorTaskTests()
  initial=fixture.decision()
  returned=fixture.decision(125.375,124,plan_id='plan-0002' if action else 'plan-0001',key='plan-key-0002' if action else 'plan-key-0001')
  for decision in (initial,returned):
   raw=decision['playback_plan']
   raw['effective_recipe'].update(video_codec='h264',dynamic_range='sdr',width=1280,height=720,segment_container='mpegts')
   raw['effective_recipe'].pop('video_sample_entry')
   raw['source'].update(video_codec='h264',video_profile='high',video_level=40,dynamic_range='sdr',width=1280,height=720)
   raw['transformations']=[]
  if change:change(returned['playback_plan'])
  return fixture.run_seek(initial=initial,returned=returned,cap_features=features or [CANONICAL,'seek_reanchor_v1'],config={'action':action} if action else {})
 def test_canonical_seek_freezes_container_and_does_not_echo_native_feature(self):
  import json
  r=self.scenario()
  self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual('mpegts',r['start']['seekReanchor']['route']['recipe']['segment_container'])
  self.assertEqual('mpegts',r['outcome']['plan']['seekReanchor']['route']['recipe']['segment_container'])
  for request in r['requests']:
   if request['method']=='POST':
    body=json.loads(request['body']);self.assertNotIn(CANONICAL,body['client_features'])
    self.assertIn(CANONICAL,body['client_playback_context']['deliveries']['hls']['features'])
 def test_canonical_quality_replan_uses_fresh_negotiation(self):
  r=self.scenario(action='playback_replan')
  self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual('mpegts',r['outcome']['plan']['seekReanchor']['route']['recipe']['segment_container'])
 def test_canonical_seek_rejects_changed_container(self):
  r=self.scenario(change=lambda raw:raw['effective_recipe'].pop('segment_container'))
  self.assertFalse(r['outcome']['ok'])

 def test_canonical_container_does_not_enable_encoded_video(self):
  def encoded(raw):
   raw['delivery']='server_transcode_hls'
   raw['effective_recipe'].update(audio_codec='aac',audio_channels=2)
   raw['transformations']=[dict(name='video_to_h264',executor='server',recipe_version='2'),dict(name='audio_to_aac',executor='server',recipe_version='4')]
  r=self.scenario(action='playback_replan',change=encoded)
  self.assertFalse(r['outcome']['ok'])

class CanonicalTSLevel50(unittest.TestCase):
 def test_unknown_generic_can_use_exact_source_bound_canonical_ts(self):
  from tests import test_silo_level50_unknown_generic as level
  def canonical(raw):
   raw['effective_recipe'].pop('video_sample_entry',None)
   raw['effective_recipe']['segment_container']='mpegts'
   raw['transformations']=[]
  r=level.Level50UnknownGeneric().start(features=[CANONICAL],receipt_change=canonical)
  self.assertTrue(r['outcome']['ok'],r['outcome'].get('errorCode'))
  self.assertEqual('731',r['outcome']['plan']['versionId'])
