"""Account Watchlist seeds resolve to owned server titles only by exact identity."""

from pathlib import Path
import unittest

from tools.brightscript import run_function

POLICY = Path(__file__).resolve().parents[1] / "source/core/WatchlistPolicy.brs"


class WatchlistPolicyTests(unittest.TestCase):
    def match(self, seed, candidates):
        return run_function(POLICY, "MatchOwnedWatchlistItem", [seed, candidates, "plex:server-a"])

    def test_exact_guid_and_active_server_match(self):
        seed = {"sourceId": "plex-watchlist:account-a", "type": "movie", "title": "Same Title",
                "guids": ["plex://movie/g1", "tmdb://123"]}
        candidates = [
            {"sourceId": "plex:server-a", "itemId": "wrong", "type": "movie", "title": "Same Title", "guids": ["tmdb://999"]},
            {"sourceId": "plex:server-a", "itemId": "owned", "type": "movie", "title": "Different Title", "guids": ["tmdb://123"]},
        ]
        self.assertEqual("owned", self.match(seed, candidates)["itemId"])

    def test_title_only_wrong_type_and_other_server_are_rejected(self):
        seed = {"sourceId": "plex-watchlist:account-a", "type": "movie", "title": "Same Title", "guids": ["tmdb://123"]}
        candidates = [
            {"sourceId": "plex:server-a", "itemId": "title", "type": "movie", "title": "Same Title", "guids": []},
            {"sourceId": "plex:server-a", "itemId": "type", "type": "show", "guids": ["tmdb://123"]},
            {"sourceId": "plex:server-b", "itemId": "scope", "type": "movie", "guids": ["tmdb://123"]},
        ]
        self.assertIsNone(self.match(seed, candidates))

    def test_untrusted_seed_or_candidate_identity_is_not_playable(self):
        seed = {"sourceId": "plex:server-a", "type": "movie", "guids": ["tmdb://123"]}
        candidates = [{"sourceId": "plex:server-a", "itemId": "owned", "type": "movie", "guids": ["tmdb://123"]}]
        self.assertIsNone(self.match(seed, candidates))
        seed["sourceId"] = "plex-watchlist:account-a"
        candidates[0]["itemId"] = ""
        self.assertIsNone(self.match(seed, candidates))


if __name__ == "__main__":
    unittest.main()
