"""Strictly refused native HLS recipes advance the real same-intent Task planner."""
import copy
import json
import unittest

from tests import test_silo_replan_task as replan
from tests import test_silo_recovery_quality as recovery
from tests.test_silo_selected_subtitle_worker import decision_with_selected


def candidate(ordinal=2, admitted=False):
    raw = decision_with_selected('session-0001')
    raw['session_id'] = 'session-0001'
    plan = raw['playback_plan']
    plan.update(plan_id=f'plan-000{ordinal}', plan_attempt_key=f'plan-key-000{ordinal}',
                delivery='server_transcode_hls' if admitted else 'server_remux_hls',
                effective_recipe={'video_codec':'h264','audio_codec':'aac' if admitted else 'eac3',
                                  'dynamic_range':'sdr','width':1920,'height':1080},
                transformations=([{'name':'video_to_h264','executor':'server','recipe_version':'2'},
                                  {'name':'audio_to_aac','executor':'server','recipe_version':'4'}] if admitted else []))
    if admitted: plan['effective_recipe']['audio_channels'] = 2
    plan['stream'].update(protocol='hls',container='hls',url='/api/v2/playback/transcode/session-0001/master.m3u8')
    return raw


class RecoveryRefusalTests(unittest.TestCase):
    def call(self, first=None, later=None, params=None, effects=None):
        return replan.SiloReplanTaskTests().call(
            params=params or recovery.RecoveryQualityTests().params(), decision=first or candidate(),
            continuations=[candidate(3, True)] if later is None else later,
            capability_features=['header_authenticated_media_v1'], advance_current=True,http_effects=effects)

    def test_refused_legacy_hls_then_qualified_recipe_keeps_exact_intent(self):
        result = self.call()
        self.assertTrue(result['outcome']['ok'], result)
        self.assertEqual(1,result['clockMarks'])
        self.assertEqual(['GET','POST','POST'], [r['method'] for r in result['requests']])
        first, second = [json.loads(r['body']) for r in result['requests'][1:]]
        for name in ('quality_preference','selected_tracks','bandwidth_cap_kbps','position_seconds','operation','failure','client_features','client_playback_context'):
            self.assertEqual(first[name], second[name], name)
        self.assertEqual(('1080p','failure_recovery'), (second['quality_preference'], second['operation']))
        self.assertEqual(('plan-0002','plan-key-0002',2),
                         (second['failed_plan_id'],second['plan_attempt_key'],second['attempt_count']))
        self.assertIn('plan-key-0002', second['attempted_plan_keys'])
        self.assertEqual([6000,90000,90000], result['timeouts'])
        plan = result['outcome']['plan']
        self.assertEqual(('plan-0003',2,'api_header_v1'),
                         (plan['planId'],plan['siloPlayback']['attemptCount'],plan['siloPlayback']['mediaAuthMode']))
        self.assertEqual('Bearer synthetic-access',plan['headers']['Authorization'])
        self.assertEqual('file:f1:subtitle:1',plan['selectedSubtitle']['trackId'])

    def test_third_candidate_and_attempt_exhaustion_preserve_latest_receipt(self):
        result = self.call(later=[candidate(3),candidate(4,True)])
        self.assertTrue(result['outcome']['ok'], result)
        bodies = [json.loads(r['body']) for r in result['requests'][1:]]
        self.assertEqual([1,2,3],[b['attempt_count'] for b in bodies])
        self.assertEqual(['plan-0001','plan-0002','plan-0003'],[b['failed_plan_id'] for b in bodies])
        params = recovery.RecoveryQualityTests().params()
        params['plan']['siloPlayback']['attemptCount'] = 6
        exhausted = self.call(params=params,later=[candidate(3),candidate(4,True)])
        self.assertFalse(exhausted['outcome']['ok'])
        self.assertEqual('no_new_playback_route',exhausted['outcome']['errorCode'])
        self.assertEqual(['GET','POST','POST'],[r['method'] for r in exhausted['requests']])
        self.assertEqual(('plan-0003',8),(exhausted['outcome']['controlReceipt']['planId'],exhausted['outcome']['controlReceipt']['attemptCount']))

    def test_terminal_after_refusal_retains_latest_validated_receipt(self):
        terminal = {'protocol_version':3,'outcome':'adaptation_unavailable',
                    'terminal':{'reason':'adaptation_exhausted','retryable':False}}
        result = self.call(later=[terminal])
        self.assertEqual('playback_terminal',result['outcome']['errorCode'])
        self.assertEqual('plan-0002',result['outcome']['controlReceipt']['planId'])

    def test_malformed_candidate_never_advances_planner_but_retains_valid_control(self):
        for label in ('timeline','origin','subtitle','recipe'):
            with self.subTest(label=label):
                raw = candidate()
                plan = raw['playback_plan']
                if label == 'timeline': plan['timeline']['timeline_offset_seconds'] = '0'
                if label == 'origin': plan['stream']['url'] = 'https://foreign.example/master.m3u8'
                if label == 'subtitle': plan['subtitle']['artifact']['timing_origin_seconds'] = -1
                if label == 'recipe': plan['effective_recipe']['height'] = '1080'
                result = self.call(first=raw)
                self.assertFalse(result['outcome']['ok'])
                self.assertEqual(['GET','POST'],[r['method'] for r in result['requests']])
                self.assertEqual('plan-0002',result['outcome']['controlReceipt']['planId'])

    def test_deadline_clamps_later_post_and_retains_late_admitted_receipt(self):
        result = self.call(effects=[{'elapsedMs':6000},{'elapsedMs':44000},{'elapsedMs':59000}])
        self.assertEqual('network_timeout',result['outcome']['errorCode'])
        self.assertEqual('plan-0003',result['outcome']['controlReceipt']['planId'])
        self.assertNotIn('plan',result['outcome'])
        self.assertEqual([6000,90000,58750],result['timeouts'])
        clamped = self.call(effects=[{'elapsedMs':6000},{'elapsedMs':60000},{'elapsedMs':42000}])
        self.assertEqual([6000,90000,42750],clamped['timeouts'])
        self.assertTrue(clamped['outcome']['ok'])

    def test_cancel_or_scope_change_after_allocated_response_preserves_latest_receipt(self):
        for effect,code in (({'cancel':True},'cancelled'),({'revisionChanged':True},'session_changed')):
            with self.subTest(code=code):
                result = self.call(effects=[{},effect])
                self.assertEqual(code,result['outcome']['errorCode'])
                self.assertEqual(['GET','POST'],[r['method'] for r in result['requests']])
                self.assertEqual('plan-0002',result['outcome']['controlReceipt']['planId'])
                self.assertNotIn('plan',result['outcome'])

    def test_refresh_late_result_does_not_save_or_replay(self):
        token = json.dumps({'access_token':'synthetic-new','refresh_token':'synthetic-rotated','expires_in':3600})
        for effect,code in (({'cancel':True},'cancelled'),({'revisionChanged':True},'session_changed'),({'elapsedMs':109000},'network_timeout')):
            with self.subTest(code=code):
                result = self.call(later=[candidate(3),candidate(4,True)],effects=[{},
                    {'statusCode':401,'body':'{}'}, {'body':token,**effect}, {}])
                self.assertEqual(code,result['outcome']['errorCode'])
                self.assertEqual(0,result['saves'])
                self.assertEqual(3,len(result['requests']))

    def test_one_refresh_for_whole_recovery_job_and_preserved_post_ceiling(self):
        token = json.dumps({'access_token':'synthetic-new','refresh_token':'synthetic-rotated','expires_in':3600})
        result = self.call(later=[candidate(3),candidate(4),candidate(5,True)],effects=[{},
            {'statusCode':401,'body':'{}'}, {'body':token}, {}, {'statusCode':401,'body':'{}'}])
        self.assertEqual('auth_required',result['outcome']['errorCode'])
        self.assertEqual(1,result['saves'])
        self.assertEqual([6000,90000,9000,90000,90000],result['timeouts'])
        self.assertEqual(5,len(result['requests']))
        self.assertEqual('plan-0004',result['outcome']['controlReceipt']['planId'])

    def test_legacy_quality_descent_shares_remaining_logical_attempts(self):
        params = recovery.RecoveryQualityTests().params()
        params['plan']['allowQualityFallback'] = True
        params['plan']['siloPlayback']['attemptCount'] = 7
        params['plan']['siloPlayback']['availableQualities'].append({'label':'720p','preservesSource':False,'height':720,'bitrateKbps':2500})
        terminal={'protocol_version':3,'outcome':'adaptation_unavailable','terminal':{'reason':'adaptation_exhausted','retryable':False}}
        result=self.call(first=terminal,later=[candidate(3,True)],params=params)
        self.assertFalse(result['outcome']['ok'],result)
        self.assertEqual(['GET','POST'],[r['method'] for r in result['requests']])
        self.assertEqual('no_new_playback_route',result['outcome']['errorCode'])

    def test_skipped_recipe_then_terminal_quality_descent_uses_latest_lease_identity(self):
        params=recovery.RecoveryQualityTests().params()
        params['plan']['allowQualityFallback']=True
        params['plan']['siloPlayback']['availableQualities'].append({'label':'720p','preservesSource':False,'height':720,'bitrateKbps':2500})
        first=candidate()
        first['playback_plan']['available_qualities'].append({'label':'720p','preserves_source':False,'height':720,'bitrate_kbps':2500})
        terminal={'protocol_version':3,'outcome':'adaptation_unavailable','terminal':{'reason':'adaptation_exhausted','retryable':False}}
        result=self.call(first=first,later=[terminal,candidate(4,True)],params=params)
        self.assertTrue(result['outcome']['ok'],result)
        self.assertEqual(['GET','POST','POST','POST'],[r['method'] for r in result['requests']])
        bodies=[json.loads(r['body']) for r in result['requests'][1:]]
        self.assertEqual(['1080p','1080p','720p'],[b['quality_preference'] for b in bodies])
        self.assertEqual(['plan-0001','plan-0002','plan-0002'],[b['failed_plan_id'] for b in bodies])
        self.assertEqual([1,2,3],[b['attempt_count'] for b in bodies])
        self.assertEqual(['plan-key-0001','plan-key-0002'],bodies[-1]['attempted_plan_keys'])
