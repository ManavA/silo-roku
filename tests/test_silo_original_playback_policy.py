"""Agreed seam: fresh wire file + snapshot/intent -> eligibility and V3 receipt.
Catches false claims, source/audio/quality drift and unsafe original recipes.
Does not prove native decoding, mapping metadata semantics or physical output.
Literal synthetic fixtures preserve official 48ae audio-array ordinal semantics.
"""
import copy
import json
from pathlib import Path
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'source/core/SiloOriginalPlaybackPolicy.brs', ROOT/'source/adapters/SiloAdapter.brs']

class SiloOriginalPlaybackPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        return run_function(FILES, name, list(args))

    def test_original_claims_remain_disabled_pending_owned_native_acceptance(self):
        self.assertEqual(self.call('SiloOriginalClaims', {'ok': True}), [])

    def fixture(self):
        return json.loads((ROOT/'tests/fixtures/silo/original_p7_candidate.json').read_text())

    def eligibility(self, fixture=None, selected=None):
        f = fixture or self.fixture()
        return self.call('SiloOriginalEligibility', f['freshFile'], selected, f['deviceSnapshot'], f['requestIntent'])

    def test_auto_uses_unique_compatible_ac3_with_official_ordinal_identity(self):
        result = self.eligibility()
        self.assertTrue(result['ok'])
        self.assertEqual(result['proof']['audioIdentity'], {'index': 1, 'id': 'file:731:audio:1', 'codec': 'ac3', 'language': 'en', 'channels': 6, 'layout': '5.1(side)'})
        self.assertEqual(result['proof']['claims'], ['client_managed_dynamic_range_v1', 'client_selected_audio_track_v1'])

    def test_unknown_or_stale_source_and_device_facts_refuse_original(self):
        mutations = [
            ('freshFile', 'fresh', False),
            ('deviceSnapshot', 'fresh', False),
            ('deviceSnapshot', 'modelNumber', 'C209X'),
            ('deviceSnapshot', 'videoMode', '1080p60'),
            ('deviceSnapshot', 'hdr10', False),
        ]
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                f = self.fixture(); f[section][key] = value
                self.assertFalse(self.eligibility(f)['ok'])
        for key, value in [('dv_profile', 8), ('dv_bl_present', False), ('dv_bl_compat_id_present', False), ('dv_bl_compat_id', 1), ('interlaced', True), ('color_transfer', ''), ('bit_depth', 8), ('frame_rate', '120'), ('height', 4320)]:
            with self.subTest(video=key):
                f = self.fixture(); f['freshFile']['wire']['video_tracks'][0][key] = value
                self.assertFalse(self.eligibility(f)['ok'])

    def test_explicit_audio_quality_scope_and_bandwidth_intent_are_pinned(self):
        self.assertFalse(self.eligibility(selected={'index': 0, 'explicit': True})['ok'])
        self.assertTrue(self.eligibility(selected={'index': 1, 'id': 'file:731:audio:1', 'explicit': True})['ok'])
        for key, value in [('fileId', '732'), ('sourceId', 'silo:other'), ('qualityPreference', '1080p'), ('subtitleMode', 'burn_in'), ('bandwidthCapKbps', 20000)]:
            with self.subTest(intent=key):
                f=self.fixture(); f['requestIntent'][key]=value
                self.assertFalse(self.eligibility(f)['ok'])
        f=self.fixture(); f['requestIntent']['scope']['generation']=5
        self.assertFalse(self.eligibility(f)['ok'])

    def test_complete_audio_inventory_keeps_distinct_ordinals_and_refuses_ambiguity(self):
        f=self.fixture(); f['freshFile']['wire']['audio_tracks'][1]['language']='eng'
        result=self.eligibility(f)
        self.assertTrue(result['ok'])
        self.assertEqual(result['proof']['audioIdentity']['language'], 'en')
        self.assertEqual(result['proof']['sourceAudio'], [
            {'index':0,'codec':'truehd','language':'en','channels':8,'layout':'7.1'},
            {'index':1,'codec':'ac3','language':'en','channels':6,'layout':'5.1(side)'}])
        for mutation in ['duplicate', 'explicit_wire_index', 'unknown_language', 'unknown_channels']:
            with self.subTest(mutation=mutation):
                f=self.fixture(); tracks=f['freshFile']['wire']['audio_tracks']
                if mutation=='duplicate': tracks.append(copy.deepcopy(tracks[1]))
                if mutation=='explicit_wire_index': tracks[1]['index']=7
                if mutation=='unknown_language': tracks[1]['language']='und'
                if mutation=='unknown_channels': tracks[1]['channels']=0
                self.assertFalse(self.eligibility(f)['ok'])

    def receipt(self):
        return json.loads((ROOT/'tests/fixtures/silo/original_p7_receipt.json').read_text())

    def owner(self):
        f=self.fixture()
        return dict(f['requestIntent'], sessionId='session-fixture-01', outputFingerprint='fixture-output-4')

    def test_authoritative_original_receipt_returns_bounded_descriptor(self):
        proof=self.eligibility()['proof']
        result=self.call('SiloOriginalReceipt', proof, self.receipt(), self.owner())
        self.assertTrue(result['ok'])
        self.assertEqual(result['descriptor'], {
            'schemaVersion':1,'sourceId':'silo:fixture','itemId':'movie-fixture','fileId':'731',
            'sessionId':'session-fixture-01','planId':'plan-fixture-01',
            'playbackAttemptId':'attempt-fixture-01','outputFingerprint':'fixture-output-4',
            'scope':{'provider':'silo','sourceId':'silo:fixture','profileId':'fixture-profile','generation':4},
            'audioIdentity':{'index':1,'id':'file:731:audio:1','codec':'ac3','language':'en','channels':6,'layout':'5.1(side)'},
            'sourceAudio':[{'index':0,'codec':'truehd','language':'en','channels':8,'layout':'7.1'},{'index':1,'codec':'ac3','language':'en','channels':6,'layout':'5.1(side)'}],
            'mappingMode':'structured_format','dolbyVisionProfile':7,'guarded':True})

    def test_allocated_receipt_with_changed_identity_or_recipe_is_refused(self):
        proof=self.eligibility()['proof']
        changes=[('session_id','other-session'),('effective_media_file_id',732),('requested_media_file_id',732),('delivery','remux_hls'),('decision_reason','client_dv7_to_hdr10'),('transformations',[{'name':'client_dv7_to_hdr10'}])]
        for key,value in changes:
            with self.subTest(receipt=key):
                receipt=self.receipt();receipt[key]=value
                self.assertFalse(self.call('SiloOriginalReceipt',proof,receipt,self.owner())['ok'])
        for section,key,value in [('selected_tracks','audio',{'index':0,'id':'file:731:audio:0'}),('stream','container','ts'),('stream','protocol','hls'),('source','dv_base_layer_proven',False),('source','width',1920),('source','dolby_vision_profile',8),('source','dv_enhancement_layer','fel'),('effective_recipe','dynamic_range','hdr10'),('effective_recipe','audio_codec','truehd'),('effective_recipe','height',1080)]:
            with self.subTest(section=section,key=key):
                receipt=self.receipt();receipt[section][key]=value
                self.assertFalse(self.call('SiloOriginalReceipt',proof,receipt,self.owner())['ok'])
        owner=self.owner();owner['playbackAttemptId']='replacement-attempt'
        self.assertFalse(self.call('SiloOriginalReceipt',proof,self.receipt(),owner)['ok'])
        owner=self.owner();owner['scope']['generation']=5
        self.assertFalse(self.call('SiloOriginalReceipt',proof,self.receipt(),owner)['ok'])

    def test_adapter_preserves_audio_array_position_separately_from_optional_wire_index(self):
        tracks=[{'codec':'truehd','channels':8,'language':'en','layout':'7.1','default':True},{'index':7,'codec':'ac3','channels':6,'language':'en','layout':'5.1(side)','default':False}]
        mapped=self.call('SiloTracks',tracks,True)
        self.assertEqual([(t['sourceOrdinal'],t['wireIndexPresent']) for t in mapped],[(0,False),(1,True)])
        self.assertEqual(mapped[1]['wireIndex'],7)
        self.assertEqual(mapped[1]['layout'],'5.1(side)')
        self.assertEqual(mapped[1]['index'],7) # Existing selector convention is preserved.

    def test_public_wire_omitted_false_boolean_and_url_source_scope_are_supported(self):
        f=self.fixture(); del f['freshFile']['wire']['video_tracks'][0]['hdr10_plus']
        for section in ['freshFile','requestIntent']:
            f[section]['sourceId']='silo:https://silo.example'
            f[section]['scope']['sourceId']='silo:https://silo.example'
        result=self.eligibility(f)
        self.assertTrue(result['ok'])
        owner=self.owner();owner['sourceId']='silo:https://silo.example';owner['scope']['sourceId']=owner['sourceId']
        self.assertTrue(self.call('SiloOriginalReceipt',result['proof'],self.receipt(),owner)['ok'])

    def test_auto_preserves_source_program_role_and_refuses_unknown_role_changes(self):
        for title in ['Director Commentary','Audio Description','Unclassified alternate program']:
            with self.subTest(title=title):
                f=self.fixture();f['freshFile']['wire']['audio_tracks'][1]['embedded_title']=title
                self.assertFalse(self.eligibility(f)['ok'])
        f=self.fixture()
        for track in f['freshFile']['wire']['audio_tracks']:
            track['title']='Main';track['embedded_title']='Original'
        self.assertTrue(self.eligibility(f)['ok'])
        f['freshFile']['wire']['audio_tracks'][1]['title']='Commentary'
        self.assertFalse(self.eligibility(f)['ok'])

    def test_public_file_ids_are_canonical_strings_and_proof_has_no_freeform_text(self):
        f=self.fixture();f['freshFile']['wire']['file_id']=731
        self.assertFalse(self.eligibility(f)['ok'])
        f=self.fixture();f['freshFile']['wire']['video_tracks'][0]['title']='private freeform title'
        f['freshFile']['wire']['audio_tracks'][0]['access_token']='private credential'
        result=self.eligibility(f)
        self.assertTrue(result['ok'])
        self.assertNotIn('private',json.dumps(result))

    def test_malformed_bounded_facts_fail_closed_without_claim_or_runtime_error(self):
        for section,key,value in [('video','profile',7),('video','frame_rate','999999999999/999999999999'),('video','dv_config_present',None),('audio','codec',7),('audio','default',None),('audio','layout',None)]:
            with self.subTest(section=section,key=key):
                f=self.fixture();tracks=f['freshFile']['wire']['video_tracks' if section=='video' else 'audio_tracks'];tracks[0][key]=value
                self.assertFalse(self.eligibility(f)['ok'])
        f=self.fixture();f['freshFile']['wire']['audio_tracks']*=17
        self.assertFalse(self.eligibility(f)['ok'])
        f=self.fixture();f['freshFile']['wire']['video_tracks']*=2
        self.assertFalse(self.eligibility(f)['ok'])

    def test_scanner_codec_fallback_titles_do_not_change_unlabelled_program(self):
        f=self.fixture();tracks=f['freshFile']['wire']['audio_tracks']
        tracks[0].update(title='Dolby TrueHD',embedded_title='')
        tracks[1].update(title='ATSC A/52A (AC-3)',embedded_title='')
        self.assertTrue(self.eligibility(f)['ok'])
        tracks[1]['embedded_title']='ATSC A/52A (AC-3)'
        self.assertTrue(self.eligibility(f)['ok'])
        tracks[1].update(title='Dolby TrueHD',embedded_title='')
        self.assertFalse(self.eligibility(f)['ok'])

    def test_usable_server_preferred_audio_is_never_replaced_to_gain_original(self):
        f=self.fixture();f['freshFile']['wire']['audio_tracks'][0].update(codec='eac3',channels=6,layout='5.1(side)')
        f['deviceSnapshot']['audioQueries'].append({'codec':'eac3','container':'mkv','chcnt':6,'result':True})
        self.assertFalse(self.eligibility(f)['ok'])
        f['freshFile']['wire']['audio_tracks'][0].update(codec='aac',channels=2,layout='stereo')
        f['deviceSnapshot']['audioQueries'].append({'codec':'aac','container':'mkv','chcnt':2,'result':True})
        self.assertFalse(self.eligibility(f)['ok'])
