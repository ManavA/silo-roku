"""Execute artwork orchestration with only device/transport/file boundaries substituted."""

import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.brightscript import run_function
from tests.test_artwork_policy import FILES, FIXTURE, JOB, ROOT, SESSION


WORKER = ROOT / "components/ArtworkTask.brs"
BOUNDARIES = '''
function LoadSession(provider as String) as Object
    return m.fixtureSession
end function
function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function
function ArtworkDeviceSession(session as Object) as Object
    return session
end function
function ArtworkElapsedMs() as Integer
    return m.elapsedMs
end function
function ArtworkTransportCapabilities() as Object
    ' Fixture transport is an origin-scoped boundary, unlike Roku's current agent.
    return {authenticated: true}
end function
function ArtworkFetch(request as Object, timeoutMs as Integer, path as String) as Object
    m.requests.Push(request)
    m.timeouts.Push(timeoutMs)
    m.paths.Push(path)
    if path <> "" then m.files[path] = true
    stage = m.requests.Count()
    if m.changes.stage = stage
        if m.changes.DoesExist("session") then m.fixtureSession = m.changes.session
        if m.changes.DoesExist("revision") then m.fixtureRevision = m.changes.revision
        if m.changes.DoesExist("cancelled") then m.top.cancelled = m.changes.cancelled
        if m.changes.DoesExist("elapsedMs") then m.elapsedMs = m.changes.elapsedMs
    end if
    if m.responses.Count() = 0 then return {ok:false,errorCode:"network_timeout"}
    return m.responses.Shift()
end function
function ArtworkInspectFile(path as String) as Object
    return m.fileInfo
end function
function ArtworkRenameFile(fromPath as String, toPath as String) as Boolean
    m.files.Delete(fromPath)
    m.files[toPath] = true
    if m.changes.DoesExist("renameRevision") then m.fixtureRevision = m.changes.renameRevision
    return true
end function
sub ArtworkDeleteFile(path as String)
    m.deleted.Push(path)
    m.files.Delete(path)
end sub
function RunArtworkFixture(job as Object, session as Object, responses as Object, info as Object, changes as Object) as Object
    m.fixtureSession = session
    m.fixtureRevision = 3
    m.elapsedMs = 0
    m.requests = []
    m.timeouts = []
    m.paths = []
    m.files = {}
    m.deleted = []
    m.responses = responses
    m.fileInfo = info
    m.changes = changes
    m.top = {job:job, cancelled:false, result:invalid}
    runArtworkJob()
    return {outcome:m.top.result, requests:m.requests, timeouts:m.timeouts, paths:m.paths, files:m.files, deleted:m.deleted}
end function
'''


