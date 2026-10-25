"""Private Task/adapter checkpoint; muxed HLS audio remains unqualified."""
import json, unittest
from tests import test_silo_compat_continuation as continuation
from tests import test_silo_p8_original_transport as transport

class OfficialLegacyHDR10(unittest.TestCase):
 def job(self, enabled=True, video=None, receipt=None, options=None, device=None, race='', http=None, source=None):
  def fixture(wire, decision):
   wire['versions'][0].update(source or {})
   wire['versions'][0]['video_tracks'][0].update(video or {})
   _,_,accepted=transport.SiloP8OriginalTransportTests().inputs()
   raw=accepted['playback_plan']
   raw.update(delivery='server_remux_hls',decision_reason='container_normalization')
   raw['stream'].update(protocol='hls',container='hls',mime_type='application/vnd.apple.mpegurl',url='/api/v2/playback/transcode/session-fixture-01/master.m3u8')
   raw['effective_recipe'].update(video_sample_entry='hvc1',dynamic_range='hdr10')
   raw['claims']={'video':{'hdr10':True,'dolby_vision':False}}
   raw['transformations']=[dict(name='server_dv7_to_hdr10',executor='server',recipe_version='2',validated_claims=['dolby_vision_metadata_removed','hdr10_base_layer_preserved','enhancement_layer_discarded'])]
   if receipt:receipt(raw)
   decision.clear();decision.update(accepted)
  intent=dict(privateLegacyHdr10=True,autoVersion=False,audioTrackIndex=0,audioTrackId='file:731:audio:0',startPositionMs=0,qualityExplicit=True)
  intent.update(options or {})
  return continuation.CompatContinuation().job(enabled=False,qualification=enabled,mutate=fixture,features=[],options=intent,device=device,race=race,http=http)
 def starts(self,r): return [json.loads(q['body']) for q in r['requests'] if '/playback/start' in q['url']]
 def test_private_actual_request_and_adapter_accept_exact_strip(self):
  r=self.job();self.assertTrue(r['outcome']['ok'],r['outcome'])
  starts=self.starts(r);self.assertEqual(1,len(starts));q=starts[0]
  self.assertEqual(('731','original',0), (q['file_id'],q['quality_preference'],q['audio_track_index']))
  c=q['client_playback_context'];self.assertFalse(c['deliveries']['progressive']['enabled']);self.assertFalse(c['deliveries']['original_http']['enabled'])
  self.assertEqual(['native_hls_playback_v1'],c['deliveries']['hls']['features']);self.assertEqual(['hevc'],c['deliveries']['hls']['video_codecs'])
  self.assertEqual([],c['output']['hdr_details']['dolby_vision_profiles'])
  self.assertEqual('hls',r['outcome']['plan']['streamFormat']);self.assertNotIn('originalPlayback',r['outcome']['plan'])
  self.assertEqual('unqualified',r['outcome']['plan']['privateLegacyHdr10']['audioAcceptance'])
 def test_disabled_gate_refuses_before_start_even_with_caller_parameter(self):
  r=self.job(enabled=False);self.assertFalse(r['outcome']['ok']);self.assertEqual([],self.starts(r))
 def test_wrong_receipt_is_owned_closed_without_retry(self):
  r=self.job(receipt=lambda raw:raw['effective_recipe'].update(dynamic_range='sdr'))
  self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(self.starts(r)))
  self.assertEqual(1,sum(q['method']=='DELETE' for q in r['requests']))
 def test_unproven_source_or_intent_never_allocates(self):
  for args in [dict(video={'dv_bl_compat_id':4}),dict(video={'dv_el_present':True}),dict(video={'color_transfer':'arib-std-b67'}),dict(options={'autoVersion':True}),dict(options={'startPositionMs':100}),dict(options={'qualityPreference':'720p'}),dict(device={'Hdr10:true':'Hdr10:false'})]:
   with self.subTest(args=args):self.assertEqual([],self.starts(self.job(**args)))
 def test_private_receipt_negatives_never_retry_or_publish(self):
  mutations=[lambda r:r['transformations'][0].update(recipe_version='1'),lambda r:r['transformations'].append(dict(name='hls_separate_audio',executor='server',recipe_version='1')),lambda r:r['effective_recipe'].update(audio_codec='aac'),lambda r:r.update(effective_media_file_id='732'),lambda r:r['selected_tracks']['audio'].update(index=1),lambda r:r['source'].update(dv_base_layer_proven=False),lambda r:r.update(runtime_corrections=['unknown'])]
  for mutate in mutations:
   with self.subTest(mutate=mutate):
    r=self.job(receipt=mutate);self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(self.starts(r)));self.assertNotIn('compatContinuation',r['outcome'])
 def test_private_lost_start_retains_allocation_uncertainty(self):
  def lost(responses): responses[2]=dict(statusCode=408,body='')
  r=self.job(http=lost);self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome'].get('leaseUncertain'),r['outcome']);self.assertEqual(1,len(self.starts(r)))
 def test_private_changed_output_after_start_closes_exact_owner(self):
  r=self.job(race='start_output');self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(self.starts(r)));self.assertEqual(1,sum(q['method']=='DELETE' for q in r['requests']))

 def test_private_plan_cannot_enter_generic_recovery(self):
  r=self.job(options={'privateControlCheck':True});self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(self.starts(r)));self.assertEqual(3,len(r['requests']),r['requests'])
 def test_private_start_auth_failure_never_reposts(self):
  def auth(responses):responses[2]=dict(statusCode=401,body='{}')
  r=self.job(http=auth);self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(self.starts(r)));self.assertFalse(any('/auth/refresh' in q['url'] for q in r['requests']))

 def test_private_claims_must_prove_hdr10_without_contradictory_range(self):
  mutations=[lambda r:r.pop('claims'),lambda r:r['claims']['video'].pop('hdr10'),lambda r:r['claims']['video'].update(hdr10=False),lambda r:r['claims']['video'].update(hdr10='true'),lambda r:r['claims']['video'].update(dolby_vision=True),lambda r:r['claims']['video'].pop('dolby_vision'),lambda r:r['claims']['video'].update(hdr10_plus=True),lambda r:r['claims']['video'].update(hlg=True)]
  for mutate in mutations:
   with self.subTest(mutate=mutate):
    r=self.job(receipt=mutate);self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(self.starts(r)))

 def test_private_source_duration_and_plan_protocol_are_required(self):
  for duration in [0,-1,None,604801]:
   with self.subTest(duration=duration):self.assertEqual([],self.starts(self.job(source={'duration':duration})))
  for protocol in [None,2,'3']:
   with self.subTest(protocol=protocol):
    r=self.job(receipt=lambda raw:raw.update(protocol_version=protocol));self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(self.starts(r)))
 def test_private_crossed_container_audio_modes_refuse_before_start(self):
  device={'if format.passthru = 1 then return {result:format.codec="eac3" and format.chcnt<=6}':'if format.codec="eac3" then return {result:(format.container="mp4" and format.passthru=0) or (format.container="ts" and format.passthru=1)}'}
  r=self.job(device=device);self.assertFalse(r['outcome']['ok']);self.assertEqual([],self.starts(r))

 def test_private_cancelled_before_http_does_not_invent_unknown_allocation(self):
  r=self.job(race='before_fetch');self.assertFalse(r['outcome']['ok']);self.assertEqual([],self.starts(r));self.assertNotIn('leaseUncertain',r['outcome'])
 def test_private_crossed_transport_never_bypasses_receipt_validation(self):
  for protocol,container in [('http_progressive','mp4'),('dash','mpd')]:
   with self.subTest(protocol=protocol):
    r=self.job(receipt=lambda raw:raw['stream'].update(protocol=protocol,container=container));self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(self.starts(r)))
 def test_private_conflicting_lease_ids_never_mint_closed_fact(self):
  def conflict(raw):raw['session_id']='conflicting-lease-02'
  r=self.job(receipt=conflict);self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome'].get('leaseUncertain'),r['outcome']);self.assertNotIn('cleanupLeaseClosed',r['outcome']);self.assertEqual(1,len(self.starts(r)))
 def test_private_video_bitrate_precedes_aggregate_bitrate(self):
  def receipt(raw):
   raw['source']['bitrate_kbps']=42000;raw['effective_recipe']['bitrate_kbps']=42000
  r=self.job(video={'bitrate':42000},receipt=receipt);self.assertTrue(r['outcome']['ok'],r['outcome'])
 def test_private_output_drift_stop_exception_retains_exact_cleanup_authority(self):
  def stop_throws(responses):responses[3]=dict(statusCode=200,body='{}',throws=True)
  r=self.job(race='start_output',http=stop_throws)
  self.assertFalse(r['outcome']['ok']);self.assertTrue(r['outcome'].get('cleanupLeaseKnown'),r['outcome']);self.assertEqual('session-fixture-01',r['outcome']['plan']['sessionId']);self.assertEqual(1,len(self.starts(r)))
