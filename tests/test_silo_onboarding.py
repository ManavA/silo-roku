"""Silo setup must preserve the code through temporary transport failures."""

from pathlib import Path
import json
import unittest

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
SILO = ROOT / "source/adapters/SiloAdapter.brs"


class SiloCapabilityResponseTests(unittest.TestCase):
    def decode(self, action, body):
        try:
            return run_function(SILO, "DecodeSiloResponse", [action, json.dumps(body), {}])
        except RuntimeError:
            self.fail("Capability decoding crashed instead of returning a public result")

    def test_pairing_ignores_allowed_metadata_without_publishing_it(self):
        for allowed in ({"private": "private-marker"}, [], "private-marker", 3):
            with self.subTest(allowed=allowed):
                result = self.decode("device_capability", {
                    "state": "available", "protocol_versions": [2], "allowed": allowed})
                self.assertEqual({"ok": True, "data": {
                    "allowed": True, "state": "available", "protocolVersions": [2]}}, result)
                self.assertNotIn("private-marker", json.dumps(result))

    def test_malformed_protocol_entries_return_an_error_instead_of_crashing(self):
        for versions in ([{}], [[]], [None], [True], ["2"], [2.5]):
            for action in ("device_capability", "playback_capabilities"):
                with self.subTest(action=action, versions=versions):
                    result = self.decode(action, {
                        "state": "available", "protocol_versions": versions, "allowed": True})
                    self.assertFalse(result["ok"])
                    self.assertEqual("invalid_response", result["errorCode"])
                    self.assertNotIn("data", result)

    def test_playback_requires_a_boolean_allowed_flag(self):
        for allowed in ({}, [], "true", 1, None):
            with self.subTest(allowed=allowed):
                result = self.decode("playback_capabilities", {
                    "state": "available", "protocol_versions": [3], "allowed": allowed})
                self.assertFalse(result["ok"])
                self.assertEqual("invalid_response", result["errorCode"])


class SiloOnboardingWiringTests(unittest.TestCase):


    def test_source_identity_preserves_case_sensitive_server_path(self):
        source = (ROOT / "components/ApiTask.brs").read_text()
        setup = source.split("function TaskSetSiloServer(", 1)[1].split("end function", 1)[0]
        self.assertIn('sourceId: "silo:" + normalized.url', setup)


if __name__ == "__main__":
    unittest.main()
