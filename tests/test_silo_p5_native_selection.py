"""Stock omit-empty P5 metadata through fresh runJob selection and HTTP."""
import json
import unittest
from tests import test_silo_compat_continuation as continuation


class P5NativeSelection(unittest.TestCase):
    def start(self, edits=None, omit=()):
        def fixture(wire, decision):
            version = wire['versions'][0]
            version.update(container='mp4', codec_audio='aac', audio_tracks=[dict(codec='aac', language='en', channels=2, layout='stereo', default=True)])
            track = version['video_tracks'][0]
            track.update(dv_profile=5, dv_level=6, dv_config_present=True,
                         dv_bl_compat_id_present=True, dv_bl_present=True,
                         dv_rpu_present=True, dv_enhancement_layer='none')
            track.pop('dv_bl_compat_id', None)
            track.pop('dv_el_present', None)
            track.update(edits or {})
            for key in omit:
                track.pop(key, None)
            variant = wire['playback_variants'][0]
            variant['default_file_id'] = '732'
            variant['parts'][0]['default_file_id'] = '732'
        return continuation.CompatContinuation().job(
            enabled=False, p7_enabled=False, automatic_hdr10=False,
            features=['native_hls_separate_audio_v1'],
            options={'fileId': '732'}, mutate=fixture)

    def requested_files(self, result):
        return [json.loads(x['body'])['file_id'] for x in result['requests']
                if '/playback/start' in x['url']]

    def test_auto_prefers_proven_4k_p5_over_server_default_1080p(self):
        self.assertEqual(['731'], self.requested_files(self.start()))

    def test_explicit_p5_zero_and_false_retain_native_priority(self):
        self.assertEqual(['731'], self.requested_files(self.start(
            {'dv_bl_compat_id': 0, 'dv_el_present': False})))

    def test_incomplete_p5_signal_keeps_supported_default(self):
        for key in ('dv_config_present', 'dv_bl_compat_id_present',
                    'dv_bl_present', 'dv_rpu_present', 'dv_enhancement_layer'):
            with self.subTest(missing=key):
                self.assertEqual(['732'], self.requested_files(self.start(omit=[key])))

    def test_present_invalid_or_contradictory_fields_are_not_repaired(self):
        controls = [
            {'dv_bl_compat_id': None}, {'dv_bl_compat_id': '0'},
            {'dv_bl_compat_id': 1}, {'dv_el_present': None},
            {'dv_el_present': 'false'}, {'dv_el_present': True},
            {'dv_profile': '5'}, {'dv_profile': 8},
            {'dv_rpu_present': 'true'}, {'dv_enhancement_layer': 'fel'},
        ]
        for edits in controls:
            with self.subTest(edits=edits):
                self.assertEqual(['732'], self.requested_files(self.start(edits)))
