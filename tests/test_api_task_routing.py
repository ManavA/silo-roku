"""Worker dispatch must keep account-scoped Plex Watchlist separate from a server."""

from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "source/adapters/PlexAdapter.brs",
         ROOT / "source/adapters/PlexWatchlist.brs",
         ROOT / "components/ApiTask.brs"]


class ApiTaskRoutingTests(unittest.TestCase):
    def test_watchlist_uses_discover_account_token(self):
        session = {"clientId": "fixture-roku", "accountToken": "fixture-account",
                   "token": "fixture-server", "baseUrl": "https://server.example.test"}
        result = run_function(FILES, "TaskBuildRequest", ["plex", "watchlist", session, {}])
        self.assertTrue(result["ok"])
        self.assertEqual("discover.provider.plex.tv", result["url"].split("/")[2])
        self.assertEqual("fixture-account", result["headers"]["X-Plex-Token"])
        self.assertNotIn("fixture-server", str(result))

    def test_watchlist_mutation_preserves_explicit_global_identity(self):
        session = {"clientId": "fixture-roku", "accountToken": "fixture-account"}
        result = run_function(FILES, "TaskBuildRequest", ["plex", "watchlist_remove", session,
                                                        {"watchlistRatingKey": "global-one"}])
        self.assertTrue(result["ok"])
        self.assertIn("removeFromWatchlist?ratingKey=global-one", result["url"])

    def test_saved_account_identity_skips_an_extra_user_request(self):
        session = {"accountToken": "fixture-account", "accountId": "123"}
        result = run_function(FILES, "TaskEnsurePlexWatchlistAccount", [session, 0])
        self.assertTrue(result["ok"])
        self.assertEqual(result["session"]["accountId"], "123")
        self.assertIn("TaskEnsurePlexWatchlistAccount(session, revision)",
                      (ROOT / "components/ApiTask.brs").read_text())


if __name__ == "__main__":
    unittest.main()
