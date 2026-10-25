"""Exercise the actual rebuild scheduler policy, without creating native Tasks."""

from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/RequestQueuePolicy.brs"
SCOPE = {"provider": "plex", "sourceId": "plex:fixture", "profileId": "owner", "generation": 4}


class RebuildRequestQueueTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "rebuild request scheduler is missing")
        return run_function(POLICY, name, list(args))

    def state(self):
        return self.call("RqCreate", SCOPE)

    def offer(self, state, action, *, params=None, purpose="items", cleanup=False, scope=None):
        job = dict(scope or SCOPE, action=action, params=params or {})
        return self.call("RqOffer", state, {"job": job, "purpose": purpose, "cleanup": cleanup})

    def test_catalog_concurrency_is_bounded_at_two(self):
        state = self.state()
        for action in ("home_continue", "home_on_deck", "sections"):
            state = self.offer(state, action)["state"]
        first = self.call("RqTake", state)
        second = self.call("RqTake", first["state"])
        blocked = self.call("RqTake", second["state"])
        self.assertEqual([first["next"]["job"]["action"], second["next"]["job"]["action"]],
                         ["home_continue", "home_on_deck"])
        self.assertIsNone(blocked["next"])
        self.assertEqual(len(blocked["state"]["active"]), 2)

    def test_session_change_waits_for_reads_then_runs_alone(self):
        state = self.offer(self.state(), "home")["state"]
        taken = self.call("RqTake", state)
        state = self.offer(taken["state"], "select_profile", purpose="select_source")["state"]
        self.assertIsNone(self.call("RqTake", state)["next"])
        state = self.call("RqComplete", state, taken["next"]["job"]["requestId"])
        taken = self.call("RqTake", state)
        self.assertEqual(taken["next"]["job"]["action"], "select_profile")
        state = self.offer(taken["state"], "sections")["state"]
        self.assertIsNone(self.call("RqTake", state)["next"])

    def test_stop_outranks_reads_but_progress_preserves_session_order(self):
        state = self.offer(self.state(), "library_items")["state"]
        state = self.offer(state, "playback_progress", params={"sessionId": "s1", "sequence": 1},
                           purpose="delivery", cleanup=True)["state"]
        state = self.offer(state, "playback_stop", params={"sessionId": "s1", "sequence": 2},
                           purpose="delivery", cleanup=True)["state"]
        taken = self.call("RqTake", state)
        self.assertEqual(taken["next"]["job"]["action"], "playback_progress")
        second = self.call("RqTake", taken["state"])
        self.assertEqual(second["next"]["job"]["action"], "library_items")
        state = self.call("RqComplete", second["state"], taken["next"]["job"]["requestId"])
        self.assertEqual(self.call("RqTake", state)["next"]["job"]["action"], "playback_stop")

    def test_route_change_drops_queued_reads_and_keeps_opened_session_cleanup(self):
        state = self.offer(self.state(), "home")["state"]
        taken = self.call("RqTake", state)
        state = self.offer(taken["state"], "sections")["state"]
        state = self.offer(state, "playback_stop", params={"sessionId": "old"},
                           purpose="delivery", cleanup=True)["state"]
        changed = dict(SCOPE, generation=5, profileId="child")
        rebound = self.call("RqRebind", state, changed)
        self.assertEqual([r["job"]["action"] for r in rebound["queued"]], ["playback_stop"])
        self.assertEqual(len(rebound["active"]), 1)
        self.assertEqual(rebound["scope"], changed)

    def test_duplicate_reads_are_rejected_without_blocking_distinct_pages(self):
        offered = self.offer(self.state(), "library_items", params={"offset": 0})
        duplicate = self.offer(offered["state"], "library_items", params={"offset": 0})
        next_page = self.offer(duplicate["state"], "library_items", params={"offset": 24})
        self.assertFalse(duplicate["accepted"])
        self.assertEqual(duplicate["reason"], "duplicate")
        self.assertTrue(next_page["accepted"])
        self.assertEqual(len(next_page["state"]["queued"]), 2)

    def test_queue_has_room_for_cleanup_when_ui_work_is_full(self):
        state = self.state()
        for index in range(24):
            state = self.offer(state, "library_items", params={"offset": index * 24})["state"]
        rejected = self.offer(state, "search")
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["reason"], "queue_full")
        stop = self.offer(state, "playback_stop", params={"sessionId": "s1"},
                          purpose="delivery", cleanup=True)
        self.assertTrue(stop["accepted"])
        self.assertEqual(len(stop["state"]["queued"]), 24)
        self.assertEqual(stop["evicted"]["job"]["params"], {"offset": 23 * 24})

    def test_late_completion_cannot_remove_a_different_request(self):
        state = self.offer(self.state(), "home")["state"]
        taken = self.call("RqTake", state)
        unchanged = self.call("RqComplete", taken["state"], "unknown-id")
        self.assertEqual(unchanged, taken["state"])
        completed = self.call("RqComplete", unchanged, taken["next"]["job"]["requestId"])
        self.assertEqual(completed["active"], [])

    def test_distinct_preview_leases_do_not_coalesce_identical_reads(self):
        job = dict(SCOPE, action="preview_detail", params={"itemId": "101"}, previewId="preview-1")
        first = self.call("RqOffer", self.state(), {"job": job, "purpose": "preview_detail"})
        job["previewId"] = "preview-2"
        second = self.call("RqOffer", first["state"], {"job": job, "purpose": "preview_detail"})
        self.assertTrue(second["accepted"])
        self.assertEqual(len(second["state"]["queued"]), 2)

    def test_foreground_play_and_catalog_outrank_preview(self):
        for action, purpose in (("playback_start", "playback"), ("sections", "items")):
            with self.subTest(action=action):
                state = self.offer(self.state(), "playback_start", purpose="preview_plan", params={"itemId": "101"})["state"]
                state = self.offer(state, action, purpose=purpose, params={"itemId": "102"})["state"]
                self.assertEqual(self.call("RqTake", state)["next"]["purpose"], purpose)

    def test_cleanup_outranks_foreground_play(self):
        state = self.offer(self.state(), "playback_start", purpose="playback")["state"]
        state = self.offer(state, "playback_stop", purpose="delivery", cleanup=True, params={"sessionId": "s1"})["state"]
        self.assertEqual(self.call("RqTake", state)["next"]["purpose"], "delivery")

    def test_cancel_removes_only_the_named_queued_request(self):
        offered = self.offer(self.state(), "preview_detail", purpose="preview_detail")
        request_id = offered["request"]["job"]["requestId"]
        state = self.offer(offered["state"], "sections")["state"]
        cancelled = self.call("RqCancelQueued", state, request_id)
        self.assertEqual(cancelled["request"]["job"]["requestId"], request_id)
        self.assertEqual([r["job"]["action"] for r in cancelled["state"]["queued"]], ["sections"])
        taken = self.call("RqTake", offered["state"])
        active = self.call("RqCancelQueued", taken["state"], request_id)
        self.assertIsNone(active["request"])
        self.assertEqual(active["state"], taken["state"])


if __name__ == "__main__":
    unittest.main()
