"""Exercise shipping search handlers with host API, timer and focus boundaries."""
import json
import re
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class SiloUISearchFlowTests(unittest.TestCase):
    def scene(self, body, real_focus=False, real_dialog=False, real_detail=False):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / 'boundary.brs'
            source = (ROOT / 'components/SiloUILibrary.brs').read_text().replace('AppRegistrySection("silo")', 'TestSearchRegistry()')
            source = re.sub(r'sub BrowsePagedChoices\(.*?\nend sub', '''sub BrowsePagedChoices(title as String, labels as Object, handler as String)
    m.peopleLabels = labels
    m.top.dialog = {close:false}
end sub''', source, count=1, flags=re.S) if not real_dialog else source
            source = source.replace('CreateObject("roSGNode", "KeyboardDialog")', 'TestDialog()')
            source = source.replace('CreateObject("roSGNode", "Dialog")', 'TestDialog()').replace('dialog.observeField(', 'TestObserveField(dialog,')
            scene = Path(directory) / 'scene.brs'
            if real_focus:
                scene_source = (ROOT / 'components/SiloUIScene.brs').read_text()
                source += '\n' + re.search(r'sub SetZone\(.*?\nend sub', scene_source, re.S)[0]
                source += '\n' + (ROOT / 'components/SiloUIAccessibility.brs').read_text()
            if real_detail:
                detail = (ROOT / 'components/SiloUIDetail.brs').read_text()
                source += '\n' + re.search(r'sub DetailOpen\(.*?\nend sub', detail, re.S)[0]
                source += '\n' + re.search(r'function DetailKey\(.*?\nend function', detail, re.S)[0]
                source += '\n' + re.search(r'function DetailIsSeries\(.*?\nend function', detail, re.S)[0]
            scene.write_text(source)
            helper_source = '''
function TestSearchRegistry() as Object
    return m.registry
end function
sub TestSearchOption(index as Integer)
    selected=m.top.dialog:selected.buttonSelected=index
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onSearchOption(event)
end sub
sub TestSearchPeople()
    SearchKey("options")
    TestSearchOption(3)
end sub
sub TestObserveField(node as Object, field as String, handler as String)
end sub
function TestDialog() as Object
    node=CreateObject("roSGNode","ContentNode")
    node.AddFields({text:"",maxHeight:0,buttons:[],buttonSelected:-1,close:false,wasClosed:false,message:""})
    return node
end function
function TestFindNode(name as String) as Object
    return {opacity:1}
end function
sub TestSetFocus(focused as Boolean)
end sub
function ItemNode(item as Object) as Object
    node=CreateObject("roSGNode","ContentNode")
    node.title=item.title
    node.AddFields({item:item})
    return node
end function
sub ApiOwned(action as String, params as Object, purpose as String, extra as Dynamic, owner as Object)
    Api(action,params,purpose,extra)
end sub
sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic)
    m.requests.Push({action:action,params:params,purpose:purpose,token:extra})
end sub
sub SetZone(zone as String)
    m.zone = zone
    m.focusMoves.Push(zone)
end sub
sub Toast(message as String)
    m.toasts.Push(message)
end sub
'''
            if real_detail:
                helper_source += '''
function StreamingScopeKey() as String
    return m.provider + ":" + m.sourceId + ":" + m.profileId
end function
sub DetailPhotosClear()
end sub
sub PlayerDiscardPrebuffer()
end sub
sub ShowView(view as String)
    m.view=view
end sub
sub DetailRender(item as Object)
    m.rendered=item
end sub
'''
            if real_focus:
                helper_source = re.sub(r'sub SetZone\(.*?\nend sub', '', helper_source, flags=re.S)
                helper_source += '''
sub PaintZone(name as String, focused as Boolean)
end sub
sub PaintPills(name as String, focused as Boolean)
end sub
sub HomeSyncTimer()
end sub
sub SiloUIFocusTrace(stage as String, zone as String)
    if stage = "zoneAfter" then m.focusMoves.Push(zone)
end sub
'''
            helper_source += '''
function SearchIndexAdd(existing as Dynamic, incoming as Dynamic, sourceId as String, limit = 500 as Integer) as Object
    m.indexBuilds++
    return OriginalSearchIndexAdd(existing,incoming,sourceId,limit)
end function
'''
            policy = Path(directory) / 'search_policy.brs'
            policy.write_text((ROOT / 'source/core/SearchPolicy.brs').read_text().replace('function SearchIndexAdd(', 'function OriginalSearchIndexAdd(', 1))
            helper.write_text(helper_source)
            output = run_brightscript(
                [scene, helper, ROOT / "components/SiloUIDialogs.brs", ROOT / "source/core/SiloUIFormat.brs", policy],
                '''
    m.registry={values:{revision:"0"},Read:function(key)
        if not m.values.DoesExist(key) then return ""
        return m.values[key]
    end function,Write:function(key,value)
        m.values[key]=value:return true
    end function,Delete:function(key)
        m.values.Delete(key):return true
    end function,Flush:function()
        return true
    end function}
    m.top={dialog:invalid,findNode:TestFindNode}:m.provider="silo":m.sourceId="s1":m.profileId="p1":m.generation=1:m.view="search":m.zone="keyboard"
    m.keyboard={text:"Arrival",setFocus:TestSetFocus}:m.searchToken=0:m.searchTimer={}
    m.searchGrid={setFocus:TestSetFocus,content:CreateObject("roSGNode","ContentNode")}:m.searchHint={text:""}
    m.indexBuilds=0:m.requests=[]:m.toasts=[]:m.peopleLabels=[]:m.focusMoves=[]:m.manualFocus={setFocus:TestSetFocus}
''' + body, root=Path(directory))
            return json.loads(output.splitlines()[-1])

    def test_collection_create_from_detail_is_explicit_and_one_shot(self):
        for button, actions in [(0,["collection_capabilities","collection_choices","collection_create"]),(1,["collection_capabilities","collection_choices","collection_create","collection_add"]),(2,["collection_capabilities","collection_choices"])]:
            with self.subTest(button=button):
                result=self.scene('''
 m.view="detail":m.zone="detailButtons":m.detailToken=4:m.detailItem={itemId:"movie",type:"movie"}
 DetailKey("options")
 node=m.top.dialog:node.buttonSelected=5
 event={node:node,getRoSGNode:function()
 return m.node
 end function}
 onBrowseSocial(event):ticket=m.requests[0].token
 BrowseResult("browse_collection_capabilities",{ok:true},{supported:true,canCreate:true},ticket)
 BrowseResult("browse_collection_choices",{ok:true},{entries:[]},ticket)
 labels=m.top.dialog.buttons
 node=m.top.dialog:node.buttonSelected=0:event.node=node:onBrowseCollection(event)
 node=m.top.dialog:node.text=" Weekend ":node.buttonSelected='''+str(button)+''':event.node=node
 onBrowseCollectionCreate(event):onBrowseCollectionCreate(event)
 BrowseResult("browse_collection_create",{ok:true},{collectionId:"new"},ticket)
 BrowseResult("browse_collection_create",{ok:true},{collectionId:"new"},ticket)
 actions=[]:for each request in m.requests:actions.Push(request.action):end for
 print FormatJson({labels:labels,actions:actions})
''',real_dialog=True,real_detail=True)
                self.assertEqual({"labels":["New collection","Cancel"],"actions":actions},result)

    def test_collection_create_without_membership_capability_skips_lookup(self):
        result=self.scene('''
 m.view="detail":m.zone="detailButtons":m.detailToken=4:m.detailItem={itemId:"movie",type:"movie"}
 DetailKey("options")
 node=m.top.dialog:node.buttonSelected=5
 event={node:node,getRoSGNode:function()
 return m.node
 end function}
 onBrowseSocial(event):ticket=m.requests[0].token
 BrowseResult("browse_collection_capabilities",{ok:true},{supported:false,canCreate:true},ticket)
 labels=m.top.dialog.buttons
 node=m.top.dialog:node.buttonSelected=0:event.node=node:onBrowseCollection(event)
 node=m.top.dialog:node.text="Weekend":node.buttonSelected=0:event.node=node:onBrowseCollectionCreate(event)
 actions=[]:for each request in m.requests:actions.Push(request.action):end for
 print FormatJson({labels:labels,actions:actions})
''',real_dialog=True,real_detail=True)
        self.assertEqual({"labels":["New collection","Cancel"],"actions":["collection_capabilities","collection_create"]},result)

    def test_created_collection_add_failure_keeps_creation_feedback(self):
        result=self.scene('''
 m.view="detail":m.zone="detailButtons":m.detailToken=4:m.detailItem={itemId:"movie",type:"movie"}
 DetailKey("options")
 node=m.top.dialog:node.buttonSelected=5
 event={node:node,getRoSGNode:function()
 return m.node
 end function}
 onBrowseSocial(event):ticket=m.requests[0].token
 BrowseResult("browse_collection_capabilities",{ok:true},{supported:true,canCreate:true},ticket)
 BrowseResult("browse_collection_choices",{ok:true},{entries:[]},ticket)
 node=m.top.dialog:node.buttonSelected=0:event.node=node:onBrowseCollection(event)
 node=m.top.dialog:node.text="Weekend":node.buttonSelected=1:event.node=node:onBrowseCollectionCreate(event)
 BrowseResult("browse_collection_create",{ok:true},{collectionId:"new"},ticket)
 BrowseResult("browse_social",{ok:false},{},m.requests[3].token)
 print FormatJson({toasts:m.toasts,pending:m.browseMutationPending,count:m.requests.Count()})
''',real_dialog=True,real_detail=True)
        self.assertEqual({"toasts":["Collection created; title was not added."],"pending":False,"count":4},result)

    def test_collection_creation_rejects_stale_dialog_and_late_receipt(self):
        for before, after, expected in [('m.profileId="other"',"",2),("",'m.detailToken=5',3),("",'m.profileId="other"',3)]:
            with self.subTest(before=before,after=after):
                result=self.scene('''
 m.view="detail":m.zone="detailButtons":m.detailToken=4:m.detailItem={itemId:"movie",type:"movie"}
 DetailKey("options")
 node=m.top.dialog:node.buttonSelected=5
 event={node:node,getRoSGNode:function()
 return m.node
 end function}
 onBrowseSocial(event):ticket=m.requests[0].token
 BrowseResult("browse_collection_capabilities",{ok:true},{supported:true,canCreate:true},ticket)
 BrowseResult("browse_collection_choices",{ok:true},{entries:[]},ticket)
 node=m.top.dialog:node.buttonSelected=0:event.node=node:onBrowseCollection(event)
 node=m.top.dialog:node.text="Weekend":node.buttonSelected=1:event.node=node
 '''+before+'''
 onBrowseCollectionCreate(event)
 '''+after+'''
 BrowseResult("browse_collection_create",{ok:true},{collectionId:"new"},ticket)
 print FormatJson(m.requests.Count())
''',real_dialog=True,real_detail=True)
                self.assertEqual(expected,result)

    def test_collection_options_load_only_owned_manual_lists_and_bind_mutation(self):
        result=self.scene('''
 m.view="detail":m.zone="detailButtons":m.detailToken=4:m.detailItem={itemId:"movie",type:"movie"}
 DetailKey("options")
 node=m.top.dialog:node.buttonSelected=5
 event={node:node,getRoSGNode:function()
 return m.node
 end function}
 onBrowseSocial(event)
 first=m.requests[0]
 BrowseResult("browse_collection_capabilities",{ok:true},{supported:true},first.token)
 lookup=m.requests[1]
 BrowseResult("browse_collection_choices",{ok:true},{entries:[
 {id:"own",title:"My list",collectionType:"manual",creatorProfileId:"p1",contains:false},
 {id:"shared",title:"Shared",collectionType:"manual",creatorProfileId:"p2",contains:false},
 {id:"smart",title:"Smart",collectionType:"smart",creatorProfileId:"p1",contains:true}]},lookup.token)
 labels=m.top.dialog.buttons
 node=m.top.dialog:node.buttonSelected=0:event.node=node
 onBrowseCollection(event)
 print FormatJson({first:first.action,lookup:lookup.params,labels:labels,last:m.requests[2].action,params:m.requests[2].params})
''',real_dialog=True,real_detail=True)
        self.assertEqual(dict(first="collection_capabilities",lookup=dict(itemId="movie"),labels=["Add to My list","Cancel"],last="collection_add",params=dict(itemId="movie",collectionId="own")),result)

    def test_collection_removal_rejects_repeated_receipts_and_stale_selection(self):
        for mutation, expected in [("",["collection_remove"]),('m.profileId="other"',[]),('m.detailToken=5',[])]:
            with self.subTest(mutation=mutation):
                result=self.scene('''
 m.view="detail":m.zone="detailButtons":m.detailToken=4:m.detailItem={itemId:"movie",type:"movie"}
 DetailKey("options")
 node=m.top.dialog:node.buttonSelected=5
 event={node:node,getRoSGNode:function()
 return m.node
 end function}
 onBrowseSocial(event):ticket=m.requests[0].token
 BrowseResult("browse_collection_capabilities",{ok:true},{supported:true},ticket)
 BrowseResult("browse_collection_capabilities",{ok:true},{supported:true},ticket)
 count=m.requests.Count()
 BrowseResult("browse_collection_choices",{ok:true},{entries:[{id:"own",title:"My list",collectionType:"manual",creatorProfileId:"p1",contains:true}]},ticket)
 node=m.top.dialog:node.buttonSelected=0:event.node=node
 '''+mutation+'''
 onBrowseCollection(event):onBrowseCollection(event)
 actions=[]
 for each request in m.requests
 if request.action="collection_remove" then actions.Push(request.action)
 end for
 print FormatJson({count:count,actions:actions})
''',real_dialog=True,real_detail=True)
                self.assertEqual(dict(count=2,actions=expected),result)

    def test_collection_lookup_stops_for_unsupported_servers_and_late_owner(self):
        for mutation, response, expected_toasts in [("", "{ok:true}",1),("", "{ok:false}",1),('m.profileId="other"',"{ok:true}",0)]:
            with self.subTest(mutation=mutation,response=response):
                result=self.scene('''
 m.view="detail":m.zone="detailButtons":m.detailToken=4:m.detailItem={itemId:"movie",type:"movie"}
 DetailKey("options")
 node=m.top.dialog:node.buttonSelected=5
 event={node:node,getRoSGNode:function()
 return m.node
 end function}
 onBrowseSocial(event):ticket=m.requests[0].token
 '''+mutation+'''
 BrowseResult("browse_collection_capabilities",'''+response+''',{supported:false},ticket)
 print FormatJson({requests:m.requests.Count(),toasts:m.toasts.Count()})
''',real_dialog=True,real_detail=True)
                self.assertEqual(dict(requests=1,toasts=expected_toasts),result)

    def test_detail_genre_cancel_and_stale_visit_do_not_navigate(self):
        actual = self.scene('''
    m.view="detail":m.zone="detailButtons":m.detailToken=7:m.history=[]
    m.detailItem={itemId:"movie",type:"movie",genres:["Drama"]}
    BrowseSocial(m.detailItem)
    selected=m.top.dialog:selected.buttonSelected=5
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onBrowseSocial(event)
    selected=m.top.dialog:selected.buttonSelected=1:event.node=selected
    onBrowseGenre(event)
    cancelled=m.requests.Count()
    BrowseSocial(m.detailItem)
    selected=m.top.dialog:selected.buttonSelected=5:event.node=selected
    onBrowseSocial(event)
    selected=m.top.dialog:selected.buttonSelected=0:event.node=selected
    m.detailToken=8
    onBrowseGenre(event)
    print FormatJson({cancelled:cancelled,requests:m.requests.Count(),history:m.history.Count(),view:m.view})
''', real_dialog=True)
        self.assertEqual(dict(cancelled=0,requests=0,history=0,view="detail"),actual)

    def test_detail_genre_browse_starts_clean_scope_and_preserves_origin(self):
        actual = self.scene('''
    m.view="detail":m.zone="detailCast":m.detailToken=7:m.history=[]
    m.detailItem={itemId:"episode",type:"episode",genres:["Drama","Science Fiction"]}
    m.librarySortProvider="silo":m.librarySorts=[{sort:"title",order:"asc"}]:m.pillGroups={libraryTabs:{index:0}}
    m.libraryTitle={}:m.grid={}:m.libraryEmpty={}:m.libraryToken=3
    m.libraryCollection="old":m.libraryPerson="old":m.libraryDecade=1990:m.libraryMinimumRating=8
    BrowseSocial(m.detailItem)
    labels=m.top.dialog.buttons
    selected=m.top.dialog:selected.buttonSelected=5
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onBrowseSocial(event)
    genres=m.top.dialog.buttons
    selected=m.top.dialog:selected.buttonSelected=1:event.node=selected
    onBrowseGenre(event)
    print FormatJson({labels:labels,genres:genres,request:m.requests.Peek(),history:m.history,zone:m.zone,view:m.view,title:m.libraryTitle.text})
''', real_dialog=True, real_detail=True)
        self.assertIn("Browse genre", actual["labels"])
        self.assertEqual(["Drama", "Science Fiction", "Cancel"], actual["genres"])
        self.assertEqual("series", actual["request"]["params"]["type"])
        self.assertEqual("Science Fiction", actual["request"]["params"]["genre"])
        self.assertEqual("query", actual["request"]["params"]["source"])
        self.assertEqual("", actual["request"]["params"]["collectionId"])
        self.assertNotIn("decade", actual["request"]["params"])
        self.assertNotIn("minimumRating", actual["request"]["params"])
        self.assertEqual("detailCast", actual["history"][0]["zone"])
        self.assertEqual("episode", actual["history"][0]["browseDetailItem"]["itemId"])
        self.assertEqual("libraryTabs", actual["zone"])
        self.assertEqual("library", actual["view"])
        self.assertEqual("Shows • Science Fiction", actual["title"])

    def test_loaded_titles_preview_then_server_owns_order_and_cursor(self):
        actual = self.scene('''
    m.sourceId="silo:test"
    m.homeLoadedScope={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    m.homeRows=[{items:[{provider:"silo",sourceId:m.sourceId,itemId:"old",title:"Arrival old",type:"movie",mediaUrl:"secret"}]}]
    onSearchTimer()
    preview=m.searchGrid.content.getChild(0).item:hint=m.searchHint.text:requests=m.requests.Count()
    SearchResult("search_results",{ok:true},{items:[{provider:"silo",sourceId:m.sourceId,itemId:"fresh",title:"Arrival fresh",type:"movie"}],hasMore:true,nextCursor:"next"},m.searchToken)
    print FormatJson({preview:preview,hint:hint,requests:requests,count:m.searchGrid.content.getChildCount(),first:m.searchGrid.content.getChild(0).item.itemId,cursor:m.searchCursor,pages:m.searchPages})
''')
        self.assertEqual(actual['preview'], dict(provider='silo', sourceId='silo:test', itemId='old', title='Arrival old', type='movie', year=0))
        self.assertIn('Loaded titles', actual['hint'])
        self.assertEqual({k: actual[k] for k in ['requests','count','first','cursor','pages']}, dict(requests=1,count=1,first='fresh',cursor='next',pages=1))

    def test_loaded_preview_scope_filters_failure_and_retry(self):
        actual = self.scene('''
    m.sourceId="silo:test"
    m.homeLoadedScope={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    m.homeRows=[{items:[{sourceId:m.sourceId,itemId:"m",title:"Arrival movie",type:"movie"},{sourceId:m.sourceId,itemId:"s",title:"Arrival show",type:"series"}]}]
    onSearchTimer():SearchResult("search_results",{ok:false},{},m.searchToken)
    failed=m.searchHint.text:count=m.searchGrid.content.getChildCount()
    SearchKey("options"):retry=m.requests.Count():retryCursor=m.requests[1].params.DoesExist("cursor")
    SearchResult("search_results",{ok:true},{items:[]},m.searchToken)
    empty=m.searchGrid.content.getChildCount()
    m.searchKind="series":onSearchText():onSearchTimer():show=m.searchGrid.content.getChild(0).item.itemId
    m.profileId="p2":onSearchText():onSearchTimer():other=m.searchGrid.content.getChildCount()
    m.profileId="p1":onSearchText():onSearchTimer():returned=m.searchGrid.content.getChildCount()
    m.generation=2:onSearchText():onSearchTimer():generation=m.searchGrid.content.getChildCount()
    m.keyboard.text="":onSearchText():onSearchTimer()
    print FormatJson({failed:failed,count:count,retry:retry,retryCursor:retryCursor,empty:empty,show:show,other:other,returned:returned,generation:generation,cleared:m.searchGrid.content.getChildCount()})
''')
        self.assertIn('Loaded titles · Incomplete', actual.pop('failed'))
        self.assertEqual(actual, dict(count=2,retry=2,retryCursor=False,empty=0,show='s',other=0,returned=2,generation=0,cleared=0))

    def test_loaded_title_selection_requests_fresh_detail(self):
        actual = self.scene('''
    m.sourceId="silo:test":m.detailVisit=0:m.history=[]:m.pillGroups={}
    m.detailRatings=CreateObject("roSGNode","ContentNode"):m.detailCast={}:m.detailSimilar={}:m.episodes={}:m.seasonPills=CreateObject("roSGNode","ContentNode")
    m.homeLoadedScope={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    m.homeRows=[{items:[{sourceId:m.sourceId,itemId:"m",title:"Arrival",type:"movie",playbackUrl:"secret",art:{poster:"secret"}}]}]
    onSearchTimer():m.searchGrid.itemSelected=0:onSearchSelect()
    print FormatJson({actions:[m.requests[0].action,m.requests[1].action,m.requests[2].action],id:m.requests[1].params.itemId,item:m.detailItem,rendered:m.rendered})
''', real_detail=True)
        self.assertEqual(actual['actions'], ['catalog_query','detail','similar'])
        self.assertEqual(actual['id'], 'm')
        self.assertIsNone(actual['item'])
        self.assertNotIn('playbackUrl', actual['rendered'])
        self.assertNotIn('art', actual['rendered'])

    def test_stale_and_failed_replies_never_seed_loaded_titles(self):
        actual = self.scene('''
    m.sourceId="silo:test":onSearchTimer():stale=m.searchToken
    m.keyboard.text="Different":onSearchText():onSearchTimer()
    items=[{sourceId:m.sourceId,itemId:"private",title:"Arrival private",type:"movie"}]
    SearchResult("search_results",{ok:true},{items:items},stale)
    SearchResult("search_results",{ok:false},{items:items},m.searchToken)
    m.keyboard.text="Arrival":onSearchText():onSearchTimer()
    print FormatJson({count:m.searchGrid.content.getChildCount(),requests:m.requests.Count(),loaded:m.searchLoaded.Count()})
''')
        self.assertEqual(actual, dict(count=0,requests=3,loaded=0))

    def test_loaded_preview_limits_rows_without_paging_before_server(self):
        actual = self.scene('''
    m.sourceId="silo:test":items=[]
    for index=1 to 150
        items.Push({sourceId:m.sourceId,itemId:index.ToStr(),title:"Arrival "+index.ToStr(),type:"movie"})
    end for
    m.homeLoadedScope={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    m.homeRows=[{items:items}]:onSearchTimer()
    m.zone="searchGrid":m.searchGrid.itemFocused=35:onSearchFocus()
    print FormatJson({rows:m.searchGrid.content.getChildCount(),indexed:m.searchLoaded.Count(),requests:m.requests.Count(),pages:m.searchPages,more:m.searchMore,cursor:m.searchCursor})
''')
        self.assertEqual(actual, dict(rows=36,indexed=100,requests=1,pages=0,more=False,cursor=''))

    def test_loaded_index_reuses_queries_and_refreshes_changed_producers(self):
        actual = self.scene('''
    m.sourceId="silo:test":m.homeLoadedRevision=1
    m.homeLoadedScope={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    m.homeRows=[{items:[{sourceId:m.sourceId,itemId:"m",title:"Arrival",type:"movie"}]}]
    onSearchTimer():m.keyboard.text="Arr":onSearchText():onSearchTimer()
    unchanged=m.indexBuilds
    m.homeRows=[{items:[{sourceId:m.sourceId,itemId:"n",title:"Arrival new",type:"movie"}]}]:m.homeLoadedRevision=2
    onSearchText():onSearchTimer():changed=m.indexBuilds:newId=m.searchGrid.content.getChild(0).item.itemId
    m.libraryLoadedScope=m.homeLoadedScope:m.libraryLoadedRevision=1
    root=CreateObject("roSGNode","ContentNode"):root.appendChild(ItemNode({sourceId:m.sourceId,itemId:"l",title:"Arrival library",type:"movie"})):m.grid={content:root}
    onSearchText():onSearchTimer():library=m.indexBuilds
    onSearchText():onSearchTimer()
    print FormatJson({unchanged:unchanged,changed:changed,newId:newId,library:library,finalBuilds:m.indexBuilds,rows:m.searchGrid.content.getChildCount(),requests:m.requests.Count()})
''')
        self.assertEqual(actual, dict(unchanged=1,changed=2,newId='n',library=3,finalBuilds=3,rows=3,requests=5))

    def test_loaded_index_refreshes_title_keys_for_same_identity(self):
        actual = self.scene('''
    m.sourceId="silo:test":m.homeLoadedRevision=1
    m.homeLoadedScope={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    m.homeRows=[{items:[{sourceId:m.sourceId,itemId:"m",title:"Arrival",type:"movie"}]}]
    onSearchTimer():first=m.searchGrid.content.getChildCount()
    m.homeRows=[{items:[{sourceId:m.sourceId,itemId:"m",title:"Departed",type:"movie"}]}]:m.homeLoadedRevision=2
    onSearchText():onSearchTimer():old=m.searchGrid.content.getChildCount()
    m.keyboard.text="Departed":onSearchText():onSearchTimer()
    print FormatJson({first:first,old:old,newTitle:m.searchGrid.content.getChild(0).item.title,builds:m.indexBuilds})
''')
        self.assertEqual(actual, dict(first=1,old=0,newTitle='Departed',builds=2))

    def test_loaded_library_title_remains_available_with_full_home_index(self):
        actual = self.scene('''
    m.sourceId="silo:test":items=[]
    for index=1 to 100
        items.Push({sourceId:m.sourceId,itemId:index.ToStr(),title:"Home "+index.ToStr(),type:"movie"})
    end for
    m.homeLoadedScope={provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    m.homeRows=[{items:items}]
    m.libraryLoadedScope=m.homeLoadedScope
    root=CreateObject("roSGNode","ContentNode"):root.appendChild(ItemNode({sourceId:m.sourceId,itemId:"library",title:"Arrival library",type:"movie"})):m.grid={content:root}
    onSearchTimer()
    print FormatJson({rows:m.searchGrid.content.getChildCount(),index:m.searchLoaded.Count()})
''')
        self.assertEqual(actual, dict(rows=1,index=100))

    def test_recent_success_survives_fresh_scene_for_only_its_owner(self):
        actual = self.scene('''
    onSearchTimer():SearchResult("search_results",{ok:true},{items:[]},m.searchToken)
    m.searchKindScope=invalid:m.searchRecents=invalid
    SearchRecentChoices():restored=m.searchRecents
    m.profileId="p2":SearchRecentChoices():other=m.searchRecents
    m.profileId="p1":m.sourceId="s2":SearchRecentChoices():source=m.searchRecents
    m.sourceId="s1":m.provider="plex":SearchRecentChoices():plex=m.searchRecents
    m.provider="silo":m.registry.values.revision="1":SearchRecentChoices()
    print FormatJson({restored:restored,other:other,source:source,plex:plex,account:m.searchRecents})
''')
        self.assertEqual(actual, dict(restored=['Arrival'], other=[], source=[], plex=[], account=[]))

    def test_clear_removes_persisted_history_before_reload(self):
        actual = self.scene('''
    onSearchTimer():SearchResult("search_results",{ok:true},{items:[]},m.searchToken)
    SearchRecentChoices()
    selected=m.top.dialog:selected.buttonSelected=1
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onSearchRecent(event)
    m.searchKindScope=invalid:m.searchRecents=invalid:SearchRecentChoices()
    print FormatJson({queries:m.searchRecents,stored:m.registry.values.DoesExist("recentSearches")})
''', real_dialog=True)
        self.assertEqual(actual, dict(queries=[], stored=False))

    def test_untrusted_recent_records_are_ignored(self):
        records = ['bad', 'x' * 2049,
                   json.dumps(dict(schemaVersion=1, sourceId='s1', profileId='p1', revision='0', queries=['x'] * 9)),
                   json.dumps(dict(schemaVersion=1, sourceId='s1', profileId='p1', revision='0', queries=['x' * 121])),
                   json.dumps(dict(schemaVersion=1, sourceId='s1', profileId='p1', revision='0', queries=[42])),
                   json.dumps(dict(schemaVersion=1, sourceId='s1', profileId='p1', revision='0', queries=['bad\nquery']))]
        for raw in records:
            with self.subTest(raw=raw[:40]):
                actual = self.scene('    m.registry.values.recentSearches="' + raw.replace('"', '""') + '"\n'
                                    + '    SearchRecentChoices():print FormatJson(m.searchRecents)')
                self.assertEqual(actual, [])

    def test_recent_records_reject_invalid_metadata_types(self):
        for field, value in [('schemaVersion', {}), ('sourceId', {}), ('profileId', []), ('revision', {})]:
            with self.subTest(field=field):
                record = dict(schemaVersion=1, sourceId='s1', profileId='p1', revision='0', queries=['Arrival'])
                record[field] = value
                raw = json.dumps(record).replace('"', '""')
                actual = self.scene('    m.registry.values.recentSearches="' + raw + '"\n'
                                    + '    SearchRecentChoices():print FormatJson(m.searchRecents)')
                self.assertEqual(actual, [])

    def test_recent_success_mru_bounds_and_identity_reset(self):
        actual = self.scene('''
    for each query in ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "tWO"]
        m.keyboard.text=query:onSearchTimer()
        SearchResult("search_results",{ok:true},{items:[]},m.searchToken)
    end for
    SearchKey("options"):TestSearchOption(4)
    first=m.top.dialog.buttons
    selected=m.top.dialog:selected.buttonSelected=6
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onSearchRecent(event)
    labels=m.top.dialog.buttons
    m.top.dialog.close=true:m.profileId="p2":onSearchText()
    SearchKey("options"):TestSearchOption(4)
    print FormatJson({first:first,labels:labels,empty:m.top.dialog.title,requests:m.requests.Count()})
''', real_dialog=True)
        self.assertEqual(actual['first'], ['tWO', 'Nine', 'Eight', 'Seven', 'Six', 'Five', 'More choices', 'Cancel'])
        self.assertEqual(actual['labels'], ['Four', 'Three', 'Clear recent searches', 'Previous choices', 'Cancel'])
        self.assertEqual(actual['empty'], 'No recent searches')
        self.assertEqual(actual['requests'], 10)

    def test_recents_ignore_failed_stale_pages_and_unsafe_queries(self):
        actual = self.scene('''
    onSearchTimer():old=m.searchToken
    m.keyboard.text="Failure":onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[]},old)
    SearchResult("search_results",{ok:false},{},m.searchToken)
    m.keyboard.text="Saved":onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",title:"A"}],hasMore:true,nextCursor:"c"},m.searchToken)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
    SearchResult("search_results",{ok:true},{items:[]},m.searchToken)
    for each query in [String(121,"x"),"bad"+Chr(10)+"query"]
        m.keyboard.text=query:onSearchTimer()
        SearchResult("search_results",{ok:true},{items:[]},m.searchToken)
    end for
    SearchKey("options"):TestSearchOption(4)
    print FormatJson({labels:m.top.dialog.buttons})
''', real_dialog=True)
        self.assertEqual(actual['labels'], ['Saved', 'Clear recent searches', 'Cancel'])

    def test_recent_selection_clear_cancel_and_stale_dialog(self):
        for action in ['select', 'cancel', 'clear', 'stale']:
            with self.subTest(action=action):
                actual = self.scene('''
    onSearchTimer():SearchResult("search_results",{ok:true},{items:[]},m.searchToken)
    m.keyboard.text="Pending":onSearchText()
    SearchKey("options"):TestSearchOption(4)
    selected=m.top.dialog
    selected.buttonSelected=''' + str({'select': 0, 'cancel': 2, 'clear': 1, 'stale': 0}[action]) + '''
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
''' + ('    m.profileId="p2"\n' if action == 'stale' else '') + '''
    onSearchRecent(event)
    before=m.requests.Count()
''' + ('    onSearchText()\n' if action == 'select' else '') + '''
    if m.searchTimer.control="start" then onSearchTimer()
    print FormatJson({before:before,requests:m.requests.Count(),query:m.keyboard.text,recents:m.searchRecents,timer:m.searchTimer.control})
''', real_dialog=True)
                self.assertEqual(actual['before'], 1)
                self.assertEqual(actual['requests'], 1 if action == 'stale' else 2)
                self.assertEqual(actual['query'], 'Arrival' if action == 'select' else 'Pending')
                self.assertEqual(actual['recents'], [] if action == 'clear' else ['Arrival'])

    def test_recent_chooser_keeps_paused_debounce_when_parent_dialog_closes(self):
        actual = self.scene('''
    onSearchText():SearchKey("options"):TestSearchOption(4)
    onSearchDialogClosed()
    print FormatJson({timer:m.searchTimer.control,requests:m.requests.Count(),title:m.top.dialog.title})
''', real_dialog=True)
        self.assertEqual(actual, dict(timer='stop', requests=0, title='No recent searches'))

    def test_empty_recent_chooser_offers_only_cancel_and_resumes_debounce(self):
        actual = self.scene('''
    onSearchText():SearchKey("options"):TestSearchOption(4)
    labels=m.top.dialog.buttons
    selected=m.top.dialog:selected.buttonSelected=0
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onSearchRecent(event)
    print FormatJson({labels:labels,timer:m.searchTimer.control,requests:m.requests.Count()})
''', real_dialog=True)
        self.assertEqual(actual, dict(labels=['Cancel'], timer='start', requests=0))

    def test_filter_menu_restarts_current_query_and_keeps_type_for_edits_and_pages(self):
        actual = self.scene('''
    onSearchTimer():old=m.requests[0].token
    SearchKey("options")
    labels=m.top.dialog.buttons
    TestSearchOption(1)
    SearchResult("search_results",{ok:true},{items:[{itemId:"old",type:"movie",title:"Old"}]},old)
    before=m.requests.Count()
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c",hasMore:true},m.requests[1].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
    m.keyboard.text="Blade":onSearchText()
    typing=m.requests.Count():onSearchTimer()
    print FormatJson({labels:labels,before:before,typing:typing,requests:m.requests,hint:m.searchHint.text})
''')
        self.assertEqual(actual['labels'][:4], ['All titles', 'Movies', 'Shows', 'Search people'])
        self.assertEqual((actual['before'], actual['typing']), (1, 3))
        self.assertEqual([r['params'].get('type') for r in actual['requests']], [None, 'movie', 'movie', 'movie'])
        self.assertEqual(actual['hint'], 'Movies · Searching…')

    def test_open_options_pauses_typing_debounce_until_back(self):
        actual = self.scene('''
    onSearchText():SearchKey("options")
    paused=m.searchTimer.control
    m.top.dialog.wasClosed=true:onSearchDialogClosed()
    resumed=m.searchTimer.control:onSearchTimer()
    print FormatJson({paused:paused,resumed:resumed,requests:m.requests.Count()})
''')
        self.assertEqual(actual, dict(paused='stop', resumed='start', requests=1))

    def test_options_cancel_keeps_debounce_and_dispatches_only_once(self):
        actual = self.scene('''
    onSearchText():SearchKey("options")
    opened=m.requests.Count():TestSearchOption(5)
    cancelled=m.requests.Count():onSearchTimer()
    print FormatJson({opened:opened,cancelled:cancelled,requests:m.requests.Count(),timer:m.searchTimer.control})
''')
        self.assertEqual(actual, dict(opened=0, cancelled=0, requests=1, timer='start'))

    def test_shows_filter_retry_and_scope_reset(self):
        actual = self.scene('''
    onSearchTimer():SearchKey("options"):TestSearchOption(2):onSearchTimer()
    SearchResult("search_results",{ok:false},{},m.requests[1].token)
    SearchKey("options")
    retry=m.requests[2].params
    m.profileId="p2":onSearchTimer()
    print FormatJson({retry:retry,reset:m.requests[3].params,hint:m.searchHint.text})
''')
        self.assertEqual(actual['retry'], dict(query='Arrival', limit=36, type='series'))
        self.assertEqual(actual['reset'], dict(query='Arrival', limit=36))
        self.assertEqual(actual['hint'], 'All titles · Searching…')

    def test_stale_filter_callbacks_cannot_mutate_or_dispatch(self):
        for change in ['m.keyboard.text="Blade":onSearchText()', 'm.sourceId="s2"',
                       'm.profileId="p2"', 'm.generation=2', 'SearchKey("options")']:
            with self.subTest(change=change):
                actual = self.scene('''
    onSearchTimer():SearchKey("options")
    selected=m.top.dialog:selected.buttonSelected=1
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
''' + change + '''
    onSearchOption(event)
    print FormatJson({kind:m.searchKind,requests:m.requests.Count()})
''')
                self.assertEqual(actual, dict(kind='', requests=1))

    def test_visible_count_uses_singular_and_excludes_duplicates_and_episodes(self):
        actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"},{itemId:"a",type:"movie",title:"duplicate"},{itemId:"e",type:"episode",title:"hidden"}],hasMore:false},m.requests[0].token)
    print FormatJson({hint:m.searchHint.text,count:m.searchGrid.content.getChildCount(),requests:m.requests.Count()})
