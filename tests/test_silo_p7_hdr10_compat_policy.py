"""Separate dormant P7 HDR10/fMP4 policy and SDK seams; synthetic facts only."""
import copy,json,tempfile,unittest
from pathlib import Path
from tools.brightscript import _execute
from tests import test_silo_modern_compat_policy as modern
ROOT=Path(__file__).resolve().parents[1]
KIND='experimental_query_p7_hdr10_fmp4_v1'
AAC_KIND='experimental_query_p7_hdr10_aac_fmp4_v1'
AAC_QUALIFICATION='stock48ae-p7-hdr10-aac2-v1'

def literal(value):return modern.literal(value)

class P7HDR10Policy(unittest.TestCase):
 def execute(self,body):
  with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
   folder=Path(directory);sdk=folder/'sdk.brs';sdk.write_text(modern.SDK)
   prefix,expression=body.rsplit('print FormatJson(',1)
   result=_execute([*modern.FILES,ROOT/'source/adapters/SiloCompatAdapter.brs',sdk],prefix,folder,expression[:-1])['result']
  names='modelNumber modelType videoMode hevcMain10 audioCodec audioChannels audioDecode audioPassthrough videoQuery audioContainer eligibilityKind mediaSourceId fileId audioOrdinal audioInventory subtitleInventory subtitleCount isDefault sourceOrdinal hearingImpaired startTicks subtitleMode audioStreamIndex playSessionId videoCopyRecipe physicalHDRVerified targetAudio targetAudioCodec targetAudioChannels targetAudioDecode targetAudioContainer instanceQualification ownerBinding schemaVersion approved sessionRevision sourceId profileId generation'.split()
  canonical={name.lower():name for name in names}
  def keys(value):
   if isinstance(value,list):return [keys(v) for v in value]
   if isinstance(value,dict):return {canonical.get(k.lower(),k):keys(v) for k,v in value.items()}
   return value
  return keys(result)
 def config(self):
  config=modern.ModernCompat().config()
  config.update(display={'hdr10':True,'DolbyVision':False},video50={'result':False},video51={'result':True})
  return config
 def snapshots(self,configs,audio=None,video=None,kind=KIND):
  audio=audio or {'codec':'ac3','channels':6};video=video or {'level':153}
  return self.execute('answers=[]\nfor each c in '+literal(configs)+'\nGetGlobalAA().config=c:GetGlobalAA().queries=[]\ns=SiloCompatSnapshotForKind(Device(),'+literal(audio)+','+literal(kind)+','+literal(video)+')\nanswers.Push({snapshot:s,queries:GetGlobalAA().queries})\nend for\nprint FormatJson(answers)')
 def data(self):
  case=modern.ModernCompat().data();case['kind']=KIND
  version=case['detail']['versions'][0];video=version['videoTracks'][0]
  video.update(dv_profile=7,dv_level=6,dv_bl_compat_id=6,dv_el_present=True,dv_enhancement_layer='unknown',level=153,width=3840,height=2160,frame_rate='24000/1001')
  version['bitrateKbps']=62830
  version['audioTracks']=[dict(sourceOrdinal=i,wireIndexPresent=False,codec=codec,channels=channels,layout=layout,language='en',isDefault=i==0) for i,(codec,channels,layout) in enumerate([('truehd',8,'7.1'),('ac3',6,'5.1(side)'),('ac3',2,'stereo')])]
  version['subtitleTracks']=[dict(index=i+4,codec='hdmv_pgs_subtitle',language=language,isDefault=i==0,forced=False,hearingImpaired=False,external=False) for i,language in enumerate(['en','fr'])]
  case['params'].update(audioTrackIndex=1,audioTrackId='file:731:audio:1')
  case['snapshot']={k:v for k,v in case['snapshot'].items() if k!='dolbyVision'}
  case['snapshot'].update(hdr10=True,audioCodec='ac3',audioChannels=6,audioContainer='mp4',videoQuery=dict(codec='hevc',container='mp4',profile='main 10',level='5.1',result=True))
  return case
 def qualification(self,owner):
  value=dict(schemaVersion=1,kind=AAC_QUALIFICATION,approved=True,sourceId=owner['sourceId'],profileId=owner['profileId'],generation=owner['generation'])
  if 'sessionRevision' in owner:value['sessionRevision']=owner['sessionRevision']
  return value
 def aac_case(self,ordinal=0):
  c=self.data();c['kind']=AAC_KIND
  c['params'].update(audioTrackIndex=ordinal,audioTrackId='file:731:audio:'+str(ordinal))
  c['snapshot']=dict(model='4850X',modelNumber='4850X',modelType='STB',os='17.1.2.5000',videoMode='2160p60',hdr10=True,hevcMain10=True,videoQuery=dict(codec='hevc',container='mp4',profile='main 10',level='5.1',result=True),targetAudioCodec='aac',targetAudioChannels=2,targetAudioDecode=True,targetAudioContainer='mp4')
  c['qualification']=self.qualification(c['owner'])
  return c
 def candidates(self,cases):
  return self.execute('answers=[]\nfor each c in '+literal(cases)+'\nanswers.Push(SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind,SpField(c,"qualification")))\nend for\nprint FormatJson(answers)')
 def aac_snapshots(self,configs):
  video=self.data()['detail']['versions'][0]['videoTracks'][0]
  return self.execute('answers=[]\nfor each c in '+literal(configs)+'\nGetGlobalAA().config=c:GetGlobalAA().queries=[]\ns=SiloCompatSnapshotForKind(Device(),{codec:"truehd",channels:8},'+literal(AAC_KIND)+','+literal(video)+')\nanswers.Push({snapshot:s,queries:GetGlobalAA().queries})\nend for\nprint FormatJson(answers)')
 def test_explicit_ac3_candidate_preserves_original_truehd_default_and_full_inventory(self):
  proof=self.candidates([self.data()])[0]
  self.assertEqual(KIND,proof['eligibilityKind']);self.assertEqual(1,proof['audioOrdinal'])
  self.assertEqual('ac3',proof['audio']['codec']);self.assertEqual(3,len(proof['audioInventory']));self.assertEqual(2,len(proof['subtitleInventory']))
  self.assertEqual('truehd',proof['audioInventory'][0]['codec']);self.assertTrue(proof['audioInventory'][0]['isDefault'])
  self.assertFalse(proof['audioInventory'][1]['isDefault']);self.assertEqual('off',proof['subtitleMode'])

 def metadata(self):
  tracks=[dict(Index=0,Type='Video',Codec='hevc',Width=3840,Height=2160,BitDepth=10,Profile='Main 10',Level=153,VideoRangeType='DOVIWithEL',ColorTransfer='smpte2084',ColorPrimaries='bt2020',ColorSpace='bt2020nc',AverageFrameRate=23.976,IsDefault=True,IsInterlaced=False)]
  for i,(codec,channels) in enumerate([('truehd',8),('ac3',6),('ac3',2)]):tracks.append(dict(Index=i+1,Type='Audio',Codec=codec,Channels=channels,Language='en',IsDefault=i==0))
  for i,language in enumerate(['en','fr']):tracks.append(dict(Index=i+4,Type='Subtitle',Codec='hdmv_pgs_subtitle',Language=language,IsDefault=i==0,IsForced=False,IsHearingImpaired=False,IsExternal=False,IsTextSubtitleStream=False,DeliveryMethod='Embed'))
  return {'MediaSources':[dict(DefaultAudioStreamIndex=1,DefaultSubtitleStreamIndex=4,Id='03000000-0000-0000-0000-0000000002db',Container='mkv',Bitrate=62830000,RunTimeTicks=600000000,MediaStreams=tracks)]}
 def receipt(self):
  response=self.metadata();response['PlaySessionId']='play-fixture';source=response['MediaSources'][0]
  source.pop('DefaultSubtitleStreamIndex',None)
  source.update(DefaultAudioStreamIndex=2,SupportsDirectPlay=False,SupportsDirectStream=False,SupportsTranscoding=True,SiloSeekReanchor=True,TranscodingSubProtocol='hls',TranscodingContainer='mp4',TranscodingUrl='/Videos/03000000-0000-0000-0000-0000000002db/remux-dv-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId=03000000-0000-0000-0000-0000000002db')
  for track in source['MediaStreams']:
   if track['Type']=='Audio':track['IsDefault']=track['Index']==2
   if track['Type']=='Subtitle':track.update(IsDefault=False,DeliveryMethod='Encode')
  return response
 def wire(self,cases):
  return self.execute('answers=[]\nfor each c in '+literal(cases)+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind,SpField(c,"qualification"))\nif p=invalid then answers.Push(invalid) else answers.Push({metadata:SiloCompatSourceMetadata(c.metadata,p),profile:SiloCompatDeviceProfile(p),receipt:SiloCompatPlaybackReceipt(c.receipt,p,"http://fixture.invalid",SpField(c,"wireAudioIndex",2))})\nend for\nprint FormatJson(answers)')
 def test_source_profile_and_receipt_keep_original_p7_separate_from_hdr10_output(self):
  case=self.data();case.update(metadata=self.metadata(),receipt=self.receipt());value=self.wire([case])[0]
  self.assertEqual(2,value['metadata']['audioStreamIndex']);self.assertEqual(2,value['metadata']['subtitleCount'])
  profile=value['profile'];self.assertEqual([],profile['DirectPlayProfiles'])
  self.assertEqual({'Type':'Video','Context':'Streaming','Container':'mp4','Protocol':'hls','VideoCodec':'hevc','audioCodec':'ac3','MaxAudioChannels':'6'},profile['TranscodingProfiles'][0])
  self.assertEqual([{'Condition':'EqualsAny','Property':'VideoRangeType','Value':'HDR10','IsRequired':True},{'Condition':'EqualsAny','Property':'VideoCodecTag','Value':'hvc1','IsRequired':True}],profile['CodecProfiles'][0]['Conditions'])
  receipt=value['receipt'];self.assertEqual('copied_p7_hdr10_fmp4',receipt['class']);self.assertFalse(receipt['physicalHDRVerified'])
  self.assertIn('/remux-dv-v1/',receipt['url']);self.assertEqual('DOVIWithEL',value['metadata']['source']['MediaStreams'][0]['VideoRangeType'])

 def test_actual_adapter_accepts_viewer_defaults_without_rewriting_original_flags(self):
  technical=json.loads((ROOT/'tests/fixtures/silo/stock_p7_hdr10_technical_metadata.json').read_text())
  version=copy.deepcopy(technical['native_version']);version['file_id']='731'
  raw={'content_id':'fixture-item','type':'movie','title':'Synthetic Fixture','versions':[version]}
  source=copy.deepcopy(technical['compat_metadata']);source['Id']='03000000-0000-0000-0000-0000000002db'
  source['DefaultAudioStreamIndex']=2;source['DefaultSubtitleStreamIndex']=4
  # GET Items advertises viewer default indices independently of raw stream
  # flags (mapping.go buildMediaStreams/detailMediaSourceDTO); PlaybackInfo
  # applies selections to flags through its separate mediaSourceDTO path.
  cases=[source]
  for key,value in [('DefaultAudioStreamIndex',99),('DefaultAudioStreamIndex',True),('DefaultSubtitleStreamIndex',99),('DefaultSubtitleStreamIndex','4')]:
   changed=copy.deepcopy(source);changed[key]=value;cases.append(changed)
  changed=copy.deepcopy(source);changed['MediaStreams'][1]['IsDefault']=False;cases.append(changed)
  changed=copy.deepcopy(source);changed['MediaStreams'][4]['IsDefault']=True;cases.append(changed)
  c=self.data()
  body='c='+literal(c)+'\ndecoded=DecodeSiloResponse("detail",FormatJson('+literal(raw)+'),{sourceId:"silo:fixture"})\ndetail=ScopeCatalogData(decoded.data,"silo:fixture")\np=SiloCompatCandidate(detail,c.owner,c.params,c.snapshot,c.kind)\nanswers=[]\nfor each source in '+literal(cases)+'\nanswers.Push(SiloCompatSourceMetadata({MediaSources:[source]},p))\nend for\nprint FormatJson({proof:p,answers:answers})'
  result=self.execute(body)
  self.assertIsNotNone(result['answers'][0]);self.assertEqual([None]*6,result['answers'][1:])
  self.assertTrue(result['proof']['audioInventory'][0]['isDefault']);self.assertFalse(result['proof']['audioInventory'][1]['isDefault'])
  self.assertEqual(45,len(result['proof']['subtitleInventory']))

 def test_actual_technical_shape_runs_adapter_and_preserves_all_45_pgs_tracks(self):
  technical=json.loads((ROOT/'tests/fixtures/silo/stock_p7_hdr10_technical_metadata.json').read_text())
  version=copy.deepcopy(technical['native_version']);version['file_id']='731'
  raw={'content_id':'fixture-item','type':'movie','title':'Synthetic Fixture','versions':[version]}
  metadata={'MediaSources':[copy.deepcopy(technical['compat_metadata'])]}
  receipt={'MediaSources':[copy.deepcopy(technical['compat_receipt'])],'PlaySessionId':'play-fixture'}
  source='03000000-0000-0000-0000-0000000002db'
  metadata['MediaSources'][0]['Id']=source;receipt['MediaSources'][0]['Id']=source
  receipt['MediaSources'][0]['TranscodingUrl']='/Videos/'+source+'/remux-dv-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId='+source
  c=self.data()
  body='c='+literal(c)+'\ndecoded=DecodeSiloResponse("detail",FormatJson('+literal(raw)+'),{sourceId:"silo:fixture"})\ndetail=ScopeCatalogData(decoded.data,"silo:fixture")\np=SiloCompatCandidate(detail,c.owner,c.params,c.snapshot,c.kind)\nmetaResult=SiloCompatSourceMetadata('+literal(metadata)+',p)\nr=SiloCompatPlaybackReceipt('+literal(receipt)+',p,"http://fixture.invalid",2)\nprint FormatJson({proof:p,metadata:metaResult,receipt:r,profile:SiloCompatDeviceProfile(p)})'
  result=self.execute(body)
  self.assertIsNotNone(result['proof']);self.assertEqual(1,result['proof']['audioOrdinal']);self.assertEqual(45,len(result['proof']['subtitleInventory']))
  self.assertTrue(result['proof']['audioInventory'][0]['isDefault']);self.assertEqual('truehd',result['proof']['audioInventory'][0]['codec'])
  self.assertEqual(45,result['metadata']['subtitleCount']);self.assertEqual(49,len(result['metadata']['source']['MediaStreams']))
  self.assertEqual('copied_p7_hdr10_fmp4',result['receipt']['class'])
  original=metadata['MediaSources'][0]['MediaStreams'];selected=receipt['MediaSources'][0]['MediaStreams']
  self.assertEqual(['Embed']*45,[x['DeliveryMethod'] for x in original if x['Type']=='Subtitle'])
  self.assertEqual(['Encode']*45,[x['DeliveryMethod'] for x in selected if x['Type']=='Subtitle'])

 def test_profile_refuses_selected_audio_type_drift_after_candidate(self):
  c=self.data();results=[]
  for change in ['p.audio.isDefault=0','p.audio.sourceOrdinal="1"']:
   results.append(self.execute('c='+literal(c)+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind)\np.audio=ParseJson(FormatJson(p.audio),"i")\n'+change+'\nprint FormatJson(SiloCompatDeviceProfile(p))'))
  self.assertEqual([{},{}],results)

 def test_profile_refuses_a_proof_with_lost_canonical_source_identity(self):
  c=self.data()
  result=self.execute('c='+literal(c)+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind)\np.fileId=invalid:p.mediaSourceId=invalid\nprint FormatJson(SiloCompatDeviceProfile(p))')
  self.assertEqual({},result)

 def test_hdr10_mp4_snapshot_uses_exact_video_and_selected_ac3_queries_without_dv(self):
  value=self.snapshots([self.config()])[0];snapshot=value['snapshot']
  self.assertTrue(snapshot['hdr10']);self.assertNotIn('dolbyvision',snapshot)
  self.assertEqual({'codec':'hevc','container':'mp4','profile':'main 10','level':'5.1','result':True},snapshot['videoQuery'])
  self.assertEqual(('mp4','ac3',6,False,True),(snapshot['audioContainer'],snapshot['audioCodec'],snapshot['audioChannels'],snapshot['audioDecode'],snapshot['audioPassthrough']))
  self.assertEqual([{'codec':'hevc','container':'mp4','profile':'main 10','level':'5.1'},{'codec':'ac3','container':'mp4','chcnt':6,'passthru':0},{'codec':'ac3','container':'mp4','chcnt':6,'passthru':1}],value['queries'])

 def test_long_duration_metadata_keeps_exact_ticks_and_rejects_fractional_or_drift(self):
  c=self.data();c['detail']['versions'][0]['durationMs']=6214000
  c.update(metadata=self.metadata(),receipt=self.receipt())
  values=[]
  # Explicit doubles preserve sub-tick drift at film durations; ParseJson on the
  # host BRS runner can otherwise narrow JSON floats to single precision.
  for ticks in ['62140000000#','62140000000.5#','62140000001#','"62140000000"','invalid']:
   body='c='+literal(c)+'\nc.metadata.MediaSources[0].RunTimeTicks='+ticks+'\nc.receipt.MediaSources[0].RunTimeTicks='+ticks+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind)\nprint FormatJson({metadata:SiloCompatSourceMetadata(c.metadata,p),receipt:SiloCompatPlaybackReceipt(c.receipt,p,"http://fixture.invalid",2)})'
   values.append(self.execute(body))
  self.assertIsNotNone(values[0]['metadata']);self.assertIsNotNone(values[0]['receipt'])
  for value in values[1:]:self.assertIsNone(value['metadata']);self.assertIsNone(value['receipt'])

 def test_required_hdr10_mp4_sdk_facts_refuse_unknown_and_audio_directions_are_independent(self):
  configs=[]
  for name in ['model','details','modelType','os','videoMode','display','video51']:
   configs.append(dict(self.config(),fail=name))
  for name,value in [('model',[]),('details',{}),('os',{}),('videoMode','2160p24Dv'),('display',{'hdr10':1}),('display',{'hdr10':False}),('display',{}),('video51',{'result':'true'}),('video51',{'result':1}),('video51',{'result':False})]:
   c=self.config();c[name]=value;configs.append(c)
  results=self.snapshots(configs);cases=[]
  for r in results:
   c=self.data();c['snapshot']=r['snapshot'];cases.append(c)
  self.assertEqual([None]*len(cases),self.candidates(cases))
  positive=[dict(self.config(),fail='decode'),dict(self.config(),decode={'result':True},fail='passthrough')]
  cases=[]
  for r in self.snapshots(positive):
   c=self.data();c['snapshot']=r['snapshot'];cases.append(c)
  self.assertTrue(all(p is not None for p in self.candidates(cases)))
  c=self.config();c.update(decode={'result':1},passthrough={'result':'true'})
  case=self.data();case['snapshot']=self.snapshots([c])[0]['snapshot'];self.assertEqual([None],self.candidates([case]))

 def test_candidate_rejects_source_selection_cap_and_container_drift(self):
  changes=[('video','dv_profile',8),('video','dv_el_present',False),('video','dv_config_present','true'),('video','level','153'),('video','frame_rate','25'),('video','color_transfer','bt709'),('version','container','mp4'),('version','bitrateKbps',0),('params','audioTrackIndex',0),('params','audioTrackId','file:731:audio:2'),('params','bandwidthCapKbps',62829),('params','subtitleMode','auto'),('params','qualityPreference','auto'),('snapshot','hdr10',1),('snapshot','audioContainer','ts')]
  cases=[]
  for target,key,value in changes:
   c=self.data();version=c['detail']['versions'][0]
   row=version['videoTracks'][0] if target=='video' else version if target=='version' else c[target]
   row[key]=value;cases.append(c)
  self.assertEqual([None]*len(cases),self.candidates(cases))

 def test_receipt_refuses_cross_route_defaults_and_non_pgs_delivery_changes(self):
  cases=[]
  for key,value in [('TranscodingContainer','ts'),('TranscodingSubProtocol','http'),('SupportsDirectPlay',True),('SiloSeekReanchor',1),('DefaultSubtitleStreamIndex',-1),('DefaultAudioStreamIndex',1),('TranscodingUrl','http://foreign.invalid/master.m3u8')]:
   c=self.data();c.update(metadata=self.metadata(),receipt=self.receipt());c['receipt']['MediaSources'][0][key]=value;cases.append(c)
  for key,value in [('DeliveryMethod','Embed'),('IsDefault',True),('IsForced',True),('Language','xx'),('Codec','subrip'),('Index',9),('IsTextSubtitleStream',True)]:
   c=self.data();c.update(metadata=self.metadata(),receipt=self.receipt());c['receipt']['MediaSources'][0]['MediaStreams'][4][key]=value;cases.append(c)
  for value in self.wire(cases):self.assertIsNotNone(value['metadata']);self.assertIsNone(value['receipt'])

 def test_stock_first_audio_default_fallback_does_not_rewrite_native_inventory(self):
  c=self.data();c.update(metadata=self.metadata(),receipt=self.receipt())
  for audio in c['detail']['versions'][0]['audioTracks']:audio['isDefault']=False
  value=self.wire([c])[0]
  self.assertIsNotNone(value['metadata']);self.assertIsNotNone(value['receipt'])
  proof=self.candidates([c])[0];self.assertFalse(any(a['isDefault'] for a in proof['audioInventory']))

 def test_metadata_refuses_audio_wire_index_drift_from_native_inventory(self):
  cases=[]
  for index in [0,2]:
   c=self.data();c.update(metadata=self.metadata(),receipt=self.receipt())
   c['metadata']['MediaSources'][0]['MediaStreams'][index]['Index']=9;cases.append(c)
  for value in self.wire(cases):self.assertIsNone(value['metadata'])

 def test_kind_dispatch_preserves_p8_class_and_rejects_lost_p7_kind(self):
  c=self.data()
  result=self.execute('c='+literal(c)+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind)\np.Delete("eligibilityKind")\nprint FormatJson({profile:SiloCompatDeviceProfile(p),metadata:SiloCompatSourceMetadata('+literal(self.metadata())+',p),classes:[SiloCompatClassForKind(),SiloCompatClassForKind("experimental_query_p8_ts_v1"),SiloCompatClassForKind("experimental_query_p7_hdr10_fmp4_v1"),SiloCompatClassForKind("unknown")]})')
  self.assertEqual({},result['profile']);self.assertIsNone(result['metadata'])
  self.assertEqual(['copied_dv8_ts','copied_dv8_ts','copied_p7_hdr10_fmp4',None],result['classes'])

 def test_aac_p7_candidate_requires_bound_explicit_opt_in_and_keeps_source_separate_from_target(self):
  c=self.aac_case()
  absent=copy.deepcopy(c);absent.pop('qualification')
  versionOnly=copy.deepcopy(c);versionOnly['qualification']={'serverVersion':'0.1.0'}
  generationMismatch=copy.deepcopy(c);generationMismatch['qualification']['generation']=8
  sourceMismatch=copy.deepcopy(c);sourceMismatch['qualification']['sourceId']='silo:other'
  profileMismatch=copy.deepcopy(c);profileMismatch['qualification']['profileId']='other-profile'
  revisionMismatch=copy.deepcopy(c);revisionMismatch['qualification']['sessionRevision']=1
  versionExtra=copy.deepcopy(c);versionExtra['qualification']['serverVersion']='0.1.0'
  wrongKind=copy.deepcopy(c);wrongKind['qualification']['kind']='stock48ae-p7-hdr10-aac2-v2'
  malformed=copy.deepcopy(c);malformed['qualification']['approved']=1
  valid=self.candidates([absent,versionOnly,generationMismatch,sourceMismatch,profileMismatch,revisionMismatch,versionExtra,wrongKind,malformed,c])
  self.assertEqual([None]*9,valid[:9])
  proof=valid[9]
  self.assertEqual(AAC_KIND,proof['eligibilityKind'])
  self.assertEqual((0,'truehd',8,True),(proof['audioOrdinal'],proof['audio']['codec'],proof['audio']['channels'],proof['audio']['isDefault']))
  self.assertEqual(3,len(proof['audioInventory']));self.assertEqual(2,len(proof['subtitleInventory']))
  self.assertTrue(proof['audioInventory'][0]['isDefault']);self.assertFalse(proof['audioInventory'][1]['isDefault'])
  self.assertEqual({'codec':'aac','channels':2},proof['targetAudio'])
  self.assertEqual(c['qualification']['sourceId'],proof['instanceQualification']['sourceId'])
  alternate=self.aac_case(1);alternateProof=self.candidates([alternate])[0]
  self.assertEqual((1,'ac3',6,False),(alternateProof['audioOrdinal'],alternateProof['audio']['codec'],alternateProof['audio']['channels'],alternateProof['audio']['isDefault']))
  classes=self.execute('print FormatJson({aac:SiloCompatClassForKind('+literal(AAC_KIND)+')})')
  self.assertEqual('converted_p7_hdr10_aac_fmp4',classes['aac'])

 def test_aac_p7_sdk_snapshot_requires_typed_mp4_aac2_decode(self):
  positive=dict(self.config(),display={'hdr10':True},decode={'result':True})
  negative=dict(positive,decode={'result':False})
  malformed=dict(positive,decode={'result':1})
  values=self.aac_snapshots([positive,negative,malformed])
  self.assertEqual({'codec':'hevc','container':'mp4','profile':'main 10','level':'5.1'}, {k:v for k,v in values[0]['queries'][0].items() if k!='result'})
  self.assertEqual([{'codec':'aac','container':'mp4','chcnt':2,'passthru':0}],values[0]['queries'][1:])
  self.assertTrue(values[0]['snapshot']['targetAudioDecode'])
  self.assertEqual({},values[1]['snapshot']);self.assertEqual({},values[2]['snapshot'])

 def test_aac_p7_source_inventory_profile_and_receipt_keep_original_stream_metadata(self):
  c=self.aac_case();c.update(metadata=self.metadata(),receipt=self.receipt(),wireAudioIndex=1)
  source=c['receipt']['MediaSources'][0]
  source['DefaultAudioStreamIndex']=1
  for track in source['MediaStreams']:
   if track['Type']=='Audio':track['IsDefault']=track['Index']==1
  value=self.wire([c])[0]
  self.assertEqual(1,value['metadata']['audioStreamIndex'])
  original=value['metadata']['source']['MediaStreams']
  audios=[track for track in original if track['Type']=='Audio']
  self.assertEqual([('truehd',8,True),('ac3',6,False),('ac3',2,False)],[(x['Codec'],x['Channels'],x['isDefault']) for x in audios])
  profile=value['profile'];self.assertEqual([],profile['DirectPlayProfiles'])
  self.assertEqual({'Type':'Video','Context':'Streaming','Protocol':'hls','Container':'mp4','VideoCodec':'hevc','audioCodec':'aac','MaxAudioChannels':'2'},profile['TranscodingProfiles'][0])
  self.assertEqual([{'Condition':'EqualsAny','Property':'VideoRangeType','Value':'HDR10','IsRequired':True},{'Condition':'EqualsAny','Property':'VideoCodecTag','Value':'hvc1','IsRequired':True}],profile['CodecProfiles'][0]['Conditions'])
  receipt=value['receipt'];self.assertEqual('converted_p7_hdr10_aac_fmp4',receipt['class']);self.assertEqual(1,receipt['audioStreamIndex'])
  self.assertIn('/remux-dv-v1/',receipt['url']);self.assertNotIn('targetAudio',receipt);self.assertNotIn('audioCodec',receipt)
  invalidProof=self.execute('c='+literal(c)+'\np=SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind,c.qualification)\np.Delete("instanceQualification")\nprint FormatJson(SiloCompatDeviceProfile(p))')
  self.assertEqual({},invalidProof)

 def test_aac_p7_candidate_rejects_wrong_original_source_and_target_evidence(self):
  cases=[]
  for key,value in [('codec','dts'),('channels',6),('sourceOrdinal',1)]:
   c=self.aac_case();c['detail']['versions'][0]['audioTracks'][0][key]=value;cases.append(c)
  c=self.aac_case();c['params']['audioTrackIndex']=1;c['params']['audioTrackId']='file:731:audio:0';cases.append(c)
  for key,value in [('targetAudioCodec','ac3'),('targetAudioChannels',6),('targetAudioDecode',False),('targetAudioDecode',1),('targetAudioContainer','ts')]:
   c=self.aac_case();c['snapshot'][key]=value;cases.append(c)
  self.assertEqual([None]*len(cases),self.candidates(cases))

if __name__=='__main__':unittest.main()
