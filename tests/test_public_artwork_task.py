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
if not (ROOT / "source/auth/SessionPolicy.brs").exists(): ROOT = Path(__file__).resolve().parents[1]
CANDIDATE=Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/metadata"
FILES = [CANDIDATE / "source/core/RuntimeIdentity.brs", ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/adapters/PlexAdapter.brs",
         ROOT / "source/adapters/SiloAdapter.brs",
         CANDIDATE / "source/adapters/MetadataAdapter.brs"]

# Standalone BrightScript has no Roku device/registry/HTTP implementation.
# Replace these IO boundaries while executing the app's complete worker path
# and the real timeout policy. Requests remain synthetic and never leave here.
BOUNDARIES = '''
function MetadataRequestConfig(version as String) as Object
    return {baseUrl:"https://metadata.example",appVersion:version}
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

function RunMetadataJob(provider as String, action as String, session as Object, params as Object, scope as Object, response as Object, changeRevision as Boolean) as Object
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


class PublicArtworkTaskTests(unittest.TestCase):
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
                response=None, change_revision=False):
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
            worker_source = (CANDIDATE / "components/ApiTask.brs").read_text()
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
            return run_function([*FILES, CANDIDATE / "components/TaskSiloReplan.brs", worker, http, boundary], "RunMetadataJob",
                                [provider, action, session, params or {}, scope, response, change_revision],
                                root=temporary)

    def test_artwork_dispatches_default_header_free_route_for_both_providers(self):
        for provider in ("plex","silo"):
            result=self.run_job("metadata_artwork",{"type":"movie","tmdbId":"141"},provider=provider,response={"ok":True,"body":json.dumps({"type":"movie","tmdbId":"141","posterPath":"/fixture.jpg"})})
            self.assertTrue(result["outcome"]["ok"])
            self.assertEqual("https://metadata.example/v1/enrich/movie/141",result["requests"][0]["url"])
            self.assertEqual([4000],result["timeouts"])
            self.assertNotIn("private",json.dumps(result))
    def test_wrong_source_and_revision_change_never_publish_artwork(self):
        scope={"sourceId":"plex:foreign","profileId":"","generation":7,"requestId":"fixture-request"}
        result=self.run_job("metadata_artwork",{"type":"movie","tmdbId":"141"},scope=scope)
        self.assertFalse(result["outcome"]["ok"]); self.assertEqual([],result["requests"])
        result=self.run_job("metadata_artwork",{"type":"movie","tmdbId":"141"},change_revision=True)
        self.assertEqual("session_changed",result["outcome"]["errorCode"])
