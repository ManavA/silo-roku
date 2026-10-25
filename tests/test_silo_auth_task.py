"""Exercise Silo v2 linking and PIN selection through the actual worker."""

import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/silo"
FILES = [ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/adapters/SiloAdapter.brs",
         ROOT / "source/core/ServerUrlPolicy.brs",
         ROOT / "source/network/Http.brs"]
SESSION = {"baseUrl": "https://silo.example", "sourceId": "silo:https://silo.example",
           "accessToken": "synthetic-old-access", "refreshToken": "synthetic-old-refresh",
           "accountId": "old-account", "accountName": "Old Account",
           "profileId": "old-profile", "profileName": "Old Profile",
           "profileToken": "synthetic-old-profile"}

# Only the Roku device, HTTP and registry boundaries are replaced. Adapter,
# worker dispatch, stored JSON decoder and public outcomes execute as shipped.
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

function ClearSession(provider as String) as Boolean
    if m.failWrite then return false
    m.fixtureSessionJson = "{}"
    m.fixtureRevision = m.fixtureRevision + 1
    m.writes = m.writes + 1
    return true
end function

function TaskDeviceSession(provider as String, session as Object) as Object
    return MergeSessionPatch(session, {deviceId:"fixture-device", model:"fixture-model", osVersion:"15.3.4"})
end function

function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    m.requests.Push(request)
    if m.changeRevision then m.fixtureRevision = m.fixtureRevision + 1
    return m.responses.Shift()
end function

function RunSiloAuthJobs(session as Object, jobs as Object, responses as Object, failWrite as Boolean, changeRevision as Boolean) as Object
    m.fixtureSessionJson = FormatJson(session)
    m.fixtureRevision = 0
    m.responses = responses
    m.requests = []
    m.outcomes = []
    m.writes = 0
    m.failWrite = failWrite
    m.changeRevision = changeRevision
    for each job in jobs
        scope = TaskValue(job,"scope",{sourceId:"", profileId:""})
        outcome = ExecuteApiAction("silo", job.action, TaskValue(job,"params",{}), scope)
        m.outcomes.Push(outcome)
        if not outcome.ok then exit for
    end for
    return {outcomes:m.outcomes, requests:m.requests, savedSession:LoadSession("silo"), writes:m.writes, revision:m.fixtureRevision}
