"""Native Libraries routes use bounded, selected-library requests."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = ROOT / 'components/SiloUILibraries.brs'

class LibrariesTests(unittest.TestCase):
    def run_flow(self, body, render=False, pop=False, keys=False):
        helpers = '''
function TextOr(value as Dynamic) as String
 if type(value)="String" then return value
 return ""
end function
function NumberOr(value as Dynamic, fallback as Dynamic) as Dynamic
 t=type(value)
 if t="Integer" or t="roInt" or t="roInteger" or t="LongInteger" or t="roLongInteger" or t="Float" or t="roFloat" or t="Double" or t="roDouble" then return value
 return fallback
end function
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.requests.Push(ParseJson(FormatJson({action:action,params:params,purpose:purpose,extra:extra})))
end sub
sub ShowView(view as String)
 m.view=view
end sub
sub SetZone(zone as String)
 m.zone=zone
end sub
sub LibraryResetFilters()
 m.libraryId="":m.librarySource="query"
end sub
sub LibraryQuery(reset as Boolean)
 m.gridRequest={libraryId:m.libraryId,type:m.libraryType,source:m.librarySource}
end sub
sub DetailOpen(item as Object)
 m.detailSelected=item.itemId
end sub
sub NavSelect(index as Integer)
 m.homeSelected=true
end sub
sub BuildPills(parent as Dynamic, name as String, labels as Object, spacing as Integer, height=36 as Integer, size=16 as Integer)
 m.pillGroups[name]={index:0,pills:labels}
end sub
sub SiloUIFocusTrace(stage as String, input as String)
end sub
sub CenterGroup(parent as Object, width as Integer)
end sub
sub SiloUINavigationBuild()
end sub
sub PaintPills(name as String, focused as Boolean)
end sub
function ItemNode(item as Object) as Object
 node=CreateObject("roSGNode","ContentNode")
 node.addFields({item:item})
 return node
end function
'''
        # Rendering is native SG; exercise the public request/result seam on the host.
        source = LIBRARIES.read_text()
        import re
        if not render:
            source = re.sub(r'sub LibrariesPaint\(\).*?\nend sub', 'sub LibrariesPaint()\nend sub', source, flags=re.S)
        if pop:
            scene=(ROOT/'components/SiloUIScene.brs').read_text()
            source += '\n'+re.search(r'function PopView\(\).*?\nend function',scene,re.S)[0]
        if keys:
            scene=(ROOT/'components/SiloUIScene.brs').read_text()
            source += '\n'+re.search(r'function onKeyEvent\(.*?\nend function',scene,re.S)[0]
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'flow.brs'; file.write_text(source+helpers)
            out=run_brightscript([file], '''
m.provider="silo":m.sourceId="source":m.profileId="profile":m.generation=1
m.requests=[]:m.librariesStatus={}:m.librariesTitle={}:m.librariesButtons={}:m.librariesList={}:m.librariesRows={rowItemFocused:[0,0]}
m.history=[]:m.pillGroups={librariesButtons:{index:0}}
'''+body, root=Path(directory))
        assert out, repr(out)
        return json.loads(out.splitlines()[-1])

    def test_overview_filters_nonvideo_and_opens_only_selected_library(self):
        actual=self.run_flow('''
LibrariesOpen()
receipt=m.requests[0].extra
LibrariesResult("libraries_list",{ok:true},{libraries:[{libraryId:"book",title:"Books",type:"ebook"},{libraryId:"m",title:"Movies",type:"movies"},{libraryId:"s",title:"Shows",type:"series"},{libraryId:"off",title:"Hidden",type:"mixed",enabled:false}]},receipt)
LibrariesSelect(1)
print FormatJson({entries:m.librariesEntries,requests:m.requests})
''')
        self.assertEqual([x['libraryId'] for x in actual['entries']], ['m','s'])
        self.assertEqual(actual['requests'][0]['action'], 'libraries')
        self.assertEqual([r['params'] for r in actual['requests'][1:]], [dict(type='video', libraryId='s',sort=s,order='desc',limit=24) for s in ['added_at','release_date','rating_imdb']])

    def test_partial_success_duplicate_and_stale_profile_results(self):
        actual=self.run_flow('''
m.librariesEntries=[{libraryId:"m",title:"Movies",type:"movie"}]
LibrariesSelect(0)
a=m.requests[0].extra:b=m.requests[1].extra:c=m.requests[2].extra
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"one"}]},a)
LibrariesResult("libraries_shelf",{ok:false},{},b)
LibrariesResult("libraries_shelf",{ok:true},{items:[]},c)
LibrariesResult("libraries_shelf",{ok:false},{},a)
old=m.librariesShelves
m.profileId="other"
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"leak"}]},b)
print FormatJson({shelves:old,pending:m.librariesPending,failed:m.librariesFailed})
''')
        self.assertEqual(actual['shelves'][0]['items'], [{'itemId':'one'}])
        self.assertEqual(actual['pending'],0)
        self.assertEqual(actual['failed'],1)

    def test_empty_and_failed_shelves_retry_only_missing_and_retire_old_visit(self):
        actual=self.run_flow('''
m.librariesEntries=[{libraryId:"m",title:"Movies",type:"mixed"}]
LibrariesSelect(0)
a=m.requests[0].extra:b=m.requests[1].extra:c=m.requests[2].extra
LibrariesResult("libraries_shelf",{ok:true},{items:[]},a)
LibrariesResult("libraries_shelf",{ok:false},{},b)
LibrariesResult("libraries_shelf",{ok:false},{},c)
LibrariesLoadShelves(true)
retry=m.requests.Count()
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"stale"}]},b)
pending=m.librariesPending
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"valid"}]},m.requests[3].extra)
LibrariesResult("libraries_shelf",{ok:false},{},m.requests[4].extra)
LibrariesBrowseAll()
print FormatJson({retry:retry,pending:pending,shelves:m.librariesShelves,grid:m.gridRequest,history:m.history})
''')
        self.assertEqual(actual['retry'],5)
        self.assertEqual(actual['pending'],2)
        self.assertEqual(actual['shelves'][0]['items'],[])
        self.assertEqual(actual['shelves'][1]['items'],[{'itemId':'valid'}])
        self.assertEqual(actual['grid'],dict(libraryId='m',type='video',source='query'))
        self.assertEqual(actual['history'],[dict(view='libraryShelves',zone='librariesButtons')])

    def test_bounded_completion_and_detail_back_restore_native_shelf_focus(self):
        actual=self.run_flow('''
m.librariesEntries=[{libraryId:"m",title:"Movies",type:"movies"}]
LibrariesSelect(0)
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"rated"}]},m.requests[2].extra)
before=m.librariesRows.content.getChildCount()
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"added"}]},m.requests[0].extra)
LibrariesResult("libraries_shelf",{ok:true},{items:[]},m.requests[1].extra)
m.librariesRows.rowItemFocused=[1,0]
m.history=[{view:"libraryShelves",zone:"librariesRows"}]:m.view="detail"
PopView()
print FormatJson({before:before,rows:m.librariesRows.content.getChildCount(),restored:m.librariesRows.jumpToRowItem,view:m.view,zone:m.zone,requests:m.requests.Count()})
''',render=True,pop=True)
        self.assertEqual(actual,dict(before=0,rows=2,restored=[1,0],view='libraryShelves',zone='librariesRows',requests=3))

    def test_back_restores_overview_selection_and_rejects_other_library_and_source(self):
        actual=self.run_flow('''
m.librariesEntries=[{libraryId:"m",title:"Movies",type:"movies"},{libraryId:"s",title:"Shows",type:"series"}]
LibrariesSelect(0)
old=m.requests[0].extra
LibrariesSelect(1)
current=m.requests[3].extra
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"old-library"}]},old)
m.sourceId="other-source"
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"other-source"}]},current)
m.sourceId="source":m.generation=2
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"old-generation"}]},current)
m.generation=1
before=m.librariesPending
LibrariesBack()
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"after-back"}]},current)
print FormatJson({before:before,view:m.view,zone:m.zone,selection:m.librariesList.jumpToItem,selected:m.librariesSelected})
''')
        self.assertEqual(actual,dict(before=3,view='libraries',zone='librariesList',selection=1,selected=None))

    def test_retry_inserting_earlier_shelf_keeps_released_card_focused(self):
        actual=self.run_flow('''
m.librariesEntries=[{libraryId:"m",title:"Movies",type:"movies"}]
LibrariesSelect(0)
LibrariesResult("libraries_shelf",{ok:false},{},m.requests[0].extra)
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"released-1"},{itemId:"released-2"},{itemId:"released-3"}]},m.requests[1].extra)
LibrariesResult("libraries_shelf",{ok:false},{},m.requests[2].extra)
LibrariesLoadShelves(true)
m.librariesRows.rowItemFocused=[0,2]:m.zone="librariesRows"
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"added"}]},m.requests[3].extra)
before=m.librariesRows.content.getChildCount()
LibrariesResult("libraries_shelf",{ok:true},{items:[]},m.requests[4].extra)
position=m.librariesRows.jumpToRowItem
focused=""
row=m.librariesRows.content.getChild(position[0])
if position[1] < row.getChildCount() then focused=row.getChild(position[1]).item.itemId
m.librariesRows.rowItemFocused=[1,99]
LibrariesPaint()
print FormatJson({before:before,position:position,focused:focused,clamped:m.librariesRows.jumpToRowItem})
''',render=True)
        self.assertEqual(actual,dict(before=1,position=[1,2],focused='released-3',clamped=[1,2]))

    def test_first_shelf_paint_accepts_empty_and_invalid_native_focus(self):
        for focus in ('[]', 'invalid', '[0]', '[invalid,invalid]', '[0,invalid]', '[invalid,0]', '[-1,-1]'):
            with self.subTest(focus=focus):
                actual=self.run_flow('''
m.librariesRows.rowItemFocused='''+focus+'''
m.librariesEntries=[{libraryId:"m",title:"Movies",type:"movies"}]
LibrariesSelect(0)
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"added"}]},m.requests[0].extra)
LibrariesResult("libraries_shelf",{ok:true},{items:[]},m.requests[1].extra)
LibrariesResult("libraries_shelf",{ok:true},{items:[]},m.requests[2].extra)
print FormatJson({rows:m.librariesRows.content.getChildCount(),jump:m.librariesRows.jumpToRowItem})
''',render=True)
                self.assertEqual(actual,dict(rows=1,jump=None))

    def test_native_selection_callback_ignores_empty_and_out_of_range_coordinates(self):
        actual=self.run_flow('''
m.librariesEntries=[{libraryId:"m",title:"Movies",type:"movies"}]
LibrariesSelect(0)
LibrariesResult("libraries_shelf",{ok:true},{items:[{itemId:"added"}]},m.requests[0].extra)
LibrariesResult("libraries_shelf",{ok:true},{items:[]},m.requests[1].extra)
LibrariesResult("libraries_shelf",{ok:true},{items:[]},m.requests[2].extra)
for each position in [[],invalid,[0],[invalid,invalid],[-1,-1],[0,invalid],[99,0],[0,99]]
 m.librariesRows.rowItemSelected=position
 onLibrariesItem()
end for
before=m.detailSelected
m.librariesRows.rowItemSelected=[0,0]
onLibrariesItem()
print FormatJson({before:before,selected:m.detailSelected})
''',render=True)
        self.assertEqual(actual,dict(before=None,selected='added'))

    def test_native_overview_select_consumes_opening_ok_until_release(self):
        actual=self.run_flow('''
LibrariesOpen()
LibrariesResult("libraries_list",{ok:true},{libraries:[{libraryId:"m",title:"Movies",type:"movies"}]},m.requests[0].extra)
m.librariesList.itemSelected=0
onLibrariesSelect()
LibrariesKey("OK")
before=ParseJson(FormatJson({view:m.view,grid:m.gridRequest,requests:m.requests.Count()}))
onKeyEvent("OK",false)
cleared=m.librariesOpeningSelect
LibrariesKey("OK")
after={view:m.view,grid:m.gridRequest,history:m.history.Count()}
LibrariesSelect(0)
programmatic=m.librariesOpeningSelect
print FormatJson({before:before,cleared:cleared,after:after,programmatic:programmatic})
''',keys=True)
        self.assertEqual(actual,dict(before=dict(view='libraryShelves',grid=None,requests=4),cleared=False,after=dict(view='library',grid=dict(libraryId='m',type='video',source='query'),history=1),programmatic=False))
