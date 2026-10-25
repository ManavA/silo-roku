"""Cross-season Continue Watching promotion requires scoped episode proof."""

from pathlib import Path
import unittest

from tools.brightscript import run_function


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "source/core/ContinueOverlay.brs"
NEIGHBORS = ROOT / "source/core/EpisodeNeighbors.brs"
SCOPE = {"sourceId": "plex:fixture", "profileId": "owner", "generation": 8}


class EpisodeOverlayTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(NEIGHBORS.is_file(), "EpisodeNeighbors policy is missing")
        return run_function([NEIGHBORS, OVERLAY], name, list(args))

    def cards(self):
        current = {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": "101",
                   "type": "episode", "title": "Finale", "seriesItemId": "100",
                   "parentItemId": "110", "seasonNumber": 1, "episodeNumber": 9}
        following = {**current, "itemId": "201", "title": "Premiere",
                     "parentItemId": "210", "seasonNumber": 2, "episodeNumber": 1}
        proof = {"status": "known", "provider": "plex", **SCOPE, "lookupId": "lookup-1",
                 "currentItemId": "101", "nextItemId": "201", "seriesId": "100",
                 "currentSeasonNumber": 1, "nextSeasonNumber": 2,
                 "currentSeasonItemId": "110", "nextSeasonItemId": "210"}
        return current, following, proof

    def record(self, current, following, proof):
        state = self.call("ContinueOverlayBind", None, SCOPE)
        return self.call("ContinueOverlayRecord", state, SCOPE, current,
                         100000, 100000, True, True, following, proof)

    def test_verified_cross_season_candidate_advances_history(self):
        current, following, proof = self.cards()
        state = self.record(current, following, proof)
        self.assertEqual("advance", state["edits"][0]["mode"])
        self.assertEqual("201", state["edits"][0]["successor"]["itemId"])
        self.assertNotIn("proof", state["edits"][0], "Overlay must retain only compact media facts")

    def test_cross_season_candidate_without_matching_proof_only_completes(self):
        current, following, proof = self.cards()
        self.assertEqual("complete", self.record(current, following, None)["edits"][0]["mode"])
        for field, wrong in (("status", "ambiguous"), ("sourceId", "plex:other"),
                             ("profileId", "child"), ("generation", 7),
                             ("currentItemId", "102"), ("nextItemId", "202"),
                             ("seriesId", "other"), ("currentSeasonNumber", 3),
                             ("nextSeasonNumber", 4), ("currentSeasonItemId", "111"),
                             ("nextSeasonItemId", "211")):
            with self.subTest(field=field):
                forged = {**proof, field: wrong}
                self.assertEqual("complete", self.record(current, following, forged)["edits"][0]["mode"])

    def test_changed_candidate_identity_cannot_use_old_proof(self):
        current, following, proof = self.cards()
        for field, wrong in (("itemId", "202"), ("sourceId", "plex:other"),
                             ("seriesItemId", "other"), ("parentItemId", "211"),
                             ("seasonNumber", 3)):
            with self.subTest(field=field):
                changed = {**following, field: wrong}
                self.assertEqual("complete", self.record(current, changed, proof)["edits"][0]["mode"])


if __name__ == "__main__":
    unittest.main()
