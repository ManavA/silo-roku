"""Current v2 units and exact-file worker ingress; no live requests.

Authority: Android4202441bec6f2e13c0e982b762bfe482b47179dd,
The Silo v2 schema FileVersion: duration seconds, bitrate kbps.
The corrected fixtures remain synthetic, not live provider recordings.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
import test_silo_playback_task as legacy
class SiloOptionsTaskTests(unittest.TestCase):
 def adapter(self,body):
  with tempfile.TemporaryDirectory() as d:
   return run_function(ROOT/'source/adapters/SiloAdapter.brs','DecodeSiloResponse',['detail',json.dumps(body),{'sourceId':'silo:synthetic'}],root=Path(d))
 def test_detail_seconds_kbps_and_complete_physical_rows_are_not_plex_parts(self):
  raw=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text());raw['versions'][0].update(duration=7080,bitrate=45000)
  d=self.adapter(raw)['data'];v=d['versions'][0]
  self.assertEqual(7080000,v['durationMs']);self.assertEqual(45000,v['bitrateKbps']);self.assertIs(d['versionsComplete'],True)
  self.assertEqual(('c1','silo:synthetic'),(v['itemId'],v['sourceId']));self.assertNotIn('partIndex',v)
 def test_detail_raw_overflow_cannot_claim_complete_or_rebind_duplicates(self):
  raw=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text());raw['versions']=[{**raw['versions'][0],'file_id':'f'+str(i)} for i in range(17)]
  d=self.adapter(raw)['data'];self.assertIs(d.get('versionsComplete'),False);self.assertLessEqual(len(d['versions']),16)
 def test_start_pins_file_and_rejects_changed_server_file_with_abandon(self):
  helper=legacy.SiloPlaybackTaskTests()
  v=helper.run_start();self.assertIs(json.loads(v['requests'][1]['body']).get('allow_alternate_versions'),False)
  decision=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text());decision['playback_plan']['effective_media_file_id']='other'
  v=helper.run_start(decision=decision)
  self.assertFalse(v['outcome']['ok']);self.assertEqual(['GET','POST','DELETE'],[r['method'] for r in v['requests']])
 def test_start_retains_scoped_provider_context_and_absolute_owed_position(self):
  v=legacy.SiloPlaybackTaskTests().run_start(params={'itemId':'fixture-item','fileId':'f1','startPositionMs':12500})['outcome']['plan']
  self.assertEqual('silo',v.get('provider'));self.assertEqual(12500,v['originalResumeMs'])
  c=v.get('siloPlayback');self.assertIsInstance(c,dict);self.assertEqual(('f1','server-install',False),(c['fileId'],c['installationId'],c['allowAlternateVersions']))
  self.assertEqual('original',c['availableQualities'][0]['label']);self.assertEqual({'audio':{'id':'a1'}},c['selectedTracks'])
 def test_start_requires_owned_item_identity_before_allocation(self):
  v=legacy.SiloPlaybackTaskTests().run_start(params={'fileId':'f1','startPositionMs':12500})
  self.assertFalse(v['outcome']['ok']);self.assertEqual([],v['requests'])
 def replacement(self,missing=False,partial=False,reject=False):
  helper=legacy.SiloPlaybackTaskTests();source=helper.session()['sourceId']
  raw=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
  proof=self.adapter(raw)['data'];proof['item']['sourceId']=source
  for row in proof['versions']:row['sourceId']=source
  if partial:proof['versionsComplete']=False
  params={'itemId':'c1','fileId':'f1','versionId':'f1','startPositionMs':12500,'detail':proof}
  captured=copy.deepcopy(params)
  if missing:raw['versions'][0]['file_id']='gone'
  cap=json.loads((ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text());cap['installation_id']='server-install'
  decision=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  if reject:decision['playback_plan']['effective_media_file_id']='other-file'
  responses=[{'statusCode':200,'body':json.dumps(raw)},{'statusCode':200,'body':json.dumps(cap)},
             {'statusCode':200,'body':json.dumps(decision)},{'statusCode':503,'body':'{"detail":"synthetic-private"}'}]
  value=helper.worker('RunSiloPlaybackStart',[helper.session(),params,responses,False])
  self.assertEqual(captured,params)
  return value
 def test_version_start_revalidates_fresh_detail_before_allocation_without_mutating_proof(self):
  v=self.replacement();self.assertTrue(v['outcome']['ok'])
  self.assertEqual(['GET','GET','POST'],[r['method'] for r in v['requests']])
  self.assertTrue(v['requests'][0]['url'].endswith('/api/v2/catalog/items/c1?image_size=medium'))
  self.assertEqual(12500,v['outcome']['plan']['originalResumeMs'])
  fresh=v['outcome'].get('data',{}).get('playbackDetail')
  self.assertIsInstance(fresh,dict)
  self.assertEqual(('c1','silo:https://silo.example'),(fresh['item']['itemId'],fresh['item']['sourceId']))
  self.assertIs(fresh['versionsComplete'],True);self.assertEqual('f1',fresh['versions'][0]['versionId'])
 def test_version_start_missing_fresh_file_or_partial_proof_never_allocates(self):
  v=self.replacement(missing=True);self.assertFalse(v['outcome']['ok'])
  self.assertEqual(1,len(v['requests']));self.assertTrue(v['requests'][0]['url'].endswith('/api/v2/catalog/items/c1?image_size=medium'))
  v=self.replacement(partial=True);self.assertFalse(v['outcome']['ok']);self.assertEqual([],v['requests'])
 def test_failed_replacement_abandon_retains_captured_owner_and_original_stop_id(self):
  value=self.replacement(reject=True);self.assertFalse(value['outcome']['ok'])
  self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in value['requests']])
  cleanup=value['outcome'].get('plan',{})
  self.assertEqual(('silo','silo:https://silo.example','c1','f1'),tuple(cleanup.get(k) for k in ('provider','sourceId','itemId','versionId')))
  self.assertEqual('10000000-0000-4000-8000-000000000001',cleanup['stopId']);self.assertIs(cleanup['persistProgress'],False)
  retry=legacy.SiloPlaybackTaskTests().run_event('playback_stop',params=cleanup)
  self.assertTrue(retry['outcome']['ok']);self.assertEqual(value['requests'][-1]['body'],retry['requests'][0]['body'])
  self.assertNotIn('synthetic-private',json.dumps(value['outcome']));self.assertNotIn('other-file',json.dumps(cleanup))
