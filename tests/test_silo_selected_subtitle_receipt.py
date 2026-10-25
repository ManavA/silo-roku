"""The selected source subtitle receipt is bounded before any native binding."""
import copy
import unittest
from pathlib import Path

from tools.brightscript import run_function

POLICY = Path(__file__).resolve().parents[1] / 'source/core/SiloPlaybackPolicy.brs'
ADAPTER = Path(__file__).resolve().parents[1] / 'source/adapters/SiloAdapter.brs'
BASE = 'https://silo.example'


def item(index=1, file_id='42', session='session-0001', **changes):
    row = dict(track_id=f'file:{file_id}:subtitle:{index}', combined_index=index,
               source='external', codec='subrip', language='eng', label='English',
               forced=False, default=False, hearing_impaired=False,
               delivery='sidecar', url=f'/api/v2/stream/{session}/subtitles/{index}.vtt?file_id={file_id}')
    row.update(changes)
    return row


def selected(mode='render', file_id='42', session='session-0001', **changes):
    subtitle = dict(mode=mode, track_id=f'file:{file_id}:subtitle:1',
                    inventory=[item(0, file_id, session), item(1, file_id, session)],
                    artifact=dict(url=f'/api/v2/stream/{session}/subtitles/1.vtt?file_id={file_id}',
                                  mime_type='text/vtt', format='vtt',
                                  timing_origin_seconds=0))
    subtitle.update(changes)
    return dict(effective_media_file_id=file_id,
                selected_tracks={'audio': {'id': f'file:{file_id}:audio:0', 'index': 0},
                                 'subtitle': {'id': f'file:{file_id}:subtitle:1', 'index': 1}},
                subtitle=subtitle)


