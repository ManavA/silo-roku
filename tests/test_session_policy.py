"""Session state stays private while the scene gets only connection facts."""

import json
from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/auth/SessionPolicy.brs"


class SessionPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file())
        return run_function(POLICY, name, list(args))

    def test_plex_status_requires_server_token_and_never_exposes_it(self):
        session = {"accountToken": "account-secret", "token": "server-secret",
                   "baseUrl": "https://media.example.test", "sourceId": "plex:one",
                   "accountName": "Alice", "serverName": "Living Room"}
        status = self.call("PublicSessionStatus", "plex", session)
        self.assertEqual(status["state"], "connected")
        self.assertEqual(status["sourceId"], "plex:one")
        self.assertEqual(status["serverName"], "Living Room")
        self.assertNotIn("secret", json.dumps(status))
        session["token"] = ""
        self.assertEqual(self.call("PublicSessionStatus", "plex", session)["state"], "choose_server")

    def test_silo_status_distinguishes_server_auth_and_profile(self):
        session = {"baseUrl": "https://silo.example", "accessToken": "secret", "profileId": "p1",
                   "sourceId": "silo:one", "profileName": "Family"}
        status = self.call("PublicSessionStatus", "silo", session)
        self.assertEqual((status["state"], status["profileId"], status["profileName"]),
                         ("connected", "p1", "Family"))
        self.assertNotIn("secret", json.dumps(status))
        session["profileId"] = ""
        self.assertEqual(self.call("PublicSessionStatus", "silo", session)["state"], "choose_profile")
        session["accessToken"] = ""
        self.assertEqual(self.call("PublicSessionStatus", "silo", session)["state"], "sign_in")
        session["baseUrl"] = ""
        self.assertEqual(self.call("PublicSessionStatus", "silo", session)["state"], "enter_server")

    def test_patch_merge_keeps_existing_fields_and_overrides_new_ones(self):
        merged = self.call("MergeSessionPatch", {"baseUrl": "https://one", "accessToken": "old"},
                           {"accessToken": "new", "profileId": "p2"})
        self.assertEqual(merged, {"baseUrl": "https://one", "accessToken": "new", "profileId": "p2"})

    def test_public_server_choices_strip_tokens_and_connections(self):
        servers = [{"machineId": "m1", "sourceId": "plex:m1", "name": "Living Room",
                    "token": "private-token", "connections": [{"baseUrl": "https://private.example"}]}]
        choices = self.call("PublicPlexServers", servers)
        self.assertEqual(choices, [{"machineId": "m1", "sourceId": "plex:m1", "name": "Living Room"}])
        self.assertNotIn("private", json.dumps(choices))


if __name__ == "__main__":
    unittest.main()
