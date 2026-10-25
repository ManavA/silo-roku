"""Actual ApiTask detail/start decode bridge; synthetic HTTP/SDK leaves only.

The raw technical fixture is source-shaped with synthetic identities. These
checks preserve selection evidence; they do not select Auto audio or activate it.
"""
import unittest
from tests import test_silo_p7_producer_flow as producer


class SiloAutoAudioDetail(unittest.TestCase):
    def detail(self, *, enabled=True, mutate=None, params=None):
        def source(wire,decision):
            producer.fixture(wire,decision)
            if mutate:
                mutate(wire)
        return producer.task.CompatContinuation().job(enabled=enabled,mutate=source,
            scope={'action':'detail','params':params or {'itemId':'fixture-item'}},device=producer.DEVICE)

    def test_real_detail_retains_source_bound_selection_facts_and_original_defaults(self):
        result = self.detail()
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        version = result['outcome']['data']['versions'][0]
        facts = version['autoAudioFacts']
        self.assertEqual('731',facts['file_id'])
        self.assertEqual({'state':'absent'},facts['effective_preference'])
        self.assertEqual(0,facts['preferred_ordinal'])
        self.assertEqual([True,False,False],[t['default'] for t in facts['tracks']])
        self.assertEqual([True,False,False],[t['isDefault'] for t in version['audioTracks']])
        self.assertEqual('truehd',version['audioCodec'])
        self.assertEqual({'state':'schema_unpublished','value':None},facts['tracks'][1]['hearing_impaired'])
        self.assertEqual(['GET'],[r['method'] for r in result['requests']])

    def test_gate_off_caller_flags_are_inert_and_existing_mapped_data_stays_exact(self):
        baseline = self.detail(enabled=False)
        attempt = self.detail(enabled=False,params={'itemId':'fixture-item',
            'compatPreparationEnabled':True,'autoAudioFacts':{'preferred_ordinal':1}})
        self.assertEqual(baseline,attempt)
        self.assertNotIn('autoAudioFacts',baseline['outcome']['data']['versions'][0])
        enabled = self.detail()
        facts = enabled['outcome']['data']['versions'][0].pop('autoAudioFacts')
        self.assertEqual(0,facts['preferred_ordinal'])
        self.assertEqual(baseline['outcome'],enabled['outcome'])
        self.assertEqual(baseline['requests'],enabled['requests'])

    def test_effective_preference_null_or_malformed_is_not_absent_preference(self):
        def preference(value):
            return lambda wire: wire['versions'][0].update(effective_audio_track_index=value)
        result = self.detail(mutate=preference(1))
        version = result['outcome']['data']['versions'][0]
        self.assertEqual({'state':'present','ordinal':1},version['autoAudioFacts']['effective_preference'])
        self.assertEqual([True,False,False],[t['isDefault'] for t in version['audioTracks']])
        for value in (None,True,'1',3):
            with self.subTest(preference=value):
                result = self.detail(mutate=preference(value))
                self.assertTrue(result['outcome']['ok'])
                self.assertNotIn('autoAudioFacts',result['outcome']['data']['versions'][0])
                self.assertEqual(['GET'],[r['method'] for r in result['requests']])

    def test_source_title_role_facts_are_separate_and_unreviewed_flags_cannot_be_coerced(self):
        def titles(wire):
            wire['versions'][0]['audio_tracks'][1].update(title='Main',embedded_title='Main audio')
            wire['versions'][0]['autoAudioFacts']={'secret':'synthetic-untrusted-marker'}
        result = self.detail(mutate=titles)
        facts = result['outcome']['data']['versions'][0]['autoAudioFacts']
        self.assertEqual(('Main','Main audio','main'),tuple(facts['tracks'][1][k] for k in ('title','embedded_title','role')))
        self.assertNotIn('synthetic-untrusted-marker',str(result['outcome']))
        for field,value in (('default','true'),('hearing_impaired',False),('hearing_impaired',None)):
            def malformed(wire,field=field,value=value):
                wire['versions'][0]['audio_tracks'][0][field]=value
            with self.subTest(field=field,value=value):
                result=self.detail(mutate=malformed)
                self.assertTrue(result['outcome']['ok'])
                self.assertNotIn('autoAudioFacts',result['outcome']['data']['versions'][0])

    def test_native_start_retains_fresh_facts_without_serializing_them_into_start(self):
        producer.P7ProducerFlow.setUpClass()
        def changed_preference(wire,decision):
            wire['versions'][0]['effective_audio_track_index']=2
        result = producer.P7ProducerFlow().run_task(mutate=changed_preference,
            features=['native_hls_separate_audio_v1'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        version = result['outcome']['data']['playbackDetail']['versions'][0]
        self.assertEqual(2,version['autoAudioFacts']['preferred_ordinal'])
        self.assertEqual('truehd',version['audioCodec'])
        self.assertEqual([True,False,False],[t['isDefault'] for t in version['audioTracks']])
        self.assertEqual(1,sum('/playback/start' in r['url'] for r in result['requests']))
        self.assertFalse(any('autoAudioFacts' in r.get('body','') for r in result['requests']))
