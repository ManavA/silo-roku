"""Current v2 file identity, strict same-session context and quality body."""
import copy
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'source/core/SiloPlaybackPolicy.brs'
SCOPE={'provider':'silo','sourceId':'silo:synthetic','profileId':'owner','generation':7}
TRACKS={'audio':{'id':'file:f1:audio:0','index':0}}
QUALITIES=[{'label':'original','preservesSource':True},{'label':'720p','preservesSource':False,'height':720,'bitrateKbps':4000}]
def context(**changes):
 return dict(schemaVersion=1,sourceId=SCOPE['sourceId'],profileId='owner',itemId='c1',fileId='f1',sessionRevision=0,
 installationId='install-0001',sessionId='session-0001',playbackAttemptId='playback-attempt-0001',planId='plan-0001',
 planAttemptId='plan-attempt-0001',planAttemptKey='plan-key-0001',attemptedPlanKeys=[],attemptCount=0,
 allowAlternateVersions=False,qualityPreference='original',selectedTracks=copy.deepcopy(TRACKS),availableQualities=copy.deepcopy(QUALITIES),**changes)
def plan():
 c=context();return dict(provider='silo',sourceId=c['sourceId'],itemId=c['itemId'],versionId=c['fileId'],sessionId=c['sessionId'],installationId=c['installationId'],siloPlayback=c)
def detail():
 return {'item':{'sourceId':SCOPE['sourceId'],'itemId':'c1'},'versionsComplete':True,'versions':[
 {'sourceId':SCOPE['sourceId'],'itemId':'c1','versionId':'f2','durationMs':200000,'bitrateKbps':2000},
 {'sourceId':SCOPE['sourceId'],'itemId':'c1','versionId':'f1','durationMs':180000,'bitrateKbps':4000}]}
