"""Shipping streaming rail: exact native ownership and asynchronous visit boundaries."""
import json
import re
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class SiloUIStreamingTests(unittest.TestCase):
    def scene(self, body):
        with tempfile.TemporaryDirectory() as directory:
            helper=Path(directory)/'boundary.brs'
            helper.write_text(re.search(r'function PopView\(.*?\nend function',(ROOT/'components/SiloUIScene.brs').read_text(),re.S)[0] + '\n' + '''
sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic)
 m.requests.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
sub ShowView(view as String)
 m.view=view
end sub
sub SetZone(zone as String)
 m.zone=zone
end sub
sub BuildButtons(group as Object, name as String, labels as Object)
 m.pillGroups[name]={index:0}
end sub
function ItemNode(item as Object, landscape=false as Boolean) as Object
 node=CreateObject("roSGNode","ContentNode")
 node.addFields({item:item})
 return node
end function
sub DetailOpen(item as Object)
 m.opened=item
end sub
sub LibraryOpenFormat(formatFilter as String)
 m.openedFormat=formatFilter
end sub
sub Toast(message as String)
 m.toast=message
end sub
sub DetailPhotosClear()
end sub
sub PlayerDiscardPrebuffer()
end sub
sub PlayerCloseTracks()
end sub
sub PlexClearImages()
end sub
''')
            home=Path(directory)/'home.brs'
            source=(ROOT/'components/SiloUIHome.brs').read_text()
            source=re.sub(r'sub HomeSetRows\(.*?\nend sub','sub HomeSetRows(rows as Object)\n m.homeRows=StreamingHomeRows(rows)\nend sub',source,count=1,flags=re.S)
            source=re.sub(r'sub HomeCacheRetire\(.*?\nend sub','sub HomeCacheRetire()\n m.cacheRetired=true\nend sub',source,count=1,flags=re.S)
            home.write_text(source)
            out=run_brightscript([ROOT/'components/SiloUITrickplay.brs',ROOT/'components/SiloUIStreaming.brs',ROOT/'components/SiloUIRobustness.brs',ROOT/'components/SiloUIOnboarding.brs',home,ROOT/'source/core/SiloUIHomePolicy.brs',ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/adapters/MetadataAdapter.brs',ROOT/'source/core/MetadataUiPolicy.brs',ROOT/'source/core/ServicePolicy.brs',helper],'''
 m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p1":m.generation=2:m.view="home":m.zone="rows"
 m.requests=[]:m.history=[]:m.pillGroups={}:m.rows={rowItemFocused:[2,3]}
 m.streamingGrid={content:CreateObject("roSGNode","ContentNode"),itemSelected:0}
 m.streamingTitle={}:m.streamingStatus={}:m.streamingButtons={}
 m.homeRows=[{items:[{provider:"silo",sourceId:"silo:synthetic",itemId:"native-a",type:"movie",title:"Owned film",tmdbId:"101"}]}]
''' + body,root=Path(directory))
            return json.loads(out.splitlines()[-1])

    def test_native_owned_catalog_selection_never_opens_public_seed(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows)
 StreamingOpen("netflix")
 cached=m.requests[0]
 StreamingResult({ok:true},{rows:[]},cached.extra)
 live=m.requests[1]
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"Public film",tmdbId:"101"},{provider:"metadata",type:"movie",title:"Unowned",tmdbId:"999"}]},live.extra)
 onStreamingSelect()
 print FormatJson({id:m.opened.itemId,provider:m.opened.provider,count:m.streamingGrid.content.getChildCount(),status:m.streamingStatus.text,mode:live.params.mode,home:m.streamingHomeFocus})
''')
        self.assertEqual(actual['id'],'native-a')
        self.assertEqual(actual['provider'],'silo')
        self.assertEqual(actual['count'],1)
        self.assertIn('Partial',actual['status'])
        self.assertEqual(actual['mode'],'live')
        self.assertEqual(actual['home'],[2,3])

    def test_curated_home_shortcut_is_lazy_and_restores_focus(self):
        actual=self.scene('''
 rows=StreamingHomeRows([{rowId:"recent",sectionType:"recent",items:[{itemId:"a"}]}])
 before=m.requests.Count()
 m.rows.rowItemFocused=[2,0]
 m.rows.content=CreateObject("roSGNode","ContentNode")
 for each values in rows
     row=m.rows.content.createChild("ContentNode")
     for each item in values.items
         row.appendChild(ItemNode(item))
     end for
 end for
 onHomeSelect()
 action=m.requests[0].action
 PopView()
 print FormatJson({before:before,rows:rows.Count(),kind:rows[2].sectionType,action:action,mode:m.requests[0].params.mode,focus:m.rows.jumpToRowItem,hero:SiloUIHomeHeroRow(rows)})
''')
        self.assertEqual(actual,dict(before=0,rows=4,kind='curated',action='home_rows',mode='cache_only',focus=[2,0],hero=0))

    def test_video_format_home_shortcut_is_local_and_selects_catalog_filter(self):
        actual=self.scene('''
 rows=StreamingHomeRows([{rowId:"recent",sectionType:"recent",items:[{itemId:"a"}]}])
 m.rows.rowItemFocused=[3,2]
 m.rows.content=CreateObject("roSGNode","ContentNode")
 for each values in rows
     row=m.rows.content.createChild("ContentNode")
     for each item in values.items
         row.appendChild(ItemNode(item))
     end for
 end for
 onHomeSelect()
 print FormatJson({count:rows.Count(),section:rows[3].sectionType,filter:m.openedFormat,requests:m.requests.Count(),hero:SiloUIHomeHeroRow(rows)})
''')
        self.assertEqual(actual,dict(count=4,section='formats',filter='4k_hdr',requests=0,hero=0))

    def test_curated_refresh_ack_keeps_groups_and_fetches_current_snapshot(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows):StreamingOpen("curated")
 StreamingResult({ok:true},{rows:[{id:"picks",title:"Picks",items:[{provider:"metadata",type:"movie",title:"Public",tmdbId:"101"}]}]},m.requests[0].extra)
 StreamingRequest("refresh")
 current=m.requests[m.requests.Count()-1]
 StreamingResult({ok:true},{refreshQueued:true},current.extra)
 print FormatJson({groups:m.streamingGroups.Count(),mode:m.requests[m.requests.Count()-1].params.mode,busy:m.streamingBusy,status:m.streamingStatus.text})
''')
        self.assertEqual(actual['groups'],1)
        self.assertEqual(actual['mode'],'live')
        self.assertTrue(actual['busy'])
        self.assertIn('background',actual['status'])

    def test_curated_groups_keep_editorial_order_and_native_identity(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows)
 StreamingOpen("curated")
 first=m.requests[0]
 StreamingResult({ok:true},{rows:[
     {id:"first",title:"Director picks",items:[{provider:"metadata",type:"movie",title:"Public A",tmdbId:"101"},{provider:"metadata",type:"movie",title:"Unowned",tmdbId:"999"}]},
     {id:"second",title:"Award winners",items:[{provider:"metadata",type:"movie",title:"Public B",tmdbId:"202"}]}
 ]},first.extra)
 m.streamingGrid.itemSelected=0
 onStreamingSelect()
 title1=m.streamingTitle.text
 id1=m.opened.itemId
 second=m.requests[1]
 StreamingResult({ok:false},{},second.extra)
 print FormatJson({action:first.action,live:second.params.mode,title1:title1,id1:id1,groups:m.streamingGroups.Count(),status:m.streamingStatus.text})
''')
        self.assertEqual(actual['action'],'home_rows')
        self.assertEqual(actual['live'],'live')
        self.assertEqual(actual['id1'],'native-a')
        self.assertIn('Director picks',actual['title1'])
        self.assertEqual(actual['groups'],1)
        self.assertIn('unavailable',actual['status'])

    def test_curated_can_page_grouped_owned_titles_without_new_request(self):
        actual=self.scene('''
 m.homeRows[0].items.Push({provider:"silo",sourceId:m.sourceId,itemId:"native-b",type:"movie",title:"Owned B",tmdbId:"202"})
 StreamingRememberRows(m.homeRows):StreamingOpen("curated")
 StreamingResult({ok:true},{rows:[
     {id:"a",title:"Director picks",items:[{provider:"metadata",type:"movie",title:"Public A",tmdbId:"101"}]},
     {id:"b",title:"Award winners",items:[{provider:"metadata",type:"movie",title:"Public B",tmdbId:"202"}]}
 ]},m.requests[0].extra)
 before=m.streamingTitle.text
 m.zone="streamingButtons":m.pillGroups.streamingButtons.index=1
 StreamingKey("OK")
 after=m.streamingTitle.text
 m.streamingGrid.itemSelected=0:onStreamingSelect()
 print FormatJson({before:before,after:after,id:m.opened.itemId,groups:m.streamingGroups.Count(),requests:m.requests.Count()})
''')
        self.assertIn('Director picks',actual['before'])
        self.assertIn('Award winners',actual['after'])
        self.assertEqual(actual['id'],'native-b')
        self.assertEqual(actual['groups'],2)
        self.assertEqual(actual['requests'],2)

    def test_curated_stale_response_and_pruned_back_request_are_fenced(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows):StreamingOpen("curated")
 stale=m.requests[0].extra
 m.history.Push({view:"streaming",zone:"streamingGrid"}):m.view="search"
 m.top={memoryPressure:90}:m.backdrop={}:m.backdropOld={}:m.heroLogo={}:m.grid={}:m.searchGrid={}
 SiloUIMemoryPressure():PopView()
 fresh=m.requests[1].extra
 StreamingResult({ok:true},{rows:[{id:"old",title:"Stale",items:[{provider:"metadata",type:"movie",title:"Old",tmdbId:"101"}]}]},stale)
 print FormatJson({action:m.requests[1].action,mode:m.requests[1].params.mode,fenced:m.streamingGroups.Count()=0 and m.streamingGrid.content.getChildCount()=0,newSerial:fresh.serial>stale.serial,zone:m.zone})
