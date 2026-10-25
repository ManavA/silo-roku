"""Plex Discover Watchlist contract, executed by the actual BrightScript adapter."""

import json
import os
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

from tools.brightscript import interpreter_available, run_function

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "source/adapters/PlexWatchlist.brs"
FIXTURES = ROOT / "tests/fixtures/plex_watchlist"


class PlexWatchlistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not interpreter_available():
            if os.environ.get("SILO_REQUIRE_BRS") == "1":
                raise RuntimeError("BrightScript interpreter is required")
            raise unittest.SkipTest("Install tools/brightscript runtime dependencies")

    def call(self, name, *arguments):
        self.assertTrue(ADAPTER.exists(), "Plex Discover Watchlist adapter is missing")
        return run_function(ADAPTER, name, list(arguments))

    def session(self, **changes):
        session = {"accountToken": "fixture-account-secret", "token": "fixture-server-secret",
                   "accountId": "account-fixture", "clientId": "roku-fixture",
                   "baseUrl": "https://server.example.test", "sourceId": "plex:server-fixture"}
        session.update(changes)
        return session

    def request(self, action, params=None, **changes):
        return self.call("BuildPlexWatchlistRequest", action, self.session(**changes), params or {})

    def decode(self, body=None, **params):
        if body is None:
            body = (FIXTURES / "watchlist.json").read_text()
        return self.call("DecodePlexWatchlistResponse", "watchlist", body,
                         {"accountId": "account-fixture", "offset": 0, "limit": 48, **params})

    def test_list_is_an_account_service_with_header_auth_and_bounded_pages(self):
        request = self.request("watchlist", {"offset": -1, "limit": 999})
        self.assertTrue(request["ok"])
        self.assertEqual(request["method"], "GET")
        self.assertEqual(urlsplit(request["url"]).netloc, "discover.provider.plex.tv")
        self.assertEqual(urlsplit(request["url"]).path, "/library/sections/watchlist/all")
        self.assertEqual(parse_qs(urlsplit(request["url"]).query)["sort"], ["watchlistedAt:desc"])
        self.assertEqual(request["headers"]["X-Plex-Token"], "fixture-account-secret")
        self.assertEqual(request["headers"]["X-Plex-Container-Start"], "0")
        self.assertEqual(request["headers"]["X-Plex-Container-Size"], "100")
        self.assertEqual(request["headers"]["X-Plex-Platform"], "Roku")
        self.assertNotIn("fixture-server-secret", json.dumps(request))
        self.assertNotIn("fixture-account-secret", request["url"])

    def test_server_auth_cannot_replace_missing_account_auth(self):
        request = self.request("watchlist", accountToken="")
        self.assertFalse(request["ok"])
        self.assertEqual(request["errorCode"], "auth_required")
        self.assertNotIn("fixture-server-secret", json.dumps(request))

    def test_registry_lowercased_session_keys_still_authorize_discover(self):
        session = {"accounttoken": "fixture-account-secret", "clientid": "roku-fixture"}
        request = self.call("BuildPlexWatchlistRequest", "watchlist", session, {"limit": 10})
        self.assertTrue(request["ok"])
        self.assertEqual(request["headers"]["X-Plex-Token"], "fixture-account-secret")
        self.assertEqual(request["headers"]["X-Plex-Client-Identifier"], "roku-fixture")
        mutation = self.call("BuildPlexWatchlistRequest", "watchlist_add", session,
                             {"watchlistratingkey": "global-movie-a"})
        self.assertTrue(mutation["ok"])
        self.assertEqual(parse_qs(urlsplit(mutation["url"]).query),
                         {"ratingKey": ["global-movie-a"]})

    def test_restored_account_token_without_account_id_needs_lookup(self):
        self.assertTrue(self.call("PlexWatchlistNeedsAccountLookup",
                                  {"accounttoken": "fixture-account-secret"}))
        self.assertFalse(self.call("PlexWatchlistNeedsAccountLookup",
                                   {"accounttoken": "fixture-account-secret", "accountid": "123"}))
        self.assertFalse(self.call("PlexWatchlistNeedsAccountLookup", {"accountid": "123"}))

    def test_mutations_use_discover_ids_in_put_requests(self):
        for action, endpoint in (("watchlist_add", "addToWatchlist"),
                                 ("watchlist_remove", "removeFromWatchlist")):
            with self.subTest(action=action):
                request = self.request(action, {"plexGuid": "plex://movie/global-movie-a"})
                self.assertTrue(request["ok"])
                self.assertEqual(request["method"], "PUT")
                self.assertEqual(urlsplit(request["url"]).path, "/actions/" + endpoint)
                self.assertEqual(parse_qs(urlsplit(request["url"]).query),
                                 {"ratingKey": ["global-movie-a"]})
                self.assertEqual(request["headers"]["X-Plex-Token"], "fixture-account-secret")
        explicit = self.request("watchlist_add", {"watchlistRatingKey": "global-show-b"})
        self.assertTrue(explicit["ok"])

    def test_mutations_do_not_guess_a_global_id_from_server_item_id(self):
        for params in ({"itemId": "101"}, {"plexGuid": "tmdb://123"},
                       {"watchlistRatingKey": "global-a&X-Plex-Token=unsafe"},
                       {"plexGuid": "plex://movie/global-a?token=unsafe"}):
            with self.subTest(params=params):
                self.assertFalse(self.request("watchlist_add", params)["ok"])
        self.assertFalse(self.request("unknown")["ok"])

    def test_watchlist_seeds_preserve_external_identity_without_playback_routes(self):
        result = self.decode()
        self.assertTrue(result["ok"])
        items = result["data"]["items"]
        self.assertEqual(len(items), 2)
        movie = items[0]
        self.assertEqual(movie["sourceId"], "plex-watchlist:account-fixture")
        self.assertEqual(movie["itemId"], "plex-watchlist:movie:global-movie-a")
        self.assertEqual(movie["watchlistRatingKey"], "global-movie-a")
        self.assertEqual(movie["plexGuid"], "plex://movie/global-movie-a")
        self.assertEqual(movie["guids"], ["plex://movie/global-movie-a", "tmdb://123", "imdb://tt1234567"])
        self.assertEqual(movie["externalIds"], {"tmdb": "123", "imdb": "tt1234567"})
        self.assertEqual(items[1]["itemId"], "plex-watchlist:show:global-show-b")
        for item in items:
            self.assertFalse(item["owned"])
            self.assertFalse(item["canPlay"])
            self.assertTrue(item["inWatchlist"])
            self.assertEqual(item["availability"], "unresolved")
            self.assertNotIn("url", item)
            self.assertNotIn("Media", item)
        self.assertNotIn("unsafe-secret", json.dumps(result))

    def test_paging_counts_source_entries_before_filtering_or_deduplicating(self):
        result = self.decode(offset=48, limit=48)["data"]
        self.assertEqual(result["sourceCount"], 4)
        self.assertEqual(result["offset"], 48)
        self.assertEqual(result["nextOffset"], 52)
        self.assertEqual(result["totalSize"], 100)
        self.assertTrue(result["hasMore"])
        empty = self.decode(body='{"MediaContainer":{"totalSize":100,"Metadata":[]}}', offset=52)
        self.assertFalse(empty["data"]["hasMore"])

    def test_malformed_pages_and_missing_account_scope_are_explicit(self):
        for body in ("bad-json", "[]", "{}", '{"MediaContainer":{"Metadata":"bad"}}'):
            with self.subTest(body=body):
                self.assertFalse(self.decode(body=body)["ok"])
        self.assertFalse(self.decode(accountId="")["ok"])

    def test_decode_bounds_the_page_even_when_the_provider_ignores_page_size(self):
        raw = {"ratingKey": "global-a", "guid": "plex://movie/global-a", "type": "movie", "title": "Fixture"}
        items = [{**raw, "ratingKey": str(i), "guid": "plex://movie/id-" + str(i)} for i in range(120)]
        result = self.decode(body=json.dumps({"MediaContainer": {"totalSize": 120, "Metadata": items}}), limit=100)
        self.assertEqual(len(result["data"]["items"]), 100)
        self.assertEqual(result["data"]["nextOffset"], 100)

    def test_successful_mutation_can_have_no_json_body(self):
        for action, state in (("watchlist_add", True), ("watchlist_remove", False)):
            result = self.call("DecodePlexWatchlistResponse", action, "", {})
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["inWatchlist"], state)


if __name__ == "__main__":
    unittest.main()
