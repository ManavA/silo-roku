"""Shipping runJob release boundaries, using synthetic source/HTTP/SDK leaves."""
import copy
import json
import unittest
from tests import test_silo_compat_continuation as task
from tests import test_silo_p7_producer_flow as explicit
from tests import test_silo_p7_auto_producer as auto


class BoundedBetaGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        explicit.P7ProducerFlow.setUpClass()
        auto.P7AutoProducer.setUpClass()

    def shipping(self, *, job=None, enabled=None, device=None, features=None):
        return task.CompatContinuation().job(enabled=enabled,p7_enabled=None,
            automatic_hdr10=None,scope=copy.deepcopy(job or auto.P7AutoProducer.job),
            mutate=explicit.fixture,device=device or explicit.DEVICE,features=features)

    def test_shipping_p7_auto_does_not_choose_audio_or_mint_handoff(self):
        result=self.shipping(features=['native_hls_separate_audio_v1'])
        baseline=self.shipping(enabled=False,features=['native_hls_separate_audio_v1'])
        self.assertNotIn('compatContinuation',result['outcome'])
        starts=[json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(1,len(starts),result)
        self.assertNotIn('audio_track_index',starts[0])
        self.assertNotIn('audio_track_id',starts[0])
        self.assertEqual(baseline['requests'],result['requests'])
        self.assertEqual(baseline['outcome'],result['outcome'])

    def test_shipping_p7_explicit_and_qualified_aac_stay_inert(self):
        runner=auto.P7AutoProducer()
        for original in (auto.P7AutoProducer.job,explicit.P7ProducerFlow.scene_job):
            for qualified in (False,True):
                job=copy.deepcopy(original)
                if qualified:job['params']['instanceQualification']=runner.aac_qualification(job)
                with self.subTest(auto=original is auto.P7AutoProducer.job,qualified=qualified):
                    result=self.shipping(job=job,device=runner.aac_only_device())
                    self.assertNotIn('compatContinuation',result['outcome'])
                    self.assertNotEqual('task_failed',result['outcome'].get('errorCode'))
                    baseline=self.shipping(job=job,device=runner.aac_only_device(),enabled=False)
                    self.assertEqual(baseline['requests'],result['requests'])
                    self.assertEqual(baseline['outcome'],result['outcome'])

    def test_shipping_detail_does_not_enrich_p7_auto_audio(self):
        result=self.shipping(job={'action':'detail','params':{'itemId':'fixture-item'}})
        self.assertTrue(result['outcome']['ok'],result)
        self.assertNotIn('autoAudioFacts',result['outcome']['data']['versions'][0])

    def test_shipping_p7_explicit_copied_audio_keeps_normal_native_behavior(self):
        job=copy.deepcopy(explicit.P7ProducerFlow.scene_job)
        result=self.shipping(job=job)
        baseline=self.shipping(job=job,enabled=False)
        self.assertNotIn('compatContinuation',result['outcome'])
        self.assertEqual(baseline['requests'],result['requests'])
        self.assertEqual(baseline['outcome'],result['outcome'])

    def test_aac_release_gate_refuses_even_when_copied_p7_is_opted_in(self):
        runner=auto.P7AutoProducer()
        for original in (auto.P7AutoProducer.job,explicit.P7ProducerFlow.scene_job):
            job=copy.deepcopy(original)
            job['params']['instanceQualification']=runner.aac_qualification(job)
            result=task.CompatContinuation().job(scope=job,mutate=explicit.fixture,
                device=runner.aac_only_device(),p7_enabled=True,aac_enabled=False)
            self.assertNotIn('compatContinuation',result['outcome'])
            self.assertNotEqual('task_failed',result['outcome'].get('errorCode'))