''')
        self.assertEqual(actual,dict(action='home_rows',mode='cache_only',fenced=True,newSerial=True,zone='streamingButtons'))

    def test_shipping_home_select_routes_service_and_restores_focus(self):
        actual=self.scene('''
 m.rows.rowItemFocused=[0,1]
 m.rows.content=CreateObject("roSGNode","ContentNode")
 row=m.rows.content.createChild("ContentNode")
 row.appendChild(ItemNode({title:"Film",itemId:"a"}))
 row.appendChild(ItemNode({title:"Netflix",type:"service",serviceId:"netflix"}))
 onHomeSelect()
 opened=m.view
 prior=m.history[0]
 PopView()
 print FormatJson({view:opened,action:m.requests[0].action,focus:m.rows.jumpToRowItem,history:prior})
''')
        self.assertEqual(actual,dict(view='streaming',action='service_catalog',focus=[0,1],history=dict(view='home',zone='rows')))

    def test_stale_visit_profile_and_generation_cannot_publish(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows)
 StreamingOpen("netflix"):old=m.requests[0].extra
 StreamingOpen("hulu")
 before=m.streamingStatus.text
 StreamingResult({ok:false},{},old)
 afterVisit=m.streamingStatus.text
 current=m.requests[1].extra
 m.profileId="p2"
 StreamingResult({ok:false},{},current)
 afterProfile=m.streamingStatus.text
 m.profileId="p1":m.generation=3
 StreamingResult({ok:false},{},current)
 print FormatJson([before,afterVisit,afterProfile,m.streamingStatus.text,m.requests.Count()])
''')
        self.assertEqual(actual[:4],[actual[0]]*4)
        self.assertEqual(actual[4],2)

    def test_failure_retry_and_unsupported_provider_are_actionable(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows)
 StreamingOpen("netflix")
 StreamingResult({ok:false},{},m.requests[0].extra)
 StreamingResult({ok:false},{},m.requests[1].extra)
 error=m.streamingStatus.text
 StreamingKey("OK")
 retry=m.requests[2].params.mode
 StreamingOpen("kanopy")
 print FormatJson({error:error,retry:retry,unsupported:m.streamingStatus.text,count:m.requests.Count(),busy:m.streamingBusy})
