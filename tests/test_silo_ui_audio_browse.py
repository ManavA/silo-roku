"""Dedicated audiobook browse at scene handlers and captured API requests."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class SiloUIAudioBrowseTests(unittest.TestCase):
 def flow(self, script, router=False):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'audio.brs'
   p.write_text((ROOT/'components/SiloUIAudio.brs').read_text().replace('CreateObject("roSGNode","ContentNode")','BrowseNode()'))
   boundary=Path(d)/'boundary.brs'
   boundary.write_text('''
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
   files=[p,ROOT/'source/core/SiloUIFormat.brs',boundary]
   if router:
    import re
    scene=(ROOT/'components/SiloUIScene.brs').read_text()
    navigation=(ROOT/'components/SiloUINavigation.brs').read_text()
    # Run the shipping key router/navigation; replace only drawer painting.
    navigation=re.sub(r'sub SiloUINavigationSync\(\).*?end sub',
                      'sub SiloUINavigationSync()\nend sub',navigation,flags=re.S)
    route=Path(d)/'router.brs'
    route.write_text(scene[scene.index('function onKeyEvent('):scene.index('sub NavSelect(')]+navigation+\
                     '\nsub SiloUIFocusTrace(stage,key)\nend sub\nfunction PlayerFailureBack() as Boolean\n return false\nend function\nfunction PopView() as Boolean\n return false\nend function\n')
    files.extend([route,ROOT/'source/core/SiloUINavigationPolicy.brs'])
   setup='''
m.calls=[]:m.provider="silo":m.scope="source/profile/1":m.view="home":m.audioBrowseToken=0
m.pillGroups={audioBrowseButtons:{index:0}}
m.audioGrid={itemFocused:0}:m.audioBrowseStatus={}:m.audioBrowseTitle={}:m.audioBrowseLibrary=""
'''
   return json.loads(run_brightscript(files,setup+script,root=Path(d)).splitlines()[-1])
 def test_direct_browse_opens_grid_and_fetches_permitted_libraries(self):
  r=self.flow('''SiloUIAudioBrowse()
print FormatJson({view:m.view,zone:m.zone,status:m.audioBrowseStatus.text,calls:m.calls})''')
  self.assertEqual(r['view'],'audioBrowse')
  self.assertEqual(r['zone'],'audioBrowseButtons')
  self.assertEqual(r['calls'][0]['action'],'audio_libraries')
  self.assertEqual(r['status'],'Loading audiobook libraries…')
 def test_library_result_auto_loads_first_library_and_catalog_ignores_stale_visits(self):
  r=self.flow('''
SiloUIAudioBrowse()
SiloUIAudioResult("audio_libraries",{ok:true},{entries:[{id:"books",title:"Books"}]},m.audioBrowseToken)
request=m.calls[1]
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"book",title:"A book",item:{itemId:"book",title:"A book"}}],nextCursor:"next"},m.audioBrowseToken)
count=m.audioGrid.content.getChildCount()
m.scope="other/profile/2"
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"stale",title:"Stale",item:{itemId:"stale"}}],nextCursor:""},m.audioBrowseToken)
print FormatJson({request:request,count:count,finalCount:m.audioGrid.content.getChildCount(),more:m.audioBrowseMore})
''')
  self.assertEqual(r['request']['params'],{'libraryId':'books'})
  self.assertEqual(r['request']['action'],'audio_catalog')
  self.assertEqual(r['count'],1)
  self.assertEqual(r['finalCount'],1)
  self.assertTrue(r['more'])
 def test_paging_is_serial_and_repeated_cursor_stops_and_error_can_retry(self):
  r=self.flow('''
SiloUIAudioBrowse()
SiloUIAudioResult("audio_libraries",{ok:true},{entries:[{id:"books",title:"Books"}]},m.audioBrowseToken)
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[],nextCursor:"next"},m.audioBrowseToken)
onSiloUIAudioGridFocus():onSiloUIAudioGridFocus()
serial=m.calls.Count()=3
SiloUIAudioResult("audio_catalog",{ok:false},{},m.audioBrowseToken)
failed=m.audioBrowseStatus.text
SiloUIAudioBrowsePage()
retried=m.calls.Count()=4
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[],nextCursor:"next"},m.audioBrowseToken)
print FormatJson({serial:serial,failed:failed,retried:retried,more:m.audioBrowseMore})
''')
  self.assertTrue(r['serial'])
  self.assertIn('Retry',r['failed'])
  self.assertTrue(r['retried'])
  self.assertFalse(r['more'])

 def test_multiple_libraries_require_explicit_selection(self):
  r=self.flow('''SiloUIAudioBrowse()
SiloUIAudioResult("audio_libraries",{ok:true},{entries:[{id:"one",title:"One"},{id:"two",title:"Two"}]},m.audioBrowseToken)
print FormatJson({choices:m.choices,calls:m.calls.Count(),status:m.audioBrowseStatus.text})''')
  self.assertEqual(r['choices'],['One','Two'])
  self.assertEqual(r['calls'],1)
  self.assertIn('Choose',r['status'])
 def test_exit_retires_inflight_results_and_drops_signed_card_content(self):
  r=self.flow('''SiloUIAudioBrowse()
old=m.audioBrowseToken
SiloUIAudioBrowseRetire()
SiloUIAudioResult("audio_libraries",{ok:true},{entries:[{id:"late",title:"Late"}]},old)
print FormatJson({content:m.audioGrid.content,loading:m.audioBrowseLoading,calls:m.calls.Count(),token:m.audioBrowseToken>old})''')
  self.assertIsNone(r['content'])
  self.assertFalse(r['loading'])
  self.assertEqual(r['calls'],1)
  self.assertTrue(r['token'])
 def test_library_switch_replaces_inflight_catalog_and_stale_page_cannot_fill_grid(self):
  r=self.flow('''SiloUIAudioBrowse()
m.audioBrowseLibraries=[{id:"one",title:"One"},{id:"two",title:"Two"}]
m.audioBrowseLoading=false
SiloUIAudioBrowseLibrary(0)
old=m.audioBrowseToken
SiloUIAudioBrowseLibrary(1)
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"old",item:{itemId:"old"}}],nextCursor:""},old)
print FormatJson({last:m.calls[2].params.libraryId,count:m.audioGrid.content.getChildCount(),loading:m.audioBrowseLoading})''')
  self.assertEqual(r,{'last':'two','count':0,'loading':True})
 def test_worker_projects_all_returned_cards_with_transient_artwork(self):
  with tempfile.TemporaryDirectory() as d:
   boundary=Path(d)/'boundary.brs'
   boundary.write_text('''
function SessionRevision(provider) as Integer
 return 1
end function
function HttpRequest(request,timeout) as Object
 return {ok:true,body:FormatJson(m.response)}
end function
''')
   out=run_brightscript([ROOT/'source/core/SiloUIAudioPolicy.brs',ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/adapters/SiloAudioAdapter.brs',ROOT/'components/ApiTask.brs',ROOT/'components/TaskSiloAudio.brs',boundary],'''
m.response={items:[],page:{has_more:true,next_cursor:"next"}}
for i=0 to 39
 m.response.items.Push({content_id:"audiobook:"+i.ToStr(),type:"audiobook",title:"Book "+i.ToStr(),poster_url:"https://fixture.example/poster?signature=transient"})
end for
session={baseUrl:"https://fixture.example",accessToken:"fixture",profileId:"p",sourceId:"silo:test"}
r=TaskAudioAction(session,"audio_catalog",{libraryId:"books"},{sourceId:"silo:test",profileId:"p"},1)
print FormatJson({count:r.data.entries.Count(),art:r.data.entries[0].item.art,cursor:r.data.nextCursor})
''',root=Path(d))
  result=json.loads(out)
  self.assertEqual(result['count'],40)
  self.assertEqual(result['art'],{'poster':'https://fixture.example/poster?signature=transient'})
  self.assertEqual(result['cursor'],'next')
 def test_back_from_player_returns_to_selected_audiobook_library(self):
  r=self.flow('''m.view="audio":m.audioReturnBrowse=true:m.audioBrowseScope=m.scope
m.audioBrowseLibraries=[{id:"one",title:"One"},{id:"two",title:"Two"}]:m.audioBrowseLibraryIndex=1
m.audioBrowseLoading=false
handled=SiloUIAudioKey("back")
print FormatJson({handled:handled,view:m.view,zone:m.zone,request:m.calls[0].params})''')
  self.assertEqual(r,{'handled':True,'view':'audioBrowse','zone':'audioBrowseButtons','request':{'libraryId':'two'}})

 def test_back_restores_book_after_bounded_catalog_reload(self):
  r=self.flow('''m.view="audio":m.audioReturnBrowse=true:m.audioBrowseScope=m.scope
m.audioBrowseLibraries=[{id:"books",title:"Books"}]:m.audioBrowseLibraryIndex=0
m.audioBrowseReturn={scope:m.scope,libraryId:"books",itemId:"wanted",index:2,pages:2}
SiloUIAudioKey("back")
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"a",item:{itemId:"a"}}],nextCursor:"next"},m.audioBrowseToken)
waiting=m.zone:requests=m.calls.Count()
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"wanted",item:{itemId:"wanted"}}],nextCursor:"last"},m.audioBrowseToken)
print FormatJson({waiting:waiting,requests:requests,zone:m.zone,index:m.audioGrid.jumpToItem,pending:m.audioBrowseRestore})''')
  self.assertEqual(r,{'waiting':'audioBrowseButtons','requests':2,'zone':'audioBrowseGrid','index':1,'pending':None})

 def test_missing_book_falls_back_to_clamped_card_without_scanning_new_pages(self):
  r=self.flow('''m.view="audio":m.audioReturnBrowse=true:m.audioBrowseScope=m.scope
m.audioBrowseLibraries=[{id:"books",title:"Books"}]:m.audioBrowseLibraryIndex=0
m.audioBrowseReturn={scope:m.scope,libraryId:"books",itemId:"removed",index:8,pages:1}
SiloUIAudioKey("back")
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"a",item:{itemId:"a"}},{id:"b",item:{itemId:"b"}}],nextCursor:"next"},m.audioBrowseToken)
print FormatJson({zone:m.zone,index:m.audioGrid.jumpToItem,calls:m.calls.Count()})''')
  self.assertEqual(r,{'zone':'audioBrowseGrid','index':1,'calls':1})

 def test_return_scan_stops_at_five_pages_and_rejects_other_profile(self):
  r=self.flow('''m.view="audio":m.audioReturnBrowse=true:m.audioBrowseScope=m.scope
m.audioBrowseLibraries=[{id:"books",title:"Books"}]:m.audioBrowseLibraryIndex=0
m.audioBrowseReturn={scope:m.scope,libraryId:"books",itemId:"removed",index:0,pages:99}
SiloUIAudioKey("back")
for i=1 to 5
 SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"a",item:{itemId:"a"}}],nextCursor:i.ToStr()},m.audioBrowseToken)
end for
bounded=m.calls.Count():zone=m.zone
m.view="audio":m.audioBrowseReturn.scope="other/profile"
SiloUIAudioKey("back")
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"a",item:{itemId:"a"}}],nextCursor:""},m.audioBrowseToken)
print FormatJson({bounded:bounded,zone:zone,otherZone:m.zone,pending:m.audioBrowseRestore})''')
  self.assertEqual(r,{'bounded':5,'zone':'audioBrowseGrid','otherZone':'audioBrowseButtons','pending':None})

 def test_return_result_cannot_steal_focus_after_navigation_or_profile_change(self):
  r=self.flow('''m.view="audio":m.audioReturnBrowse=true:m.audioBrowseScope=m.scope
m.audioBrowseLibraries=[{id:"books",title:"Books"}]:m.audioBrowseLibraryIndex=0
m.audioBrowseReturn={scope:m.scope,libraryId:"books",itemId:"a",index:0,pages:1}
SiloUIAudioKey("back")
SiloUIAudioBrowseKey("up")
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"a",item:{itemId:"a"}}],nextCursor:""},m.audioBrowseToken)
zone=m.zone
m.view="audio":SiloUIAudioKey("back"):m.scope="other/profile"
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"a",item:{itemId:"a"}}],nextCursor:""},m.audioBrowseToken)
print FormatJson({zone:zone,changedZone:m.zone,count:m.audioGrid.content.getChildCount()})''')
  self.assertEqual(r,{'zone':'nav','changedZone':'audioBrowseButtons','count':0})

 def test_router_navigation_cancels_return_before_async_focus(self):
  for mode,key in [('top','back'),('left','left'),('left','back')]:
   with self.subTest(mode=mode,key=key):
    r=self.flow('''m.view="audio":m.audioReturnBrowse=true:m.audioBrowseScope=m.scope
m.audioBrowseLibraries=[{id:"books",title:"Books"}]:m.audioBrowseLibraryIndex=0
m.audioBrowseReturn={scope:m.scope,libraryId:"books",itemId:"a",index:0,pages:1}
m.pillGroups.nav={index:0}:m.navigationMode="MODE"
SiloUIAudioKey("back")
m.pillGroups.audioBrowseButtons.index=0
onKeyEvent("KEY",true)
before=m.zone
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"a",item:{itemId:"a"}}],nextCursor:""},m.audioBrowseToken)
print FormatJson({before:before,after:m.zone,pending:m.audioBrowseRestore})'''.replace('MODE',mode).replace('KEY',key),router=True)
    self.assertEqual(r,{'before':'nav' if mode=='top' else 'drawer','after':'nav' if mode=='top' else 'drawer','pending':None})

 def test_router_key_release_preserves_pending_return(self):
  r=self.flow('''m.view="audio":m.audioReturnBrowse=true:m.audioBrowseScope=m.scope
m.audioBrowseLibraries=[{id:"books",title:"Books"}]:m.audioBrowseLibraryIndex=0
m.audioBrowseReturn={scope:m.scope,libraryId:"books",itemId:"a",index:0,pages:1}
SiloUIAudioKey("back")
onKeyEvent("back",false)
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[{id:"a",item:{itemId:"a"}}],nextCursor:""},m.audioBrowseToken)
print FormatJson({zone:m.zone,index:m.audioGrid.jumpToItem})''',router=True)
  self.assertEqual(r,{'zone':'audioBrowseGrid','index':0})

 def test_empty_return_keeps_retry_focused(self):
  r=self.flow('''m.view="audio":m.audioReturnBrowse=true:m.audioBrowseScope=m.scope
m.audioBrowseLibraries=[{id:"books",title:"Books"}]:m.audioBrowseLibraryIndex=0
m.audioBrowseReturn={scope:m.scope,libraryId:"books",itemId:"removed",index:8,pages:1}
SiloUIAudioKey("back")
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[],nextCursor:""},m.audioBrowseToken)
print FormatJson({zone:m.zone,index:m.pillGroups.audioBrowseButtons.index,pending:m.audioBrowseRestore})''')
  self.assertEqual(r,{'zone':'audioBrowseButtons','index':1,'pending':None})

 def test_zero_libraries_focuses_retry_and_select_fetches_libraries_again(self):
  r=self.flow('''SiloUIAudioBrowse()
SiloUIAudioResult("audio_libraries",{ok:true},{entries:[]},m.audioBrowseToken)
index=m.pillGroups.audioBrowseButtons.index
SiloUIAudioBrowseKey("OK")
print FormatJson({index:index,zone:m.zone,calls:m.calls.Count(),action:m.calls[1].action})''')
  self.assertEqual(r,{'index':1,'zone':'audioBrowseButtons','calls':2,'action':'audio_libraries'})
 def test_empty_catalog_retry_refreshes_library_without_error_or_cursor(self):
  r=self.flow('''SiloUIAudioBrowse()
SiloUIAudioResult("audio_libraries",{ok:true},{entries:[{id:"books",title:"Books"}]},m.audioBrowseToken)
SiloUIAudioResult("audio_catalog",{ok:true},{entries:[],nextCursor:""},m.audioBrowseToken)
empty=m.audioBrowseStatus.text
m.pillGroups.audioBrowseButtons.index=1
SiloUIAudioBrowseKey("OK")
print FormatJson({empty:empty,calls:m.calls.Count(),last:m.calls[m.calls.Count()-1].params,loading:m.audioBrowseLoading})''')
  self.assertEqual(r['empty'],'No audiobooks in this library.')
  self.assertEqual(r['calls'],3)
  self.assertEqual(r['last'],{'libraryId':'books'})
  self.assertTrue(r['loading'])
