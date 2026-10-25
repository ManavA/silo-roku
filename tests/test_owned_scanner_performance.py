import copy
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from tools.brightscript import ROOT,run_function
from tests.test_owned_index_coordinator import SCOPE,NOW
INDEX=Path(os.environ.get('SILO_OWNED_POLICY',ROOT/'source/core/OwnedIndexPolicy.brs'))
MANIFEST=ROOT/'source/core/OwnedIndexManifestPolicy.brs'
POLICY=Path(os.environ.get('SILO_COORDINATOR_POLICY',ROOT/'source/core/OwnedIndexCoordinatorPolicy.brs'))
HELPERS='''
function FixtureFold(value as String) as String
    m.foldCalls++
    return LCase(value)
end function
function OwnedIndexField(data as Dynamic,key as String,fallback=invalid as Dynamic) as Dynamic
    m.fieldCalls++
    return OriginalOwnedIndexField(data,key,fallback)
end function
function ValidateStateFixture(states as Object) as Object
    m.fieldCalls = 0
    m.foldCalls = 0
    results = []
    for each state in states
        results.Push(OwnedIndexCoordinatorValidState(state))
    end for
    return {results:results,fieldCalls:m.fieldCalls,foldCalls:m.foldCalls}
end function
function MutateStateFixture(state as Object) as Object
    m.fieldCalls = 0
    m.foldCalls = 0
    first = OwnedIndexCoordinatorValidState(state)
    state.sections[23].pages = 201
    second = OwnedIndexCoordinatorValidState(state)
    return [first,second]
end function
'''
def state():
    with tempfile.TemporaryDirectory() as d:
        discovery={'sections':[{'sectionId':str(i+1),'type':'movie'} for i in range(24)],'truncated':True}
        return run_function([INDEX,MANIFEST,POLICY],'OwnedIndexCoordinatorStart',[SCOPE,discovery,NOW],root=Path(d))
class ScannerLookupTests(unittest.TestCase):
    def call(self,name,states):
        with tempfile.TemporaryDirectory() as d:
            index=Path(d)/'index.brs';index.write_text(re.sub(r'\bLCase\s*\(', 'FixtureFold(', INDEX.read_text().replace('function OwnedIndexField(','function OriginalOwnedIndexField(',1), flags=re.I))
            helper=Path(d)/'helper.brs';helper.write_text(HELPERS)
            policy=Path(d)/'policy.brs';policy.write_text(re.sub(r'\bLCase\s*\(', 'FixtureFold(', POLICY.read_text(), flags=re.I))
            return run_function([index,MANIFEST,policy,helper],name,[states],root=Path(d))
    def test_section_validation_does_not_repeat_field_walks_per_section(self):
        result=self.call('ValidateStateFixture',[state()])
        self.assertEqual([True],result['results'])
        self.assertLessEqual(result['fieldCalls'],32)
        self.assertLessEqual(result['foldCalls'],300)
    def test_case_alias_projection_and_invalid_external_states(self):
        good=state()
        cases=[(good,True)]
        for field in ('schema','partial','sectionTruncated','finished','authoritativeAbsence','sourceInventoryComplete','sectionIndex','dispatchedPages','nextRequestId','scope','manifest','sections'):
            bad=copy.deepcopy(good);bad[field]=None;cases.append((bad,False))
        for field,value in [('pages',201),('pages','0'),('nextOffset',-1),('libraryId','../x'),('type',5),('status',False)]:
            bad=copy.deepcopy(good);bad['sections'][23][field]=value;cases.append((bad,False))
        bad=copy.deepcopy(good);bad['validated']=True;cases.append((bad,False))
        for upper,lower,expected in ((1,2,True),(2,1,False)):
            alias=copy.deepcopy(good);alias.pop('status');alias['SCHEMA']=upper;alias['schema']=lower;cases.append((alias,expected))
        result=self.call('ValidateStateFixture',[v for v,_ in cases])
        self.assertEqual([expected for _,expected in cases],result['results'])
    def test_mutating_same_associative_array_is_revalidated(self):
        self.assertEqual([True,False],self.call('MutateStateFixture',state()))
if __name__=='__main__':unittest.main()