''')
        self.assertIn('Retry',actual['error'])
        self.assertEqual(actual['retry'],'refresh')
        self.assertIn('unavailable',actual['unsupported'])
        self.assertEqual(actual['count'],3)
        self.assertFalse(actual['busy'])

    def test_public_and_unknown_identities_cannot_open_detail_or_fetch(self):
        actual=self.scene('''
 StreamingOpen("unknown")
 initial=m.requests.Count()
 StreamingOpen("netflix")
 m.streamingGrid.content.appendChild(ItemNode({provider:"metadata",sourceId:m.sourceId,itemId:"global-id",title:"Public",type:"movie",tmdbId:"101"}))
 onStreamingSelect()
 print FormatJson({initial:initial,opened:m.opened})
''')
        self.assertEqual(actual,dict(initial=0,opened=None))

    def test_empty_and_cross_profile_inventory_are_never_called_complete(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows)
 m.profileId="p2"
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"Public",tmdbId:"101"}]},m.requests[0].extra)
 print FormatJson({count:m.streamingGrid.content.getChildCount(),status:m.streamingStatus.text})
''')
        self.assertEqual(actual['count'],0)
        self.assertIn('full library has not been checked',actual['status'])

    def test_rail_is_local_and_does_not_replace_media_hero(self):
        actual=self.scene('''
 rows=StreamingHomeRows([{sectionType:"recent",title:"Recent",items:[{itemId:"a"}]}])
 rows=StreamingHomeRows(rows)
 empty=StreamingHomeRows([])
 print FormatJson({rows:rows.Count(),services:rows[1].items.Count(),first:rows[1].items[0].serviceId,last:rows[1].items[11].serviceId,hero:SiloUIHomeHeroRow(rows),emptyHero:SiloUIHomeHeroRow(empty),requests:m.requests.Count()})
''')
        self.assertEqual(actual,dict(rows=4,services=12,first='netflix',last='kanopy',hero=0,emptyHero=-1,requests=0))

    def test_return_from_covered_hub_retires_pending_live_request(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows)
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"Owned",tmdbId:"101"}]},m.requests[0].extra)
 late=m.requests[1].extra
 m.history.Push({view:"streaming",zone:"streamingGrid"})
 m.view="detail"
 StreamingResult({ok:false},{},late)
 PopView()
 before=m.streamingStatus.text
 StreamingResult({ok:false},{},late)
 print FormatJson({view:m.view,zone:m.zone,busy:m.streamingBusy,count:m.streamingGrid.content.getChildCount(),before:before,after:m.streamingStatus.text})
