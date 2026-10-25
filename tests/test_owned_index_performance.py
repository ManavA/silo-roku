"""Keep closed owned-index validation linear without changing accepted values."""
import os
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import ROOT, run_function
POLICY=Path(os.environ.get("SILO_OWNED_POLICY",ROOT / "source/core/OwnedIndexPolicy.brs"))

RECORD={'itemId':'1','type':'movie','title':'Synthetic title','year':2026,'tmdbId':'1','imdbId':'','tvdbId':''}

WHITELIST_HELPERS='''
function FixtureFold(value as String) as String
    m.foldCalls++
    return LCase(value)
end function
function FoldedWhitelistFixture(value as Dynamic, allowed as Object) as Object
    m.foldCalls = 0
    accepted = OwnedIndexKeys(value,allowed)
    return {accepted:accepted,foldCalls:m.foldCalls}
end function
'''
class WhitelistCostTests(unittest.TestCase):
    def run_case(self,value,allowed):
        with tempfile.TemporaryDirectory(prefix='silo-owned-keys-cost-') as d:
            target=Path(d)/'policy.brs'
            target.write_text(re.sub(r'\bLCase\s*\(', 'FixtureFold(', POLICY.read_text(), flags=re.I))
            helpers=Path(d)/'boundary.brs';helpers.write_text(WHITELIST_HELPERS)
            return run_function([target,helpers],'FoldedWhitelistFixture',[value,allowed],root=Path(d))
    def test_twelve_field_shard_whitelist_does_not_repeat_case_folding_per_pair(self):
        names=['libraryId','offset','rawCount','nextOffset','terminal','identityComplete','recordCount','itemIds','uri','bytes','createdAt','expiresAt']
        value={name.upper():1 for name in names}
        result=self.run_case(value,names)
        self.assertTrue(result['accepted'])
        self.assertLessEqual(result['foldCalls'],len(value)+len(names))
    def test_field_lookup_folds_requested_key_once_and_keeps_alias_order(self):
        with tempfile.TemporaryDirectory(prefix='silo-owned-field-cost-') as d:
            target=Path(d)/'policy.brs'
            target.write_text(re.sub(r'\bLCase\s*\(', 'FixtureFold(', POLICY.read_text(), flags=re.I))
            helpers=Path(d)/'boundary.brs'
            helpers.write_text(WHITELIST_HELPERS+'\nfunction FoldedFieldFixture(value as Dynamic, name as String) as Object\n    m.foldCalls = 0\n    found = OwnedIndexField(value,name,"missing")\n    return {found:found,foldCalls:m.foldCalls}\nend function\n')
            value={f'key{i:02d}':i for i in range(12)}
            result=run_function([target,helpers],'FoldedFieldFixture',[value,'KEY11'],root=Path(d))
            self.assertEqual(11,result['found'])
            self.assertLessEqual(result['foldCalls'],len(value)+1)
            result=run_function([target,helpers],'FoldedFieldFixture',[{'sourceId':'lower','SOURCEID':'upper'},'sourceId'],root=Path(d))
            self.assertEqual('upper',result['found'])
    def test_case_aliases_extras_empty_and_non_objects_preserve_existing_decisions(self):
        cases=[({'ITEMID':'1','Type':'movie'},['itemId','type'],True),
               ({'Guid':'a','guid':'b'},['GUID'],True),
               ({'ITEMID':'1','TOKEN':'private'},['itemId','type'],False),
               ({},[],True),({'TYPE':3},['type'],True),({},[3],True),([],[],False), (None,[],False)]
        for value,allowed,expected in cases:
            with self.subTest(value=value,allowed=allowed):
                self.assertEqual(expected,self.run_case(value,allowed)['accepted'])

