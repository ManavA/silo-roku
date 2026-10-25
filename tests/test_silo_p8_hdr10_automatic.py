"""Automatic fallback requires explicit negative DV evidence; QA stays separate."""
import copy,re,tempfile,unittest
from pathlib import Path
from tools.brightscript import _execute
from tests import test_silo_p8_hdr10_compat_policy as p8
from tests import test_silo_p7_hdr10_compat_policy as p7
from tests import test_silo_modern_compat_policy as modern

class AutomaticHDR10(unittest.TestCase):
 def test_automatic_candidate_requires_typed_negative_dv_and_full_hdr10_proof(self):
  good=p8.P8HDR10Policy().data();good['snapshot']['dolbyVision']=False
  cases=[good]
  for value in [None,True,0,'false']:
   c=copy.deepcopy(good);c['snapshot']['dolbyVision']=value;cases.append(c)
  c=copy.deepcopy(good);del c['snapshot']['dolbyVision'];cases.append(c)
  for key,value in [('hdr10',False),('hevcMain10',False),('audioDecode',False)]:
   c=copy.deepcopy(good);c['snapshot'][key]=value
   if key=='audioDecode':c['snapshot']['audioPassthrough']=False
   cases.append(c)
  result=p8.P8HDR10Policy().execute('answers=[]\nfor each c in '+p7.literal(cases)+'\nanswers.Push(SiloCompatP8HDR10AutomaticCandidate(c.detail,c.owner,c.params,c.snapshot))\nend for\nprint FormatJson(answers)')
  self.assertEqual(p8.KIND,result[0]['eligibilityKind']);self.assertEqual([None]*(len(cases)-1),result[1:])
 def producer(self,configs,gate=False,params=None):
  source=(p7.ROOT/'components/ApiTask.brs').read_text();functions=[]
  for name in ['SiloCompatPreparationEnabled','SiloP8HDR10CompatPreparationEnabled','SiloP8HDR10AutomaticPreparationEnabled','TaskSiloCompatProof']:
   match=re.search(r'function '+name+r'\([^\n]*\n.*?end function',source,re.S)
   self.assertIsNotNone(match,name);functions.append(match.group())
  text='\n'.join(functions)
  if gate is not None:
   text=text.replace('function SiloCompatPreparationEnabled()','function ShippingPreparationEnabled()')
   text+='\nfunction SiloCompatPreparationEnabled() as Boolean\n return true\nend function\n'
  if gate is not None:
   text=text.replace('function SiloP8HDR10AutomaticPreparationEnabled()','function ShippingAutomaticEnabled()')
   text+='\nfunction SiloP8HDR10AutomaticPreparationEnabled() as Boolean\n return '+str(gate).lower()+'\nend function\n'
  case=p8.P8HDR10Policy().data()
  if params:case['params'].update(params)
  with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
   root=Path(td);sdk=root/'sdk.brs';sdk.write_text(modern.SDK+'\n'+text)
   body='c='+p7.literal(case)+'\nanswers=[]\nfor each cfg in '+p7.literal(configs)+'\nGetGlobalAA().config=cfg:GetGlobalAA().queries=[]\nv=c.detail.versions[0]\np=TaskSiloCompatProof(c.detail,c.owner,c.params,Device(),v.audioTracks[0],v)\nanswers.Push(p)\nend for'
   return _execute([*modern.FILES,sdk],body,root,'answers')['result']
 def test_producer_auto_gate_and_unknown_dv_fail_closed(self):
  good=p7.P7HDR10Policy().config();good['video50']={'result':True}
  cases=[good]
  for display in [{'hdr10':True},{'hdr10':True,'DolbyVision':None},{'hdr10':True,'DolbyVision':'false'},{'hdr10':False,'DolbyVision':False}]:
   c=copy.deepcopy(good);c['display']=display;cases.append(c)
  for key in ['video50','decode','passthrough']:
   c=copy.deepcopy(good);c[key]={'result':False}
   if key in ['decode','passthrough']:c['decode']={'result':False};c['passthrough']={'result':False}
   cases.append(c)
  result=self.producer(cases,True)
  self.assertEqual(p8.KIND,result[0].get('eligibilityKind'));self.assertEqual([None]*(len(cases)-1),result[1:])
  self.assertEqual([None],self.producer([good],False,{'p8HDR10AutomaticPreparationEnabled':True,'eligibilityKind':p8.KIND}))
  dv=copy.deepcopy(good);dv['display']['DolbyVision']=True
  self.assertEqual('experimental_query_p8_ts_v1',{k.lower():v for k,v in self.producer([dv],True)[0].items()}.get('eligibilitykind'))

 def test_automatic_gate_preserves_negotiated_native_dv_selection(self):
  from tests import test_silo_compat_continuation as native
  result=native.CompatContinuation().job(automatic_hdr10=True,device={'major:"16",minor:"0",revision:"4",build:"834"':'major:"15",minor:"3",revision:"4",build:"2402"'},features=['native_hls_separate_audio_v1'])
  self.assertNotIn('compatContinuation',result['outcome'])
  import json
  starts=[json.loads(q['body']) for q in result['requests'] if '/playback/start' in q['url']]
  self.assertEqual(['731'],[q['file_id'] for q in starts])
 def test_automatic_single_source_without_native_proof_hands_off_hdr10(self):
  from tests import test_silo_compat_continuation as native
  from tests.test_silo_modern_compat_flow import modern_device
  def single_source(wire,decision):
   del wire['versions'][1:]
   wire['versions'][0]['subtitle_tracks']=[]
  device=modern_device();device['DolbyVision:true']='DolbyVision:false'
  result=native.CompatContinuation().job(automatic_hdr10=True,device=device,mutate=single_source)
  self.assertEqual('compat_prepare_required',result['outcome'].get('errorCode'),result['outcome'])
  self.assertEqual(p8.KIND,result['outcome']['compatContinuation']['eligibilityKind'])
  self.assertEqual({'state':'not_allocated'},result['outcome']['compatContinuation']['nativeClosure'])
  self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))

 def test_shipping_producer_prefers_dv_and_admits_only_typed_negative_hdr10(self):
  good=p7.P7HDR10Policy().config();good['video50']={'result':True}
  dv=copy.deepcopy(good);dv['display']['DolbyVision']=True
  unknown=copy.deepcopy(good);del unknown['display']['DolbyVision']
  result=self.producer([dv,good,unknown],gate=None)
  self.assertEqual('experimental_query_p8_ts_v1',{k.lower():v for k,v in result[0].items()}['eligibilitykind'])
  self.assertEqual(p8.KIND,{k.lower():v for k,v in result[1].items()}['eligibilitykind'])
  self.assertIsNone(result[2])