''')
        self.assertEqual(actual['view'],'streaming')
        self.assertEqual(actual['zone'],'streamingGrid')
        self.assertFalse(actual['busy'])
        self.assertEqual(actual['count'],1)
        self.assertEqual(actual['before'],actual['after'])

    def test_hydration_preserves_service_focus_after_media_row_is_added(self):
        actual=self.scene('''
 m.homeRendered=true:m.heroItem=invalid
 m.homeRows=StreamingHomeRows([{rowId:"recent",items:[{itemId:"a"}]}])
 m.rows.rowItemFocused=[1,4]
 HomeHydrationRender([{rowId:"recent",items:[{itemId:"a"}]},{rowId:"new",items:[{itemId:"b"}]}])
 serviceFocus=m.rows.jumpToRowItem
 m.rows.rowItemFocused=[0,0]
 HomeHydrationRender([{rowId:"new",items:[{itemId:"b"}]},{rowId:"recent",items:[{itemId:"a"}]}])
 print FormatJson({service:serviceFocus,media:m.rows.jumpToRowItem})
''')
        self.assertEqual(actual,dict(service=[2,4],media=[1,0]))

    def test_memory_prunes_hidden_hub_and_back_reconstructs_with_fresh_request(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows)
 StreamingOpen("netflix")
 late=m.requests[0].extra
 m.history.Push({view:"streaming",zone:"streamingGrid"}):m.view="detail"
 m.top={memoryPressure:90}:m.backdrop={}:m.backdropOld={}:m.heroLogo={}:m.grid={}:m.searchGrid={}
 SiloUIMemoryPressure()
 pruned=m.streamingGrid.content=invalid and m.streamingIndex=invalid and m.streamingBusy=false
 PopView()
 fresh=m.requests[1].extra
 StreamingResult({ok:false},{},late)
 print FormatJson({pruned:pruned,view:m.view,zone:m.zone,mode:m.requests[1].params.mode,empty:m.streamingGrid.content.getChildCount(),newSerial:fresh.serial>late.serial,status:m.streamingStatus.text})
''')
        self.assertTrue(actual['pruned'])
        self.assertEqual(actual['view'],'streaming')
        self.assertEqual(actual['zone'],'streamingButtons')
        self.assertEqual(actual['mode'],'cache_only')
        self.assertEqual(actual['empty'],0)
        self.assertTrue(actual['newSerial'])
        self.assertIn('Loading',actual['status'])

    def test_scope_reset_drops_all_streaming_ownership_content_and_pending_authority(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows):StreamingOpen("netflix")
 late=m.requests[0].extra
 m.keyboard={text:""}:m.searchTimer={}
 ObResetScope()
 m.view="streaming"
 StreamingResult({ok:true},{items:[]},late)
 print FormatJson({cacheRetired:m.cacheRetired,index:m.streamingIndex,content:m.streamingGrid.content,owner:m.streamingOwner,service:m.streamingService,busy:m.streamingBusy,focus:m.streamingHomeFocus,requests:m.requests.Count()})
''')
        self.assertEqual(actual,dict(cacheRetired=True,index=None,content=None,owner=None,service=None,busy=False,focus=None,requests=1))

    def test_pruned_unsupported_provider_returns_to_unavailable_actions(self):
        actual=self.scene('''
 StreamingOpen("kanopy")
 m.history.Push({view:"streaming",zone:"streamingButtons"}):m.view="search"
 m.top={memoryPressure:90}:m.backdrop={}:m.backdropOld={}:m.heroLogo={}:m.grid={}:m.searchGrid={}
 SiloUIMemoryPressure()
 PopView()
 print FormatJson({status:m.streamingStatus.text,requests:m.requests.Count(),busy:m.streamingBusy,zone:m.zone})
''')
        self.assertIn('unavailable',actual['status'])
        self.assertNotIn('Loading',actual['status'])
        self.assertEqual(actual['requests'],0)
        self.assertFalse(actual['busy'])
        self.assertEqual(actual['zone'],'streamingButtons')
