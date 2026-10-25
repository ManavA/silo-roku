"""Dormant query-driven TS P8 eligibility; synthetic SDK/policy evidence only."""
import copy,json,tempfile,unittest
from pathlib import Path
from tools.brightscript import _execute
from tests.test_silo_playback_task import FILES as NATIVE_FILES
from tests import test_silo_p8_original_transport as native
ROOT=Path(__file__).resolve().parents[1]
KIND='experimental_query_p8_ts_v1'
FILES=[*NATIVE_FILES,ROOT/'source/core/SiloNativeBearerTransport.brs',ROOT/'source/core/SiloCompatPlaybackPolicy.brs',ROOT/'source/core/SiloCompatCapability.brs']
def literal(x):return 'ParseJson("'+json.dumps(x).replace('"','""')+'","i")'
SDK='''
function Fact(name as String) as Dynamic
 c=GetGlobalAA().config
 if c.fail=name then throw "synthetic SDK refusal"
 return c[name]
end function
function Device() as Object
 return {GetModel:function() as Dynamic
 return Fact("model")
 end function,GetModelDetails:function() as Dynamic
 return Fact("details")
 end function,GetModelType:function() as Dynamic
 return Fact("modelType")
 end function,GetOSVersion:function() as Dynamic
 return Fact("os")
 end function,GetVideoMode:function() as Dynamic
 return Fact("videoMode")
 end function,GetDisplayProperties:function() as Dynamic
 return Fact("display")
 end function,CanDecodeVideo:function(q as Object) as Dynamic
 GetGlobalAA().queries.Push(q)
 if q.level="5.0" then return Fact("video50")
 return Fact("video51")
 end function,CanDecodeAudio:function(q as Object) as Dynamic
 GetGlobalAA().queries.Push(q)
 if q.passthru=0 then return Fact("decode")
 return Fact("passthrough")
 end function}
end function
'''
class ModernCompat(unittest.TestCase):
 def execute(self,body):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);sdk=root/'sdk.brs';sdk.write_text(SDK)
   # Return interpreter values directly: FormatJson cannot serialize every
   # retained normalized source value; AA keys emitted by BRS are lowercase.
   prefix,expression=body.rsplit('print FormatJson(',1)
   result=_execute([*FILES,sdk],prefix,root,expression[:-1])["result"]
   names="modelNumber modelType videoMode dolbyVision hevcMain10 audioCodec audioChannels audioDecode audioPassthrough videoQuery audioContainer eligibilityKind mediaSourceId fileId audioOrdinal audioInventory startTicks subtitleMode".split()
   canonical={name.lower():name for name in names}
   def keys(value):
    if isinstance(value,list):return [keys(x) for x in value]
    if isinstance(value,dict):return {canonical.get(k.lower(),k):keys(v) for k,v in value.items()}
    return value
   return keys(result)
 def data(self):
  _,wire,_=native.SiloP8OriginalTransportTests().inputs();video=copy.deepcopy(wire['versions'][0]['video_tracks'][0]);video.update(level=150,frame_rate='24000/1001')
  source='silo:fixture';audio=dict(codec='eac3',channels=6,layout='5.1(side)',language='en',sourceOrdinal=0,isDefault=True)
  detail=dict(versionsComplete=True,item=dict(sourceId=source,itemId='fixture-item'),versions=[dict(sourceId=source,itemId='fixture-item',versionId='731',container='mkv',durationMs=60000,bitrateKbps=54000,videoTracks=[video],audioTracks=[audio])])
  owner=dict(provider='silo',sourceId=source,profileId='profile',generation=7,sessionRevision=0)
  params=dict(itemId='fixture-item',fileId='731',startPositionMs=0,subtitleMode='off',qualityPreference='original',audioTrackIndex=0,audioTrackId='file:731:audio:0')
  snapshot=dict(model='4850X',modelNumber='4850X',modelType='STB',os='17.1.2.5000',videoMode='2160p60',dolbyVision=True,hevcMain10=True,audioCodec='eac3',audioChannels=6,audioDecode=False,audioPassthrough=True,videoQuery=dict(codec='hevc',container='ts',profile='main 10',level='5.0',result=True),audioContainer='ts')
  return dict(detail=detail,owner=owner,params=params,snapshot=snapshot,kind=KIND)
 def candidates(self,cases):
  return self.execute('answers=[]\nfor each c in '+literal(cases)+'\n answers.Push(SiloCompatCandidate(c.detail,c.owner,c.params,c.snapshot,c.kind))\nend for\nprint FormatJson(answers)')
 def config(self):return dict(model='4850X',details={'ModelNumber':'4850X'},modelType='STB',os={'major':'17','minor':'1','revision':'2','build':'5000'},videoMode='2160p60',display={'DolbyVision':True},video50={'result':True},video51={'result':False},decode={'result':False},passthrough={'result':True})
 def snapshots(self,configs,kind=KIND,level=150):
  return self.execute('answers=[]\nfor each c in '+literal(configs)+'\n GetGlobalAA().config=c:GetGlobalAA().queries=[]\n s=SiloCompatSnapshotForKind(Device(),{codec:"eac3",channels:6},'+literal(kind)+',{level:'+str(level)+'})\n answers.Push({snapshot:s,queries:GetGlobalAA().queries})\nend for\nprint FormatJson(answers)')
 def test_modern_models_and_exact_level50_ts_work_without_generic51(self):
  cases=[]
  for model in ['4850X','3820X','future-9900X']:
   c=self.data();c['snapshot'].update(model=model,modelNumber=model);cases.append(c)
  for proof in self.candidates(cases):self.assertEqual(KIND,proof['eligibilityKind'])
  value=self.snapshots([self.config()])[0];s=value['snapshot'];self.assertEqual(dict(codec='hevc',container='ts',profile='main 10',level='5.0',result=True),s['videoQuery']);self.assertEqual('ts',s['audioContainer'])
  self.assertEqual([dict(codec='hevc',container='ts',profile='main 10',level='5.0'),dict(codec='eac3',container='ts',chcnt=6,passthru=0),dict(codec='eac3',container='ts',chcnt=6,passthru=1)],value['queries'])
  c=self.data();c['snapshot']=s;self.assertIsNotNone(self.candidates([c])[0])
 def test_level51_maps153_and_recognized_refresh_modes_only(self):
  c=self.config();c['video51']={'result':True};value=self.snapshots([c],level=153)[0];self.assertEqual('5.1',value['snapshot']['videoQuery']['level'])
  cases=[]
  for mode in ['2160p24','2160p25','2160p30','2160p50','2160p60']:
   x=self.data();x['detail']['versions'][0]['videoTracks'][0]['level']=153;x['snapshot']=copy.deepcopy(value['snapshot']);x['snapshot']['videoMode']=mode;cases.append(x)
  self.assertTrue(all(x is not None for x in self.candidates(cases)))
  bad=[]
  for mode in ['2160p','2160p59','2160p60junk','1080p','']:
   x=self.data();x['snapshot']['videoMode']=mode;bad.append(x)
  self.assertEqual([None]*len(bad),self.candidates(bad))
 def test_required_sdk_missing_malformed_or_throw_refuses_but_audio_is_independent(self):
  configs=[]
  for name in ['model','details','modelType','os','videoMode','display','video50']:
   configs.append(dict(self.config(),fail=name))
  for name,value in [('model',None),('details',[]),('details',{}),('modelType',123),('os',{}),('display',{}),('display',{'DolbyVision':1}),('display',{'DolbyVision':False}),('video50',{'result':'true'}),('video50',{'result':False})]:
   c=self.config();c[name]=value;configs.append(c)
  for name in ['model','details','modelType','os','videoMode','display','video50']:
   c=self.config();c.pop(name);configs.append(c)
  results=self.snapshots(configs);cases=[]
  for r in results:
   c=self.data();c['snapshot']=r['snapshot'];cases.append(c)
  self.assertEqual([None]*len(cases),self.candidates(cases))
  configs=[dict(self.config(),fail='decode'),dict(self.config(),decode={'result':True},fail='passthrough'),dict(self.config(),decode={'result':1}),dict(self.config(),decode={'result':True},passthrough=[])]
  for r in self.snapshots(configs):
   c=self.data();c['snapshot']=r['snapshot'];self.assertIsNotNone(self.candidates([c])[0])
 def test_typed_snapshot_query_audio_identity_and_source_drift_refuse(self):
  changes=[lambda c:c['snapshot'].update(dolbyVision=1),lambda c:c['snapshot'].update(hevcMain10='true'),lambda c:c['snapshot'].update(audioContainer='mkv'),lambda c:c['snapshot'].update(audioChannels=2),lambda c:c['snapshot'].update(audioCodec='aac'),lambda c:c['snapshot'].update(audioDecode=False,audioPassthrough=False),lambda c:c['snapshot'].update(audioDecode='true'),lambda c:c['snapshot']['videoQuery'].update(container='mkv'),lambda c:c['snapshot']['videoQuery'].update(level='5.1'),lambda c:c['snapshot']['videoQuery'].update(result=1),lambda c:c['snapshot'].pop('videoQuery'),lambda c:c.update(kind='experimental_query_p8_ts_v2')]
  for name,value in [('model',''),('modelNumber',''),('modelType',''),('os','17.1.2')]:changes.append(lambda c,n=name,v=value:c['snapshot'].update({n:v}))
  for name,value in [('dv_profile',5),('dv_profile',7),('dv_el_present',True),('dv_bl_compat_id',0),('dv_rpu_present',False),('color_transfer','bt709'),('width',3841),('frame_rate','25'),('level',156),('level','150'),('dv_config_present','true'),('bit_depth','10'),('interlaced',0)]:changes.append(lambda c,n=name,v=value:c['detail']['versions'][0]['videoTracks'][0].update({n:v}))
  for name,value in [('bitrateKbps',0),('bitrateKbps',-1),('container','mp4')]:changes.append(lambda c,n=name,v=value:c['detail']['versions'][0].update({n:v}))
  for name,value in [('bandwidthCapKbps',53999),('qualityPreference','1080p'),('subtitleMode','on'),('audioTrackIndex',1),('audioTrackId','file:731:audio:1')]:changes.append(lambda c,n=name,v=value:c['params'].update({n:v}))
  for name in ['dv_config_present','dv_bl_present','dv_rpu_present','dv_bl_compat_id_present','interlaced','dv_profile','dv_level','dv_bl_compat_id','level','bit_depth']:
   changes.append(lambda c,n=name:c['detail']['versions'][0]['videoTracks'][0].pop(n,None))
  for name,value in [('sourceOrdinal',1),('channels',0),('channels',7),('language',''),('codec','aac')]:
   changes.append(lambda c,n=name,v=value:c['detail']['versions'][0]['audioTracks'][0].update({n:v}))
  cases=[]
  for change in changes:
   c=self.data();change(c);cases.append(c)
  self.assertEqual([None]*len(cases),self.candidates(cases))
 def test_legacy_snapshot_and_candidate_shape_stay_unchanged_unknown_kind_closed(self):
  cfg=self.config();cfg.update(model='C000X',details={'ModelNumber':'C208X'},modelType='TV',os={'major':'16','minor':'0','revision':'4','build':'834'},video51={'result':True})
  value=self.execute('GetGlobalAA().config='+literal(cfg)+'\nGetGlobalAA().queries=[]\n direct=SiloCompatSnapshot(Device(),{codec:"eac3",channels:6}):q=GetGlobalAA().queries\nGetGlobalAA().queries=[]\n absent=SiloCompatSnapshotForKind(Device(),{codec:"eac3",channels:6})\nprint FormatJson({direct:direct,queries:q,absent:absent,again:GetGlobalAA().queries})')
  self.assertEqual(value['direct'],value['absent']);self.assertEqual(value['queries'],value['again']);self.assertEqual(3,len(value['queries']));self.assertNotIn('container',value['queries'][0]);self.assertEqual(['mkv','mkv'],[q['container'] for q in value['queries'][1:]])
  c=self.data();c['snapshot']=value['direct'];c['kind']=None;proof=self.candidates([c])[0];self.assertIsNotNone(proof);self.assertNotIn('eligibilityKind',proof)
  # The Off receipt repair intentionally retains this one additional intent field.
  self.assertEqual({'mediaSourceId','fileId','video','audio','audioOrdinal','audioInventory','startTicks','snapshot','subtitleMode'},set(proof))
  self.assertEqual('off',proof['subtitleMode'])
  self.assertEqual({},self.snapshots([cfg],kind='unknown')[0]['snapshot'])
  c['kind']='unknown';self.assertIsNone(self.candidates([c])[0])
 def test_legacy_malformed_sdk_results_cannot_authorize_candidate(self):
  cfg=self.config();cfg.update(model='C000X',details={'ModelNumber':'C208X'},modelType='TV',os={'major':'16','minor':'0','revision':'4','build':'834'},video51={'result':True})
  configs=[]
  for name,value in [('display',{'DolbyVision':1}),('display',{'DolbyVision':'true'}),('video51',{'result':1}),('video51',{'result':'true'}),('decode',{'result':1}),('passthrough',{'result':'true'}),('details',[]),('model',[]),('modelType',[]),('os',{'major':16,'minor':0,'revision':4,'build':834})]:
   c=copy.deepcopy(cfg);c[name]=value
   if name in ('decode','passthrough'):
    c['decode']={'result':False};c['passthrough']={'result':False};c[name]=value
   configs.append(c)
  results=self.snapshots(configs,kind=None);cases=[]
  for r in results:
   c=self.data();c['kind']=None;c['snapshot']=r['snapshot'];cases.append(c)
  self.assertEqual([None]*6,self.candidates(cases[:6]))
  self.assertEqual([None]*4,self.candidates(cases[6:]))
 def test_documented_2160_suffix_modes_keep_typed_ts_eligibility(self):
  accepted=['2160p24b10','2160p25b10','2160p30b10','2160p50b10','2160p60b10','2160p30Dv','2160p60Dv']
  refused=['2160p24Dv','2160p25Dv','2160p50Dv','2160p60dv','2160p60b10junk']
  results=[]
  for mode in accepted+refused:
   cfg=self.config();cfg['videoMode']=mode;results.append(cfg)
  snapshots=self.snapshots(results);cases=[]
  for r in snapshots:
   c=self.data();c['snapshot']=r['snapshot'];cases.append(c)
  proofs=self.candidates(cases)
  self.assertEqual([True]*7+[False]*5,[p is not None for p in proofs])
  self.assertEqual(accepted,[p['snapshot']['videoMode'] for p in proofs[:7]])
