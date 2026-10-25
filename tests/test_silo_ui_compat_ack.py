"""Actual reviewed079 ACK envelope→Scene→same persistent holder unused-close."""
import copy,json,unittest
from tests import test_silo_compat_owned_refusal as native
from tests import test_silo_compat_continuation as inventory
from tests import test_silo_compat_playback_task as holder
class AcknowledgedCompatScene(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.native=native.OwnedRefusal().start()
  _,cls.wire,_=inventory.CompatContinuation().fixture()
 def scene(self,mutate=None,control='',duplicate=None):
  envelope=copy.deepcopy(self.native['outcome'])
  if mutate:mutate(envelope)
  return holder.CompatPlaybackTask().transcript(scene=dict(envelope=envelope,wire=copy.deepcopy(self.wire),control=control,duplicateEnvelope=duplicate))
 def test_actual_owned_native_stop_ack_enters_same_pinned_unused_holder(self):
  requests=self.native['requests']
  self.assertEqual(['GET','GET','POST','DELETE'],[q['method'] for q in requests])
  self.assertEqual(['731'],[json.loads(q['body'])['file_id'] for q in requests if '/playback/start' in q['url']])
  r=self.scene();self.assertTrue(r['scene']['holderCreated'],'receipt-derived ACK must reach actual Scene holder')
  self.assertEqual(['prepared','closed'],[x['phase'] for x in r['results']])
  self.assertTrue(r['scene']['released']);self.assertFalse(r['scene']['bound']);self.assertEqual(0,r['mediaRequests'])
  self.assertTrue(r['results'][-1]['credentialRevoked']);self.assertFalse(any(q['method']=='DELETE' or '.m3u8' in q['url'] for q in r['requests']))

 def test_confirmed_unused_close_retains_one_bounded_attempt_history(self):
  r=self.scene();a=r['scene']['attempt']
  self.assertIsInstance(a,dict)
  self.assertEqual(('731','fixture-item',1,True,False,['731'],'closed'),(a['fileId'],a['itemId'],a['playToken'],a['compatibilityAttempted'],a['resumeConsumed'],a['nativeAttemptedFileIds'],a['phase']))
  self.assertEqual(self.native['outcome']['compatContinuation']['owner'],a['owner'])

 def test_fresh_request_and_attempt_cannot_repeat_the_consumed_foreground_intent(self):
  second=native.OwnedRefusal().start(scope={'requestId':42},device={'"10000000-0000-4000-8000-"':'"20000000-0000-4000-8000-"'})['outcome']
  self.assertNotEqual(self.native['outcome']['compatContinuation']['playbackAttemptId'],second['compatContinuation']['playbackAttemptId'])
  r=self.scene(control='duplicate',duplicate=second)
  self.assertEqual(1,r['scene']['holderCount']);self.assertTrue(r['scene']['released']);self.assertFalse(r['scene']['loading'])
  self.assertEqual(41,r['scene']['attempt']['requestId']);self.assertFalse(r['scene']['attempt']['resumeConsumed'])

 def test_genuine_new_foreground_intent_after_drain_can_have_a_new_bounded_attempt(self):
  second=native.OwnedRefusal().start(scope={'requestId':43,'generation':8},device={'"10000000-0000-4000-8000-"':'"30000000-0000-4000-8000-"'})['outcome']
  r=self.scene(control='new_intent',duplicate=second)
  self.assertEqual(2,r['scene']['holderCount']);self.assertEqual(8,r['scene']['attempt']['owner']['generation']);self.assertEqual(3,r['scene']['attempt']['playToken'])

 def test_missing_or_malformed_closure_authority_never_allocates_holder(self):
  cases=[]
  for field in ('sessionId','installationId','stopId','owner','requestId','playbackAttemptId'):
   cases.append((field,lambda e,f=field:e['compatContinuation']['nativeClosure'].pop(f)))
  for field,value in (('sessionId','https://untrusted.example'),('sessionId','native\n'),('sessionId',12),('installationId',''),('stopId','not-a-canonical-uuid')):
   cases.append((str((field,value)),lambda e,f=field,v=value:e['compatContinuation']['nativeClosure'].__setitem__(f,v)))
  for name,mutate in cases:
   with self.subTest(case=name):self.assertFalse(self.scene(mutate=mutate)['scene']['holderCreated'])
 def test_closure_scope_request_attempt_and_posted_file_must_match(self):
  cases=[]
  for field,value in (('sourceId','silo:other'),('profileId','other'),('generation',8),('sessionRevision',1),('sessionRevision',False)):
   cases.append((field,lambda e,f=field,v=value:e['compatContinuation']['nativeClosure']['owner'].__setitem__(f,v)))
  for field,value in (('requestId',42),('requestId',True),('playbackAttemptId','other-attempt')):
   cases.append((field,lambda e,f=field,v=value:e['compatContinuation']['nativeClosure'].__setitem__(f,v)))
  cases.append(('posted_file',lambda e:e['compatContinuation'].__setitem__('nativeSelectedFileId','732')))
  cases.append(('lease_uncertain',lambda e:e.__setitem__('leaseUncertain',True)))
  for name,mutate in cases:
   with self.subTest(case=name):self.assertFalse(self.scene(mutate=mutate)['scene']['holderCreated'])
 def test_ack_does_not_clear_stale_output_token_transition_or_old_native_owner(self):
  for control in ('stale_token','output','transition','pending_stop','failed_stop','late_failed_stop'):
   with self.subTest(control=control):self.assertFalse(self.scene(control=control)['scene']['holderCreated'])
 def test_not_allocated_label_cannot_hide_explicit_native_lease_uncertainty(self):
  value=inventory.CompatContinuation().job()['outcome'];value['leaseUncertain']=True
  r=holder.CompatPlaybackTask().transcript(scene=dict(envelope=value,wire=copy.deepcopy(self.wire),control=''))
  self.assertFalse(r['scene']['holderCreated'])

 def test_node_failure_finishes_loading_but_keeps_attempt_consumed(self):
  r=self.scene(control='node_failure');self.assertFalse(r['scene']['holderCreated']);self.assertFalse(r['scene']['loading']);self.assertEqual('failed',r['scene']['attempt']['phase']);self.assertTrue(r['scene']['attempt']['compatibilityAttempted']);self.assertEqual([],r['requests'])
 def test_not_allocated_history_does_not_invent_a_native_4k_attempt(self):
  value=inventory.CompatContinuation().job()['outcome']
  r=holder.CompatPlaybackTask().transcript(scene=dict(envelope=value,wire=copy.deepcopy(self.wire),control=''))
  self.assertEqual([],r['scene']['attempt']['nativeAttemptedFileIds']);self.assertTrue(r['scene']['released']);self.assertFalse(r['scene']['attempt']['resumeConsumed'])

 def test_postclose_speculation_cannot_block_genuine_new_intent(self):
  second=native.OwnedRefusal().start(scope={'requestId':43,'generation':8},device={'"10000000-0000-4000-8000-"':'"30000000-0000-4000-8000-"'})['outcome']
  for control in ('postclose_video','postclose_hero'):
   with self.subTest(control=control):
    r=self.scene(control=control,duplicate=second)
    self.assertEqual(0,r['scene']['secondOwnerRequests']);self.assertEqual(2,r['scene']['holderCount']);self.assertEqual(3,r['scene']['attempt']['playToken'])
 def test_invalid_selector_does_not_erase_consumed_foreground_history(self):
  r=self.scene(control='invalid_selector')
  self.assertIsInstance(r['scene']['attempt'],dict);self.assertEqual(1,r['scene']['attempt']['playToken']);self.assertEqual('closed',r['scene']['attempt']['phase'])

 def test_pending_native_control_keeps_old_history_and_blocks_new_foreground(self):
  for action in ('playback_audio_select','playback_subtitle_select','playback_subtitle_off'):
   with self.subTest(action=action):
    r=self.scene(control='pending_control_'+action)
    self.assertEqual(0,r['scene']['secondOwnerRequests']);self.assertEqual(1,r['scene']['holderCount']);self.assertEqual(1,r['scene']['attempt']['playToken'])

 def test_unused_compat_preparation_refusal_retries_unattempted_same_source_once(self):
  value=inventory.CompatContinuation().job(mutate=lambda w,d:(w['versions'].__delitem__(slice(1,None)),w['playback_variants'][0]['parts'][0].__setitem__('versions',w['versions'])))['outcome']
  wire=copy.deepcopy(self.wire);wire['versions']=wire['versions'][:1];wire['playback_variants'][0]['parts'][0]['versions']=wire['versions']
  r=holder.CompatPlaybackTask().transcript(scene=dict(envelope=value,wire=wire,control=''),change=lambda v:v.__setitem__('metadata',{'MediaSources':[]}))
  jobs=r['scene']['resumeJobs']
  self.assertEqual(1,len(jobs))
  self.assertEqual([],jobs[0]['params']['excludedVersionIds'])
  self.assertEqual(['731'],jobs[0]['params']['compatExcludedFileIds'])
  self.assertTrue(r['scene']['attempt']['resumeConsumed'])
  self.assertEqual([],r['scene']['attempt']['nativeAttemptedFileIds'])

 def test_real_native_refusal_keeps_source_excluded_after_compat_preparation_failure(self):
  r=holder.CompatPlaybackTask().transcript(scene=dict(envelope=copy.deepcopy(self.native['outcome']),wire=copy.deepcopy(self.wire),control=''),change=lambda v:v.__setitem__('metadata',{'MediaSources':[]}))
  self.assertEqual(1,len(r['scene']['resumeJobs']))
  self.assertEqual(['731'],r['scene']['resumeJobs'][0]['params']['excludedVersionIds'])
  self.assertEqual(['731'],r['scene']['attempt']['nativeAttemptedFileIds'])

 def test_preparation_cleanup_uncertainty_or_cancel_never_resumes_native(self):
  def failed_logout(v):
   v['metadata']={'MediaSources':[]};v['statuses']={'compat/logout':503}
  for change,cancel in ((failed_logout,''),(None,'compat/metadata')):
   with self.subTest(cancel=cancel):
    r=holder.CompatPlaybackTask().transcript(scene=dict(envelope=copy.deepcopy(self.native['outcome']),wire=copy.deepcopy(self.wire),control=''),change=change,cancel_at=cancel)
    self.assertEqual([],r['scene']['resumeJobs'])
    self.assertFalse(r['scene']['attempt']['resumeConsumed'])

 def test_prior_native_exclusions_survive_compat_admission_and_preparation_failure(self):
  r=holder.CompatPlaybackTask().transcript(scene=dict(envelope=copy.deepcopy(self.native['outcome']),wire=copy.deepcopy(self.wire),control=''),change=lambda v:v.__setitem__('metadata',{'MediaSources':[]}),sdk_overrides={' m.fixtureNativeParams=params':' params["excludedVersionIds"]=["732"]\n m.fixtureNativeParams=params'})
  self.assertEqual(['732','731'],r['scene']['attempt']['nativeAttemptedFileIds'])
  self.assertEqual([],r['scene']['resumeJobs'])
  self.assertFalse(r['scene']['attempt']['resumeConsumed'])

 def test_mutated_resume_with_uncertain_native_allocation_still_blocks_next_play(self):
  from tests.test_silo_ui_compat_continuation import SiloUICompatContinuation
  SiloUICompatContinuation.setUpClass()
  old='''if child.job.action="playback_start"
     FixtureScheduleChild(child):m.fixtureNativeResults.Push(child.result):onApiResult(FixtureSceneEvent(child.result))
    end if'''
  new='''if child.job.action="playback_start"
     job=child.job:job.params.compatExcludedFileIds=[]:child.job=job
     failed={requestId:job.requestId,action:"playback_start",ok:false,errorCode:"unsupported_stream",sessionRevision:0,leaseUncertain:true}
     onApiResult(FixtureSceneEvent(failed))
     before=m.requestId:PlayItem(m.playItem,60000):m.fixtureBlockedStartDelta=m.requestId-before
    end if'''
  r=holder.CompatPlaybackTask().transcript(scene=dict(envelope=copy.deepcopy(SiloUICompatContinuation.envelope),wire=copy.deepcopy(SiloUICompatContinuation.wire),control='media_failure'),sdk_overrides={old:new})
  self.assertEqual(0,r['scene']['blockedStartDelta'])
  self.assertFalse(r['scene']['bound'])
