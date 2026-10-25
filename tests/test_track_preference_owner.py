"""Scoped preference owner behavior. Actual compact preference policy executes."""
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.brightscript import run_function, ROOT as R
R=Path(__file__).resolve().parents[1]; C=Path(__file__).resolve().parents[1]
SCOPE={'provider':'plex','sourceId':'plex:fixture-server','profileId':'owner','generation':7}

def pref(**kw):
 d={'schemaVersion':1,'sourceId':SCOPE['sourceId'],'profileId':'owner','subtitleMode':'auto','subtitleLanguage':'eng','subtitleName':'','audioLanguage':'','audioName':''};d.update(kw);return d

class PreferenceOwnerTests(unittest.TestCase):
 def call(self,fn,*args):
  with tempfile.TemporaryDirectory(prefix='silo-pref-owner-') as d:
   return run_function([R/'source/core/TrackPreference.brs',C/'source/core/TrackPreferenceOwnerPolicy.brs'],fn,list(args),root=Path(d))
 def create(self):return self.call('TpoCreate',SCOPE)
 def step(self,state,**event):return self.call('TpoReduce',state,event)
 def receipt(self,effect,ok=True,record=None,**changes):
  job={**effect['scope'],'action':effect['action'],'params':effect['params'],'preferenceOwner':effect['preferenceOwner'],'requestId':'mapped-1'}
  result={**job,'ok':ok,'data':{'preference':record or pref()}}
  result.update(changes)
  return {'kind':'result','job':job,'result':result}
 def test_read_emits_one_scoped_audited_job_and_typed_matching_receipt_is_loaded(self):
  loaded=self.step(self.create(),kind='load')
  self.assertEqual(1,len(loaded['effects']))
  effect=loaded['effects'][0];self.assertEqual('track_pref_get',effect['action'])
  self.assertEqual([],self.step(loaded['state'],kind='load')['effects'])
  done=self.call('TpoReduce',loaded['state'],self.receipt(effect,record=pref(subtitleMode='off')))
  self.assertTrue(done['state']['loaded']);self.assertEqual('off',done['state']['preference']['subtitleMode'])
 def test_late_read_after_manual_intent_does_not_override_local_preference_or_emit_native_effect(self):
  read=self.step(self.create(),kind='load')
  changed=self.step(read['state'],kind='mode',mode='off')
  self.assertEqual('off',changed['state']['preference']['subtitleMode'])
  late=self.call('TpoReduce',changed['state'],self.receipt(read['effects'][0]))
  self.assertEqual('off',late['state']['preference']['subtitleMode']);self.assertEqual(['track_pref_set'],[e['action'] for e in late['effects']])
 def test_mode_before_initial_read_preserves_actual_stored_audio_and_holds_latest_mode(self):
  read=self.step(self.create(),kind='load')
  off=self.step(read['state'],kind='mode',mode='off')
  self.assertEqual([],off['effects']);self.assertFalse(off['state']['loaded'])
  on=self.step(off['state'],kind='mode',mode='on')
  self.assertEqual([],on['effects'])
  stored=pref(subtitleMode='auto',audioLanguage='spa',audioName='Spanish')
  done=self.call('TpoReduce',on['state'],self.receipt(read['effects'][0],record=stored))
  self.assertTrue(done['state']['loaded']);self.assertEqual(1,len(done['effects']))
  saved=done['effects'][0]['params']['preference']
  self.assertEqual(('on','spa','Spanish'),(saved['subtitleMode'],saved['audioLanguage'],saved['audioName']))
 def test_native_manual_intent_retires_waiting_settings_mode_before_late_read(self):
  read=self.step(self.create(),kind='load')
  off=self.step(read['state'],kind='mode',mode='off')
  manual=self.step(off['state'],kind='manual_intent')
  done=self.call('TpoReduce',manual['state'],self.receipt(read['effects'][0],record=pref(audioLanguage='spa')))
  self.assertEqual([],done['effects']);self.assertFalse(done['state']['loaded'])
 def test_receipt_requires_actual_bool_and_exact_request_operation_action_params_viewer(self):
  read=self.step(self.create(),kind='load');self.assertEqual(1,len(read['effects']));effect=read['effects'][0]
  events=[]
  for changes in ({'ok':'true'},{'ok':1},{'requestId':'old'},{'sourceId':'plex:other'},{'profileId':'other'}, {'action':'track_pref_set'},{'params':{'preference':pref()}}):events.append(self.receipt(effect,**changes))
  wrong=self.receipt(effect);wrong['result']['preferenceOwner']={'operationId':'other'};events.append(wrong)
  for event in events:
   with self.subTest(event=event):
    outcome=self.call('TpoReduce',read['state'],event)
    self.assertFalse(outcome['accepted']);self.assertFalse(outcome['state']['loaded']);self.assertEqual([],outcome['effects'])
 def test_writes_are_bounded_to_one_inflight_and_latest_then_truthful_storage_receipts(self):
  ready=self.create();ready['loaded']=True
  first=self.step(ready,kind='mode',mode='off')
  self.assertEqual(1,len(first['effects']))
  second=self.step(first['state'],kind='mode',mode='on');third=self.step(second['state'],kind='mode',mode='auto')
  self.assertEqual([],second['effects']);self.assertEqual([],third['effects'])
  done=self.call('TpoReduce',third['state'],self.receipt(first['effects'][0],record=pref(subtitleMode='off')))
  self.assertEqual(1,len(done['effects']));self.assertEqual('auto',done['effects'][0]['params']['preference']['subtitleMode'])
  failed=self.call('TpoReduce',done['state'],self.receipt(done['effects'][0],ok=False,record=pref()))
  self.assertEqual('Could not save track preference.',failed['state']['status'])
 def test_actual_worker_envelope_needs_no_owner_params_or_revision_projection(self):
  read=self.step(self.create(),kind='load');effect=read['effects'][0]
  event=self.receipt(effect,record=pref(subtitleMode='off'))
  for key in ['params','preferenceOwner']:del event['result'][key]
  done=self.call('TpoReduce',read['state'],event)
  self.assertTrue(done['state']['loaded']);self.assertEqual('off',done['state']['preference']['subtitleMode'])
 def test_native_integer_aliases_keep_real_scope_numbers_and_finite_guards(self):
  for alias in ('roInteger','roLongInteger'):
   with tempfile.TemporaryDirectory(prefix='silo-pref-types-') as d:
    root=Path(d);policy=root/'policy.brs'
    source=(C/'source/core/TrackPreferenceOwnerPolicy.brs').read_text().replace('type(','FixtureType(')
    source+='\nfunction FixtureType(value as Dynamic) as String\n    kind=Type(value)\n    if kind="Integer" or kind="roInt" then return "'+alias+'"\n    return kind\nend function\nfunction FixtureTypes(scope as Object,values as Object) as Object\n    answers=[]\n    for each value in values\n        answers.Push(TpoWhole(value))\n    end for\n    return {scope:TpoScope(scope),answers:answers}\nend function\n'
    policy.write_text(source)
    result=run_function([R/'source/core/TrackPreference.brs',policy],'FixtureTypes',[SCOPE,[7,True,'7',{},[],1.5,1e30]],root=root)
    self.assertEqual(7,result['scope']['generation']);self.assertEqual([True,False,False,False,False,False,False],result['answers'])
 def test_settings_have_three_safe_scoped_modes_and_no_secret_fields(self):
  rows=self.call('TpoSettings',self.create())
  self.assertEqual(['subtitle_auto','subtitle_on','subtitle_off'],[r['uiAction'] for r in rows])
  self.assertTrue(rows[0]['title'].endswith('✓'))
  self.assertNotIn('trackId',str(rows));self.assertNotIn('url',str(rows))
 def test_pre_admission_dispatch_failure_releases_pending_without_saved_claim(self):
  ready=self.create();ready['loaded']=True
  issued=self.step(ready,kind='mode',mode='off')
  failed=self.call('TpoDispatchFailed',issued['state'],issued['effects'][0])
  self.assertIsNone(failed['state']['writePending']);self.assertEqual([],failed['effects'])
  self.assertEqual('Could not save track preference.',failed['state']['status'])
 def test_viewer_switch_retires_pending_and_requires_fresh_read(self):
  state=self.step(self.create(),kind='load')['state']
  rebound=self.step(state,kind='viewer',scope={**SCOPE,'profileId':'different'})
  self.assertFalse(rebound['state']['loaded']);self.assertIsNone(rebound['state']['readPending'])
  self.assertEqual('different',rebound['state']['preference']['profileId'])

