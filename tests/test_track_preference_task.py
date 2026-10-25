"""Actual local worker routing and JSON persistence with synthetic session fixtures."""

import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "components/ApiTask.brs"
FILES = [ROOT / "source/auth/SessionPolicy.brs", ROOT / "source/core/TrackPreference.brs",
         ROOT / "source/adapters/PlexAdapter.brs", ROOT / "source/adapters/SiloAdapter.brs"]
FIXTURE = json.loads((ROOT / "tests/fixtures/track_preference/session.json").read_text())

BOUNDARIES = '''
function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function

function LoadSession(provider as String) as Object
    session = DecodeStoredSession(m.fixtureSessionJson)
    if m.changeAfterLoad
        m.fixtureRevision++
        m.changeAfterLoad = false
    end if
    return session
end function

function SaveSession(provider as String, session as Object, revision as Integer) as Boolean
    if m.changeDuringSave then m.fixtureRevision++
    if revision <> m.fixtureRevision or m.failWrite then return false
    serialized = FormatJson(session)
    if Len(serialized) > 14000 then return false
    m.fixtureSessionJson = serialized
    m.writes++
    return true
end function

function TaskDeviceSession(provider as String, session as Object) as Object
    m.deviceCalls++
    return session
end function

function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    m.requests.Push(request)
    return {ok:false,errorCode:"unexpected_http"}
end function

function RunTrackPreferenceJobs(provider as String, session as Object, jobs as Object, failWrite as Boolean, changeAfterLoad as Boolean, changeDuringSave as Boolean) as Object
    m.fixtureSessionJson = FormatJson(session)
    m.fixtureRevision = 0
    m.requests = []
    m.outcomes = []
    m.writes = 0
    m.deviceCalls = 0
    m.failWrite = failWrite
    m.changeAfterLoad = changeAfterLoad
    m.changeDuringSave = changeDuringSave
    for each job in jobs
        outcome = ExecuteApiAction(provider,job.action,TaskValue(job,"params",{}),job.scope)
        m.outcomes.Push(outcome)
        if not outcome.ok then exit for
    end for
    return {outcomes:m.outcomes,requests:m.requests,savedSession:DecodeStoredSession(m.fixtureSessionJson),writes:m.writes,deviceCalls:m.deviceCalls}
end function
'''