end function
'''


class SiloAuthTaskTests(unittest.TestCase):
    def run_auth(self, jobs, responses, *, session=None, fail_write=False, change_revision=False):
        with tempfile.TemporaryDirectory(prefix="silo-silo-auth-") as directory:
            temporary = Path(directory)
            worker = temporary / "ApiTask.brs"
            worker.write_text((ROOT / "components/ApiTask.brs").read_text().replace(
                "function TaskDeviceSession(", "function UnusedDeviceSession(", 1))
            http = temporary / "Http.brs"
            http.write_text((ROOT / "source/network/Http.brs").read_text().replace(
                "function HttpRequest(", "function UnusedHttpRequest(", 1))
            decoder = re.search(r"function DecodeStoredSession\(.*?^end function",
                                (ROOT / "source/auth/SessionStore.brs").read_text(), re.S | re.M)
            self.assertIsNotNone(decoder)
            boundary = temporary / "boundaries.brs"
            boundary.write_text(decoder.group() + "\n" + BOUNDARIES)
            return run_function([*FILES[:-1], http, worker, boundary], "RunSiloAuthJobs",
                                [session or {}, jobs, responses, fail_write, change_revision], root=temporary)

    def response(self, body):
        return {"ok": True, "statusCode": 200, "body": json.dumps(body)}

    def approval(self, *, full_login=False):
        body = json.loads((FIXTURES / "device_poll_approved.json").read_text())
        if full_login:
            body["profile_id"] = ""
            body["profile_token"] = ""
        return self.response(body)

    def test_missing_v2_device_capability_has_a_distinct_safe_error(self):
        result = self.run_auth([{"action": "device_capability"}],
                               [{"ok": False, "statusCode": 404, "errorCode": "not_found",
                                 "body": "private-server-address private-token"}], session=SESSION)
        self.assertEqual([{"ok": False, "errorCode": "silo_api_unavailable", "transportStatus": 404}], result["outcomes"])
        self.assertEqual(SESSION, result["savedSession"])
        self.assertEqual(0, result["writes"])
        self.assertNotIn("private-", json.dumps(result["outcomes"]))

    def test_other_missing_silo_auth_endpoints_keep_their_http_error(self):
        for action in ("device_start", "device_poll", "profiles"):
            with self.subTest(action=action):
                result = self.run_auth([{"action": action, "params": {"deviceCode": "synthetic-code"}}],
                                       [{"ok": False, "statusCode": 404, "errorCode": "not_found"}],
                                       session=SESSION)
                expected = {"ok": False, "errorCode": "not_found"}
                if action != "profiles":
                    expected["transportStatus"] = 404
                self.assertEqual([expected], result["outcomes"])

    def test_rejected_profile_pin_does_not_open_the_previous_profile(self):
        result = self.run_auth([{"action": "profile_verify", "params": {
            "profileId": "locked-profile", "profileName": "Locked", "pin": "4321"}}],
            [self.response({"valid": False, "expires_at": None})], session=SESSION)
        self.assertEqual([{"ok": False, "errorCode": "profile_pin_invalid"}], result["outcomes"])
        self.assertEqual(SESSION, result["savedSession"])
        self.assertEqual(0, result["writes"])
        self.assertNotIn("4321", json.dumps(result["outcomes"]))

    def test_approval_replaces_credentials_and_account_identity_in_one_write(self):
        result = self.run_auth([{"action": "device_poll", "params": {"deviceCode": "synthetic-code"}}],
                               [self.approval(full_login=True)], session=SESSION)
        self.assertTrue(result["outcomes"][0]["ok"])
        self.assertEqual(1, result["writes"])
        self.assertEqual(1, result["revision"])
        saved = result["savedSession"]
        self.assertEqual("synthetic-access", saved["accessToken"])
        self.assertEqual(("u1", "Test Viewer", "", "", "", ""),
                         tuple(saved[field] for field in ("accountId", "accountName", "profileId",
                                                          "profileName", "profileToken", "deviceCode")))
        data = result["outcomes"][0]["data"]
        self.assertEqual("approved", data["state"])
        self.assertEqual("", data["profileId"])
        self.assertEqual(SESSION["sourceId"], data["sourceId"])
        self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))

    def test_failed_approval_write_preserves_previous_account(self):
        result = self.run_auth([{"action": "device_poll", "params": {"deviceCode": "synthetic-code"}}],
                               [self.approval()], session=SESSION, fail_write=True)
        self.assertFalse(result["outcomes"][0]["ok"])
        self.assertEqual(SESSION, result["savedSession"])
        self.assertEqual(0, result["writes"])

    def test_scope_change_during_approval_cannot_replace_account(self):
        result = self.run_auth([{"action": "device_poll", "params": {"deviceCode": "synthetic-code"}}],
                               [self.approval()], session=SESSION, change_revision=True)
        self.assertEqual([{"ok": False, "errorCode": "session_changed"}], result["outcomes"])
        self.assertEqual(SESSION, result["savedSession"])
        self.assertEqual(0, result["writes"])

    def test_approval_missing_account_identity_cannot_replace_credentials(self):
        approved = json.loads(self.approval()["body"])
        del approved["tokens"]["user"]
        result = self.run_auth([{"action": "device_poll", "params": {"deviceCode": "synthetic-code"}}],
                               [self.response(approved)], session=SESSION)
        self.assertEqual([{"ok": False, "errorCode": "invalid_response"}], result["outcomes"])
        self.assertEqual(SESSION, result["savedSession"])
        self.assertEqual(0, result["writes"])

    def test_approval_with_empty_account_id_cannot_replace_credentials(self):
        for user in ({}, {"id": ""}, {"id": " "}, {"id": None}, {"id": {"value": "u1"}}):
            with self.subTest(user=user):
                approved = json.loads(self.approval()["body"])
                approved["tokens"]["user"] = user
                result = self.run_auth([{"action": "device_poll", "params": {"deviceCode": "synthetic-code"}}],
                                       [self.response(approved)], session=SESSION)
                self.assertEqual([{"ok": False, "errorCode": "invalid_response"}], result["outcomes"])
                self.assertEqual(SESSION, result["savedSession"])
                self.assertEqual(0, result["writes"])
                self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))

    def test_device_code_full_login_profile_selection_restart_and_sign_out(self):
        jobs = [{"action": "set_server", "params": {"baseUrl": "https://silo.example"}},
                {"action": "device_start"}, {"action": "device_poll"}, {"action": "device_poll"},
                {"action": "profiles"},
                {"action": "select_profile", "params": {"profileId": "p1", "profileName": "Family"}},
                {"action": "session_status"}, {"action": "sign_out"}, {"action": "session_status"}]
        responses = [self.response(json.loads((FIXTURES / name).read_text()))
                     for name in ("device_start.json", "device_poll_pending.json")]
        responses.extend([self.approval(full_login=True),
                          self.response(json.loads((FIXTURES / "profiles.json").read_text()))])
        result = self.run_auth(jobs, responses)
        self.assertEqual(9, len(result["outcomes"]))
        self.assertTrue(all(outcome["ok"] for outcome in result["outcomes"]))
        self.assertEqual("ABCD-1234", result["outcomes"][1]["data"]["userCode"])
        self.assertEqual("42", result["outcomes"][1]["data"]["matchCode"])
        self.assertEqual(5000, result["outcomes"][2]["data"]["pollAfterMs"])
        restored = result["outcomes"][6]["data"]
        self.assertEqual((True, "p1", "Family", "Test Viewer"),
                         (restored["connected"], restored["profileId"], restored["profileName"], restored["accountName"]))
        self.assertEqual("enter_server", result["outcomes"][-1]["data"]["state"])
        self.assertEqual({}, result["savedSession"])
        for request in result["requests"][:3]:
            self.assertNotIn("Authorization", request["headers"])
        for request in result["requests"][1:3]:
            self.assertEqual({"device_code": "synthetic-device-code"}, json.loads(request["body"]))
        self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))

    def test_unauthorized_profile_list_refreshes_once_and_persists_before_retry(self):
        refreshed = {"access_token": "synthetic-new-access", "refresh_token": "synthetic-new-refresh", "expires_in": 3600}
        result = self.run_auth([{"action": "profiles"}],
            [{"ok": False, "statusCode": 401, "errorCode": "auth_required"}, self.response(refreshed),
             self.response(json.loads((FIXTURES / "profiles.json").read_text()))], session=SESSION)
        self.assertTrue(result["outcomes"][0]["ok"])
        self.assertEqual(3, len(result["requests"]))
        self.assertEqual("Bearer synthetic-old-access", result["requests"][0]["headers"]["Authorization"])
        self.assertNotIn("Authorization", result["requests"][1]["headers"])
        self.assertEqual({"refresh_token": "synthetic-old-refresh"}, json.loads(result["requests"][1]["body"]))
        self.assertEqual("Bearer synthetic-new-access", result["requests"][2]["headers"]["Authorization"])
        self.assertEqual("synthetic-new-refresh", result["savedSession"]["refreshToken"])
        self.assertEqual(SESSION["profileId"], result["savedSession"]["profileId"])
        self.assertEqual(1, result["writes"])
        self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))

    def test_verified_profile_is_saved_and_restored_without_a_second_selection(self):
        jobs = [{"action": "profile_verify", "params": {
            "profileId": "locked-profile", "profileName": "Locked", "pin": "4321"}}, {"action": "session_status"}]
        result = self.run_auth(jobs, [self.response({"valid": True, "expires_at": None,
                                                  "profile_token": "synthetic-new-profile"})], session=SESSION)
        self.assertTrue(all(outcome["ok"] for outcome in result["outcomes"]))
        self.assertEqual(("locked-profile", "Locked", "synthetic-new-profile"),
                         tuple(result["savedSession"][field] for field in ("profileId", "profileName", "profileToken")))
        self.assertEqual("locked-profile", result["outcomes"][-1]["data"]["profileId"])
        self.assertEqual(1, result["writes"])
        self.assertEqual(1, result["revision"])
        self.assertNotIn("synthetic-", json.dumps(result["outcomes"]))


if __name__ == "__main__":
    unittest.main()