''')
        self.assertEqual(actual, dict(hint='All titles · 1 result', count=1, requests=1))

    def test_additional_page_keeps_visible_count_while_loading(self):
        actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"},{itemId:"b",type:"series",title:"B"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    ready=m.searchHint.text
    m.zone="searchGrid":m.searchGrid.itemFocused=1:onSearchFocus():onSearchFocus()
    print FormatJson({ready:ready,hint:m.searchHint.text,requests:m.requests.Count(),cursor:m.requests[1].params.cursor})
''')
        self.assertEqual(actual, dict(ready='All titles · 2 results', hint='All titles · 2 results · Loading more…', requests=2, cursor='c1'))

    def test_old_reply_cannot_render_during_new_query_debounce(self):
        actual = self.scene('''
    onSearchTimer()
    old=m.requests[0].token
    m.keyboard.text="Blade Runner"
    onSearchText()
    SearchResult("search_results",{ok:true},{items:[]},old)
    print FormatJson({hint:m.searchHint.text,requests:m.requests.Count(),count:m.searchGrid.content.getChildCount()})
''')
        self.assertEqual(actual, dict(hint='All titles · Searching…', requests=1, count=0))

    def test_clear_removes_results_and_returns_focus_before_late_reply(self):
        actual = self.scene('''
    onSearchTimer()
    old=m.requests[0].token
    m.searchGrid.content.appendChild(CreateObject("roSGNode","ContentNode"))
    m.zone="searchGrid":m.keyboard.text=""
    onSearchText()
    SearchResult("search_results",{ok:false},{},old)
    print FormatJson({hint:m.searchHint.text,count:m.searchGrid.content.getChildCount(),zone:m.zone,timer:m.searchTimer.control,requests:m.requests.Count()})
''')
        self.assertEqual(actual, dict(hint='All titles · Search titles. Options filters and people.',
                                     count=0, zone='keyboard', timer='stop', requests=1))

    def test_failed_current_query_can_retry_with_options_and_fresh_ownership(self):
        actual = self.scene('''
    onSearchTimer()
    old=m.requests[0].token
    SearchResult("search_results",{ok:false},{},old)
    hint=m.searchHint.text
    handled=SearchKey("options")
    SearchResult("search_results",{ok:false},{},old)
    print FormatJson({hint:hint,handled:handled,requests:m.requests,freshHint:m.searchHint.text,zone:m.zone})
''')
        self.assertEqual(actual['hint'], 'All titles · Search failed. Press Options to retry.')
        self.assertTrue(actual['handled'])
        self.assertEqual([r['action'] for r in actual['requests']], ['catalog_query', 'catalog_query'])
        self.assertEqual(actual['requests'][1]['params'], dict(query='Arrival', limit=36))
        self.assertGreater(actual['requests'][1]['token'], actual['requests'][0]['token'])
        self.assertEqual(actual['freshHint'], 'All titles · Searching…')
        self.assertEqual(actual['zone'], 'keyboard')

    def test_old_error_cannot_replace_new_titles_or_offer_retry(self):
        actual = self.scene('''
    onSearchTimer():old=m.requests[0].token
    m.keyboard.text="Blade Runner":onSearchText():onSearchTimer()
    current=m.requests[1].token
    SearchResult("search_results",{ok:true},{items:[{type:"movie",title:"Blade Runner"}]},current)
    SearchResult("search_results",{ok:false},{},old)
    TestSearchPeople()
    print FormatJson({hint:m.searchHint.text,title:m.searchGrid.content.getChild(0).title,action:m.requests[2].action,query:m.requests[2].params.query})
''')
        self.assertEqual(actual, dict(hint='All titles · 1 result', title='Blade Runner', action='people', query='Blade Runner'))

    def test_people_reply_and_error_are_retired_before_new_debounce(self):
        actual = self.scene('''
    onSearchTimer():TestSearchPeople():old=m.requests[1].token
    m.keyboard.text="Blade Runner":onSearchText()
    BrowseResult("browse_people",{ok:true},{entries:[{id:"old",title:"Old person"}]},old)
    BrowseResult("browse_people",{ok:false},{},old)
    print FormatJson({labels:m.peopleLabels,toasts:m.toasts,hint:m.searchHint.text})
''')
        self.assertEqual(actual, dict(labels=[], toasts=[], hint='All titles · Searching…'))

    def test_clear_retires_people_and_options_after_edit_uses_current_text(self):
        actual = self.scene('''
    onSearchTimer():TestSearchPeople():old=m.requests[1].token
    m.keyboard.text="":onSearchText()
    BrowseResult("browse_people",{ok:true},{entries:[{id:"old",title:"Old person"}]},old)
    cleared=m.peopleLabels.Count()
    m.keyboard.text="New person":onSearchText():TestSearchPeople()
    current=m.requests[2].token
    BrowseResult("browse_people",{ok:true},{entries:[{id:"new",title:"New person"}]},current)
    print FormatJson({cleared:cleared,labels:m.peopleLabels,query:m.requests[2].params.query})
''')
        self.assertEqual(actual, dict(cleared=0, labels=['New person'], query='New person'))

    def test_final_row_focus_dispatches_one_exact_cursor_page_and_appends(self):
        actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"},{itemId:"b",type:"series",title:"B"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=1
    onSearchFocus():onSearchFocus()
    request=m.requests[1]
    SearchResult("search_results",{ok:true},{items:[{itemId:"b",type:"series",title:"duplicate"},{itemId:"e",type:"episode",title:"episode"},{itemId:"c",type:"movie",title:"C"}],hasMore:false},request.token)
    print FormatJson({requests:m.requests,count:m.searchGrid.content.getChildCount(),last:m.searchGrid.content.getChild(2).title,focused:m.searchGrid.itemFocused,moves:m.focusMoves})