class TrackPreferenceTaskTests(unittest.TestCase):
    def scope(self, provider="plex"):
        return {key: FIXTURE[provider][key] for key in ("sourceId", "profileId")}

    def preference(self, provider="plex", **changes):
        return {"schemaVersion": 1, **self.scope(provider), "subtitleMode": "auto", "subtitleLanguage": "eng",
                "subtitleName": "", "audioLanguage": "", "audioName": "", **changes}

    def job(self, action="track_pref_get", params=None, scope=None, provider="plex"):
        return {"action": action, "params": params if params is not None else {},
                "scope": scope if scope is not None else self.scope(provider)}

    def call(self, jobs, *, provider="plex", session=None, fail_write=False, change_after_load=False, change_during_save=False):
        with tempfile.TemporaryDirectory(prefix="silo-track-pref-task-") as directory:
            temporary = Path(directory)
            worker = temporary / "ApiTask.brs"
            source = WORKER.read_text().replace("function TaskDeviceSession(", "function UnusedTaskDeviceSession(", 1)
            worker.write_text(source)
            decoder = re.search(r"function DecodeStoredSession\(.*?^end function",
                                (ROOT / "source/auth/SessionStore.brs").read_text(), re.S | re.M)
            self.assertIsNotNone(decoder)
            boundaries = temporary / "boundaries.brs"
            boundaries.write_text(decoder.group() + "\n" + BOUNDARIES)
            return run_function([*FILES, worker, boundaries], "RunTrackPreferenceJobs",
                                [provider, session if session is not None else FIXTURE[provider], jobs,
                                 fail_write, change_after_load, change_during_save], root=temporary)

    def assert_local(self, outcome):
        self.assertEqual([], outcome["requests"])
        self.assertEqual(0, outcome["deviceCalls"])
        self.assertNotIn("synthetic-", json.dumps(outcome["outcomes"]))

    def test_get_returns_default_before_device_queries_or_provider_network(self):
        result = self.call([self.job()])
        self.assertEqual([{"ok": True, "data": {"preference": self.preference()}}], result["outcomes"])
        self.assertEqual(0, result["writes"])
        self.assertEqual(FIXTURE["plex"], result["savedSession"])
        self.assert_local(result)

    def test_set_then_get_round_trip_preserves_explicit_off_and_existing_credentials(self):
        preference = self.preference(subtitleMode="off")
        result = self.call([self.job("track_pref_set", {"preference": preference}), self.job()])
        self.assertEqual([{"ok": True, "data": {"preference": preference}}] * 2, result["outcomes"])
        self.assertEqual(1, result["writes"])
        self.assertEqual({**FIXTURE["plex"], "trackPreference": preference}, result["savedSession"])
        self.assert_local(result)

    def test_silo_on_and_audio_preference_are_normalized_under_active_profile(self):
        raw = self.preference("silo", subtitleMode="on", subtitleLanguage="English", audioLanguage="ja", audioName="Japanese Main")
        result = self.call([self.job("track_pref_set", {"preference": raw}, provider="silo"), self.job(provider="silo")], provider="silo")
        expected = self.preference("silo", subtitleMode="on", audioLanguage="jpn", audioName="Japanese Main")
        self.assertEqual([{"ok": True, "data": {"preference": expected}}] * 2, result["outcomes"])
        self.assertEqual(1, result["writes"])
        self.assert_local(result)

    def test_explicit_empty_plex_owner_profile_is_scoped(self):
        session = {**FIXTURE["plex"], "profileId": ""}
        result = self.call([self.job(scope={"sourceId": session["sourceId"], "profileId": ""})], session=session)
        self.assertTrue(result["outcomes"][0]["ok"])
        self.assertEqual("", result["outcomes"][0]["data"]["preference"]["profileId"])
        self.assert_local(result)

    def test_foreign_or_missing_scope_never_reads_or_writes_preferences(self):
        scopes = [{"sourceId": "plex:other", "profileId": "fixture-owner"},
                  {"sourceId": "plex:fixture-server", "profileId": "other-profile"},
                  {"sourceId": "plex:fixture-server"}, {"sourceId": "plex:fixture-server", "profileId": None},
                  {"sourceId": "plex:fixture-server", "profileId": ""}, {}]
        for scope in scopes:
            with self.subTest(scope=scope):
                result = self.call([self.job(scope=scope)])
                self.assertEqual([{"ok": False, "errorCode": "session_changed"}], result["outcomes"])
                self.assertEqual(0, result["writes"])
                self.assert_local(result)
        result = self.call([self.job("track_pref_set", {"preference": self.preference(sourceId="plex:other")})])
        self.assertEqual("session_changed", result["outcomes"][0]["errorCode"])
        self.assertEqual(0, result["writes"])

    def test_set_rejects_unknown_secret_runtime_id_and_url_fields(self):
        for extra in ({"token": "synthetic-secret"}, {"headers": {"Authorization": "synthetic-secret"}},
                      {"trackId": "runtime-id"}, {"subtitleTrack": "https://private.example.test/sub"},
                      {"extra": {"password": "synthetic-secret"}}):
            with self.subTest(extra=extra):
                result = self.call([self.job("track_pref_set", {"preference": self.preference(**extra)})])
                self.assertEqual("invalid_request", result["outcomes"][0]["errorCode"])
                self.assertEqual(0, result["writes"])
                self.assert_local(result)
        result = self.call([self.job("track_pref_set", {"preference": self.preference(), "token": "synthetic-secret"})])
        self.assertEqual("invalid_request", result["outcomes"][0]["errorCode"])
        self.assertEqual(0, result["writes"])

    def test_set_rejects_malformed_records_modes_language_and_names(self):
        records = [None, [], "off", {}, self.preference(schemaVersion=True), self.preference(schemaVersion=2),
                   self.preference(subtitleMode="sometimes"), self.preference(subtitleMode={}),
                   self.preference(subtitleLanguage="https://private.example.test?token=fixture"),
                   self.preference(subtitleName="Authorization: Bearer fixture"),
                   self.preference(audioName="x" * 97), self.preference(audioLanguage=2)]
        for record in records:
            with self.subTest(record=record):
                result = self.call([self.job("track_pref_set", {"preference": record})])
                self.assertEqual("invalid_request", result["outcomes"][0]["errorCode"])
                self.assertEqual(0, result["writes"])
                self.assert_local(result)

    def test_get_drops_other_profile_and_sanitizes_old_preference_fields_without_write(self):
        session = {**FIXTURE["plex"], "trackPreference": self.preference(profileId="other-profile", subtitleMode="off", token="synthetic-secret")}
        result = self.call([self.job()], session=session)
        self.assertTrue(result["outcomes"][0]["ok"])
        self.assertEqual(self.preference(), result["outcomes"][0]["data"]["preference"])
        self.assertEqual(0, result["writes"])
        self.assert_local(result)
        session["trackPreference"] = self.preference(subtitleMode="on", subtitleName="https://private.example.test/sub", token="synthetic-secret")
        result = self.call([self.job()], session=session)
        self.assertTrue(result["outcomes"][0]["ok"])
        self.assertEqual(self.preference(subtitleMode="on"), result["outcomes"][0]["data"]["preference"])
        self.assert_local(result)

    def test_storage_failure_keeps_existing_session_and_revision_change_is_distinct(self):
        job = self.job("track_pref_set", {"preference": self.preference(subtitleMode="off")})
        for options, error in (({"fail_write": True}, "storage_error"), ({"change_during_save": True}, "session_changed")):
            with self.subTest(options=options):
                result = self.call([job], **options)
                self.assertEqual([{"ok": False, "errorCode": error}], result["outcomes"])
                self.assertEqual(FIXTURE["plex"], result["savedSession"])
                self.assertEqual(0, result["writes"])
                self.assert_local(result)

    def test_revision_change_during_get_does_not_return_old_scope_preferences(self):
        result = self.call([self.job()], change_after_load=True)
        self.assertEqual([{"ok": False, "errorCode": "session_changed"}], result["outcomes"])
        self.assertEqual(0, result["writes"])
        self.assert_local(result)

    def test_worker_xml_loads_policy_and_local_dispatch_precedes_device_lookup(self):
        self.assertIn("pkg:/source/core/TrackPreference.brs", (ROOT / "components/ApiTask.xml").read_text())
        source = WORKER.read_text().split("function ExecuteApiAction(", 1)[1].split("end function", 1)[0]
        self.assertIn('action = "track_pref_get"', source)
        self.assertLess(source.index('action = "track_pref_get"'), source.index("session = TaskDeviceSession("))


if __name__ == "__main__":
    unittest.main()
