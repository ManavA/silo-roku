from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.brightscript import run_function, ROOT as R
C=Path(__file__).resolve().parents[1]
SCOPE={'provider':'plex','sourceId':'plex:fixture-server','profileId':'owner','generation':7}
PREF={'schemaVersion':1,'sourceId':SCOPE['sourceId'],'profileId':'owner','subtitleMode':'off','subtitleLanguage':'eng','subtitleName':'','audioLanguage':'','audioName':''}
BOUNDARY='''function PreferenceQueueTrace(scope as Object,changed as Object,entries as Object) as Object
    q=RqCreate(scope)
    for each entry in entries
        admitted=RqOffer(q,entry)
        q=admitted.state
    end for
    return {before:q,after:RqRebind(q,changed)}
end function'''
class PreferenceQueueTests(unittest.TestCase):
 def trace(self,*entries,scope=None):
  with tempfile.TemporaryDirectory(prefix='silo-pref-queue-') as d:
   p=Path(d)/'fixture.brs';p.write_text(BOUNDARY)
   return run_function([C/'source/core/RequestQueuePolicy.brs',p],'PreferenceQueueTrace',[SCOPE,scope or {**SCOPE,'generation':8},list(entries)],root=Path(d))
 def entry(self,action='track_pref_set',params=None):return {'job':{**SCOPE,'action':action,'params':params or {'preference':PREF}},'purpose':action,'cleanup':False}
 def test_only_already_admitted_compact_same_viewer_preference_write_survives_route_generation(self):
  result=self.trace(self.entry(),self.entry('watched',{'itemId':'1'}),self.entry('track_pref_get',{}))
  self.assertEqual(3,len(result['before']['queued']))
  self.assertEqual(['track_pref_set'],[r['job']['action'] for r in result['after']['queued']])
  self.assertEqual(result['before']['queued'][0],result['after']['queued'][0])
  self.assertFalse(result['after']['queued'][0]['cleanup'])
 def test_changed_source_or_profile_retires_preference_write(self):
  for key,value in [('sourceId','plex:other'),('profileId','other'),('provider','silo')]:
   with self.subTest(key=key):self.assertEqual([],self.trace(self.entry(),scope={**SCOPE,key:value})['after']['queued'])
 def test_malformed_preference_payload_has_no_retention_exemption(self):
  for value in ({'preference':{'sourceId':SCOPE['sourceId']}},{'preference':{**PREF,'token':'synthetic-only-token'}},{'preference':{**PREF,'profileId':'other'}}):
   with self.subTest(value=value):self.assertEqual([],self.trace(self.entry(params=value))['after']['queued'])
if __name__=='__main__':unittest.main()
