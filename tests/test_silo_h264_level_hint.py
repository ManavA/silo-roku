"""H264 source proof uses fresh same-profile decoder ceiling evidence."""
import json
import unittest
from unittest.mock import patch

from tests import test_silo_playback_task as native
from tests import test_silo_sdr_dv_classification as sdr


class H264LevelHint(unittest.TestCase):
    def run_proof(self, hint=None, higher=True, codec='h264', mutate=None):
        version = sdr.SDRDVClassification().version()
        if codec == 'hevc':
            version['videoCodec'] = 'hevc'
            version['videoTracks'][0].update(codec='hevc', profile='Main', level=120)
        if mutate:
            mutate(version)
        hint = {'result':False,'updated':'level','level':['4.2','4.1']} if hint is None else hint
        answer = json.dumps(hint).replace('"', '""')
        sdk = native.BOUNDARIES.replace('if m.rejectMain10 = true', '''if format.level="4.0" then return ParseJson("''' + answer + '''")
        if format.level<>invalid then return {result:''' + str(higher).lower() + '''}
        if m.rejectMain10 = true''')
        sdk += '''
function RunH264SourceProof(version as Object) as Object
 device=FixtureSiloDevice()
 proof=TaskSiloVersionProof(version,device,{}, {})
 return {proof:proof,queries:device.videoQueries,version:version}
end function
'''
        with patch.object(native, 'BOUNDARIES', sdk):
            return native.SiloPlaybackTaskTests().worker('RunH264SourceProof', [version])

    def test_level_only_hint_rechecks_smallest_ceiling_without_changing_source(self):
        result = self.run_proof()
        self.assertEqual(dict(pixels=1536000,hdrScore=0,bitrate=10264), result['proof'])
        self.assertEqual([dict(codec='mpeg4 avc',container='mkv',profile='high',level=level)
                          for level in ['4.0','4.1']], result['queries'])
        self.assertEqual(40, result['version']['videoTracks'][0]['level'])

    def test_hint_requires_fresh_positive_same_format_requery(self):
        result = self.run_proof(higher=False)
        self.assertIsNone(result['proof'])
        self.assertEqual(['4.0','4.1'], [q['level'] for q in result['queries']])

    def test_non_level_and_unbounded_hints_cannot_prove_native_source(self):
        invalid = [dict(result=False), dict(result=False, updated='profile', level=['4.1']),
                   dict(result=False, updated=['level'], level=['4.1']),
                   dict(result=False, updated='level,profile', level=['4.1']),
                   dict(result=False, updated='level', level='4.1'),
                   dict(result=False, updated='level', level=[]),
                   dict(result=False, updated='level', level=['4.1'] * 10),
                   dict(result=False, updated='level', level=['4.1', '9.9']),
                   dict(result=False, updated='level', level=[4.1]),
                   dict(result=False, updated='level', level=['3.1']),
                   dict(result=False, updated='level', level=['4.1'], profile='main'),
                   dict(result=False, updated='level', level=['4.1'], codec='hevc'),
                   dict(result=False, updated='level', level=['4.1'], container='mp4'),
                   dict(updated='level', level=['4.1'])]
        for hint in invalid:
            with self.subTest(hint=hint):
                result = self.run_proof(hint)
                self.assertIsNone(result['proof'])
                self.assertEqual(1, len(result['queries']))

    def test_hevc_level_hint_never_authorizes_source(self):
        result = self.run_proof(codec='hevc')
        self.assertIsNone(result['proof'])
        self.assertEqual(1, len(result['queries']))

    def test_higher_decoder_level_does_not_relax_source_dimensions_or_rate(self):
        for change in [dict(width=3840), dict(frame_rate='120'), dict(bit_depth=10)]:
            with self.subTest(change=change):
                result = self.run_proof(mutate=lambda v:v['videoTracks'][0].update(change))
                self.assertIsNone(result['proof'])

    def test_native_h264_selection_retains_existing_native_rank(self):
        sdk = native.BOUNDARIES.replace('if m.rejectMain10 = true', '''if format.codec="mpeg4 avc" and format.level="4.0" then return {result:false,updated:"level",level:["4.1","4.2"]}
        if m.rejectMain10 = true''')
        with patch.object(native, 'BOUNDARIES', sdk):
            result = native.SiloPlaybackTaskTests().native_best_start(incompatible=True)
        starts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['f1'], [p['file_id'] for p in starts])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        with patch.object(native, 'BOUNDARIES', sdk):
            result = native.SiloPlaybackTaskTests().native_best_start()
        starts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['f2'], [p['file_id'] for p in starts])

    def test_canonical_h264_start_and_replan_keep_source_level40(self):
        from tests import test_silo_canonical_ts as canonical
        sdk = native.BOUNDARIES.replace('if m.rejectMain10 = true', '''if format.codec="mpeg4 avc" and format.level="4.0" then return {result:false,updated:"level",level:["4.1","4.2"]}
        if m.rejectMain10 = true''')
        with patch.object(native, 'BOUNDARIES', sdk):
            result = canonical.CanonicalTSControl().scenario(action='playback_replan')
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertEqual(40, result['start']['seekReanchor']['route']['source']['video_level'])
        self.assertEqual(40, result['outcome']['plan']['seekReanchor']['route']['source']['video_level'])

    def test_canonical_h264_replan_requires_fresh_ceiling_support(self):
        from tests import test_silo_canonical_ts as canonical
        sdk = native.BOUNDARIES.replace('if m.rejectMain10 = true', '''if format.codec="mpeg4 avc" and format.level="4.0" then return {result:false,updated:"level",level:["4.1","4.2"]}
        if m.rejectCeiling=true and format.codec="mpeg4 avc" and format.level="4.1" then return {result:false}
        if m.rejectMain10 = true''')
        from tests import test_silo_seek_reanchor_task as seek
        wrapper = seek.WRAPPER.replace('outcome=ExecuteApiAction',
                                      'FixtureSiloDevice().rejectCeiling=true\n outcome=ExecuteApiAction')
        with patch.object(native, 'BOUNDARIES', sdk), patch.object(seek, 'WRAPPER', wrapper):
            result = canonical.CanonicalTSControl().scenario(action='playback_replan')
        self.assertFalse(result['outcome']['ok'], result['outcome'])

    def test_exact_positive_keeps_single_query_and_unsupported_audio_still_refuses(self):
        result = self.run_proof(hint={'result':True})
        self.assertIsNotNone(result['proof'])
        self.assertEqual(['4.0'], [q['level'] for q in result['queries']])
        result = self.run_proof(mutate=lambda v:v.update(audioCodec='truehd'))
        self.assertIsNone(result['proof'])

    def test_mixed_known_hints_choose_smallest_strictly_higher_ceiling(self):
        result = self.run_proof(hint=dict(result=False,updated='level',level=['3.1','4.0','4.2','4.1']))
        self.assertIsNotNone(result['proof'])
        self.assertEqual(['4.0','4.1'], [q['level'] for q in result['queries']])
        result = self.run_proof(hint=dict(result=False,updated='level',level=['3.1','4.0']))
        self.assertIsNone(result['proof'])
        self.assertEqual(['4.0'], [q['level'] for q in result['queries']])
