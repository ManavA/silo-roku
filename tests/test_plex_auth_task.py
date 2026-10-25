"""Run Plex PIN linking through the actual worker and serialized sessions."""

import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlsplit

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/adapters/PlexAdapter.brs",
         ROOT / "source/adapters/PlexWatchlist.brs"]

# Replace device, registry and HTTP IO only. The complete worker dispatch,
# adapter, session decoder and public results execute without live requests.
BOUNDARIES = '''
function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function

function LoadSession(provider as String) as Object
    return DecodeStoredSession(m.fixtureSessionJson)
end function

function SaveSession(provider as String, session as Object, revision as Integer) as Boolean
    if revision <> m.fixtureRevision or m.failWrite then return false
    m.fixtureSessionJson = FormatJson(session)
    m.writes = m.writes + 1
    return true
end function

function ReplaceSession(provider as String, session as Object, revision as Integer) as Boolean
    if not SaveSession(provider, session, revision) then return false
    m.fixtureRevision = m.fixtureRevision + 1
    return true
end function

function TaskDeviceSession(provider as String, session as Object) as Object
    clientId="fixture-client"
    if m.missingClient then clientId=""
    return MergeSessionPatch(session, {clientId:clientId, deviceId:"fixture-device", osVersion:"15.3.4"})
end function

function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    m.requests.Push(request)
    if m.throwHttp then throw "fixture-private-token https://private.example.test"
    if m.changeRevision then m.fixtureRevision = m.fixtureRevision + 1
    return m.responses.Shift()
end function

function RunPlexAuthJobs(session as Object, jobs as Object, responses as Object, failWrite as Boolean, changeRevision as Boolean, missingClient as Boolean, throwHttp as Boolean, publish as Boolean) as Object
    m.missingClient=missingClient
    m.throwHttp=throwHttp
    m.fixtureSessionJson = FormatJson(session)
    m.fixtureRevision = 0
    m.responses = responses
    m.requests = []
    m.outcomes = []
    m.writes = 0
    m.failWrite = failWrite
    m.changeRevision = changeRevision
    for each job in jobs
        if publish
            scoped=MergeSessionPatch({provider:"plex",sourceId:"",profileId:"",generation:3,requestId:"fixture-worker"},job)
            m.top={job:scoped,result:invalid}
            runJob()
            outcome=m.top.result
        else
            outcome = ExecuteApiAction("plex", job.action, TaskValue(job,"params",{}), {sourceId:"", profileId:""})
        end if
        m.outcomes.Push(outcome)
        if not outcome.ok then exit for
    end for
    return {outcomes:m.outcomes, requests:m.requests, savedSession:LoadSession("plex"), writes:m.writes}
end function
'''


