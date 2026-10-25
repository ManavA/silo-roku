import os
from pathlib import Path
import sys
import tempfile
import unittest
from tools.brightscript import ROOT,run_function
INDEX=Path(os.environ.get('SILO_OWNED_POLICY',ROOT/'source/core/OwnedIndexPolicy.brs'))
SEARCH=Path(os.environ.get('SILO_SEARCH_POLICY',ROOT/'source/core/SearchPolicy.brs'))
SHARD=Path(os.environ.get('SILO_SHARD_SEARCH_POLICY',ROOT/'source/core/OwnedShardSearchPolicy.brs'))
HELPERS='''
function OwnedIndexField(data as Dynamic,key as String,fallback=invalid as Dynamic) as Dynamic
    m.fieldCalls++
    return OriginalOwnedIndexField(data,key,fallback)
end function
function SearchBoundedEditDistance(leftText as String,rightText as String,maximum as Integer) as Integer
    m.distanceCalls++
    return OriginalSearchBoundedEditDistance(leftText,rightText,maximum)
end function
function SearchField(value as Dynamic,field as String,fallback as Dynamic) as Dynamic
    m.searchFieldCalls++
    return OriginalSearchField(value,field,fallback)
end function
function FuzzyFixture(titles as Object,remaining as Integer) as Object
    context = SearchQueryContext("nightmoon")
    initialBudget = context.remaining
    context.remaining = remaining
    m.distanceCalls = 0
    buckets = []
    for each title in titles
        buckets.Push(SearchTitleBucket(title,context))
    end for
    cached = 0
    if context.DoesExist("editDistances") then cached = context.editDistances.Count()
    return {buckets:buckets,remaining:context.remaining,calls:m.distanceCalls,cached:cached,initialBudget:initialBudget}
end function
function RankFixture(records as Object,sourceId = "plex:fixture-server" as String) as Object
    m.fieldCalls = 0
    m.distanceCalls = 0
    m.sortCalls = 0
    m.searchFieldCalls = 0
    state = OwnedShardSearchState("moon",sourceId)
    state = OwnedShardSearchAccumulate(state,records)
    return {outcome:OwnedShardSearchResults(state),invalidRecord:state.invalidRecord,fieldCalls:m.fieldCalls,searchFieldCalls:m.searchFieldCalls}
end function
'''
SORT_HELPERS='\nsub SortRankedFixture(ranked as Object)\n    m.sortCalls++\n    ranked.SortBy("sortkey")\nend sub\nfunction RankPagesFixture(pages as Object) as Object\n    m.fieldCalls = 0\n    m.distanceCalls = 0\n    m.sortCalls = 0\n    m.searchFieldCalls = 0\n    state = OwnedShardSearchState("moon","plex:fixture-server")\n    for each records in pages\n        state = OwnedShardSearchAccumulate(state,records)\n    end for\n    before = OwnedShardSearchResults(state)\n    state = OwnedShardSearchAccumulate(state,[{itemId:"2000",type:"movie",title:"Moon",year:2026,tmdbId:"",imdbId:"",tvdbId:""}])\n    return {before:before,after:OwnedShardSearchResults(state),sortCalls:m.sortCalls,inspected:state.inspected}\nend function\n'
class SearchWorkTests(unittest.TestCase):
    def call(self,name,args):
        with tempfile.TemporaryDirectory() as d:
            index=Path(d)/'index.brs';index.write_text(INDEX.read_text().replace('function OwnedIndexField(','function OriginalOwnedIndexField(',1))
            search=Path(d)/'search.brs';search.write_text(SEARCH.read_text().replace('function SearchBoundedEditDistance(','function OriginalSearchBoundedEditDistance(',1).replace('function SearchField(','function OriginalSearchField(',1))
            helper=Path(d)/'helper.brs';helper.write_text(HELPERS+SORT_HELPERS)
            shard=Path(d)/'shard.brs';shard.write_text(SHARD.read_text().replace('state.ranked.SortBy("sortkey")','SortRankedFixture(state.ranked)'))
            return run_function([index,search,shard,helper],name,args,root=Path(d))
    def test_repeated_fuzzy_pairs_keep_budget_accounting_without_recomputing_distance(self):
        result=self.call('FuzzyFixture',[['Nightmoom']*20,64])
        self.assertEqual([3]*20,result['buckets'])
        self.assertEqual((44,1024),(result['remaining'],result['initialBudget']))
        self.assertLessEqual(result['calls'],1)
    def test_exhaustion_still_disables_fuzzy_and_preserves_later_exact(self):
        result=self.call('FuzzyFixture',[['Nightmoom','Nightmoom','Nightmoon'],1])
        self.assertEqual(([3,4,0],0,1),(result['buckets'],result['remaining'],result['calls']))
    def test_negative_pairs_and_cache_storage_are_bounded(self):
        result=self.call('FuzzyFixture',[['Unrelated']*5,12])
        self.assertEqual(([4]*5,7),(result['buckets'],result['remaining']))
        self.assertLessEqual(result['calls'],1)
        result=self.call('FuzzyFixture',[[f'Nightmoo{i}' for i in range(80)],128])
        self.assertLessEqual(result['cached'],64)
        self.assertEqual(48,result['remaining'])
    def test_compact_public_projection_does_not_repeat_case_folded_field_walks(self):
        records=[{'itemId':str(i+1),'type':'movie','title':'Moon','year':2026,'tmdbId':'','imdbId':'','tvdbId':''} for i in range(48)]
        result=self.call('RankFixture',[records])
        self.assertFalse(result['invalidRecord'])
        self.assertEqual(48,len(result['outcome']['items']))
        self.assertLessEqual(result['fieldCalls'],2)
        self.assertLessEqual(result['searchFieldCalls'],48)
    def test_projection_keeps_first_alias_defaults_and_discards_private_extras(self):
        records=[{'ITEMID':'1','TYPE':'movie','TITLE':'Moon','title':'Other','tmdbId':'','imdbId':'','tvdbId':'','token':'private'},
                 {'itemId':'2','type':'movie','title':'Moon','year':None,'tmdbId':12,'imdbId':'','tvdbId':''}]
        result=self.call('RankFixture',[records])
        self.assertFalse(result['invalidRecord'])
        self.assertEqual(['1','2'],[x['itemId'] for x in result['outcome']['items']])
        self.assertEqual(('Moon',0),(result['outcome']['items'][0]['title'],result['outcome']['items'][0]['year']))
        self.assertEqual(0,result['outcome']['items'][1]['year'])
        self.assertNotIn('private',str(result['outcome']))
        for name in ('count','doesExist'):
            record={'itemId':'3','type':'movie','title':'Moon','year':2026,'imdbId':'','tvdbId':'',name:'private'}
            self.assertFalse(self.call('RankFixture',[[record]])['invalidRecord'])
    def test_full_top_hundred_skips_later_ties_and_still_accepts_better_exact(self):
        records=[{'itemId':str(i+1),'type':'movie','title':'Moon base','year':2026,'tmdbId':'','imdbId':'','tvdbId':''} for i in range(144)]
        result=self.call('RankPagesFixture',[[records[i:i+48] for i in range(0,144,48)]])
        self.assertEqual([str(i) for i in range(1,101)],[x['itemId'] for x in result['before']['items']])
        self.assertEqual('2000',result['after']['items'][0]['itemId'])
        self.assertEqual((100,145),(len(result['after']['items']),result['inspected']))
        self.assertLessEqual(result['sortCalls'],101)
    def test_owned_card_value_guards_match_existing_normalizer(self):
        base={'itemId':'1','type':'movie','title':'Moon','year':2026,'tmdbId':'','imdbId':'','tvdbId':''}
        valid=[{**base,'itemId':'1','title':'  Moon  '},
               {**base,'itemId':'2','year':None},
               {**base,'itemId':'3','year':2026.5},
               {**base,'itemId':'4','year':'2026'},
               {**base,'itemId':'5','type':'episode'},
               {**base,'itemId':'6','type':'collection'},
               {**base,'itemId':'7','year':-1},
               {**base,'itemId':'8','year':10000},
               {**base,'itemId':'9','year':False}]
        result=self.call('RankFixture',[valid])
        self.assertFalse(result['invalidRecord'])
        by_id={card['itemId']:card for card in result['outcome']['items']}
        self.assertEqual('Moon',by_id['1']['title'])
        self.assertEqual(0,by_id['2']['year'])
        self.assertNotIn('year',by_id['3'])
        self.assertNotIn('year',by_id['4'])
        self.assertEqual((-1,10000),(by_id['7']['year'],by_id['8']['year']))
        self.assertNotIn('year',by_id['9'])
        for patch in ({'itemId':'a'},{'itemId':'123456789012345678901'},{'itemId':''},
                      {'title':'  '},{'title':12},{'type':'unsupported'}):
            with self.subTest(patch=patch):
                result=self.call('RankFixture',[[{**base,**patch}]])
                self.assertTrue(result['invalidRecord'])
    def test_owned_projection_keeps_plex_source_guards(self):
        record={'itemId':'1','type':'movie','title':'Moon','year':2026,'tmdbId':'','imdbId':'','tvdbId':''}
        for source in ('plex:','silo:fixture','global:fixture','','Plex:fixture'):
            with self.subTest(source=source):
                result=self.call('RankFixture',[[record],source])
                self.assertTrue(result['invalidRecord'])
if __name__=='__main__':unittest.main()
