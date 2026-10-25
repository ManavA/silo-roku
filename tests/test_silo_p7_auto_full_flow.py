"""Genuine no-choice Scene/Task through persistent holder and ordinary Back.

Reuse the explicit flow's independent ownership, source-time and cleanup
assertions, changing only public entry intent and real producer envelopes.
"""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch
from tests import test_silo_p7_full_flow as full
from tests import test_silo_p7_auto_producer as auto


class P7AutoFullFlow(full.P7FullFlow):
    @classmethod
    def setUpClass(cls):
        auto.P7AutoProducer.setUpClass()
        cls.expectedJob=copy.deepcopy(auto.P7AutoProducer.job)
        cls.detailResult=copy.deepcopy(auto.P7AutoProducer.detail)
        cls.producerResult=auto.P7AutoProducer().run_auto()['outcome']
        params={key.lower():value for key,value in cls.expectedJob['params'].items()}
        assert params['autoversion'] is True
        assert cls.producerResult['compatContinuation']['autoVersion'] is True
        assert not any(key.lower() in ('audiotrackid','audiotrackindex')
                       for key in cls.expectedJob['params'])

    def transcript(self,control='media_roundtrip',mutate=None):
        # The real producer and fresh holder detail must run under the same
        # opt-in test gate. Shipping defaults remain unchanged.
        read=Path.read_text
        def gated(path,*args,**kwargs):
            text=read(path,*args,**kwargs)
            if path==full.ROOT/'components/ApiTask.brs':
                marker='function SiloCompatPreparationEnabled('
                assert text.count(marker)==1
                text=text.replace(marker,'function ShippingSiloCompatPreparationEnabled(',1)
                text+='\nfunction SiloCompatPreparationEnabled() as Boolean\n return true\nend function\n'
                for gate in ('SiloP7CompatPreparationEnabled','SiloP7AACPreparationEnabled'):
                    text=text.replace('function '+gate+'(','function Shipping'+gate+'(',1)
                    text+='\nfunction '+gate+'() as Boolean\n return true\nend function\n'
            return text
        # The full Scene plus three holder generations takes over 112s after
        # interpreter startup. Keep a bounded local budget including compilation.
        budget=os.environ.get('SILO_BRS_TIMEOUT','180')
        with patch.object(Path,'read_text',gated),patch.dict(os.environ,{'SILO_BRS_TIMEOUT':budget}):
            return super().transcript(control=control,mutate=mutate,automatic=True)

    def test_qualified_aac_conversion_reaches_scene_holder_reanchors_and_closes(self):
        runner=auto.P7AutoProducer()
        device=runner.aac_only_device()
        job=copy.deepcopy(self.expectedJob)
        job['params']['instanceQualification']=runner.aac_qualification(job)
        started=runner.run_auto(job=job,device=device)['outcome']
        self.assertEqual('experimental_query_p7_hdr10_aac_fmp4_v1',started['compatContinuation']['eligibilityKind'])
        previous_job,previous_result=self.expectedJob,self.producerResult
        self.expectedJob,self.producerResult=job,started
        def select_source_default(values):
            receipt=values['playback']['MediaSources'][0]
            receipt['DefaultAudioStreamIndex']=1
            for stream in receipt['MediaStreams']:
                if stream['Type']=='Audio':stream['IsDefault']=stream['Index']==1
        try:
            with patch.object(full.producer,'DEVICE',device):
                result=self.transcript(mutate=select_source_default)
        finally:
            self.expectedJob,self.producerResult=previous_job,previous_result
        self.assertNotIn('fixtureError',result,result)
        self.assertTrue(result.get('scene',{}).get('holderCreated'),result)
        self.assertEqual(job,result.get('entryJob'))
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['privateCleared'])
        prepared=[r for r in result['results'] if r['phase']=='prepared']
        self.assertEqual([1,2,3],[r['planGeneration'] for r in prepared],result['results'])
        self.assertEqual(['converted_p7_hdr10_aac_fmp4']*3,[r['class'] for r in prepared])
        requests=[r for r in result['requests'] if '/PlaybackInfo' in r['url']]
        self.assertEqual(3,len(requests))
        for request in requests:
            body=json.loads(request['body'])
            self.assertEqual(1,body['AudioStreamIndex'])
            profile=body['DeviceProfile']['TranscodingProfiles'][0]
            self.assertEqual(('aac','2'),(profile['AudioCodec'],profile['MaxAudioChannels']))

    def test_qualified_input_keeps_copied_ac3_priority_through_scene_holder(self):
        runner=auto.P7AutoProducer()
        device=auto.explicit.DEVICE
        job=copy.deepcopy(self.expectedJob)
        job['params']['instanceQualification']=runner.aac_qualification(job)
        started=runner.run_auto(job=job,device=device)['outcome']
        continuation=started['compatContinuation']
        self.assertEqual(auto.explicit.KIND,continuation['eligibilityKind'])
        self.assertNotIn('instanceQualification',continuation)
        previous_job,previous_result=self.expectedJob,self.producerResult
        self.expectedJob,self.producerResult=job,started
        try:
            with patch.object(full.producer,'DEVICE',device):
                result=self.transcript()
        finally:
            self.expectedJob,self.producerResult=previous_job,previous_result
        self.assertNotIn('fixtureError',result,result)
        self.assertTrue(result.get('scene',{}).get('holderCreated'),result)
        self.assertEqual(job,result.get('entryJob'))
        self.assertEqual(['copied_p7_hdr10_fmp4']*3,[r['class'] for r in result['results'] if r['phase']=='prepared'])
        requests=[r for r in result['requests'] if '/PlaybackInfo' in r['url']]
        self.assertEqual(3,len(requests))
        for request in requests:
            profile=json.loads(request['body'])['DeviceProfile']['TranscodingProfiles'][0]
            self.assertEqual('ac3',profile['AudioCodec'])
            self.assertEqual('6',profile['MaxAudioChannels'])