class PlexAuthTaskTests(unittest.TestCase):
    def run_auth(self, jobs, responses, *, session=None, fail_write=False, change_revision=False,
                 missing_client=False, throw_http=False, publish=False):
        with tempfile.TemporaryDirectory(prefix="silo-plex-auth-") as directory:
            temporary = Path(directory)
            worker = temporary / "ApiTask.brs"
            source = (ROOT / "components/ApiTask.brs").read_text()
            source = source.replace("function TaskDeviceSession(", "function UnusedDeviceSession(", 1)
            worker.write_text(source)
            decoder = re.search(r"function DecodeStoredSession\(.*?^end function",
                                (ROOT / "source/auth/SessionStore.brs").read_text(), re.S | re.M)
            self.assertIsNotNone(decoder)
            boundary = temporary / "boundaries.brs"
            boundary.write_text(decoder.group() + "\n" + BOUNDARIES)
            return run_function([*FILES, worker, boundary], "RunPlexAuthJobs",
                                [session or {}, jobs, responses, fail_write, change_revision,
                                 missing_client, throw_http, publish],
                                root=temporary)

    def response(self, body):
        return {"ok": True, "statusCode": 200, "body": json.dumps(body)}

    def poll(self, response, **options):
        return self.run_auth([{"action": "pin_poll", "params": {"pinId": "42"}}],
                             [response], **options)

    def test_pin_requests_use_the_shared_platform_timeout_policy(self):
        for action, params, timeout in (("pin_start", {}, 8000),
                                        ("pin_poll", {"pinId": "42"}, 5000)):
            with self.subTest(action=action):
                request = run_function(FILES, "BuildPlexRequest",
                                       [action, {"clientId": "fixture-client"}, params])
                actual = run_function(ROOT / "source/network/Http.brs", "HttpTimeoutMs", [request, 0])
                self.assertEqual(timeout, actual)

    def test_pin_transport_failure_exposes_only_bounded_numeric_status(self):
        result = self.run_auth([{"action": "pin_start"}],
                               [{"ok": False, "statusCode": -60, "errorCode": "network_error",
                                 "body": "private-token https://private.example"}])
        self.assertEqual([{"ok": False, "errorCode": "network_error", "transportStatus": -60, "authPhase": "http"}],
                         result["outcomes"])
        self.assertNotIn("private", json.dumps(result["outcomes"]))

    def test_pin_poll_requests_current_approval_state_without_cached_pending_replies(self):
        result = self.poll(self.response({"id": 42, "authToken": None}))
        request = result["requests"][0]
        self.assertEqual("no-cache", request["headers"].get("Cache-Control"))
        self.assertEqual("no-cache", request["headers"].get("Pragma"))
        self.assertNotIn("X-Plex-Token", request["headers"])
        self.assertEqual({"ok": True, "data": {"state": "pending"}}, result["outcomes"][0])

    def test_account_lookup_write_failure_reports_storage_error_and_preserves_saved_account(self):
        previous = {"accountToken": "synthetic-account-token"}
        for action in ("user", "watchlist"):
            with self.subTest(action=action):
                result = self.run_auth([{"action": action}],
                                       [self.response({"id": 7, "username": "Fixture Account"})],
                                       session=previous, fail_write=True)
                self.assertEqual([{"ok": False, "errorCode": "storage_error"}], result["outcomes"])
                self.assertEqual(previous, result["savedSession"])
                self.assertEqual(0, result["writes"])
                self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))

    def test_revision_change_during_account_lookup_preserves_saved_account(self):
        previous = {"accountToken": "synthetic-account-token"}
        for action in ("user", "watchlist"):
            with self.subTest(action=action):
                result = self.run_auth([{"action": action}],
                                       [self.response({"id": 7, "username": "Fixture Account"})],
                                       session=previous, change_revision=True)
                self.assertEqual([{"ok": False, "errorCode": "session_changed"}], result["outcomes"])
                self.assertEqual(previous, result["savedSession"])
                self.assertEqual(0, result["writes"])

    def test_server_removed_pin_is_expired_without_changing_saved_account(self):
        session = {"accountToken": "synthetic-existing-token", "accountId": "old-account"}
        result = self.poll({"ok": False, "statusCode": 404, "errorCode": "not_found"}, session=session)
        self.assertEqual([{"ok": True, "data": {"state": "expired"}}], result["outcomes"])
        self.assertEqual(session, result["savedSession"])
        self.assertEqual(0, result["writes"])

    def test_non_pin_not_found_remains_an_error(self):
        result = self.run_auth([{"action": "user"}],
                               [{"ok": False, "statusCode": 404, "errorCode": "not_found"}],
                               session={"accountToken": "synthetic-account-token"})
        self.assertEqual([{"ok": False, "errorCode": "not_found"}], result["outcomes"])

    def test_new_approved_account_discards_all_previous_account_and_profile_identity(self):
        previous = {"accountToken": "synthetic-old-account-token", "accountId": "old-account",
                    "accountName": "Old Account", "profileId": "old-profile", "profileName": "Old Profile",
                    "profileToken": "synthetic-old-profile-token", "token": "synthetic-old-server-token",
                    "baseUrl": "https://old-server.example.test", "sourceId": "plex:old-server",
                    "serverName": "Old Server", "machineId": "old-server", "local": True,
                    "candidateServers": [{"token": "synthetic-old-candidate-token"}]}
        result = self.poll(self.response({"id": 42, "authToken": "synthetic-new-account-token"}),
                           session=previous)
        self.assertEqual([{"ok": True, "data": {"state": "linked"}}], result["outcomes"])
        self.assertEqual("synthetic-new-account-token", result["savedSession"]["accountToken"])
        for field in ("accountId", "accountName", "profileId", "profileName", "profileToken",
                      "token", "baseUrl", "sourceId", "serverName", "machineId"):
            with self.subTest(field=field):
                self.assertEqual("", result["savedSession"].get(field, ""))
        self.assertEqual([], result["savedSession"]["candidateServers"])
        self.assertFalse(result["savedSession"]["local"])
        self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))

    def test_pin_account_discovery_selection_and_restart_use_serialized_sessions(self):
        jobs = [{"action": "pin_start"}, {"action": "pin_poll", "params": {"pinId": "42"}},
                {"action": "user"}, {"action": "resources"},
                {"action": "select_server", "params": {"machineId": "fixture-server"}},
                {"action": "session_status"}]
        resources = [{"clientIdentifier": "fixture-server", "name": "Fixture Server", "provides": "server",
                      "accessToken": "synthetic-server-token", "owned": True,
                      "connections": [{"uri": "https://server.example.test", "local": False, "relay": False}]}]
        responses = [self.response({"id": 42, "code": "ABCD", "expiresIn": 120}),
                     self.response({"id": 42, "authToken": "synthetic-account-token"}),
                     self.response({"id": 7, "username": "Fixture Account"}), self.response(resources),
                     self.response({"MediaContainer": {"machineIdentifier": "fixture-server"}})]
        result = self.run_auth(jobs, responses)
        self.assertEqual(6, len(result["outcomes"]))
        self.assertTrue(all(outcome["ok"] for outcome in result["outcomes"]))
        self.assertEqual("ABCD", result["outcomes"][0]["data"]["code"])
        restored = result["outcomes"][-1]["data"]
        self.assertTrue(restored["connected"])
        self.assertEqual("plex:fixture-server", restored["sourceId"])
        self.assertEqual("Fixture Account", restored["accountName"])
        self.assertEqual("7", result["savedSession"]["accountId"])
        self.assertEqual("synthetic-account-token", result["savedSession"]["accountToken"])
        self.assertEqual("synthetic-server-token", result["savedSession"]["token"])
        requests = result["requests"]
        self.assertEqual(["/api/v2/pins", "/api/v2/pins/42", "/api/v2/user", "/api/v2/resources", "/identity"],
                         [urlsplit(request["url"]).path for request in requests])
        self.assertTrue(all(request["headers"]["X-Plex-Client-Identifier"] == "fixture-client"
                            for request in requests))
        self.assertTrue(all("X-Plex-Token" not in request["headers"] for request in requests[:2]))
        self.assertEqual(["synthetic-account-token", "synthetic-account-token", "synthetic-server-token"],
                         [request["headers"]["X-Plex-Token"] for request in requests[2:]])
        self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))

    def test_unapproved_or_failed_poll_preserves_existing_session(self):
        previous = {"accountToken": "synthetic-existing-token", "accountId": "old-account"}
        for response in (self.response({"id": 42, "authToken": None}),
                         {"ok": False, "errorCode": "network_timeout"}):
            with self.subTest(response=response):
                result = self.poll(response, session=previous)
                self.assertEqual(previous, result["savedSession"])
                self.assertEqual(0, result["writes"])

    def test_server_without_resource_token_restores_the_account_token_used_for_probe(self):
        resources = [{"clientIdentifier": "fixture-server", "name": "Fixture Server", "provides": "server",
                      "owned": True,
                      "connections": [{"uri": "https://server.example.test", "local": False, "relay": False}]}]
        result = self.run_auth([
            {"action": "resources"},
            {"action": "select_server", "params": {"machineId": "fixture-server"}},
            {"action": "session_status"},
        ], [self.response(resources),
            self.response({"MediaContainer": {"machineIdentifier": "fixture-server"}})],
            session={"accountToken": "synthetic-account-token"})
        self.assertEqual("synthetic-account-token", result["requests"][1]["headers"]["X-Plex-Token"])
        self.assertTrue(result["outcomes"][1]["data"]["connected"])
        self.assertTrue(result["outcomes"][2]["data"]["connected"])
        self.assertEqual("synthetic-account-token", result["savedSession"]["token"])
        self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))

    def test_starting_a_relink_pin_does_not_replace_the_connected_account(self):
        previous = {"accountToken": "synthetic-existing-token", "accountId": "old-account",
                    "sourceId": "plex:old-server", "token": "synthetic-old-server-token",
                    "baseUrl": "https://old-server.example.test"}
        result = self.run_auth([{"action": "pin_start"}],
                               [self.response({"id": 42, "code": "ABCD", "expiresIn": 120})],
                               session=previous)
        self.assertTrue(result["outcomes"][0]["ok"])
        self.assertEqual(previous, result["savedSession"])
        self.assertEqual(0, result["writes"])
        self.assertNotIn("X-Plex-Token", result["requests"][0]["headers"])

    def test_revision_change_during_approval_cannot_replace_the_session(self):
        previous = {"accountToken": "synthetic-existing-token"}
        result = self.poll(self.response({"id": 42, "authToken": "synthetic-new-account-token"}),
                           session=previous, change_revision=True)
        self.assertEqual([{"ok": False, "errorCode": "session_changed"}], result["outcomes"])
        self.assertEqual(previous, result["savedSession"])
        self.assertEqual(0, result["writes"])

    def test_failed_approval_write_reports_storage_error_and_preserves_saved_account(self):
        previous = {"accountToken": "synthetic-existing-token", "accountId": "old-account"}
        result = self.poll(self.response({"id": 42, "authToken": "synthetic-new-account-token"}),
                           session=previous, fail_write=True)
        self.assertEqual([{"ok": False, "errorCode": "storage_error"}], result["outcomes"])
        self.assertEqual(previous, result["savedSession"])
        self.assertEqual(0, result["writes"])
        self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))


    def test_pin_decode_failure_retains_bounded_http_status_and_preserves_account(self):
        previous = {"accountToken": "synthetic-existing-token", "sourceId": "plex:existing"}
        result = self.run_auth([{"action": "pin_start"}],
                               [self.response({"unexpected": "fixture-private-token"})], session=previous)
        self.assertEqual([{"ok": False, "errorCode": "decode_error", "authPhase": "decode",
                           "transportStatus": 200}], result["outcomes"])
        self.assertEqual(previous, result["savedSession"])
        self.assertEqual(0, result["writes"])
        self.assertNotIn("fixture-private", json.dumps(result["outcomes"]))

    def test_pin_build_failure_has_no_invented_http_status_or_request(self):
        result = self.run_auth([{"action": "pin_start"}], [], missing_client=True)
        self.assertEqual([{"ok": False, "errorCode": "client_identity_missing", "authPhase": "build"}],
                         result["outcomes"])
        self.assertEqual([], result["requests"])

    def test_worker_exception_names_worker_without_exposing_native_text(self):
        result = self.run_auth([{"action": "pin_start"}], [], throw_http=True, publish=True)
        outcome = result["outcomes"][0]
        self.assertEqual({"provider": "plex", "action": "pin_start", "sourceId": "", "profileId": "",
                          "generation": 3, "requestId": "fixture-worker", "sessionRevision": 0, "ok": False,
                          "errorCode": "task_failed", "authPhase": "worker"}, outcome)
        self.assertNotIn("fixture-private", json.dumps(outcome))

    def test_pin_decode_status_rejects_malformed_or_unbounded_numbers(self):
        for status in (True, -1000, 600, 201.5, "201", None):
            with self.subTest(status=status):
                response = {"ok": True, "statusCode": status, "body": "not-json fixture-private"}
                result = self.run_auth([{"action": "pin_start"}], [response])
                self.assertEqual([{"ok": False, "errorCode": "decode_error", "authPhase": "decode"}],
                                 result["outcomes"])



if __name__ == "__main__":
    unittest.main()