class ArtworkTaskTests(unittest.TestCase):
    def run_job(self, *, job=None, session=None, responses=None, info=None, changes=None, safe_fixture_transport=True):
        self.assertTrue(WORKER.is_file(), "Private artwork Task is missing")
        if responses is None:
            responses = [{"ok": True, "body": FIXTURE.read_text()},
                         {"ok": True, "contentType": "image/jpeg"}]
        if info is None:
            info = {"ok": True, "encodedBytes": 2048, "firstBytesHex": "ffd8ffe000104a4649460001"}
        with tempfile.TemporaryDirectory(prefix="silo-artwork-worker-") as directory:
            temporary = Path(directory)
            worker = temporary / "ArtworkTask.brs"
            source = WORKER.read_text()
            for name in ("ArtworkDeviceSession", "ArtworkElapsedMs", "ArtworkFetch", "ArtworkInspectFile", "ArtworkRenameFile"):
                source = source.replace("function " + name + "(", "function Unused" + name + "(", 1)
            boundaries = BOUNDARIES
            if safe_fixture_transport:
                source = source.replace("function ArtworkTransportCapabilities(", "function UnusedArtworkTransportCapabilities(", 1)
            else:
                boundaries = boundaries.replace("function ArtworkTransportCapabilities(", "function UnusedFixtureArtworkTransportCapabilities(", 1)
            source = source.replace("sub ArtworkDeleteFile(", "sub UnusedArtworkDeleteFile(", 1)
            worker.write_text(source)
            boundary = temporary / "boundaries.brs"
            boundary.write_text(boundaries)
            return run_function([*FILES, worker, boundary], "RunArtworkFixture",
                                [job or JOB, session or SESSION, responses, info, changes or {"stage": -1}], root=temporary)

    def test_finite_native_task_declares_job_result_and_cooperative_cancel(self):
        path = ROOT / "components/ArtworkTask.xml"
        self.assertTrue(path.is_file(), "Artwork SceneGraph Task is missing")
        component = ET.parse(path).getroot()
        self.assertEqual("Task", component.get("extends"))
        self.assertEqual({"job", "result", "cancelled"}, {n.get("id") for n in component.findall("interface/field")})
        scripts = [n.get("uri") for n in component.findall("script")]
        self.assertIn("pkg:/source/core/ArtworkPolicy.brs", scripts)
        self.assertIn("pkg:/source/auth/SessionStore.brs", scripts)
        self.assertNotIn("pkg:/components/ApiTask.brs", scripts)

    def test_private_detail_then_fresh_empty_header_image_download_publishes_local_file(self):
        result = self.run_job()
        self.assertEqual("ready", result["outcome"]["status"])
        self.assertEqual("tmp:/artwork-7-12.jpg", result["outcome"]["uri"])
        self.assertEqual(["", "tmp:/artwork-7-12.part"], result["paths"])
        self.assertEqual([3000, 5000], result["timeouts"])
        self.assertEqual("Bearer synthetic-private-access", result["requests"][0]["headers"]["Authorization"])
        self.assertEqual({}, result["requests"][1]["headers"])
        self.assertEqual({"tmp:/artwork-7-12.jpg": True}, result["files"])
        for key in JOB:
            self.assertEqual(JOB[key], result["outcome"][key])
        self.assertNotIn("Signature", json.dumps(result["outcome"]))
        self.assertNotIn("synthetic-private", json.dumps(result["outcome"]))

    def test_foreign_scope_is_rejected_before_any_request(self):
        for change in ({"sourceId": "silo:other"}, {"profileId": "other"}, {"accessToken": ""}):
            result = self.run_job(session={**SESSION, **change})
            self.assertEqual("unavailable", result["outcome"]["status"])
            self.assertEqual([], result["requests"])

    def test_sign_out_revision_or_account_replacement_after_detail_prevents_cdn_request(self):
        for changes in ({"stage": 1, "revision": 4},
                        {"stage": 1, "session": {**SESSION, "accessToken": "synthetic-other-account"}},
                        {"stage": 1, "session": {**SESSION, "profileId": "other"}}):
            result = self.run_job(changes=changes)
            self.assertEqual("session_changed", result["outcome"]["errorCode"])
            self.assertEqual(1, len(result["requests"]))
            self.assertEqual({}, result["files"])

    def test_cancel_or_session_change_during_download_deletes_partial_and_never_publishes_uri(self):
        for changes in ({"stage": 2, "cancelled": True}, {"stage": 2, "revision": 4}):
            result = self.run_job(changes=changes)
            self.assertEqual("cancelled", result["outcome"]["status"])
            self.assertEqual("", result["outcome"]["uri"])
            self.assertEqual({}, result["files"])
            self.assertIn("tmp:/artwork-7-12.part", result["deleted"])

    def test_session_change_after_rename_deletes_final_before_result_publication(self):
        result = self.run_job(changes={"stage": -1, "renameRevision": 4})
        self.assertEqual("cancelled", result["outcome"]["status"])
        self.assertEqual("", result["outcome"]["uri"])
        self.assertEqual({}, result["files"])
        self.assertIn("tmp:/artwork-7-12.jpg", result["deleted"])

    def test_failed_oversized_and_wrong_format_downloads_delete_partial(self):
        cases = [({"ok": False, "errorCode": "private-server-text"}, None, "invalid_response"),
                 ({"ok": True, "contentType": "image/jpeg"}, {"ok": True, "encodedBytes": 262145, "firstBytesHex": "ffd8ffe000104a4649460001"}, "image_too_large"),
                 ({"ok": True, "contentType": "text/html"}, None, "image_format")]
        for response, info, code in cases:
            result = self.run_job(responses=[{"ok": True, "body": FIXTURE.read_text()}, response], info=info)
            self.assertEqual(code, result["outcome"]["errorCode"])
            self.assertEqual("", result["outcome"]["uri"])
            self.assertEqual({}, result["files"])

    def test_cancel_or_total_deadline_after_detail_prevents_second_request(self):
        for changes in ({"stage": 1, "cancelled": True}, {"stage": 1, "elapsedMs": 8000}):
            result = self.run_job(changes=changes)
            self.assertNotEqual("ready", result["outcome"]["status"])
            self.assertEqual(1, len(result["requests"]))

    def test_plex_is_explicitly_unsupported_without_a_header_redirect_guarantee(self):
        job = {**JOB, "provider": "plex", "sourceId": "plex:fixture-server", "profileId": "", "itemId": "101"}
        session = {"sourceId": job["sourceId"], "profileId": "", "baseUrl": SESSION["baseUrl"],
                   "token": "synthetic-private-plex", "accountToken": "synthetic-private-account"}
        result = self.run_job(job=job, session=session)
        self.assertEqual("unsupported_redirect_safety", result["outcome"]["errorCode"])
        self.assertEqual([], result["requests"])

    def test_native_execute_blocks_authenticated_requests_for_both_providers(self):
        for provider in ("silo", "plex"):
            job = {**JOB, "provider": provider, "sourceId": provider + ":fixture-server"}
            session = {**SESSION, "sourceId": job["sourceId"]}
            if provider == "plex":
                session.update(token="synthetic-private-plex", accountToken="synthetic-private-account")
            result = self.run_job(job=job, session=session, safe_fixture_transport=False)
            self.assertEqual("unsupported_redirect_safety", result["outcome"]["errorCode"])
            self.assertEqual([], result["requests"])
            self.assertEqual({}, result["files"])

    def test_native_transport_is_async_cancelled_tls_checked_and_file_sized(self):
        self.assertTrue(WORKER.is_file(), "Private artwork Task is missing")
        source = WORKER.read_text()
        for required in ('AsyncGetToFile(path)', 'AsyncGetToString()', 'AsyncCancel()', 'wait(100, port)',
                         'EnablePeerVerification(true)', 'EnableHostVerification(true)',
                         'ArtworkTaskCurrent()', 'Stat(path)', 'ReadFile(path, 0, 12)'):
            self.assertIn(required, source)
        self.assertNotIn('EnableRedirect', source)
        self.assertNotIn('AddHeader(', source)
        self.assertNotIn('GetFailureReason', source)
        self.assertNotIn('print ', source.lower())


if __name__ == "__main__":
    unittest.main()
