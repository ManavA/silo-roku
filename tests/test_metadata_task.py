"""Metadata worker jobs preserve session scope and public catalog identity."""

import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/metadata"
FILES = [ROOT / "source/core/RuntimeIdentity.brs", ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/adapters/PlexAdapter.brs",
         ROOT / "source/adapters/SiloAdapter.brs",
         ROOT / "source/adapters/MetadataAdapter.brs"]

# Standalone BrightScript has no Roku device/registry/HTTP implementation.
# Replace these IO boundaries while executing the app's complete worker path
# and the real timeout policy. Requests remain synthetic and never leave here.
BOUNDARIES = '''
function MetadataRequestConfig(version as String) as Object
    return {baseUrl:m.fixtureMetadataUrl,appVersion:version}
end function

function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function

function LoadSession(provider as String) as Object
    return m.fixtureSession
end function

function TaskDeviceSession(provider as String, session as Object) as Object
    return session
end function

function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    m.requests.Push(request)
    m.timeouts.Push(HttpTimeoutMs(request, timeoutMs))
    if m.changeRevision then m.fixtureRevision = m.fixtureRevision + 1
    return m.fixtureResponse
end function

function RunMetadataJob(provider as String, action as String, session as Object, params as Object, scope as Object, response as Object, changeRevision as Boolean, metadataUrl as String) as Object
    m.fixtureMetadataUrl = metadataUrl
    m.fixtureSession = session
    m.fixtureResponse = response
    m.fixtureRevision = 0
    m.changeRevision = changeRevision
    m.requests = []
    m.timeouts = []
    job = MergeSessionPatch(scope, {provider:provider, action:action, params:params})
    m.top = {job:job, result:invalid}
    runJob()
    return {outcome:m.top.result, requests:m.requests, timeouts:m.timeouts}
end function
'''


