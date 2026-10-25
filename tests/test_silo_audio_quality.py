"""102 actual Task/SDK/HTTP qualification of permitted AAC output counts."""
import unittest,json
from tests import test_silo_audio_projection as projection
EXACT_GENERIC=projection.EXACT_GENERIC

AAC_BOTH='if format.chcnt <> invalid then return {result:format.codec="aac" and format.container="ts" and format.passthru=0 and (format.chcnt=2 or format.chcnt=6)}\n'+EXACT_GENERIC
class AudioQuality(unittest.TestCase):
 def test_original_dts_surround_uses_highest_proven_aac_output(self):
  r=projection.AudioProjection().start(source=lambda v:v['audio_tracks'][0].update(codec='dts'),probe=AAC_BOTH,receipt=lambda p:p['effective_recipe'].update(audio_channels=6,audio_layout='5.1'))
  b=projection.AudioProjection().bodies(r)[0];self.assertEqual(6,b['client_playback_context']['deliveries']['hls']['max_channels'])
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual('732',r['outcome']['plan']['versionId'])
  self.assertEqual({'fileId','container','audio'},set(r['outcome']['plan']['sourceAudioProjection']))
 def encoded(self,p,channels=6,height=720):
  p.update(delivery='server_transcode_hls',transformations=[dict(name='video_to_h264',executor='server',recipe_version='2',validated_claims=None),dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode'])])
  p['effective_recipe'].update(audio_channels=channels,audio_layout='5.1' if channels==6 else 'stereo',height=height)
 def test_plain_quality_start_and_retained_replan_use_proven_surround(self):
  for action in ('start','replan'):
   with self.subTest(action=action):
    args=dict(source=lambda v:v['audio_tracks'][0].update(codec='dts'),probe=AAC_BOTH,receipt=self.encoded)
    if action=='start':args['options']={'qualityPreference':'720p'}
    else:args['quality']='720p'
    r=getattr(projection.AudioProjection(),action)(**args)
    self.assertEqual(['GET','GET','POST'],[q['method'] for q in r['requests']],r['outcome'])
    body=json.loads(r['requests'][-1]['body']);self.assertEqual(6,body['client_playback_context']['deliveries']['hls'].get('max_channels'))
    self.assertEqual('720p',body['quality_preference']);self.assertTrue(r['outcome']['ok'],r['outcome'])
 def test_required_video_encode_constrains_positive_surround_to_proven_aac2(self):
  probe='if format.chcnt <> invalid then return {result:(format.codec="eac3" and format.chcnt=6 and format.passthru=1) or (format.codec="aac" and format.container="ts" and format.chcnt=2 and format.passthru=0)}\n'+EXACT_GENERIC
  for action in ('start','replan'):
   with self.subTest(action=action):
    args=dict(probe=probe,receipt=lambda p:self.encoded(p,2))
    if action=='start':args['options']={'qualityPreference':'720p'}
    else:args['quality']='720p'
    r=getattr(projection.AudioProjection(),action)(**args);body=json.loads(r['requests'][-1]['body'])
    self.assertEqual(2,body['client_playback_context']['deliveries']['hls'].get('max_channels'))
    self.assertTrue(r['outcome']['ok'],r['outcome'])
 def test_zero_width_cannot_prove_encoding_despite_tall_raw_height(self):
  probe='if format.chcnt <> invalid then return {result:(format.codec="eac3" and format.chcnt=6 and format.passthru=1) or (format.codec="aac" and format.chcnt=2 and format.passthru=0)}\n'+EXACT_GENERIC
  def source(v):v['video_tracks'][0].update(width=0,height=2160);v['resolution']='1080p'
  r=projection.AudioProjection().start(source=source,probe=probe,options={'qualityPreference':'1080p'})
  body=projection.AudioProjection().bodies(r)[0];self.assertNotIn('max_channels',body['client_playback_context']['deliveries']['hls'])
 def test_ceiling_six_accepts_stereo_only_with_its_independent_proof(self):
  r=projection.AudioProjection().start(probe=AAC_BOTH)
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(6,projection.AudioProjection().bodies(r)[0]['client_playback_context']['deliveries']['hls']['max_channels'])
  only6='if format.chcnt <> invalid then return {result:format.codec="aac" and format.container="ts" and format.chcnt=6 and format.passthru=0}\n'+EXACT_GENERIC
  r=projection.AudioProjection().start(probe=only6)
  self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
  self.assertEqual(6,projection.AudioProjection().bodies(r)[0]['client_playback_context']['deliveries']['hls']['max_channels'])
 def test_only_stereo_proof_cannot_authorize_surround_or_wrong_layout(self):
  for channels,layout in [(6,'5.1'),(2,'5.1')]:
   with self.subTest(channels=channels,layout=layout):
    r=projection.AudioProjection().start(receipt=lambda p:p['effective_recipe'].update(audio_channels=channels,audio_layout=layout))
    self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
 def test_short_source_never_advertises_six_from_generic_or_unrelated_probe(self):
  r=projection.AudioProjection().start(source=lambda v:v['audio_tracks'][0].update(channels=4),probe=AAC_BOTH)
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(2,projection.AudioProjection().bodies(r)[0]['client_playback_context']['deliveries']['hls']['max_channels'])
  self.assertFalse(any(q.get('codec')=='aac' and q.get('chcnt')==6 for q in r['audioQueries']))
 def test_positive_source_without_strict_height_encoding_remains_unchanged(self):
  positive='if format.chcnt <> invalid then return {result:(format.codec="eac3" and format.chcnt=6 and format.passthru=1) or (format.codec="aac" and format.chcnt=2 and format.passthru=0)}\n'+EXACT_GENERIC
  for height in (720,480,None,'malformed'):
   with self.subTest(height=height):
    def source(v):
     if height is None:v['video_tracks'][0].pop('height')
     elif height=='malformed':v['video_tracks']={}
     else:v['video_tracks'][0]['height']=height
    r=projection.AudioProjection().start(source=source,probe=positive,options={'qualityPreference':'720p'})
    self.assertNotIn('max_channels',projection.AudioProjection().bodies(r)[0]['client_playback_context']['deliveries']['hls'])
  r=projection.AudioProjection().start(probe=positive,options={'qualityPreference':'original','bandwidthCapKbps':1000})
  self.assertNotIn('max_channels',projection.AudioProjection().bodies(r)[0]['client_playback_context']['deliveries']['hls'])
 def test_encoding_only_authority_refuses_remux_or_changed_source_height(self):
  positive='if format.chcnt <> invalid then return {result:(format.codec="eac3" and format.chcnt=6 and format.passthru=1) or (format.codec="aac" and format.chcnt=2 and format.passthru=0)}\n'+EXACT_GENERIC
  for kind in ('remux','height'):
   with self.subTest(kind=kind):
    def receipt(p):
     if kind=='height':self.encoded(p,2);p['source']['height']=720
     else:p['effective_recipe']['height']=720
    r=projection.AudioProjection().start(probe=positive,options={'qualityPreference':'720p'},receipt=receipt)
    self.assertFalse(r['outcome']['ok']);self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in r['requests']])
 def test_positive_source_encoding_can_retain_proven_aac_surround(self):
  positive=AAC_BOTH.replace('return {result:format.codec=', 'return {result:(format.codec="eac3" and format.chcnt=6 and format.passthru=1) or format.codec=',1)
  r=projection.AudioProjection().start(probe=positive,options={'qualityPreference':'720p'},receipt=self.encoded)
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(6,projection.AudioProjection().bodies(r)[0]['client_playback_context']['deliveries']['hls']['max_channels'])
 def test_plain_4k_and_480p_keep_the_user_quality_and_selected_source(self):
  for quality in ('4k','480p'):
   with self.subTest(quality=quality):
    receipt=(lambda p:self.encoded(p,6,480)) if quality=='480p' else (lambda p:p['effective_recipe'].update(audio_channels=6,audio_layout='5.1'))
    r=projection.AudioProjection().start(source=lambda v:v['audio_tracks'][0].update(codec='truehd'),probe=AAC_BOTH,options={'qualityPreference':quality},receipt=receipt)
    self.assertTrue(r['outcome']['ok'],r['outcome']);body=projection.AudioProjection().bodies(r)[0]
    self.assertEqual((quality,'732','file:732:audio:0',50000),(body['quality_preference'],body['file_id'],body['audio_track_id'],body['bandwidth_cap_kbps']))

 def test_plain_replan_without_matching_hint_retains_ordinary_request_count(self):
  r=projection.AudioProjection().replan(quality='720p',hint=None)
  self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(['GET','POST'],[q['method'] for q in r['requests']])
  self.assertNotIn('max_channels',json.loads(r['requests'][-1]['body'])['client_playback_context']['deliveries']['hls'])
