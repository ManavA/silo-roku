"""Fresh source/snapshot and immutable V3 receipt seams; no native decode claim."""
import copy
import json
from pathlib import Path
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'source/core/SiloOriginalPlaybackPolicy.brs', ROOT/'source/adapters/SiloAdapter.brs']

class SiloOriginalP8PolicyTests(unittest.TestCase):
    def fixture(self):
        f = json.loads((ROOT/'tests/fixtures/silo/original_p7_candidate.json').read_text())
        f['deviceSnapshot']['os'] = dict(major='16', minor='0', revision='4', build='834')
        v = f['freshFile']['wire']['video_tracks'][0]
        v.update(dv_profile=8, dv_bl_compat_id=1, dv_el_present=False, dv_enhancement_layer='none', level=150)
        wire = f['freshFile']['wire']
        wire['audio_tracks'] = [dict(codec='eac3', language='en', channels=6, layout='5.1(side)', default=True)]
        wire['effective_audio_track_index'] = 0
        wire['codec_audio'] = 'eac3'
        f['deviceSnapshot']['audioQueries'][0]['codec'] = 'eac3'
        return f

    def call(self, name, *args):
        return run_function(FILES, name, list(args))

    def eligible(self, f=None, selected=None):
        f = f or self.fixture()
        return self.call('SiloOriginalEligibility', f['freshFile'], selected, f['deviceSnapshot'], f['requestIntent'])

    def receipt(self, f, proof):
        plan = json.loads((ROOT/'tests/fixtures/silo/original_p7_receipt.json').read_text())
        plan['source'].update(video_level=f['freshFile']['wire']['video_tracks'][0]['level'], dolby_vision_profile=8, dv_bl_compat_id=1, dv_enhancement_layer='none', audio_codec=proof['audioIdentity']['codec'])
        plan['effective_recipe']['audio_codec'] = proof['audioIdentity']['codec']
        plan['selected_tracks']['audio'] = {k:proof['audioIdentity'][k] for k in ('index','id')}
        owner = dict(f['requestIntent'], sessionId='session-fixture-01', outputFingerprint='fixture-output-4')
        return plan, owner

    def test_p8_default_eac3_accepts_both_source_levels_without_activation(self):
        for level in (150,153):
            f=self.fixture();f['freshFile']['wire']['video_tracks'][0]['level']=level
            result=self.eligible(f)
            self.assertTrue(result['ok'],result)
            self.assertEqual('eac3',result['proof']['audioIdentity']['codec'])
            self.assertEqual([],self.call('SiloOriginalClaims',result['proof']))

    def test_p8_default_ac3_and_profile_firmware_boundaries(self):
        f=self.fixture()
        f['freshFile']['wire']['audio_tracks'][0]['codec']='ac3'
        f['deviceSnapshot']['audioQueries'][0]['codec']='ac3'
        self.assertTrue(self.eligible(f)['ok'])
        p7=json.loads((ROOT/'tests/fixtures/silo/original_p7_candidate.json').read_text())
        f['deviceSnapshot']['os']=copy.deepcopy(p7['deviceSnapshot']['os'])
        self.assertFalse(self.eligible(f)['ok'])
        p7['deviceSnapshot']['os']=self.fixture()['deviceSnapshot']['os']
        self.assertFalse(self.eligible(p7)['ok'])
        f=self.fixture();f['freshFile']['fresh']=False
        self.assertFalse(self.eligible(f)['ok'])

    def test_el_omission_is_allowed_but_unknown_or_nonboolean_values_refuse(self):
        f=self.fixture();del f['freshFile']['wire']['video_tracks'][0]['dv_el_present']
        self.assertTrue(self.eligible(f)['ok'])
        for value in (True,0,'false',None,{},[]):
            f=self.fixture();f['freshFile']['wire']['video_tracks'][0]['dv_el_present']=value
            self.assertFalse(self.eligible(f)['ok'],repr(value))
        for value in ('unknown','',None,'mel','fel'):
            f=self.fixture();f['freshFile']['wire']['video_tracks'][0]['dv_enhancement_layer']=value
            self.assertFalse(self.eligible(f)['ok'],repr(value))

    def test_p8_requires_exact_device_fresh_decoder_and_source_facts(self):
        for section,key,value in [('deviceSnapshot','modelNumber','C209X'),('deviceSnapshot','fresh',False),('deviceSnapshot','videoMode','2160p30'),('deviceSnapshot','hdr10',False)]:
            f=self.fixture();f[section][key]=value;self.assertFalse(self.eligible(f)['ok'])
        for group,key,value in [('os','build','835'),('os','major','15'),('videoQuery','level','5.0'),('videoQuery','container','mp4'),('videoQuery','result',False)]:
            f=self.fixture();f['deviceSnapshot'][group][key]=value;self.assertFalse(self.eligible(f)['ok'])
        for key,value in [('dv_profile',5),('dv_bl_compat_id',6),('dv_level',5),('level',156),('bit_depth',8),('color_transfer','arib-std-b67'),('color_primaries','bt709'),('color_space','bt709'),('dv_rpu_present',False),('dv_config_present',False),('dv_bl_present',False)]:
            f=self.fixture();f['freshFile']['wire']['video_tracks'][0][key]=value;self.assertFalse(self.eligible(f)['ok'],key)

    def test_eac3_exact_positive_mkv_channel_query_required_and_p7_unchanged(self):
        for key,value in [('codec','ac3'),('container','mp4'),('chcnt',2),('result',False)]:
            f=self.fixture();f['deviceSnapshot']['audioQueries'][0][key]=value;self.assertFalse(self.eligible(f)['ok'])
        p7=json.loads((ROOT/'tests/fixtures/silo/original_p7_candidate.json').read_text())
        self.assertTrue(self.eligible(p7)['ok'])
        p7['freshFile']['wire']['audio_tracks']=self.fixture()['freshFile']['wire']['audio_tracks']
        p7['deviceSnapshot']['audioQueries']=self.fixture()['deviceSnapshot']['audioQueries']
        self.assertFalse(self.eligible(p7)['ok'])

    def test_unknown_dts_program_refuses_auto_but_unique_explicit_ac3_is_pinned(self):
        f=self.fixture();tracks=f['freshFile']['wire']['audio_tracks']
        tracks[0].update(codec='dts',title='Unidentified program')
        tracks.append(dict(codec='ac3',language='en',channels=6,layout='5.1(side)',default=False))
        f['deviceSnapshot']['audioQueries']=[dict(codec='ac3',container='mkv',chcnt=6,result=True)]
        self.assertFalse(self.eligible(f)['ok'])
        result=self.eligible(f,dict(index=1,explicit=True))
        self.assertTrue(result['ok'],result)
        self.assertEqual(1,result['proof']['audioIdentity']['index'])
        tracks.append(copy.deepcopy(tracks[1]))
        self.assertFalse(self.eligible(f,dict(index=1,explicit=True))['ok'])

    def test_receipt_uses_p8_immutable_source_audio_and_lease_bounds(self):
        f=self.fixture();proof=self.eligible(f)['proof'];plan,owner=self.receipt(f,proof)
        result=self.call('SiloOriginalReceipt',proof,plan,owner)
        self.assertTrue(result['ok'])
        self.assertEqual(8,result['descriptor']['dolbyVisionProfile'])
        for section,key,value in [('source','dolby_vision_profile',7),('source','dv_bl_compat_id',6),('source','dv_enhancement_layer','unknown'),('source','video_level',153),('source','audio_codec','ac3'),('effective_recipe','audio_codec','ac3'),('source','media_file_id','732'),('selected_tracks','audio',dict(index=1,id='file:731:audio:1'))]:
            changed=copy.deepcopy(plan);changed[section][key]=value
            self.assertFalse(self.call('SiloOriginalReceipt',proof,changed,owner)['ok'],key)
        for key,value in [('session_id','different-lease'),('delivery','remux'),('transformations',[{}]),('runtime_corrections',[{}])]:
            changed=copy.deepcopy(plan);changed[key]=value
            self.assertFalse(self.call('SiloOriginalReceipt',proof,changed,owner)['ok'],key)
        bad=copy.deepcopy(proof);bad['videoFacts']['dv_el_present']=True
        self.assertFalse(self.call('SiloOriginalReceipt',bad,plan,owner)['ok'])

    def test_unscoped_pure_eligibility_cannot_authorize_ordinary_task_promotion(self):
        f=self.fixture()
        f['freshFile']['wire']['audio_tracks']=[dict(codec='dts',language='en',channels=6,layout='5.1',default=True),dict(codec='ac3',language='en',channels=2,layout='stereo',default=False)]
        f['deviceSnapshot']['audioQueries']=[dict(codec='ac3',container='mkv',chcnt=2,result=True)]
        result=self.eligible(f,dict(index=1,explicit=True))
        self.assertTrue(result['ok'])
        self.assertNotIn('qualifiedRoute',result['proof'])
        self.assertEqual([],self.call('SiloOriginalClaims',result['proof']))

if __name__ == '__main__':
    unittest.main()
