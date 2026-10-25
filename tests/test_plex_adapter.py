"""Plex wire contracts executed by the BrightScript interpreter, never reimplemented here."""

import json
import os
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
ADAPTER = ROOT / "source/adapters/PlexAdapter.brs"
FIXTURES = ROOT / "tests/fixtures/plex"


class PlexAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ADAPTER.exists():
            raise AssertionError("Plex request and decoder adapter is missing")
        from brightscript import interpreter_available, run_function
        if not interpreter_available():
            message = "install runtime tests: npm ci --prefix tools/brightscript --ignore-scripts"
            if os.environ.get("SILO_REQUIRE_BRS") == "1":
                raise RuntimeError(message)
            raise unittest.SkipTest(message)
        cls.run_function = staticmethod(run_function)

    def call(self, function, *arguments):
        return self.run_function(ADAPTER, function, list(arguments))

    def session(self, **changes):
        value = {"clientId": "fixture-client", "token": "fixture-only-secret", "baseUrl": "https://plex.example.test", "sourceId": "plex:server-a", "local": False}
        value.update(changes)
        return value

    def request(self, action, params=None, **session_changes):
        return self.call("BuildPlexRequest", action, self.session(**session_changes), params or {})

    def decode(self, action, fixture=None, body=None, **params):
        payload = body if body is not None else (FIXTURES / fixture).read_text()
        return self.call("DecodePlexResponse", action, payload, {"sourceId": "plex:server-a", **params})

    def test_pin_requests_do_not_send_an_existing_account_token(self):
        start = self.request("pin_start")
        poll = self.request("pin_poll", {"pinId": 42})
        self.assertEqual((start["method"], start["url"]), ("POST", "https://plex.tv/api/v2/pins?strong=false"))
        self.assertEqual(poll["url"], "https://plex.tv/api/v2/pins/42")
        for request in (start, poll):
            self.assertNotIn("X-Plex-Token", request["headers"])
            self.assertEqual(request["headers"]["X-Plex-Platform"], "Roku")
            self.assertEqual(request["headers"]["X-Plex-Client-Identifier"], "fixture-client")

    def test_pin_request_identifies_the_actual_roku_os_version(self):
        request = self.request("pin_start", osVersion="15.3.4")
        self.assertEqual("15.3.4", request["headers"]["X-Plex-Platform-Version"])

    def test_account_and_resource_requests_use_header_auth(self):
        for action, path in (("user", "/api/v2/user"), ("resources", "/api/v2/resources?includeHttps=1&includeRelay=1")):
            with self.subTest(action=action):
                request = self.request(action, accountToken="fixture-account-token")
                self.assertTrue(request["ok"])
                self.assertEqual(request["url"], "https://plex.tv" + path)
                self.assertEqual(request["headers"]["X-Plex-Token"], "fixture-account-token")
                self.assertNotIn("fixture-account-token", request["url"])

    def test_account_endpoints_never_use_selected_server_access_token(self):
        for action in ("user", "resources"):
            with self.subTest(action=action):
                request = self.request(action, token="shared-server-token", accountToken="owner-account-token")
                self.assertEqual("owner-account-token", request["headers"]["X-Plex-Token"])
                self.assertNotIn("shared-server-token", str(request))
                self.assertEqual("auth_required", self.request(action, token="shared-server-token", accountToken="")["errorCode"])
        library = self.request("sections", token="shared-server-token", accountToken="owner-account-token")
        self.assertEqual("shared-server-token", library["headers"]["X-Plex-Token"])

    def test_catalog_endpoints_and_small_pages(self):
        expected = {"identity": "/identity", "sections": "/library/sections", "home_continue": "/hubs/home/continueWatching", "home_on_deck": "/hubs/home/onDeck", "library_items": "/library/sections/2/all", "detail": "/library/metadata/101", "children": "/library/metadata/101/children", "section_hubs": "/hubs/sections/2"}
        for action, path in expected.items():
            with self.subTest(action=action):
                request = self.request(action, {"sectionId": "2", "itemId": "101", "limit": 999, "offset": -1})
                self.assertTrue(request["ok"])
                self.assertEqual(urlsplit(request["url"]).path, path)
                self.assertEqual(request["headers"]["X-Plex-Token"], "fixture-only-secret")
                if action.startswith("home_"):
                    self.assertEqual(request["headers"]["X-Plex-Container-Size"], "12")
                if action == "library_items":
                    query = parse_qs(urlsplit(request["url"]).query)
                    self.assertEqual(query["X-Plex-Container-Size"], ["48"])
                    self.assertEqual(query["X-Plex-Container-Start"], ["0"])

    def test_related_uses_owned_metadata_identity_and_header_auth(self):
        request = self.request("related", {"itemId": "101"})
        self.assertTrue(request["ok"])
        self.assertEqual(request["method"], "GET")
        self.assertEqual(urlsplit(request["url"]).path, "/library/metadata/101/related")
        self.assertEqual(request["headers"]["X-Plex-Token"], "fixture-only-secret")
        self.assertNotIn("fixture-only-secret", request["url"])
        for item_id in ("", "../101", "101?X-Plex-Token=unsafe"):
            self.assertFalse(self.request("related", {"itemId": item_id})["ok"])

    def test_related_flattens_video_hubs_in_server_order_and_bounds_items(self):
        result = self.decode("related", "related.json", limit=2)
        self.assertTrue(result["ok"])
        self.assertEqual([item["itemId"] for item in result["data"]["items"]], ["201", "202"])
        self.assertTrue(all(item["sourceId"] == "plex:server-a" for item in result["data"]["items"]))
        self.assertFalse(self.decode("related", body='{"MediaContainer":{"Hub":"invalid"}}')["ok"])

    def test_search_query_is_encoded_and_cannot_inject_token(self):
        request = self.request("search", {"query": "雪 & X-Plex-Token=bad", "limit": 6})
        query = parse_qs(urlsplit(request["url"]).query)
        self.assertEqual(query["query"], ["雪 & X-Plex-Token=bad"])
        self.assertNotIn("X-Plex-Token", query)
        self.assertEqual(query["limit"], ["6"])
        self.assertNotIn("fixture-only-secret", request["url"])

    def test_rejects_credential_urls_and_missing_identifiers_without_echoing_secrets(self):
        for request in (self.request("sections", baseUrl="https://name:fixture-only-secret@plex.example.test"), self.request("sections", baseUrl="https://plex.example.test?token=fixture-only-secret"), self.request("detail"), self.request("pin_poll"), self.request("unknown")):
            self.assertFalse(request["ok"])
            self.assertNotIn("fixture-only-secret", json.dumps(request))

    def test_pin_start_normalizes_expiry_and_poll_interval(self):
        result = self.decode("pin_start", body='{"id":42,"code":"ABCD","expiresIn":120,"authToken":"should-not-leak"}', nowMs=1000)
        self.assertEqual(result["data"]["pinId"], "42")
        self.assertEqual(result["data"]["code"], "ABCD")
        self.assertEqual(result["data"]["expiresAtMs"], 121000)
        self.assertEqual(result["data"]["pollIntervalMs"], 2000)
        self.assertNotIn("should-not-leak", json.dumps(result))

    def test_poll_returns_credentials_separately_from_display_data(self):
        result = self.decode("pin_poll", body='{"id":42,"authToken":"fixture-linked-token"}')
        self.assertEqual(result["data"], {"state": "linked"})
        self.assertEqual(result["session"], {"accountToken": "fixture-linked-token"})
        pending = self.decode("pin_poll", body='{"id":42,"authToken":null}', nowMs=1000, expiresAtMs=2000)
        expired = self.decode("pin_poll", body='{"id":42,"authToken":null}', nowMs=2001, expiresAtMs=2000)
        self.assertEqual(pending["data"]["state"], "pending")
        self.assertEqual(expired["data"]["state"], "expired")

    def test_user_requires_an_id_and_omits_email_and_auth_token(self):
        result = self.decode("user", body='{"id":7,"username":"","title":"Fixture User","email":"private@example.test","authToken":"secret"}')
        self.assertEqual(result["data"], {"accountId": "7", "accountName": "Fixture User"})
        self.assertFalse(self.decode("user", body='{"username":"No ID"}')["ok"])

    def test_resources_filter_players_and_unsafe_connections(self):
        result = self.decode("resources", "resources.json")
        self.assertEqual(len(result["data"]["servers"]), 1)
        server = result["data"]["servers"][0]
        self.assertEqual(server["sourceId"], "plex:server-a")
        self.assertEqual(server["machineId"], "server-a")
        self.assertEqual(server["token"], "fixture-resource-token")
        self.assertEqual([c["baseUrl"] for c in server["connections"]], ["https://server.example.test", "https://relay.example.test"])

    def resource(self, machine_id, *, owned, connection_count=1):
        return {"clientIdentifier": machine_id, "name": machine_id, "provides": "server",
                "accessToken": "synthetic-resource-token", "owned": owned,
                "connections": [{"uri": f"https://{machine_id}-{index}.example.test",
                                 "local": False, "relay": False}
                                for index in range(connection_count)]}

    def test_owned_server_after_twenty_four_shared_servers_remains_visible_within_caps(self):
        resources = [self.resource(f"shared-{index}", owned=False) for index in range(24)]
        resources.extend([self.resource("owned-a", owned=True, connection_count=15),
                          self.resource("owned-b", owned=True)])
        result = self.decode("resources", body=json.dumps(resources))
        self.assertTrue(result["ok"])
        servers = result["data"]["servers"]
        self.assertEqual(["owned-a", "owned-b", *[f"shared-{index}" for index in range(22)]],
                         [server["machineId"] for server in servers])
        self.assertEqual(24, len(servers))
        self.assertEqual(12, len(servers[0]["connections"]))

    def test_owned_servers_fill_the_resource_cap_before_shared_servers(self):
        resources = [self.resource("shared-first", owned=False)]
        resources.extend(self.resource(f"owned-{index}", owned=True) for index in range(25))
        result = self.decode("resources", body=json.dumps(resources))
        self.assertTrue(result["ok"])
        self.assertEqual([f"owned-{index}" for index in range(24)],
                         [server["machineId"] for server in result["data"]["servers"]])

    def test_selected_shared_server_can_be_resolved_after_resource_order_changes(self):
        resources = [self.resource(f"owned-{index}", owned=True) for index in range(24)]
        resources.append(self.resource("selected-shared", owned=False))
        public = self.decode("resources", body=json.dumps(resources))
        self.assertNotIn("selected-shared", [server["machineId"] for server in public["data"]["servers"]])
        selected = self.call("PlexDecodeResources", resources, "selected-shared")
        self.assertTrue(selected["ok"])
        self.assertEqual(["selected-shared"], [server["machineId"] for server in selected["data"]["servers"]])

    def test_targeted_resolution_skips_duplicate_without_a_usable_route(self):
        unusable = self.resource("selected", owned=False)
        unusable["connections"] = [{"uri": "https://user:secret@invalid.example.test", "local": False}]
        usable = self.resource("selected", owned=False)
        selected = self.call("PlexDecodeResources", [unusable, usable], "selected")
        self.assertEqual(["selected"], [server["machineId"] for server in selected["data"]["servers"]])

    def test_identity_mismatch_cannot_connect_to_a_different_server(self):
        matched = self.decode("identity", body='{"MediaContainer":{"machineIdentifier":"server-a"}}', machineId="server-a")
        mismatch = self.decode("identity", body='{"MediaContainer":{"machineIdentifier":"server-b"}}', machineId="server-a")
        self.assertTrue(matched["ok"])
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["errorCode"], "server_mismatch")

    def test_sections_only_include_video_libraries(self):
        result = self.decode("sections", "sections.json")
        self.assertEqual([section["sectionId"] for section in result["data"]["sections"]], ["1", "2"])
        self.assertTrue(all(s["sourceId"] == "plex:server-a" for s in result["data"]["sections"]))

    def test_episode_home_item_preserves_identity_and_resume(self):
        result = self.decode("home_continue", "continue.json")
        item = result["data"]["items"][0]
        self.assertEqual((item["sourceId"], item["itemId"], item["type"]), ("plex:server-a", "101", "episode"))
        self.assertEqual(item["seriesTitle"], "Sample Show")
        self.assertEqual(item["durationMs"], 2700000)
        self.assertEqual(item["resumeMs"], 900000)
        self.assertEqual(item["thumbKey"], "/library/metadata/100/thumb/2000")

    def test_episode_and_season_preserve_parent_identity_for_up_next(self):
        episode = self.decode("home_continue", "continue.json")["data"]["items"][0]
        self.assertIn("parentItemId", episode)
        self.assertEqual(episode["parentItemId"], "110")
        self.assertEqual(episode["seasonItemId"], "110")
        self.assertEqual(episode["seriesItemId"], "100")
        season = self.decode("children", "seasons.json")["data"]["items"][0]
        self.assertEqual(season["parentItemId"], "100")
        self.assertEqual(season["seriesItemId"], "100")
        self.assertEqual(season["seasonItemId"], "110")
        self.assertEqual(season["seasonNumber"], 1)
        self.assertEqual(season["episodeNumber"], 0)
        self.assertEqual(season["seriesTitle"], "Sample Show")

    def test_parent_identity_drops_unsafe_rating_keys(self):
        raw = {"ratingKey": "101", "type": "episode", "parentRatingKey": "110?token=unsafe", "grandparentRatingKey": "../100"}
        item = self.decode("children", body=json.dumps({"MediaContainer": {"Metadata": [raw]}}))["data"]["items"][0]
        self.assertIn("parentItemId", item)
        self.assertEqual(item["parentItemId"], "")
        self.assertEqual(item["seasonItemId"], "")
        self.assertEqual(item["seriesItemId"], "")

    def children_payload(self, start, count, *, kind="episode", **container_fields):
        metadata = []
        for ordinal in range(start, start + count):
            item = {"ratingKey": str(1000 + ordinal), "type": kind,
                    "title": "Synthetic Child " + str(ordinal), "index": ordinal + 1,
                    "parentRatingKey": "110", "grandparentRatingKey": "100", "parentIndex": 1}
            if kind == "season":
                item["parentRatingKey"] = "100"
            metadata.append(item)
        return {"MediaContainer": {"offset": start, "size": count, "Metadata": metadata, **container_fields}}

    def children_page(self, payload, **params):
        return self.decode("children", body=json.dumps(payload), **params)

    def test_children_requests_send_bounded_query_ranges_and_preserve_header_auth(self):
        for params, start, size in (({"itemId": "110"}, 0, 24),
                                    ({"itemId": "110", "offset": 24, "limit": 24}, 24, 24),
                                    ({"itemId": "100", "offset": -10, "limit": 999}, 0, 48),
                                    ({"itemId": "100", "offset": "48", "limit": 0}, 48, 1)):
            with self.subTest(params=params):
                request = self.request("children", params, osVersion="15.3.4")
                self.assertTrue(request["ok"])
                query = parse_qs(urlsplit(request["url"]).query)
                self.assertIn("X-Plex-Container-Start", query)
                self.assertIn("X-Plex-Container-Size", query)
                self.assertEqual([str(start)], query["X-Plex-Container-Start"])
                self.assertEqual([str(size)], query["X-Plex-Container-Size"])
                self.assertEqual(["1"], query["includeGuids"])
                self.assertNotIn("X-Plex-Container-Start", request["headers"])
                self.assertNotIn("X-Plex-Container-Size", request["headers"])
                self.assertEqual("fixture-only-secret", request["headers"]["X-Plex-Token"])
                self.assertEqual("15.3.4", request["headers"]["X-Plex-Platform-Version"])
                self.assertNotIn("fixture-only-secret", request["url"])

    def test_more_than_24_children_are_reachable_in_bounded_pages(self):
        all_ids = []
        for offset, count, has_more, next_offset in ((0, 24, True, 24), (24, 24, True, 48), (48, 12, False, -1)):
            with self.subTest(offset=offset):
                result = self.children_page(self.children_payload(offset, count, totalSize=60), offset=offset, limit=24)
                self.assertTrue(result["ok"])
                data = result["data"]
                self.assertIn("hasMore", data)
                self.assertEqual((offset, 24, count, True, 60, has_more, next_offset),
                                 (data["offset"], data["pageSize"], data["rawCount"], data["totalKnown"], data["totalSize"], data["hasMore"], data["nextOffset"]))
                self.assertEqual(count, len(data["items"]))
                self.assertTrue(all(item["sourceId"] == "plex:server-a" for item in data["items"]))
                all_ids.extend(item["itemId"] for item in data["items"])
        self.assertEqual([str(1000 + i) for i in range(60)], all_ids)

    def test_show_seasons_use_the_same_pagination_contract(self):
        first = self.children_page(self.children_payload(0, 24, kind="season", totalSize=30), limit=24)["data"]
        self.assertIn("nextOffset", first)
        self.assertEqual(24, first["nextOffset"])
        last = self.children_page(self.children_payload(24, 6, kind="season", totalSize=30), offset=24, limit=24)["data"]
        self.assertEqual((False, -1), (last["hasMore"], last["nextOffset"]))
        self.assertTrue(all(item["type"] == "season" and item["seriesItemId"] == "100" for item in first["items"] + last["items"]))

    def test_children_paging_advances_by_raw_slots_when_items_are_filtered(self):
        payload = self.children_payload(24, 24, totalSize=70)
        payload["MediaContainer"]["Metadata"][0] = {"type": "episode", "title": "Missing Native ID"}
        payload["MediaContainer"]["Metadata"][1] = {"ratingKey": "music", "type": "track"}
        data = self.children_page(payload, offset=24, limit=24)["data"]
        self.assertIn("rawCount", data)
        self.assertEqual((22, 24, True, 48), (len(data["items"]), data["rawCount"], data["hasMore"], data["nextOffset"]))

    def test_children_raw_window_is_bounded_before_normalization(self):
        payload = self.children_payload(0, 5, totalSize=8)
        payload["MediaContainer"]["Metadata"][0] = {"type": "episode"}
        data = self.children_page(payload, limit=2)["data"]
        self.assertEqual(["1001"], [item["itemId"] for item in data["items"]])
        self.assertEqual((2, 2, True, 2), (data["pageSize"], data["rawCount"], data["hasMore"], data["nextOffset"]))

    def test_unknown_child_total_uses_full_or_short_page_not_size_as_total(self):
        full = self.children_page(self.children_payload(0, 24), limit=24)["data"]
        self.assertIn("totalKnown", full)
        self.assertEqual((False, 24, True, 24), (full["totalKnown"], full["totalSize"], full["hasMore"], full["nextOffset"]))
        last = self.children_page(self.children_payload(24, 3), offset=24, limit=24)["data"]
        self.assertEqual((False, 27, False, -1), (last["totalKnown"], last["totalSize"], last["hasMore"], last["nextOffset"]))

    def test_empty_child_page_ends_even_when_server_reports_more(self):
        for payload in (self.children_payload(48, 0, totalSize=1000), {"MediaContainer": {"offset": 48, "totalSize": 1000}}):
            with self.subTest(payload=payload):
                data = self.children_page(payload, offset=48, limit=24)["data"]
                self.assertIn("hasMore", data)
                self.assertEqual(([], 0, False, -1), (data["items"], data["rawCount"], data["hasMore"], data["nextOffset"]))

    def test_short_child_page_with_known_total_does_not_skip_missing_slots(self):
        data = self.children_page(self.children_payload(24, 3, totalSize=60), offset=24, limit=24)["data"]
        self.assertIn("nextOffset", data)
        self.assertEqual((True, 27), (data["hasMore"], data["nextOffset"]))

    def test_missing_child_response_offset_uses_requested_offset(self):
        payload = self.children_payload(24, 24, totalSize=60)
        del payload["MediaContainer"]["offset"]
        data = self.children_page(payload, offset=24, limit=24)["data"]
        self.assertEqual(24, data["offset"])
        self.assertEqual(48, data["nextOffset"])

    def test_repeated_or_malformed_child_response_offset_is_rejected(self):
        for offset in (0, -1, "unreadable", 24.5):
            with self.subTest(offset=offset):
                payload = self.children_payload(24, 24, totalSize=60)
                payload["MediaContainer"]["offset"] = offset
                result = self.children_page(payload, offset=24, limit=24)
                self.assertFalse(result["ok"])
                self.assertEqual("page_mismatch", result["errorCode"])

    def test_fully_filtered_child_page_can_still_advance(self):
        payload = {"MediaContainer": {"offset": 24, "totalSize": 60, "Metadata": [{"type": "track", "ratingKey": str(i)} for i in range(24)]}}
        data = self.children_page(payload, offset=24, limit=24)["data"]
        self.assertIn("rawCount", data)
        self.assertEqual(([], 24, True, 48), (data["items"], data["rawCount"], data["hasMore"], data["nextOffset"]))

    def library_page(self, start, count, *, total=None, limit=100, **container_fields):
        payload = self.children_payload(start, count, kind="movie", **container_fields)
        if total is not None:
            payload["MediaContainer"]["totalSize"] = total
        return self.decode("library_items", body=json.dumps(payload), offset=start, limit=limit)

    def test_library_pages_advance_by_raw_slots_when_native_cards_are_filtered(self):
        payload = self.children_payload(48, 48, kind="movie", totalSize=120)
        payload["MediaContainer"]["Metadata"][0] = {"type": "movie", "title": "Missing Native ID"}
        payload["MediaContainer"]["Metadata"][1] = {"ratingKey": "1049", "type": "track"}
        data = self.decode("library_items", body=json.dumps(payload), offset=48, limit=100)["data"]
        self.assertIn("rawCount", data)
        self.assertEqual((46, 48, 48, True, 120, True, 96),
                         (len(data["items"]), data["pageSize"], data["rawCount"], data["totalKnown"],
                          data["totalSize"], data["hasMore"], data["nextOffset"]))
        next_page = self.library_page(data["nextOffset"], 24, total=120)["data"]
        self.assertEqual("1096", next_page["items"][0]["itemId"])
        self.assertEqual((False, -1), (next_page["hasMore"], next_page["nextOffset"]))

    def test_library_unknown_total_uses_full_or_short_raw_window(self):
        first = self.library_page(0, 48)["data"]
        self.assertIn("totalKnown", first)
        self.assertEqual((False, 48, True, 48),
                         (first["totalKnown"], first["totalSize"], first["hasMore"], first["nextOffset"]))
        last = self.library_page(48, 3)["data"]
        self.assertEqual((False, 51, False, -1),
                         (last["totalKnown"], last["totalSize"], last["hasMore"], last["nextOffset"]))

    def test_library_known_total_allows_short_page_and_ends_at_final_slot(self):
        first = self.library_page(48, 3, total=60)["data"]
        self.assertIn("nextOffset", first)
        self.assertEqual((True, 51), (first["hasMore"], first["nextOffset"]))
        last = self.library_page(51, 9, total=60)["data"]
        self.assertEqual((True, 60, False, -1),
                         (last["totalKnown"], last["totalSize"], last["hasMore"], last["nextOffset"]))

    def test_library_raw_window_is_bounded_before_normalization(self):
        payload = self.children_payload(0, 60, kind="movie", totalSize=70)
        payload["MediaContainer"]["Metadata"][0] = {"type": "movie"}
        data = self.decode("library_items", body=json.dumps(payload), limit=100)["data"]
        self.assertEqual([str(1000 + i) for i in range(1, 48)], [item["itemId"] for item in data["items"]])
        self.assertEqual((48, 48, True, 48), (data["pageSize"], data["rawCount"], data["hasMore"], data["nextOffset"]))

    def test_library_missing_response_offset_uses_requested_offset(self):
        payload = self.children_payload(48, 48, kind="movie", totalSize=120)
        del payload["MediaContainer"]["offset"]
        data = self.decode("library_items", body=json.dumps(payload), offset=48, limit=100)["data"]
        self.assertEqual(48, data["offset"])
        self.assertEqual(96, data["nextOffset"])

    def test_library_repeated_or_malformed_response_offset_is_rejected(self):
        for reported_offset in (0, -1, "unreadable", 48.5):
            with self.subTest(offset=reported_offset):
                payload = self.children_payload(48, 48, kind="movie", totalSize=120)
                payload["MediaContainer"]["offset"] = reported_offset
                result = self.decode("library_items", body=json.dumps(payload), offset=48, limit=100)
                self.assertFalse(result["ok"])
                self.assertEqual("page_mismatch", result["errorCode"])

    def test_library_fully_filtered_raw_page_still_advances(self):
        payload = {"MediaContainer": {"offset": 48, "totalSize": 120,
                                      "Metadata": [{"type": "track", "ratingKey": str(i)} for i in range(48)]}}
        data = self.decode("library_items", body=json.dumps(payload), offset=48, limit=100)["data"]
        self.assertIn("rawCount", data)
        self.assertEqual(([], 48, True, 96), (data["items"], data["rawCount"], data["hasMore"], data["nextOffset"]))

    def test_library_empty_raw_page_ends_even_when_reported_total_is_larger(self):
        for payload in (self.children_payload(48, 0, kind="movie", totalSize=120),
                        {"MediaContainer": {"offset": 48, "totalSize": 120}}):
            with self.subTest(payload=payload):
                data = self.decode("library_items", body=json.dumps(payload), offset=48, limit=100)["data"]
                self.assertIn("hasMore", data)
                self.assertEqual(([], 0, False, -1), (data["items"], data["rawCount"], data["hasMore"], data["nextOffset"]))

    def test_search_flattens_video_hubs_and_drops_items_without_native_ids(self):
        result = self.decode("search", "search.json")
        self.assertEqual([item["itemId"] for item in result["data"]["items"]], ["1", "100"])
        self.assertEqual(result["data"]["totalSize"], 2)

    def test_detail_preserves_exact_part_selection_and_streams(self):
        detail = self.decode("detail", "movie_detail.json")["data"]
        self.assertEqual(detail["item"]["summary"], "A sample movie summary.")
        self.assertEqual(len(detail["versions"]), 2)
        version = detail["versions"][1]
        self.assertEqual((version["mediaIndex"], version["partIndex"], version["mediaId"], version["partId"]), (1, 0, "2002", "3002"))
        self.assertEqual(version["versionId"], "plex:server-a:1:2002:3002")
        self.assertEqual(version["audio"][0]["codec"], "aac")
        self.assertEqual(detail["markers"][0], {"type": "intro", "startMs": 30000, "endMs": 90000, "isFinal": False})
        self.assertFalse(detail["item"]["watched"])

    def test_detail_preserves_final_skip_marker_and_discards_invalid_intervals(self):
        markers = self.decode("detail", "detail_extras.json")["data"]["markers"]
        self.assertEqual(markers, [
            {"type": "intro", "startMs": 30000, "endMs": 90000, "isFinal": False},
            {"type": "credits", "startMs": 7100000, "endMs": 7200000, "isFinal": True},
        ])

    def test_detail_normalizes_verified_cast_directors_and_playable_extras(self):
        detail = self.decode("detail", "detail_extras.json")["data"]
        self.assertIn("cast", detail)
        self.assertEqual(detail["cast"], [{"sourceId": "plex:server-a", "personId": "7", "name": "Fixture Actor", "role": "The Guide", "department": "Acting", "thumbKey": "/library/metadata/7/thumb/1000"}])
        self.assertEqual(detail["crew"], [{"sourceId": "plex:server-a", "personId": "8", "name": "Fixture Director", "role": "", "department": "Directing", "thumbKey": ""}])
        self.assertEqual([item["itemId"] for item in detail["extras"]], ["501", "502"])
        self.assertEqual([item["type"] for item in detail["extras"]], ["movie", "movie"])
        self.assertEqual([item["extraType"] for item in detail["extras"]], ["trailer", "featurette"])
        self.assertTrue(all(item["sourceId"] == "plex:server-a" for item in detail["extras"]))
        self.assertNotIn("unsafe-image-token", json.dumps(detail))

    def test_clip_detail_resolves_its_own_native_media_part(self):
        result = self.decode("detail", "clip_detail.json")
        self.assertTrue(result["ok"])
        detail = result["data"]
        self.assertEqual((detail["item"]["itemId"], detail["item"]["type"], detail["item"]["extraType"]), ("501", "movie", "trailer"))
        plan = self.call("PlexDirectPlan", detail, 0, 0, self.session())
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["url"], "https://plex.example.test/library/parts/3501/file.mp4")
        self.assertEqual(plan["itemId"], "501")
        self.assertEqual(plan["versionId"], "plex:server-a:501:2501:3501")

    def test_detail_bounds_credit_and_extra_arrays(self):
        raw = {"ratingKey": "1", "type": "movie", "Role": [{"id": index, "tag": "Actor"} for index in range(60)], "Director": [{"id": index, "tag": "Director"} for index in range(60)], "Extras": {"Metadata": [{"ratingKey": str(index), "type": "clip", "subtype": "trailer"} for index in range(60)]}}
        detail = self.decode("detail", body=json.dumps({"MediaContainer": {"Metadata": [raw]}}))["data"]
        self.assertIn("cast", detail)
        self.assertEqual(len(detail["cast"]), 32)
        self.assertEqual(len(detail["crew"]), 32)
        self.assertEqual(len(detail["extras"]), 24)

    def test_owned_items_keep_exact_guid_ids_without_case_collision(self):
        item = self.decode("detail", "detail_extras.json")["data"]["item"]
        self.assertIn("guids", item)
        self.assertEqual(item["guids"], ["plex://movie/global-movie-a", "tmdb://603", "imdb://tt0133093", "tvdb://123"])
        self.assertNotIn("unsafe-guid-token", json.dumps(item))
        legacy = self.decode("library_items", body='{"MediaContainer":{"Metadata":[{"ratingKey":"2","type":"movie","guid":"plex://movie/legacy-a"}]}}')["data"]["items"][0]
        self.assertEqual(legacy["guids"], ["plex://movie/legacy-a"])

    def test_owned_guid_arrays_are_unique_and_bounded(self):
        raw = {"ratingKey": "1", "type": "movie", "Guid": [{"id": "tmdb://" + str(index)} for index in range(40)]}
        item = self.decode("search", body=json.dumps({"MediaContainer": {"Metadata": [raw]}}))["data"]["items"][0]
        self.assertIn("guids", item)
        self.assertEqual(item["guids"], ["tmdb://" + str(index) for index in range(16)])

    def test_lowercase_media_is_supported_and_bad_metadata_is_bounded(self):
        result = self.decode("detail", body='{"MediaContainer":{"Metadata":[{"ratingKey":"9","type":"movie","title":"Lowercase","media":[{"id":"m9","Part":[{"id":"p9","key":"/library/parts/p9/file.mp4","container":"mp4"}]}]}]}}')
        self.assertEqual(len(result["data"]["versions"]), 1)
        for body in ("bad-json", "[]", '{"MediaContainer":{"Metadata":"wrong"}}', '{"MediaContainer":{"Metadata":[]}}'):
            with self.subTest(body=body):
                self.assertFalse(self.decode("detail", body=body)["ok"])

    def test_direct_plan_uses_selected_part_and_header_auth(self):
        detail = self.decode("detail", "movie_detail.json")["data"]
        plan = self.call("PlexDirectPlan", detail, 1, 0, self.session())
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["url"], "https://plex.example.test/library/parts/3002/file.mp4")
        self.assertEqual(plan["streamFormat"], "mp4")
        self.assertEqual(plan["headers"]["X-Plex-Token"], "fixture-only-secret")
        self.assertEqual(plan["versionId"], "plex:server-a:1:2002:3002")
        self.assertEqual(plan["audioCodec"], "aac")
        self.assertNotIn("fixture-only-secret", plan["url"])

    def test_direct_plan_rejects_missing_selection_unsafe_path_and_source_mismatch(self):
        detail = self.decode("detail", "movie_detail.json")["data"]
        missing = self.call("PlexDirectPlan", detail, 5, 0, self.session())
        detail["versions"][1]["partKey"] = "https://other.example.test/secret"
        unsafe = self.call("PlexDirectPlan", detail, 1, 0, self.session())
        mismatch = self.call("PlexDirectPlan", detail, 0, 0, self.session(sourceId="plex:server-b"))
        self.assertFalse(missing["ok"])
        self.assertFalse(unsafe["ok"])
        self.assertFalse(mismatch["ok"])

    def test_transcode_builder_uses_one_session_and_roku_capability_profile(self):
        params = {"itemId": "1", "mediaIndex": 1, "partIndex": 0, "transcodeSessionId": "fixture-playback", "audioStreamId": "4005", "maxVideoBitrate": 8000, "videoResolution": "1920x1080", "profileExtra": "add-transcode-target(type=videoProfile&context=streaming&protocol=hls&container=mpegts&videoCodec=h264&audioCodec=aac)", "startPositionMs": 90500}
        decision = self.request("transcode_decision", params)
        start = self.request("transcode_start", params)
        for request in (decision, start):
            self.assertTrue(request["ok"])
            query = parse_qs(urlsplit(request["url"]).query)
            self.assertEqual(query["session"], ["fixture-playback"])
            self.assertEqual(query["directPlay"], ["0"])
            self.assertEqual(query["directStream"], ["1"])
            self.assertEqual(query["mediaIndex"], ["1"])
            self.assertEqual(query["maxVideoBitrate"], ["8000"])
            self.assertNotIn("videoBitrate", query)
            self.assertNotIn("X-Plex-Token", query)
        self.assertEqual(parse_qs(urlsplit(decision["url"]).query)["protocol"], ["*"])
        self.assertEqual(parse_qs(urlsplit(start["url"]).query)["protocol"], ["hls"])
        self.assertEqual(parse_qs(urlsplit(start["url"]).query)["offset"], ["0"])
        self.assertFalse(self.request("transcode_start", {"itemId": "1"})["ok"])

    def test_decision_refusal_is_explicit_and_does_not_echo_server_message(self):
        copy = self.decode("transcode_decision", "decision-copy.json")
        self.assertEqual(copy["data"]["delivery"], "direct_stream")
        refusal = self.decode("transcode_decision", body='{"MediaContainer":{"generalDecisionCode":2001,"generalDecisionText":"secret signed URL"}}')
        self.assertFalse(refusal["ok"])
        self.assertEqual(refusal["errorCode"], "plex_decision_refused")
        self.assertNotIn("secret signed URL", json.dumps(refusal))

    def test_timeline_and_watched_requests_use_native_id_and_headers(self):
        timeline = self.request("timeline", {"itemId": "101", "state": "paused", "positionMs": 900500, "durationMs": 2700000})
        query = parse_qs(urlsplit(timeline["url"]).query)
        self.assertEqual(query["ratingKey"], ["101"])
        self.assertEqual(query["time"], ["900500"])
        self.assertEqual(query["duration"], ["2700000"])
        self.assertEqual(query["state"], ["paused"])
        for action, path in (("scrobble", "/:/scrobble"), ("unscrobble", "/:/unscrobble")):
            with self.subTest(action=action):
                request = self.request(action, {"itemId": "101"})
                self.assertTrue(request["ok"])
                self.assertEqual(urlsplit(request["url"]).path, path)
                self.assertEqual(parse_qs(urlsplit(request["url"]).query)["key"], ["101"])
                self.assertEqual(parse_qs(urlsplit(request["url"]).query)["identifier"], ["com.plexapp.plugins.library"])
                self.assertEqual(request["headers"]["X-Plex-Token"], "fixture-only-secret")
        self.assertFalse(self.request("timeline", {"itemId": "1", "state": "anything"})["ok"])

    def test_watched_mutations_accept_empty_success_acknowledgements(self):
        for action in ("scrobble", "unscrobble"):
            with self.subTest(action=action):
                self.assertEqual(self.decode(action, body=""), {"ok": True, "data": {}})
                self.assertFalse(self.request(action, {"itemId": ""})["ok"])

    def test_hls_plan_has_authenticated_manifest_and_stream_decision_fields(self):
        detail = self.decode("detail", "movie_detail.json")["data"]
        params = {"itemId": "1", "transcodeSessionId": "fixture-playback", "mediaIndex": 1, "partIndex": 0, "profileExtra": "fixture-profile", "startPositionMs": 0}
        request = self.request("transcode_start", params)
        plan = self.call("PlexTranscodePlan", request, self.session(), detail, 1, 0)
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["streamFormat"], "hls")
        self.assertEqual(plan["headers"]["X-Plex-Token"], "fixture-only-secret")
        self.assertEqual(plan["itemId"], "1")
        self.assertEqual(plan["versionId"], detail["versions"][1]["versionId"])
        self.assertEqual(plan["delivery"], "transcode")
        self.assertEqual(plan["timelineOffsetMs"], 0)
        self.assertFalse(self.call("PlexTranscodePlan", {"ok": False}, self.session(), detail, 1, 0)["ok"])

    def test_hls_resume_uses_canonical_manifest_and_native_client_position(self):
        detail = self.decode("detail", "movie_detail.json")["data"]
        detail["item"]["resumeMs"] = 90500
        request = self.request("transcode_start", {"itemId": "1", "transcodeSessionId": "fixture-playback", "mediaIndex": 1, "partIndex": 0, "profileExtra": "fixture-profile", "startPositionMs": 90500})
        plan = self.call("PlexTranscodePlan", request, self.session(), detail, 1, 0)
        self.assertEqual(parse_qs(urlsplit(request["url"]).query)["offset"], ["0"])
        self.assertEqual(plan["startPositionMs"], 90500)
        self.assertEqual(plan["timelineOffsetMs"], 0)
        self.assertFalse(plan["relativeTimeline"])

    def test_hls_plan_rejects_a_request_for_a_different_item_or_file(self):
        detail = self.decode("detail", "movie_detail.json")["data"]
        for changes in ({"itemId": "2"}, {"mediaIndex": 0}):
            request = self.request("transcode_start", {"itemId": "1", "transcodeSessionId": "fixture-playback", "mediaIndex": 1, "partIndex": 0, "profileExtra": "fixture-profile", **changes})
            self.assertFalse(self.call("PlexTranscodePlan", request, self.session(), detail, 1, 0)["ok"])

    def test_hls_plan_rejects_a_server_offset_that_would_shift_absolute_progress(self):
        detail = self.decode("detail", "movie_detail.json")["data"]
        request = self.request("transcode_start", {"itemId": "1", "transcodeSessionId": "fixture-playback", "mediaIndex": 1, "partIndex": 0, "profileExtra": "fixture-profile"})
        if "&offset=0" in request["url"]:
            request["url"] = request["url"].replace("&offset=0", "&offset=90")
        else:
            request["url"] += "&offset=90"
        self.assertFalse(self.call("PlexTranscodePlan", request, self.session(), detail, 1, 0)["ok"])

    def test_pin_iso_expiry_keeps_millisecond_precision(self):
        result = self.decode("pin_start", body='{"id":42,"code":"ABCD","expiresAt":"2030-01-01T00:01:01Z","expiresIn":120}', nowMs=1893456000000)
        self.assertEqual(result["data"]["expiresAtMs"], 1893456061000)

    def test_oversized_catalog_is_capped_and_missing_fields_stay_readable(self):
        payload = {"MediaContainer": {"totalSize": 1000, "offset": 48, "Metadata": [{"ratingKey": str(i), "type": "movie"} for i in range(100)]}}
        result = self.decode("library_items", body=json.dumps(payload), offset=48, limit=999)
        self.assertEqual(len(result["data"]["items"]), 48)
        self.assertEqual(result["data"]["totalSize"], 1000)
        self.assertEqual(result["data"]["offset"], 48)
        self.assertEqual(result["data"]["items"][0]["summary"], "")

    def test_missing_media_ids_do_not_create_fake_stable_versions(self):
        payload = '{"MediaContainer":{"Metadata":[{"ratingKey":"9","type":"movie","Media":[{"Part":[{"key":"/library/parts/9/file.mp4"}]}]}]}}'
        detail = self.decode("detail", body=payload)["data"]
        self.assertEqual(detail["versions"], [])


if __name__ == "__main__":
    unittest.main()