''')
        self.assertEqual(len(actual['requests']), 2)
        self.assertEqual(actual['requests'][1]['params'], dict(query='Arrival', limit=36, cursor='c1'))
        self.assertGreater(actual['requests'][1]['token'], actual['requests'][0]['token'])
        self.assertEqual((actual['count'], actual['last'], actual['focused'], actual['moves']), (3, 'C', 1, []))

    def test_failed_page_keeps_cards_and_retries_same_cursor_with_fresh_token(self):
        actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
    old=m.requests[1].token
    SearchResult("search_results",{ok:false},{},old)
    onSearchFocus():onSearchFocus()
    failed={count:m.searchGrid.content.getChildCount(),requests:m.requests.Count(),hint:m.searchHint.text}
    SearchKey("options")
    SearchResult("search_results",{ok:false},{},old)
    hint=m.searchHint.text
    SearchResult("search_results",{ok:true},{items:[{itemId:"b",type:"movie",title:"B"}],hasMore:false},m.requests[2].token)
    print FormatJson({failed:failed,requests:m.requests,count:m.searchGrid.content.getChildCount(),zone:m.zone,moves:m.focusMoves,hint:hint})
''')
        self.assertEqual(actual['failed'], dict(count=1, requests=2, hint='All titles · Search failed. Press Options to retry.'))
        self.assertEqual(actual['requests'][1]['params'], actual['requests'][2]['params'])
        self.assertGreater(actual['requests'][2]['token'], actual['requests'][1]['token'])
        self.assertEqual((actual['count'], actual['zone'], actual['moves'], actual['hint']), (2, 'searchGrid', [], 'All titles · 1 result · Loading more…'))

    def test_scope_changes_retire_page_replies_and_block_dispatch(self):
        changes = ['m.sourceId="s2"', 'm.profileId="p2"', 'm.generation=2',
                   'm.provider="plex"']
        for change in changes:
            with self.subTest(change=change):
                actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
