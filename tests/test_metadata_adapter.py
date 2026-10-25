"""Synthetic fixtures execute the actual public Metadata BrightScript contract."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from tools.brightscript import interpreter_available, run_function

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "source/adapters/MetadataAdapter.brs"
FIXTURES = ROOT / "tests/fixtures/metadata"
CONFIG = {"baseUrl": "https://metadata.example", "appVersion": "0.1.0"}
OWNED = {"sourceId": "plex:server-one", "itemId": "501", "type": "movie",
         "title": "Synthetic Moon", "year": 2026, "guids": ["tmdb://101", "imdb://tt0000101"]}


class MetadataAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not interpreter_available():
            message = "install runtime tests: npm ci --prefix tools/brightscript --ignore-scripts"
            if os.environ.get("SILO_REQUIRE_BRS") == "1":
                raise RuntimeError(message)
            raise unittest.SkipTest(message)
        cls.package_root = tempfile.TemporaryDirectory(prefix="metadata-policy-root-")

    @classmethod
    def tearDownClass(cls):
        cls.package_root.cleanup()

    def call(self, function, *args):
        self.assertTrue(ADAPTER.is_file(), "Metadata adapter implementation is missing")
        return run_function(ADAPTER, function, list(args), root=Path(self.package_root.name))

    def request(self, action, params=None, config=None):
        return self.call("BuildMetadataRequest", action, CONFIG if config is None else config, params or {})

    def decode(self, action, fixture, params=None):
        return self.call("DecodeMetadataResponse", action, (FIXTURES / fixture).read_text(), params or {})

    def test_unconfigured_metadata_is_disabled_without_a_request(self):
        for action in ("home_rows", "service_catalog", "discover_trending", "metadata_artwork", "ava_recommend"):
            result = self.request(action, config={})
            self.assertFalse(result["ok"])
            self.assertEqual("metadata_disabled", result["errorCode"])
            self.assertNotIn("url", result)

    def test_catalog_request_uses_verified_home_path_and_cache_mode(self):
        result = self.request("home_rows", {"mode": "cache_only"})
        self.assertTrue(result["ok"])
        self.assertEqual("GET", result["method"])
        self.assertEqual("/v1/catalog/home/rows", urlsplit(result["url"]).path)
        self.assertEqual({"cacheOnly": ["1"], "v": ["20260814-showcase-v7"], "format": ["compact"]}, parse_qs(urlsplit(result["url"]).query))
        self.assertEqual(10000, result["timeoutMs"])

    def test_compact_home_expands_ordered_indices_as_bounded_unresolved_cards(self):
        body = {"format": "compact-v1", "fetchedAtEpochMs": 100,
                "items": [{"tmdbId": "101", "type": "movie", "title": "Synthetic Moon"},
                          {"tmdbId": "202", "type": "tv", "title": "Synthetic Stars"}],
                "rows": [{"id": "picks", "title": "Picks", "i": [1, -1, 0.5, "0", 99, 0, 1]}]}
        result = self.call("DecodeMetadataResponse", "home_rows", json.dumps(body), {})
        self.assertTrue(result["ok"])
        self.assertEqual(["202", "101"], [x["tmdbId"] for x in result["data"]["rows"][0]["items"]])
        self.assertTrue(all(not x["canPlay"] for x in result["data"]["rows"][0]["items"]))
        self.assertEqual(100, result["data"]["fetchedAtEpochMs"])

    def test_catalog_refresh_has_explicit_bounded_timeout(self):
        result = self.request("home_rows", {"mode": "refresh"})
        self.assertEqual(["1"], parse_qs(urlsplit(result["url"]).query)["refresh"])
        self.assertEqual(12000, result["timeoutMs"])
        self.assertNotIn("cacheOnly", self.request("home_rows", {"mode": "live"})["url"])

    def test_trending_uses_the_verified_paged_route_without_provider_auth(self):
        result = self.request("discover_trending", {"page": 2}, {**CONFIG, "token": "synthetic-private"})
        self.assertTrue(result["ok"])
        self.assertEqual("/v1/trending/all/week", urlsplit(result["url"]).path)
        self.assertEqual({"page": ["2"]}, parse_qs(urlsplit(result["url"]).query))
        self.assertEqual(10000, result["timeoutMs"])
        self.assertNotIn("synthetic-private", json.dumps(result))

    def test_trending_page_is_bounded_before_integer_conversion(self):
        for value, expected in ((None, 1), (0, 1), (-2, 1), (500, 20), (1e40, 20), (2.9, 2), ("2", 1)):
            params = {} if value is None else {"page": value}
            result = self.request("discover_trending", params)
            self.assertTrue(result["ok"])
            self.assertEqual([str(expected)], parse_qs(urlsplit(result["url"]).query)["page"])

    def test_trending_decodes_tmdb_results_as_unresolved_rows_with_next_page(self):
        result = self.decode("discover_trending", "trending.json")
        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual((1, 2), (data["page"], data["nextPage"]))
        self.assertEqual("trending-week", data["rows"][0]["id"])
        items = data["rows"][0]["items"]
        self.assertEqual(["metadata:movie:101", "metadata:show:202"], [item["catalogId"] for item in items])
        self.assertEqual("Synthetic Stars", items[1]["title"])
        self.assertEqual(2025, items[1]["year"])
        self.assertEqual("https://image.tmdb.org/t/p/w342/synthetic-moon.jpg", items[0]["thumbKey"])
        for item in items:
            self.assertFalse(item["canPlay"])
            self.assertFalse(item["owned"])
            self.assertNotIn("itemId", item)
            self.assertNotIn("sourceId", item)
        self.assertNotIn("must-be-omitted", json.dumps(result))

    def test_trending_limits_seed_count_and_page_navigation(self):
        body = {"page": 19, "total_pages": 1000, "results": [
            {"id": index + 1, "media_type": "movie", "title": f"Synthetic {index}"} for index in range(100)]}
        result = self.call("DecodeMetadataResponse", "discover_trending", json.dumps(body), {})
        self.assertTrue(result["ok"])
        self.assertEqual(20, len(result["data"]["rows"][0]["items"]))
        self.assertEqual(20, result["data"]["nextPage"])
        for page, total in ((20, 1000), (2, 2), (1, 0)):
            body.update(page=page, total_pages=total)
            result = self.call("DecodeMetadataResponse", "discover_trending", json.dumps(body), {})
            self.assertEqual(0, result["data"]["nextPage"])

    def test_trending_rejects_invalid_shapes_and_never_infers_media_type(self):
        for body in ({}, {"results": None}, {"results": {}}, {"results": [], "page": 21}, {"results": [], "page": "1"}):
            result = self.call("DecodeMetadataResponse", "discover_trending", json.dumps(body), {})
            self.assertEqual("invalid_response", result["errorCode"])
        body = {"page": 1, "total_pages": 1, "results": [
            {"id": "101", "media_type": "movie", "title": "Wrong ID type"},
            {"id": 0, "media_type": "movie", "title": "Zero ID"},
            {"id": 1.5, "media_type": "movie", "title": "Noninteger ID"},
            {"id": 101, "title": "Missing type"},
            {"id": 101, "media_type": "person", "name": "Person"}]}
        result = self.call("DecodeMetadataResponse", "discover_trending", json.dumps(body), {})
        self.assertTrue(result["ok"])
        self.assertEqual([], result["data"]["rows"][0]["items"])
        self.assertEqual(0, result["data"]["nextPage"])

    def test_trending_still_refuses_response_bodies_over_two_mib_before_json_parse(self):
        result = self.call("DecodeMetadataResponse", "discover_trending", " " * 2097153, {})
        self.assertEqual("response_too_large", result["errorCode"])

    def test_service_catalog_slug_cannot_add_routes_or_query_fields(self):
        self.assertEqual("/v1/catalog/service/synthetic-service", urlsplit(self.request("service_catalog", {"slug": "synthetic-service"})["url"]).path)
        for slug in ("", "../private", "service?token=x", "a/library", "a#fragment"):
            self.assertEqual("invalid_request", self.request("service_catalog", {"slug": slug})["errorCode"])

    def test_public_requests_never_send_provider_tokens_or_private_headers(self):
        config = {**CONFIG, "token": "synthetic-private", "accessToken": "synthetic-private", "profileToken": "synthetic-private",
                  "headers": {"Authorization": "Bearer synthetic-private", "X-Plex-Token": "synthetic-private"}}
        for action, params in (("home_rows", {}), ("ava_recommend", {"prompt": "Moon films", "sourceId": OWNED["sourceId"]})):
            result = self.request(action, params, config)
            self.assertEqual("roku/0.1.0", result["headers"]["X-Silo-Client"])
            self.assertNotIn("Authorization", result["headers"])
            self.assertNotIn("X-Plex-Token", result["headers"])
            self.assertNotIn("synthetic-private", json.dumps(result))

    def test_base_url_rejects_auth_query_fragment_cleartext_and_invalid_host(self):
        for base in ("https://user:pass@metadata.example", "https://metadata.example?token=x", "https://metadata.example#x",
                     "http://metadata.example", "https://metadata.example\\evil", "https://metadata.example\r\nX: bad", "https://metadata.example:99999"):
            with self.subTest(base=base):
                self.assertEqual("invalid_server", self.request("home_rows", config={"baseUrl": base})["errorCode"])

    def test_configured_ava_stays_on_exact_user_origin_and_path(self):
        result = self.request("ava_recommend", {"prompt": "Moon films", "sourceId": OWNED["sourceId"]}, {"baseUrl":"https://custom.example:8443/metadata/"})
        self.assertEqual("https://custom.example:8443/metadata/v1/ava/recommendations", result["url"])
        self.assertEqual(30000, result["timeoutMs"])

    def test_ava_body_whitelists_only_active_source_owned_candidates(self):
        candidate = {**OWNED, "token": "synthetic-private", "baseUrl": "https://private.example", "versions": [{"url": "private"}]}
        params = {"sourceId": OWNED["sourceId"], "prompt": " Moon films ", "libraryCandidates": [candidate, {**candidate, "sourceId": "plex:other"}], "limit": 8}
        result = self.request("ava_recommend", params)
        self.assertEqual("POST", result["method"])
        body = json.loads(result["body"])
        self.assertEqual("Moon films", body["prompt"])
        self.assertEqual([{"title": "Synthetic Moon", "mediaType": "movie", "tmdbId": "101", "imdbId": "tt0000101", "year": 2026, "genres": []}], body["libraryCandidates"])
        self.assertNotIn("private", result["body"])
        self.assertNotIn("sourceId", result["body"])
        self.assertNotIn("itemId", result["body"])
        self.assertNotIn("Moon", result["url"])

    def test_ava_caps_hints_candidates_genres_and_limit(self):
        candidates = [{**OWNED, "itemId": str(index), "guids": [f"tmdb://{index+1}"], "genres": [f"Genre {n}" for n in range(20)]} for index in range(220)]
        result = self.request("ava_recommend", {"sourceId": OWNED["sourceId"], "prompt": "Moon", "libraryHints": [f"Title {n}" for n in range(60)], "libraryCandidates": candidates, "limit": 500})
        body = json.loads(result["body"])
        self.assertEqual(40, len(body["libraryHints"]))
        self.assertEqual(180, len(body["libraryCandidates"]))
        self.assertEqual(8, len(body["libraryCandidates"][0]["genres"]))
        self.assertEqual(30, body["limit"])

    def test_ava_rejects_blank_overlong_prompt_missing_source_and_invalid_media_kind(self):
        for params in ({"prompt": " "}, {"prompt": "x" * 1001, "sourceId": OWNED["sourceId"]}, {"prompt": "Moon"}):
            self.assertEqual("invalid_request", self.request("ava_recommend", params)["errorCode"])
        result = self.request("ava_recommend", {"sourceId": OWNED["sourceId"], "prompt": "Moon", "libraryCandidates": [{**OWNED, "type": "episode"}]})
        self.assertEqual([], json.loads(result["body"])["libraryCandidates"])

    def test_ava_candidate_normalization_removes_duplicate_ids_and_invalid_values(self):
        candidate = {**OWNED, "rating": 11, "genres": ["Drama", "Drama", "", "Moon\nDrama"]}
        result = self.request("ava_recommend", {"sourceId": OWNED["sourceId"], "prompt": "Moon", "libraryCandidates": [candidate, candidate, {**candidate, "type": "show"}]})
        body = json.loads(result["body"])
        self.assertEqual(2, len(body["libraryCandidates"]))
        self.assertEqual("show", body["libraryCandidates"][1]["mediaType"])
        self.assertNotIn("rating", body["libraryCandidates"][0])
        self.assertEqual(["Drama", "Moon Drama"], body["libraryCandidates"][0]["genres"])

    def test_curated_rows_decode_candidates_without_provider_playback_ids(self):
        result = self.decode("home_rows", "home_rows.json")
        self.assertTrue(result["ok"])
        row = result["data"]["rows"][0]
        self.assertEqual("synthetic-picks", row["id"])
        item = row["items"][0]
        self.assertEqual("metadata:movie:101", item["catalogId"])
        self.assertEqual("101", item["tmdbId"])
        self.assertEqual("movie", item["type"])
        self.assertEqual("https://image.tmdb.org/t/p/w342/synthetic-moon.jpg", item["thumbKey"])
        self.assertFalse(item["canPlay"])
        self.assertFalse(item["owned"])
        self.assertNotIn("itemId", item)
        self.assertNotIn("token", json.dumps(result["data"]))

    def test_catalog_preserves_show_alias_and_trims_bounded_rows(self):
        body = json.loads((FIXTURES / "home_rows.json").read_text())
        body["rows"][0]["items"] *= 40
        body["rows"] *= 20
        result = self.call("DecodeMetadataResponse", "home_rows", json.dumps(body), {})
        self.assertEqual(12, len(result["data"]["rows"]))
        self.assertLessEqual(len(result["data"]["rows"][0]["items"]), 24)
        self.assertEqual("show", result["data"]["rows"][0]["items"][1]["type"])

    def test_unsafe_artwork_and_unknown_media_types_never_become_media_cards(self):
        body = json.loads((FIXTURES / "home_rows.json").read_text())
        body["rows"][0]["items"][0]["posterPath"] = "https://private.example/art?token=synthetic-private"
        body["rows"][0]["items"].append({"tmdbId": "222", "type": "person", "title": "Unknown"})
        result = self.call("DecodeMetadataResponse", "home_rows", json.dumps(body), {})
        self.assertEqual("", result["data"]["rows"][0]["items"][0]["thumbKey"])
        self.assertEqual(2, len(result["data"]["rows"][0]["items"]))
        self.assertNotIn("synthetic-private", json.dumps(result))

    def test_ava_response_is_bounded_and_does_not_infer_missing_or_unknown_types(self):
        result = self.decode("ava_recommend", "ava.json")
        self.assertTrue(result["ok"])
        self.assertEqual(["101", "202"], [item["tmdbId"] for item in result["data"]["items"]])
        self.assertEqual("show", result["data"]["items"][1]["type"])
        self.assertEqual("A few synthetic choices.", result["data"]["reply"])
        self.assertNotIn("itemId", result["data"]["items"][0])
        body = {"reply": "x" * 500, "matches": [{"title": f"Title {i}", "mediaType": "movie", "tmdbId": str(i+1)} for i in range(100)]}
        result = self.call("DecodeMetadataResponse", "ava_recommend", json.dumps(body), {"limit": 5})
        self.assertEqual(5, len(result["data"]["items"]))
        self.assertEqual(180, len(result["data"]["reply"]))

    def test_malformed_shapes_fail_without_echoing_error_text(self):
        for action, bodies in (("home_rows", ["{", "[]", "null", "{}", '{"rows":null}']), ("ava_recommend", ["{}", '{"matches":null}', '{"error":"synthetic-private"}'])):
            for body in bodies:
                result = self.call("DecodeMetadataResponse", action, body, {})
                self.assertEqual("invalid_response", result["errorCode"])
                self.assertNotIn("synthetic-private", json.dumps(result))
        self.assertEqual("unsupported_action", self.request("never_called")["errorCode"])

    def test_exact_match_uses_active_source_and_owned_id_without_title_guessing(self):
        seed = self.decode("ava_recommend", "ava.json")["data"]["items"][0]
        candidates = [{**OWNED, "sourceId": "plex:other"}, {**OWNED, "guids": ["tmdb://999"]}, OWNED]
        result = self.call("MatchMetadataOwnedItem", seed, candidates, OWNED["sourceId"])
        self.assertEqual("501", result["itemId"])
        self.assertEqual(OWNED["sourceId"], result["sourceId"])
        self.assertTrue(result["owned"])
        self.assertEqual(None, self.call("MatchMetadataOwnedItem", seed, candidates[:2], OWNED["sourceId"]))

    def test_exact_match_rejects_wrong_kind_explicit_unowned_and_conflicting_ids(self):
        seed = self.decode("ava_recommend", "ava.json")["data"]["items"][0]
        for candidate in ({**OWNED, "type": "show"}, {**OWNED, "owned": False}, {**OWNED, "guids": ["tmdb://101", "imdb://tt0000999"]}):
            self.assertIsNone(self.call("MatchMetadataOwnedItem", seed, [candidate], OWNED["sourceId"]))
        self.assertIsNone(self.call("MatchMetadataOwnedItem", {**seed, "tmdbId": "", "imdbId": ""}, [OWNED], OWNED["sourceId"]))

    def test_exact_match_accepts_normalized_silo_external_ids_and_drops_unknown_private_fields(self):
        seed = self.decode("ava_recommend", "ava.json")["data"]["items"][0]
        owned = {**OWNED, "sourceId": "silo:synthetic-source", "tmdbId": "101", "imdbId": "tt0000101", "guids": [], "accessToken": "synthetic-private", "versions": [{"url": "private"}]}
        result = self.call("MatchMetadataOwnedItem", seed, [owned], owned["sourceId"])
        self.assertEqual(owned["sourceId"], result["sourceId"])
        self.assertNotIn("private", json.dumps(result))
