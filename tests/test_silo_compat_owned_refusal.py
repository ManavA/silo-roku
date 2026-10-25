"""Actual runJob Start→owned DELETE→compatibility intent; no Scene or media.

Existing HTTP200 stopped/applied/replayed receipt semantics remain authoritative.
All responses/credentials here are synthetic, not native playback qualification.
"""
import copy,json,unittest
from tests import test_silo_compat_continuation as continuation
from tests import test_silo_p8_original_transport as transport

class OwnedRefusal(unittest.TestCase):
 def start(self,enabled=True,stop=None,mutate=None,options=None,device=None,race='',scope=None):
  def high(wire,decision):
   _,_,accepted=transport.SiloP8OriginalTransportTests().inputs()
   raw=accepted['playback_plan']
   raw.update(delivery='server_remux_hls',decision_reason='server_remux')
   raw['stream'].update(protocol='hls',container='hls',url='/api/v2/playback/transcode/fixture/master.m3u8?st=synthetic')
   raw['effective_recipe'].update(video_codec='hevc',audio_codec='eac3',dynamic_range='hdr10',video_sample_entry='hvc1')
   raw['transformations']=[dict(name='server_dv7_to_hdr10',executor='server',recipe_version='3',validated_claims=['dolby_vision_metadata_removed','hdr10_base_layer_preserved','enhancement_layer_discarded']),dict(name='hls_separate_audio',executor='server',recipe_version='1',validated_claims=None)]
   decision.clear();decision.update(accepted)
   if mutate:mutate(wire,decision)
  def transcript(responses):
   if stop:responses[3]=stop
   first=json.loads(responses[2]['body'])
   if not first.get('session_id') and not first.get('playback_plan',{}).get('session_id'):responses.pop(3)
   _,_,low=transport.SiloP8OriginalTransportTests().inputs();raw=low['playback_plan']
   low['session_id']='session-low-fixture';raw.update(session_id='session-low-fixture',requested_media_file_id='732',effective_media_file_id='732',delivery='original_http',decision_reason='direct_play',transformations=[])
   for key in list(raw['source']):
    if key.startswith('dv_') or key.startswith('dolby_'):raw['source'].pop(key)
   raw['source'].update(media_file_id='732',video_codec='h264',video_profile='high',video_level=40,bit_depth=8,width=1920,height=1080,bitrate_kbps=12000,dynamic_range='sdr',audio_codec='aac',audio_channels=2,audio_layout='stereo')
   raw['effective_recipe'].update(video_codec='h264',width=1920,height=1080,bitrate_kbps=12000,dynamic_range='sdr',audio_codec='aac',audio_channels=2,audio_layout='stereo')
   raw['available_qualities']=[dict(label='original',height=1080,bitrate_kbps=12000,preserves_source=True)]
   raw['stream'].update(protocol='http_progressive',container='mkv',url='/api/v2/stream/session-low-fixture?file_id=732')
   raw['selected_tracks']={'audio':{'id':'file:732:audio:0','index':0}}
   responses.extend(copy.deepcopy(responses[:2])+[dict(statusCode=200,body=json.dumps(low))])
  return continuation.CompatContinuation().job(enabled=enabled,mutate=high,features=['native_hls_separate_audio_v1'],options=options,device=device,race=race,http=transcript,scope=scope)
 def test_owned_stop_ack_returns_same_4k_intent_before_1080_retry(self):
  r=self.start();requests=r['requests']
  starts=[json.loads(q['body']) for q in requests if '/playback/start' in q['url']]
  self.assertEqual(['731'],[q['file_id'] for q in starts],r['outcome'])
  self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in requests])
  result=r['outcome'];self.assertFalse(result['ok']);self.assertEqual('compat_prepare_required',result['errorCode']);self.assertNotIn('plan',result)
  c=result['compatContinuation'];self.assertEqual(('native_routes_exhausted','731','731','731','file:731:audio:0',0,25000,'original','off'),(c['reason'],c['fileId'],c['requestedFileId'],c['nativeSelectedFileId'],c['audioTrackId'],c['audioTrackIndex'],c['startPositionMs'],c['qualityPreference'],c['subtitleMode']))
  closure=c['nativeClosure'];self.assertEqual('acknowledged',closure['state']);self.assertEqual(c['owner'],closure['owner']);self.assertEqual(c['requestId'],closure['requestId']);self.assertEqual(c['playbackAttemptId'],closure['playbackAttemptId'])
  self.assertEqual('session-fixture-01',closure['sessionId']);self.assertEqual('server-install',closure['installationId'])
  stop=json.loads(requests[3]['body']);self.assertEqual(stop['stop_id'],closure['stopId']);self.assertFalse({'position','sequence','is_paused'} & stop.keys())
  self.assertFalse(any('compat.example' in q['url'] or '.m3u8' in q['url'] for q in requests))

 def test_missing_allocated_identity_never_hands_off_or_allocates_1080(self):
  def missing(w,d):
   d.pop('session_id');d['playback_plan'].pop('session_id')
  r=self.start(mutate=missing)
  self.assertNotIn('compatContinuation',r['outcome'])
  self.assertEqual(['731'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])

 def test_sent_eligible_attempt_stays_uncertain_when_output_drops_and_lease_is_missing(self):
  def missing(w,d):d.pop('session_id');d['playback_plan'].pop('session_id')
  r=self.start(mutate=missing,race='start_output')
  self.assertNotIn('compatContinuation',r['outcome'])
  self.assertEqual(['731'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])

 def test_valid_stop_outcomes_keep_authenticated_request_identity_without_echo_requirements(self):
  for outcome in ('applied','replayed'):
   with self.subTest(outcome=outcome):
    r=self.start(stop=dict(statusCode=200,body=json.dumps(dict(outcome=outcome,stop_id='earlier-durable-stop-id'))))
    c=r['outcome']['compatContinuation'];request=next(q for q in r['requests'] if q['method']=='DELETE')
    self.assertEqual(json.loads(request['body'])['stop_id'],c['nativeClosure']['stopId'])
    self.assertNotEqual('earlier-durable-stop-id',c['nativeClosure']['stopId'])
    self.assertEqual(4,len(r['requests']))
 def test_gate_off_retains_fallback_and_accepted_native_plan_never_hands_off(self):
  off=self.start(enabled=False)
  self.assertEqual(['731','732'],[json.loads(q['body'])['file_id'] for q in off['requests'] if '/playback/start' in q['url']])
  self.assertNotIn('compatContinuation',off['outcome']);self.assertTrue(off['outcome']['ok'],off['outcome'])
  def accepted(w,d):d['playback_plan']['transformations'][0]['recipe_version']='2'
  good=self.start(mutate=accepted)
  self.assertTrue(good['outcome']['ok'],good['outcome']);self.assertEqual('731',good['outcome']['plan']['versionId']);self.assertNotIn('compatContinuation',good['outcome'])
  self.assertFalse(any(q['method']=='DELETE' for q in good['requests']))
 def test_failed_stop_preserves_exact_cleanup_owner_and_never_allocates_again(self):
  cases=[dict(statusCode=500,body='{}'),dict(statusCode=204,body=''),dict(statusCode=200,body='{"outcome":"accepted"}'),dict(statusCode=0,body=''),dict(statusCode=200,body='',throws=True)]
  for response in cases:
   with self.subTest(response=response):
    r=self.start(stop=response);o=r['outcome'];self.assertNotIn('compatContinuation',o);self.assertTrue(o['leaseUncertain']);self.assertFalse(o['ok'])
    self.assertEqual(['731'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])
    request=next(q for q in r['requests'] if q['method']=='DELETE');body=json.loads(request['body'])
    self.assertEqual((body['stop_id'],body['installation_id'],'session-fixture-01'),(o['plan']['stopId'],o['plan']['installationId'],o['plan']['sessionId']))
    self.assertFalse(o['plan']['persistProgress'])
 def test_malformed_control_or_conflicting_identity_never_becomes_acknowledged_handoff(self):
  def source(w,d):d['playback_plan']['source']=None
  def tracks(w,d):d['playback_plan']['selected_tracks']={'audio':[]}
  def qualities(w,d):d['playback_plan']['available_qualities']=None
  def conflict(w,d):d['session_id']='different-session'
  def claims(w,d):d['playback_plan']['transformations'][0]['validated_claims']=['unknown']
  for mutate in (source,tracks,qualities,conflict,claims):
   with self.subTest(mutate=mutate.__name__):
    r=self.start(mutate=mutate);self.assertNotIn('compatContinuation',r['outcome']);self.assertFalse(r['outcome']['ok'])
    self.assertEqual(['731'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])
    if mutate==conflict:self.assertTrue(r['outcome']['leaseUncertain'])
 def test_cancelled_or_stale_owner_after_stop_cannot_advance_or_restart_native(self):
  for race in ('stop_cancel','stop_revision','stop_profile','stop_pin'):
   with self.subTest(race=race):
    r=self.start(race=race);self.assertNotIn('compatContinuation',r['outcome']);self.assertFalse(r['outcome']['ok'])
    self.assertEqual(['731'],[json.loads(q['body'])['file_id'] for q in r['requests'] if '/playback/start' in q['url']])
    self.assertEqual(1,sum(q['method']=='DELETE' for q in r['requests']))
