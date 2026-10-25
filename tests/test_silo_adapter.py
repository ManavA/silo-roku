"""Execute Silo's pure BrightScript adapter against sanitized v2/v3 fixtures."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from tools.brightscript import interpreter_available, run_function

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "source/adapters/SiloAdapter.brs"
FIXTURES = ROOT / "tests/fixtures/silo"
SESSION = {
    "baseUrl": "https://silo.example", "accessToken": "synthetic-access",
    "refreshToken": "synthetic-refresh", "profileId": "p1",
    "profileToken": "synthetic-profile", "deviceId": "roku-installation",
    "appVersion": "0.1.0", "model": "test-model", "osVersion": "test-os",
}


class SiloAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not interpreter_available():
            message = "install runtime tests: npm ci --prefix tools/brightscript --ignore-scripts"
            if os.environ.get("SILO_REQUIRE_BRS") == "1":
                raise RuntimeError(message)
            raise unittest.SkipTest(message)
        # Pure adapter tests don't load SceneGraph components or transport Tasks.
        cls.package_root = tempfile.TemporaryDirectory(prefix="silo-policy-root-")

    @classmethod
    def tearDownClass(cls):
        cls.package_root.cleanup()

    def call(self, function, *arguments):
        self.assertTrue(ADAPTER.is_file(), "Silo adapter implementation is missing")
        return run_function(ADAPTER, function, list(arguments), root=Path(self.package_root.name))

    def request(self, action, params=None, session=None):
        return self.call("BuildSiloRequest", action, session or SESSION, params or {})

    def decode(self, action, fixture, **params):
        return self.call("DecodeSiloResponse", action, (FIXTURES / fixture).read_text(), params)

    def test_collection_create_is_private_and_requires_created_owned_receipt(self):
        request = self.request("collection_create", {"name":"  Weekend  "})
        self.assertEqual("POST", request["method"])
        self.assertEqual({"name":"Weekend","collection_type":"manual","is_shared":False}, json.loads(request["body"]))
        self.assertTrue(request["url"].endswith("/api/v2/collections"))
        receipt = {"id":"new", "name":"Weekend", "creator_profile_id":"p1", "collection_type":"manual", "is_shared":False}
        for status in (200, 201):
            result = self.call("DecodeSiloResponse", "collection_create", json.dumps(receipt), {"statusCode":status,"profileId":"p1"})
            self.assertEqual(status == 201, result["ok"])
        receipt["creator_profile_id"] = "other"
        self.assertFalse(self.call("DecodeSiloResponse", "collection_create", json.dumps(receipt), {"statusCode":201,"profileId":"p1"})["ok"])

    def test_detail_genres_are_bounded_clean_labels(self):
        raw = json.loads((FIXTURES / "catalog_item_detail_movie.json").read_text())
        self.assertEqual(["Action", "Sci-Fi"], self.call("SiloItem", raw)["item"]["genres"])
        raw["genres"] = [" Drama ", "drama", "", {}, "bad\nlabel", "x" * 101, "Comedy"]
        self.assertEqual(["Drama", "Comedy"], self.call("SiloItem", raw)["item"]["genres"])

    def test_catalog_decade_and_rating_combine_with_scope_and_existing_rules(self):
        request = self.request("catalog_query", {"type":"movie", "libraryId":"lib-1",
            "source":"user_collection", "collectionId":"collection-1", "cursor":"page-2",
            "genre":"Drama", "decade":1990, "minimumRating":7})
        body = json.loads(request["body"])
        self.assertEqual(body["library_id"], "lib-1")
        self.assertEqual(body["collection_id"], "collection-1")
        self.assertEqual(body["cursor"], "page-2")
        self.assertEqual(body["groups"], [{"match":"all", "rules":[
            {"field":"genre", "op":"contains", "value":"Drama"},
            {"field":"year", "op":"between", "value":[1990,1999]},
            {"field":"rating_imdb", "op":"gte", "value":7}]}])

    def test_episode_art_preserves_only_explicit_still_classification(self):
        for flag in (False, True, None, 'false'):
            raw={'content_id':'episode','title':'Episode','type':'episode',
                 'poster_url':'https://images.example/cover','poster_is_episode_still':flag}
            result=self.call('SiloItem',raw)['item']['art']
            if isinstance(flag,bool):
                self.assertIs(result['posterIsEpisodeStill'],flag)
            else:
                self.assertNotIn('posterIsEpisodeStill',result)

    def test_collection_membership_requests_and_owned_manual_choices(self):
        request = self.request("collection_choices", {"itemId":"movie/1"})
        self.assertEqual(parse_qs(urlsplit(request["url"]).query), {"contains_item":["movie/1"]})
        for action, method in [("collection_add","PUT"),("collection_remove","DELETE")]:
            request = self.request(action, {"itemId":"movie/1","collectionId":"list/1"})
            self.assertEqual(request["method"],method)
            self.assertEqual(request["headers"]["X-Profile-Id"],SESSION["profileId"])
            self.assertEqual(request["headers"]["X-Profile-Token"],SESSION["profileToken"])
            self.assertTrue(request["url"].endswith("/collections/list%2F1/items/movie%2F1"))
            if method == "PUT": self.assertEqual(json.loads(request["body"]), {"position":0})
            self.assertFalse(self.call("DecodeSiloResponse",action,"",{"statusCode":200})["ok"])
            self.assertTrue(self.call("DecodeSiloResponse",action,"",{"statusCode":204})["ok"])
        decoded = self.call("DecodeSiloResponse","collection_choices",json.dumps({"items":[
            {"id":"one","name":"My list","collection_type":"manual","creator_profile_id":"p1","contains":False},
            {"id":"two","name":"Shared","collection_type":"manual","creator_profile_id":"p2","contains":True}]}),{})
        self.assertEqual(decoded["data"]["entries"][0],dict(id="one",title="My list",collectionType="manual",creatorProfileId="p1",contains=False))

    def test_collection_editing_requires_available_contains_capability(self):
        self.assertTrue(self.request("collection_capabilities")["url"].endswith("/collections/capabilities"))
        for document, supported in [
            ({"state":"available","contains_item":True},True),
            ({"state":"available","allowed":False,"contains_item":True},False),
            ({"state":"disabled","contains_item":True},False),
            ({"state":"available"},False), ({},False)]:
            result=self.call("DecodeSiloResponse","collection_capabilities",json.dumps(document),{})
            self.assertEqual(result["data"]["supported"],supported)

    def test_collections_current_wire_shape_and_legacy_items(self):
        request = self.request("collections")
        self.assertTrue(request["url"].endswith("/api/v2/collections"))
        current = self.decode("collections", "collections_current.json")
        self.assertTrue(current["ok"])
        self.assertEqual(current["data"]["entries"], [
            {"id": "personal-1", "title": "Weekend films", "source": "user_collection"},
            {"id": "personal-2", "title": "Family favorites", "source": "user_collection"},
        ])
        legacy = self.call("DecodeSiloResponse", "collections", json.dumps({"items": [
            {"id": "older-1", "name": "Older server list"}]}), {})
        self.assertEqual(legacy["data"]["entries"][0]["id"], "older-1")
        self.assertFalse(self.call("DecodeSiloResponse", "collections", json.dumps({"wrong": []}), {})["ok"])
        bounded = self.call("DecodeSiloResponse", "collections", json.dumps({"collections":
            [{"id": "", "name": "Ignored"}] * 100 + [{"id": "too-late", "name": "Too late"}]}), {})
        self.assertEqual(bounded["data"]["entries"], [])

    def test_server_collections_preserve_library_scope_and_order(self):
        request = self.request("server_collections")
        self.assertTrue(request["url"].endswith("/api/v2/collections/server"))
        self.assertEqual(request["headers"]["X-Profile-Id"], "p1")
        current = self.decode("server_collections", "server_collections_current.json")
        self.assertTrue(current["ok"])
        self.assertEqual(current["data"]["entries"], [
            {"id": "admin-1", "title": "Movies • Award winners", "source": "library_collection", "libraryId": "12"},
            {"id": "admin-2", "title": "Movies • Family night", "source": "library_collection", "libraryId": "12"},
            {"id": "admin-3", "title": "Shows • Short seasons", "source": "library_collection", "libraryId": "21"},
        ])
        self.assertFalse(self.call("DecodeSiloResponse", "server_collections", json.dumps({"items": []}), {})["ok"])
        bounded = self.call("DecodeSiloResponse", "server_collections", json.dumps({"libraries": [{
            "library_id": 12, "library_name": "Movies", "collections":
            [{"id": "", "title": "Ignored"}] * 50 + [{"id": "too-late", "title": "Too late"}]}]}), {})
        self.assertEqual(bounded["data"]["entries"], [])

    def test_video_format_shortcuts_use_server_indexed_same_file_rules(self):
        expected = {
            "4k": [{"field": "resolution", "op": "is", "value": "2160p"}],
            "hdr": [{"field": "hdr", "op": "is", "value": True}],
            "4k_hdr": [{"field": "resolution", "op": "is", "value": "2160p"},
                       {"field": "hdr", "op": "is", "value": True}],
            "dv": [{"field": "dolby_vision", "op": "is", "value": True}],
        }
        for format_filter, rules in expected.items():
            with self.subTest(format_filter=format_filter):
                request = self.request("catalog_query", {"type": "video", "source": "query", "formatFilter": format_filter, "limit": 60})
                self.assertTrue(request["ok"])
                body = json.loads(request["body"])
                self.assertEqual(body["type"], "video")
                self.assertEqual(body["groups"], [{"match": "all", "rules": rules}])
        self.assertFalse(self.request("catalog_query", {"formatFilter": "atmos"})["ok"])

    def test_settings_effective_repeats_keys_and_writes_explicit_scope(self):
        request = self.request('settings_effective', {'keys':['playback.subtitle_mode','playback.auto_play_next']})
        self.assertTrue(request['ok'])
        self.assertEqual(parse_qs(urlsplit(request['url']).query)['keys'], ['playback.subtitle_mode','playback.auto_play_next'])
        write = self.request('settings_write', {'key':'playback.subtitle_mode','scope':'profile','value':'always'})
        self.assertEqual(write['method'], 'PUT')
        self.assertEqual(parse_qs(urlsplit(write['url']).query), {'scope':['profile']})
        self.assertEqual(json.loads(write['body']), {'value':'always'})
        self.assertFalse(self.request('settings_write', {'key':'ui.theme','value':'light'})['ok'])
        self.assertFalse(self.request('settings_write', {'key':'playback.subtitle_mode','value':'always'})['ok'])

    def test_settings_write_requires_confirmed_row_and_effective_revision(self):
        params = {'key':'playback.subtitle_mode','scope':'profile','value':'always'}
        response = {'key':'playback.subtitle_mode','scope':'profile','value':'off','revision':1}
        self.assertFalse(self.call('DecodeSiloResponse','settings_write',json.dumps(response),params)['ok'])
        self.assertFalse(self.call('DecodeSiloResponse','settings_effective',json.dumps({'items':[]}),{})['ok'])
        self.assertFalse(self.call('DecodeSiloResponse','settings_capabilities',json.dumps({'api_version':2,'manifest_revision':1,'allowed':True,'state':'available'}),{})['ok'])

    def test_shuffle_requests_use_conditional_server_owned_current_and_next(self):
        start=self.request('shuffle_start',{'kind':'season','scopeId':'season-7'})
        self.assertTrue(start['ok'])
        self.assertEqual(json.loads(start['body']),{'scope':{'kind':'season','id':'season-7'}})
        advance=self.request('shuffle_advance',{'shuffleId':'s1','itemId':'episode-1'})
        self.assertEqual(json.loads(advance['body']),{'from_content_id':'episode-1'})
        skip=self.request('shuffle_skip',{'shuffleId':'s1','itemId':'episode-2'})
        self.assertEqual(json.loads(skip['body']),{'next_content_id':'episode-2'})
        self.assertEqual(self.request('shuffle_stop',{'shuffleId':'s1'})['method'],'DELETE')
        self.assertFalse(self.request('shuffle_start',{'kind':'unknown','scopeId':'1'})['ok'])

    def test_shuffle_response_validates_identity_and_exact_picks(self):
        response={'id':'s1','scope':{'kind':'season','id':'season-7','title':'Season 7'},'current':{'content_id':'ep1','title':'First','type':'episode'},'next':{'content_id':'ep2','title':'Second','type':'episode'}}
        result=self.call('DecodeSiloResponse','shuffle_start',json.dumps(response),{'kind':'season','scopeId':'season-7'})
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['current']['itemId'],'ep1')
        self.assertEqual(result['data']['next']['itemId'],'ep2')
        self.assertFalse(self.call('DecodeSiloResponse','shuffle_status',json.dumps(response),{'shuffleId':'different'})['ok'])
        response['next']['type']='series'
        self.assertFalse(self.call('DecodeSiloResponse','shuffle_start',json.dumps(response),{'kind':'season','scopeId':'season-7'})['ok'])

    def plan(self, changes=None, **session_changes):
        body = json.loads((FIXTURES / "playback_decision_plan.json").read_text())
        if changes:
            body["playback_plan"]["stream"].update(changes)
        return self.call("SiloPlaybackPlan", body, {**SESSION, **session_changes})

    def start_params(self):
        return json.loads((FIXTURES / "roku_start_input.json").read_text())

    def test_home_section_items_uses_encoded_identity_and_maps_section(self):
        request = self.request("home_section_items", {"sectionId": "recent/custom"})
        self.assertTrue(request["ok"])
        self.assertTrue(request["url"].endswith("/home/sections/recent%2Fcustom/items"))
        body = json.loads((FIXTURES / "home_sections.json").read_text())["sections"][0]
        result = self.call("DecodeSiloResponse", "home_section_items", json.dumps(body), {})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["data"]["items"]), len(body["items"]))
        self.assertFalse(self.request("home_section_items", {"sectionId": 12})["ok"])

    def test_public_device_requests_never_carry_account_headers(self):
        for action in ("device_capability", "device_start", "device_poll", "refresh"):
            with self.subTest(action=action):
                result = self.request(action, {"deviceCode": "synthetic-code"})
                self.assertTrue(result["ok"])
                self.assertNotIn("Authorization", result["headers"])
                self.assertNotIn("X-Profile-Token", result["headers"])
                self.assertNotIn("synthetic-", result["url"])

    def test_device_start_identifies_roku_without_android_claims(self):
        result = self.request("device_start")
        self.assertEqual("POST", result["method"])
        self.assertEqual("https://silo.example/api/v2/auth/device/start", result["url"])
        self.assertEqual("roku", result["headers"]["X-Client-Platform"])
        self.assertEqual("tv", result["headers"]["X-Silo-Client-Family"])
        self.assertEqual({"client_purpose": "device_login", "device_name": "Silo (test-model)",
                          "device_platform": "roku", "temporary": False}, json.loads(result["body"]))

    def test_server_scheme_and_host_case_are_normalized_before_transport(self):
        result = self.request("device_capability", session={**SESSION, "baseUrl": "HTTPS://SILO.EXAMPLE/Silo/"})
        self.assertEqual("https://silo.example/Silo/api/v2/auth/device/capability", result["url"])

    def test_valid_ipv6_server_addresses_accepted_by_setup_reach_the_adapter(self):
        for base_url in ("https://[2001:db8::1]", "http://[::1]:8090"):
            with self.subTest(base_url=base_url):
                result = self.request("device_capability", session={**SESSION, "baseUrl": base_url})
                self.assertTrue(result["ok"])
                self.assertEqual(base_url + "/api/v2/auth/device/capability", result["url"])

    def test_poll_and_refresh_use_required_json_bodies(self):
        self.assertEqual({"device_code": "synthetic-code"},
                         json.loads(self.request("device_poll", {"deviceCode": "synthetic-code"})["body"]))
        self.assertEqual({"refresh_token": "synthetic-refresh"},
                         json.loads(self.request("refresh")["body"]))

    def test_watched_mutations_use_native_v2_item_and_accept_empty_success(self):
        for action, method in (("mark_watched", "POST"), ("mark_unwatched", "DELETE")):
            with self.subTest(action=action):
                request = self.request(action, {"itemId": "content-501"})
                self.assertTrue(request["ok"])
                self.assertEqual(method, request["method"])
                self.assertEqual("https://silo.example/api/v2/watched/content-501", request["url"])
                self.assertEqual("synthetic-access", request["headers"]["Authorization"].removeprefix("Bearer "))
                self.assertEqual("p1", request["headers"]["X-Profile-Id"])
                self.assertEqual("", request["body"])
                self.assertEqual({"ok": True, "data": {}}, self.call("DecodeSiloResponse", action, "", {}))
        for bad in ("", "../other", "bad/name", "bad?query"):
            self.assertFalse(self.request("mark_watched", {"itemId": bad})["ok"])

    def test_catalog_requires_real_profile_and_authenticated_session(self):
        for action in ("home", "libraries", "catalog_query", "detail", "playback_capabilities", "playback_start"):
            with self.subTest(action=action):
                result = self.request(action, {"itemId": "c1"}, {**SESSION, "profileId": " "})
                self.assertFalse(result["ok"])
                self.assertEqual("profile_required", result["errorCode"])
        self.assertEqual("auth_required", self.request("home", session={**SESSION, "accessToken": ""})["errorCode"])

    def test_profiles_can_resolve_blank_profile_after_full_login(self):
        result = self.request("profiles", session={**SESSION, "profileId": "", "profileToken": ""})
        self.assertTrue(result["ok"])
        self.assertEqual("https://silo.example/api/v2/profiles", result["url"])
        self.assertNotIn("X-Profile-Id", result["headers"])

    def test_profile_selection_can_recover_an_expired_locked_profile_proof(self):
        for action, params in (("profiles", {}), ("profile_verify", {"profileId": "p2", "pin": "4321"})):
            with self.subTest(action=action):
                result = self.request(action, params, {**SESSION, "profileToken": "synthetic-expired-proof"})
                self.assertTrue(result["ok"])
                self.assertEqual("Bearer synthetic-access", result["headers"]["Authorization"])
                self.assertNotIn("X-Profile-Id", result["headers"])
                self.assertNotIn("X-Profile-Token", result["headers"])

    def test_pin_verification_is_private_and_can_target_a_locked_profile(self):
        result = self.request("profile_verify", {"profileId": "p/2", "pin": "4321"},
                              {**SESSION, "profileId": "", "profileToken": ""})
        self.assertTrue(result["ok"])
        self.assertEqual("https://silo.example/api/v2/profiles/p%2F2/verify-pin", result["url"])
        self.assertEqual({"pin": "4321"}, json.loads(result["body"]))
        decoded = self.call("DecodeSiloResponse", "profile_verify",
                            '{"valid":true,"expires_at":null,"profile_token":"synthetic-profile"}', {"profileId": "p2"})
        self.assertEqual({"valid": True}, decoded["data"])
        self.assertEqual({"profileId": "p2", "profileToken": "synthetic-profile"}, decoded["session"])

    def test_series_browsing_uses_current_season_and_episode_paths(self):
        seasons = self.request("seasons", {"seriesId": "series:one"})
        self.assertEqual("https://silo.example/api/v2/catalog/series/series%3Aone/seasons?image_size=medium", seasons["url"])
        episodes = self.request("episodes", {"seriesId": "series:one", "seasonNumber": 0, "cursor": "next/+"})
        self.assertEqual("https://silo.example/api/v2/catalog/series/series%3Aone/seasons/0/episodes?image_size=medium", episodes["url"])
        season = self.call("DecodeSiloResponse", "seasons", '{"items":[{"content_id":"season1","season_number":1,"title":"Season 1","episode_count":2}]}', {})
        self.assertEqual("season", season["data"]["items"][0]["type"])
        self.assertEqual(1, season["data"]["items"][0]["seasonNumber"])
        episode = self.call("DecodeSiloResponse", "episodes", '{"items":[{"content_id":"episode1","season_number":1,"episode_number":2,"title":"Episode 2","runtime":20}]}', {})
        self.assertEqual("episode", episode["data"]["items"][0]["type"])
        self.assertEqual(1200000, episode["data"]["items"][0]["durationMs"])

    def test_catalog_request_is_bounded_and_uses_headers_for_auth(self):
        result = self.request("catalog_query", {"libraryId": "lib1", "query": "Heat", "cursor": "next", "limit": 500})
        self.assertEqual("Bearer synthetic-access", result["headers"]["Authorization"])
        self.assertEqual("p1", result["headers"]["X-Profile-Id"])
        self.assertEqual("synthetic-profile", result["headers"]["X-Profile-Token"])
        self.assertEqual({"library_id": "lib1", "q": "Heat", "cursor": "next", "limit": 100}, json.loads(result["body"]))

    def test_item_identifiers_are_percent_encoded(self):
        result = self.request("detail", {"itemId": "movie:Heat / Ω?#"})
        self.assertEqual("https://silo.example/api/v2/catalog/items/movie%3AHeat%20%2F%20%CE%A9%3F%23?image_size=medium", result["url"])

    def test_markers_and_similar_requests_use_verified_paths_and_private_headers(self):
        for action, path in (("markers", "markers/items"), ("similar", "recommendations/similar")):
            with self.subTest(action=action):
                result = self.request(action, {"itemId": "movie:one /", "limit": 900})
                self.assertTrue(result["ok"])
                self.assertEqual("GET", result["method"])
                self.assertEqual(f"/api/v2/{path}/movie%3Aone%20%2F", urlsplit(result["url"]).path)
                self.assertEqual("Bearer synthetic-access", result["headers"]["Authorization"])
                self.assertEqual("synthetic-profile", result["headers"]["X-Profile-Token"])
                self.assertEqual("", result["body"])
                self.assertNotIn("synthetic-", result["url"])
                self.assertEqual("item_required", self.request(action)["errorCode"])

    def test_similar_requests_are_bounded_to_the_recommendation_contract(self):
        for supplied, expected in ((None, "20"), (900, "50"), (0, "1"), (12.9, "12")):
            with self.subTest(limit=supplied):
                params = {"itemId": "c1"}
                if supplied is not None:
                    params["limit"] = supplied
                result = self.request("similar", params)
                self.assertTrue(result["ok"])
                # Captured live 2026-10-14 OpenAPI declares limit only for this route.
                self.assertEqual({"limit": [expected]}, parse_qs(urlsplit(result["url"]).query))

    def test_top_rated_catalog_and_filmography_keep_sort_and_cursor(self):
        for action in ("catalog_query", "person_items"):
            with self.subTest(action=action):
                result = self.request(action, {"sort": "rating_imdb", "order": "desc",
                                               "cursor": "rated-page-2", "personId": "actor-1"})
                self.assertTrue(result["ok"])
                body = json.loads(result["body"])
                self.assertEqual(body["sort"], "rating_imdb")
                self.assertEqual(body["order"], "desc")
                self.assertEqual(body["cursor"], "rated-page-2")
                if action == "person_items":
                    self.assertEqual(body["source"], "person")
                    self.assertEqual(body["person_id"], "actor-1")

    def test_person_detail_and_filmography_use_verified_catalog_contracts(self):
        person = self.request("person", {"personId": "person:one /"})
        self.assertTrue(person["ok"])
        self.assertEqual("GET", person["method"])
        self.assertEqual("https://silo.example/api/v2/catalog/people/person%3Aone%20%2F", person["url"])
        items = self.request("person_items", {"personId": "person:one /", "cursor": "page/+", "limit": 900})
        self.assertTrue(items["ok"])
        self.assertEqual("POST", items["method"])
        self.assertEqual("https://silo.example/api/v2/catalog/query?image_size=medium", items["url"])
        self.assertEqual({"source": "person", "person_id": "person:one /", "cursor": "page/+", "limit": 100},
                         json.loads(items["body"]))
        for action in ("person", "person_items"):
            self.assertEqual("person_required", self.request(action)["errorCode"])

    def test_new_catalog_actions_require_profile_and_account_auth(self):
        for action in ("markers", "similar", "person", "person_items"):
            with self.subTest(action=action):
                self.assertEqual("profile_required", self.request(action, {"itemId": "c1", "personId": "p1"},
                                 {**SESSION, "profileId": ""})["errorCode"])
                self.assertEqual("auth_required", self.request(action, {"itemId": "c1", "personId": "p1"},
                                 {**SESSION, "accessToken": ""})["errorCode"])

    def test_invalid_base_url_and_unknown_action_fail_without_echoing_input(self):
        result = self.request("home", session={**SESSION, "baseUrl": "https://secret@example.com"})
        self.assertEqual("invalid_server_url", result["errorCode"])
        self.assertNotIn("secret", result["message"])
        self.assertEqual("unsupported_action", self.request("unrecognized")["errorCode"])

    def test_start_uses_v3_and_only_supplied_roku_capabilities(self):
        params = self.start_params()
        result = self.request("playback_start", params)
        self.assertTrue(result["ok"])
        body = json.loads(result["body"])
        self.assertEqual(3, body["protocol_version"])
        self.assertEqual(params["clientCapabilities"], body["client_capabilities"])
        self.assertEqual(params["clientPlaybackContext"], body["client_playback_context"])
        self.assertEqual([], body["client_features"])
        self.assertEqual(12.5, body["start_position"])
        self.assertEqual("preserve", body["subtitle_fidelity_preference"])
        self.assertNotIn("MediaCodec", result["body"])

    def test_playback_start_refuses_missing_capability_evidence(self):
        params = self.start_params()
        del params["clientCapabilities"]
        self.assertEqual("capabilities_required", self.request("playback_start", params)["errorCode"])

    def test_playback_start_refuses_non_roku_context(self):
        params = self.start_params()
        params["clientPlaybackContext"]["device"]["platform"] = "android_tv"
        self.assertEqual("invalid_capabilities", self.request("playback_start", params)["errorCode"])

    def test_stop_preserves_server_identity_and_seconds(self):
        result = self.request("playback_stop", {"sessionId": "sess/1", "installationId": "server-install",
                                               "stopId": "stop-1", "positionMs": 12500, "sequence": 2})
        self.assertEqual("DELETE", result["method"])
        self.assertEqual("https://silo.example/api/v2/playback/sess%2F1", result["url"])
        self.assertEqual({"installation_id": "server-install", "stop_id": "stop-1", "position": 12.5, "sequence": 2},
                         json.loads(result["body"]))

    def test_progress_uses_existing_session_endpoint_and_server_sequence(self):
        result = self.request("playback_progress", {"sessionId": "sess-1", "installationId": "server-install",
                                                   "positionMs": 12500, "sequence": 2, "isPaused": True})
        self.assertTrue(result["ok"])
        self.assertEqual("POST", result["method"])
        self.assertEqual("https://silo.example/api/v2/playback/sess-1/progress", result["url"])
        self.assertEqual({"installation_id": "server-install", "position": 12.5, "sequence": 2, "is_paused": True},
                         json.loads(result["body"]))
        mutation = self.call("DecodeSiloResponse", "playback_progress", '{"outcome":"updated"}', {})
        self.assertEqual({"ok": True, "data": {"outcome": "updated"}}, mutation)

    def test_device_capability_is_pairing_support_not_server_health(self):
        result = self.decode("device_capability", "device_capability.json")
        self.assertEqual({"allowed": True, "state": "available", "protocolVersions": [2]}, result["data"])

    def test_device_login_support_uses_pairing_state_and_protocol_with_optional_allowed(self):
        for allowed in (None, False, True):
            body = {"state": "available", "protocol_versions": [2], "allowed": allowed}
            with self.subTest(allowed=allowed):
                result = self.call("DecodeSiloResponse", "device_capability", json.dumps(body), {})
                self.assertTrue(result["data"]["allowed"])
        for state, versions in (("disabled", [2]), ("unavailable", [2]), ("available", [1]), ("available", [])):
            body = {"state": state, "protocol_versions": versions, "allowed": True}
            with self.subTest(state=state, versions=versions):
                result = self.call("DecodeSiloResponse", "device_capability", json.dumps(body), {})
                self.assertFalse(result["data"]["allowed"])

    def test_device_start_and_pending_poll_respect_server_timing(self):
        start = self.decode("device_start", "device_start.json")
        self.assertEqual(5000, start["data"]["intervalMs"])
        self.assertNotIn("deviceCode", start["data"])
        self.assertEqual("synthetic-device-code", start["session"]["deviceCode"])
        pending = self.decode("device_poll", "device_poll_pending.json")
        self.assertEqual({"status": "pending", "pollAfterMs": 5000}, pending["data"])

    def test_approved_login_and_refresh_keep_tokens_out_of_ui_data(self):
        for action, fixture in (("device_poll", "device_poll_approved.json"), ("refresh", "refresh.json")):
            with self.subTest(action=action):
                result = self.decode(action, fixture)
                self.assertTrue(result["ok"])
                self.assertEqual("synthetic-access", result["session"]["accessToken"])
                self.assertNotIn("synthetic-", json.dumps(result["data"]))
                if action == "device_poll":
                    self.assertEqual("p1", result["session"]["profileId"])
                    self.assertEqual("u1", result["data"]["accountId"])

    def test_unknown_poll_status_and_incomplete_approval_are_decode_errors(self):
        for body in ({"status": "mystery"}, {"status": "approved", "tokens": {}}):
            result = self.call("DecodeSiloResponse", "device_poll", json.dumps(body), {})
            self.assertEqual("invalid_response", result["errorCode"])

    def test_home_normalizes_owned_rows_and_resume_units(self):
        result = self.decode("home", "home_sections.json")
        row = result["data"]["rows"][0]
        self.assertEqual("sec1", row["rowId"])
        self.assertEqual("continue_watching", row["sectionType"])
        item = row["items"][0]
        self.assertEqual("silo", item["sourceId"])
        self.assertEqual("c1", item["itemId"])
        self.assertEqual(12500, item["resumeMs"])
        self.assertEqual(120000, item["durationMs"])

    def test_catalog_preserves_display_artwork_on_every_item_route(self):
        fixtures = {
            "home": "home_sections.json",
            "catalog_query": "catalog_query_page1.json",
            "detail": "catalog_item_detail_movie.json",
            "seasons": "catalog_query_page1.json",
            "episodes": "episodes_external_ids.json",
            "similar": "similar_items.json",
            "person_items": "person_items_page1.json",
        }
        for action, fixture in fixtures.items():
            with self.subTest(action=action):
                body = json.loads((FIXTURES / fixture).read_text())
                if action == "home":
                    raw = body["sections"][0]["items"][0]
                elif action == "detail":
                    raw = body
                else:
                    raw = body["items"][0]
                raw.update({
                    "poster_url": "https://images.example/poster.jpg?sig=synthetic-artwork-proof",
                    "backdrop_url": "https://images.example/synthetic-artwork-proof/backdrop.jpg",
                    "still_url": "/images/still.jpg?sig=synthetic-artwork-proof",
                })
                result = self.call("DecodeSiloResponse", action, json.dumps(body), {"seriesId": "series1"})
                self.assertTrue(result["ok"])
                if action == "home":
                    item = result["data"]["rows"][0]["items"][0]
                elif action == "detail":
                    item = result["data"]["item"]
                else:
                    item = result["data"]["items"][0]
                self.assertEqual(raw["content_id"], item["itemId"])
                self.assertEqual(raw["title"], item["title"])
                self.assertEqual("", item["thumbKey"])
                self.assertEqual("", item["backdropKey"])
                self.assertEqual({"poster": raw["poster_url"], "backdrop": raw["backdrop_url"],
                                  "still": raw["still_url"]}, item["art"])

    def test_public_tmdb_artwork_is_available_as_display_art(self):
        raw = {"content_id": "c1", "title": "Fixture film", "type": "movie",
               "poster_url": "https://image.tmdb.org/t/p/w342/synthetic_path.jpg",
               "backdrop_url": "https://image.tmdb.org/t/p/w780/synthetic_path.jpg"}
        result = self.call("SiloItem", raw)
        self.assertTrue(result["ok"])
        self.assertEqual("", result["item"]["thumbKey"])
        self.assertEqual("", result["item"]["backdropKey"])
        self.assertEqual({"poster": raw["poster_url"], "backdrop": raw["backdrop_url"]}, result["item"]["art"])

    def test_credit_ui_data_excludes_provider_photo_urls(self):
        detail = json.loads((FIXTURES / "catalog_item_detail_markers_credits.json").read_text())
        for credit in detail["cast"] + detail["crew"]:
            credit["photo_url"] = "https://images.example/photo.jpg?sig=synthetic-artwork-proof"
        data = self.call("DecodeSiloResponse", "detail", json.dumps(detail), {})["data"]
        for kind in ("cast", "crew"):
            self.assertTrue(data[kind], "The cast and crew remain available for person navigation")
            for credit in data[kind]:
                self.assertTrue(credit["thumbKey"] == "", "Provider credit photos must stay inside the Task")
        self.assertFalse("synthetic-artwork-proof" in json.dumps(data),
                         "Credit photo signatures must not enter UI data")

    def test_person_ui_data_excludes_provider_photo_urls(self):
        person = json.loads((FIXTURES / "person.json").read_text())
        person["photo_url"] = "https://images.example/synthetic-artwork-proof/photo.jpg"
        data = self.call("DecodeSiloResponse", "person", json.dumps(person), {})["data"]
        self.assertEqual(person["id"], data["person"]["personId"])
        self.assertEqual(person["name"], data["person"]["name"])
        self.assertTrue(data["person"]["thumbKey"] == "", "Provider person photos must stay inside the Task")
        self.assertFalse("synthetic-artwork-proof" in json.dumps(data),
                         "Person photo signatures must not enter UI data")

    def test_home_section_type_is_bounded_before_reaching_scene(self):
        body = json.loads((FIXTURES / "home_sections.json").read_text())
        body["sections"][0]["section_type"] = "x" * 1000
        result = self.call("DecodeSiloResponse", "home", json.dumps(body), {})
        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["data"]["rows"][0]["sectionType"]), 64)

    def test_catalog_preserves_cursor_and_watched_state(self):
        result = self.decode("catalog_query", "catalog_query_page1.json")
        self.assertEqual("next-page", result["data"]["nextCursor"])
        self.assertEqual("window-1", result["data"]["windowCursor"])
        self.assertTrue(result["data"]["items"][0]["watched"])

    def test_libraries_preserve_video_types_ids_and_enabled_without_private_fields(self):
        decoded = self.call("DecodeSiloResponse", "libraries", json.dumps({"items": [
            {"id":"movies-id","name":"Movies","type":"movies","enabled":True,"paths":["private"]},
            {"id":"off-id","name":"Disabled","type":"series","enabled":False},
            {"id":"book-id","name":"Books","type":"ebooks"},
        ]}), {})["data"]["libraries"]
        self.assertEqual(decoded, [
            dict(sourceId="silo",libraryId="movies-id",title="Movies",type="movies",enabled=True),
            dict(sourceId="silo",libraryId="off-id",title="Disabled",type="series",enabled=False),
            dict(sourceId="silo",libraryId="book-id",title="Books",type="ebooks",enabled=True),
        ])
        for sort in ("added_at", "release_date", "rating_imdb"):
            request = self.request("catalog_query", dict(type="video", libraryId="movies-id", sort=sort, order="desc", limit=24))
            self.assertEqual(json.loads(request["body"]), dict(type="video",library_id="movies-id",sort=sort,order="desc",limit=24))

    def test_libraries_and_profiles_drop_private_server_fields(self):
        libraries = self.decode("libraries", "libraries.json")["data"]["libraries"]
        self.assertEqual("lib1", libraries[0]["libraryId"])
        self.assertNotIn("paths", libraries[0])
        self.assertTrue(self.decode("profiles", "profiles.json")["data"]["profiles"][0]["isPrimary"])

    def test_display_fields_keep_quality_ratings_and_series_context(self):
        raw = {"content_id": "ep1", "title": "Fixture episode", "type": "episode",
               "series_title": "Fixture series", "content_rating": "TV-14",
               "overlay_summary": {"resolution": "2160p", "hdr": "DV", "audio": "EAC3",
                                   "audio_channels": "5.1", "private": "discard"},
               "rating_imdb": 8.2, "rating_rt_critic": 0, "rating_rt_audience": 91}
        item = self.call("SiloItem", raw)["item"]
        self.assertEqual("Fixture series", item["seriesTitle"])
        self.assertEqual("TV-14", item["contentRating"])
        self.assertEqual({"resolution": "2160p", "hdr": "DV", "audio": "EAC3",
                          "audio_channels": "5.1", "imdb": 8.2, "rtCritic": 0,
                          "rtAudience": 91}, item["badges"])

    def test_catalog_routes_request_medium_artwork_without_changing_auth_or_body(self):
        for action, params in (("home", {}), ("detail", {"itemId": "c1"}),
                               ("seasons", {"seriesId": "series1"}),
                               ("episodes", {"seriesId": "series1", "seasonNumber": 1}),
                               ("catalog_query", {"query": "Fixture"}),
                               ("person_items", {"personId": "person1"})):
            with self.subTest(action=action):
                request = self.request(action, params)
                self.assertTrue(request["ok"])
                self.assertEqual(["medium"], parse_qs(urlsplit(request["url"]).query)["image_size"])
                self.assertEqual("Bearer synthetic-access", request["headers"]["Authorization"])
                self.assertNotIn("image_size", request["body"])

    def test_live_playable_progressive_mkv_decodes_to_native_matroska(self):
        body = json.loads((FIXTURES / "playback_decision_plan.json").read_text())
        body["outcome"] = "playable"
        body["playback_plan"]["stream"].update(protocol="http_progressive", container="mkv")
        decoded = self.call("DecodeSiloResponse", "playback_start", json.dumps(body), {})
        self.assertTrue(decoded["ok"])
        plan = self.call("SiloPlaybackPlan", decoded["playbackDecision"], SESSION)
        self.assertTrue(plan["ok"])
        self.assertEqual("mkv", plan["streamFormat"])

    def test_detail_retains_bounded_chapters_without_signed_thumbnails(self):
        body = json.loads((FIXTURES / "catalog_item_detail_movie.json").read_text())
        body["versions"][0]["chapters"] = [{"start_seconds": 0, "end_seconds": 30, "title": "Opening", "thumbnail_url": "https://art.example/private?signature=synthetic"}]
        result = self.call("DecodeSiloResponse", "detail", json.dumps(body), {})
        self.assertEqual(result["data"]["versions"][0]["chapters"], [{"start_seconds": 0, "end_seconds": 30, "title": "Opening"}])

    def test_detail_normalizes_versions_and_markers(self):
        result = self.decode("detail", "catalog_item_detail_movie.json")
        self.assertEqual("c1", result["data"]["item"]["itemId"])
        self.assertEqual("f1", result["data"]["versions"][0]["versionId"])
        self.assertEqual(7080000, result["data"]["versions"][0]["durationMs"])
        self.assertEqual({"kind": "intro", "startMs": 30000, "endMs": 90000}, result["data"]["markers"][0])

    def test_detail_preserves_verified_external_ids_without_changing_provider_identity(self):
        body = json.loads((FIXTURES / "catalog_item_detail_external_ids.json").read_text())
        body["access_token"] = "private-field-must-be-omitted"
        body["folder_paths"] = ["private-path-must-be-omitted"]
        body["external_ids"] = {"unknown": "private-field-must-be-omitted"}
        result = self.call("DecodeSiloResponse", "detail", json.dumps(body), {})
        item = result["data"]["item"]
        self.assertEqual("synthetic-external-movie", item["itemId"])
        self.assertEqual("silo", item["sourceId"])
        self.assertEqual({"tmdbId": "101", "imdbId": "tt0000101", "tvdbId": "301"},
                         {key: item.get(key) for key in ("tmdbId", "imdbId", "tvdbId")})
        self.assertNotIn("folder_paths", item)
        self.assertNotIn("private", json.dumps(item))

    def test_episode_external_ids_describe_the_episode_and_preserve_series_identity(self):
        result = self.decode("episodes", "episodes_external_ids.json", seriesId="synthetic-series")
        item = result["data"]["items"][0]
        self.assertEqual("episode", item["type"])
        self.assertEqual("synthetic-episode", item["itemId"])
        self.assertEqual("synthetic-series", item["seriesId"])
        self.assertEqual("202", item.get("tmdbId"))
        self.assertEqual("tt0000202", item.get("imdbId"))
        self.assertEqual("302", item.get("tvdbId"))

    def test_detail_external_ids_reject_nonstring_malformed_and_credential_like_values(self):
        body = json.loads((FIXTURES / "catalog_item_detail_external_ids.json").read_text())
        invalid_values = [None, 101, -1, {}, [], "0", "-101", "101.5", "1" * 13,
                          "https://private.example/101?token=private", "101\nAuthorization: private"]
        for value in invalid_values:
            with self.subTest(value=value):
                body.update(tmdb_id=value, imdb_id=value, tvdb_id=value)
                result = self.call("DecodeSiloResponse", "detail", json.dumps(body), {})
                item = result["data"]["item"]
                self.assertEqual({"tmdbId": "", "imdbId": "", "tvdbId": ""},
                                 {key: item.get(key) for key in ("tmdbId", "imdbId", "tvdbId")})
                self.assertNotIn("private", json.dumps(item))
        body.update(tmdb_id=" 000101 ", imdb_id=" TT0000101 ", tvdb_id=" 000301 ")
        item = self.call("DecodeSiloResponse", "detail", json.dumps(body), {})["data"]["item"]
        self.assertEqual(("101", "tt0000101", "301"), (item.get("tmdbId"), item.get("imdbId"), item.get("tvdbId")))

    def test_missing_detail_external_ids_stay_unknown(self):
        item = self.decode("detail", "catalog_item_detail_movie.json")["data"]["item"]
        self.assertEqual(("", "", ""), (item.get("tmdbId"), item.get("imdbId"), item.get("tvdbId")))

    def test_summary_shapes_never_import_undocumented_external_ids(self):
        raw = {"content_id": "synthetic-summary", "title": "Synthetic Summary", "type": "movie",
               "tmdb_id": "101", "imdb_id": "tt0000101", "tvdb_id": "301",
               "plex_guid": "plex://movie/101", "external_ids": {"tmdb": "101"}}
        for action in ("catalog_query", "similar", "person_items", "seasons"):
            result = self.call("DecodeSiloResponse", action, json.dumps({"items": [raw]}), {})
            for key in ("tmdbId", "imdbId", "tvdbId", "plexGuid", "guids", "externalIds"):
                self.assertNotIn(key, result["data"]["items"][0])
        body = {"sections": [{"id": "synthetic-row", "title": "Synthetic Row", "items": [raw]}]}
        item = self.call("DecodeSiloResponse", "home", json.dumps(body), {})["data"]["rows"][0]["items"][0]
        self.assertNotIn("tmdbId", item)

    def test_hydrated_silo_detail_matches_metadata_only_after_active_source_scoping(self):
        item = self.decode("detail", "catalog_item_detail_external_ids.json")["data"]["item"]
        source_id = "silo:synthetic-source"
        seed = {"provider": "metadata", "type": "movie", "tmdbId": "101", "imdbId": "tt0000101", "tvdbId": "301"}
        files = [ADAPTER, ROOT / "source/adapters/MetadataAdapter.brs", ROOT / "source/core/MediaScope.brs"]
        unmatched = run_function(files, "MatchMetadataOwnedItem", [seed, [item], source_id], root=Path(self.package_root.name))
        self.assertIsNone(unmatched)
        scoped = run_function(files, "ScopeCatalogData", [{"item": item}, source_id], root=Path(self.package_root.name))["item"]
        matched = run_function(files, "MatchMetadataOwnedItem", [seed, [scoped], source_id], root=Path(self.package_root.name))
        self.assertIsNotNone(matched, "verified external IDs must resolve the scoped owned Silo detail")
        self.assertEqual("synthetic-external-movie", matched["itemId"])
        self.assertEqual(source_id, matched["sourceId"])

    def test_marker_endpoint_decodes_seconds_and_file_identity(self):
        result = self.decode("markers", "markers_file.json", itemId="c1")
        self.assertTrue(result["ok"])
        self.assertEqual({"itemId": "c1", "versionId": "f1", "markers": [
            {"kind": "recap", "startMs": 0, "endMs": 12500},
            {"kind": "intro", "startMs": 30000, "endMs": 90500},
            {"kind": "credits", "startMs": 6900000, "endMs": 7080000},
        ]}, result["data"])

    def test_marker_occurrences_preserve_repeated_kinds_without_duplicate_summary_segments(self):
        result = self.decode("markers", "markers_occurrences.json", itemId="c1")
        self.assertTrue(result["ok"])
        self.assertEqual([
            {"kind": "intro", "startMs": 12000, "endMs": 20000},
            {"kind": "intro", "startMs": 35000, "endMs": 45000},
            {"kind": "credits", "startMs": 100000, "endMs": 110000},
        ], result["data"]["markers"])
        self.assertNotIn("provider", json.dumps(result["data"]))

    def test_marker_decoder_omits_incomplete_unknown_and_invalid_ranges(self):
        body = {"file_id": "f1", "intro": {"start_seconds": 0}, "recap": {},
                "preview": {"start_seconds": -1, "end_seconds": 3},
                "credits": {"start_seconds": 4, "end_seconds": 3}}
        result = self.call("DecodeSiloResponse", "markers", json.dumps(body), {"itemId": "c1"})
        self.assertTrue(result["ok"])
        self.assertEqual([], result["data"]["markers"])
        body["marker_segments"] = [{"kind": "unknown", "start_seconds": 0, "end_seconds": 3},
                                   {"kind": "intro", "start_seconds": "0", "end_seconds": 3},
                                   {"kind": "recap", "start_seconds": 3, "end_seconds": 3}]
        self.assertEqual([], self.call("DecodeSiloResponse", "markers", json.dumps(body), {})["data"]["markers"])
        for body in ({}, {"file_id": "f1", "marker_segments": None}):
            self.assertEqual("invalid_response", self.call("DecodeSiloResponse", "markers", json.dumps(body), {})["errorCode"])

    def test_detail_preserves_file_markers_and_falls_back_to_shared_kinds(self):
        result = self.decode("detail", "catalog_item_detail_markers_credits.json")
        self.assertTrue(result["ok"])
        first, second = result["data"]["versions"]
        self.assertIn("markers", first)
        self.assertIn("markers", second)
        self.assertEqual([
            {"kind": "recap", "startMs": 0, "endMs": 10000},
            {"kind": "intro", "startMs": 12000, "endMs": 32000},
            {"kind": "preview", "startMs": 90000, "endMs": 100000},
            {"kind": "credits", "startMs": 100000, "endMs": 120000},
        ], first["markers"])
        self.assertEqual([
            {"kind": "recap", "startMs": 0, "endMs": 10000},
            {"kind": "intro", "startMs": 30000, "endMs": 45000},
            {"kind": "credits", "startMs": 200000, "endMs": 220000},
        ], second["markers"])
        self.assertEqual(first["markers"], result["data"]["markers"])

    def test_detail_preserves_sanitized_cast_and_crew_for_person_navigation(self):
        body = json.loads((FIXTURES / "catalog_item_detail_markers_credits.json").read_text())
        body["cast"][0]["access_token"] = "private-field-must-be-omitted"
        result = self.call("DecodeSiloResponse", "detail", json.dumps(body), {})
        self.assertTrue(result["ok"])
        self.assertIn("cast", result["data"])
        self.assertIn("crew", result["data"])
        self.assertEqual({"sourceId": "silo", "personId": "person-1", "name": "Test Actor",
                          "role": "Hero", "thumbKey": "", "order": 0,
                          "tmdbId": "700", "imdbId": "nm0000001", "tvdbId": "", "plexGuid": ""},
                         result["data"]["cast"][0])
        self.assertEqual("Director", result["data"]["crew"][0]["role"])
        self.assertEqual("person-2", result["data"]["crew"][0]["personId"])
        self.assertNotIn("private", json.dumps(result["data"]))
        self.assertNotIn("access_token", json.dumps(result["data"]))

    def test_similar_recommendations_use_normalized_owned_items(self):
        body = json.loads((FIXTURES / "similar_items.json").read_text())
        body["items"][0]["access_token"] = "private-field-must-be-omitted"
        result = self.call("DecodeSiloResponse", "similar", json.dumps(body), {})
        self.assertTrue(result["ok"])
        self.assertEqual(["c2", "series1"], [item["itemId"] for item in result["data"]["items"]])
        self.assertEqual("silo", result["data"]["items"][0]["sourceId"])
        self.assertEqual(12500, result["data"]["items"][0]["resumeMs"])
        self.assertTrue(result["data"]["items"][0]["watched"])
        self.assertFalse(result["data"]["hasMore"])
        self.assertNotIn("access_token", json.dumps(result["data"]))

    def test_person_details_and_filmography_drop_unknown_private_fields(self):
        body = json.loads((FIXTURES / "person.json").read_text())
        body["access_token"] = "private-field-must-be-omitted"
        result = self.call("DecodeSiloResponse", "person", json.dumps(body), {})
        self.assertTrue(result["ok"])
        self.assertEqual({"sourceId": "silo", "personId": "person-1", "name": "Test Actor",
                          "thumbKey": "", "bio": "A synthetic biography.",
                          "birthDate": "1970-01-01", "deathDate": "", "birthplace": "Example City",
                          "tmdbId": "700", "imdbId": "nm0000001", "tvdbId": "", "plexGuid": ""},
                         result["data"]["person"])
        self.assertNotIn("private", json.dumps(result["data"]))
        items = self.decode("person_items", "person_items_page1.json", personId="person-1")["data"]
        self.assertEqual("page/+", items["nextCursor"])
        self.assertTrue(items["hasMore"])
        self.assertEqual("window-person-1", items["windowCursor"])
        self.assertEqual("c2", items["items"][0]["itemId"])

    def test_new_catalog_decoders_reject_missing_required_public_shapes(self):
        for action, body in (("person", {}), ("person", {"id": "p1", "name": ""}),
                             ("similar", {}), ("person_items", {"items": [None]})):
            with self.subTest(action=action):
                self.assertEqual("invalid_response", self.call("DecodeSiloResponse", action, json.dumps(body), {})["errorCode"])

    def test_track_normalization_preserves_selectable_ordinals_and_omits_unknown_fields(self):
        body = json.loads((FIXTURES / "catalog_item_detail_movie.json").read_text())
        body["versions"][0]["audio_tracks"][0]["access_token"] = "synthetic-access"
        result = self.call("DecodeSiloResponse", "detail", json.dumps(body), {})
        track = result["data"]["versions"][0]["audioTracks"][0]
        self.assertEqual(0, track["index"])
        self.assertEqual("0", track["id"])
        self.assertEqual("eac3", track["codec"])
        self.assertNotIn("synthetic-access", json.dumps(result["data"]))

    def test_problem_and_malformed_responses_do_not_echo_server_messages(self):
        result = self.call("DecodeSiloResponse", "home", '{"status":403,"type":"https://siloserver.org/docs/api/v2/problems/profile_locked","title":"Profile locked","detail":"secret-url","instance":"urn:silo:request:synthetic"}', {})
        self.assertEqual("profile_locked", result["errorCode"])
        self.assertNotIn("secret-url", result["message"])
        for body in ("{", "[]", "null", "{}"):
            self.assertEqual("invalid_response", self.call("DecodeSiloResponse", "home", body, {})["errorCode"])

    def test_playback_decision_and_mutation_decode_keep_streams_outside_ui_data(self):
        result = self.decode("playback_start", "playback_decision_plan.json")
        self.assertEqual("plan", result["data"]["outcome"])
        self.assertNotIn("https://", json.dumps(result["data"]))
        self.assertEqual(3, result["playbackDecision"]["protocol_version"])
        stopped = self.call("DecodeSiloResponse", "playback_stop", '{"outcome":"stopped"}', {})
        self.assertEqual({"outcome": "stopped"}, stopped["data"])

    def test_v3_capability_decodes_server_installation_identity(self):
        result = self.decode("playback_capabilities", "playback_capabilities.json")
        self.assertEqual([3], result["data"]["protocolVersions"])
        self.assertEqual("server-install", result["data"]["installationId"])

    def test_hls_stays_disabled_until_native_audio_delivery_is_proven(self):
        result=self.plan({"url":"/stream/one.m3u8","protocol":"hls","container":"mpegts"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["errorCode"],"unsupported_stream")

    def test_same_origin_plan_applies_provider_auth_and_player_timeline(self):
        result = self.plan({"url": "/stream/one.mp4", "protocol": "progressive", "container":"mp4", "headers": {"User-Agent": "SiloPlayer"}})
        self.assertTrue(result["ok"])
        self.assertEqual("https://silo.example/stream/one.mp4", result["url"])
        self.assertEqual("mp4", result["streamFormat"])
        self.assertEqual("Bearer synthetic-access", result["headers"]["Authorization"])
        self.assertEqual(12500, result["startPositionMs"])
        self.assertEqual("f1", result["versionId"])
        self.assertEqual("sess-1", result["sessionId"])

    def test_foreign_signed_plan_strips_provider_credentials(self):
        result = self.plan({"url": "https://cdn.example/one.mp4?signature=synthetic", "protocol": "progressive", "container": "mp4",
                            "headers": {"Authorization": "Bearer synthetic-access", "x-profile-token": "synthetic-profile", "User-Agent": "SiloPlayer"}})
        self.assertTrue(result["ok"])
        self.assertEqual({"User-Agent": "SiloPlayer"}, result["headers"])
        self.assertEqual("mp4", result["streamFormat"])

    def test_playback_headers_reject_invalid_names_and_preserve_values_with_colons(self):
        headers = {"X-Test": "one:two", "X!Allowed": "value", "Bad:Name": "value", "Bad Name": "value",
                   "Bad\tName": "value", "Bad\x00Name": "value", "Ünicode": "value", "BadValue": "one\r\ntwo"}
        result = self.plan({"url": "https://cdn.example/one.mp4", "protocol": "progressive", "container": "mp4",
                            "headers": headers})
        self.assertTrue(result["ok"])
        self.assertEqual({"X-Test": "one:two", "X!Allowed": "value"}, result["headers"])

    def test_same_origin_compares_scheme_host_and_effective_port(self):
        for url, same in (("https://SILO.example:443/one.mp4", True), ("https://silo.example:444/one.mp4", False),
                          ("http://silo.example/one.mp4", False), ("https://silo.example.evil.test/one.mp4", False)):
            with self.subTest(url=url):
                result = self.plan({"url": url, "protocol": "progressive", "container": "mp4"})
                self.assertEqual(same, "Authorization" in result["headers"])

    def test_plan_rejects_unknown_format_refresh_and_terminal_without_echoing(self):
        for changes, code in (({"protocol": "rtsp"}, "unsupported_stream"),
                              ({"header_refresh": "required"}, "unsupported_header_refresh"),
                              ({"url": "https://secret@example.com/one.mp4"}, "invalid_stream_url")):
            with self.subTest(changes=changes):
                result = self.plan(changes)
                self.assertEqual(code, result["errorCode"])
                self.assertNotIn("secret", result["message"])
        terminal = json.loads((FIXTURES / "playback_decision_terminal.json").read_text())
        result = self.call("SiloPlaybackPlan", terminal, SESSION)
        self.assertEqual("playback_terminal", result["errorCode"])
        self.assertEqual("no_playable_source", result["reason"])

    def test_conversion_start_failure_reason_propagates_only_as_allowlisted_enum(self):
        decision={"protocol_version":3,"outcome":"adaptation_unavailable",
                  "terminal":{"reason":"transcode_start_failed","message":"private server detail https://secret.invalid/x","retryable":False}}
        plan=self.call("SiloPlaybackPlan",decision,SESSION)
        self.assertFalse(plan["ok"])
        self.assertEqual(("playback_terminal","transcode_start_failed",False),(plan["errorCode"],plan["reason"],plan["retryable"]))
        failure=self.call("SiloPlaybackFailureDetails",{"ok":False,"errorCode":"playback_terminal"},decision,"start")
        self.assertEqual({"ok":False,"errorCode":"playback_terminal","stage":"start","reason":"transcode_start_failed"},failure)
        reported=self.call("SiloPlaybackErrorBody",{"report":{"installationId":"install","playbackAttemptId":"attempt-0001"},
            "supportCode":"2016","errorCode":"playback_terminal","reason":"transcode_start_failed",
            "eventId":"10000000-0000-4000-8000-000000000001"})
        self.assertTrue(reported["ok"])
        self.assertEqual("transcode_start_failed",reported["body"]["diagnostics"]["reason"])
        self.assertEqual("2016",reported["body"]["diagnostics"]["error_code"])
        untrusted=dict(decision,terminal={"reason":"future_private_reason","message":"secret","retryable":False})
        filtered=self.call("SiloPlaybackFailureDetails",{"ok":False,"errorCode":"playback_terminal"},untrusted,"start")
        self.assertEqual({"ok":False,"errorCode":"playback_terminal","stage":"start"},filtered)
        self.assertNotIn("secret",json.dumps([plan,failure,reported,filtered]))


if __name__ == "__main__":
    unittest.main()