''' + change + '''
    onSearchFocus()
    SearchResult("search_results",{ok:true},{items:[{itemId:"b",type:"movie",title:"B"}],nextCursor:"c2",hasMore:true},m.requests[1].token)
    SearchResult("search_results",{ok:false},{},m.requests[1].token)
    print FormatJson({requests:m.requests.Count(),count:m.searchGrid.content.getChildCount(),hint:m.searchHint.text,moves:m.focusMoves})
''')
                self.assertEqual(actual, dict(requests=2, count=1, hint='All titles · 1 result · Loading more…', moves=[]))

    def test_grid_focus_is_required_and_trimmed_query_is_frozen(self):
        actual = self.scene('''
    m.keyboard.text="  Arrival  ":onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.searchGrid.itemFocused=0:onSearchFocus()
    keyboardRequests=m.requests.Count()
    m.zone="searchGrid":onSearchFocus()
    print FormatJson({keyboardRequests:keyboardRequests,requests:m.requests})
''')
        self.assertEqual(actual['keyboardRequests'], 1)
        self.assertEqual(actual['requests'][1]['params'], dict(query='Arrival', limit=36, cursor='c1'))

    def test_empty_and_duplicate_pages_continue_but_stop_at_three_successes(self):
        actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"e",type:"episode",title:"hidden"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    SearchResult("search_results",{ok:true},{items:[],nextCursor:"c2",hasMore:true},m.requests[1].token)
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c3",hasMore:true},m.requests[2].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
    print FormatJson({requests:m.requests,count:m.searchGrid.content.getChildCount(),hint:m.searchHint.text})
''')
        self.assertEqual([r['params'].get('cursor') for r in actual['requests']], [None, 'c1', 'c2'])
        self.assertEqual((actual['count'], actual['hint']), (1, 'All titles · 1 result · Refine your search for more.'))

    def test_cursor_end_and_cycles_stop_without_more_requests(self):
        for terminal in ['{hasMore:false,nextCursor:"c2"}', '{hasMore:true}',
                         '{hasMore:true,nextCursor:""}', '{hasMore:true,nextCursor:"c1"}']:
            with self.subTest(terminal=terminal):
                actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[],hasMore:true,nextCursor:"c1"},m.requests[0].token)
    data=''' + terminal + '''
    data.items=[]
    SearchResult("search_results",{ok:true},data,m.requests[1].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
    print FormatJson({requests:m.requests.Count(),hint:m.searchHint.text})
''')
                self.assertEqual(actual, dict(requests=2, hint='All titles · No matches.'))

    def test_plex_results_remain_single_page(self):
        actual = self.scene('''
    m.provider="plex":onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[],hasMore:true,nextCursor:"c1"},m.requests[0].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
    print FormatJson({requests:m.requests})
