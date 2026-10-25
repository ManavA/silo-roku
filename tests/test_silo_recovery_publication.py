"""Total recovery envelope through real runJob and HTTP/SDK clock/filesystem."""
import json
import unittest
from pathlib import Path
from tests import test_silo_selected_subtitle_prepare as prepare
from tests import test_silo_recovery_quality as recovery
from tests.test_silo_recovery_refusal import candidate

ROOT=Path(__file__).resolve().parents[1]
KEPT='tmp:/silo-subtitle-11111111-1111-4111-8111-111111111111.vtt'

class RecoveryPublicationTests(unittest.TestCase):
    def run_job(self, **effects):
        params=recovery.RecoveryQualityTests().params()
        final=candidate(3,True)
        artifact=final['playback_plan']['subtitle']['artifact']
        artifact.update(url='/api/v2/stream/session-0001/subtitles/1.srt?file_id=f1',format='srt',mime_type='application/x-subrip')
        final['playback_plan']['subtitle']['inventory'][1]['url']=artifact['url']
        cap=json.loads((ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text())
        cap.update(installation_id='install-0001',features=['header_authenticated_media_v1'],deliveries=['original_http','server_remux_hls','server_transcode_hls'])
        responses=[{'statusCode':200,'body':json.dumps(cap),'elapsedMs':6000},
                   {'statusCode':200,'body':json.dumps(candidate()),'elapsedMs':45000},
                   {'statusCode':200,'body':json.dumps(final),'elapsedMs':45000}]
        session={'baseUrl':'https://silo.example','sourceId':'silo:synthetic','profileId':'owner','deviceId':'fixture-device',
                 'accessToken':'synthetic-access','profileToken':'synthetic-profile'}
        job={'provider':'silo','action':'playback_replan','sourceId':session['sourceId'],'profileId':session['profileId'],
             'generation':7,'requestId':13,'params':params}
        scenario={'headers':{'Content-Type':'application/x-subrip'},'body':'1\n00:00:00,000 --> 00:00:05,000\nSynthetic\n','keepFile':True,**effects}
        return prepare.SelectedSubtitlePreparationTests().run_job(job_override=job,session_override=session,
            responses_override=responses,scenario=scenario,recovery_clock=True)

    def test_deadline_after_owned_artifact_preparation_refuses_and_retires_only_that_artifact(self):
        # The injected SDK clock models a scheduling pause after file preparation,
        # before final result publication; it does not warm or fake media admission.
        result=self.run_job(publicationDelayMs=24000)
        outcome=result['outcome']
        self.assertFalse(outcome['ok'],result)
        self.assertEqual('network_timeout',outcome['errorCode'])
        self.assertEqual(('playback_replan',13,7),(outcome['action'],outcome['requestId'],outcome['generation']))
        self.assertEqual('plan-0003',outcome['controlReceipt']['planId'])
        self.assertTrue(outcome['leaseUncertain'])
        self.assertNotIn('plan',outcome)
        self.assertIsNone(result['binding'])
        self.assertEqual([KEPT],result['files'])
        self.assertEqual(1,len(result['downloads']))
        self.assertEqual(['GET','POST','POST'],[r['method'] for r in result['requests']])

    def test_final_cancellation_or_revision_change_keeps_latest_receipt_and_retires_owned_file(self):
        for effects,code in (({'cancelBeforePublication':True},'cancelled'),
                             ({'revisionBeforePublication':True},'session_changed')):
            with self.subTest(code=code):
                result=self.run_job(**effects)
                outcome=result['outcome']
                self.assertFalse(outcome['ok'],result)
                self.assertEqual(code,outcome['errorCode'])
                self.assertEqual('plan-0003',outcome['controlReceipt']['planId'])
                self.assertNotIn('plan',outcome)
                self.assertIsNone(result['binding'])
                self.assertEqual([KEPT],result['files'])
                self.assertEqual(1,len(result['downloads']))

    def test_publication_before_total_deadline_transfers_the_exact_ready_artifact(self):
        result=self.run_job(publicationDelayMs=23999)
        self.assertTrue(result['outcome']['ok'],result)
        plan=result['outcome']['plan']
        artifact=plan['subtitleArtifact']
        self.assertEqual('plan-key-0003',artifact['owner']['planAttemptKey'])
        self.assertEqual(13,artifact['owner']['requestId'])
        self.assertEqual(artifact['uri'],result['binding']['uri'])
        self.assertEqual({KEPT,artifact['uri']},set(result['files']))
        self.assertEqual(1,len(result['downloads']))
