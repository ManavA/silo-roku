"""Watched writes run through the real worker with active-source scope."""

from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/adapters/PlexAdapter.brs",
         ROOT / "source/adapters/SiloAdapter.brs",
         ROOT / "components/ApiTask.brs"]

BOUNDARIES = '''
function SessionRevision(provider as String) as Integer
    return 0
end function

function LoadSession(provider as String) as Object
    return m.fixtureSession
end function

function TaskDeviceSession(provider as String, session as Object) as Object
    return session
end function

function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    m.requests.Push(request)
    return {ok:true,statusCode:204,body:""}
end function

function RunWatchedMutation(provider as String, action as String, session as Object, sourceId as String) as Object
    m.fixtureSession = session
    m.requests = []
    result = ExecuteApiAction(provider, action, {itemId:"501"}, {sourceId:sourceId,profileId:"p1"})
    return {result:result,requests:m.requests}
end function
'''


class WatchedTaskTests(unittest.TestCase):
    def call(self, provider, action, session, source_id):
        with tempfile.TemporaryDirectory(prefix="silo-watched-task-") as directory:
            root = Path(directory)
            worker = root / "ApiTask.brs"
            source = FILES[-1].read_text()
            source = source.replace("function TaskDeviceSession(", "function UnusedTaskDeviceSession(", 1)
            worker.write_text(source)
            boundary = root / "boundaries.brs"
            boundary.write_text(BOUNDARIES)
            return run_function([*FILES[:-1], worker, boundary], "RunWatchedMutation",
                                [provider, action, session, source_id], root=root)

    def test_plex_scrobble_and_unscrobble_use_server_token_and_empty_ack(self):
        session = {"sourceId": "plex:server", "profileId": "p1", "clientId": "fixture-client",
                   "baseUrl": "https://server.example.test", "token": "synthetic-server-token"}
        for action, path in (("scrobble", "/:/scrobble"), ("unscrobble", "/:/unscrobble")):
            with self.subTest(action=action):
                outcome = self.call("plex", action, session, "plex:server")
                self.assertEqual({"ok": True, "data": {}}, outcome["result"])
                self.assertEqual(1, len(outcome["requests"]))
                self.assertIn(path, outcome["requests"][0]["url"])
                self.assertEqual("synthetic-server-token", outcome["requests"][0]["headers"]["X-Plex-Token"])

    def test_silo_watched_write_uses_profile_and_empty_ack(self):
        session = {"sourceId": "silo:server", "profileId": "p1", "baseUrl": "https://silo.example.test",
                   "accessToken": "synthetic-access-token", "deviceId": "fixture-client"}
        for action, method in (("mark_watched", "POST"), ("mark_unwatched", "DELETE")):
            with self.subTest(action=action):
                outcome = self.call("silo", action, session, "silo:server")
                self.assertEqual({"ok": True, "data": {}}, outcome["result"])
                self.assertEqual(1, len(outcome["requests"]))
                self.assertEqual(method, outcome["requests"][0]["method"])
                self.assertEqual("p1", outcome["requests"][0]["headers"]["X-Profile-Id"])

    def test_stale_source_rejected_before_http(self):
        session = {"sourceId": "silo:server", "profileId": "p1", "baseUrl": "https://silo.example.test",
                   "accessToken": "synthetic-access-token"}
        outcome = self.call("silo", "mark_watched", session, "silo:other")
        self.assertEqual("session_changed", outcome["result"]["errorCode"])
        self.assertEqual([], outcome["requests"])


if __name__ == "__main__":
    unittest.main()
