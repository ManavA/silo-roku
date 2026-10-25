"""Accepted recovery intent need not appear in the server quality menu."""
import copy
import json
import unittest

from tests import test_silo_playback_policy as policy
from tests import test_silo_replan_task as replan
from tests.test_silo_selected_subtitle_worker import decision_with_selected


class RecoveryQualityTests(unittest.TestCase):
    def params(self):
        params = replan.SiloReplanTaskTests().params()
        params.update(qualityPreference='1080p', failureClassification='decoder_failure')
        params['plan']['siloPlayback'].update(
            qualityPreference='1080p', availableQualities=[{'label':'original','preservesSource':True}],
            bandwidthCapKbps=3500, mediaAuthMode='api_header_v1')
        params['plan']['siloPlayback']['selectedTracks']['subtitle'] = {'id':'file:f1:subtitle:1','index':1}
        return params

    def test_policy_retains_accepted_quality_and_tracks_absent_from_menu(self):
        params = self.params()
        current = params['plan']['siloPlayback']
        for reason in ('decoder_failure', 'buffering_timeout'):
            with self.subTest(reason=reason):
                params['failureClassification'] = reason
                built = policy.SiloPlaybackPolicyTests().call('SiloPlaybackReplanBody',current,params,{},{})
                self.assertTrue(built['ok'], built)
                self.assertEqual(('failure_recovery','1080p',3500),
                                 (built['body']['operation'],built['body']['quality_preference'],built['body']['bandwidth_cap_kbps']))
                self.assertEqual({'classification':reason}, built['body']['failure'])
                self.assertEqual(current['selectedTracks'], built['body']['selected_tracks'])
                self.assertEqual('api_header_v1', built['context']['mediaAuthMode'])
                self.assertEqual(1, built['context']['attemptCount'])

    def test_actual_task_recovery_posts_retained_quality_selected_pair_and_header_mode(self):
        for reason in ('decoder_failure', 'buffering_timeout'):
            with self.subTest(reason=reason):
                params = self.params()
                params['failureClassification'] = reason
                raw = decision_with_selected('session-0001')
                raw['playback_plan']['stream']['url'] = '/api/v2/stream/session-0001'
                result = replan.SiloReplanTaskTests().call(params=params, decision=raw,
                    capability_features=['header_authenticated_media_v1'])
                self.assertTrue(result['outcome']['ok'], result)
                self.assertEqual(['GET','POST'], [r['method'] for r in result['requests']])
                body = json.loads(result['requests'][-1]['body'])
                self.assertEqual(('failure_recovery','1080p',3500,12.5),
                                 (body['operation'],body['quality_preference'],body['bandwidth_cap_kbps'],body['position_seconds']))
                self.assertEqual({'classification':reason}, body['failure'])
                self.assertEqual(params['plan']['siloPlayback']['selectedTracks'], body['selected_tracks'])
                self.assertEqual(['header_authenticated_media_v1'], body['client_features'])
                self.assertEqual('synthetic-profile', result['requests'][-1]['headers']['X-Profile-Token'])
                accepted = result['outcome']['plan']
                self.assertEqual('api_header_v1', accepted['siloPlayback']['mediaAuthMode'])
                self.assertEqual('file:f1:subtitle:1', accepted['selectedSubtitle']['trackId'])
                self.assertEqual(('session-0001','f1'), (accepted['sessionId'],accepted['versionId']))

    def test_actual_task_preserves_real_terminal_route_exhaustion(self):
        terminal = {'protocol_version':3,'outcome':'adaptation_unavailable',
                    'terminal':{'reason':'adaptation_exhausted','retryable':False}}
        result = replan.SiloReplanTaskTests().call(params=self.params(), decision=terminal,
            capability_features=['header_authenticated_media_v1'])
        self.assertFalse(result['outcome']['ok'], result)
        self.assertEqual(['GET','POST'], [r['method'] for r in result['requests']])
        self.assertEqual('playback_terminal', result['outcome']['errorCode'])
        self.assertEqual('adaptation_exhausted', result['outcome']['reason'])
        self.assertEqual('replan', result['outcome']['stage'])
        self.assertNotIn('plan', result['outcome'])

    def test_unlisted_recovery_never_authorizes_new_intent_or_foreign_owner(self):
        base = self.params()
        cases = []
        for change in ({'failureClassification':'untrusted'}, {'failureClassification':None},
                       {'failureClassification':''}, {'qualityPreference':'720p'},
                       {'selectedTracks':copy.deepcopy(policy.TRACKS)},
                       {'bandwidthCapKbps':9000}, {'mediaAuthMode':'other'},
                       {'sessionId':'foreign-session'}):
            params = copy.deepcopy(base)
            params.update(change)
            cases.append((str(change),params,policy.SCOPE))
        params = copy.deepcopy(base)
        del params['failureClassification']
        cases.append(('generic quality change',params,policy.SCOPE))
        for field,value in (('attemptCount',8), ('sessionRevision',1)):
            params = copy.deepcopy(base)
            params['plan']['siloPlayback'][field] = value
            cases.append((field,params,policy.SCOPE))
        for field,value in (('sourceId','silo:foreign'), ('profileId','foreign')):
            cases.append((field,base,{**policy.SCOPE,field:value}))
        for label,params,scope in cases:
            with self.subTest(case=label):
                result = replan.SiloReplanTaskTests().call(params=params,scope=scope)
                self.assertFalse(result['outcome']['ok'], result)
                self.assertEqual([], result['requests'])
