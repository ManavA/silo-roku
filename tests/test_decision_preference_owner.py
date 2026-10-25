"""Current viewer, admitted request and confirmed storage own decision settings."""
from copy import deepcopy
from pathlib import Path
import tempfile
import re
import unittest
from tools.brightscript import run_function
C=Path(__file__).resolve().parents[1]
ROOT=C if (C/'source/core/ServerUrlPolicy.brs').exists() else Path(__file__).resolve().parents[1]
OWNER=C/'source/core/DecisionPreferenceOwnerPolicy.brs'
SCHEMA=ROOT/'source/core/DecisionPreference.brs'
if not SCHEMA.exists():SCHEMA=Path('/tmp/silo-still-watching-worker/source/core/DecisionPreference.brs')
SCOPE={'provider':'plex','sourceId':'plex:fixture','profileId':'owner','generation':7}

def preference(**changes):
    value={'schemaVersion':1,'sourceId':SCOPE['sourceId'],'profileId':SCOPE['profileId'],
           'personalized':False,'cloudDecisions':False,'stillWatchingCheck':False,'gatewayOrigin':''}
    value.update(changes);return value

class DecisionPreferenceOwnerTests(unittest.TestCase):
    def call(self,name,*args):
        self.assertTrue(OWNER.exists(),'decision preference owner behavior is not implemented')
        self.assertTrue(SCHEMA.exists(),'worker-owned verified preference schema is not available')
        with tempfile.TemporaryDirectory(prefix='silo-decision-owner-') as d:
            return run_function([ROOT/"source/core/ServerUrlPolicy.brs",SCHEMA,OWNER],name,list(args),root=Path(d))
    def create(self,scope=None):return self.call('DpoCreate',scope or SCOPE)
    def step(self,state,**event):return self.call('DpoReduce',state,event)
    def bound(self,state,effect,request_id='mapped-1'):
        job={**effect['scope'],'action':effect['action'],'params':effect['params'],
             'decisionPreferenceOwner':effect['decisionPreferenceOwner'],'requestId':request_id}
        out=self.step(state,kind='bound',job=job)
        self.assertTrue(out['accepted']);return out['state'],job
    def receipt(self,state,job,record=None,ok=True,**extra):
        result={k:job[k] for k in ('provider','sourceId','profileId','generation','requestId','action')}
        result.update(ok=ok,data={'preference':record if record is not None else preference()},**extra)
        return self.step(state,kind='result',job=job,result=result)
    def loaded(self,record=None):
        read=self.step(self.create(),kind='load');state,job=self.bound(read['state'],read['effects'][0])
        return self.receipt(state,job,record)['state']

    def test_default_off_and_one_read_require_exact_admitted_receipt(self):
        state=self.create();self.assertEqual(preference(),state['desired']);self.assertIsNone(self.call('DpoEffective',state,SCOPE))
        read=self.step(state,kind='load');effect=read['effects'][0]
        self.assertEqual(('decision_pref_get',{},SCOPE),(effect['action'],effect['params'],effect['scope']))
        self.assertEqual([],self.step(read['state'],kind='load')['effects'])
        fake={**SCOPE,'action':effect['action'],'params':{},'requestId':'unbound','decisionPreferenceOwner':effect['decisionPreferenceOwner']}
        self.assertFalse(self.receipt(read['state'],fake)['accepted'])
        state,job=self.bound(read['state'],effect)
        done=self.receipt(state,job);self.assertTrue(done['state']['loaded'])
        self.assertEqual(preference(),self.call('DpoEffective',done['state'],SCOPE))

    def test_edit_before_get_merges_only_latest_changed_fields_into_stored_record(self):
        read=self.step(self.create(),kind='load');state,job=self.bound(read['state'],read['effects'][0])
        changed=self.step(state,kind='change',field='personalized',value=True)
        self.assertEqual([],changed['effects']);self.assertIsNone(self.call('DpoEffective',changed['state'],SCOPE))
        stored=preference(cloudDecisions=True,gatewayOrigin='https://gateway.example.test')
        done=self.receipt(changed['state'],job,stored)
        self.assertEqual(1,len(done['effects']))
        self.assertEqual(preference(personalized=True,cloudDecisions=True,gatewayOrigin='https://gateway.example.test'),done['effects'][0]['params']['preference'])

    def test_coalesced_writes_keep_latest_desired_and_gate_until_latest_ack(self):
        state=self.loaded(preference(gatewayOrigin='https://gateway.example.test'))
        first=self.step(state,kind='change',field='personalized',value=True)
        state,job=self.bound(first['state'],first['effects'][0])
        second=self.step(state,kind='change',field='cloudDecisions',value=True)
        third=self.step(second['state'],kind='change',field='stillWatchingCheck',value=True)
        self.assertEqual([],second['effects']);self.assertEqual([],third['effects'])
        self.assertIsNone(self.call('DpoEffective',third['state'],SCOPE))
        done=self.receipt(third['state'],job,first['effects'][0]['params']['preference'])
        self.assertTrue(done['state']['desired']['stillWatchingCheck']);self.assertEqual(1,len(done['effects']))
        latest=done['effects'][0];self.assertTrue(all(latest['params']['preference'][f] for f in ('personalized','cloudDecisions','stillWatchingCheck')))
        state,job=self.bound(done['state'],latest,'mapped-2')
        final=self.receipt(state,job,latest['params']['preference'])
        self.assertEqual(latest['params']['preference'],self.call('DpoEffective',final['state'],SCOPE))

    def test_reverting_to_confirmed_while_first_write_pending_still_saves_latest_intent(self):
        first=self.step(self.loaded(),kind='change',field='personalized',value=True)
        state,job=self.bound(first['state'],first['effects'][0])
        latest=self.step(state,kind='change',field='personalized',value=False)
        done=self.receipt(latest['state'],job,first['effects'][0]['params']['preference'])
        self.assertEqual(1,len(done['effects']));self.assertFalse(done['effects'][0]['params']['preference']['personalized'])

    def test_read_and_write_failures_stay_disabled_and_retry_reads_before_save(self):
        read=self.step(self.create(),kind='load');state,job=self.bound(read['state'],read['effects'][0])
        failed=self.receipt(state,job,ok=False);self.assertTrue(failed['state']['error']);self.assertIsNone(self.call('DpoEffective',failed['state'],SCOPE))
        retry=self.step(failed['state'],kind='load');self.assertEqual('decision_pref_get',retry['effects'][0]['action'])
        first=self.step(self.loaded(),kind='change',field='personalized',value=True)
        state,job=self.bound(first['state'],first['effects'][0])
        failed=self.receipt(state,job,ok=False);self.assertTrue(failed['state']['desired']['personalized'])
        self.assertIsNone(self.call('DpoEffective',failed['state'],SCOPE))
        retry=self.step(failed['state'],kind='load');self.assertEqual('decision_pref_get',retry['effects'][0]['action'])

    def test_receipts_require_bound_id_scope_action_params_owner_revision_and_actual_bool(self):
        read=self.step(self.create(),kind='load');state,job=self.bound(read['state'],read['effects'][0])
        for change in ('id','source','profile','generation','action','params','owner','revision','ok'):
            with self.subTest(change=change):
                j=deepcopy(job);result={k:job[k] for k in ('provider','sourceId','profileId','generation','requestId','action')}
                result.update(ok=True,data={'preference':preference()})
                if change=='id':result['requestId']='foreign'
                if change=='source':result['sourceId']='plex:foreign'
                if change=='profile':result['profileId']='other'
                if change=='generation':result['generation']=6
                if change=='action':result['action']='decision_pref_set'
                if change=='params':j['params']={'unowned':True}
                if change=='owner':j['decisionPreferenceOwner']['operationId']='foreign'
                if change=='revision':j['decisionPreferenceOwner']['revision']+=1
                if change=='ok':result['ok']=1
                out=self.step(state,kind='result',job=j,result=result)
                self.assertFalse(out['accepted']);self.assertEqual(state,out['state']);self.assertEqual([],out['effects'])

    def test_foreign_or_malformed_record_and_unmatched_set_echo_cannot_confirm(self):
        read=self.step(self.create(),kind='load');state,job=self.bound(read['state'],read['effects'][0])
        for record in (preference(sourceId='plex:foreign'),preference(personalized=1),{'personalized':True}):
            self.assertFalse(self.receipt(state,job,record)['accepted'])
        first=self.step(self.loaded(),kind='change',field='personalized',value=True)
        state,job=self.bound(first['state'],first['effects'][0]);self.assertFalse(self.receipt(state,job,preference())['accepted'])

    def test_generation_change_retires_receipts_and_merges_dirty_intent_after_fresh_read(self):
        first=self.step(self.loaded(),kind='change',field='personalized',value=True)
        state,old_job=self.bound(first['state'],first['effects'][0])
        scope={**SCOPE,'generation':8};changed=self.step(state,kind='viewer',scope=scope)
        self.assertFalse(changed['state']['loaded']);self.assertTrue(changed['state']['desired']['personalized'])
        self.assertIsNone(self.call('DpoEffective',changed['state'],scope))
        self.assertFalse(self.receipt(changed['state'],old_job,first['effects'][0]['params']['preference'])['accepted'])
        read=self.step(changed['state'],kind='load');state,job=self.bound(read['state'],read['effects'][0],'fresh-read')
        done=self.receipt(state,job,preference())
        self.assertEqual(scope,done['effects'][0]['scope']);self.assertTrue(done['effects'][0]['params']['preference']['personalized'])

    def test_source_and_profile_change_reset_to_defaults_and_old_results_are_inert(self):
        read=self.step(self.create(),kind='load');state,job=self.bound(read['state'],read['effects'][0])
        for field,value in (('sourceId','plex:other'),('profileId','other')):
            scope={**SCOPE,field:value};changed=self.step(state,kind='viewer',scope=scope)
            self.assertFalse(changed['state']['loaded']);self.assertFalse(changed['state']['desired']['personalized'])
            self.assertIsNone(self.call('DpoEffective',changed['state'],scope))
            self.assertFalse(self.receipt(changed['state'],job)['accepted'])

    def test_only_exact_unadmitted_rejection_settles_pending_without_fake_request_id(self):
        read=self.step(self.create(),kind='load');effect=read['effects'][0]
        wrong=deepcopy(effect);wrong['decisionPreferenceOwner']['operationId']='foreign'
        self.assertFalse(self.step(read['state'],kind='rejected',effect=wrong)['accepted'])
        done=self.step(read['state'],kind='rejected',effect=effect)
        self.assertTrue(done['state']['error']);self.assertIsNone(done['state']['readPending'])
        state,job=self.bound(read['state'],effect)
        self.assertFalse(self.step(state,kind='rejected',effect=effect)['accepted'])

    def test_invalid_toggle_and_origin_do_not_change_or_publish_preference(self):
        state=self.loaded()
        for field,value in (('personalized',1),('cloudDecisions','true'),('unknown',True),('gatewayOrigin','http://gateway.example.test'),('gatewayOrigin','https://gateway.example.test/private')):
            with self.subTest(field=field,value=value):
                out=self.step(state,kind='change',field=field,value=value)
                self.assertEqual(state['desired'],out['state']['desired']);self.assertEqual([],out['effects'])

    def test_real_silo_scope_and_native_numeric_aliases_keep_generation_finite_and_typed(self):
        scope={**SCOPE,'provider':'silo','sourceId':'silo:https://synthetic.example.test'}
        self.assertEqual(scope,self.create(scope)['scope'])
        for generation in (True,'7',{},1.5,1e30):
            state=self.create({**SCOPE,'generation':generation});self.assertIsNone(state['scope'])


    def test_native_numeric_type_facade_accepts_boxed_aliases_without_accepting_bool_or_strings(self):
        self.assertTrue(OWNER.exists(),'decision preference owner behavior is not implemented')
        self.assertTrue(SCHEMA.exists(),'worker-owned verified preference schema is not available')
        for alias in ('roInteger','roLongInteger','roDouble'):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory(prefix='silo-decision-types-') as d:
                p=Path(d);policy=p/'owner.brs'
                text=re.sub(r'\btype\s*\(', 'DecisionFixtureType(', OWNER.read_text(), flags=re.I)
                text+='\nfunction DecisionFixtureType(value as Dynamic) as String\n    kind=Type(value)\n    if kind="Integer" or kind="roInt" then return "'+alias+'"\n    return kind\nend function\nfunction DecisionTypeCase(scope as Object,values as Object) as Object\n    answers=[]\n    for each value in values\n        answers.Push(DpoScope({provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,generation:value})<>invalid)\n    end for\n    return answers\nend function\n'
                policy.write_text(text)
                result=run_function([ROOT/'source/core/ServerUrlPolicy.brs',SCHEMA,policy],
                                    'DecisionTypeCase',[SCOPE,[7,True,'7',{},[],1.5,1e30]],root=p)
                self.assertEqual([True,False,False,False,False,False,False],result)

if __name__=='__main__':unittest.main()
