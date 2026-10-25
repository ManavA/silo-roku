"""Accepted native Detail responses contribute exact service ownership evidence."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class SiloUIStreamingDetailTests(unittest.TestCase):
    def scene(self, body):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'detail.brs'
            source = (ROOT / 'components/SiloUIDetail.brs').read_text()
            replacements = {
                'DetailRender': 'sub DetailRender(item as Object)\n m.detailItem=item\nend sub',
                'DetailPhotosClear': 'sub DetailPhotosClear()\nend sub',
                'DetailExperimentalProbe': 'sub DetailExperimentalProbe()\nend sub',
                'DetailPhotosStart': 'sub DetailPhotosStart()\nend sub',
            }
            for name, replacement in replacements.items():
                if replacement:
                    source = re.sub(r'(?:sub|function) ' + name + r'\(.*?\nend (?:sub|function)', replacement, source, count=1, flags=re.S)
            source += '\n' + re.search(r'function PopView\(.*?\nend function', (ROOT/'components/SiloUIScene.brs').read_text(), re.S)[0]
            source += '''
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic)
 m.requests.Push({params:params,purpose:purpose,extra:extra})
end sub
sub ShowView(view as String)
 m.view=view
end sub
sub SetZone(zone as String)
 m.zone=zone
end sub
sub HomeRefreshHero()
end sub
sub PlayerDiscardPrebuffer()
end sub
sub PlayerPrebuffer(item as Object,versions as Object,markers as Dynamic,data as Object)
end sub
function ItemNode(item as Object) as Object
 node=CreateObject("roSGNode","ContentNode")
 node.addFields({item:item})
 return node
end function
sub BuildButtons(group as Object,name as String,labels as Object)
end sub
'''
            fixture.write_text(source)
            files = [fixture, ROOT/'components/SiloUIStreaming.brs'] + [ROOT/p for p in ['source/core/SiloUIFormat.brs', 'source/core/SiloUIDetailPolicy.brs', 'source/adapters/MetadataAdapter.brs', 'source/core/MetadataUiPolicy.brs', 'source/core/ServicePolicy.brs', 'source/core/SiloUIBrowsePolicy.brs']]
            files = [p for p in files if p.exists()]
            output = run_brightscript(files, '''
m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p1":m.generation=2
m.view="home":m.zone="rows":m.history=[]:m.requests=[]:m.detailVisit=0:m.pillGroups={}
m.detailRatings={visible:false,removeChildren:function(children):return invalid:end function,getChildren:function(a,b):return []:end function}
m.detailCast={}:m.detailSimilar={}:m.episodes={}
m.seasonPills=CreateObject("roSGNode","ContentNode")
m.streamingGrid={}:m.streamingTitle={}:m.streamingStatus={}:m.streamingButtons={}:m.rows={rowItemFocused:[0,0]}
native={provider:"silo",sourceId:"silo:synthetic",itemId:"native-a",type:"movie",title:"Owned",tmdbId:"101"}
seed={items:[{provider:"metadata",type:"movie",title:"Public",tmdbId:"101"}]}
DetailOpen({itemId:"native-a",type:"movie"})
''' + body, root=Path(directory))
            return json.loads(output.splitlines()[-1])

    def test_accepted_detail_survives_return_home_and_opens_exact_native_catalog(self):
        actual = self.scene('''
DetailResult("detail_item",{ok:true},{item:native},m.detailToken)
PopView()
StreamingOpen("netflix")
StreamingResult({ok:true},seed,m.requests[m.requests.Count()-1].extra)
item=invalid
if m.streamingGrid.content.getChildCount()>0 then item=m.streamingGrid.content.getChild(0).item
print FormatJson({count:m.streamingGrid.content.getChildCount(),item:item})
''')
        self.assertEqual(actual['count'], 1)
        self.assertEqual(actual['item']['itemId'], 'native-a')
        self.assertEqual(actual['item']['provider'], 'silo')

    def test_unaccepted_detail_cannot_establish_native_ownership(self):
        cases = {
            'failed': 'DetailResult("detail_item",{ok:false},{item:native},m.detailToken)',
            'stale_visit': 'DetailResult("detail_item",{ok:true},{item:native},m.detailToken-1)',
            'wrong_item': 'native.itemId="other":DetailResult("detail_item",{ok:true},{item:native},m.detailToken)',
            'wrong_source': 'native.sourceId="silo:other":DetailResult("detail_item",{ok:true},{item:native},m.detailToken)',
            'public': 'native.provider="metadata":DetailResult("detail_item",{ok:true},{item:native},m.detailToken)',
            'placeholder': 'DetailRender(native)',
            'similar': 'DetailResult("detail_similar",{ok:false},{items:[native]},m.detailToken)',
        }
        for name, action in cases.items():
            with self.subTest(name=name):
                actual = self.scene(action + '\nprint FormatJson(ServiceOwnedEntries(seed,m.streamingIndex,StreamingScope()).items.Count())')
                self.assertEqual(actual, 0)

    def test_changed_scope_cannot_repopulate_retired_index(self):
        for change in ['m.sourceId="silo:other"', 'm.profileId="p2"', 'm.generation=3', 'm.provider="plex"']:
            with self.subTest(change=change):
                actual = self.scene('''
DetailResult("detail_item",{ok:true},{item:native},m.detailToken)
StreamingRetire(true)
''' + change + '''
DetailResult("detail_item",{ok:true},{item:native},m.detailToken)
print FormatJson(m.streamingIndex)
''')
                self.assertIsNone(actual)

    def test_newer_detail_without_ids_or_ownership_retires_positive(self):
        for change in ['native.tmdbId=""', 'native.owned=false']:
            with self.subTest(change=change):
                actual = self.scene('''
DetailResult("detail_item",{ok:true},{item:native},m.detailToken)
''' + change + '''
DetailResult("detail_item",{ok:true},{item:native},m.detailToken)
print FormatJson(ServiceOwnedEntries(seed,m.streamingIndex,StreamingScope()).items.Count())
''')
                self.assertEqual(actual, 0)
