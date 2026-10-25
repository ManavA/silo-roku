"""Ebook browse at scene handlers and captured API requests."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class SiloUIEbookBrowseTests(unittest.TestCase):
 def flow(self, script, router=False):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'ebook.brs'
   p.write_text((ROOT/'components/SiloUIEbookBrowse.brs').read_text().replace('CreateObject("roSGNode","ContentNode")','BrowseNode()'))
   boundary=Path(d)/'boundary.brs'
   boundary.write_text('''
function SiloUIFont(size,bold) as Object
 return {}
end function
function HomeProgressScope() as String
 return m.scope
end function
sub Api(action,params,purpose,extra)
 m.calls.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
sub ShowView(view)
 m.view=view
end sub
sub SetZone(zone)
 m.zone=zone
end sub
function BrowseNode() as Object
 return {children:[],appendChild:sub(node)
 m.children.Push(node)
 end sub,getChildCount:function()
 return m.children.Count()
 end function,getChild:function(index)
 return m.children[index]
 end function}
end function
sub PaintPills(name,focused)
 m.painted={name:name,focused:focused}
end sub
sub BrowsePagedChoices(title,labels,handler)
 m.choices=labels
end sub
function ItemNode(item) as Object
 return {item:item}
end function
''')
   files=[p,ROOT/'components/SiloUIEbook.brs',ROOT/'components/SiloUIOnboarding.brs',ROOT/'source/core/SiloUIFormat.brs',boundary]
   if router:
    import re
    scene=(ROOT/'components/SiloUIScene.brs').read_text()
    navigation=(ROOT/'components/SiloUINavigation.brs').read_text()
    # Run the shipping key router/navigation; replace only drawer painting.
    navigation=re.sub(r'sub SiloUINavigationSync\(\).*?end sub',
                      'sub SiloUINavigationSync()\nend sub',navigation,flags=re.S)
    route=Path(d)/'router.brs'
    route.write_text(scene[scene.index('function onKeyEvent('):scene.index("' Temporary native QA trace:")]+navigation+\
                     '\nfunction PlayerFailureBack() as Boolean\n return false\nend function\nsub SiloUIAudioBrowse()\n m.view="audioBrowse"\nend sub\nsub SiloUIFocusTrace(stage,key)\nend sub\nfunction PopView() as Boolean\n return false\nend function\n')
    files.extend([route,ROOT/'source/core/SiloUINavigationPolicy.brs'])
   setup='''
m.calls=[]:m.provider="silo":m.scope="source/profile/1":m.view="home":m.ebookBrowseToken=0
m.pillGroups={ebookBrowseButtons:{index:0}}
m.ebookToken=0:m.ebookTitle={}:m.ebookBody={}:m.ebookStatus={}
m.ebookGrid={itemFocused:0}:m.ebookBrowseStatus={}:m.ebookBrowseTitle={}:m.ebookBrowseLibrary=""
'''
   return json.loads(run_brightscript(files,setup+script,root=Path(d)).splitlines()[-1])
 def test_capability_gate_precedes_libraries(self):
  r=self.flow('''SiloUIEbookBrowse()
first=m.calls[0].action
SiloUIEbookBrowseResult("ebook_browse_capability",{ok:true},{textPages:true},m.ebookBrowseToken)
print FormatJson({first:first,last:m.calls[1].action,view:m.view})''')
  self.assertEqual(r,{'first':'ebook_capability','last':'ebook_libraries','view':'ebookBrowse'})

 def library_setup(self):
  return '''SiloUIEbookBrowse()
SiloUIEbookBrowseResult("ebook_browse_capability",{ok:true},{textPages:true},m.ebookBrowseToken)
SiloUIEbookBrowseResult("ebook_browse_libraries",{ok:true},{entries:[{id:"books",title:"Books"}]},m.ebookBrowseToken)
'''
 def test_explicit_library_choice_and_request_fencing(self):
  r=self.flow('''SiloUIEbookBrowse()
SiloUIEbookBrowseResult("ebook_browse_capability",{ok:true},{textPages:true},m.ebookBrowseToken)
SiloUIEbookBrowseResult("ebook_browse_libraries",{ok:true},{entries:[{id:"one",title:"One"},{id:"two",title:"Two"}]},m.ebookBrowseToken)
choices=m.choices
SiloUIEbookBrowseLibrary(0):old=m.ebookBrowseToken
SiloUIEbookBrowseLibrary(1)
SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[{id:"old",item:{itemId:"old"}}],nextCursor:""},old)
print FormatJson({choices:choices,last:m.calls[3].params,count:m.ebookGrid.content.getChildCount()})''')
  self.assertEqual(r,{'choices':['One','Two'],'last':{'libraryId':'two'},'count':0})
 def test_page_retry_is_serial_and_old_page_cannot_append(self):
  r=self.flow(self.library_setup()+'''old=m.ebookBrowseToken
SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:false},{},old)
m.pillGroups.ebookBrowseButtons.index=1:SiloUIEbookBrowseKey("OK")
retry=m.ebookBrowseToken
SiloUIEbookBrowsePage()
SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[{id:"late",item:{itemId:"late"}}],nextCursor:""},old)
SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[{id:"good",item:{itemId:"good"}}],nextCursor:"next"},retry)
onSiloUIEbookGridFocus():onSiloUIEbookGridFocus()
SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[],nextCursor:"next"},m.ebookBrowseToken)
print FormatJson({calls:m.calls.Count(),count:m.ebookGrid.content.getChildCount(),more:m.ebookBrowseMore})''')
  self.assertEqual(r,{'calls':5,'count':1,'more':False})
 def test_five_page_bound_and_profile_scope(self):
  r=self.flow(self.library_setup()+'''for i=1 to 5
 SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[{id:i.ToStr(),item:{itemId:i.ToStr()}}],nextCursor:i.ToStr()},m.ebookBrowseToken)
 if i<5 then SiloUIEbookBrowsePage()
end for
SiloUIEbookBrowsePage()
bounded=m.calls.Count()
m.scope="different/profile":onSiloUIEbookGridSelect():SiloUIEbookBrowseLibrary(0)
SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[{id:"bad",item:{itemId:"bad"}}],nextCursor:""},m.ebookBrowseToken)
print FormatJson({bounded:bounded,calls:m.calls.Count(),count:m.ebookGrid.content.getChildCount(),more:m.ebookBrowseMore})''')
  self.assertEqual(r,{'bounded':7,'calls':7,'count':5,'more':False})
 def test_back_retires_scope_and_capability_retry_preserves_origin(self):
  r=self.flow('''m.zone="heroButtons":SiloUIEbookBrowse()
SiloUIEbookBrowseResult("ebook_browse_capability",{ok:false},{},m.ebookBrowseToken)
SiloUIEbookBrowseKey("OK")
last=m.calls[1].action
SiloUIEbookBrowseKey("back")
SiloUIEbookBrowseRetire()
SiloUIEbookBrowseResult("ebook_browse_capability",{ok:true},{textPages:true},m.ebookBrowseToken-1)
print FormatJson({last:last,view:m.view,zone:m.zone,calls:m.calls.Count(),content:m.ebookGrid.content})''')
  self.assertEqual(r,{'last':'ebook_capability','view':'home','zone':'heroButtons','calls':2,'content':None})

 def test_selection_fetches_epub_detail_then_reader_back_focuses_card(self):
  r=self.flow(self.library_setup()+'''SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[{id:"ebook:a",item:{itemId:"ebook:a"}},{id:"ebook:b",item:{itemId:"ebook:b"}}],nextCursor:""},m.ebookBrowseToken)
m.ebookGrid.itemSelected=1:m.zone="ebookBrowseGrid"
onSiloUIEbookGridSelect():detail=m.calls[3]
SiloUIEbookBrowseResult("ebook_browse_detail",{ok:true},{contentId:"ebook:b",fileId:"12",title:"Book B"},detail.extra)
opened=m.view:reader=m.calls[4]
SiloUIEbookKey("back")
print FormatJson({detail:detail,reader:reader,opened:opened,view:m.view,zone:m.zone,index:m.ebookGrid.jumpToItem,count:m.ebookGrid.content.getChildCount()})''')
  self.assertEqual(r['detail']['action'],'ebook_detail')
  self.assertEqual(r['detail']['params'],{'contentId':'ebook:b'})
  self.assertEqual(r['reader']['action'],'ebook_capability')
  self.assertEqual((r['opened'],r['view'],r['zone'],r['index'],r['count']),('ebook','ebookBrowse','ebookBrowseGrid',1,2))

 def test_unavailable_capability_stays_closed_and_retry_rechecks(self):
  r=self.flow('''SiloUIEbookBrowse()
SiloUIEbookBrowseResult("ebook_browse_capability",{ok:true},{textPages:false},m.ebookBrowseToken)
status=m.ebookBrowseStatus.text
SiloUIEbookBrowseKey("OK")
print FormatJson({status:status,calls:m.calls.Count(),action:m.calls[1].action})''')
  self.assertIn('unavailable',r['status'])
  self.assertEqual((r['calls'],r['action']),(2,'ebook_capability'))

 def test_detail_failure_retry_keeps_selected_identity_and_ignores_old_reply(self):
  r=self.flow(self.library_setup()+'''SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[{id:"ebook:a",item:{itemId:"ebook:a"}}],nextCursor:""},m.ebookBrowseToken)
m.ebookGrid.itemSelected=0:onSiloUIEbookGridSelect():old=m.ebookBrowseToken
SiloUIEbookBrowseResult("ebook_browse_detail",{ok:false},{},old)
m.zone="ebookBrowseButtons":m.pillGroups.ebookBrowseButtons.index=1:SiloUIEbookBrowseKey("OK")
SiloUIEbookBrowseResult("ebook_browse_detail",{ok:true},{contentId:"ebook:a",fileId:"12",title:"A"},old)
print FormatJson({view:m.view,action:m.calls[4].action,params:m.calls[4].params,calls:m.calls.Count()})''')
  self.assertEqual(r,{'view':'ebookBrowse','action':'ebook_detail','params':{'contentId':'ebook:a'},'calls':5})

 def test_shipping_scene_retains_grid_only_for_reader_and_exposes_books_entry(self):
  import xml.etree.ElementTree as ET
  scene=ET.parse(ROOT/'components/SiloUIScene.xml').getroot()
  self.assertIn('pkg:/components/SiloUIEbookBrowse.brs',[s.attrib['uri'] for s in scene.findall('script')])
  self.assertIsNotNone(scene.find('.//Group[@id="ebookBrowse"]/MarkupGrid[@id="ebookBrowseGrid"]'))
  status=scene.find('.//Group[@id="ebookBrowse"]/Label[@id="ebookBrowseStatus"]')
  self.assertEqual(status.attrib.get('wrap'),'true')
  self.assertGreaterEqual(int(status.attrib.get('height','0')),50)
  source=(ROOT/'components/SiloUIScene.brs').read_text()
  self.assertIn('SiloUIEbookBrowseInit()',source)
  self.assertIn('SiloUIEbookBrowseResult(p,result,data,entry.extra)',source)
  self.assertIn('if m.view = "ebookBrowse" and view <> "ebookBrowse" and view <> "ebook" then SiloUIEbookBrowseRetire()',source)
  router=source[source.index('function onKeyEvent('):]
  self.assertLess(router.index('m.view = "ebookBrowse" and key = "back"'),router.index('if m.navigationMode = "left"'))
  self.assertIn('"Books"',source[source.index('m.navItems ='):source.index('m.navItems =')+110])

 def test_drawer_recognizes_ebook_content_zones(self):
  with tempfile.TemporaryDirectory() as d:
   output=run_brightscript([ROOT/'source/core/SiloUINavigationPolicy.brs'],'''print FormatJson({grid:SiloUINavigationContentZone("ebookBrowse","ebookBrowseGrid"),buttons:SiloUINavigationContentZone("ebookBrowse","ebookBrowseButtons"),other:SiloUINavigationContentZone("home","ebookBrowseGrid")})''',root=Path(d))
   self.assertEqual(json.loads(output),{'grid':True,'buttons':True,'other':False})

 def test_router_back_dismisses_drawer_before_closing_browser(self):
  r=self.flow(self.library_setup()+'''m.navigationMode="left":m.drawerOpen=true:m.zone="drawer"
m.navigationReturn={view:"ebookBrowse",zone:"ebookBrowseButtons",provider:m.provider,sourceId:"s",profileId:"p",generation:1}
m.sourceId="s":m.profileId="p":m.generation=1
onKeyEvent("back",true)
print FormatJson({view:m.view,zone:m.zone,drawer:m.drawerOpen})''',router=True)
  self.assertEqual(r,{'view':'ebookBrowse','zone':'ebookBrowseButtons','drawer':False})

 def test_pending_detail_opened_from_drawer_returns_to_selected_grid(self):
  r=self.flow(self.library_setup()+'''SiloUIEbookBrowseResult("ebook_browse_catalog",{ok:true},{entries:[{id:"ebook:a",item:{itemId:"ebook:a"}}],nextCursor:""},m.ebookBrowseToken)
m.ebookGrid.itemSelected=0:onSiloUIEbookGridSelect()
m.zone="drawer"
SiloUIEbookBrowseResult("ebook_browse_detail",{ok:true},{contentId:"ebook:a",fileId:"12",title:"Book"},m.ebookBrowseToken)
SiloUIEbookKey("back")
print FormatJson({view:m.view,zone:m.zone,index:m.ebookGrid.jumpToItem})''')
  self.assertEqual(r,{'view':'ebookBrowse','zone':'ebookBrowseGrid','index':0})

 def test_profile_menu_books_opens_browser_and_back_returns_home(self):
  r=self.flow('''m.view="onboarding":m.zone="obButtons":m.history=[]
ObChoose({action:"profile_books"})
opened={view:m.view,zone:m.zone,action:m.calls[0].action}
SiloUIEbookBrowseKey("back")
print FormatJson({opened:opened,view:m.view,zone:m.zone})''')
  self.assertEqual(r,{'opened':{'view':'ebookBrowse','zone':'ebookBrowseButtons','action':'ebook_capability'},'view':'home','zone':'nav'})

 def test_profile_menu_audiobooks_dispatches_existing_browser(self):
  r=self.flow('''m.view="onboarding":m.zone="obButtons":m.history=[]
ObChoose({action:"profile_audio"})
print FormatJson({view:m.view,history:m.history})''',router=True)
  self.assertEqual(r,{'view':'audioBrowse','history':[]})

 def test_books_and_audiobooks_remain_selectable_in_left_navigation(self):
  import re
  source=(ROOT/'components/SiloUIScene.brs').read_text()
  labels=re.search(r'm.navItems = (\[.*?\])',source).group(1)
  for mode in ['left']:
   with self.subTest(mode=mode):
    r=self.flow('m.navItems='+labels+':m.pillGroups.nav={index:5,pills:[]}\n'+
     'm.navigationMode="'+mode+'":m.zone="nav"\n'+
     ('m.drawerOpen=true:m.drawerIndex=5:m.zone="drawer"\n' if mode=='left' else '')+'''onKeyEvent("OK",true)
books={view:m.view,zone:m.zone,action:m.calls[0].action}
onKeyEvent("back",true)
returned={view:m.view,zone:m.zone}
m.zone="nav":m.pillGroups.nav.index=4
'''+('m.drawerOpen=true:m.drawerIndex=4:m.zone="drawer"\n' if mode=='left' else '')+'''onKeyEvent("OK",true)
print FormatJson({books:books,returned:returned,audio:m.view})''',router=True)
    self.assertEqual(r,{'books':{'view':'ebookBrowse','zone':'ebookBrowseButtons','action':'ebook_capability'},'returned':{'view':'home','zone':'nav'},'audio':'audioBrowse'})

 def test_older_server_explains_missing_reader_and_can_retry_or_go_back(self):
  for result,data in [({'ok':False},{}),({'ok':True},{'textPages':False})]:
   with self.subTest(result=result):
    r=self.flow('m.zone="nav":SiloUIEbookBrowse()\nSiloUIEbookBrowseResult("ebook_browse_capability",'+('{ok:false}' if not result['ok'] else '{ok:true}')+','+('{}' if not data else '{textPages:false}')+''',m.ebookBrowseToken)
status=m.ebookBrowseStatus.text
SiloUIEbookBrowseKey("down")
zone=m.zone
SiloUIEbookBrowseKey("OK")
SiloUIEbookBrowseKey("back")
print FormatJson({status:status,zone:zone,view:m.view,backZone:m.zone,calls:m.calls.Count(),retry:m.calls[1].action})''')
    self.assertIn('Silo server',r['status'])
    self.assertIn('unavailable',r['status'])
    self.assertEqual((r['zone'],r['view'],r['backZone'],r['calls'],r['retry']),('ebookBrowseButtons','home','nav',2,'ebook_capability'))

 def test_books_back_from_audiobooks_returns_to_live_home_owner(self):
  r=self.flow('''m.navItems=["Home","Search","Movies","Shows","Audiobooks","Books","Settings"]
m.pillGroups.nav={index:5,pills:[]}:m.navigationMode="top"
m.view="audioBrowse":m.zone="nav"
NavSelect(5)
SiloUIEbookBrowseKey("back")
print FormatJson({view:m.view,zone:m.zone})''',router=True)
  self.assertEqual(r,{'view':'home','zone':'nav'})
