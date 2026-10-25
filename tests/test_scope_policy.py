"""The scene must never paint a response from an old source or profile."""

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from brightscript import interpreter_available, run_function

POLICY = ROOT / "source" / "core" / "ScopePolicy.brs"
URL_POLICY = ROOT / "source" / "core" / "ServerUrlPolicy.brs"


class _BrightScriptCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not interpreter_available():
            if os.environ.get("SILO_REQUIRE_BRS") == "1":
                raise AssertionError("BrightScript interpreter required by SILO_REQUIRE_BRS")
            raise unittest.SkipTest("install test interpreter with npm ci --prefix tools/brightscript --ignore-scripts")


class ScopePolicyTests(_BrightScriptCase):
    def test_current_source_profile_and_generation_can_paint(self):
        active = {"sourceId": "plex:server-a", "profileId": "owner", "generation": 8}
        self.assertTrue(run_function(POLICY, "ScopeMatches", [active, dict(active)]))

    def test_previous_generation_cannot_paint_after_navigation(self):
        active = {"sourceId": "plex:server-a", "profileId": "owner", "generation": 9}
        old = {"sourceId": "plex:server-a", "profileId": "owner", "generation": 8}
        self.assertFalse(run_function(POLICY, "ScopeMatches", [active, old]))

    def test_previous_source_or_profile_cannot_paint(self):
        active = {"sourceId": "silo:server-b", "profileId": "child", "generation": 9}
        for stale in (
            {"sourceId": "plex:server-a", "profileId": "child", "generation": 9},
            {"sourceId": "silo:server-b", "profileId": "owner", "generation": 9},
            {"sourceId": "silo:server-b", "generation": 9},
        ):
            with self.subTest(stale=stale):
                self.assertFalse(run_function(POLICY, "ScopeMatches", [active, stale]))


class ServerUrlPolicyTests(_BrightScriptCase):
    def test_secure_and_private_server_addresses_are_normalized(self):
        examples = {
            "https://media.example.com/": "https://media.example.com",
            "http://192.168.4.60:8090/": "http://192.168.4.60:8090",
            "http://nas.local:8090/silo/": "http://nas.local:8090/silo",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(run_function(URL_POLICY, "NormalizeServerUrl", [raw]), {"ok": True, "url": expected})

    def test_cleartext_remote_and_embedded_credentials_are_rejected(self):
        for raw in (
            "http://media.example.com",
            "http://10.evil.example.com",
            "http://172.16.evil.com",
            "http://192.168.bad.example",
            "https://user:password@media.example.com",
            "https://media.example.com/?token=secret",
            "https://media.example.com:abc",
            "https://media.example.com:70000",
            "https://media.example.com\r\nX-Header:secret",
            "http://nas..local:8090",
            "file:///tmp/media",
            "https://",
        ):
            with self.subTest(raw=raw):
                result = run_function(URL_POLICY, "NormalizeServerUrl", [raw])
                self.assertFalse(result["ok"])
                self.assertNotIn(raw, str(result))

    def test_scheme_and_host_case_normalize_without_changing_server_path(self):
        result = run_function(URL_POLICY, "NormalizeServerUrl", [" HTTPS://SILO.EXAMPLE:8443/Silo/ "])
        self.assertEqual({"ok": True, "url": "https://silo.example:8443/Silo"}, result)

    def test_malformed_host_labels_and_ipv6_are_rejected_during_setup(self):
        for raw in ("https://-silo.example", "https://silo-.example", "https://[bad]",
                    "https://[::gg]", "https://[1:2:3]", "https://[1::2::3]"):
            with self.subTest(raw=raw):
                self.assertEqual({"ok": False, "errorCode": "invalid_server_url"},
                                 run_function(URL_POLICY, "NormalizeServerUrl", [raw]))

    def test_valid_ipv6_hosts_remain_usable(self):
        for raw in ("https://[2001:db8::1]", "https://[1:2:3:4:5:6:7:8]:8443", "http://[::1]:8090"):
            with self.subTest(raw=raw):
                self.assertEqual({"ok": True, "url": raw},
                                 run_function(URL_POLICY, "NormalizeServerUrl", [raw]))


if __name__ == "__main__":
    unittest.main()