class MetadataTaskTests(unittest.TestCase):
    def session(self, provider="plex", **changes):
        if provider == "plex":
            value = {"sourceId": "plex:fixture-server", "profileId": "", "clientId": "fixture-client",
                     "baseUrl": "https://provider-private.example.test",
                     "accountToken": "synthetic-private-account-token",
                     "token": "synthetic-private-server-token", "appVersion": "0.1.0"}
        else:
            value = {"sourceId": "silo:fixture-server", "profileId": "fixture-profile",
                     "baseUrl": "https://provider-private.example.test",
                     "accessToken": "synthetic-private-access-token",
                     "refreshToken": "synthetic-private-refresh-token",
                     "profileToken": "synthetic-private-profile-token", "appVersion": "0.1.0"}
        value.update(changes)
        return value

    def run_job(self, action, params=None, *, provider="plex", session=None, scope=None,
                response=None, change_revision=False, metadata_url="https://metadata.example"):

        if session is None:
            session = self.session(provider)
        if scope is None:
            scope = {"sourceId": session.get("sourceId", ""),
                     "profileId": session.get("profileId", ""),
                     "generation": 7, "requestId": "fixture-request"}
        if response is None:
            fixture = "ava.json" if action == "ava_recommend" else "home_rows.json"
            if action == "discover_trending":
                fixture = "trending.json"
            response = {"ok": True, "body": (FIXTURES / fixture).read_text(), "statusCode": 200}
        with tempfile.TemporaryDirectory(prefix="silo-metadata-worker-") as directory:
            temporary = Path(directory)
            worker = temporary / "ApiTask.brs"
            worker_source = (ROOT / "components/ApiTask.brs").read_text()
            worker_source = worker_source.replace("function TaskDeviceSession(",
                                                  "function UnusedDeviceSession(", 1)
            worker.write_text(worker_source)
            http = temporary / "HttpTimeout.brs"
            timeout = re.search(r"function HttpTimeoutMs\(.*?^end function",
                                (ROOT / "source/network/Http.brs").read_text(), re.S | re.M)
            self.assertIsNotNone(timeout, "the real bounded HTTP timeout policy is required")
            http.write_text(timeout.group())
            boundary = temporary / "boundaries.brs"
            boundary.write_text(BOUNDARIES)
            return run_function([*FILES, ROOT / "components/TaskSiloReplan.brs", worker, http, boundary], "RunMetadataJob",
                                [provider, action, session, params or {}, scope, response, change_revision, metadata_url],
                                root=temporary)

    def test_unconfigured_metadata_never_reaches_transport(self):
        for action in ("home_rows", "service_catalog", "discover_trending", "ava_recommend", "metadata_artwork"):
            with self.subTest(action=action):
                result = self.run_job(action, {"prompt":"Moon films","type":"movie","itemId":"native-1","itemType":"movie"}, metadata_url="")
                self.assertEqual("metadata_disabled", result["outcome"]["errorCode"])
                self.assertEqual([], result["requests"])
        for url in ("https://user:pass@invalid.example", "http://invalid.example", "https://invalid.example?key=secret"):
            result = self.run_job("home_rows",metadata_url=url)
            self.assertEqual("invalid_server",result["outcome"]["errorCode"])
            self.assertEqual([],result["requests"])

    def test_task_xml_loads_the_metadata_adapter(self):
        component = ET.parse(ROOT / "components/ApiTask.xml").getroot()
        scripts = [node.get("uri") for node in component.findall("script")]
        self.assertIn("pkg:/source/adapters/MetadataAdapter.brs", scripts)

    def test_compact_refresh_accepts_no_content_only_for_current_home_refresh(self):
        response = {"ok": True, "body": "", "statusCode": 204}
        result = self.run_job("home_rows", {"mode": "refresh"}, response=response)
        self.assertTrue(result["outcome"]["ok"])
        self.assertTrue(result["outcome"]["data"]["refreshQueued"])
        stale = self.run_job("home_rows", {"mode": "refresh"}, response=response, change_revision=True)
        self.assertEqual("session_changed", stale["outcome"]["errorCode"])
        live = self.run_job("home_rows", {"mode": "live"}, response=response)
        self.assertFalse(live["outcome"]["ok"])

    def test_home_rows_dispatches_for_both_active_providers(self):
        for provider in ("plex", "silo"):
            with self.subTest(provider=provider):
                result = self.run_job("home_rows", {"mode": "cache_only"}, provider=provider)
                self.assertTrue(result["outcome"]["ok"])
                self.assertEqual("/v1/catalog/home/rows", urlsplit(result["requests"][0]["url"]).path)
                self.assertEqual([10000], result["timeouts"])
                self.assertEqual("synthetic-picks", result["outcome"]["data"]["rows"][0]["id"])

    def test_trending_dispatches_as_public_metadata_for_both_active_providers(self):
        for provider in ("plex", "silo"):
            with self.subTest(provider=provider):
                result = self.run_job("discover_trending", {"page": 1}, provider=provider)
                self.assertTrue(result["outcome"]["ok"])
                request = result["requests"][0]
                self.assertEqual("https://metadata.example/v1/trending/all/week?page=1", request["url"])
                self.assertEqual([10000], result["timeouts"])
                self.assertEqual("trending-week", result["outcome"]["data"]["rows"][0]["id"])
                self.assertEqual(2, result["outcome"]["data"]["nextPage"])
                self.assertEqual(self.session(provider)["sourceId"], result["outcome"]["sourceId"])
                self.assertFalse(result["outcome"]["data"]["rows"][0]["items"][0]["canPlay"])
                self.assertNotIn("synthetic-private-", json.dumps(request))
                self.assertNotIn("provider-private.example.test", json.dumps(request))

    def test_trending_preserves_source_guards_and_safe_error_codes(self):
        stale = self.run_job("discover_trending", change_revision=True)
        self.assertEqual("session_changed", stale["outcome"]["errorCode"])
        missing = self.run_job("discover_trending", scope={"sourceId": "", "profileId": ""})
        self.assertEqual("source_required", missing["outcome"]["errorCode"])
        self.assertEqual([], missing["requests"])
        malformed = self.run_job("discover_trending", response={"ok": True, "body": '{"error":"synthetic-private-body"}'})
        self.assertEqual("invalid_response", malformed["outcome"]["errorCode"])
        self.assertNotIn("synthetic-private-body", json.dumps(malformed))

    def test_service_catalog_uses_adapter_slug_validation_and_refresh_timeout(self):
        result = self.run_job("service_catalog", {"slug": "synthetic-service", "mode": "refresh"})
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual("/v1/catalog/service/synthetic-service", urlsplit(result["requests"][0]["url"]).path)
        self.assertEqual([12000], result["timeouts"])
        refused = self.run_job("service_catalog", {"slug": "../private"})
        self.assertEqual("invalid_request", refused["outcome"]["errorCode"])
        self.assertEqual([], refused["requests"])

    def test_ava_uses_registered_source_for_candidates_and_thirty_second_timeout(self):
        source = self.session()["sourceId"]
        candidate = {"sourceId": source, "itemId": "fixture-owned-501", "title": "Synthetic Moon",
                     "type": "movie", "guids": ["tmdb://101"], "owned": True,
                     "token": "synthetic-private-candidate-token", "url": "https://provider-private.example.test/file"}
        params = {"prompt": "Moon films", "sourceId": "plex:caller-spoofed",
                  "baseUrl": "https://provider-private.example.test",
                  "headers": {"X-Plex-Token": "synthetic-private-param-token"},
                  "libraryCandidates": [candidate, {**candidate, "sourceId": "plex:another-source"}]}
        result = self.run_job("ava_recommend", params)
        self.assertTrue(result["outcome"]["ok"])
        request = result["requests"][0]
        self.assertEqual("/v1/ava/recommendations", urlsplit(request["url"]).path)
        self.assertEqual([30000], result["timeouts"])
        body = json.loads(request["body"])
        self.assertEqual([{"title": "Synthetic Moon", "mediaType": "movie", "tmdbId": "101", "genres": []}],
                         body["libraryCandidates"])
        self.assertNotIn("fixture-owned-501", request["body"])
        self.assertNotIn("sourceId", request["body"])
        self.assertEqual("A few synthetic choices.", result["outcome"]["data"]["reply"])

    def test_ava_requires_a_connected_registered_session(self):
        for provider, changes in (("plex", {"token": ""}), ("silo", {"accessToken": ""})):
            with self.subTest(provider=provider):
                result = self.run_job("ava_recommend", {"prompt": "Moon films"},
                                      provider=provider, session=self.session(provider, **changes))
                self.assertEqual("auth_required", result["outcome"]["errorCode"])
                self.assertEqual([], result["requests"])

    def test_metadata_actions_require_an_explicit_source_scope(self):
        for action, params in (("home_rows", {}), ("service_catalog", {"slug": "synthetic-service"}),
                               ("ava_recommend", {"prompt": "Moon films"})):
            result = self.run_job(action, params, scope={"sourceId": "", "profileId": ""})
            self.assertEqual("source_required", result["outcome"]["errorCode"])
            self.assertEqual([], result["requests"])

    def test_stale_source_and_profile_jobs_never_start_metadata_requests(self):
        for scope in ({"sourceId": "silo:other", "profileId": "fixture-profile"},
                      {"sourceId": "silo:fixture-server", "profileId": "other-profile"},
                      {"sourceId": "silo:fixture-server", "profileId": ""},
                      {"sourceId": "silo:fixture-server"}):
            result = self.run_job("home_rows", provider="silo", scope=scope)
            self.assertEqual("session_changed", result["outcome"]["errorCode"])
            self.assertEqual([], result["requests"])

    def test_scope_change_during_metadata_io_discards_the_response(self):
        result = self.run_job("home_rows", change_revision=True)
        self.assertEqual("session_changed", result["outcome"]["errorCode"])
        self.assertNotIn("data", result["outcome"])

    def test_plex_owner_scope_requires_an_explicit_string_profile(self):
        for profile in (None, False, 0):
            result = self.run_job("home_rows", scope={"sourceId": "plex:fixture-server", "profileId": profile})
            self.assertFalse(result["outcome"]["ok"])
            self.assertEqual("session_changed", result["outcome"]["errorCode"])
            self.assertEqual([], result["requests"])

    def test_results_keep_envelope_scope_and_global_items_unplayable(self):
        for action, params in (("home_rows", {}), ("service_catalog", {"slug": "synthetic-service"}),
                               ("ava_recommend", {"prompt": "Moon films"})):
            result = self.run_job(action, params)
            outcome = result["outcome"]
            self.assertTrue(outcome["ok"])
            self.assertEqual("plex", outcome["provider"])
            self.assertEqual("plex:fixture-server", outcome["sourceId"])
            self.assertEqual("", outcome["profileId"])
            self.assertEqual(7, outcome["generation"])
            self.assertEqual("fixture-request", outcome["requestId"])
            self.assertEqual(action, outcome["action"])
            items = outcome["data"]["items"] if action == "ava_recommend" else outcome["data"]["rows"][0]["items"]
            for item in items:
                self.assertEqual("metadata", item["provider"])
                self.assertTrue(item["catalogId"].startswith("metadata:"))
                self.assertFalse(item["canPlay"])
                self.assertFalse(item["owned"])
                self.assertNotIn("itemId", item)
                self.assertNotIn("sourceId", item)

    def test_provider_credentials_and_origins_never_enter_metadata_requests_or_results(self):
        for provider in ("plex", "silo"):
            result = self.run_job("ava_recommend", {"prompt": "Moon films"}, provider=provider)
            self.assertTrue(result["outcome"]["ok"])
            wire = json.dumps(result)
            self.assertNotIn("synthetic-private-", wire)
            self.assertNotIn("provider-private.example.test", wire)
            self.assertNotIn("must-be-omitted", wire)
            headers = result["requests"][0]["headers"]
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("X-Plex-Token", headers)
            self.assertNotIn("X-Profile-Token", headers)

    def test_catalog_results_keep_adapter_row_and_item_bounds(self):
        items = [{"tmdbId": str(index + 1), "type": "movie", "title": f"Synthetic {index}"}
                 for index in range(60)]
        body = {"rows": [{"id": f"synthetic-row-{index}", "title": "Synthetic row", "items": items}
                         for index in range(20)]}
        result = self.run_job("home_rows", response={"ok": True, "body": json.dumps(body)})
        self.assertTrue(result["outcome"]["ok"])
        rows = result["outcome"]["data"]["rows"]
        self.assertEqual(12, len(rows))
        self.assertTrue(all(len(row["items"]) == 24 for row in rows))

    def test_ava_results_keep_requested_limit_and_reply_bounds(self):
        body = {"reply": "x" * 500,
                "matches": [{"tmdbId": str(index + 1), "mediaType": "movie", "title": f"Synthetic {index}"}
                            for index in range(100)]}
        result = self.run_job("ava_recommend", {"prompt": "Moon films", "limit": 3},
                              response={"ok": True, "body": json.dumps(body)})
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(3, len(result["outcome"]["data"]["items"]))
        self.assertEqual(180, len(result["outcome"]["data"]["reply"]))

    def test_transport_and_decode_errors_do_not_echo_response_body(self):
        for response, expected in (({"ok": False, "errorCode": "network_timeout", "body": "synthetic-private-body"}, "network_timeout"),
                                   ({"ok": True, "body": '{"error":"synthetic-private-body"}'}, "invalid_response")):
            result = self.run_job("home_rows", response=response)
            self.assertEqual(expected, result["outcome"]["errorCode"])
            self.assertNotIn("synthetic-private-body", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
