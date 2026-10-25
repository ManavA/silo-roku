"""Library modes run through real selection, requests, results and Back.

The host substitutes native ContentNode creation and focus nodes. It does not
establish physical D-pad behavior or live provider sort support.
"""

import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

from tools.brightscript import run_function


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/LibraryBrowsePolicy.brs"
MODES = ["title", "added", "released", "rated", "viewed"]
TITLES = ["All titles", "Recently Added", "Recently Released", "Top Rated", "Last Viewed"]
PLEX_SORTS = ["titleSort:asc", "addedAt:desc", "originallyAvailableAt:desc", "audienceRating:desc", "lastViewedAt:desc"]
SILO_SORTS = ["title", "added_at", "release_date", "rating_imdb", "last_watched"]


class LibraryBrowseTests(unittest.TestCase):
    def policy(self, name, *arguments):
        self.assertTrue(POLICY.exists(), "Library browse modes are not implemented")
        return run_function(POLICY, name, list(arguments))


    def test_both_providers_offer_the_five_unique_focusable_modes(self):
        for provider in ("plex", "silo"):
            entries = self.policy("LibraryBrowseModes", provider)
            self.assertEqual(TITLES, [entry["title"] for entry in entries])
            self.assertEqual(MODES, [entry["libraryMode"] for entry in entries])
            self.assertEqual(5, len({entry["uiAction"] for entry in entries}))
        self.assertEqual([], self.policy("LibraryBrowseModes", "unknown"))

    def test_mode_requests_reach_actual_provider_builders_with_header_auth(self):
        for provider in ("plex", "silo"):
            session = {"baseUrl": "https://provider.example.test", "clientId": "fixture-client",
                       "token": "fixture-only-token", "accessToken": "fixture-only-token", "profileId": "owner"}
            adapter = ROOT / ("source/adapters/" + provider.title() + "Adapter.brs")
            for index, mode in enumerate(MODES):
                with self.subTest(provider=provider, mode=mode):
                    planned = self.policy("LibraryBrowseRequest", provider, "2", mode, "page-2", 48)
                    self.assertTrue(planned["ok"])
                    request = run_function(adapter, "Build" + provider.title() + "Request",
                                           [planned["action"], session, planned["params"]])
                    self.assertTrue(request["ok"])
                    if provider == "plex":
                        query = parse_qs(urlsplit(request["url"]).query)
                        self.assertEqual([PLEX_SORTS[index]], query["sort"])
                        self.assertEqual(["48"], query["X-Plex-Container-Start"])
                        self.assertEqual(["48"], query["X-Plex-Container-Size"])
                    else:
                        body = json.loads(request["body"])
                        self.assertEqual(SILO_SORTS[index], body["sort"])
                        self.assertEqual("asc" if mode == "title" else "desc", body["order"])
                        self.assertEqual("page-2", body["cursor"])
                        self.assertEqual(100, body["limit"])
                    self.assertNotIn("fixture-only-token", request["url"])

    def test_unknown_mode_or_provider_never_builds_a_catalog_request(self):
        for provider, mode in (("plex", "unknown"), ("silo", "addedAt:desc"), ("unknown", "title"), ("plex", None), ("silo", {})):
            self.assertFalse(self.policy("LibraryBrowseRequest", provider, "2", mode, "", 0)["ok"])
        self.assertFalse(self.policy("LibraryBrowseRequest", "plex", "", "title", "", 0)["ok"])

    def test_fresh_mode_omits_stale_silo_cursor_and_starts_at_zero_for_plex(self):
        for provider in ("plex", "silo"):
            planned = self.policy("LibraryBrowseRequest", provider, "2", "released", "", 0)
            self.assertTrue(planned["ok"])
            if provider == "plex":
                self.assertEqual(0, planned["params"]["offset"])
            else:
                self.assertNotIn("cursor", planned["params"])


if __name__ == "__main__":
    unittest.main()
