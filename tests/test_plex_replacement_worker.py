"""Actual Plex worker refreshes exact physical identity before any allocation."""
from pathlib import Path
import sys,tempfile,json,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.brightscript import run_function
from tests.test_plex_mp4_gate import BOUNDARY
C=Path(__file__).resolve().parents[1]
class ReplacementWorkerTests(unittest.TestCase):
 def call(self,params,refresh=None,ok=True):
  original=json.loads((C/'tests/fixtures/plex/movie_detail.json').read_text())
  fresh=refresh or json.loads(json.dumps(original));fresh['MediaContainer']['Metadata'][0]['Media'].reverse()
  session=dict(clientId='fixture-client',sourceId='plex:fixture-server',baseUrl='https://server.example.test',local=False,token='synthetic-server-token',accountToken='synthetic-account-token')
  expected=dict(sourceId=session['sourceId'],itemId='1',mediaId='2002',partId='3002',versionId='plex:fixture-server:1:2002:3002')
  args={'itemId':'1','versionIndex':1,'versionId':expected['versionId'],'startPositionMs':90500,'replacementFile':expected,**params}
  with tempfile.TemporaryDirectory(prefix='silo_ui-replacement-worker-') as d:
   root=Path(d);worker=root/'worker.brs';worker.write_text((C/'components/ApiTask.brs').read_text().replace('CreateObject("roDeviceInfo")','FixtureDevice()').replace('function TaskUniqueId(','function UnusedTaskUniqueId(',1))
   boundary=root/'boundary.brs';boundary.write_text(BOUNDARY)
   helper=C/'source/core/PlexReplacementPolicy.brs'
   files=[C/'source/auth/SessionPolicy.brs',C/'source/adapters/PlexAdapter.brs',C/'source/core/PlexDirectCapability.brs',worker,boundary]
   if helper.exists():files.append(helper)
   return run_function(files,'FixtureStart',[session,json.dumps(original),args,{'result':True},{'result':True},'1080p',[{'ok':ok,'body':json.dumps(fresh),'errorCode':'network_error'},{'ok':True,'body':(C/'tests/fixtures/plex/decision-copy.json').read_text()}]],root=root)
 def test_refresh_resolves_physical_ids_after_reorder_and_returns_private_ingress(self):
  r=self.call({});self.assertTrue(r['outcome']['ok'])
  self.assertEqual(1,len(r['requests']));self.assertIn('/library/metadata/1',r['requests'][0]['url'])
  p=r['outcome']['plan'];self.assertEqual((0,0,90500),(p['mediaIndex'],p['partIndex'],p['startPositionMs']))
  self.assertEqual('plex:fixture-server:1:2002:3002',p['clientIntent']['versionId']);self.assertEqual(1,r['outcome']['data']['playbackDetail']['versions'][0]['partCount'])
 def test_known_physical_ids_allow_current_safe_rotated_part_route(self):
  fresh=json.loads((C/'tests/fixtures/plex/movie_detail.json').read_text())
  fresh['MediaContainer']['Metadata'][0]['Media'][1]['Part'][0]['key']='/library/parts/3002/new-file.mp4'
  data=self.call({},fresh);self.assertTrue(data['outcome']['ok']);self.assertTrue(data['outcome']['plan']['url'].endswith('/library/parts/3002/new-file.mp4'))
 def test_explicit_cap_and_lane_are_kept_on_actual_decision_and_start_requests(self):
  r=self.call({'audioStreamId':'4005','maxVideoBitrate':4000,'videoResolution':'1280x720','forceTranscode':True})
  self.assertTrue(r['outcome']['ok']);self.assertEqual(2,len(r['requests']))
  url=r['requests'][1]['url'];self.assertIn('mediaIndex=0',url);self.assertIn('maxVideoBitrate=4000',url);self.assertIn('audioStreamID=4005',url)
  self.assertEqual(('4005',True,4000),(r['outcome']['plan']['clientIntent']['audioStreamId'],r['outcome']['plan']['clientIntent']['forceCompatible'],r['outcome']['plan']['clientIntent']['maxVideoBitrate']))
 def test_truncated_raw_inventory_cannot_hide_late_duplicate_or_approve_a_file(self):
  raw=json.loads((C/'tests/fixtures/plex/movie_detail.json').read_text())
  selected=raw['MediaContainer']['Metadata'][0]['Media'][1]
  raw['MediaContainer']['Metadata'][0]['Media']=[json.loads(json.dumps(selected))]
  for i in range(15):
   row=json.loads(json.dumps(selected));row['id']=str(5000+i);row['Part'][0]['id']=str(6000+i)
   raw['MediaContainer']['Metadata'][0]['Media'].append(row)
  raw['MediaContainer']['Metadata'][0]['Media'].append(json.loads(json.dumps(selected)))
  r=self.call({},raw);self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(r['requests']))
 def test_outer_version_and_physical_receipt_must_agree_before_refresh(self):
  r=self.call({'versionId':'other'})
  self.assertFalse(r['outcome']['ok']);self.assertEqual([],r['requests'])
 def test_missing_ambiguous_multipart_short_or_failed_refresh_has_no_allocation(self):
  original=json.loads((C/'tests/fixtures/plex/movie_detail.json').read_text())
  variants=[]
  missing=json.loads(json.dumps(original));missing['MediaContainer']['Metadata'][0]['Media']=missing['MediaContainer']['Metadata'][0]['Media'][:1];variants.append(missing)
  missing_id=json.loads(json.dumps(original));del missing_id['MediaContainer']['Metadata'][0]['Media'][1]['id'];variants.append(missing_id)
  missing_part=json.loads(json.dumps(original));del missing_part['MediaContainer']['Metadata'][0]['Media'][1]['Part'][0]['id'];variants.append(missing_part)
  multi=json.loads(json.dumps(original));part=multi['MediaContainer']['Metadata'][0]['Media'][1]['Part'][0];multi['MediaContainer']['Metadata'][0]['Media'][1]['Part'].append({**part,'id':'other'});variants.append(multi)
  short=json.loads(json.dumps(original));short['MediaContainer']['Metadata'][0]['Media'][1]['Part'][0]['duration']=90000;variants.append(short)
  duplicate=json.loads(json.dumps(original));duplicate['MediaContainer']['Metadata'][0]['Media'].append(duplicate['MediaContainer']['Metadata'][0]['Media'][1]);variants.append(duplicate)
  for body in variants:
   with self.subTest(body=body):
    r=self.call({},body);self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(r['requests']));self.assertNotIn('/transcode/',r['requests'][0]['url'])
  r=self.call({},ok=False);self.assertFalse(r['outcome']['ok']);self.assertEqual(1,len(r['requests']))
if __name__=='__main__':unittest.main()