class NativeOwnerPreferenceTests(unittest.TestCase):
 call=PreferenceOwnerTests.call
 create=PreferenceOwnerTests.create
 step=PreferenceOwnerTests.step
 receipt=PreferenceOwnerTests.receipt
 def native_command(self):return {'commandId':3,'attemptId':'play-1','versionId':'file-1','clipId':7,'inventoryRevision':2,'kind':'audio','intent':'select','handle':'a-2-1'}
 def test_manual_intent_emits_native_context_and_waits_for_applied_before_storage(self):
  state=self.create();state['loaded']=True
  issued=self.step(state,kind='manual',command=self.native_command())
  self.assertEqual(1,len(issued['effects']));self.assertEqual('native',issued['effects'][0]['kind'])
  self.assertIsNone(issued['state']['writePending'])
  current={k:self.native_command()[k] for k in ('attemptId','versionId','clipId','inventoryRevision')}
  snapshot={**current,'lastCommand':{'commandId':3,'accepted':True,'result':'issued'}}
  waiting=self.step(issued['state'],kind='native_result',snapshot=snapshot,current=current)
  self.assertEqual([],waiting['effects'])
  snapshot['lastCommand'].update(result='applied',preference=pref(audioLanguage='spa',audioName='Spanish'),preferenceRevision=issued['state']['revision'])
  done=self.step(waiting['state'],kind='native_result',snapshot=snapshot,current=current)
  self.assertEqual(1,len(done['effects']));self.assertEqual('track_pref_set',done['effects'][0]['action'])
 def test_manual_choice_before_initial_read_does_not_overwrite_unknown_stored_fields(self):
  issued=self.step(self.create(),kind='manual',command=self.native_command())
  self.assertFalse(issued['effects'][0]['command']['preferenceContext']['remember'])
  current={k:self.native_command()[k] for k in ('attemptId','versionId','clipId','inventoryRevision')}
  snapshot={**current,'lastCommand':{'commandId':3,'accepted':True,'result':'applied','preference':pref(audioLanguage='spa'),'preferenceRevision':issued['state']['revision']}}
  done=self.step(issued['state'],kind='native_result',snapshot=snapshot,current=current)
  self.assertEqual([],done['effects']);self.assertIsNone(done['state']['writePending'])
 def test_stale_native_ack_cannot_remember_or_release_new_pending_manual_owner(self):
  issued=self.step(self.create(),kind='manual',command=self.native_command())
  self.assertEqual(1,len(issued['effects']))
  current={k:self.native_command()[k] for k in ('attemptId','versionId','clipId','inventoryRevision')}
  base={**current,'lastCommand':{'commandId':3,'accepted':True,'result':'applied','preference':pref(audioLanguage='spa'),'preferenceRevision':issued['state']['revision']}}
  for key,value in [('attemptId','old'),('versionId','old'),('clipId',8),('inventoryRevision',3)]:
   changed={**base,key:value};result=self.step(issued['state'],kind='native_result',snapshot=changed,current=current)
   self.assertFalse(result['accepted']);self.assertEqual([],result['effects']);self.assertIsNotNone(result['state']['nativePending'])
 def test_manual_intent_fences_delayed_get_even_before_native_landing(self):
  read=self.step(self.create(),kind='load')
  issued=self.step(read['state'],kind='manual',command=self.native_command())
  self.assertEqual(1,len(issued['effects']))
  late=self.call('TpoReduce',issued['state'],self.receipt(read['effects'][0],record=pref(subtitleMode='off')))
  self.assertEqual('auto',late['state']['preference']['subtitleMode']);self.assertEqual([],late['effects'])

if __name__=='__main__':unittest.main()