''')
        self.assertEqual(len(actual['requests']), 1)
        self.assertEqual(actual['requests'][0]['action'], 'search')

    def test_people_request_and_modal_pause_paging_until_focus_returns(self):
        actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:TestSearchPeople()
    onSearchFocus():pending=m.requests.Count()
    BrowseResult("browse_people",{ok:true},{entries:[{id:"person",title:"Person"}]},m.requests[1].token)
    onSearchFocus():modal=m.requests.Count()
    m.top.dialog.close=true
    onSearchFocus()
    print FormatJson({pending:pending,modal:modal,requests:m.requests,zone:m.zone,moves:m.focusMoves})
''')
        self.assertEqual((actual['pending'], actual['modal']), (2, 2))
        self.assertEqual(actual['requests'][2]['params'], dict(query='Arrival', limit=36, cursor='c1'))
        self.assertEqual((actual['zone'], actual['moves']), ('searchGrid', []))

    def test_three_successful_pages_hold_at_108_cards(self):
        actual = self.scene('''
    onSearchTimer()
    for page=0 to 2
        items=[]
        for index=0 to 39
            id=(page*40+index).ToStr()
            items.Push({itemId:id,type:"movie",title:id})
        end for
        SearchResult("search_results",{ok:true},{items:items,nextCursor:(page+1).ToStr(),hasMore:true},m.requests[page].token)
        m.zone="searchGrid":m.searchGrid.itemFocused=m.searchGrid.content.getChildCount()-1
        onSearchFocus()
    end for
    print FormatJson({requests:m.requests.Count(),count:m.searchGrid.content.getChildCount(),first:m.searchGrid.content.getChild(0).title,last:m.searchGrid.content.getChild(107).title,hint:m.searchHint.text})
''')
        self.assertEqual(actual, dict(requests=3, count=108, first='0', last='115', hint='All titles · 108 results · Refine your search for more.'))

    def test_duplicate_only_page_advances_to_next_cursor_without_new_focus_event(self):
        actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"duplicate"}],nextCursor:"c2",hasMore:true},m.requests[1].token)
    SearchResult("search_results",{ok:true},{items:[{itemId:"b",type:"movie",title:"B"}],nextCursor:"c3",hasMore:true},m.requests[2].token)
    onSearchFocus()
    print FormatJson({requests:m.requests.Count(),count:m.searchGrid.content.getChildCount(),first:m.searchGrid.content.getChild(0).title,last:m.searchGrid.content.getChild(1).title,moves:m.focusMoves,hint:m.searchHint.text})
