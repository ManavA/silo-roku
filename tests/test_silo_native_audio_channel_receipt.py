"""Actual Task receipt admission with codec-positive, layout-negative SDK facts."""
import copy
import json
import unittest
from unittest.mock import patch

from tests import test_silo_p7_producer_flow as producer
from tests import test_silo_optional_sdk_resilience as optional


class NativeAudioChannelReceipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        producer.P7ProducerFlow.setUpClass()
        cls.job = copy.deepcopy(producer.P7ProducerFlow.scene_job)

    def test_native_ac3_six_receipt_cannot_override_exact_negative_layout_queries(self):
        device = copy.deepcopy(producer.DEVICE)
        generic = 'if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}'
        device[generic] = 'return {result:format.chcnt=invalid and format.codec="ac3" and format.passthru=0}'
        result = producer.task.CompatContinuation().job(
            scope=copy.deepcopy(self.job), mutate=producer.fixture, device=device,
            features=['native_hls_separate_audio_v1'])
        exact = [query for query in result['audioQueries']
                 if query.get('codec') == 'ac3' and query.get('chcnt') == 6]
        self.assertTrue(exact, 'test must reach exact selected-layout SDK probes')
        self.assertFalse(result['outcome']['ok'],
                         'a codec-only positive cannot authorize the returned AC3-six output')
        self.assertNotIn('plan', result['outcome'])
        self.assertEqual(1, sum(request['method'] == 'DELETE' for request in result['requests']),
                         'the allocated native owner must be retired on receipt refusal')


    def legacy_aac(self, exact='unknown', generic='true'):
        sdk = optional.OptionalSDKResilience().sdk('')
        old = 'return {result:format.codec="aac" and format.passthru=0 and (format.chcnt=invalid or format.chcnt=2)}'
        if exact == 'throw':
            unknown = 'throw "synthetic-exact-aac-query"'
        elif exact == 'malformed':
            unknown = 'return {result:"true"}'
        else:
            unknown = 'return invalid' if exact == 'unknown' else 'return {result:'+exact+'}'
        generic_reply = 'return invalid' if generic == 'unknown' else 'return {result:'+generic+'}'
        new = ('if format.codec="aac" and format.passthru=0\n'
               ' if format.chcnt=2 then '+unknown+'\n'
               ' if format.chcnt=invalid\n if m.receiptStarted=true then '+generic_reply+'\n return {result:true}\n end if\n'
               'end if\nreturn {result:false}')
        self.assertIn(old,sdk)
        sdk=sdk.replace(old,new,1)
        # Keep discovery truthful/positive; only the fresh receipt query changes
        # after the actual native POST, so refusal exercises owned cleanup.
        http='    response = m.responses.Shift()'
        self.assertIn(http,sdk)
        sdk=sdk.replace(http,'    if request.method="POST" and Instr(1,request.url,"/playback/start")>0 then FixtureSiloDevice().receiptStarted=true\n'+http,1)
        with patch.object(optional.OptionalSDKResilience,'sdk',return_value=sdk):
            return optional.OptionalSDKResilience().start()

    def test_legacy_aac_stereo_unknown_exact_query_preserves_fresh_generic_ts_decode(self):
        result = self.legacy_aac()
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertTrue(any(q.get('codec')=='aac' and q.get('container')=='ts' and
                            q.get('chcnt')==2 and q.get('passthru')==0 for q in result['audioQueries']))
        self.assertFalse(any(r['method']=='DELETE' for r in result['requests']))
        self.assertEqual('server_transcode_hls',result['outcome']['plan']['playbackDiagnostics']['delivery'])


    def receipt(self, answer, *, mutate=None, job=None):
        device=copy.deepcopy(producer.DEVICE)
        generic='if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}'
        device[generic]=answer
        def source(wire,decision):
            producer.fixture(wire,decision)
            if mutate:mutate(wire,decision)
        return producer.task.CompatContinuation().job(enabled=False,
            scope=copy.deepcopy(self.job) if job is None else job,mutate=source,device=device,
            features=['native_hls_separate_audio_v1'])

    def assert_owned_refusal(self,result,session='session-fixture-01'):
        self.assertFalse(result['outcome']['ok'],result['outcome'])
        self.assertNotIn('plan',result['outcome'])
        self.assertEqual(1,sum('/playback/start' in r['url'] for r in result['requests']))
        deletes=[r for r in result['requests'] if r['method']=='DELETE']
        self.assertEqual(1,len(deletes))
        self.assertTrue(deletes[0]['url'].endswith('/playback/'+session))
        self.assertEqual('server-install',json.loads(deletes[0]['body'])['installation_id'])

    def test_split_video_mp4_still_requires_ts_audio_decode_or_passthrough(self):
        for direction in (0,1):
            with self.subTest(direction=direction):
                answer=('return {result:format.codec="ac3" and ((format.chcnt=invalid and format.passthru=0) or '
                        '(format.chcnt=6 and format.container="ts" and format.passthru='+str(direction)+'))}')
                result=self.receipt(answer)
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                self.assertEqual([0,1],[q['passthru'] for q in result['audioQueries'][-2:]])
                self.assertTrue(all(q.get('container')=='ts' and q.get('chcnt')==6 for q in result['audioQueries'][-2:]))
                self.assertFalse(any(r['method']=='DELETE' for r in result['requests']))
        for answer in ('return {result:format.codec="ac3" and format.passthru=0 and (format.chcnt=invalid or format.container="mp4")}',
                       'if format.chcnt=6 then return invalid\nreturn {result:format.codec="ac3" and format.chcnt=invalid and format.passthru=0}'):
            with self.subTest(answer=answer):
                self.assert_owned_refusal(self.receipt(answer))

    def test_delivered_aac_conversion_can_play_even_when_source_truehd_cannot(self):
        job=copy.deepcopy(self.job)
        for key in list(job['params']):
            if key.lower() in ('audiotrackid','audiotrackindex'):del job['params'][key]
        job['params'].update(audioTrackId='file:731:audio:0',audioTrackIndex=0)
        def converted(wire,decision):
            plan=decision['playback_plan']
            plan['source'].update(audio_codec='truehd',audio_channels=8,audio_layout='7.1')
            plan['selected_tracks']['audio'].update(id='file:731:audio:0',index=0)
            plan['effective_recipe'].update(audio_codec='aac',audio_channels=2,audio_layout='stereo')
            plan['claims']['audio'].update(codec='aac',passthrough=False)
            plan['transformations'].append(dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode']))
        answer='return {result:format.codec="aac" and format.passthru=0 and (format.chcnt=invalid or (format.chcnt=2 and format.container="ts"))}'
        result=self.receipt(answer,mutate=converted,job=job)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertFalse(any(r['method']=='DELETE' for r in result['requests']))
        posted=json.loads(next(r['body'] for r in result['requests'] if '/playback/start' in r['url']))
        self.assertEqual(('file:731:audio:0',0),(posted['audio_track_id'],posted['audio_track_index']))
        self.assertTrue(all(q.get('codec')=='aac' and q.get('chcnt')==2 and q.get('container')=='ts' for q in result['audioQueries'][-2:]))

    def test_aac_stereo_baseline_never_overrides_exact_false_or_unknown_generic(self):
        for exact,generic in (('false','true'),('unknown','false'),('unknown','unknown')):
            with self.subTest(exact=exact,generic=generic):
                result=self.legacy_aac(exact,generic)
                self.assert_owned_refusal(result,session='sess-1')
                exact_pair=[dict(codec='aac',chcnt=2,container='ts',passthru=direction) for direction in (0,1)]
                if exact=='false':
                    self.assertEqual(exact_pair,result['audioQueries'][-2:])
                else:
                    self.assertEqual(exact_pair+[dict(codec='aac',container='ts',passthru=0)],result['audioQueries'][-3:])
        self.assertTrue(self.legacy_aac('true')['outcome']['ok'])

    def test_unknown_copy_channel_count_cannot_be_inferred_from_codec_or_source(self):
        def omitted(wire,decision):
            del decision['playback_plan']['effective_recipe']['audio_channels']
        answer='return {result:format.codec="ac3" and format.passthru=0}'
        self.assert_owned_refusal(self.receipt(answer,mutate=omitted))


    def test_stereo_query_faults_are_unknown_but_surround_never_gets_baseline_inference(self):
        for exact in ('throw','malformed'):
            with self.subTest(exact=exact):
                result=self.legacy_aac(exact)
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                sequence=[dict(codec='aac',chcnt=2,container='ts',passthru=direction) for direction in (0,1)]
                sequence.append(dict(codec='aac',container='ts',passthru=0))
                queries=result['audioQueries']
                self.assertTrue(any(queries[i:i+3]==sequence for i in range(len(queries)-2)),queries)
        def surround(wire,decision):
            plan=decision['playback_plan']
            plan['effective_recipe'].update(audio_codec='aac',audio_channels=6,audio_layout='5.1')
            plan['claims']['audio'].update(codec='aac',passthrough=False)
            plan['transformations'].append(dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode']))
        answer='if format.codec="aac" and format.chcnt=6 then return invalid\nreturn {result:format.chcnt=invalid and (format.codec="aac" or format.codec="ac3") and format.passthru=0}'
        self.assert_owned_refusal(self.receipt(answer,mutate=surround))


if __name__ == '__main__':
    unittest.main()
