"""Bounded track diagnostics contain counts and flags, never media identity."""

from pathlib import Path
import unittest

from tools.brightscript import run_function

POLICY = Path(__file__).resolve().parents[1] / "source/core/NativeTrackPolicy.brs"


class NativeTrackDiagnosticsTests(unittest.TestCase):
    def call(self, status, audio, subtitles):
        return run_function(POLICY, "NativeTrackDiagnostic", [status, audio, subtitles])

    def test_native_empty_and_rejected_inventory_are_distinguishable(self):
        status = {"available": True, "audio": [], "subtitles": [], "captionMode": "Off"}
        empty = self.call(status, [], [])
        rejected = self.call(status, [{"Track": ""}], [])
        self.assertEqual(0, empty["rawAudioCount"])
        self.assertEqual(1, rejected["rawAudioCount"])
        self.assertEqual(0, rejected["audioCount"])
        self.assertTrue(rejected["available"])

    def test_private_payloads_cannot_enter_diagnostics(self):
        secret = "https://fixture.test/stream?private-fixture=1"
        result = self.call({"available": True, "attemptId": secret, "versionId": secret,
                            "audio": [{"label": secret}], "subtitles": [{"handle": secret}],
                            "currentAudioHandle": "a-1-0", "currentSubtitleHandle": "s-1-0",
                            "captionMode": "Instant replay", "lastCommand": {"result": secret}},
                           [{"Track": secret}], [{"TrackName": secret}])
        self.assertNotIn(secret, str(result))
        self.assertNotIn("attemptId", result)
        self.assertEqual("none", result["command"])
        self.assertEqual("Instant replay", result["captionMode"])
        self.assertTrue(result["hasCurrentAudio"])

    def test_malformed_fields_and_counts_have_finite_closed_output(self):
        result = self.call({"available": "true", "audio": {}, "subtitles": None,
                            "captionMode": "private-fixture", "currentAudioHandle": 123},
                           [{}] * 1000, "private-fixture")
        self.assertEqual(64, result["rawAudioCount"])
        self.assertEqual(0, result["rawSubtitleCount"])
        self.assertEqual(0, result["audioCount"])
        self.assertFalse(result["available"])
        self.assertFalse(result["hasCurrentAudio"])
        self.assertEqual("", result["captionMode"])


if __name__ == "__main__":
    unittest.main()