''')
        self.assertEqual(actual, dict(requests=3, count=2, first='A', last='B', moves=[], hint='All titles · 2 results · Refine your search for more.'))

    def test_people_failure_and_empty_reply_resume_cursor_without_focus_move(self):
        for response in ['{ok:false}', '{ok:true}']:
            with self.subTest(response=response):
                actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:TestSearchPeople()
    BrowseResult("browse_people",''' + response + ''',{entries:[]},m.requests[1].token)
    onSearchFocus()
    print FormatJson({requests:m.requests,moves:m.focusMoves})
''')
                self.assertEqual(actual['requests'][2]['params'], dict(query='Arrival', limit=36, cursor='c1'))
                self.assertEqual(actual['moves'], [])

    def test_same_owner_reply_while_away_preserves_cursor_and_returns_without_stuck_loading(self):
        for leave in ['m.zone="nav"', 'm.view="detail":m.zone="detailButtons"']:
            with self.subTest(leave=leave):
                actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.zone="searchGrid":m.searchGrid.itemFocused=0:onSearchFocus()
''' + leave + '''
    SearchResult("search_results",{ok:true},{items:[{itemId:"b",type:"movie",title:"B"}],nextCursor:"c2",hasMore:true},m.requests[1].token)
    onSearchFocus()
    away={count:m.searchGrid.content.getChildCount(),requests:m.requests.Count(),loading:m.searchLoading,zone:m.zone}
    m.view="search":m.zone="searchGrid":onSearchFocus()
    print FormatJson({away:away,requests:m.requests,moves:m.focusMoves})