COMPACT_HELPERS='''
function FixtureFold(value as String) as String
    m.foldCalls++
    return LCase(value)
end function
function CompactFixture(records as Object) as Object
    results = []
    m.foldCalls = 0
    for each record in records
        results.Push(OwnedIndexValidCompactRecord(record))
    end for
    return {results:results,foldCalls:m.foldCalls}
end function
'''
class CompactRecordTests(unittest.TestCase):
    def call(self,records):
        with tempfile.TemporaryDirectory(prefix='silo-owned-record-') as d:
            target=Path(d)/'policy.brs'
            target.write_text(re.sub(r'\bLCase\s*\(', 'FixtureFold(', POLICY.read_text(), flags=re.I))
            helpers=Path(d)/'boundary.brs';helpers.write_text(COMPACT_HELPERS)
            return run_function([target,helpers],'CompactFixture',[records],root=Path(d))
    def test_compact_validation_does_not_repeatedly_refold_the_same_fields(self):
        result=self.call([RECORD])
        self.assertEqual([True],result['results'])
        self.assertLessEqual(result['foldCalls'],len(RECORD)*5)
    def test_closed_schema_aliases_and_all_value_guards(self):
        cases=[(RECORD,True),({k.upper():v for k,v in RECORD.items()},True),({**RECORD,'type':'show'},True),
               ({**RECORD,'title':' '},True),({**RECORD,'year':0},True),({**RECORD,'year':9999},True),
               ({**RECORD,'itemId':'1'*128,'title':'a'*256,'tmdbId':'1'*16,'imdbId':'tt'+'1'*16,'tvdbId':'1'*16},True)]
        for key,values in {'itemId':['',None,1,True,'../1','1'*129], 'type':['episode','',None,1],
                           'title':['',None,1,'a'*257,'bad\nline','bad\x7fline'],
                           'year':['2026',None,True,-1,10000,2026.5],
                           'tmdbId':[None,1,'bad','1'*17], 'imdbId':[None,1,'123','tt'],
                           'tvdbId':[None,1,'bad']}.items():
            cases.extend(({**RECORD,key:value},False) for value in values)
        for key in RECORD:
            bad={k:v for k,v in RECORD.items() if k!=key}
            cases.append((bad,False))
            bad={k:v for k,v in RECORD.items() if k!=key}
            alias='ITEMID' if key!='itemId' else 'TYPE'
            bad[alias]=RECORD['itemId' if key!='itemId' else 'type']
            cases.append((bad,False))
        cases.extend([({**RECORD,'token':'private'},False),(None,False),([],False)])
        result=self.call([record for record,_ in cases])
        self.assertEqual([expected for _,expected in cases],result['results'])
    def test_native_integer_aliases_keep_underlying_values_and_value_bounds(self):
        helpers='\nfunction FixtureNativeType(value as Dynamic) as String\n    kind = type(value)\n    if kind = "Integer" or kind = "roInt" then return m.numericAlias\n    return kind\nend function\nfunction NativeCompactFixture(alias as String, records as Object) as Object\n    m.numericAlias = alias\n    results = []\n    for each record in records\n        results.Push(OwnedIndexValidCompactRecord(record))\n    end for\n    return results\nend function\n'
        records=[RECORD,{**RECORD,'year':0},{**RECORD,'year':9999},
                 {**RECORD,'year':-1},{**RECORD,'year':10000},{**RECORD,'year':'2026'},
                 {**RECORD,'year':True},{**RECORD,'year':2026.5}]
        with tempfile.TemporaryDirectory(prefix='silo-owned-record-native-') as d:
            target=Path(d)/'policy.brs'
            target.write_text(re.sub(r'\btype\s*\(', 'FixtureNativeType(', POLICY.read_text(), flags=re.I))
            boundary=Path(d)/'boundary.brs';boundary.write_text(helpers)
            for alias in ('roInteger','roLongInteger'):
                with self.subTest(alias=alias):
                    self.assertEqual([True,True,True,False,False,False,False,False],
                                     run_function([target,boundary],'NativeCompactFixture',[alias,records],root=Path(d)))


if __name__ == "__main__":
    unittest.main()
