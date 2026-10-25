"""Manual P8.1 AC3 copy qualification; synthetic source and SDK facts only."""
import copy
import unittest
from tests import test_silo_p8_hdr10_compat_policy as p8
from tests import test_silo_p7_hdr10_compat_policy as p7

KIND = 'experimental_query_p8_hdr10_ac3_fmp4_v1'

class P8AC3Policy(unittest.TestCase):
 execute = p7.P7HDR10Policy.execute
 candidates = p7.P7HDR10Policy.candidates
 wire = p7.P7HDR10Policy.wire

 def data(self):
  c = p8.P8HDR10Policy().data()
  c['kind'] = KIND
  c['detail']['versions'][0]['audioTracks'] = [dict(sourceOrdinal=i,wireIndexPresent=False,codec=codec,channels=channels,language='en',isDefault=i==0) for i,(codec,channels) in enumerate([('truehd',8),('ac3',6),('ac3',6)])]
  c['params'].update(autoVersion=False,audioTrackIndex=1,audioTrackId='file:731:audio:1')
  c['snapshot']['audioCodec'] = 'ac3'
  return c

 def metadata(self,negotiated=False):
  c = p8.P8HDR10Policy().receipt() if negotiated else p8.P8HDR10Policy().metadata()
  source = c['MediaSources'][0]
  source['MediaStreams'] = source['MediaStreams'][:1] + [dict(Index=i+1,Type='Audio',Codec=codec,Channels=channels,Language='en',IsDefault=i==(1 if negotiated else 0)) for i,(codec,channels) in enumerate([('truehd',8),('ac3',6),('ac3',6)])]
  source['DefaultAudioStreamIndex'] = 2 if negotiated else 1
  return c

 def test_explicit_ac3_ordinal_maps_to_exact_compat_index_with_copy_only_profile(self):
  c=self.data();c.update(metadata=self.metadata(),receipt=self.metadata(True),wireAudioIndex=2)
  proof=self.candidates([c])[0]
  self.assertIsNotNone(proof)
  self.assertEqual(1,proof['audioOrdinal'])
  result=self.wire([c])[0]
  self.assertEqual(2,result['metadata']['audioStreamIndex'])
  self.assertEqual('ac3',result['profile']['TranscodingProfiles'][0]['audioCodec'])
  self.assertEqual('hevc',result['profile']['TranscodingProfiles'][0]['VideoCodec'])
  self.assertEqual('mp4',result['profile']['TranscodingProfiles'][0]['Container'])
  self.assertEqual('HDR10',result['profile']['CodecProfiles'][0]['Conditions'][0]['Value'])
  self.assertEqual('hvc1',result['profile']['CodecProfiles'][0]['Conditions'][1]['Value'])
  self.assertEqual([],result['profile']['DirectPlayProfiles'])
  self.assertEqual('copied_p8_hdr10_ac3_fmp4',result['receipt']['class'])
  self.assertFalse(result['receipt']['physicalHDRVerified'])

 def test_sdk_queries_actual_mp4_ac3_without_relabeling_display(self):
  helper=p7.P7HDR10Policy()
  config=helper.config();config['video50']={'result':True}
  result=helper.snapshots([config],audio={'codec':'ac3','channels':6},video={'level':150},kind=KIND)[0]
  self.assertEqual('ac3',result['snapshot']['audioCodec'])
  self.assertEqual('mp4',result['snapshot']['audioContainer'])
  self.assertFalse(result['snapshot']['dolbyVision'])
  self.assertEqual('5.0',result['snapshot']['videoQuery']['level'])
  self.assertEqual('mp4',result['queries'][0]['container'])
  self.assertEqual('ac3',result['queries'][1]['codec'])
  self.assertEqual('mp4',result['queries'][1]['container'])

 def test_manual_class_requires_explicit_ac3_and_rejects_automatic_selection(self):
  cases=[]
  for index in [None,0]:
   c=self.data();c['params']['audioTrackIndex']=index;cases.append(c)
  c=self.data();c['kind']=p8.KIND;cases.append(c)
  self.assertEqual([None]*len(cases),self.candidates(cases))
  c=self.data();c['snapshot']['dolbyVision']=False
  body='c='+p7.literal(c)+'\nprint FormatJson(SiloCompatP8HDR10AutomaticCandidate(c.detail,c.owner,c.params,c.snapshot))'
  self.assertIsNone(self.execute(body))

 def test_manual_pin_allows_multiple_versions_but_refuses_auto_version(self):
  c=self.data();other=copy.deepcopy(c['detail']['versions'][0]);other['versionId']='732'
  c['detail']['versions'].append(other)
  self.assertIsNotNone(self.candidates([c])[0])
  cases=[]
  for value in [None,True]:
   bad=self.data();bad['params']['autoVersion']=value;cases.append(bad)
  self.assertEqual([None,None],self.candidates(cases))

 def test_unknown_device_and_changed_source_refuse_without_dv_relabeling(self):
  cases=[]
  for key,value in [('hdr10',None),('hdr10',False),('dolbyVision',None),('audioCodec','aac'),('audioDecode',None),('audioContainer','ts')]:
   c=self.data();c['snapshot'][key]=value
   if key=='audioDecode':c['snapshot']['audioPassthrough']=False
   cases.append(c)
  c=self.data();c['snapshot']['videoQuery']['result']=None;cases.append(c)
  c=self.data();c['detail']['versions'][0]['videoTracks'][0]['dv_bl_compat_id']=4;cases.append(c)
  c=self.data();c['params']['fileId']='732';cases.append(c)
  self.assertEqual([None]*len(cases),self.candidates(cases))
  c=self.data();c['snapshot']['dolbyVision']=False
  self.assertIsNotNone(self.candidates([c])[0])

 def test_changed_or_unselected_audio_receipt_fails_closed(self):
  cases=[]
  for index in [1,3]:
   c=self.data();c.update(metadata=self.metadata(),receipt=self.metadata(True),wireAudioIndex=index);cases.append(c)
  for key,value in [('Codec','aac'),('Channels',2),('Language','fr')]:
   c=self.data();c.update(metadata=self.metadata(),receipt=self.metadata(True),wireAudioIndex=2)
   c['receipt']['MediaSources'][0]['MediaStreams'][2][key]=value;cases.append(c)
  for result in self.wire(cases):self.assertIsNone(result['receipt'])

 def test_persistent_task_prepares_exact_ac3_and_closes_without_media(self):
  import json
  from tests.test_silo_compat_playback_task import CompatPlaybackTask
  def change(values):
   version=values['detail']['versions'][0]
   version['duration']=60
   version['audio_tracks']=[dict(codec=codec,channels=channels,language='en',default=i==0) for i,(codec,channels) in enumerate([('truehd',8),('ac3',6),('ac3',6)])]
   values['metadata']=self.metadata()
   values['playback']=self.metadata(True)
  result=CompatPlaybackTask().transcript(change=change,options=dict(eligibilityKind=KIND,autoVersion=False),device_overrides={'format.codec="eac3"':'format.codec="ac3"','return {DolbyVision:true}':'return {DolbyVision:true,hdr10:true}'})
  self.assertEqual(['prepared','closed'],[r.get('phase') for r in result['results']],result['results'])
  self.assertEqual('copied_p8_hdr10_ac3_fmp4',result['results'][0]['class'])
  self.assertEqual(0,result['mediaRequests'])
  self.assertTrue(result['privateCleared'])
  self.assertTrue(result['results'][-1]['credentialRevoked'])
  body=json.loads(next(q for q in result['requests'] if '/PlaybackInfo' in q['url'])['body'])
  self.assertEqual(2,body['AudioStreamIndex'])
  self.assertTrue(body['AllowAudioStreamCopy']);self.assertTrue(body['AllowVideoStreamCopy'])
  self.assertEqual('ac3',body['DeviceProfile']['TranscodingProfiles'][0]['AudioCodec'])
  self.assertEqual([],body['DeviceProfile']['DirectPlayProfiles'])

if __name__ == '__main__':
 unittest.main()
