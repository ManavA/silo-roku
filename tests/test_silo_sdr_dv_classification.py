"""Native source proof distinguishes absent DV enhancement layers from DV signals."""
import unittest
from tests import test_silo_playback_task as native


class SDRDVClassification(unittest.TestCase):
    def version(self):
        return dict(container='mkv', videoCodec='h264', audioCodec='eac3',
            hdr=False, bitrateKbps=10264, videoTracks=[dict(codec='h264',
                profile='High', level=40, width=1920, height=800, bit_depth=8,
                frame_rate='23.976', interlaced=False, color_transfer='bt709',
                color_primaries='bt709', color_space='bt709',
                dv_config_present=False, dv_bl_compat_id_present=False,
                dv_enhancement_layer='none')])

    def proof(self, version, caps=None):
        return native.SiloPlaybackTaskTests().worker('RunVersionProof', [version, caps or {}, {}])

    def test_explicit_absent_enhancement_layer_keeps_h264_sdr_native_proof(self):
        self.assertEqual(dict(pixels=1536000, hdrScore=0, bitrate=10264), self.proof(self.version()))

    def test_real_dv_signals_and_invalid_h264_bounds_remain_refused(self):
        changes = [dict(dv_enhancement_layer=x) for x in ('unknown', 'mel', 'fel')]
        changes += [dict(dv_config_present=True), dict(dv_rpu_present=True),
                    dict(dv_profile=8), dict(dv_el_present=True),
                    dict(width=1921), dict(height='800')]
        for change in changes:
            with self.subTest(change=change):
                version = self.version()
                version['videoTracks'][0].update(change)
                self.assertIsNone(self.proof(version))

    def hevc(self, hdr):
        version = self.version()
        version.update(videoCodec='hevc', hdr=hdr)
        version['videoTracks'][0].update(codec='hevc', profile='Main 10', level=153,
            width=3840, height=2160, bit_depth=10,
            color_transfer='smpte2084' if hdr else 'bt709')
        return version

    def test_explicit_absent_layer_keeps_hevc_sdr_and_hdr10_native_proof(self):
        for hdr in (False, True):
            with self.subTest(hdr=hdr):
                proof = self.proof(self.hevc(hdr), {'hdr_details': {'hdr10': True}})
                self.assertEqual(dict(pixels=8294400, hdrScore=int(hdr), bitrate=10264), proof)

    def test_absent_layer_does_not_hide_positive_hevc_dv_signals(self):
        for signal in ('dv_config_present', 'dv_rpu_present', 'dv_profile'):
            with self.subTest(signal=signal):
                version = self.hevc(True)
                version['videoTracks'][0][signal] = 8 if signal == 'dv_profile' else True
                self.assertIsNone(self.proof(version, {'hdr_details': {'hdr10': True}}))