''')
                self.assertEqual(actual['away']['count'], 2)
                self.assertEqual(actual['away']['requests'], 2)
                self.assertFalse(actual['away']['loading'])
                self.assertEqual(actual['requests'][2]['params'], dict(query='Arrival', limit=36, cursor='c2'))
                self.assertEqual(actual['moves'], [])

    def test_matching_hidden_people_reply_unpauses_without_dialog_and_reentry_resumes(self):
        for response, leave in [(r, l) for r in ['{ok:false}', '{ok:true}']
                                for l in ['m.view="detail":m.zone="detailButtons"', 'm.zone="nav"']]:
            with self.subTest(response=response, leave=leave):
                actual = self.scene('''
    onSearchTimer():TestSearchPeople()
''' + leave + '''
    BrowseResult("browse_people",''' + response + ''',{entries:[{id:"p",title:"Person"}]},m.requests[1].token)
    hidden={pending:m.searchPeoplePending,labels:m.peopleLabels,toasts:m.toasts,requests:m.requests.Count()}
    m.view="search":SetZone("keyboard")
    print FormatJson({hidden:hidden,requests:m.requests,moves:m.focusMoves})
''', real_focus=True)
                self.assertEqual(actual['hidden'], dict(pending=False, labels=[], toasts=[], requests=2))
                self.assertEqual(actual['requests'][2]['action'], 'catalog_query')
                self.assertEqual(actual['moves'], ['keyboard'])

    def test_debounce_while_in_nav_resumes_initial_request_on_real_reentry(self):
        actual = self.scene('''
    onSearchText():SetZone("nav"):onSearchTimer()
    before=m.requests.Count()
    SetZone("keyboard")
    print FormatJson({before:before,requests:m.requests})
