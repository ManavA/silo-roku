"""Real API dispatch and Silo builder at injected HTTP/session/device boundaries."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from tools.brightscript import run_function
import test_silo_playback_policy as values
import test_silo_playback_task as legacy
BOUNDARY='''
function TaskDeviceSession(provider as String,session as Object) as Object
 return session
end function
function LoadSession(provider as String) as Object
 return m.fixtureSession
end function
function FixtureRecoveryClock() as Object
 return {owner:m,marks:0,Mark:sub()
 m.marks=m.marks+1:m.owner.fixtureElapsed=0
 end sub}
end function
function SaveSession(provider as String,session as Object,revision as Integer) as Boolean
 if revision<>m.fixtureRevision then return false
 m.fixtureSession=session:m.fixtureSaves=m.fixtureSaves+1
 return true
end function
function RunSiloReplan(params as Object,scope as Object,responses as Object,config as Object) as Object
 m.requests=[]:m.timeouts=[]:m.responses=responses:m.fixtureRevision=0:m.changeRevision=false
 m.fixtureElapsed=999999:m.fixtureSaves=0:m.top={cancelled:false}
 m.enforceCurrentPlan=config.enforce
 m.currentPlanId=params.plan.siloPlayback.planId:m.currentPlanKey=params.plan.siloPlayback.planAttemptKey
 m.fixtureSession={baseUrl:"https://silo.example",sourceId:"silo:synthetic",profileId:"owner",deviceId:"fixture-device",accessToken:"synthetic-access",refreshToken:"synthetic-refresh",profileToken:"synthetic-profile"}
 action="playback_replan"
 if config.audio then action="playback_audio_select"
 if config.subtitleOff then action="playback_subtitle_off"
 if config.subtitleSelect then action="playback_subtitle_select"
 outcome=ExecuteApiAction("silo",action,params,scope)
 clockMarks=0
 if m.siloRecoveryBudget<>invalid then clockMarks=m.siloRecoveryBudget.clock.marks
 return {outcome:outcome,requests:m.requests,timeouts:m.timeouts,saves:m.fixtureSaves,clockMarks:clockMarks}
end function
'''
class SiloReplanTaskTests(unittest.TestCase):
 def params(self):
  return {'sessionId':'session-0001','plan':values.plan(),'qualityPreference':'720p','positionMs':12500,'replanRequestId':'replan-request-0001'}
 def call(self,params=None,decision=None,status=200,scope=None,followup=None,advance_current=False,audio_index=None,audio_codec="aac",audio_hls=True,capability_features=None,capability_deliveries=None,subtitle_off=False,capability_protocols=None,subtitle_select=False,continuations=None,http_effects=None):
  p=self.params() if params is None else params
  cap=json.loads((ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text());cap['installation_id']='install-0001'
  if capability_features is not None:
   cap['features']=capability_features
   cap['deliveries'].append('server_remux_hls')
  if capability_deliveries is not None:cap['deliveries']=capability_deliveries
  if capability_protocols is not None:cap['protocol_versions']=capability_protocols
  raw=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text()) if decision is None else decision
  raw=copy.deepcopy(raw);raw['session_id']='session-0001'
  plan=raw.get('playback_plan',{})
  plan.update(plan_id='plan-0002',plan_attempt_key='plan-key-0002')
  plan.setdefault('selected_tracks',values.TRACKS)
  if decision is None:plan['selected_tracks']=values.TRACKS
  if followup is not None or continuations is not None:cap['deliveries'].append('server_transcode_hls')
  if audio_index is not None and audio_hls:cap['deliveries'].append('server_transcode_hls')
  responses=[{'statusCode':200,'body':json.dumps(cap)},{'statusCode':status,'body':json.dumps(raw)}]
  if audio_index is not None:
   p=copy.deepcopy(p);p.pop('qualityPreference',None);p['audioTrackIndex']=audio_index
   wire=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
   wire['versions'][0]['audio_tracks']=[{'index':audio_index,'codec':audio_codec,'channels':2,'language':'eng'}]
   raw['playback_plan']['selected_tracks']={'audio':{'id':'file:f1:audio:'+str(audio_index),'index':audio_index}}
   if audio_hls and decision is None:
    raw['playback_plan']['stream'].update(protocol='hls',container='hls')
    raw['playback_plan'].update(delivery='server_transcode_hls',effective_recipe={'video_codec':'h264','audio_codec':'aac','dynamic_range':'sdr','width':1280,'height':720,'audio_channels':2},transformations=[{'name':'video_to_h264','executor':'server','recipe_version':'2'},{'name':'audio_to_aac','executor':'server','recipe_version':'4'}])
   responses[1]['body']=json.dumps(raw)
   responses.insert(0,{'statusCode':200,'body':json.dumps(wire)})
  if followup is not None:responses.append({'statusCode':200,'body':json.dumps(followup)})
  if continuations is not None:responses.extend({'statusCode':200,'body':json.dumps(row)} for row in continuations)
  if http_effects is not None:
   for response,effect in zip(responses,http_effects):response.update(effect)
  with tempfile.TemporaryDirectory() as d:
   t=Path(d);api=t/'api.brs';api.write_text((ROOT/'components/ApiTask.brs').read_text().replace('function TaskDeviceSession(','function UnusedTaskDeviceSession(',1).replace('function TaskUniqueId(','function UnusedTaskUniqueId(',1).replace('function TaskRokuSiloContext(','function UnusedTaskRokuSiloContext(',1).replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()'))
   http=t/'http.brs';http.write_text((ROOT/'source/network/Http.brs').read_text().replace('function HttpRequest(','function UnusedHttpRequest(',1))
   b=t/'boundaries.brs';b.write_text(legacy.BOUNDARIES.replace('function LoadSession(', 'function UnusedFixtureLoadSession(', 1).replace('response = m.responses.Shift()', 'response = m.responses.Shift()\n    m.fixtureElapsed = m.fixtureElapsed + TaskValue(response,"elapsedMs",0)\n    if TaskValue(response,"cancel",false) then m.top.cancelled = true\n    if TaskValue(response,"revisionChanged",false) then m.fixtureRevision = m.fixtureRevision + 1')+BOUNDARY+'\nfunction TaskSiloRecoveryElapsedMs(budget as Object) as Integer\n return m.fixtureElapsed\nend function\n')
   files=[ROOT/'source/core/RuntimeIdentity.brs', ROOT/'source/auth/SessionPolicy.brs',ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/core/PlaybackPolicy.brs',ROOT/'source/core/MediaScope.brs',api,http,b]
   for relative in ('source/core/SiloPlaybackPolicy.brs','source/core/SiloOriginalPlaybackPolicy.brs','source/core/SiloUIPlaybackChoicesPolicy.brs','components/TaskSiloReplan.brs'):
    f=ROOT/relative
    if f.exists():
     local=t/f.name;local.write_text(f.read_text().replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()').replace('function TaskSiloRecoveryElapsedMs(', 'function UnusedTaskSiloRecoveryElapsedMs(',1).replace('CreateObject("roTimespan")','FixtureRecoveryClock()'));files.append(local)
   return run_function(files,'RunSiloReplan',[p,scope or values.SCOPE,responses,{'enforce':advance_current,'audio':audio_index is not None,'subtitleOff':subtitle_off,'subtitleSelect':subtitle_select}],root=t)

 def subtitle_params(self):
  p=self.params();p.pop('qualityPreference')
  p['plan']['siloPlayback']['selectedTracks']['subtitle']={'id':'file:f1:subtitle:1','index':1}
  p['plan']['siloPlayback']['bandwidthCapKbps']=3500
  return p

 def subtitle_decision(self):
  raw=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  raw['playback_plan']['selected_tracks']=copy.deepcopy(values.TRACKS)
  raw['playback_plan']['subtitle']={'mode':'off','inventory':[]}
  return raw

 def test_provider_subtitle_off_uses_track_change_and_keeps_file_audio_quality_budget(self):
  p=self.subtitle_params();v=self.call(params=p,decision=self.subtitle_decision(),subtitle_off=True)
  self.assertTrue(v['outcome']['ok'],v['outcome'])
  self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']])
  body=json.loads(v['requests'][1]['body'])
  self.assertEqual('track_change',body['operation']);self.assertNotIn('failure',body)
  self.assertEqual('original',body['quality_preference']);self.assertEqual(3500,body['bandwidth_cap_kbps'])
  self.assertEqual(values.TRACKS,body['selected_tracks']);self.assertEqual(12.5,body['position_seconds'])
  self.assertEqual('session-0001',v['outcome']['plan']['sessionId']);self.assertEqual('f1',v['outcome']['plan']['versionId'])
  self.assertEqual(values.TRACKS,v['outcome']['plan']['siloPlayback']['selectedTracks'])
  self.assertTrue(v['outcome']['plan']['siloPlayback']['subtitleOffRequired'])

 def test_recovery_preserves_verified_provider_off_and_refuses_burned_captions(self):
  for mode in ('off','burn_in'):
   with self.subTest(mode=mode):
    p=self.params();p['failureClassification']='decoder_failure'
    p['plan']['siloPlayback']['subtitleOffRequired']=True
    raw=self.subtitle_decision();raw['playback_plan']['subtitle']={'mode':mode}
    v=self.call(params=p,decision=raw)
    if mode=='off':
     self.assertTrue(v['outcome']['ok'],v)
     self.assertTrue(v['outcome']['plan']['siloPlayback']['subtitleOffRequired'])
    else:
     self.assertFalse(v['outcome']['ok'],v)
     self.assertEqual('invalid_response',v['outcome']['errorCode'])
     self.assertTrue(v['outcome']['leaseUncertain'])
    self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']])

 def test_provider_subtitle_off_refuses_unproved_media_without_deleting_owned_lease(self):
  for subtitle in (None,{'mode':'render','track_id':'file:f1:subtitle:1'}, {'mode':'burn_in','track_id':'file:f1:subtitle:1'}, {'mode':'off','artifact':{'url':'/stale.vtt'}}):
   with self.subTest(subtitle=subtitle):
    raw=self.subtitle_decision()
    if subtitle is None:raw['playback_plan'].pop('subtitle')
    else:raw['playback_plan']['subtitle']=subtitle
    v=self.call(params=self.subtitle_params(),decision=raw,subtitle_off=True)
    self.assertFalse(v['outcome']['ok']);self.assertEqual('invalid_response',v['outcome']['errorCode'])
    self.assertTrue(v['outcome']['leaseUncertain']);self.assertEqual('plan-0002',v['outcome']['controlReceipt']['planId'])
    self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']])

 def test_provider_subtitle_off_request_has_no_public_operation_quality_or_audio_override(self):
  for field,value in [('operation','track_change'),('qualityPreference','off'),('audioTrackIndex',1),('failureClassification','decoder_failure')]:
   p=self.subtitle_params();p[field]=value
   v=self.call(params=p,decision=self.subtitle_decision(),subtitle_off=True)
   self.assertEqual('invalid_request',v['outcome']['errorCode']);self.assertEqual([],v['requests'])

 def test_provider_subtitle_off_transport_failure_preserves_uncertain_lease(self):
  v=self.call(params=self.subtitle_params(),decision=self.subtitle_decision(),subtitle_off=True,status=503)
  self.assertFalse(v['outcome']['ok']);self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']])
  self.assertTrue(v['outcome']['leaseUncertain'])

 def test_provider_subtitle_off_legacy_protocol_refuses_without_post(self):
  v=self.call(params=self.subtitle_params(),decision=self.subtitle_decision(),subtitle_off=True,capability_protocols=[2])
  self.assertEqual('unsupported_playback_protocol',v['outcome']['errorCode'])
  self.assertEqual(['GET'],[r['method'] for r in v['requests']])

 def test_provider_subtitle_off_cannot_change_audio_or_retain_subtitle_selection(self):
  for tracks in ({'audio':{'id':'file:f1:audio:2','index':2}},
                 {**values.TRACKS,'subtitle':{'id':'file:f1:subtitle:1','index':1}}):
   raw=self.subtitle_decision();raw['playback_plan']['selected_tracks']=tracks
   v=self.call(params=self.subtitle_params(),decision=raw,subtitle_off=True)
   self.assertEqual('invalid_response',v['outcome']['errorCode']);self.assertTrue(v['outcome'].get('leaseUncertain'))
   self.assertNotIn('controlReceipt',v['outcome']);self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']])
 def test_negotiated_replan_preparation_gets_90_seconds_at_the_real_http_boundary(self):
  value=self.call(capability_features=['native_hls_separate_audio_v1'])
  self.assertTrue(value['outcome']['ok'],value['outcome'])
  self.assertEqual([6000,90000],value['timeouts'])

 def test_unpatched_legacy_hls_replan_gets_90_seconds_without_fork_features(self):
  value=self.call(capability_features=[],capability_deliveries=['original_http','server_transcode_hls'])
  self.assertTrue(value['outcome']['ok'],value['outcome'])
  body=json.loads(value['requests'][1]['body'])
  self.assertEqual([],body['client_features'])
  self.assertEqual(['native_hls_playback_v1'],body['client_playback_context']['deliveries']['hls']['features'])
  self.assertEqual([6000,90000],value['timeouts'])

 def test_explicit_source_audio_fetches_fresh_inventory_and_preserves_same_lease(self):
  value=self.call(audio_index=2)
  self.assertTrue(value['outcome']['ok'],value['outcome'])
  self.assertEqual(['GET','GET','POST'],[r['method'] for r in value['requests']])
  body=json.loads(value['requests'][-1]['body'])
  self.assertEqual(body['selected_tracks']['audio'],{'id':'file:f1:audio:2','index':2})
  self.assertEqual('track_change',body['operation']);self.assertNotIn('failure',body)
  self.assertEqual(value['outcome']['plan']['sessionId'],'session-0001')
  self.assertEqual(value['outcome']['plan']['originalResumeMs'],12500)
  preference=value['outcome']['audioPreference']
  self.assertEqual(preference['seriesId'],'c1')
  self.assertEqual(preference['preference'],{'audio_track_index':0,'audio_language':'eng','track_signature':{'language':'eng','title':'','embedded_title':'','codec':'aac','layout':'','channels':2}})
  refused=self.call(audio_index=2,audio_codec='dts')
  self.assertFalse(refused['outcome']['ok'])
  self.assertNotIn('audioPreference',refused['outcome'])
  self.assertEqual(['GET'],[r['method'] for r in refused['requests']])

 def test_explicit_480p_is_preserved_through_replan_without_upward_normalization(self):
  params=self.params();params['qualityPreference']='480p'
  params['plan']['siloPlayback']['availableQualities'].append({'label':'480p','preservesSource':False,'height':480,'bitrateKbps':1500})
  value=self.call(params=params)
  self.assertTrue(value['outcome']['ok'],value['outcome'])
  self.assertEqual(json.loads(value['requests'][-1]['body'])['quality_preference'],'480p')
  self.assertEqual(value['outcome']['plan']['siloPlayback']['qualityPreference'],'480p')

 def test_rejected_audio_media_retains_control_receipt_and_marks_lease_uncertain(self):
  raw=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  raw['playback_plan']['stream']['protocol']='unsupported'
  value=self.call(audio_index=2,decision=raw)
  self.assertFalse(value['outcome']['ok'])
  self.assertTrue(value['outcome'].get('leaseUncertain'))
  self.assertEqual(value['outcome']['controlReceipt']['planId'],'plan-0002')

 def test_explicit_audio_refuses_direct_file_without_native_mapping_proof(self):
  value=self.call(audio_index=2,audio_hls=False)
  self.assertFalse(value['outcome']['ok'])
  self.assertEqual(value['outcome']['errorCode'],'unsupported_direct_audio_mapping')
  self.assertTrue(value['outcome']['leaseUncertain'])
  self.assertEqual(value['outcome']['controlReceipt']['planId'],'plan-0002')

 def test_quality_replan_uses_same_session_without_terminal_and_stable_request(self):
  v=self.call();self.assertTrue(v['outcome']['ok']);self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']])
  b=json.loads(v['requests'][1]['body']);self.assertEqual('replan-request-0001',b['replan_request_id']);self.assertEqual(12.5,b['position_seconds'])
  p=v['outcome']['plan'];self.assertEqual(('silo','session-0001','f1',12500),(p['provider'],p['sessionId'],p['versionId'],p['originalResumeMs']))
  self.assertEqual(1,p['siloPlayback']['attemptCount']);self.assertEqual(values.TRACKS,b['selected_tracks'])
  again=self.call();self.assertEqual(v['requests'][1]['body'],again['requests'][1]['body'])
 def test_native_failure_replans_same_session_without_delete(self):
  params=self.params();params.update(qualityPreference='original',failureClassification='decoder_failure')
  value=self.call(params=params)
  self.assertTrue(value['outcome']['ok'])
  self.assertEqual(['GET','POST'],[r['method'] for r in value['requests']])
  body=json.loads(value['requests'][1]['body'])
  self.assertEqual('failure_recovery',body['operation']);self.assertEqual('decoder_failure',body['failure']['classification'])
  self.assertEqual(1,value['outcome']['plan']['siloPlayback']['attemptCount'])

 def test_exhausted_automatic_original_can_replan_hd_on_the_same_lease(self):
  params=self.params();params.update(qualityPreference='original',failureClassification='decoder_failure')
  params['plan']['allowQualityFallback']=True
  params['plan']['siloPlayback']['availableQualities'].append({'label':'1080p','preservesSource':False,'height':1080,'bitrateKbps':8000})
  followup=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  followup['session_id']='session-0001'
  followup['playback_plan'].update(plan_id='plan-0003',plan_attempt_key='plan-key-0003',selected_tracks=values.TRACKS)
  terminal={'protocol_version':3,'outcome':'adaptation_unavailable','terminal':{'reason':'adaptation_exhausted','retryable':False}}
  result=self.call(params=params,decision=terminal,followup=followup)
  self.assertTrue(result['outcome']['ok'],result['outcome'])
  bodies=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
  self.assertEqual(['original','1080p'],[b['quality_preference'] for b in bodies])
  self.assertEqual('session-0001',result['outcome']['plan']['sessionId'])

 def test_automatic_hd_failure_descends_to_advertised_720p_and_explicit_choice_stays_pinned(self):
  params=self.params();params.update(qualityPreference='1080p',failureClassification='decoder_failure')
  params['plan']['siloPlayback']['qualityPreference']='1080p'
  params['plan']['siloPlayback']['availableQualities'].append({'label':'1080p','preservesSource':False,'height':1080,'bitrateKbps':8000})
  params['plan']['allowQualityFallback']=True
  terminal={'protocol_version':3,'outcome':'adaptation_unavailable','terminal':{'reason':'adaptation_exhausted','retryable':False}}
  followup=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  followup['session_id']='session-0001'
  followup['playback_plan'].update(plan_id='plan-0003',plan_attempt_key='plan-key-0003',selected_tracks=values.TRACKS)
  result=self.call(params=params,decision=terminal,followup=followup)
  self.assertTrue(result['outcome']['ok'],result['outcome'])
  bodies=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
  self.assertEqual(['1080p','720p'],[body['quality_preference'] for body in bodies])
  params['plan']['allowQualityFallback']=False
  pinned=self.call(params=params,decision=terminal)
  self.assertFalse(pinned['outcome']['ok'])
  self.assertEqual(2,len(pinned['requests']))

 def test_oversized_playable_replan_advances_identity_before_hd_retry(self):
  params=self.params();params.update(qualityPreference='original',failureClassification='decoder_failure')
  params['plan']['allowQualityFallback']=True
  params['plan']['siloPlayback']['availableQualities'].append({'label':'1080p','preservesSource':False,'height':1080,'bitrateKbps':8000})
  oversized=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  oversized['playback_plan'].update(delivery='server_transcode_hls',selected_tracks=values.TRACKS,
   effective_recipe={'video_codec':'h264','audio_codec':'aac','dynamic_range':'sdr','width':3840,'height':2160},
   transformations=[{'name':'video_to_h264','executor':'server','recipe_version':'2'},{'name':'audio_to_aac','executor':'server','recipe_version':'4'}],
   available_qualities=[{'label':'original','preserves_source':True},{'label':'1080p','preserves_source':False,'height':1080,'bitrate_kbps':8000}])
  oversized['playback_plan']['stream'].update(protocol='hls',container='hls')
  followup=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  followup['session_id']='session-0001'
  followup['playback_plan'].update(plan_id='plan-0003',plan_attempt_key='plan-key-0003',selected_tracks=values.TRACKS)
  result=self.call(params=params,decision=oversized,followup=followup,advance_current=True)
  self.assertTrue(result['outcome']['ok'],result['outcome'])
  bodies=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
  self.assertEqual(['plan-0001','plan-0002'],[b['failed_plan_id'] for b in bodies])
  self.assertEqual(['plan-key-0001','plan-key-0002'],bodies[-1]['attempted_plan_keys'])
  self.assertEqual(2,bodies[-1]['attempt_count'])

 def test_refused_hevc_hls_advances_receipt_before_compatible_quality_retry(self):
  params=self.params();params.update(qualityPreference='original',failureClassification='decoder_failure')
  params['plan']['allowQualityFallback']=True
  params['plan']['siloPlayback']['availableQualities'].append({'label':'1080p','preservesSource':False,'height':1080,'bitrateKbps':8000})
  refused=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  refused['playback_plan'].update(delivery='server_remux_hls',selected_tracks=values.TRACKS,
   effective_recipe={'video_codec':'hevc','audio_codec':'eac3','dynamic_range':'dolby_vision'},
   transformations=[],available_qualities=[{'label':'original','preserves_source':True},
    {'label':'1080p','preserves_source':False,'height':1080,'bitrate_kbps':8000}])
  refused['playback_plan']['stream'].update(protocol='hls',container='hls')
  followup=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  followup['session_id']='session-0001'
  followup['playback_plan'].update(plan_id='plan-0003',plan_attempt_key='plan-key-0003',selected_tracks=values.TRACKS)
  result=self.call(params=params,decision=refused,followup=followup,advance_current=True)
  self.assertTrue(result['outcome']['ok'],result['outcome'])
  bodies=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
  self.assertEqual(['original','1080p'],[b['quality_preference'] for b in bodies])
  self.assertEqual(['plan-0001','plan-0002'],[b['failed_plan_id'] for b in bodies])
  self.assertEqual(2,bodies[-1]['attempt_count'])
  self.assertNotIn('DELETE',[r['method'] for r in result['requests']])

 def test_foreign_scope_revision_or_top_level_session_is_rejected_before_http(self):
  p=self.params();p['sessionId']='foreign'
  v=self.call(params=p);self.assertEqual('invalid_request',v['outcome'].get('errorCode'));self.assertEqual([],v['requests'])
  p=self.params();p['plan']['siloPlayback']['sessionRevision']=1
  v=self.call(params=p);self.assertEqual('session_changed',v['outcome'].get('errorCode'));self.assertEqual([],v['requests'])
 def test_changed_file_session_and_malformed_replan_never_delete(self):
  for change in ('file','session','malformed'):
   raw=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
   if change=='file':raw['playback_plan']['effective_media_file_id']='other'
   elif change=='session':raw['playback_plan']['session_id']='foreign'
   else:raw['playback_plan']['timeline']=[]
   v=self.call(decision=raw);self.assertFalse(v['outcome']['ok']);self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']]);self.assertNotIn('plan',v['outcome'])
 def test_off_requires_matching_returned_tracks_and_never_sends_fake_selector(self):
  p=self.params();p['plan']['siloPlayback']['selectedTracks']['subtitle']={'id':'file:f1:subtitle:1','index':1};p['selectedTracks']=values.TRACKS
  v=self.call(params=p,decision=self.subtitle_decision());self.assertTrue(v['outcome']['ok']);self.assertNotIn('subtitle',json.loads(v['requests'][1]['body'])['selected_tracks'])
  self.assertEqual('track_change',json.loads(v['requests'][1]['body'])['operation'])
  raw=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text());raw['playback_plan']['selected_tracks']=p['plan']['siloPlayback']['selectedTracks']
  v=self.call(params=p,decision=raw);self.assertEqual('invalid_response',v['outcome'].get('errorCode'));self.assertEqual(2,len(v['requests']))
 def test_nonseekable_mismatch_and_transport_failure_cannot_acknowledge_replan(self):
  raw=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text());raw['playback_plan']['selected_tracks']=values.TRACKS;raw['playback_plan']['timeline'].update(can_seek_anywhere=False,player_start_seconds=0)
  v=self.call(decision=raw);self.assertFalse(v['outcome']['ok']);self.assertEqual(2,len(v['requests']))
  v=self.call(status=503);self.assertFalse(v['outcome']['ok']);self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']])

 def test_provider_off_preserves_1080p_when_server_menu_has_only_original(self):
  p=self.subtitle_params()
  p['plan']['siloPlayback'].update(qualityPreference='1080p',availableQualities=[{'label':'original','preservesSource':True}])
  v=self.call(params=p,decision=self.subtitle_decision(),subtitle_off=True)
  self.assertTrue(v['outcome']['ok'],v)
  body=json.loads(v['requests'][-1]['body'])
  self.assertEqual(('track_change','1080p'),(body['operation'],body['quality_preference']))
  self.assertNotIn('subtitle',body['selected_tracks'])
  self.assertEqual('1080p',v['outcome']['plan']['siloPlayback']['qualityPreference'])


 def test_user_audio_preserves_1080p_when_server_menu_has_only_original(self):
  p=self.params();p['plan']['siloPlayback'].update(qualityPreference='1080p',availableQualities=[{'label':'original','preservesSource':True}])
  v=self.call(params=p,audio_index=1)
  self.assertTrue(v['outcome']['ok'],v)
  body=json.loads(v['requests'][-1]['body'])
  self.assertEqual(('track_change','1080p'),(body['operation'],body['quality_preference']))
  self.assertEqual(1,body['selected_tracks']['audio']['index'])


 def test_unlisted_quality_refuses_generic_and_different_failure_quality_before_http(self):
  for failure in (False,True):
   p=self.params();p['qualityPreference']='1080p'
   p['plan']['siloPlayback'].update(qualityPreference='1080p',availableQualities=[{'label':'original','preservesSource':True}])
   if failure:
    p['failureClassification']='decoder_failure'
    p['qualityPreference']='720p'  # Recovery may retain 1080p, never introduce an unlisted rung.
   v=self.call(params=p)
   self.assertEqual('invalid_request',v['outcome']['errorCode'])
   self.assertEqual([],v['requests'])


 def test_internal_audio_detail_refuses_failures_null_failures_and_foreign_files(self):
  boundary='''
function RunAudioDetailGuard(session as Object, params as Object, scope as Object, raw as String) as Object
 m.requests=[]:m.timeouts=[]:m.responses=[]:m.fixtureRevision=0:m.fixtureSession=session
 decoded=DecodeSiloResponse("detail",raw,{sourceId:scope.sourceId,itemId:params.plan.itemId})
 detail=ScopeCatalogData(decoded.data,scope.sourceId)
 outcome=TaskReplanSiloPlayback(session,params,scope,0,detail)
 return {outcome:outcome,requests:m.requests}
end function
'''
  session={'baseUrl':'https://silo.example','sourceId':'silo:synthetic','profileId':'owner',
           'deviceId':'fixture-device','accessToken':'synthetic-access'}
  raw=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
  for change,foreign in (({'failureClassification':'decoder_failure'},False),({'failureClassification':None},False),({},True)):
   p=self.params();p.update(qualityPreference='original',**change)
   wire=copy.deepcopy(raw)
   if foreign:wire['versions'][0]['file_id']='foreign-file'
   with patch.object(legacy,'BOUNDARIES',legacy.BOUNDARIES+boundary):
    v=legacy.SiloPlaybackTaskTests().worker('RunAudioDetailGuard',[session,p,values.SCOPE,json.dumps(wire)])
   self.assertEqual('invalid_request',v['outcome']['errorCode'],v)
   self.assertEqual([],v['requests'])
