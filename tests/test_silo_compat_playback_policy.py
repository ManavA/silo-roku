"""Approved seam: public pure compatibility identity and wire-time policy.

These checks do not wire an adapter, allocate a session or qualify playback.
"""
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloCompatPlaybackPolicy.brs'


class SiloCompatPlaybackPolicyTests(unittest.TestCase):
    def call(self, function, *arguments):
        self.assertTrue(POLICY.exists(), 'public compatibility policy is missing')
        return run_function(POLICY, function, list(arguments))

    def test_media_source_uuid_preserves_exact_uint64_decimal_identity(self):
        # Server idcodec.go: type byte 3, seven zero bytes, big-endian uint64.
        vectors = [
            ('1', '03000000-0000-0000-0000-000000000001'),
            ('255', '03000000-0000-0000-0000-0000000000ff'),
            ('256', '03000000-0000-0000-0000-000000000100'),
            ('9007199254740993', '03000000-0000-0000-0020-000000000001'),
            ('18446744073709551615', '03000000-0000-0000-ffff-ffffffffffff'),
        ]
        for decimal, expected in vectors:
            with self.subTest(decimal=decimal):
                self.assertEqual(expected, self.call('SiloCompatMediaSourceId', decimal))

    def test_media_source_id_refuses_noncanonical_or_out_of_range_identity(self):
        for value in (None, True, False, 1, 1.0, {}, [], '', '0', '00', '01',
                      ' 1', '1 ', '+1', '-1', '1.0', '1e3',
                      '18446744073709551616', '999999999999999999999'):
            with self.subTest(value=value):
                self.assertIsNone(self.call('SiloCompatMediaSourceId', value))

    def test_positions_serialize_as_int64_json_ticks(self):
        self.assertTrue(POLICY.exists())
        vectors = [('0#', 0), ('0.125#', 1_250_000), ('4.855#', 48_550_000),
                   ('215#', 2_150_000_000), ('14400#', 144_000_000_000),
                   ('900719925#', 9_007_199_250_000_000)]
        with tempfile.TemporaryDirectory() as directory:
            for seconds, expected in vectors:
                with self.subTest(seconds=seconds):
                    printed = run_brightscript(POLICY,
                        f'ticks=SiloCompatPositionTicks({seconds})\n'
                        'print Type(ticks)\nprint FormatJson({PositionTicks:ticks})',
                        root=Path(directory))
                    kind, payload = printed.strip().splitlines()
                    self.assertEqual('LongInteger', kind)
                    self.assertRegex(payload, r'^\{"PositionTicks":\d+\}$')
                    actual = json.loads(payload)['PositionTicks']
                    self.assertIsInstance(actual, int)
                    self.assertEqual(expected, actual)

    def test_position_ticks_refuse_missing_negative_nonnumeric_and_unsafe_bounds(self):
        self.assertIsNone(self.call('SiloCompatPositionTicks'))
        for value in (None, True, False, -1, -0.001, '4.855', {}, [], 900_719_926):
            with self.subTest(value=value):
                self.assertIsNone(self.call('SiloCompatPositionTicks', value))
        # Preserve this Double boundary: JSON argument parsing yields a Float
        # in the host interpreter and loses the fractional upper-bound input.
        with tempfile.TemporaryDirectory() as directory:
            printed = run_brightscript(POLICY,
                'print SiloCompatPositionTicks(900719925.5#)=invalid',
                root=Path(directory))
        self.assertEqual('true', printed.strip())

    def test_sub_tick_fraction_is_truncated_without_negative_or_decimal_wire_value(self):
        with tempfile.TemporaryDirectory() as directory:
            printed = run_brightscript(POLICY,
                'print FormatJson({PositionTicks:SiloCompatPositionTicks(0.00000015#)})',
                root=Path(directory))
        self.assertEqual('{"PositionTicks":1}', printed.strip())


# Public copied-TS receipt policy; actual official response fields only.
import copy
from tests import test_silo_p8_original_transport as native
FILES=[ROOT/'source/core/SiloCompatPlaybackPolicy.brs',ROOT/'source/core/SiloOriginalPlaybackPolicy.brs',ROOT/'source/core/SiloPlaybackPolicy.brs',ROOT/'source/core/ServerUrlPolicy.brs',ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/adapters/SiloCompatAdapter.brs']
SOURCE='03000000-0000-0000-0000-0000000002db'
class CompatPlaybackPolicy(unittest.TestCase):
 def fixture(self):
  _,wire,_=native.SiloP8OriginalTransportTests().inputs();video=wire['versions'][0]['video_tracks'][0]
  proof=dict(mediaSourceId=SOURCE,video=video,audioOrdinal=1,audioInventory=[dict(codec='aac',language='en',channels=2),dict(codec='eac3',language='en',channels=6)])
  streams=[dict(Index=0,Type='Video',Codec='hevc',Width=video['width'],Height=video['height'],BitDepth=10,VideoRangeType='DOVIWithHDR10',AverageFrameRate=24000/1001),dict(Index=1,Type='Audio',Codec='aac',Language='en',Channels=2),dict(Index=2,Type='Audio',Codec='eac3',Language='en',Channels=6)]
  source=dict(Id=SOURCE,Container='mkv',MediaStreams=streams,DefaultAudioStreamIndex=2,DefaultSubtitleStreamIndex=-1,SupportsDirectPlay=False,SupportsTranscoding=True,SiloSeekReanchor=True,TranscodingSubProtocol='hls',TranscodingContainer='ts',TranscodingUrl='/Videos/'+SOURCE+'/remux-ts-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId='+SOURCE,DirectStreamUrl='/stream?api_key=discard')
  return dict(PlaySessionId='play-fixture',MediaSources=[source]),proof
 def receipt(self,wire,proof):
  with tempfile.TemporaryDirectory() as td:return run_function(FILES,'SiloCompatPlaybackReceipt',[wire,proof,'https://compat.example/media',2],root=Path(td))
 def test_copied_recipe_receipt_preserves_prefix_and_discards_credential_alternative(self):
  wire,proof=self.fixture();r=self.receipt(wire,proof);self.assertEqual('https://compat.example/media'+wire['MediaSources'][0]['TranscodingUrl'],r['url']);self.assertEqual(2,r['audioStreamIndex']);self.assertFalse(r['physicalDVVerified']);self.assertNotIn('api_key',json.dumps(r))
 def test_ts_label_without_exact_copy_recipe_or_matching_source_audio_is_not_authority(self):
  wire,proof=self.fixture()
  for mutate in (lambda s:s.update(TranscodingUrl=s['TranscodingUrl'].replace('/remux-ts-v1','')),lambda s:s.update(TranscodingUrl='https://foreign.example/master.m3u8'),lambda s:s.update(TranscodingUrl=s['TranscodingUrl']+'&api_key=secret'),lambda s:s.update(TranscodingContainer='mp4'),lambda s:s.update(DefaultAudioStreamIndex=1),lambda s:s.update(SiloSeekReanchor=False),lambda s:s['MediaStreams'][0].update(VideoRangeType='HDR10'),lambda s:s['MediaStreams'][2].update(Channels=2),lambda s:s.update(Id='03000000-0000-0000-0000-0000000002dc')):
   with self.subTest(mutate=mutate):
    changed=copy.deepcopy(wire);mutate(changed['MediaSources'][0]);self.assertIsNone(self.receipt(changed,proof))


if __name__ == '__main__':
    unittest.main()
