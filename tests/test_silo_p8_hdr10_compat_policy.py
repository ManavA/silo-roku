"""Dormant P8.1 HDR10 policy; synthetic source and capability facts only."""
import copy,unittest
from tests import test_silo_p7_hdr10_compat_policy as p7
from tests import test_silo_modern_compat_policy as modern
KIND='experimental_query_p8_hdr10_fmp4_v1'
class P8HDR10Policy(unittest.TestCase):
 def execute(self,body):
  import tempfile
  from pathlib import Path
  from tools.brightscript import _execute
  with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
   folder=Path(directory)
   prefix,expression=body.rsplit('print FormatJson(',1)
   result=_execute([*modern.FILES,p7.ROOT/'source/adapters/SiloCompatAdapter.brs',p7.ROOT/'source/core/ServerUrlPolicy.brs'],prefix,folder,expression[:-1])['result']
  names='mediaSourceId eligibilityKind audioOrdinal fileId audioStreamIndex physicalHDRVerified dolbyVision'.split()
  canonical={name.lower():name for name in names}
  def keys(value):
   if isinstance(value,list):return [keys(v) for v in value]
   if isinstance(value,dict):return {canonical.get(k.lower(),k):keys(v) for k,v in value.items()}
   return value
  return keys(result)
 candidates=p7.P7HDR10Policy.candidates
 wire=p7.P7HDR10Policy.wire
 def data(self):
  c=modern.ModernCompat().data();c['kind']=KIND
  c['detail']['versions'][0]['subtitleTracks']=[]
  c['detail']['versions'][0]['audioTracks'][0]['wireIndexPresent']=False
  c['snapshot'].update(hdr10=True,audioContainer='mp4')
  c['snapshot']['videoQuery']['container']='mp4'
  return c
 def test_explicit_p8_hdr10_candidate_keeps_real_dv_fact_and_source_identity(self):
  proof=self.candidates([self.data()])[0]
  self.assertIsNotNone(proof)
  self.assertEqual(KIND,proof['eligibilityKind'])
  self.assertTrue(proof['snapshot']['dolbyVision'])
  self.assertEqual('731',proof['fileId'])
  self.assertEqual('eac3',proof['audio']['codec'])
 def metadata(self):
  value=p7.P7HDR10Policy().metadata();source=value['MediaSources'][0]
  source.update(Bitrate=54000000,DefaultAudioStreamIndex=1);source.pop('DefaultSubtitleStreamIndex')
  source['MediaStreams']=source['MediaStreams'][:2]
  source['MediaStreams'][0].update(Level=150,VideoRangeType='DOVIWithHDR10')
  source['MediaStreams'][1].update(Codec='eac3',Channels=6)
  return value
 def receipt(self):
  value=self.metadata();value['PlaySessionId']='play-fixture';source=value['MediaSources'][0]
  source.update(SupportsDirectPlay=False,SupportsDirectStream=False,SupportsTranscoding=True,SiloSeekReanchor=True,TranscodingSubProtocol='hls',TranscodingContainer='mp4',TranscodingUrl='/Videos/03000000-0000-0000-0000-0000000002db/remux-dv-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId=03000000-0000-0000-0000-0000000002db')
  return value
 def test_hdr10_profile_and_receipt_preserve_original_dv_source_and_copy_audio(self):
  c=self.data();c.update(metadata=self.metadata(),receipt=self.receipt(),wireAudioIndex=1)
  result=self.wire([c])[0]
  self.assertIsNotNone(result['metadata'])
  self.assertEqual('DOVIWithHDR10',result['metadata']['source']['MediaStreams'][0]['VideoRangeType'])
  profile=result['profile'];self.assertEqual([],profile['DirectPlayProfiles'])
  self.assertEqual('eac3',profile['TranscodingProfiles'][0]['AudioCodec'])
  self.assertEqual('HDR10',profile['CodecProfiles'][0]['Conditions'][0]['Value'])
  self.assertEqual('hvc1',profile['CodecProfiles'][0]['Conditions'][1]['Value'])
  self.assertEqual('copied_p8_hdr10_fmp4',result['receipt']['class'])
  self.assertFalse(result['receipt']['physicalHDRVerified'])
 def test_rejects_non_p81_missing_and_contradictory_source_or_device_facts(self):
  cases=[]
  for target,key,value in [('video','dv_profile',5),('video','dv_profile',7),('video','dv_bl_compat_id',4),('video','dv_el_present',True),('video','dv_el_present',None),('video','dv_config_present',False),('video','color_transfer','arib-std-b67'),('video','profile','Main'),('video','level',156),('video','frame_rate','25'),('video','bit_depth',8),('video','dv_enhancement_layer','unknown'),('version','bitrateKbps',0),('params','bandwidthCapKbps',53999),('params','subtitleMode','auto'),('params','qualityPreference','auto'),('params','audioTrackId','file:732:audio:0'),('snapshot','hdr10',False),('snapshot','hdr10',1),('snapshot','dolbyVision',None),('snapshot','audioCodec','ac3'),('snapshot','audioChannels',2),('snapshot','audioDecode',False),('snapshot','audioContainer','ts')]:
   c=self.data();v=c['detail']['versions'][0]
   row=v['videoTracks'][0] if target=='video' else v if target=='version' else c[target]
   row[key]=value
   if key=='audioDecode':c['snapshot']['audioPassthrough']=False
   cases.append(c)
  for key in ['dv_profile','dv_bl_compat_id','dv_config_present','dv_bl_present','dv_rpu_present','color_primaries','frame_rate']:
   c=self.data();c['detail']['versions'][0]['videoTracks'][0].pop(key);cases.append(c)
  self.assertEqual([None]*len(cases),self.candidates(cases))
 def test_changed_wire_inventory_binding_seek_and_cross_class_receipts_fail(self):
  cases=[]
  for key,value in [('Id','03000000-0000-0000-0000-0000000002dc'),('Bitrate',54000001),('RunTimeTicks',600000001),('DefaultAudioStreamIndex',2),('SiloSeekReanchor',False),('TranscodingContainer','ts'),('TranscodingUrl','/Videos/03000000-0000-0000-0000-0000000002db/remux-ts-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId=03000000-0000-0000-0000-0000000002db')]:
   c=self.data();c.update(metadata=self.metadata(),receipt=self.receipt(),wireAudioIndex=1);c['receipt']['MediaSources'][0][key]=value;cases.append(c)
  for key,value in [('Codec','ac3'),('Language','fr'),('Channels',2),('Index',2)]:
   c=self.data();c.update(metadata=self.metadata(),receipt=self.receipt(),wireAudioIndex=1);c['receipt']['MediaSources'][0]['MediaStreams'][1][key]=value;cases.append(c)
  c=self.data();c.update(metadata=self.metadata(),receipt=self.receipt(),wireAudioIndex=1);c['receipt']['MediaSources'][0]['MediaStreams'][0]['VideoRangeType']='DOVIWithEL';cases.append(c)
  for result in self.wire(cases):self.assertIsNone(result['receipt'])
  c=self.data()
  body='c='+p7.literal(c)+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind)\nanswers=[]\nfor each k in ["experimental_query_p8_ts_v1","experimental_query_p7_hdr10_fmp4_v1","experimental_query_p7_hdr10_aac_fmp4_v1","unknown"]\np.eligibilityKind=k\nanswers.Push({profile:SiloCompatDeviceProfile(p),receipt:SiloCompatPlaybackReceipt('+p7.literal(self.receipt())+',p,"http://fixture.invalid",1)})\nend for\nprint FormatJson(answers)'
  for result in self.execute(body):self.assertIsNone(result['receipt'])
 def test_stock_text_projection_stays_off_without_relabeling_source(self):
  c=self.data();c['detail']['versions'][0]['subtitleTracks']=[dict(index=2,codec='subrip',language='en',isDefault=True,forced=False,hearingImpaired=False,external=False)]
  c.update(metadata=self.metadata(),receipt=self.receipt(),wireAudioIndex=1)
  text=dict(Index=2,Type='Subtitle',Codec='subrip',Language='en',IsDefault=True,IsForced=False,IsHearingImpaired=False,IsExternal=False,IsTextSubtitleStream=True,DeliveryMethod='Embed')
  c['metadata']['MediaSources'][0]['MediaStreams'].append(text)
  delivered=dict(text,IsDefault=False,DeliveryMethod='External')
  c['receipt']['MediaSources'][0]['MediaStreams'].append(delivered)
  result=self.wire([c])[0];self.assertIsNotNone(result['metadata']);self.assertIsNotNone(result['receipt'])
  c['receipt']['MediaSources'][0]['MediaStreams'][-1]['IsTextSubtitleStream']=False
  self.assertIsNone(self.wire([c])[0]['receipt'])
 def test_adapter_body_keeps_video_audio_copy_original_off_and_seek(self):
  from tests.test_silo_compat_auth import SESSION
  c=self.data();c['params']['startPositionMs']=12500
  body='c='+p7.literal(c)+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind)\nr=BuildSiloCompatRequest("playback_info",'+p7.literal(SESSION)+',{mediaSourceId:p.mediaSourceId,audioStreamIndex:1,startTicks:p.startTicks,eligibilityKind:p.eligibilityKind,deviceProfile:SiloCompatDeviceProfile(p)})\nprint FormatJson(ParseJson(r.body,"i"))'
  value=self.execute(body)
  self.assertTrue(value['AllowVideoStreamCopy']);self.assertTrue(value['AllowAudioStreamCopy'])
  self.assertEqual(-1,value['SubtitleStreamIndex']);self.assertEqual(125000000,value['StartTimeTicks'])
  self.assertTrue(value['SiloSeekReanchor']);self.assertNotIn('MaxAudioChannels',value)
if __name__=='__main__':unittest.main()
