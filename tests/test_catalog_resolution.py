import json
import unittest
from tests import test_silo_adapter as silo_tests

class CatalogResolutionAdapterTests(unittest.TestCase):
    setUpClass = classmethod(silo_tests.SiloAdapterTests.setUpClass.__func__)
    tearDownClass = classmethod(silo_tests.SiloAdapterTests.tearDownClass.__func__)
    call = silo_tests.SiloAdapterTests.call
    request = silo_tests.SiloAdapterTests.request
    def test_batch_request_and_authorized_native_mapping(self):
        seeds=[{'type':'movie','tmdb_id':'999'}]
        request=self.request('catalog_resolve',{'seeds':seeds,'limit':100})
        self.assertTrue(request['ok'])
        self.assertTrue(request['url'].endswith('/api/v2/catalog/resolve'))
        self.assertEqual(json.loads(request['body']),{'seeds':seeds,'limit':100})
        result=self.call('DecodeSiloResponse','catalog_resolve',json.dumps({'matches':[{'seed':0,'item':{'content_id':'native-new','title':'Owned','type':'movie'}}],'complete':True}),{'seeds':seeds})
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['matches'][0]['item']['itemId'],'native-new')
        self.assertNotIn('tmdbId',result['data']['matches'][0]['item'])

    def test_capability_preserves_smaller_batch_limit(self):
        for maximum in [24,8]:
            result=self.call('DecodeSiloResponse','catalog_identity_capabilities',json.dumps({'state':'available','identity_resolution':True,'max_identity_batch':maximum}),{})
            self.assertEqual(result['data'],{'identityResolution':True,'maxIdentityBatch':maximum})

    def test_task_scopes_native_receipt_without_public_identity(self):
        import re
        import tempfile
        from pathlib import Path
        from tools.brightscript import run_brightscript
        root=Path(__file__).resolve().parents[1]
        task=(root/'components/ApiTask.brs').read_text()
        with tempfile.TemporaryDirectory() as directory:
            helper=Path(directory)/'task.brs'
            helper.write_text('\n'.join(re.search(r'(?ms)^function '+name+r'\(.*?^end function',task)[0] for name in ['TaskFinishSilo','TaskValue','TaskString']))
            output=run_brightscript([root/'source/adapters/SiloAdapter.brs',root/'source/core/MediaScope.brs',helper],'''
 decoded=DecodeSiloResponse("catalog_resolve",FormatJson({matches:[{seed:0,item:{content_id:"native-new",title:"Owned",type:"movie"}}],complete:true}),{seeds:[{type:"movie",tmdb_id:"999"}]})
 print FormatJson(TaskFinishSilo("catalog_resolve",decoded,{sourceId:"silo:synthetic"},1))
''',root=Path(directory))
        match=json.loads(output.splitlines()[-1])['data']['matches'][0]
        self.assertEqual(match['seed'],0)
        self.assertEqual(match['item']['sourceId'],'silo:synthetic')
        self.assertNotIn('tmdbId',match['item'])

    def test_batch_rejects_wrong_seed_type_index_conflicts_and_duplicate_ids(self):
        seeds=[{'type':'movie','tmdb_id':'999'}]
        for matches in [
            [{'seed':1,'item':{'content_id':'n','title':'Owned','type':'movie'}}],
            [{'seed':0,'item':{'content_id':'n','title':'Owned','type':'series'}}],
            [{'seed':0,'item':{'content_id':'n','title':'Owned','type':'movie','tmdb_id':'123'}}],
            [{'seed':0,'item':{'content_id':'n','title':'Owned','type':'movie'}}]*2,
        ]:
            result=self.call('DecodeSiloResponse','catalog_resolve',json.dumps({'matches':matches,'complete':True}),{'seeds':seeds})
            self.assertFalse(result['ok'])
        cap=self.call('DecodeSiloResponse','catalog_identity_capabilities',json.dumps({'state':'available'}),{})
        self.assertFalse(cap['data']['identityResolution'])

