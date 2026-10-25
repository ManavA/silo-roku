"""Roku playback claims derive from measured decoders, not Android defaults."""

from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/PlaybackPolicy.brs"


class PlaybackPolicyTests(unittest.TestCase):
    def test_only_measured_video_audio_capabilities_are_declared(self):
        caps = run_function(POLICY, "RokuSiloCapabilities", [True, True, True])
        self.assertEqual(caps["codecs_video"], ["h264", "hevc"])
        self.assertEqual(caps["codecs_audio"], ["aac"])
        self.assertEqual(caps["codecs_video_hardware"], [])
        self.assertFalse(caps["hdr"])
        self.assertEqual(caps["containers"], ["mp4", "hls"])

    def test_unsupported_decoder_does_not_become_server_claim(self):
        caps = run_function(POLICY, "RokuSiloCapabilities", [False, False, False])
        self.assertEqual(caps["codecs_video"], [])
        self.assertEqual(caps["codecs_audio"], [])
        self.assertEqual(caps["containers"], [])


if __name__ == "__main__":
    unittest.main()
