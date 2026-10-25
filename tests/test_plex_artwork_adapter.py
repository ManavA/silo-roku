"""Artwork identity uses the exact lightweight Plex metadata route."""
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]


class PlexArtworkAdapterTests(unittest.TestCase):
    def request(self, item_id):
        with tempfile.TemporaryDirectory(prefix="silo-plex-artwork-route-") as directory:
            return run_function(ROOT / "source/adapters/PlexAdapter.brs", "BuildPlexRequest",
                ["artwork_detail", {"clientId":"synthetic-device", "baseUrl":"https://plex.example.test",
                 "sourceId":"plex:fixture", "token":"synthetic-server-token", "accountToken":"synthetic-account-token"},
                 {"itemId":item_id, "thumbKey":"/private/image", "url":"https://other.example.test"}], root=Path(directory))

    def test_exact_metadata_guid_read_has_no_playback_or_extras_request(self):
        request = self.request("501")
        self.assertTrue(request["ok"])
        self.assertEqual("GET", request["method"])
        self.assertEqual("https://plex.example.test/library/metadata/501?includeGuids=1", request["url"])
        self.assertEqual("", request["body"])
        self.assertEqual(98304, request["responseBodyLimit"])
        self.assertEqual(4000, request["timeoutMs"])
        self.assertEqual("synthetic-server-token", request["headers"]["X-Plex-Token"])
        self.assertNotIn("synthetic", request["url"])

    def test_invalid_native_ids_never_make_a_request(self):
        for identifier in ("", ".", "..", "abc", "1/2", "1?token=x", "1%2F2", "9"*21):
            with self.subTest(identifier=identifier):
                request=self.request(identifier)
                self.assertFalse(request["ok"])
                self.assertEqual("invalid_request",request["errorCode"])