from tests import test_silo_ui_streaming as streaming_tests

class CatalogResolutionSceneTests(unittest.TestCase):
    scene = streaming_tests.SiloUIStreamingTests.scene
    def test_live_group_resolves_unobserved_native_card_without_borrowed_ids(self):
        actual=self.scene('''
 StreamingOpen("curated")
 StreamingResult({ok:true},{rows:[]},m.requests[0].extra)
 StreamingResult({ok:true},{rows:[{title:"New picks",items:[{provider:"metadata",type:"movie",tmdbId:"999",title:"Public"}]}]},m.requests[1].extra)
 cap=m.requests[2]
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:48},cap.extra)
 lookup=m.requests[3]
 StreamingIdentityResult({ok:true},{matches:[{seed:0,item:{provider:"silo",sourceId:m.sourceId,itemId:"native-new",type:"movie",title:"Owned"}}],complete:true},lookup.extra)
 onStreamingSelect()
 print FormatJson({action:lookup.action,seeds:lookup.params.seeds,id:m.opened.itemId,tmdb:m.opened.tmdbId,count:m.streamingGrid.content.getChildCount()})
''')
        self.assertEqual(actual,{'action':'catalog_resolve','seeds':[{'type':'movie','tmdb_id':'999'}],'id':'native-new','tmdb':None,'count':1})

    def test_empty_conflict_pages_continue_with_frozen_batch_and_stop_at_bound(self):
        actual=self.scene('''
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[]},m.requests[0].extra)
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"Public",tmdbId:"999"}]},m.requests[1].extra)
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:48},m.requests[2].extra)
 first=m.requests[3]
 StreamingIdentityResult({ok:true},{matches:[],complete:false,nextCursor:"a"},first.extra)
 second=m.requests[4]
 StreamingIdentityResult({ok:true},{matches:[],complete:false,nextCursor:"b"},second.extra)
 third=m.requests[5]
 StreamingIdentityResult({ok:true},{matches:[],complete:false,nextCursor:"c"},third.extra)
 print FormatJson({count:m.requests.Count(),seeds:second.params.seeds,cursor:third.params.cursor,items:m.streamingGrid.content.getChildCount(),status:m.streamingStatus.text})
''')
        self.assertEqual(actual['count'],6)
        self.assertEqual(actual['seeds'],[{'type':'movie','tmdb_id':'999'}])
        self.assertEqual(actual['cursor'],'b')
        self.assertEqual(actual['items'],0)
        self.assertIn('Partial',actual['status'])

    def test_unsupported_capability_keeps_observed_fallback_and_is_cached(self):
        actual=self.scene('''
 StreamingRememberRows(m.homeRows):StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[]},m.requests[0].extra)
 data={items:[{provider:"metadata",type:"movie",title:"Public",tmdbId:"101"}]}
 StreamingResult({ok:true},data,m.requests[1].extra)
 StreamingIdentityResult({ok:false},{},m.requests[2].extra)
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[]},m.requests[3].extra)
 StreamingResult({ok:true},data,m.requests[4].extra)
 print FormatJson({count:m.requests.Count(),items:m.streamingGrid.content.getChildCount(),status:m.streamingStatus.text})
''')
        self.assertEqual(actual['count'],5)
        self.assertEqual(actual['items'],1)
        self.assertIn('already browsed',actual['status'])

    def test_late_capability_from_previous_visit_does_not_start_lookup(self):
        actual=self.scene('''
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[]},m.requests[0].extra)
 data={items:[{provider:"metadata",type:"movie",title:"Public",tmdbId:"999"}]}
 StreamingResult({ok:true},data,m.requests[1].extra)
 stale=m.requests[2].extra
 StreamingOpen("hulu")
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:48},stale)
 print FormatJson({count:m.requests.Count(),cap:m.streamingCapability,items:m.streamingGrid.content.getChildCount()})
''')
        self.assertEqual(actual,{'count':4,'cap':None,'items':0})

    def test_wrong_mapping_or_foreign_card_cannot_publish(self):
        for match in [
            '{seed:1,item:{provider:"silo",sourceId:m.sourceId,itemId:"new",type:"movie",title:"Owned"}}',
            '{seed:0,item:{provider:"silo",sourceId:"silo:foreign",itemId:"new",type:"movie",title:"Owned"}}',
            '{seed:0,item:{provider:"silo",sourceId:m.sourceId,itemId:"new",type:"series",title:"Owned"}}',
        ]:
            actual=self.scene('''
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[]},m.requests[0].extra)
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"Public",tmdbId:"999"}]},m.requests[1].extra)
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:48},m.requests[2].extra)
 StreamingIdentityResult({ok:true},{matches:['''+match+'''],complete:true},m.requests[3].extra)
 print FormatJson({items:m.streamingGrid.content.getChildCount()})
''')
            self.assertEqual(actual['items'],0)

    def test_refresh_invalidates_inflight_receipt_before_new_seed_batch(self):
        actual=self.scene('''
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[]},m.requests[0].extra)
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"Old",tmdbId:"999"}]},m.requests[1].extra)
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:48},m.requests[2].extra)
 stale=m.requests[3].extra
 StreamingRequest("refresh")
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"New",tmdbId:"777"}]},m.requests[4].extra)
 before=m.requests.Count()
 StreamingIdentityResult({ok:true},{matches:[{seed:0,item:{sourceId:m.sourceId,itemId:"old-native",title:"Old",type:"movie"}}],complete:true},stale)
 print FormatJson({before:before,after:m.requests.Count(),items:m.streamingGrid.content.getChildCount(),seeds:m.requests[5].params.seeds})
''')
        self.assertEqual(actual,{'before':5,'after':6,'items':0,'seeds':[{'type':'movie','tmdb_id':'777'}]})


    def test_lower_batch_max_is_bounded_and_remains_explicitly_partial(self):
        actual=self.scene('''
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[]},m.requests[0].extra)
 entries=[]
 for index=1 to 30
     entries.Push({provider:"metadata",type:"movie",title:"Public",tmdbId:index.ToStr()})
 end for
 StreamingResult({ok:true},{items:entries},m.requests[1].extra)
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:24},m.requests[2].extra)
 lookup=m.requests[3]
 StreamingIdentityResult({ok:true},{matches:[],complete:true},lookup.extra)
 print FormatJson({count:lookup.params.seeds.Count(),status:m.streamingStatus.text})
''')
        self.assertEqual(actual['count'],24)
        self.assertIn('Partial',actual['status'])
        self.assertIn('selected catalog',actual['status'])

    def test_new_visit_live_waits_for_old_rpc_then_starts_current_batch_once(self):
        actual=self.scene('''
 StreamingOpen("netflix")
 StreamingResult({ok:true},{items:[]},m.requests[0].extra)
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"Old",tmdbId:"999"}]},m.requests[1].extra)
 stale=m.requests[2].extra
 StreamingOpen("hulu")
 StreamingResult({ok:true},{items:[]},m.requests[3].extra)
 StreamingResult({ok:true},{items:[{provider:"metadata",type:"movie",title:"New",tmdbId:"777"}]},m.requests[4].extra)
 before=m.requests.Count()
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:48},stale)
 cap=m.requests[5]
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:48},cap.extra)
 StreamingIdentityResult({ok:true},{identityResolution:true,maxIdentityBatch:48},stale)
 print FormatJson({before:before,count:m.requests.Count(),action:m.requests[6].action,seeds:m.requests[6].params.seeds,visit:m.requests[6].extra.visit})
''')
        self.assertEqual(actual,{'before':5,'count':7,'action':'catalog_resolve','seeds':[{'type':'movie','tmdb_id':'777'}],'visit':2})
