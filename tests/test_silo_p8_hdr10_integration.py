"""SDK and dormant producer boundaries for P8 HDR10; synthetic facts only."""
import unittest
from tests import test_silo_p7_hdr10_compat_policy as p7
from tests import test_silo_p8_hdr10_compat_policy as p8

class P8HDR10Integration(unittest.TestCase):
 def test_sdk_queries_exact_mp4_level_and_retains_real_dolby_vision(self):
  helper=p7.P7HDR10Policy();cfg=helper.config()
  cfg['display']['DolbyVision']=True;cfg['video50']={'result':True}
  rows=helper.snapshots([cfg],audio={'codec':'eac3','channels':6},video={'level':150},kind=p8.KIND)
  snapshot=rows[0]['snapshot']
  self.assertTrue(snapshot.get('hdr10'));self.assertTrue(snapshot.get('dolbyVision'))
  self.assertEqual([{'codec':'hevc','container':'mp4','profile':'main 10','level':'5.0'}, {'codec':'eac3','container':'mp4','chcnt':6,'passthru':0}, {'codec':'eac3','container':'mp4','chcnt':6,'passthru':1}],rows[0]['queries'])

 def test_producer_gate_selects_hdr10_without_mutating_real_device_facts(self):
  import re,tempfile
  from pathlib import Path
  from tools.brightscript import _execute
  from tests import test_silo_modern_compat_policy as modern
  source=(p7.ROOT/'components/ApiTask.brs').read_text()
  functions=[]
  for name in ['SiloCompatPreparationEnabled','SiloP8HDR10CompatPreparationEnabled','SiloP8HDR10AutomaticPreparationEnabled','TaskSiloCompatProof']:
   match=re.search(r'function '+name+r'\([^\n]*\n.*?end function',source,re.S)
   self.assertIsNotNone(match,name);functions.append(match.group())
  cfg=p7.P7HDR10Policy().config();cfg['display']['DolbyVision']=True;cfg['video50']={'result':True}
  c=p8.P8HDR10Policy().data()
  for gate,expected in [(False,"experimental_query_p8_ts_v1"),(True,p8.KIND)]:
   with self.subTest(gate=gate), tempfile.TemporaryDirectory(dir='/dev/shm') as td:
    root=Path(td);sdk=root/'sdk.brs'
    text='\n'.join(functions).replace('function SiloCompatPreparationEnabled()', 'function ShippingPreparationEnabled()')
    text+='\nfunction SiloCompatPreparationEnabled() as Boolean\n return true\nend function\n'
    if gate:
     text=text.replace('function SiloP8HDR10CompatPreparationEnabled()', 'function ShippingHDR10Enabled()')
     text+='\nfunction SiloP8HDR10CompatPreparationEnabled() as Boolean\n return true\nend function\n'
    sdk.write_text(modern.SDK+'\n'+text)
    prefix='GetGlobalAA().config='+p7.literal(cfg)+'\nGetGlobalAA().queries=[]\nc='+p7.literal(c)+'\nv=c.detail.versions[0]\np=TaskSiloCompatProof(c.detail,c.owner,c.params,Device(),v.audioTracks[0],v)'
    result=_execute([*modern.FILES,sdk],prefix,root,'p')['result']
    self.assertIsNotNone(result)
    self.assertEqual(expected,result.get('eligibilityKind',result.get('eligibilitykind')))
 def scene(self,control="media_close"):
  import copy
  from tests import test_silo_modern_compat_flow as flow
  from tests import test_silo_compat_playback_task as holder
  from tests import test_silo_compat_continuation as native
  from tests.test_silo_single_source_compat_flow import single_source
  envelope=native.CompatContinuation().job(device=flow.modern_device(),mutate=single_source)['outcome']
  envelope['compatContinuation']['eligibilityKind']=p8.KIND
  _,wire,_=native.CompatContinuation().fixture()
  del wire['versions'][1:]
  def change(values):
   values['metadata']=p8.P8HDR10Policy().metadata()
   values['playback']=p8.P8HDR10Policy().receipt()
   for name in ['metadata','playback']:
    values[name]['MediaSources'][0]['RunTimeTicks']=72000000000
  device=flow.modern_device()
  result=holder.CompatPlaybackTask().transcript(scene=dict(envelope=copy.deepcopy(envelope),wire=wire,control=control),change=change,device_overrides=device)
  return result
 def test_scene_holder_admit_hdr10_and_close_exact_owned_session(self):
  from tests import test_silo_modern_compat_flow as flow
  result=self.scene()
  self.assertTrue(result['scene'].get('released'),result)
  self.assertEqual('copied_p8_hdr10_fmp4',result['results'][0].get('class'))
  flow.ModernCompatFlow().assert_owned_logout(result,media=True)

 def test_source_seek_reanchors_hdr10_twice_and_owned_close_retires_all_generations(self):
  result=self.scene("media_roundtrip")
  prepared=[r for r in result['results'] if r.get('phase')=='prepared']
  self.assertEqual(['copied_p8_hdr10_fmp4']*3,[r.get('class') for r in prepared])
  self.assertTrue(result['scene']['released'])
  self.assertEqual(3,sum('/PlaybackInfo' in r['url'] for r in result['requests']))
  self.assertTrue(result['results'][-1]['credentialRevoked'])
