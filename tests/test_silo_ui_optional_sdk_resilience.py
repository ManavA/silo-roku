"""Optional render-thread SDK failures: unknown diagnostics, closed owned binding.

Only device/SG seams are substituted. Player policy, allocation-result handling,
native-first retirement and the cleanup ledger execute their actual code.
"""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.brightscript import run_brightscript
from tests import test_silo_ui_native_hdr10_scene as ordinary
from tests import test_silo_ordinary_p8_original as original
ROOT=Path(__file__).resolve().parents[1]
HEALTHY=dict(model='C000X',details={'ModelNumber':'C208X'},os={'major':'16','minor':'0','revision':'4','build':'834'},display={'Hdr10':True},mode='2160p60')
DEVICE='''
function OptionalRead(name as String) as Dynamic
 c=GetGlobalAA().optional
 if c.fail=name then throw "synthetic optional SDK failure"
 return c[name]
end function
function FixtureSiloDevice() as Dynamic
 if GetGlobalAA().optional.fail="create" then throw "synthetic optional SDK failure"
 if GetGlobalAA().optional.deviceInvalid=true then return invalid
 return {GetRandomUUID:function() as String
 return "20000000-0000-4000-8000-000000000001"
 end function,GetModel:function() as Dynamic
 return OptionalRead("model")
 end function,GetModelDetails:function() as Dynamic
 return OptionalRead("details")
 end function,GetOSVersion:function() as Dynamic
 return OptionalRead("os")
 end function,GetDisplayProperties:function() as Dynamic
 return OptionalRead("display")
 end function,GetVideoMode:function() as Dynamic
 return OptionalRead("mode")
 end function}
end function
'''
def literal(value):return 'ParseJson("'+json.dumps(value).replace('"','""')+'")'
class OptionalSdk(unittest.TestCase):
 def direct(self,body):
  with tempfile.TemporaryDirectory() as td:
   folder=Path(td);player=folder/'player.brs';player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()'))
   sdk=folder/'SDK.brs';sdk.write_text(DEVICE)
   output=run_brightscript([player,ROOT/'source/core/SiloUIFormat.brs',sdk],body,root=folder)
   return json.loads(output.strip().splitlines()[-1])
 def scene(self,config,tail='',outcomes=(),before_play=''):
  real=ordinary.run_brightscript
  def execute(files,body,*,root):
   if before_play:
    assert body.count(' PlayItem(')==1
    body=body.replace(' PlayItem(',before_play+'\n PlayItem(',1)
   return real(files,'GetGlobalAA().optional='+literal(config)+'\n'+body+'\n'+tail,root=root)
  sdk=ordinary.SDK.split('function FixtureSiloDevice()',1)[0]+DEVICE
  with patch.object(ordinary,'SDK',sdk),patch.object(ordinary,'run_brightscript',execute):
   return ordinary.OrdinaryNativeHdr10Scene().scene(outcomes)
 def test_video_mode_throw_create_and_wrong_types_are_unknown_without_fallback(self):
  cases=[dict(HEALTHY,deviceInvalid=True),dict(HEALTHY,fail='create'),dict(HEALTHY,fail='mode'),dict(HEALTHY,mode=123),dict(HEALTHY,mode=None)]
  values=self.direct('answers=[]\nfor each c in '+literal(cases)+'\n GetGlobalAA().optional=c\n answers.Push(PlayerVideoMode())\nend for\nprint FormatJson(answers)')
  self.assertEqual(['']*len(cases),values)
 def test_fingerprint_healthy_bytes_preserved_and_partial_or_throwing_facts_refuse(self):
  false=copy.deepcopy(HEALTHY);false['display']['Hdr10']=False
  cases=[HEALTHY,false,dict(HEALTHY,deviceInvalid=True)]
  for name in ['create','model','details','os','display','mode']:cases.append(dict(HEALTHY,fail=name))
  for name,value in [('details',[]),('details',{}),('os',[]),('os',{'major':'16','minor':'0','revision':'4'}),('display',[]),('display',{}),('display',{'Hdr10':'true'}),('display',{'Hdr10':1}),('mode',''),('mode',False),('model','')]:cases.append(dict(HEALTHY,**{name:value}))
  values=self.direct('answers=[]\nfor each c in '+literal(cases)+'\n GetGlobalAA().optional=c\n answers.Push(PlayerOriginalOutputFingerprint())\nend for\nprint FormatJson(answers)')
  self.assertEqual(['C000X/C208X/16.0.4.834/2160p60/hdr10','C000X/C208X/16.0.4.834/2160p60']+['']*(len(cases)-2),values)
 def test_cold_playitem_and_speed_quality_mode_failure_do_not_invent_output(self):
  value=self.scene(dict(HEALTHY,fail='mode'),tail='print FormatJson({mode:PlayerVideoMode(),quality:preTaskQuality,tasks:GetGlobalAA().tasks})',before_play='preTaskQuality=PlayerSpeedQuality({resolution:"2160p"})')
  self.assertEqual('',value['mode']);self.assertEqual('original',value['quality'])
  self.assertEqual(['detail'],[x['job']['action'] for x in value['tasks']])
  self.assertNotIn('clientCapabilities',value['tasks'][0]['job']['params']);self.assertNotIn('clientPlaybackContext',value['tasks'][0]['job']['params'])
 def test_up_diagnostics_unknown_mode_preserves_bound_playback(self):
  fixture=ordinary.OrdinaryNativeHdr10Scene();entry=fixture.scene();detail=fixture.task(entry['tasks'][0]['job'])['outcome'];selected=fixture.scene([detail]);started=fixture.task(selected['tasks'][1]['job'])['outcome']
  tail='m.diagnostics.visible=false:handled=PlayerKey("up"):print FormatJson({handled:handled,mode:m.diagnosticsOutputMode,lines:m.diagnosticsText.text.Split(Chr(10)),bound:m.video.content<>invalid,control:m.video.control})'
  value=self.scene(dict(HEALTHY,fail='mode'),tail,[detail,started])
  self.assertTrue(value['handled']);self.assertEqual('',value['mode']);self.assertTrue(value['bound']);self.assertEqual('play',value['control']);self.assertIn('Display mode: Unavailable',value['lines'])
 def test_real_allocated_result_bad_fresh_fingerprint_queues_owned_cleanup(self):
  fixture=ordinary.OrdinaryNativeHdr10Scene();entry=fixture.scene();detail=fixture.task(entry['tasks'][0]['job'])['outcome']
  result=original.OrdinaryP8Original().start(job={'requestId':2})['outcome'];self.assertTrue(result['ok'],result)
  healthy=self.scene(HEALTHY,outcomes=[detail,result]);self.assertTrue(healthy['bound'])
  rejected=self.scene(dict(HEALTHY,fail='display'),outcomes=[detail,result])
  self.assertFalse(rejected['bound']);self.assertEqual('stop',rejected['control']);self.assertEqual(1,rejected['tickets'])
  stops=[x['job'] for x in rejected['tasks'] if x['job']['action']=='playback_stop'];self.assertEqual(1,len(stops));self.assertEqual(result['plan']['sessionId'],stops[0]['params']['sessionId'])
