"""Native P8 HDR10 eligibility through actual runJob/SDK/HTTP, not playback proof.

Source contract: cce24de plan_v3.go canStripDolbyVisionToHDR10V3 includes P8
compatibility1, and actual server strip recipe2 uses server_dv7_to_hdr10.
No DV8 output bound, decoder success, or compatibility activation is invented.
"""
import copy,json,unittest
from tests import test_silo_compat_continuation as continuation
from tests import test_silo_p8_original_transport as transport

class NativeHdr10(unittest.TestCase):
 def start(self,*,video=None,options=None,features=None,device=None,receipt=None,bitrate=None):
  def fixture(wire,decision):
   if bitrate is not None:wire['versions'][0]['bitrate']=bitrate
   track=wire['versions'][0]['video_tracks'][0]
   for key,value in (video or {}).items():
    if value is None:track.pop(key,None)
    else:track[key]=value
   _,_,accepted=transport.SiloP8OriginalTransportTests().inputs()
   raw=accepted['playback_plan']
   raw.update(delivery='server_remux_hls',decision_reason='server_remux')
   raw['stream'].update(protocol='hls',container='hls',url='/api/v2/playback/transcode/fixture/master.m3u8?st=synthetic')
   raw['effective_recipe'].update(video_codec='hevc',audio_codec='eac3',dynamic_range='hdr10',video_sample_entry='hvc1')
   raw['source']['height']=track.get('height',2160);raw['effective_recipe']['height']=track.get('height',2160)
   raw['transformations']=[dict(name='server_dv7_to_hdr10',executor='server',recipe_version='2'),dict(name='hls_separate_audio',executor='server',recipe_version='1')]
   if receipt:receipt(raw)
   decision.clear();decision.update(accepted)
  hdr10_device={'DolbyVision:true':'DolbyVision:false'}
  hdr10_device.update(device or {})
  return continuation.CompatContinuation().job(enabled=True,mutate=fixture,options=options,features=['native_hls_separate_audio_v1'] if features is None else features,device=hdr10_device)
 def starts(self,r):return [json.loads(q['body']) for q in r['requests'] if '/playback/start' in q['url']]
 def test_os16_native_hdr10_attempt_precedes_compat_and_accepts_actual_strip_receipt(self):
  r=self.start();starts=self.starts(r)
  self.assertEqual(['731'],[q['file_id'] for q in starts],r['outcome'])
  self.assertEqual('original',starts[0]['quality_preference'])
  hls=starts[0]['client_playback_context']['deliveries']['hls']
  self.assertTrue(hls['hdr_details']['hdr10']);self.assertNotIn(8,hls['hdr_details']['dolby_vision_profiles'])
  self.assertEqual([],starts[0]['client_playback_context']['deliveries']['original_http']['validated_claims'])
  self.assertNotIn('compatContinuation',r['outcome']);self.assertTrue(r['outcome']['ok'],r['outcome'])
  self.assertEqual(('731','hls'),(r['outcome']['plan']['versionId'],r['outcome']['plan']['streamFormat']))
  self.assertEqual(0,sum(q['method']=='DELETE' for q in r['requests']))
 def test_unproven_hdr10_base_never_gets_native_4k_attempt(self):
  controls=[dict(dv_profile=5,dv_bl_compat_id=0),dict(dv_bl_compat_id=0),dict(dv_bl_compat_id=4),dict(dv_el_present=True),dict(dv_enhancement_layer='fel'),dict(dv_enhancement_layer=None),dict(dv_rpu_present=False),dict(dv_bl_present=None),dict(dv_config_present=None),dict(dv_bl_compat_id_present=None),dict(color_transfer='arib-std-b67'),dict(color_primaries='bt709'),dict(color_space=None),dict(hdr10_plus=True),dict(frame_rate='60'),dict(bit_depth=8),dict(dv_level=7)]
  for video in controls:
   with self.subTest(video=video):self.assertNotIn('731',[q['file_id'] for q in self.starts(self.start(video=video,device={'DolbyVision:true':'DolbyVision:false'} if video.get('dv_profile')==5 else None))])
 def test_copy_negotiation_hdr10_output_and_intent_are_required(self):
  for inputs in [dict(features=[]),dict(features=['native_hls_mpegts_v1']),dict(device={'Hdr10:true':'Hdr10:false'}),dict(options={'bandwidthCapKbps':1000}),dict(options={'qualityPreference':'720p','qualityExplicit':True})]:
   with self.subTest(inputs=inputs):
    r=self.start(**inputs)
    native=self.starts(r)
    if inputs.get('options',{}).get('qualityPreference')=='720p':self.assertTrue(all(q['quality_preference']=='720p' for q in native))
    elif inputs.get('options',{}).get('bandwidthCapKbps')==1000:
     self.assertEqual([('731','original',1000)],[(q['file_id'],q['quality_preference'],q['bandwidth_cap_kbps']) for q in native])
     self.assertTrue(r['outcome']['ok'],r['outcome'])
     plan=r['outcome']['plan']
     self.assertEqual({'delivery':'server_remux_hls','recipeRange':'hdr10'},plan['playbackDiagnostics'])
     self.assertEqual(('hls',1000),(plan['streamFormat'],plan['siloPlayback']['bandwidthCapKbps']))
     self.assertNotIn('originalPlayback',plan)
    else:self.assertNotIn('731',[q['file_id'] for q in native])
 def test_letterboxed_source_height_remains_pinned_in_hdr10_attempt(self):
  r=self.start(video={'height':1600})
  self.assertEqual('731',self.starts(r)[0]['file_id']);self.assertNotIn('compatContinuation',r['outcome'])
 def test_refused_pinned_recipe_uses_existing_owned_stop_and_never_claims_playable(self):
  def refused(raw):raw['transformations'][0]['recipe_version']='999'
  r=self.start(options={'autoVersion':False,'qualityExplicit':True},receipt=refused)
  self.assertFalse(r['outcome']['ok']);self.assertNotIn('plan',r['outcome']);self.assertNotIn('compatContinuation',r['outcome'])
  self.assertEqual(['731'],[q['file_id'] for q in self.starts(r)])
  stops=[q for q in r['requests'] if q['method']=='DELETE']
  self.assertEqual(1,len(stops));self.assertTrue(stops[0]['url'].endswith('/playback/session-fixture-01'))
  body=json.loads(stops[0]['body']);self.assertEqual('server-install',body['installation_id']);self.assertRegex(body['stop_id'],r'^[0-9a-f-]{36}$')
  self.assertFalse({'position','sequence','is_paused'} & body.keys())

 def test_new_hdr10_attempt_obeys_exact_source_copy_cap_boundary(self):
  for cap,allowed in ((0,False),(54000,True),(53999,False)):
   with self.subTest(cap=cap):
    r=self.start(options={'bandwidthCapKbps':cap});starts=self.starts(r)
    self.assertEqual(allowed,any(q['file_id']=='731' for q in starts))
    self.assertTrue(all(q['bandwidth_cap_kbps']==cap for q in starts))
    if allowed:self.assertTrue(r['outcome']['ok'],r['outcome'])
    if cap==0:self.assertEqual('invalid_request',r['outcome']['errorCode']) # Existing public options require a positive explicit cap.
  r=self.start(bitrate=0,options={'bandwidthCapKbps':54000})
  self.assertNotIn('731',[q['file_id'] for q in self.starts(r)])
