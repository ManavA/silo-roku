"""Pure raw-source facts and exact-MP4 chooser; no client activation/decoding claim."""
import copy
import json
import unittest
from pathlib import Path
from tools.brightscript import _execute, PURE_ROOT, run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT/'source/core/SiloPlaybackPolicy.brs',
         ROOT/'source/core/SiloOriginalPlaybackPolicy.brs',
         ROOT/'source/core/SiloAutoAudioPolicy.brs']
TECHNICAL = json.loads((ROOT/'tests/fixtures/silo/stock_p7_hdr10_technical_metadata.json').read_text())


class SiloAutoAudioPolicy(unittest.TestCase):
    def source(self):
        wire = copy.deepcopy(TECHNICAL['native_version'])
        wire['file_id'] = '731'
        return wire

    def project(self, wire):
        encoded = json.dumps(wire).replace('"','""')
        return _execute(FILES,'wire=ParseJson("'+encoded+'")\nfacts=SiloAutoAudioFacts(wire)',
                        PURE_ROOT,'{facts:facts,source:wire}')['result']

    def test_actual_technical_inventory_preserves_defaults_and_unpublished_hi(self):
        wire = self.source()
        self.assertEqual(49, len(wire['video_tracks'])+len(wire['audio_tracks'])+len(wire['subtitle_tracks']))
        result = self.project(wire)
        facts = result['facts']
        self.assertEqual(wire,result['source'])
        self.assertEqual('731',facts['file_id'])
        self.assertEqual({'state':'absent'},facts['effective_preference'])
        self.assertEqual(0,facts['preferred_ordinal'])
        self.assertEqual([True,False,False],[track['default'] for track in facts['tracks']])
        self.assertEqual(('truehd',8),tuple(facts['tracks'][0][k] for k in ('codec','channels')))
        self.assertEqual('file:731:audio:1',facts['tracks'][1]['id'])
        self.assertEqual('unlabelled',facts['tracks'][1]['role'])
        self.assertEqual('en',facts['tracks'][1]['language'])
        for track in facts['tracks']:
            self.assertEqual({'state':'schema_unpublished','value':None},track['hearing_impaired'])
            self.assertFalse(track['title_present'])
            self.assertFalse(track['embedded_title_present'])

    def queries(self):
        return [dict(source_ordinal=i,codec=t['codec'],channels=t['channels'],container='mp4',
                     decode=i==1,passthrough=False)
                for i,t in enumerate(self.source()['audio_tracks'])]

    def choose(self, wire=None, queries=None):
        facts = self.project(self.source() if wire is None else wire)['facts']
        return run_function(FILES,'SiloAutoAudioChoose',[facts,self.queries() if queries is None else queries])

    def test_exact_mp4_equivalent_ac3_six_is_chosen_without_rewriting_default(self):
        answer = self.choose()
        self.assertEqual('auto',answer['mode'])
        self.assertEqual('equivalent_fallback',answer['selection'])
        self.assertEqual(('file:731:audio:1',1,0),tuple(answer[k] for k in ('audio_track_id','audio_track_index','preferred_ordinal')))
        self.assertEqual([True,False,False],[t['default'] for t in answer['basis']['tracks']])
        self.assertEqual('published_language_title_inference',answer['equivalence'])
        self.assertIsNone(answer['basis']['tracks'][1]['hearing_impaired']['value'])

    def test_technical_labels_preserve_unlabelled_equivalence(self):
        wire = self.source()
        for track, label in zip(wire['audio_tracks'], ('Dolby TrueHD 7.1', 'AC-3 5.1', 'AC3 2.0')):
            track.update(title=label, embedded_title=label)
        facts = self.project(wire)['facts']
        self.assertEqual(['unlabelled'] * 3, [t['role'] for t in facts['tracks']])
        answer = self.choose(wire)
        self.assertEqual(('equivalent_fallback', 1), (answer['selection'], answer['audio_track_index']))
        self.assertEqual([True, False, False], [t['default'] for t in answer['basis']['tracks']])

    def test_codec_specific_technical_modifiers_require_matching_layout(self):
        wire = self.source()
        for track, label in zip(wire['audio_tracks'], ('Dolby TrueHD Atmos 7.1', 'Dolby Digital 5.1-EX')):
            track.update(title=label, embedded_title=label)
        self.assertEqual(1, self.choose(wire)['audio_track_index'])

    def test_technical_labels_do_not_relax_unknown_roles_or_sdk_answers(self):
        for label in ('AC-3 5.1 feature', 'AC-3 5.1 English', 'TrueHD 5.1',
                      'AC-3 7.1', 'AC-3 Atmos 5.1', 'AC-3 7.1-EX',
                      'AC-3 5.1 Commentary', 'AC-3 5.1 Audio Description'):
            with self.subTest(label=label):
                wire = self.source()
                wire['audio_tracks'][1].update(title=label, embedded_title=label)
                self.assertIsNone(self.choose(wire))
        wire = self.source()
        wire['audio_tracks'][0].update(title='TrueHD 7.1', embedded_title='TrueHD 7.1')
        wire['audio_tracks'][1].update(title='AC-3 5.1', embedded_title='AC-3 5.1')
        for ordinal in (0, 1):
            queries = self.queries()
            queries[ordinal]['decode'] = None
            self.assertIsNone(self.choose(wire, queries))
        wire['audio_tracks'][1]['layout'] = 'stereo'
        self.assertIsNone(self.choose(wire))

    def test_boolean_query_ordinal_is_not_a_source_ordinal(self):
        queries = self.queries()
        queries[1]['source_ordinal'] = True
        self.assertIsNone(self.choose(queries=queries))

    def test_effective_preference_preserves_presence_and_stock_default_fallback(self):
        wire = self.source()
        wire['effective_audio_track_index'] = 1
        facts = self.project(wire)['facts']
        self.assertEqual({'state':'present','ordinal':1},facts['effective_preference'])
        self.assertEqual(1,facts['preferred_ordinal'])
        self.assertEqual('preferred',self.choose(wire)['selection'])
        for bad in (None,True,'1',-1,3,1.5):
            with self.subTest(preference=bad):
                wire['effective_audio_track_index'] = bad
                self.assertIsNone(self.project(wire)['facts'])
        wire = self.source()
        wire['effective_audio_track_index'] = 1
        wire['EFFECTIVE_AUDIO_TRACK_INDEX'] = 0
        self.assertIsNone(self.project(wire)['facts'])
        wire = self.source()
        wire['audio_tracks'][1]['default'] = True
        self.assertEqual(0,self.project(wire)['facts']['preferred_ordinal'])
        wire['audio_tracks'][0]['default'] = False
        self.assertEqual(1,self.project(wire)['facts']['preferred_ordinal'])
        wire['audio_tracks'][1]['default'] = False
        self.assertEqual(0,self.project(wire)['facts']['preferred_ordinal'])

    def test_preferred_positive_stays_preferred_and_unknown_cannot_authorize_fallback(self):
        queries = self.queries()
        queries[0]['decode'] = True
        answer = self.choose(queries=queries)
        self.assertEqual(('preferred',0),(answer['selection'],answer['audio_track_index']))
        for track,field,value in ((0,'decode',None),(1,'decode',None),(1,'decode',False),
                                  (1,'decode','true'),(1,'container','ts'),
                                  (1,'channels',2),(1,'codec','eac3')):
            with self.subTest(track=track,field=field,value=value):
                queries = self.queries()
                queries[track][field] = value
                self.assertIsNone(self.choose(queries=queries))
        queries = self.queries()
        queries[1].update(decode=None,passthrough=True)
        self.assertEqual(1,self.choose(queries=queries)['audio_track_index'])

    def test_language_role_and_stock_unpublished_flags_remain_conservative(self):
        for field,value in (('language','fr'),('language','zz'),('title','commentary'),
                            ('title','Audio Description'),('title','unreviewed program label')):
            with self.subTest(field=field,value=value):
                wire = self.source()
                wire['audio_tracks'][1][field] = value
                self.assertIsNone(self.choose(wire))
        wire = self.source()
        wire['audio_tracks'][0].update(title='Main',embedded_title='Commentary')
        self.assertEqual('unknown',self.project(wire)['facts']['tracks'][0]['role'])
        self.assertIsNone(self.choose(wire))
        wire = self.source()
        wire['audio_tracks'][0]['title'] = 'Dolby TrueHD'
        wire['audio_tracks'][1]['title'] = 'ATSC A/52A (AC-3)'
        self.assertEqual(1,self.choose(wire)['audio_track_index'])
        for value in (True,False,None,'false'):
            wire = self.source()
            wire['audio_tracks'][1]['hearing_impaired'] = value
            with self.subTest(unreviewed_hi=value):
                self.assertIsNone(self.project(wire)['facts'])

    def test_equal_equivalent_candidates_are_ambiguous_and_source_defaults_stay_typed(self):
        wire = self.source()
        wire['audio_tracks'][2].update(channels=6,layout='5.1')
        queries = self.queries()
        queries[2].update(channels=6,decode=True)
        self.assertIsNone(self.choose(wire,queries))
        for value in (None,'true',1):
            with self.subTest(default=value):
                wire = self.source()
                wire['audio_tracks'][0]['default'] = value
                self.assertIsNone(self.project(wire)['facts'])