''', real_focus=True)
        self.assertEqual(actual['before'], 0)
        self.assertEqual(actual['requests'][0]['params'], dict(query='Arrival', limit=36))

    def test_unchanged_grid_reentry_resumes_eligible_cursor(self):
        actual = self.scene('''
    onSearchTimer()
    SearchResult("search_results",{ok:true},{items:[{itemId:"a",type:"movie",title:"A"}],nextCursor:"c1",hasMore:true},m.requests[0].token)
    m.searchGrid.itemFocused=0:SetZone("nav"):SetZone("searchGrid")
    print FormatJson({requests:m.requests,moves:m.focusMoves})
''', real_focus=True)
        self.assertEqual(actual['requests'][1]['params'], dict(query='Arrival', limit=36, cursor='c1'))
        self.assertEqual(actual['moves'], ['nav', 'searchGrid'])

    def test_people_dialog_dismissal_hook_resumes_cancelled_initial_request(self):
        actual = self.scene('''
    onSearchTimer():TestSearchPeople()
    BrowseResult("browse_people",{ok:true},{entries:[{id:"p",title:"Person"}]},m.requests[1].token)
    before=m.requests.Count()
    m.top.dialog.wasClosed=true
    onSearchDialogClosed()
    print FormatJson({before:before,requests:m.requests,moves:m.focusMoves})
''')
        self.assertEqual(actual['before'], 2)
        self.assertEqual(actual['requests'][2]['params'], dict(query='Arrival', limit=36))
        self.assertEqual(actual['moves'], [])

    def test_people_error_before_debounce_resumes_initial_search_once(self):
        actual = self.scene('''
    onSearchText():TestSearchPeople()
    BrowseResult("browse_people",{ok:false},{},m.requests[0].token)
    print FormatJson({requests:m.requests,timer:m.searchTimer.control,moves:m.focusMoves})
''')
        self.assertEqual([r['action'] for r in actual['requests']], ['people', 'catalog_query'])
        self.assertEqual(actual['requests'][1]['params'], dict(query='Arrival', limit=36))
        self.assertEqual(actual['timer'], 'stop')
        self.assertEqual(actual['moves'], [])

    def test_real_people_selection_keeps_person_request_owned_across_dialog_close(self):
        actual = self.scene('''
    onSearchTimer():TestSearchPeople()
    BrowseResult("browse_people",{ok:true},{entries:[{id:"p",title:"Person"}]},m.requests[1].token)
    selected=m.top.dialog
    selected.buttonSelected=0
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onBrowsePeople(event)
    personRequest=m.requests[2]
    onSearchDialogClosed()
    afterClose=m.requests.Count()
    BrowseResult("browse_person",{ok:true},{person:{id:"p",name:"Person name",bio:"Biography"}},personRequest.token)
    print FormatJson({afterClose:afterClose,requests:m.requests,title:m.top.dialog.title,message:m.top.dialog.message,moves:m.focusMoves})
''', real_dialog=True)
        self.assertEqual(actual['afterClose'], 3)
        self.assertEqual(actual['requests'][2]['action'], 'person')
        self.assertEqual((actual['title'], actual['message'], actual['moves']), ('Person name', 'Biography', []))

    def test_hidden_selected_person_settlement_unpauses_without_cross_scope_ui(self):
        for response, scope in [('{ok:false}', ''), ('{ok:true}', ''),
                                ('{ok:false}', 'm.profileId="p2"')]:
            with self.subTest(response=response, scope=scope):
                actual = self.scene('''
    onSearchTimer():TestSearchPeople()
    BrowseResult("browse_people",{ok:true},{entries:[{id:"p",title:"Person"}]},m.requests[1].token)
    selected=m.top.dialog:selected.buttonSelected=0
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onBrowsePeople(event)
    onSearchDialogClosed()
    m.view="detail":m.zone="detailButtons"
''' + scope + '''
    BrowseResult("browse_person",''' + response + ''',{person:{name:"Hidden",bio:"Hidden"}},m.requests[2].token)
    settled=m.searchPersonPendingToken=invalid
    m.view="search":SetZone("keyboard")
    print FormatJson({settled:settled,requests:m.requests.Count(),toasts:m.toasts,title:m.top.dialog.title})
''', real_focus=True, real_dialog=True)
                self.assertTrue(actual['settled'])
                self.assertEqual(actual['requests'], 3 if scope else 4)
                self.assertEqual(actual['toasts'], [])
                self.assertEqual(actual['title'], 'People')

    def test_detail_person_supersedes_search_person_pause_in_either_reply_order(self):
        for order in [(0, 1), (1, 0)]:
            with self.subTest(order=order):
                actual = self.scene('''
    onSearchTimer():TestSearchPeople()
    BrowseResult("browse_people",{ok:true},{entries:[{id:"a",title:"A"}]},m.requests[1].token)
    selected=m.top.dialog:selected.buttonSelected=0
    event={node:selected,getRoSGNode:function() as Object
        return m.node
    end function}
    onBrowsePeople(event):onSearchDialogClosed()
    tokens=[m.requests[2].token]
    m.view="detail":m.zone="detailButtons":m.detailToken=7
    BrowsePerson("b"):tokens.Push(m.requests[3].token)
''' + ''.join('    BrowseResult("browse_person",{ok:false},{},tokens[%d])\n' % index for index in order) + '''
    pending=m.searchPersonPendingToken<>invalid
    m.view="search":SetZone("keyboard")
    print FormatJson({pending:pending,requests:m.requests,moves:m.focusMoves})
''', real_focus=True, real_dialog=True)
                self.assertFalse(actual['pending'])
                self.assertEqual(actual['requests'][4]['action'], 'catalog_query')
                self.assertEqual(actual['requests'][4]['params'], dict(query='Arrival', limit=36))
                self.assertEqual(actual['moves'], ['keyboard'])
