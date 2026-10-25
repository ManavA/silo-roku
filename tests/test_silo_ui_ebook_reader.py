"""Hidden reader seam: captured API requests and native-label state."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]

class EbookReaderTests(unittest.TestCase):
 def flow(self,script):
  with tempfile.TemporaryDirectory() as d:
   reader=Path(d)/'reader.brs'
   reader.write_text((ROOT/'components/SiloUIEbook.brs').read_text().replace('CreateObject("roSGNode", "KeyboardDialog")','FixtureKeyboard()'))
   stub=Path(d)/'boundary.brs'
   stub.write_text('''
function FixtureKeyboard()
 m.keyboardId=NumberOr(m.keyboardId,0)+1
 return {id:m.keyboardId,IsSameNode:function(other)
 return m.id=other.id
 end function,observeField:sub(a,b)
 end sub,buttonSelected:0}
end function
function KeyboardEvent(dialog)
 return {dialog:dialog,getRoSGNode:function()
 return m.dialog
 end function}
end function
function HomeProgressScope() as String
 return m.scope
end function
sub Api(action,params,purpose,extra)
 m.calls.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
function SiloUIFont(size,bold)
 return {size:size}
end function
sub BrowsePagedChoices(title,choices,handler)
 m.chooser={title:title,choices:choices,handler:handler}
end sub
function BrowseChoiceIndex(event)
 return event.index
end function
sub ShowView(view)
 m.view=view
end sub
sub SetZone(zone)
 m.zone=zone
end sub
''')
   return json.loads(run_brightscript([reader,ROOT/'source/core/SiloUIFormat.brs',stub],'''
m.top={}:m.calls=[]:m.scope="silo/p/1":m.provider="silo":m.view="detail":m.zone="detailActions"
m.ebookToken=0:m.ebookTitle={}:m.ebookBody={}:m.ebookStatus={}
SiloUIEbookOpen("ebook:one","12","Book")
'''+script,root=Path(d)).splitlines()[-1])
 def test_capability_then_page_and_back_restore_origin(self):
  r=self.flow('''
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[0].extra)
page=m.calls[1]
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Readable text",revision:"rev",pageIndex:0,totalPages:2,previousPage:-1,nextPage:1},page.extra)
body=m.ebookBody.text
SiloUIEbookKey("back")
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Stale"},page.extra)
print FormatJson({calls:m.calls,body:body,view:m.view,zone:m.zone,cleared:m.ebookBody.text})
''')
  self.assertEqual([c['action'] for c in r['calls']],['ebook_capability','ebook_text_page'])
  self.assertEqual(r['calls'][1]['params'],{'contentId':'ebook:one','fileId':'12','pageIndex':0})
  self.assertEqual(r['body'],'Readable text')
  self.assertEqual((r['view'],r['zone'],r['cleared']),('detail','detailActions',''))
 def test_reverse_turn_rejects_old_response_and_error_retries_exact_page(self):
  r=self.flow('''
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[0].extra)
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"First",revision:"r",pageIndex:1,totalPages:3,previousPage:0,nextPage:2},m.calls[1].extra)
SiloUIEbookKey("right"):old=m.calls[2]
SiloUIEbookKey("left"):new=m.calls[3]
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Wrong"},old.extra)
retained=m.ebookBody.text
SiloUIEbookResult("ebook_reader_page",{ok:false},{},new.extra)
SiloUIEbookKey("OK")
retry=m.calls[4]
m.scope="changed"
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Wrong"},retry.extra)
print FormatJson({retained:retained,body:m.ebookBody.text,retry:retry,calls:m.calls.Count()})
''')
  self.assertEqual(r['retained'],'First')
  self.assertEqual(r['body'],'First')
  self.assertEqual(r['retry']['params']['pageIndex'],0)
  self.assertEqual(r['calls'],5)
 def test_all_chunk_text_remains_reachable_in_bounded_screens(self):
  r=self.flow('''
body=String(16384,"W")
screens=SiloUIEbookScreens(body)
joined="":maximum=0
for each screen in screens
 joined=joined+screen.Replace(Chr(10),"")
 if Len(screen)>maximum then maximum=Len(screen)
end for
print FormatJson({length:Len(joined),maximum:maximum,count:screens.Count()})
''')
  self.assertEqual(r['length'],16384)
  self.assertLessEqual(r['maximum'],429)
  self.assertGreater(r['count'],1)
 def test_revision_change_preserves_display_and_never_saves_progress(self):
  r=self.flow('''
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[0].extra)
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"First",revision:"r",pageIndex:0,totalPages:2,previousPage:-1,nextPage:1},m.calls[1].extra)
SiloUIEbookKey("right")
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Changed",revision:"different"},m.calls[2].extra)
print FormatJson({body:m.ebookBody.text,status:m.ebookStatus.text,calls:m.calls})
''')
  self.assertEqual(r['body'],'First')
  self.assertIn('Book changed',r['status'])
  self.assertNotIn('ebook_save_progress',[c['action'] for c in r['calls']])
 def test_shipping_scene_wires_reader_and_owns_keys_before_navigation(self):
  import xml.etree.ElementTree as ET
  scene=ET.parse(ROOT/'components/SiloUIScene.xml').getroot()
  self.assertIn('pkg:/components/SiloUIEbook.brs',[s.attrib['uri'] for s in scene.findall('script')])
  body=scene.find('.//Group[@id="ebook"]/Label[@id="ebookBody"]')
  self.assertIsNotNone(body)
  self.assertEqual(body.attrib.get('wrap'),'true')
  source=(ROOT/'components/SiloUIScene.brs').read_text()
  self.assertIn('SiloUIEbookInit()',source)
  self.assertIn('SiloUIEbookResult(p,result,data,entry.extra)',source)
  router=source[source.index('function onKeyEvent('):]
  self.assertLess(router.index('SiloUIEbookKey(key)'),router.index('if m.navigationMode = "left"'))
  self.assertIn('if m.view = "ebook" and view <> "ebook" then SiloUIEbookRelease()',source)
  self.assertIn('"Books"',source[source.index('m.navItems ='):source.index('m.navItems =')+110])

 def test_unicode_text_preserves_characters_across_local_screens(self):
  r=self.flow('''
body=""
for index=1 to 80
 body=body+"中文阅读 café naïve élève "
end for
screens=SiloUIEbookScreens(body)
joined=""
for each screen in screens
 joined=joined+screen.Replace(Chr(10),"")
end for
print FormatJson({body:body,joined:joined,count:screens.Count()})
''')
  self.assertEqual(r['joined'],'中文阅读 café naïve élève '*80)
  self.assertEqual(r['joined'],r['body'])
  self.assertGreater(r['count'],1)

 def test_reader_prefers_word_boundaries_and_limits_visible_lines(self):
  r=self.flow('''
body="Roku reader QA paragraph 1. The text should remain readable from the couch, with every sentence visible. "
screens=SiloUIEbookScreens(body)
first=screens[0]
print FormatJson({bad:Instr(1,first,"s"+Chr(10)+"hould")>0,joined:first.Replace(Chr(10),""),breaks:Len(first)-Len(first.Replace(Chr(10),""))})
''')
  self.assertEqual(r['joined'],'Roku reader QA paragraph 1. The text should remain readable from the couch, with every sentence visible. ')
  self.assertFalse(r['bad'])
  self.assertLessEqual(r['breaks'],9)

 def test_options_resize_retained_chunk_and_keep_reading_position(self):
  r=self.flow('''
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[0].extra)
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:String(3000,"W"),revision:"r",pageIndex:0,totalPages:1,previousPage:-1,nextPage:-1},m.calls[1].extra)
SiloUIEbookKey("right")
anchor=m.ebookOffsets[m.ebookScreen]
SiloUIEbookKey("options")
choices=m.chooser.choices
onSiloUIEbookOption({index:0})
onSiloUIEbookSize({index:2})
print FormatJson({choices:choices,size:m.ebookBody.font.size,screen:m.ebookScreen,calls:m.calls.Count(),offset:m.ebookOffsets[m.ebookScreen],anchor:anchor,bodyLength:Len(m.ebookBody.text)})
''')
  self.assertEqual(r['choices'],['Text size','Go to page'])
  self.assertEqual(r['size'],32)
  self.assertGreater(r['screen'],0)
  self.assertEqual(r['calls'],2)
  self.assertEqual(r['offset'],r['anchor'])
  self.assertGreater(r['bodyLength'],0)

 def test_resize_during_loading_and_error_preserves_retry_and_original_newline_anchor(self):
  r=self.flow('''
SiloUIEbookKey("options")
onSiloUIEbookOption({index:0})
onSiloUIEbookSize({index:0})
loading=m.ebookStatus.text
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[0].extra)
body=""
for n=1 to 100
 body=body+"中文 café paragraph"+Chr(10)
end for
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:body,revision:"r",pageIndex:0,totalPages:2,previousPage:-1,nextPage:1},m.calls[1].extra)
SiloUIEbookKey("right")
anchor=m.ebookOffsets[m.ebookScreen]
SiloUIEbookKey("options")
onSiloUIEbookOption({index:0})
onSiloUIEbookSize({index:2})
preserved=m.ebookOffsets[m.ebookScreen]=anchor
first=Left(m.ebookBody.text,1)
expected=Mid(body,anchor+1,1)
for n=1 to 200
 SiloUIEbookKey("right")
 if m.calls.Count()>2 then exit for
end for
pending=m.calls[2]
SiloUIEbookResult("ebook_reader_page",{ok:false},{},pending.extra)
status=m.ebookStatus.text
SiloUIEbookKey("options")
onSiloUIEbookOption({index:0})
onSiloUIEbookSize({index:1})
errorRetained=m.ebookStatus.text=status
SiloUIEbookKey("OK")
print FormatJson({loading:loading,preserved:preserved,first:first,expected:expected,errorRetained:errorRetained,retry:m.calls[3].params.pageIndex,calls:m.calls.Count()})
''')
  self.assertIn('Loading',r['loading'])
  self.assertTrue(r['preserved'])
  self.assertEqual(r['first'],r['expected'])
  self.assertTrue(r['errorRetained'])
  self.assertEqual(r['retry'],1)
  self.assertEqual(r['calls'],4)

 def test_old_size_choice_cannot_mutate_reopened_reader_or_another_profile(self):
  r=self.flow('''
SiloUIEbookKey("options")
SiloUIEbookKey("back")
SiloUIEbookOpen("ebook:two","13","Other")
onSiloUIEbookSize({index:2})
reopened=m.ebookBody.font.size
SiloUIEbookKey("options")
m.scope="silo/p/2"
onSiloUIEbookSize({index:0})
print FormatJson({reopened:reopened,changed:m.ebookBody.font.size,calls:m.calls.Count()})
''')
  self.assertEqual(r['reopened'],28)
  self.assertEqual(r['changed'],28)
  self.assertEqual(r['calls'],2)

 def test_go_to_page_native_prompt_and_valid_boundaries(self):
  r=self.flow('''
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[0].extra)
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Middle",revision:"r",pageIndex:1,totalPages:3,previousPage:0,nextPage:2},m.calls[1].extra)
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
dialog=m.top.dialog:initial=dialog.text:title=dialog.title
 dialog.text="3":onSiloUIEbookPage(KeyboardEvent(dialog))
last=m.calls[2]
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
dialog=m.top.dialog:dialog.text="1":onSiloUIEbookPage(KeyboardEvent(dialog))
print FormatJson({initial:initial,title:title,last:last,first:m.calls[3],body:m.ebookBody.text})
''')
  self.assertEqual(r['initial'],'2')
  self.assertIn('1–3',r['title'])
  self.assertEqual(r['last']['params']['pageIndex'],2)
  self.assertEqual(r['first']['params']['pageIndex'],0)
  self.assertEqual(r['first']['extra']['screenIndex'],0)
  self.assertEqual(r['body'],'Middle')

 def test_invalid_cancel_same_page_and_pending_response_preserve_display(self):
  r=self.flow('''
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
beforePage=m.top.dialog=invalid
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[0].extra)
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Current",revision:"r",pageIndex:1,totalPages:3,previousPage:0,nextPage:2},m.calls[1].extra)
SiloUIEbookKey("right"):pending=m.calls[2]
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
dialog=m.top.dialog:firstDialog=dialog
for each bad in ["0","4","2.5","abc","","-1","1e0"]
 dialog.text=bad:onSiloUIEbookPage(KeyboardEvent(dialog)):dialog=m.top.dialog
end for
invalidCalls=m.calls.Count():validation=dialog.title:replaced=not dialog.IsSameNode(firstDialog)
 dialog.buttonSelected=1:onSiloUIEbookPage(KeyboardEvent(dialog))
cancelKeptPending=m.ebookPending.token=pending.extra.token
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
dialog=m.top.dialog:dialog.text="2":onSiloUIEbookPage(KeyboardEvent(dialog))
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Pending result",revision:"r",pageIndex:2,totalPages:3,previousPage:1,nextPage:-1},pending.extra)
print FormatJson({beforePage:beforePage,replaced:replaced,cancelKeptPending:cancelKeptPending,invalidCalls:invalidCalls,validation:validation,calls:m.calls,body:m.ebookBody.text})
''')
  self.assertTrue(r['beforePage'])
  self.assertTrue(r['replaced'])
  self.assertTrue(r['cancelKeptPending'])
  self.assertEqual(r['invalidCalls'],3)
  self.assertIn('whole page number',r['validation'])
  self.assertEqual(len(r['calls']),3)
  self.assertEqual(r['body'],'Current')
  self.assertNotIn('ebook_save_progress',[c['action'] for c in r['calls']])

 def test_closed_replaced_reopened_and_profile_dialogs_cannot_jump(self):
  r=self.flow('''
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[0].extra)
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Current",revision:"r",pageIndex:0,totalPages:3,previousPage:-1,nextPage:1},m.calls[1].extra)
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
closed=m.top.dialog:onSiloUIEbookPageClosed(KeyboardEvent(closed))
closed.text="3":onSiloUIEbookPage(KeyboardEvent(closed))
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
old=m.top.dialog
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
current=m.top.dialog:old.text="3":onSiloUIEbookPage(KeyboardEvent(old))
onSiloUIEbookPageClosed(KeyboardEvent(old))
current.text="2":onSiloUIEbookPage(KeyboardEvent(current))
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
old=m.top.dialog:SiloUIEbookKey("back")
SiloUIEbookOpen("ebook:two","13","Other")
SiloUIEbookResult("ebook_reader_capability",{ok:true},{textPages:true},m.calls[3].extra)
SiloUIEbookResult("ebook_reader_page",{ok:true},{text:"Other",revision:"r2",pageIndex:0,totalPages:2,previousPage:-1,nextPage:1},m.calls[4].extra)
SiloUIEbookKey("options"):onSiloUIEbookOption({index:1})
current=m.top.dialog:old.text="2":onSiloUIEbookPage(KeyboardEvent(old))
m.scope="silo/p/2":current.text="2":onSiloUIEbookPage(KeyboardEvent(current))
print FormatJson({calls:m.calls,body:m.ebookBody.text})
''')
  self.assertEqual(len(r['calls']),5)
  self.assertEqual(r['calls'][2]['params']['pageIndex'],1)
  self.assertEqual(r['body'],'Other')
