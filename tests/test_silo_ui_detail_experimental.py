"""Experimental Detail action is qualified, opt-in and scoped to fresh intent."""
import json,re,tempfile,unittest
from pathlib import Path
from tools.brightscript import run_function,run_brightscript
ROOT=Path(__file__).resolve().parents[1];POLICY=ROOT/'source/core/SiloUIDetailPolicy.brs'
def version(id='4k',profile=8):
 return dict(versionId=id,videoTracks=[dict(codec='hevc',width=3840,height=2160,dv_profile=profile,dv_bl_compat_id=6 if profile==7 else 1,bit_depth=10,color_transfer='smpte2084',color_primaries='bt2020',color_space='bt2020nc')],audioTracks=[])
class ExperimentalDetail(unittest.TestCase):
 def candidate(self,rows,selected='',provider='silo',kind='movie'):
  return run_function(POLICY,'SiloUIDetailExperimentalVersion',[provider,dict(itemId='movie',type=kind),rows,selected])
 def test_unique_qualified_file_and_explicit_selection_are_independent_of_first_version(self):
  low=version('1080');low['videoTracks'][0].update(width=1920,height=1080)
  self.assertEqual('4k',self.candidate([low,version()]))
  self.assertEqual('',self.candidate([version(),version('other')]))
  self.assertEqual('other',self.candidate([version(),version('other',7)],'other'))
  self.assertEqual('',self.candidate([low,version()],'1080'))
 def test_cinematic_4k_heights_are_offered_within_existing_decoder_bounds(self):
  for height in [1600,1608,1920,2160]:
   row=version();row['videoTracks'][0]['height']=height
   self.assertEqual('4k',self.candidate([row]),height)
  for height in [0,-1,2161,1600.5,'1600',True,None]:
   row=version();row['videoTracks'][0]['height']=height
   self.assertEqual('',self.candidate([row]),height)
 def test_cinematic_gate_rejects_malformed_width(self):
  for width in [True,False,'3840',3840.5,4096,None]:
   row=version();row['videoTracks'][0].update(width=width,height=1600)
   self.assertEqual('',self.candidate([row]),repr(width))
 def test_refuses_profile5_non_hdr10_non4k_ambiguous_and_non_silo(self):
  for key,value in [('dv_profile',5),('dv_bl_compat_id',0),('width',1920),('bit_depth',8),('color_transfer','arib-std-b67'),('codec','h264')]:
   row=version();row['videoTracks'][0][key]=value;self.assertEqual('',self.candidate([row]),key)
  self.assertEqual('',self.candidate([version(),version()]))
  self.assertEqual('',self.candidate([version()],provider='plex'))
  self.assertEqual('',self.candidate([version()],kind='series'))
 def flow(self,body,boundary_extra="",files_extra=()):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);s=(ROOT/'components/SiloUIDetail.brs').read_text();s=re.sub(r'(?m)^sub DetailRender\(','sub UnusedDetailRender(',s,count=1)
   (p/'detail.brs').write_text(s)
   (p/'boundary.brs').write_text('''sub DetailRender(item as Object)
m.renderCount++
m.pillGroups.detailButtons.index=0
end sub
sub PaintButtons(name as String,focused as Boolean)
end sub
sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
m.requests.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
sub Toast(message as String)
m.message=message
end sub
sub PlayItem(item as Object,startMs as Dynamic,fileId="" as String,audio=invalid as Dynamic,ticket=invalid as Dynamic)
m.played={fileId:fileId,audio:audio,ticket:ticket,start:startMs}
end sub
'''+boundary_extra)
   setup='''m.provider="silo":m.sourceId="silo:one":m.profileId="profile":m.generation=2:m.view="detail":m.detailToken=4
m.detailItem={itemId:"movie",type:"movie",resumeMs:75000}:m.detailAudioChoice=invalid
m.detailSelectedVersion="":m.detailExperimentalDetail={item:m.detailItem}:m.requests=[]:m.renderCount=0:m.detailActions=["Play","Mark watched"]:m.pillGroups={detailButtons:{index:1}}:m.zone="detailButtons"
'''+ 'm.detailVersions=ParseJson("'+json.dumps([version()]).replace('"','""')+'")\n'
   out=run_brightscript([POLICY,ROOT/'source/core/SiloUIFormat.brs',p/'detail.brs',p/'boundary.brs',*files_extra],setup+body,root=p)
   return json.loads(out.strip().splitlines()[-1])
 def test_probe_and_click_are_explicit_and_capture_current_ticket(self):
  value=self.flow('''DetailExperimentalProbe():request=m.requests[0]
DetailResult("detail_experimental_probe",{ok:true},{available:true},request.extra)
m.detailActions=["Play","Experimental Play"]:DetailAction(1)
print FormatJson({action:request.action,file:request.params.fileId,ticket:m.played.ticket,played:m.played.fileId,start:m.played.start,message:m.message})''')
  self.assertEqual('experimental_playback_probe',value['action']);self.assertEqual('4k',value['played']);self.assertEqual(75000,value['start']);self.assertEqual('experimental_original',value['ticket']['kind']);self.assertEqual('null',value['ticket']['audioSignature']);self.assertIn('HDR fallback',value['message'])
 def test_stale_failure_and_unknown_probe_cannot_offer_or_dispatch(self):
  for change in ['m.detailToken=5','m.generation=3','m.detailSelectedVersion="gone"','m.detailAudioChoice={}']:
   value=self.flow('''DetailExperimentalProbe():old=m.requests[0].extra
'''+change+'''
DetailResult("detail_experimental_probe",{ok:true},{available:true},old)
m.detailActions=["Experimental Play"]:DetailAction(0)
print FormatJson({available:m.detailExperimentalAvailable,played:m.played})''')
   self.assertIsNone(value['played']);self.assertIsNot(value['available'],True)
 def test_probe_requires_boolean_availability_and_preserves_focus(self):
  for expression in ['{ok:false},{available:true}','{ok:true},{}','{ok:true},{available:1}','{ok:true},{available:"true"}']:
   value=self.flow('''DetailExperimentalProbe():ticket=m.requests[0].extra
DetailResult("detail_experimental_probe",'''+expression+''',ticket)
print FormatJson({available:m.detailExperimentalAvailable,focus:m.pillGroups.detailButtons.index})''')
   self.assertFalse(value['available']);self.assertEqual(1,value['focus'])
 def test_probe_audio_is_canonical_and_old_owner_choice_cannot_probe(self):
  value=self.flow('''m.detailVersions[0].AddReplace("audioTracks",[{id:"3",sourceOrdinal:0,codec:"aac",language:"en",channels:2},{id:"4",sourceOrdinal:1,codec:"ac3",language:"en",channels:6}])
choices=SiloUIDetailAudioChoices("silo",m.detailItem,m.detailVersions,"")
m.detailAudioChoice=choices[1]:m.detailAudioChoice.visit=4:m.detailAudioChoice.sourceId=m.sourceId:m.detailAudioChoice.profileId=m.profileId:m.detailAudioChoice.generation=2
DetailExperimentalProbe():request=m.requests[0]
m.detailAudioChoice.sourceId="silo:old":DetailExperimentalProbe()
print FormatJson({count:m.requests.Count(),index:request.params.audioTrackIndex,id:request.params.audioTrackId,current:m.detailExperimentalTicket<>invalid})''')
  self.assertEqual(1,value['count']);self.assertEqual(1,value['index']);self.assertEqual('file:4k:audio:1',value['id']);self.assertFalse(value['current'])
 def test_old_same_file_probe_and_refusal_do_not_reenable(self):
  value=self.flow('''DetailExperimentalProbe():old=m.requests[0].extra
DetailExperimentalProbe():fresh=m.requests[1].extra
DetailResult("detail_experimental_probe",{ok:true},{available:true},old)
a=m.detailExperimentalAvailable
DetailResult("detail_experimental_probe",{ok:true},{available:false},fresh)
print FormatJson({old:a,current:m.detailExperimentalAvailable,played:m.played})''')
  self.assertFalse(value['old']);self.assertFalse(value['current']);self.assertIsNone(value['played'])
if __name__=='__main__':unittest.main()
