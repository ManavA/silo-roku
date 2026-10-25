"""Detail exposes complete synopsis pages without changing the selected title."""
import json
import tempfile
import unittest
from pathlib import Path
from tests import test_silo_ui_detail_experimental as experimental


class DetailSynopsisTests(unittest.TestCase):
    def test_synopsis_action_is_available_only_for_nonempty_summary(self):
        for summary, expected in [('Full synopsis', True), ('   ', False), ('', False)]:
            actual = self.flow('m.detailItem.summary=ParseJson("' + json.dumps(summary).replace('"', '""') + '")\nBrowseSocial(m.detailItem)\nprint FormatJson(m.dialogLabels)')
            self.assertEqual(expected, 'Synopsis' in actual)

    def flow(self, body):
        boundary = '''
function SynopsisSameNode(other as Object) as Boolean
 return m.tag=other.tag
end function
function SynopsisEventNode() as Object
 return m.node
end function
sub SynopsisObserve(field as String,handler as String)
end sub
sub BrowseDialog(title as String,labels as Object,handler as String)
 m.dialogLabels=labels
 m.browseDialog={tag:NumberOr(m.browseDialogSequence,0)+1,isSameNode:SynopsisSameNode,observeField:SynopsisObserve,buttonSelected:0,title:title}
 m.top={dialog:m.browseDialog}
 BrowseBindDialog(m.browseDialog,handler)
end sub
sub SetZone(zone as String)
 m.zone=zone
 m.focusRestored=true
end sub
'''
        with tempfile.TemporaryDirectory() as root:
            library = Path(root)/'library.brs'
            library.write_text((experimental.ROOT/'components/SiloUILibrary.brs').read_text().replace('sub BrowseDialog(', 'sub UnusedBrowseDialog(', 1))
            return experimental.ExperimentalDetail().flow(
                'm.detailItem.title="Title":m.detailItem.summary=String(400,"a")+"THE END"\n'+body,
                boundary_extra=boundary, files_extra=[experimental.ROOT/'components/SiloUIDialogs.brs',library])

    def test_reader_reaches_full_text_and_returns_to_selected_action(self):
        actual = self.flow('''DetailSynopsisOpen(m.detailItem)
 first={text:m.browseDialog.message,labels:m.dialogLabels,title:m.browseDialog.title}
 event={node:m.browseDialog,getRoSGNode:SynopsisEventNode}
 onDetailSynopsis(event)
 last={text:m.browseDialog.message,labels:m.dialogLabels,title:m.browseDialog.title}
 m.browseDialog.buttonSelected=1
 event={node:m.browseDialog,getRoSGNode:SynopsisEventNode}
 onDetailSynopsis(event)
 print FormatJson({first:first,last:last,closed:m.browseDialog.close,zone:m.zone,focus:m.pillGroups.detailButtons.index,requests:m.requests})''')
        self.assertEqual('a'*400, actual['first']['text'])
        self.assertEqual(['Next page','Close'], actual['first']['labels'])
        self.assertEqual('THE END', actual['last']['text'])
        self.assertEqual(['Previous page','Close'], actual['last']['labels'])
        self.assertTrue(actual['closed'])
        self.assertEqual(('detailButtons',1,[]), (actual['zone'],actual['focus'],actual['requests']))

    def test_pages_preserve_unicode_long_words_and_newlines_in_both_directions(self):
        actual = self.flow('''m.detailItem.summary=String(401,"x")+Chr(10)+"日本語 café 😀"+String(20,Chr(10))+"End"
 DetailSynopsisOpen(m.detailItem)
 original=m.detailItem.summary:collected="":pages=[]
 for attempt=0 to 20
     pages.Push(m.browseDialog.message.Replace(Chr(10),"|"))
     collected=collected+m.browseDialog.message
     nextIndex=-1
     for index=0 to m.dialogLabels.Count()-1
         if m.dialogLabels[index]="Next page" then nextIndex=index
     end for
     if nextIndex < 0 then exit for
     m.browseDialog.buttonSelected=nextIndex
     onDetailSynopsis({node:m.browseDialog,getRoSGNode:SynopsisEventNode})
 end for
 m.browseDialog.buttonSelected=0
 onDetailSynopsis({node:m.browseDialog,getRoSGNode:SynopsisEventNode})
 print FormatJson({original:original.Replace(Chr(10),"|"),collected:collected.Replace(Chr(10),"|"),pages:pages,previous:m.browseDialog.message.Replace(Chr(10),"|")})''')
        self.assertEqual(actual['original'], actual['collected'])
        self.assertTrue(all(0 < len(page) <= 400 and page.count('|') <= 6 for page in actual['pages']))
        self.assertEqual(actual['pages'][-2], actual['previous'])

    def test_back_restores_focus_when_native_dialog_is_already_removed(self):
        actual = self.flow('''DetailSynopsisOpen(m.detailItem)
 event={node:m.browseDialog,getRoSGNode:SynopsisEventNode}
 m.top.dialog=invalid
 onDetailSynopsisClosed(event)
 print FormatJson({reader:m.detailSynopsis,restored:m.focusRestored,index:m.pillGroups.detailButtons.index})''')
        self.assertIsNone(actual['reader'])
        self.assertTrue(actual['restored'])
        self.assertEqual(1, actual['index'])

    def test_stale_title_owner_or_dialog_cannot_page_or_restore_focus(self):
        for change in ['m.detailToken=5', 'm.detailItem={itemId:"other"}', 'm.profileId="other"', 'm.generation=3', 'm.view="home"', 'BrowseDialog("Other",["Close"],"otherHandler")']:
            actual = self.flow('''DetailSynopsisOpen(m.detailItem)
 old=m.browseDialog:event={node:old,getRoSGNode:SynopsisEventNode}
 '''+change+'''
 onDetailSynopsis(event)
 onDetailSynopsisClosed(event)
 print FormatJson({page:m.detailSynopsis.page,restored:m.focusRestored,requests:m.requests})''')
            self.assertEqual(0, actual['page'], change)
            self.assertIsNone(actual['restored'], change)
            self.assertEqual([], actual['requests'])

    def test_options_selection_opens_synopsis_without_mutations_or_focus_changes(self):
        actual = self.flow('''BrowseSocial(m.detailItem)
 m.browseDialog.buttonSelected=m.browseSynopsisIndex
 onBrowseSocial({node:m.browseDialog,getRoSGNode:SynopsisEventNode})
 print FormatJson({text:m.browseDialog.message,handler:m.browseDialogTicket.handler,index:m.pillGroups.detailButtons.index,requests:m.requests})''')
        self.assertEqual('a'*400, actual['text'])
        self.assertEqual('onDetailSynopsis', actual['handler'])
        self.assertEqual(1, actual['index'])
        self.assertEqual([], actual['requests'])

    def test_repeated_old_page_events_leave_new_page_open(self):
        actual = self.flow('''DetailSynopsisOpen(m.detailItem)
 old=m.browseDialog:event={node:old,getRoSGNode:SynopsisEventNode}
 onDetailSynopsis(event)
 onDetailSynopsis(event)
 onDetailSynopsisClosed(event)
 print FormatJson({page:m.detailSynopsis.page,text:m.browseDialog.message,closed:m.browseDialog.close,restored:m.focusRestored})''')
        self.assertEqual(1, actual['page'])
        self.assertEqual('THE END', actual['text'])
        self.assertIsNone(actual['closed'])
        self.assertIsNone(actual['restored'])

    def test_page_boundary_keeps_unicode_character_whole(self):
        actual = self.flow('''m.detailItem.summary=String(399,"x")+"😀End"
 DetailSynopsisOpen(m.detailItem)
 first=m.browseDialog.message
 onDetailSynopsis({node:m.browseDialog,getRoSGNode:SynopsisEventNode})
 print FormatJson({first:first,last:m.browseDialog.message})''')
        self.assertEqual('x'*399, actual['first'])
        self.assertEqual('😀End', actual['last'])