class SiloPlaybackPolicyTests(unittest.TestCase):
 def call(self,name,*args,bridge=''):
  self.assertTrue(POLICY.exists(),'Silo playback policy is missing')
  with tempfile.TemporaryDirectory() as d:
   files=[POLICY]
   if bridge:
    p=Path(d)/'bridge.brs';p.write_text(bridge);files.append(p)
   return run_function(files,name,list(args),root=Path(d))
 def test_automatic_fallback_quality_obeys_device_ceiling_and_descends(self):
  self.assertEqual('720p',self.call('SiloFallbackQuality','original','720p'))
  self.assertEqual('1080p',self.call('SiloFallbackQuality','original','2160p'))
  self.assertEqual('720p',self.call('SiloFallbackQuality','1080p','2160p'))
  self.assertEqual('480p',self.call('SiloFallbackQuality','720p','2160p'))
  self.assertEqual('720p',self.call('SiloFallbackQuality','original','1080p',QUALITIES))
  self.assertEqual('',self.call('SiloFallbackQuality','original','1080p',[]))
  self.assertEqual('720p',self.call('SiloFallbackQuality','original',''))

 def test_last_resort_quality_stops_at_480p_and_honors_server_menu(self):
  self.assertEqual('',self.call('SiloFallbackQuality','480p','2160p'))
  self.assertEqual('',self.call('SiloFallbackQuality','private','2160p'))
  self.assertEqual('480p',self.call('SiloFallbackQuality','original','2160p',[{'label':'480p'}]))
  self.assertEqual('480p',self.call('SiloFallbackQuality','1080p','1080p',[{'label':'480p'}]))
  self.assertEqual('',self.call('SiloFallbackQuality','720p','2160p',[{'label':'1080p'},{'label':'720p'}]))

 def test_exact_file_survives_reorder_without_plex_part_fields(self):
  d=detail();v=self.call('SiloPlaybackFile',d,SCOPE['sourceId'],'c1','f1',12500)
  self.assertEqual(('f1',1,180000,4000),(v['versionId'],v['versionIndex'],v['durationMs'],v['bitrateKbps']))
  d['versions'].reverse();self.assertEqual(0,self.call('SiloPlaybackFile',d,SCOPE['sourceId'],'c1','f1',12500)['versionIndex'])
 def test_file_refuses_partial_duplicate_foreign_or_owed_position_outside_file(self):
  cases=[]
  for patch in ({'versionsComplete':False},{'versionsComplete':1},{'versions':detail()['versions']*2}):cases.append({**detail(),**patch})
  d=detail();d['versions'][1]['sourceId']='silo:foreign';cases.append(d)
  d=detail();d['versions'][1]['itemId']='other';cases.append(d)
  d=detail();d['versions']*=9;cases.append(d)
  bridge='''function BadSiloFiles(values as Object,source as String) as Object
 out=[]
 for each value in values
  out.Push(SiloPlaybackFile(value,source,"c1","f1",12500))
 end for
 return out
end function'''
  self.assertEqual([None]*len(cases),self.call('BadSiloFiles',cases,SCOPE['sourceId'],bridge=bridge))
  self.assertIsNone(self.call('SiloPlaybackFile',detail(),SCOPE['sourceId'],'c1','f1',180000))
 def test_context_is_exact_scoped_header_free_and_retains_advertised_choices(self):
  p=plan();self.assertEqual(context(),self.call('SiloPlaybackContext',p,SCOPE))
  for field,value in [('sessionId','foreign'),('versionId','f2'),('provider','plex')]:
   changed=copy.deepcopy(p);changed[field]=value;self.assertIsNone(self.call('SiloPlaybackContext',changed,SCOPE))
 def test_context_rejects_unknown_collision_unpinned_file_and_bad_track_ids(self):
  values=[]
  for patch in ({'allowAlternateVersions':True},{'attemptCount':True},{'headers':{}},{'SessionId':'other'},
                {'selectedTracks':{'audio':{'id':'native-handle','url':'private'}}}, {'availableQualities':QUALITIES*9}):
   p=plan();p['siloPlayback'].update(patch);values.append(p)
  bridge='''function BadSiloContexts(values as Object,scope as Object) as Object
 out=[]
 for each value in values
  out.Push(SiloPlaybackContext(value,scope))
 end for
 return out
end function'''
  self.assertEqual([None]*len(values),self.call('BadSiloContexts',values,SCOPE,bridge=bridge))
 def test_failed_original_is_withdrawn_for_the_retained_file_lease(self):
  p=plan();p['siloPlayback']['originalDisabled']=True
  retained=self.call('SiloPlaybackContext',p,SCOPE)
  self.assertTrue(retained['originalDisabled'])
  params={'qualityPreference':'original','positionMs':12500,'replanRequestId':'request-0001','failureClassification':'decoder_failure'}
  built=self.call('SiloPlaybackReplanBody',retained,params,{},{})
  self.assertTrue(built['context']['originalDisabled'])
  p['siloPlayback']['originalDisabled']='true'
  self.assertIsNone(self.call('SiloPlaybackContext',p,SCOPE))

 def test_retained_short_server_ids_are_valid_but_cannot_form_a_replan_request(self):
  p=plan();p['siloPlayback']['planId']='p';p['siloPlayback']['planAttemptKey']='k'
  self.assertEqual(p['siloPlayback'],self.call('SiloPlaybackContext',p,SCOPE))
  self.assertFalse(self.call('SiloPlaybackCanReplan',p['siloPlayback']))
 def test_quality_body_is_same_lease_stable_request_and_preserves_current_tracks(self):
  params={'qualityPreference':'720p','positionMs':12500,'replanRequestId':'request-0001'}
  built=self.call('SiloPlaybackReplanBody',context(),params,{},{});self.assertTrue(built['ok'])
  b=built['body'];self.assertEqual(('quality_change',12.5,'session-0001'),(b['operation'],b['position_seconds'],built['context']['sessionId']))
  self.assertEqual(TRACKS,b['selected_tracks']);self.assertEqual(['plan-key-0001'],b['attempted_plan_keys']);self.assertEqual(1,b['attempt_count'])
  self.assertNotIn('file_id',b);self.assertNotIn('allow_alternate_versions',b)
  self.assertEqual(b,self.call('SiloPlaybackReplanBody',context(),params,{},{})['body'])
 def test_native_failure_reuses_lease_and_bounds_attempts_without_track_changes(self):
  params={'qualityPreference':'original','positionMs':12500,'replanRequestId':'recover-request-0001','failureClassification':'decoder_failure'}
  built=self.call('SiloPlaybackReplanBody',context(),params,{},{})
  self.assertTrue(built['ok']);body=built['body']
  self.assertEqual('failure_recovery',body['operation'])
  self.assertEqual({'classification':'decoder_failure'},body['failure'])
  self.assertEqual(TRACKS,body['selected_tracks']);self.assertEqual(1,body['attempt_count'])
  self.assertEqual(['plan-key-0001'],body['attempted_plan_keys'])
  self.assertFalse(self.call('SiloPlaybackReplanBody',context(),{**params,'failureClassification':'untrusted'},{},{})['ok'])

 def test_quality_body_rejects_unadvertised_or_exhausted_and_off_is_omission(self):
  base={'qualityPreference':'720p','positionMs':12500,'replanRequestId':'request-0001'}
  self.assertFalse(self.call('SiloPlaybackReplanBody',context(),{**base,'qualityPreference':'1080p'},{},{})['ok'])
  c=context();c['attemptCount']=8;self.assertFalse(self.call('SiloPlaybackReplanBody',c,base,{},{})['ok'])
  b=self.call('SiloPlaybackReplanBody',context(),{**base,'selectedTracks':{'audio':TRACKS['audio']}},{},{})['body']
  self.assertNotIn('subtitle',b['selected_tracks'])

 def test_proven_subtitle_omission_is_track_change_without_failure(self):
  c=context();c['selectedTracks']['subtitle']={'id':'file:f1:subtitle:1','index':1}
  params={'qualityPreference':'original','positionMs':12500,'replanRequestId':'subtitle-off-0001','selectedTracks':copy.deepcopy(TRACKS)}
  body=self.call('SiloPlaybackReplanBody',c,params,{},{})['body']
  self.assertEqual('track_change',body['operation']);self.assertNotIn('failure',body)
  unchanged=self.call('SiloPlaybackReplanBody',context(),params,{},{})['body']
  self.assertEqual('quality_change',unchanged['operation'])
  failed=self.call('SiloPlaybackReplanBody',c,{**params,'failureClassification':'decoder_failure'},{},{})['body']
  self.assertEqual('failure_recovery',failed['operation'])

 def test_track_change_preserves_only_captured_quality_without_failure_or_null_bypass(self):
  c=context();c.update(qualityPreference='1080p',availableQualities=[{'label':'original','preservesSource':True}])
  params={'qualityPreference':'1080p','positionMs':12500,'replanRequestId':'track-request-0001'}
  built=self.call('SiloPlaybackReplanBody',c,params,{},{},True)
  self.assertTrue(built['ok'],built)
  self.assertEqual(('track_change','1080p'),(built['body']['operation'],built['body']['quality_preference']))
  self.assertEqual(c['availableQualities'],built['context']['availableQualities'])
  self.assertFalse(self.call('SiloPlaybackReplanBody',c,params,{},{})['ok'])
  for change in ({'qualityPreference':'720p'},{'qualityPreference':'original'},
                 {'failureClassification':'decoder_failure'},{'failureClassification':None}):
   with self.subTest(change=change):
    self.assertFalse(self.call('SiloPlaybackReplanBody',c,{**params,**change},{},{},True)['ok'])
  c['attemptCount']=8
  self.assertFalse(self.call('SiloPlaybackReplanBody',c,params,{},{},True)['ok'])
