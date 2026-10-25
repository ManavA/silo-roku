"""Synthetic contract receipts through real Start and ExecuteApiAction; no media proof."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_function
from tests import test_silo_playback_task as playback
ROOT=Path(__file__).resolve().parents[1]
SEEK_ID='20000000-0000-4000-8000-000000000001'
WRAPPER='''
function TaskDeviceSession(provider as String, session as Object) as Object
 return session
end function
function FixtureSeekClock() as Object
 return {Mark:sub()
  m.top.fixtureElapsed=0
 end sub,TotalMilliseconds:function() as Integer
  return m.top.fixtureElapsed
 end function,top:m}
end function
function SaveSession(provider as String, session as Object, revision as Integer) as Boolean
 if revision<>m.fixtureRevision then return false
 m.fixtureSession=session
 return true
end function
function RunSeekScenario(session as Object, params as Object, responses as Object, config as Object) as Object
 m.requests=[]:m.timeouts=[]:m.responses=responses:m.fixtureRevision=0:m.changeRevision=false:m.fixtureElapsed=0
 m.fixtureSession=session:m.top={cancelled:false}
 device=FixtureSiloDevice():device.uuids=[]
 if config.dvQuery=true then device.videoMode="2160p60"
 for i=1 to 30
  device.uuids.Push("10000000-0000-4000-8000-"+Right("000000000000"+i.ToStr(),12))
 end for
 scope={provider:"silo",sourceId:session.sourceId,profileId:session.profileId,generation:7,requestId:41}
 m.top.job=scope
 start=ExecuteApiAction("silo","playback_start",params,scope)
 if start.ok<>true then return {start:start,requests:m.requests}
 start=TaskSiloPrepareSelectedSubtitle(start,scope)
 captured=SpCopy(start.plan)
 if config.planPatch<>invalid
  for each key in config.planPatch
   start.plan[key]=config.planPatch[key]
  end for
 end if
 seek={sessionId:start.plan.sessionId,plan:start.plan,positionMs:config.targetMs,replanRequestId:config.operationId}
 if config.extra<>invalid then seek[config.extra]="unexpected"
 action="playback_seek_reanchor"
 if config.action<>invalid
  action=config.action
  if action="playback_replan" then seek["qualityPreference"]="720p"
  if action="playback_audio_select" then seek["audioTrackIndex"]=1
  if action="playback_subtitle_select" then seek["subtitleTrackId"]="file:f1:subtitle:1":seek["subtitleTrackIndex"]=1
 end if
 outcome=ExecuteApiAction("silo",action,seek,scope)
 if config.repeat=true and outcome.ok=true
  seek={sessionId:outcome.plan.sessionId,plan:outcome.plan,positionMs:20250,replanRequestId:"20000000-0000-4000-8000-000000000002"}
  outcome=ExecuteApiAction("silo","playback_seek_reanchor",seek,scope)
 end if
 return {start:captured,outcome:outcome,requests:m.requests,timeouts:m.timeouts}
end function
'''
class SiloSeekReanchorTaskTests(unittest.TestCase):
 def decision(self,target=0,origin=0,plan_id='plan-0001',key='plan-key-0001'):
  raw=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
  raw['session_id']='session-0001'
  p=raw['playback_plan'];p.update(plan_id=plan_id,plan_attempt_key=key,delivery='server_remux_hls',
   available_qualities=[{'label':'original','preserves_source':True},{'label':'720p','preserves_source':False,'height':720,'bitrate_kbps':4000}],
   selected_tracks={'audio':{'id':'file:f1:audio:0','index':0}},
   effective_recipe={'video_codec':'hevc','video_sample_entry':'hvc1','audio_codec':'eac3','audio_channels':6,'dynamic_range':'hdr10','width':3840,'height':2160},
   transformations=[{'name':'hls_separate_audio','executor':'server','recipe_version':'1'}],subtitle={'mode':'off'},
   claims={'video':{'hdr10':True,'hdr10_plus':False,'hlg':False,'dolby_vision':False},'audio':{'codec':'eac3','passthrough':True,'atmos_preserved':False},'subtitles':{'ass_styling_preserved':False,'bitmap_overlay':False,'bitmap_sidecar':False}},applied_quirks=[],runtime_corrections=[])
  # The copy recipe retains this explicitly declared EAC3-six source count
  # (stock recipeFromSourceV3 publishes known positive AudioChannels).
  p['source'].update(duration_seconds=7200,container='mkv',dynamic_range='hdr10',audio_codec='eac3',audio_channels=6)
  p['stream'].update(protocol='hls',container='hls',url='/api/v2/playback/transcode/session-0001/master.m3u8?st=synthetic')
  p['timeline']={'source_start_seconds':target,'stream_origin_seconds':origin,'player_start_seconds':max(0,target-origin),'timeline_offset_seconds':origin,'seek_window_start_seconds':origin,'can_seek_anywhere':False,'seek_restoration':'source_position'}
  return raw
 def run_seek(self,*,returned=None,cap_features=None,config=None,responses=None,initial=None,detail=None):
  session={'baseUrl':'https://silo.example','sourceId':'silo:synthetic','profileId':'owner','deviceId':'fixture-device','accessToken':'synthetic-access','refreshToken':'synthetic-refresh','profileToken':'synthetic-profile'}
  cap=json.loads((ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text())
  cap.update(installation_id='install-0001',features=['native_hls_separate_audio_v1','seek_reanchor_v1'] if cap_features is None else cap_features,deliveries=['original_http','server_remux_hls'])
  replies=[{'statusCode':200,'body':json.dumps(cap)},{'statusCode':200,'body':json.dumps(self.decision() if initial is None else initial)}]
  if detail is not None:replies.append({'statusCode':200,'body':json.dumps(detail)})
  if (config or {}).get('action'):replies.append({'statusCode':200,'body':json.dumps(cap)})
  replies+=responses if responses is not None else [{'statusCode':200,'body':json.dumps(self.decision(125.375,124)) if returned is None else json.dumps(returned)}]
  cfg={'targetMs':125375,'operationId':SEEK_ID,**(config or {})}
  boundary=playback.BOUNDARIES.replace('response = m.responses.Shift()', '''response = m.responses.Shift()
    m.fixtureElapsed=m.fixtureElapsed+TaskValue(response,"elapsedMs",0)
    if TaskValue(response,"cancel",false) then m.top.cancelled=true
    if TaskValue(response,"revisionChanged",false) then m.fixtureRevision=m.fixtureRevision+1
    if TaskValue(response,"profileChanged",false) then m.fixtureSession["profileToken"]="changed"''')
  with tempfile.TemporaryDirectory() as d:
   t=Path(d);files=[]
   for p in [*playback.FILES,ROOT/'source/core/SiloUIPlaybackChoicesPolicy.brs',ROOT/'components/ApiTask.brs',ROOT/'source/network/Http.brs']:
    local=t/p.name;src=p.read_text().replace('function TaskDeviceSession(','function UnusedTaskDeviceSession(',1).replace('function TaskRokuSiloContext(','function UnusedTaskRokuSiloContext(',1).replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()').replace('CreateObject("roTimespan")','FixtureSeekClock()')
    if p.name=='Http.brs':src=src.replace('function HttpRequest(','function UnusedHttpRequest(',1)
    local.write_text(src);files.append(local)
   f=t/'boundary.brs';f.write_text(boundary.replace('function TaskUniqueId(','function UnusedFixtureTaskUniqueId(',1)+WRAPPER);files.append(f)
   return run_function(files,'RunSeekScenario',[session,{'itemId':'c1','fileId':'f1','startPositionMs':0},replies,cfg],root=t)
 def test_real_start_then_single_same_lease_seek_preserves_exact_request_authority(self):
  v=self.run_seek();self.assertTrue(v['outcome']['ok'],v)
  self.assertEqual(['GET','POST','POST'],[r['method'] for r in v['requests']])
  start=json.loads(v['requests'][1]['body']);body=json.loads(v['requests'][2]['body'])
  self.assertEqual('seek_reanchor',body['operation']);self.assertEqual(125.375,body['position_seconds'])
  self.assertEqual(SEEK_ID,body['replan_request_id']);self.assertEqual(1,body['attempt_count'])
  self.assertEqual(['plan-key-0001'],body['attempted_plan_keys'])
  self.assertEqual('/api/v2/playback/session-0001/replan',v['requests'][2]['url'].split('https://silo.example')[1])
  for key in ['client_capabilities','client_playback_context','client_features','quality_preference','playback_attempt_id','installation_id']:
   self.assertEqual(start[key],body[key],key)
  p=v['outcome']['plan'];self.assertEqual(124000,p['timelineOffsetMs']);self.assertEqual(1375,p['startPositionMs'])
  self.assertEqual(0,p['siloPlayback']['attemptCount']);self.assertEqual([],p['siloPlayback']['attemptedPlanKeys'])
 def test_timeline_and_exact_bounded_authority_survive_start_and_returned_seek(self):
  v=self.run_seek();p=v['outcome']['plan'];d=p['seekReanchor']
  self.assertEqual(125375,p.get('sourceStartMs'));self.assertEqual(124000,p.get('streamOriginMs'))
  self.assertEqual(124000,p['seekWindowStartMs']);self.assertNotIn('seekWindowEndMs',p)
  self.assertEqual('source_position',p['seekRestoration'])
  wire=json.loads(v['requests'][1]['body'])
  for key in ['client_capabilities','client_playback_context','client_features','quality_preference','metered']:
   self.assertEqual(wire[key],v['start']['seekReanchor']['request'][key])
  text=json.dumps(d)
  for private in ['synthetic-access','synthetic-profile','https://','master.m3u8','Authorization','url','headers']:
   self.assertNotIn(private,text)
 def test_missing_feature_or_descriptor_never_posts(self):
  for config,features in [({'planPatch':{'seekReanchor':None}},None),({},['native_hls_separate_audio_v1']),({},['native_hls_separate_audio_v1']+['unknown']*65)]:
   with self.subTest(config=config,features=features):
    v=self.run_seek(config=config,cap_features=features)
    self.assertFalse(v['outcome']['ok']);self.assertEqual(['GET','POST'],[r['method'] for r in v['requests']])
 def test_changed_immutable_receipt_is_uncertain_without_publishing_media(self):
  for field in ['session','file','tracks','recipe','source','claims','quirk','subtitle','plan','key','feature','timeline']:
   with self.subTest(field=field):
    raw=self.decision(125.375,124);p=raw['playback_plan']
    if field=='session':raw['session_id']='foreign-session'
    elif field=='file':p['effective_media_file_id']='f2'
    elif field=='tracks':p['selected_tracks']['audio']['index']=2
    elif field=='recipe':p['effective_recipe']['audio_codec']='aac'
    elif field=='source':p['source']['audio_channels']=2
    elif field=='claims':p['claims']['audio']['atmos_preserved']=True
    elif field=='quirk':p['applied_quirks']=[{'id':'q','registry_revision':'2','action':'change'}]
    elif field=='subtitle':p['subtitle']={'mode':'render','track_id':'other'}
    elif field=='plan':p['plan_id']='plan-0002'
    elif field=='key':p['plan_attempt_key']='plan-key-0002'
    elif field=='feature':raw['server_features']=[]
    elif field=='timeline':p['timeline']['stream_origin_seconds']=123
    v=self.run_seek(returned=raw)
    self.assertFalse(v['outcome']['ok'],v);self.assertTrue(v['outcome']['leaseUncertain']);self.assertNotIn('plan',v['outcome'])
    self.assertEqual(['GET','POST','POST'],[r['method'] for r in v['requests']])
 def test_invalid_ingress_is_refused_before_mutation(self):
  for cfg in [{'targetMs':-1},{'targetMs':'125375'},{'targetMs':7200000},{'operationId':'not-a-uuid'},{'extra':'qualityPreference'}]:
   v=self.run_seek(config=cfg);self.assertFalse(v['outcome']['ok']);self.assertEqual(2,len(v['requests']))
 def test_one_auth_refresh_replays_the_exact_body_inside_one_budget(self):
  refresh={'access_token':'synthetic-refreshed','refresh_token':'synthetic-refresh'}
  v=self.run_seek(responses=[{'statusCode':401,'body':'{}','elapsedMs':20000},
   {'statusCode':200,'body':json.dumps(refresh),'elapsedMs':5000},
   {'statusCode':200,'body':json.dumps(self.decision(125.375,124)),'elapsedMs':1000}])
  self.assertTrue(v['outcome']['ok'],v)
  self.assertEqual(['GET','POST','POST','POST','POST'],[r['method'] for r in v['requests']])
  self.assertEqual(v['requests'][2]['body'],v['requests'][4]['body'])
  self.assertEqual([43750,9000,18750],v['timeouts'][2:])
 def test_post_exception_and_late_success_retain_known_lease_and_control_authority(self):
  for effect,code in [({'throws':True},'task_failed'),({'elapsedMs':44000},'network_timeout'),({'cancel':True},'cancelled'),({'revisionChanged':True},'session_changed'),({'profileChanged':True},'session_changed')]:
   with self.subTest(effect=effect):
    response={'statusCode':200,'body':json.dumps(self.decision(125.375,124)),**effect}
    v=self.run_seek(responses=[response]);o=v['outcome']
    self.assertFalse(o['ok']);self.assertEqual(code,o['errorCode']);self.assertTrue(o['leaseUncertain']);self.assertEqual('session-0001',o['knownLease']['sessionId']);self.assertNotIn('plan',o)
    if not effect.get('throws'):self.assertEqual('plan-0001',o['controlReceipt']['planId'])
    self.assertEqual(3,len(v['requests']))
 def test_actual_server_optional_mime_and_dv_base_proof_are_preserved(self):
  initial=self.decision();returned=self.decision(125.375,124)
  for raw in (initial,returned):
   raw['playback_plan']['stream']['mime_type']='application/vnd.apple.mpegurl'
   raw['playback_plan']['source']['dv_base_layer_proven']=True
   raw['playback_plan']['subtitle_fidelity_policy']='require_authored_fidelity'
  v=self.run_seek(initial=initial,returned=returned)
  self.assertTrue(v['outcome']['ok'],v)
  self.assertEqual('application/vnd.apple.mpegurl',v['outcome']['plan']['seekReanchor']['route']['mime_type'])
 def test_successive_seeks_get_new_uuids_and_do_not_consume_failure_history(self):
  v=self.run_seek(config={'repeat':True},responses=[{'statusCode':200,'body':json.dumps(self.decision(125.375,124))},{'statusCode':200,'body':json.dumps(self.decision(20.25,20.1915))}])
  self.assertTrue(v['outcome']['ok'],v)
  bodies=[json.loads(r['body']) for r in v['requests'][2:]]
  self.assertEqual([1,1],[b['attempt_count'] for b in bodies]);self.assertNotEqual(bodies[0]['replan_request_id'],bodies[1]['replan_request_id']);self.assertNotEqual(bodies[0]['plan_attempt_id'],bodies[1]['plan_attempt_id'])
  self.assertTrue(all(not b['plan_attempt_id'].startswith('roku-') for b in bodies))
  self.assertEqual(0,v['outcome']['plan']['siloPlayback']['attemptCount'])
 def test_accepted_quality_replan_updates_exact_request_snapshot_and_receipt(self):
  raw=self.decision(125.375,124,plan_id='plan-0002',key='plan-key-0002')
  v=self.run_seek(returned=raw,config={'action':'playback_replan'})
  self.assertTrue(v['outcome']['ok'],v)
  p=v['outcome']['plan'];d=p.get('seekReanchor')
  self.assertIsNotNone(d)
  self.assertEqual('plan-0002',d['control']['planId']);self.assertEqual('720p',d['request']['quality_preference'])
  self.assertEqual(json.loads(v['requests'][-1]['body'])['client_capabilities'],d['request']['client_capabilities'])
 def test_features_dropped_by_later_replan_clear_descriptor_without_breaking_playback(self):
  raw=self.decision(125.375,124,plan_id='plan-0002',key='plan-key-0002');raw['server_features']=[]
  v=self.run_seek(returned=raw,config={'action':'playback_replan'})
  self.assertTrue(v['outcome']['ok'],v);self.assertNotIn('seekReanchor',v['outcome']['plan'])
 def test_http_refusals_and_repeated_unauthorized_never_try_another_route(self):
  for status in [403,409,408,503]:
   v=self.run_seek(responses=[{'statusCode':status,'body':'{}'}]);self.assertFalse(v['outcome']['ok']);self.assertTrue(v['outcome']['leaseUncertain']);self.assertEqual(3,len(v['requests']))

class SiloSeekPublicationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from tests.test_silo_selected_subtitle_receipt import selected
  helper=SiloSeekReanchorTaskTests();cls.helper=helper
  initial=helper.decision();cls.returned=helper.decision(125.375,0)
  for raw in [initial,cls.returned]:
   raw['playback_plan'].update(selected(file_id='f1'))
   artifact=raw['playback_plan']['subtitle']['artifact']
   artifact.update(url='/api/v2/stream/session-0001/subtitles/1.srt?file_id=f1',format='srt',mime_type='application/x-subrip')
   raw['playback_plan']['subtitle']['inventory'][1]['url']=artifact['url']
  value=helper.run_seek(initial=initial,returned=cls.returned)
  if not value['outcome']['ok']:raise AssertionError(value)
  cls.plan=value['start']
 def run_job(self,**scenario):
  from tests import test_silo_selected_subtitle_prepare as prepare
  plan=copy.deepcopy(self.plan)
  session={'baseUrl':'https://silo.example','sourceId':'silo:synthetic','profileId':'owner','deviceId':'fixture-device','accessToken':'synthetic-access','profileToken':'synthetic-profile'}
  job={'provider':'silo','action':'playback_seek_reanchor','sourceId':'silo:synthetic','profileId':'owner','generation':7,'requestId':57,
   'params':{'sessionId':'session-0001','plan':plan,'positionMs':125375,'replanRequestId':SEEK_ID}}
  response={'statusCode':200,'body':json.dumps(self.returned),'elapsedMs':40000}
  return prepare.SelectedSubtitlePreparationTests().run_job(job_override=job,session_override=session,responses_override=[response],scenario={'keepFile':True,'headers':{'Content-Type':'application/x-subrip'},'body':'1\n00:00:00,000 --> 00:00:05,000\nSynthetic\n',**scenario},recovery_clock=True)
 def test_real_job_publishes_scoped_ready_artifact_inside_seek_budget(self):
  v=self.run_job(publicationDelayMs=14999);o=v['outcome']
  self.assertTrue(o['ok'],v);self.assertEqual(('playback_seek_reanchor',57,7,0),tuple(o[k] for k in ['action','requestId','generation','sessionRevision']))
  self.assertEqual(o['plan']['subtitleArtifact']['uri'],v['binding']['uri'])
  self.assertEqual(57,o['plan']['subtitleArtifact']['owner']['requestId']);self.assertEqual(1,len(v['requests']))
 def test_real_job_retires_only_owned_artifact_at_total_deadline(self):
  v=self.run_job(publicationDelayMs=15000);o=v['outcome']
  self.assertFalse(o['ok']);self.assertEqual('network_timeout',o['errorCode']);self.assertTrue(o['leaseUncertain']);self.assertNotIn('plan',o)
  self.assertEqual('plan-0001',o['controlReceipt']['planId']);self.assertIsNone(v['binding'])
  self.assertEqual(['tmp:/silo-subtitle-11111111-1111-4111-8111-111111111111.vtt'],v['files'])
 def test_real_job_final_profile_token_change_refuses_publication(self):
  v=self.run_job(profileBeforePublication=True);o=v['outcome']
  self.assertFalse(o['ok']);self.assertEqual('session_changed',o['errorCode']);self.assertTrue(o['leaseUncertain']);self.assertNotIn('plan',o)

class SiloSeekDescriptorFenceTests(unittest.TestCase):
 def test_stale_or_credential_bearing_descriptor_refuses_before_http(self):
  helper=SiloSeekReanchorTaskTests();base=helper.run_seek()['start']
  for change in ['route_url','route_file','owner','control','top_plan']:
   with self.subTest(change=change):
    plan=copy.deepcopy(base)
    if change=='route_url':plan['seekReanchor']['route']['source']['url']='https://private.invalid'
    elif change=='route_file':plan['seekReanchor']['route']['source']['media_file_id']='other'
    elif change=='owner':plan['seekReanchor']['owner']['generation']=8
    elif change=='control':plan['seekReanchor']['control']['planId']='stale-plan'
    elif change=='top_plan':plan['planId']='stale-plan'
    v=helper.run_seek(config={'planPatch':plan})
    self.assertFalse(v['outcome']['ok']);self.assertEqual(2,len(v['requests']));self.assertNotIn('leaseUncertain',v['outcome'])

class SiloSeekRefreshFenceTests(unittest.TestCase):
 def test_refresh_authority_changes_and_second_unauthorized_are_bounded(self):
  helper=SiloSeekReanchorTaskTests()
  refresh={'access_token':'synthetic-refreshed','refresh_token':'synthetic-refresh'}
  for effect in [{'profileChanged':True},{'revisionChanged':True}]:
   v=helper.run_seek(responses=[{'statusCode':401,'body':'{}'}, {'statusCode':200,'body':json.dumps(refresh),**effect}])
   self.assertFalse(v['outcome']['ok']);self.assertTrue(v['outcome']['leaseUncertain']);self.assertEqual(4,len(v['requests']))
  v=helper.run_seek(responses=[{'statusCode':401,'body':'{}'},{'statusCode':200,'body':json.dumps(refresh)},{'statusCode':401,'body':'{}'}])
  self.assertFalse(v['outcome']['ok']);self.assertTrue(v['outcome']['leaseUncertain']);self.assertEqual(5,len(v['requests']))
  self.assertEqual(v['requests'][2]['body'],v['requests'][4]['body'])
 def test_eight_prior_failures_are_not_a_lifetime_seek_cap(self):
  helper=SiloSeekReanchorTaskTests();p=helper.run_seek()['start']
  p['siloPlayback']['attemptCount']=8;p['seekReanchor']['control']['attemptCount']=8
  v=helper.run_seek(config={'planPatch':p})
  self.assertTrue(v['outcome']['ok'],v);self.assertEqual(8,v['outcome']['plan']['siloPlayback']['attemptCount'])
  self.assertEqual(1,json.loads(v['requests'][-1]['body'])['attempt_count'])

class SiloSeekFeatureBoundsTests(unittest.TestCase):
 def test_unknown_safe_additive_features_are_bounded_but_urls_disable_retention(self):
  helper=SiloSeekReanchorTaskTests()
  safe=['native_hls_separate_audio_v1','seek_reanchor_v1','future_safe_v9']
  v=helper.run_seek(cap_features=safe);self.assertTrue(v['outcome']['ok'],v)
  v=helper.run_seek(cap_features=safe+['https://private.invalid/token'])
  self.assertNotIn('seekReanchor',v['start']);self.assertFalse(v['outcome']['ok']);self.assertEqual(2,len(v['requests']))

class SiloSeekDVAuthorityTests(unittest.TestCase):
 def test_actual_dv_sdk_request_supports_p7_receipt_and_seek(self):
  helper=SiloSeekReanchorTaskTests();initial=helper.decision();returned=helper.decision(125.375,124)
  for raw in [initial,returned]:
   p=raw['playback_plan']
   # SourceDescriptor remains the original P7/compat6/level6; typed recipe v1
   # proves delivered P8/compat1. It does not rewrite the source descriptor.
   p['source'].update(dynamic_range='dolby_vision',dolby_vision_profile=7,dolby_vision_level=6,
    dv_bl_compat_id=6,dv_base_layer_proven=True,dv_enhancement_layer='FEL')
   p['effective_recipe'].update(dynamic_range='dolby_vision',video_sample_entry='dvh1')
   p['transformations'].append({'name':'server_dv7_to_dv81','executor':'server','recipe_version':'1'})
   p['claims']['video'].update(hdr10=False,dolby_vision=True)
  v=helper.run_seek(initial=initial,returned=returned,config={'dvQuery':True},cap_features=['native_hls_separate_audio_v1','server_dv7_to_dv81_v1','seek_reanchor_v1'])
  self.assertTrue(v['outcome']['ok'],v)
  wire=json.loads(v['requests'][1]['body']);self.assertIn('server_dv7_to_dv81_v1',wire['client_features'])
  details=wire['client_playback_context']['deliveries']['hls']['hdr_details']
  self.assertTrue(any(row['profile']==8 and row['bl_compatibility_ids']==[1] for row in details['dolby_vision_profile_levels']))
  self.assertEqual(wire['client_playback_context'],json.loads(v['requests'][-1]['body'])['client_playback_context'])

class SiloSeekTrackAuthorityTests(unittest.TestCase):
 def test_actual_audio_change_then_seek_retains_new_track_and_negotiation(self):
  helper=SiloSeekReanchorTaskTests();changed=helper.decision(125.375,124,plan_id='plan-0002',key='plan-key-0002');next_seek=helper.decision(20.25,20.1915,plan_id='plan-0002',key='plan-key-0002')
  detail=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
  detail['versions'][0]['audio_tracks']=[{'index':0,'codec':'eac3','channels':6,'language':'eng'},{'index':1,'codec':'aac','channels':2,'language':'eng'}]
  for raw in [changed,next_seek]:
   p=raw['playback_plan'];p['selected_tracks']['audio']={'id':'file:f1:audio:1','index':1};p['source'].update(audio_codec='aac',audio_channels=2);p['effective_recipe'].update(audio_codec='aac',audio_channels=2);p['claims']['audio'].update(codec='aac',passthrough=False)
  v=helper.run_seek(config={'action':'playback_audio_select','repeat':True},detail=detail,responses=[{'statusCode':200,'body':json.dumps(changed)},{'statusCode':200,'body':json.dumps(next_seek)}])
  self.assertTrue(v['outcome']['ok'],v)
  bodies=[json.loads(r['body']) for r in v['requests'] if r['method']=='POST']
  self.assertEqual(['track_change','seek_reanchor'],[b['operation'] for b in bodies[1:]])
  self.assertEqual({'id':'file:f1:audio:1','index':1},bodies[-1]['selected_tracks']['audio'])
  self.assertIn('seek_reanchor_v1',bodies[1]['client_features']);self.assertEqual(1,v['outcome']['plan']['siloPlayback']['attemptCount'])
 def test_actual_subtitle_on_then_seek_retains_new_selector_and_negotiation(self):
  from tests.test_silo_selected_subtitle_receipt import selected
  helper=SiloSeekReanchorTaskTests();initial=helper.decision();selection=selected(file_id='f1')
  initial['playback_plan']['subtitle']={'mode':'off','inventory':selection['subtitle']['inventory']}
  changed=helper.decision(125.375,124,plan_id='plan-0002',key='plan-key-0002');next_seek=helper.decision(20.25,20.1915,plan_id='plan-0002',key='plan-key-0002')
  for raw in [changed,next_seek]:raw['playback_plan'].update(copy.deepcopy(selection))
  v=helper.run_seek(initial=initial,config={'action':'playback_subtitle_select','repeat':True},responses=[{'statusCode':200,'body':json.dumps(changed)},{'statusCode':200,'body':json.dumps(next_seek)}])
  self.assertTrue(v['outcome']['ok'],v)
  bodies=[json.loads(r['body']) for r in v['requests'] if r['method']=='POST']
  self.assertEqual(['track_change','seek_reanchor'],[b['operation'] for b in bodies[1:]])
  self.assertEqual({'id':'file:f1:subtitle:1','index':1},bodies[-1]['selected_tracks']['subtitle'])
  self.assertIn('seek_reanchor_v1',bodies[1]['client_features']);self.assertEqual(1,v['outcome']['plan']['siloPlayback']['attemptCount'])

class SiloSeekScalarReceiptTests(unittest.TestCase):
 def test_malformed_optional_route_scalars_disable_descriptor_only(self):
  helper=SiloSeekReanchorTaskTests()
  for key,value in [('mime_type','https://private.invalid/token'),('mime_type',{'url':'https://private.invalid/token'}),('subtitle_fidelity_policy','https://private.invalid/token'),('subtitle_fidelity_policy',{'url':'https://private.invalid/token'}),('header_refresh',{'url':'https://private.invalid/token'})]:
   with self.subTest(key=key,value=value):
    initial=helper.decision()
    if key=='subtitle_fidelity_policy':initial['playback_plan'][key]=value
    else:initial['playback_plan']['stream'][key]=value
    v=helper.run_seek(initial=initial)
    self.assertNotIn('seekReanchor',v['start']);self.assertFalse(v['outcome']['ok']);self.assertEqual(2,len(v['requests']))

class SiloSeekNullableTransformationTests(unittest.TestCase):
 def test_server_null_claims_start_retains_descriptor_and_seeks_same_lease(self):
  # Server TransformationV3's nil []string serializes as null; empty means no claims.
  helper=SiloSeekReanchorTaskTests();initial=helper.decision();returned=helper.decision(125.375,124)
  initial['playback_plan']['transformations'][0]['validated_claims']=None
  returned['playback_plan']['transformations'][0]['validated_claims']=[]
  v=helper.run_seek(initial=initial,returned=returned)
  self.assertIn('seekReanchor',v['start'])
  self.assertTrue(v['outcome']['ok'],v)
  self.assertEqual(['GET','POST','POST'],[r['method'] for r in v['requests']])
  self.assertEqual('seek_reanchor',json.loads(v['requests'][-1]['body'])['operation'])
  self.assertEqual('session-0001',v['outcome']['plan']['sessionId'])
  self.assertNotIn('validated_claims',v['start']['seekReanchor']['route']['transformations'][0])
 def test_malformed_transformation_claims_do_not_enable_seek(self):
  helper=SiloSeekReanchorTaskTests()
  cases=[{'name':None},{'executor':None},{'recipe_version':None},{'unknown':None},
         {'validated_claims':'claim'},{'validated_claims':{}},{'validated_claims':[None]},
         {'validated_claims':['https://private.invalid/token']}]
  for patch in cases:
   with self.subTest(patch=patch):
    initial=helper.decision();initial['playback_plan']['transformations'][0].update(patch)
    v=helper.run_seek(initial=initial)
    self.assertNotIn('seekReanchor',v['start']);self.assertFalse(v.get('outcome',{}).get('ok'));self.assertFalse(any('/replan' in r['url'] for r in v['requests']))
 def test_null_source_or_capability_field_does_not_enable_seek(self):
  helper=SiloSeekReanchorTaskTests()
  initial=helper.decision();initial['playback_plan']['source']['audio_codec']=None
  v=helper.run_seek(initial=initial)
  self.assertNotIn('seekReanchor',v.get('start',{}));self.assertEqual(2,len(v['requests']))
  base=helper.run_seek()['start'];base['seekReanchor']['request']['client_capabilities']['codecs_video']=None
  v=helper.run_seek(config={'planPatch':base})
  self.assertFalse(v.get('outcome',{}).get('ok'));self.assertEqual(2,len(v['requests']))