class SelectedSubtitleReceiptTests(unittest.TestCase):
    def receipt(self, plan):
        return run_function([POLICY, ADAPTER], 'SiloSelectedSubtitleReceipt', [plan, BASE, 'session-0001'])

    def test_exact_sidecar_is_private_and_public_metadata_has_no_url(self):
        result = self.receipt(selected())
        self.assertTrue(result['ok'], result)
        public = result['public']
        self.assertEqual(('sidecar_pending', 'render', 'file:42:subtitle:1', 1, 'eng', 'vtt'),
                         (public['kind'], public['mode'], public['trackId'],
                          public['combinedIndex'], public['language'], public['format']))
        self.assertFalse(public['renderingReady'])
        self.assertNotIn('url', str(public).lower())
        self.assertEqual('https://silo.example/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42',
                         result['privateArtifact']['url'])

    def test_off_burn_embedded_and_unsupported_do_not_expose_artifact(self):
        off = selected('off', track_id='', artifact=None, inventory=[])
        del off['selected_tracks']['subtitle']
        burn = selected('burn_in', artifact=None)
        embedded = selected('render', artifact=None,
                            embedded={'stream_index': 3, 'container_track_id': '4'})
        embedded['subtitle']['inventory'][1].update(source='embedded', url=None)
        unsupported = selected(artifact=dict(url='/api/v2/stream/session-0001/subtitles/1.ass?file_id=42',
                                             mime_type='text/x-ssa', format='ass',
                                             timing_origin_seconds=0))
        unsupported['subtitle']['inventory'][1]['url'] = '/api/v2/stream/session-0001/subtitles/1.ass?file_id=42'
        for raw, kind in ((off, 'off'), (burn, 'burn_in'),
                          (embedded, 'embedded_render'), (unsupported, 'unsupported')):
            with self.subTest(kind=kind):
                result = self.receipt(raw)
                self.assertTrue(result['ok'], result)
                self.assertEqual(kind, result['public']['kind'])
                self.assertIsNone(result['privateArtifact'])
                self.assertNotIn('url', str(result['public']).lower())

    def test_convert_accepts_only_server_vtt_extension_substitution(self):
        raw = selected('convert')
        raw['subtitle']['inventory'][1].update(codec='ass',
                                                url='/api/v2/stream/session-0001/subtitles/1.ass?file_id=42&embedded_stream_index=3')
        raw['subtitle']['artifact']['url'] = '/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42&embedded_stream_index=3'
        result = self.receipt(raw)
        self.assertTrue(result['ok'], result)
        self.assertEqual('sidecar_pending', result['public']['kind'])
        self.assertEqual('https://silo.example/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42&embedded_stream_index=3',
                         result['privateArtifact']['url'])
        altered = copy.deepcopy(raw)
        altered['subtitle']['artifact']['url'] = '/api/v2/stream/session-0001/subtitles/0.vtt?file_id=42&embedded_stream_index=3'
        self.assertFalse(self.receipt(altered)['ok'])

        srt = selected('convert')
        srt['subtitle']['inventory'][1].update(codec='subrip',
            url='/api/v2/stream/session-0001/subtitles/1.srt?file_id=42&original=1&downloaded_subtitle_id=77')
        srt['subtitle']['artifact']['url'] = (
            '/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42&downloaded_subtitle_id=77')
        converted = self.receipt(srt)
        self.assertTrue(converted['ok'], converted)
        self.assertEqual('sidecar_pending', converted['public']['kind'])
        self.assertEqual('https://silo.example/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42&downloaded_subtitle_id=77',
                         converted['privateArtifact']['url'])

    def test_identity_ordinal_and_origin_disagreement_fail_closed(self):
        cases = []
        wrong = selected(); wrong['selected_tracks']['subtitle']['index'] = 0; cases.append(wrong)
        wrong = selected(); wrong['subtitle']['track_id'] = 'file:42:subtitle:0'; cases.append(wrong)
        wrong = selected(); wrong['subtitle']['inventory'][1]['combined_index'] = 3; cases.append(wrong)
        wrong = selected(); wrong['subtitle']['inventory'][1]['track_id'] = 'file:42:subtitle:0'; cases.append(wrong)
        wrong = selected(); wrong['subtitle']['artifact']['url'] = 'https://foreign.example/secret.vtt'; cases.append(wrong)
        wrong = selected(); wrong['subtitle']['artifact']['url'] = '//foreign.example/secret.vtt'; cases.append(wrong)
        wrong = selected(); wrong['subtitle']['artifact']['mime_type'] = 'text/html'; cases.append(wrong)
        wrong = selected(); wrong['subtitle']['inventory'] *= 129; cases.append(wrong)
        for raw in cases:
            with self.subTest(raw=raw['subtitle'].get('artifact')):
                result = self.receipt(raw)
                self.assertFalse(result['ok'], result)
                self.assertIsNone(result['privateArtifact'])

    def test_missing_old_server_subtitle_is_nonblocking(self):
        result = self.receipt({'effective_media_file_id': 'f1', 'selected_tracks': {'audio': {'id': 'a'}}})
        self.assertTrue(result['ok'])
        self.assertIsNone(result['public'])
        self.assertIsNone(result['privateArtifact'])

    def test_same_origin_sidecar_must_match_session_file_and_ordinal(self):
        for path in ('/api/v2/stream/other-session/subtitles/1.vtt?file_id=42',
                     '/api/v2/stream/session-0001/subtitles/1.vtt?file_id=99',
                     '/api/v2/stream/session-0001/subtitles/0.vtt?file_id=42',
                     '/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42&file_id=99'):
            raw = selected()
            raw['subtitle']['artifact']['url'] = path
            raw['subtitle']['inventory'][1]['url'] = path
            with self.subTest(path=path):
                self.assertFalse(self.receipt(raw)['ok'])

    def test_internal_numeric_file_id_is_not_a_v2_wire_id(self):
        raw = selected()
        raw['effective_media_file_id'] = 42
        raw['selected_tracks']['subtitle']['id'] = 'file:42:subtitle:1'
        raw['subtitle']['track_id'] = 'file:42:subtitle:1'
        for index, row in enumerate(raw['subtitle']['inventory']):
            row['track_id'] = f'file:42:subtitle:{index}'
        result = self.receipt(raw)
        self.assertFalse(result['ok'], result)


if __name__ == '__main__':
    unittest.main()
