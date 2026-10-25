"""Source subtitle selection through real Task publication and HTTP boundaries."""
import copy
import json
import unittest
from tests import test_silo_replan_task as replan
from tests import test_silo_selected_subtitle_prepare as prepare
from tests.test_silo_selected_subtitle_worker import decision_with_selected
from tests.test_silo_playback_policy import SCOPE, TRACKS

class SourceSubtitleSelectionTests(unittest.TestCase):
    def test_final_job_publishes_url_free_inventory_even_when_off(self):
        raw=decision_with_selected()
        raw['playback_plan']['selected_tracks']=copy.deepcopy(TRACKS)
        raw['playback_plan']['subtitle'].update(mode='off',track_id='',artifact=None)
        result=prepare.SelectedSubtitlePreparationTests().run_job(decision=raw)
        self.assertTrue(result['outcome']['ok'],result)
        inventory=result['outcome']['plan']['sourceSubtitleInventory']
        self.assertEqual(7,inventory['owner']['generation'])
        self.assertEqual(['file:f1:subtitle:0','file:f1:subtitle:1'],[r['trackId'] for r in inventory['entries']])
        self.assertNotIn('url',json.dumps(inventory).lower())
        self.assertEqual([],result['downloads'])

    def selection_params(self):
        worker=replan.SiloReplanTaskTests()
        p=worker.params();p.pop('qualityPreference')
        c=p['plan']['siloPlayback'];c['bandwidthCapKbps']=3500;c['subtitleOffRequired']=True
        keys=('sourceId','profileId','sessionRevision','sessionId','fileId','planId','planAttemptId','planAttemptKey','playbackAttemptId','attemptCount')
        owner={k:c[k] for k in keys};owner['generation']=7
        p['plan']['sourceSubtitleInventory']={'owner':owner,'entries':[
            {'trackId':'file:f1:subtitle:1','combinedIndex':1,'source':'external','codec':'subrip','language':'eng','label':'English','forced':False,'default':False,'hearingImpaired':False,'delivery':'sidecar'}]}
        first=copy.deepcopy(p['plan']['sourceSubtitleInventory']['entries'][0]);first.update(trackId='file:f1:subtitle:0',combinedIndex=0)
        p['plan']['sourceSubtitleInventory']['entries'].insert(0,first)
        p.update(subtitleTrackId='file:f1:subtitle:1',subtitleTrackIndex=1)
        return p

    def test_explicit_on_replans_same_lease_clears_off_and_preserves_budget(self):
        p=self.selection_params()
        result=replan.SiloReplanTaskTests().call(params=p,decision=decision_with_selected('session-0001'),subtitle_select=True)
        self.assertTrue(result['outcome']['ok'],result)
        self.assertEqual(['GET','POST'],[r['method'] for r in result['requests']])
        body=json.loads(result['requests'][-1]['body'])
        self.assertEqual({'audio':TRACKS['audio'],'subtitle':{'id':'file:f1:subtitle:1','index':1}},body['selected_tracks'])
        self.assertEqual('track_change',body['operation']);self.assertNotIn('failure',body)
        self.assertEqual(('original',3500,12.5),(body['quality_preference'],body['bandwidth_cap_kbps'],body['position_seconds']))
        self.assertEqual('replan-request-0001',body['replan_request_id'])
        self.assertEqual('playback-attempt-0001',body['playback_attempt_id'])
        self.assertNotIn('subtitleOffRequired',result['outcome']['plan']['siloPlayback'])

    def test_stale_owner_and_untrusted_request_fields_refuse_before_http(self):
        for field in ('generation','planId','planAttemptId','planAttemptKey','playbackAttemptId','sessionRevision','sessionId','fileId','sourceId','profileId','attemptCount'):
            with self.subTest(owner=field):
                p=self.selection_params();p['plan']['sourceSubtitleInventory']['owner'][field]='stale'
                value=replan.SiloReplanTaskTests().call(params=p,subtitle_select=True)
                self.assertFalse(value['outcome']['ok']);self.assertEqual([],value['requests'])
        for key,value in [('failureClassification',None),('qualityPreference','720p'),('mediaAuthMode','api_header_v1'),('selectedTracks',TRACKS),('subtitleMode','render')]:
            with self.subTest(request=key):
                p=self.selection_params();p[key]=value
                result=replan.SiloReplanTaskTests().call(params=p,subtitle_select=True)
                self.assertFalse(result['outcome']['ok']);self.assertEqual([],result['requests'])

    def test_replacement_must_confirm_exact_selection_and_supported_receipt(self):
        for mutation in ('off','wrong','malformed','unsupported','bad-inventory','burn'):
            with self.subTest(response=mutation):
                raw=decision_with_selected('session-0001');sub=raw['playback_plan']['subtitle']
                if mutation=='off':
                    raw['playback_plan']['selected_tracks'].pop('subtitle');sub.update(mode='off',track_id='',artifact=None)
                if mutation=='wrong':
                    raw['playback_plan']['selected_tracks']['subtitle']={'id':'file:f1:subtitle:0','index':0}
                    sub.update(track_id='file:f1:subtitle:0',mode='burn_in',artifact=None)
                if mutation=='malformed': sub['artifact']['mime_type']='broken'
                if mutation=='unsupported': sub['artifact'].update(format='ass',mime_type='text/x-ass')
                if mutation=='bad-inventory': sub['inventory'][0]['label']='x'*129
                if mutation=='burn': sub.update(mode='burn_in',artifact=None)
                value=replan.SiloReplanTaskTests().call(params=self.selection_params(),decision=raw,subtitle_select=True)
                if mutation=='burn':
                    self.assertTrue(value['outcome']['ok'],value);self.assertEqual('burn_in',value['outcome']['plan']['selectedSubtitle']['kind'])
                else:
                    self.assertFalse(value['outcome']['ok'],value);self.assertTrue(value['outcome']['leaseUncertain'])
                    if mutation in ('malformed','unsupported','bad-inventory'):
                        self.assertEqual('plan-0002',value['outcome']['controlReceipt']['planId'])
                self.assertEqual(['GET','POST'],[r['method'] for r in value['requests']])

    def test_passive_missing_or_malformed_inventory_preserves_video(self):
        for bad in (None,[],[{'track_id':'foreign'}]):
            raw=decision_with_selected();raw['playback_plan']['selected_tracks']=copy.deepcopy(TRACKS)
            raw['playback_plan']['subtitle']={'mode':'off'}
            if bad is not None:raw['playback_plan']['subtitle']['inventory']=bad
            value=prepare.SelectedSubtitlePreparationTests().run_job(decision=raw)
            self.assertTrue(value['outcome']['ok'],value)
            if bad != []:self.assertNotIn('sourceSubtitleInventory',value['outcome']['plan'])

    def test_generic_recovery_keeps_sticky_off_and_explicit_on_clears_retry_selectors(self):
        p=self.selection_params();p['plan']['autoVersionRequest']={'itemId':'c1','fileId':'f1','autoVersion':True,'subtitleMode':'off','subtitleOffRequired':True,'qualityPreference':'original','mediaAuthMode':'api_header_v1'}
        value=replan.SiloReplanTaskTests().call(params=p,decision=decision_with_selected('session-0001'),subtitle_select=True)
        self.assertTrue(value['outcome']['ok'],value)
        retry=value['outcome']['plan']['autoVersionRequest']
        self.assertNotIn('subtitleOffRequired',retry);self.assertNotIn('subtitleMode',retry)
        self.assertNotIn('subtitleTrackIndex',retry);self.assertEqual('api_header_v1',retry['mediaAuthMode'])
        p=replan.SiloReplanTaskTests().params();p['plan']['siloPlayback']['subtitleOffRequired']=True
        value=replan.SiloReplanTaskTests().call(params=p,decision=decision_with_selected('session-0001'))
        self.assertFalse(value['outcome']['ok']);self.assertTrue(value['outcome']['leaseUncertain'])

    def test_final_auto_audio_replan_replaces_older_inventory_at_job_generation(self):
        playback=prepare.playback
        class CaptureScenario(playback.SiloPlaybackTaskTests):
            def worker(self,function,arguments,**kwargs):
                if function=='RunSiloNativeBestStart':return arguments
                return super().worker(function,arguments,**kwargs)
        session,params,responses,*_=CaptureScenario().native_best_start(compatible_audio=True)
        selected_plans=[]
        for response in responses:
            raw=json.loads(response['body'])
            if 'playback_plan' in raw:selected_plans.append((response,raw))
        for number,(response,raw) in enumerate(selected_plans):
            plan=raw['playback_plan']
            receipt=prepare.selected(file_id='f2',session=raw['session_id'])
            plan['subtitle']=receipt['subtitle'];plan['selected_tracks']['subtitle']=receipt['selected_tracks']['subtitle']
            plan['subtitle']['inventory'][0]['label']='Final' if number==len(selected_plans)-1 else 'Old'
            response['body']=json.dumps(raw)
        job={'provider':'silo','action':'playback_start','sourceId':session['sourceId'],'profileId':session['profileId'],'generation':17,'requestId':12,'params':params}
        value=prepare.SelectedSubtitlePreparationTests().run_job(job_override=job,session_override=session,responses_override=responses)
        self.assertTrue(value['outcome']['ok'],value)
        plan=value['outcome']['plan'];inventory=plan['sourceSubtitleInventory']
        self.assertEqual((17,'plan-key-0002','Final'),(inventory['owner']['generation'],inventory['owner']['planAttemptKey'],inventory['entries'][0]['label']))
        self.assertEqual(1,len(value['downloads']))

    def test_explicit_on_preserves_existing_header_auth_mode(self):
        p=self.selection_params();p['plan']['siloPlayback']['mediaAuthMode']='api_header_v1'
        raw=decision_with_selected('session-0001');raw['playback_plan']['stream']['url']='/api/v2/stream/session-0001'
        value=replan.SiloReplanTaskTests().call(params=p,decision=raw,subtitle_select=True,capability_features=['header_authenticated_media_v1'])
        self.assertTrue(value['outcome']['ok'],value)
        self.assertEqual('api_header_v1',value['outcome']['plan']['siloPlayback']['mediaAuthMode'])
        self.assertIn('header_authenticated_media_v1',json.loads(value['requests'][-1]['body'])['client_features'])

    def test_explicit_on_through_run_job_prepares_existing_selected_artifact(self):
        p=self.selection_params();raw=decision_with_selected('session-0001')
        raw['session_id']='session-0001';raw['playback_plan'].update(plan_id='plan-0002',plan_attempt_key='plan-key-0002')
        cap=json.loads((prepare.ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text());cap['installation_id']='install-0001'
        session=prepare.playback.SiloPlaybackTaskTests().session();session.update(sourceId=SCOPE['sourceId'],profileId='owner')
        job={**SCOPE,'action':'playback_subtitle_select','requestId':31,'params':p}
        responses=[{'statusCode':200,'body':json.dumps(cap)},{'statusCode':200,'body':json.dumps(raw)}]
        value=prepare.SelectedSubtitlePreparationTests().run_job(job_override=job,session_override=session,responses_override=responses)
        self.assertTrue(value['outcome']['ok'],value)
        plan=value['outcome']['plan']
        self.assertEqual('sidecar_ready',plan['selectedSubtitle']['kind'])
        self.assertEqual([plan['subtitleArtifact']['uri']],value['files'])
        self.assertEqual(31,plan['subtitleArtifact']['owner']['requestId'])
        self.assertEqual('plan-key-0002',plan['sourceSubtitleInventory']['owner']['planAttemptKey'])

    def test_optional_unbounded_private_inventory_fields_never_block_off_video(self):
        cases=('nested-private','malformed-label','too-many-rows')
        for case in cases:
            with self.subTest(case=case):
                raw=decision_with_selected()
                raw['playback_plan']['selected_tracks']=copy.deepcopy(TRACKS)
                sub=raw['playback_plan']['subtitle'];sub.update(mode='off',track_id='',artifact=None)
                if case=='nested-private':
                    sub['inventory'][0]['private_data']={'nested':[{'url':'https://private.invalid/'+('x'*65536)}]}
                elif case=='malformed-label':
                    sub['inventory'][0]['label']={'nested':['private']*256}
                else:
                    sub['inventory']*=65
                value=prepare.SelectedSubtitlePreparationTests().run_job(decision=raw)
                self.assertTrue(value['outcome']['ok'],value)
                self.assertEqual('off',value['outcome']['plan']['selectedSubtitle']['kind'])
                inventory=value['outcome']['plan'].get('sourceSubtitleInventory')
                if case=='nested-private':
                    self.assertEqual(2,len(inventory['entries']))
                    self.assertNotIn('private',json.dumps(inventory))
                    self.assertNotIn('url',json.dumps(inventory).lower())
                else:self.assertIsNone(inventory)
                self.assertEqual([],value['downloads'])
