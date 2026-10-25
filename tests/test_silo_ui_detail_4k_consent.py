"""Normal Detail actions offer scoped subtitle-off consent without changing defaults."""
import unittest
from tests import test_silo_ui_detail_experimental as detail

BOUNDARY='''
function ConsentSameNode(other as Object) as Boolean
 return m.tag=other.tag
end function
function ConsentEventNode() as Object
 return m.node
end function
sub BrowseDialog(title as String,labels as Object,handler as String)
 m.dialogLabels=labels
 m.browseDialog={tag:1,isSameNode:ConsentSameNode,buttonSelected:0}
 m.top={dialog:m.browseDialog}
 BrowseBindDialog(m.browseDialog,handler)
end sub
'''
READY='''m.preferences={quality:"original",subtitles:"always"}
DetailExperimentalProbe():probe=m.requests[0].extra
DetailResult("detail_experimental_probe",{ok:true},{available:true},probe)
m.detailActions=["Resume","From beginning"]
'''
class Detail4KConsent(unittest.TestCase):
 def flow(self,body):
  return detail.ExperimentalDetail().flow(READY+body,boundary_extra=BOUNDARY,files_extra=[detail.ROOT/'components/SiloUIDialogs.brs'])
 def answer(self,index):
  return 'm.browseDialog.buttonSelected='+str(index)+':event={node:m.browseDialog,getRoSGNode:ConsentEventNode}\nonDetail4KConsent(event)\n'
 def test_fast_play_waits_for_probe_then_offers_once_with_original_start(self):
  for action,start in [(0,75000),(1,0)]:
   body='m.preferences={subtitles:"always"}\nDetailExperimentalProbe():probe=m.requests[0].extra\nm.detailActions=["Resume","From beginning"]\nDetailAction('+str(action)+')\nDetailAction('+str(action)+')\nbefore=m.played\nDetailResult("detail_experimental_probe",{ok:true},{available:true},probe)\n'+'if m.browseDialog <> invalid\n'+self.answer(0)+'end if\nprint FormatJson({before:before,played:m.played,count:m.requests.Count()})'
   result=detail.ExperimentalDetail().flow(body,boundary_extra=BOUNDARY,files_extra=[detail.ROOT/'components/SiloUIDialogs.brs'])
   self.assertIsNone(result['before']);self.assertEqual(start,result['played']['start']);self.assertEqual('experimental_original',result['played']['ticket']['kind']);self.assertEqual(1,result['count'])
 def pending_flow(self,body):
  return detail.ExperimentalDetail().flow('m.preferences={subtitles:"always"}\nDetailExperimentalProbe():probe=m.requests[0].extra\nm.detailActions=["Resume","From beginning"]\nDetailAction(1)\n'+body,boundary_extra=BOUNDARY,files_extra=[detail.ROOT/'components/SiloUIDialogs.brs'])
 def test_fast_refusal_or_error_falls_back_once_at_captured_start(self):
  for response in ['{ok:true},{available:false}','{ok:false,errorCode:"network_timeout"},{}']:
   result=self.pending_flow('DetailResult("detail_experimental_probe",'+response+',probe)\nprint FormatJson({played:m.played,labels:m.dialogLabels,pending:m.detail4KPendingPlay})')
   self.assertEqual(0,result['played']['start']);self.assertEqual('',result['played']['fileId']);self.assertIsNone(result['played']['ticket']);self.assertIsNone(result['labels']);self.assertIsNone(result['pending'])
 def test_pending_play_is_cancelled_by_context_or_selection_drift(self):
  for change in ['m.browseViewToken=1','m.view="home"','m.detailSelectedVersion="gone"','m.detailAudioChoice={}','m.sourceId="silo:other"','m.profileId="other"','m.generation=3','m.detailToken=5','DetailExperimentalProbe()']:
   result=self.pending_flow(change+'\nDetailResult("detail_experimental_probe",{ok:true},{available:true},probe)\nprint FormatJson({played:m.played,labels:m.dialogLabels})')
   self.assertIsNone(result['played'],change);self.assertIsNone(result['labels'],change)
 def test_fast_play_dialog_repeat_cancel_and_duplicate_callback_are_one_shot(self):
  result=self.pending_flow('DetailResult("detail_experimental_probe",{ok:true},{available:true},probe)\nsequence=m.browseDialogSequence\nDetailAction(0)\n'+self.answer(2)+'DetailResult("detail_experimental_probe",{ok:true},{available:true},probe)\nprint FormatJson({played:m.played,sequence:sequence,after:m.browseDialogSequence})')
  self.assertIsNone(result['played']);self.assertEqual(result['sequence'],result['after'])
 def test_accept_preserves_exact_resume_or_start_and_ticket_without_mutating_preferences(self):
  for action,start in [(0,75000),(1,0)]:
   result=self.flow(('m.detailSelectedVersion="4k"\n' if action == 0 else '')+'DetailAction('+str(action)+')\nbefore=m.played\n'+self.answer(0)+'''print FormatJson({before:before,played:m.played,prefs:m.preferences,labels:m.dialogLabels})''')
   self.assertIsNone(result['before'])
   self.assertEqual((start,'4k','experimental_original'),(result['played']['start'],result['played']['fileId'],result['played']['ticket']['kind']))
   self.assertEqual('always',result['prefs']['subtitles'])
   self.assertEqual(['Play 4K without subtitles','Keep subtitle preference','Cancel'],result['labels'])
 def test_keep_uses_original_auto_selection_and_no_experimental_override(self):
  result=self.flow('DetailAction(0)\n'+self.answer(1)+'''print FormatJson({played:m.played,prefs:m.preferences})''')
  self.assertEqual('',result['played']['fileId']);self.assertIsNone(result['played']['ticket'])
  self.assertEqual(75000,result['played']['start']);self.assertEqual('always',result['prefs']['subtitles'])
 def test_cancel_and_changed_selection_do_not_start_playback(self):
  for change,index in [('',2),('m.detailSelectedVersion="gone"',0),('m.detailAudioChoice={}',0),('m.sourceId="silo:other"',0),('m.detailToken=5',0)]:
   result=self.flow('DetailAction(0)\n'+change+'\n'+self.answer(index)+'''print FormatJson({played:m.played,count:m.requests.Count(),prefs:m.preferences})''')
   self.assertIsNone(result['played']);self.assertEqual(1,result['count']);self.assertEqual('always',result['prefs']['subtitles'])
 def test_no_available_ticket_or_subtitles_off_uses_normal_play(self):
  for change in ['m.detailExperimentalAvailable=false','m.preferences.subtitles="off"']:
   result=self.flow(change+'\nDetailAction(0)\nprint FormatJson({played:m.played,labels:m.dialogLabels})')
   self.assertIsNone(result['labels']);self.assertIsNone(result['played']['ticket'])
