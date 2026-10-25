"""Execute preview lease, editorial start, and captured cleanup policies."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/PreviewPolicy.brs"
FILES = [ROOT / "tests/fixtures/legacy_policy_values.brs", ROOT / "source/core/VideoOwnerPolicy.brs", POLICY]
SCOPE = {"provider": "plex", "sourceId": "plex:fixture", "profileId": "owner", "generation": 4}
BOUNDS = {"x": 682, "y": 160, "width": 512, "height": 288}
ITEM = {"provider": "plex", "sourceId": "plex:fixture", "itemId": "101", "type": "movie", "durationMs": 120000, "resumeMs": 0}


def focus(item=None, scope=None, now=0, **extra):
    chosen = deepcopy(item or ITEM)
    return {"kind": "focus", "key": chosen["itemId"], "item": chosen,
            "scope": deepcopy(scope or SCOPE), "bounds": BOUNDS,
            "contentFocused": True, "autoplayAllowed": True, "nowMs": now, **extra}


def detail(preview="preview-1", scope=None, item=None, **extra):
    return {"kind": "detail_result", "previewId": preview, "scope": deepcopy(scope or SCOPE),
            "ok": True, "data": {"candidateItemId": (item or ITEM)["itemId"], "item": deepcopy(item or ITEM), "versions": [{"versionId": "version-1", "markers": []}]},
            "nowMs": 1200, **extra}


def plan(preview="preview-1", scope=None, session="session-1", **extra):
    return {"kind": "plan_result", "previewId": preview, "scope": deepcopy(scope or SCOPE), "ok": True,
            "plan": {"itemId": "101", "sessionId": session, "installationId": "roku-fixture",
                     "url": "https://fixture.example.test/preview.m3u8", "streamFormat": "hls"},
            "nowMs": 1300, **extra}


def native(state="stopped", attempt="preview-1", **extra):
    return {"kind": "native", "attemptId": attempt, "mode": "preview", "state": state, "nowMs": 2600, **extra}


def cleanup(ok=True, preview="preview-1", scope=None, **extra):
    return {"kind": "cleanup_result", "previewId": preview, "scope": deepcopy(scope or SCOPE), "ok": ok, "nowMs": 2700, **extra}


class PreviewPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "preview lease policy is missing")
        return run_function(FILES, name, list(args))

    def trace(self, *events):
        self.assertTrue(POLICY.is_file(), "preview lease policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-preview-") as directory:
            helper = Path(directory) / "trace.brs"
            helper.write_text('''function PreviewTestTrace(events as Object) as Object
    state = PreviewCreate()
    trace = []
    for each event in events
        result = PreviewReduce(state,event)
        state = result.state
        result["busy"] = PreviewBusy(state)
        trace.Push(result)
    end for
    return trace
end function
''')
            return run_function([*FILES, helper], "PreviewTestTrace", [events], root=Path(directory))

    def kinds(self, result):
        return [effect["kind"] for effect in result["effects"]]

    def test_initial_state_has_no_busy_lease(self):
        state = self.call("PreviewCreate")
        self.assertEqual("idle", state["phase"])
        self.assertIsNone(state["current"])
        self.assertFalse(self.call("PreviewBusy", state))

    def test_run_identity_scopes_preview_and_cleanup_ids_across_launches(self):
        state = self.call("PreviewCreate", "preview-fixture-run")
        result = self.call("PreviewReduce", state, focus())
        self.assertEqual("preview-fixture-run-1", result["effects"][0]["previewId"])
        self.assertEqual("preview-fixture-run-1-stop", result["state"]["current"]["stopId"])

    def test_invalid_bounds_never_schedule_preview(self):
        for bounds in ([], {"x": 1, "y": 2, "width": 0, "height": 100},
                       dict(BOUNDS, x="bad"), dict(BOUNDS, height=-1)):
            self.assertIsNone(self.trace(focus(bounds=bounds))[0]["state"]["wanted"])

    def test_prepare_starts_immediately_and_dwell_delays_only_allocation(self):
        trace = self.trace(focus(), detail(nowMs=100), focus(now=900),
                           {"kind": "dwell", "nowMs": 1199}, {"kind": "dwell", "nowMs": 1200})
        request, timer = trace[0]["effects"]
        self.assertEqual("preview_detail", request["purpose"])
        self.assertEqual("preview_detail", request["action"])
        self.assertEqual({"itemId": "101", "type": "movie"}, request["params"])
        self.assertEqual("preview-1", request["previewId"])
        self.assertEqual(SCOPE, request["scope"])
        self.assertEqual({"kind": "timer", "milliseconds": 1200}, timer)
        self.assertEqual([], trace[1]["effects"])
        self.assertEqual("dwell", trace[1]["state"]["phase"])
        self.assertFalse(trace[1]["busy"])
        self.assertEqual([], trace[2]["effects"])
        self.assertNotIn("request", self.kinds(trace[3]))
        self.assertEqual("preview_plan", trace[4]["effects"][0]["purpose"])
        self.assertTrue(trace[4]["busy"])

    def test_only_owned_movie_episode_show_focus_is_eligible(self):
        for changes in ({"type": "season"}, {"sourceId": "plex:other"},
                        {"provider": "silo"}, {"availability": "external"}, {"playable": False},
                        {"itemId": ""}, {"uiAction": "next_page"}, {"type": []}):
            with self.subTest(changes=changes):
                result = self.trace(focus(dict(ITEM, **changes)))[0]
                self.assertIsNone(result["state"]["wanted"])
                self.assertNotIn("timer", self.kinds(result))
        for extra in ({"autoplayAllowed": False}, {"contentFocused": False}, {"autoplayAllowed": "true"}):
            self.assertIsNone(self.trace(focus(**extra))[0]["state"]["wanted"])

    def test_plex_plan_uses_exact_version_and_preview_rendition(self):
        result = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail())[-1]
        request = result["effects"][0]
        self.assertEqual("preview_plan", request["purpose"])
        self.assertEqual("playback_start", request["action"])
        self.assertEqual({"itemId": "101", "versionIndex": 0, "versionId": "version-1", "startPositionMs": 0,
                          "forceTranscode": True, "maxVideoBitrate": 2500, "videoResolution": "1280x720",
                          "detail": detail()["data"]}, request["params"])
        self.assertTrue(result["busy"])

    def test_silo_plan_uses_exact_file_and_preview_rendition(self):
        scope = dict(SCOPE, provider="silo", sourceId="silo:fixture")
        item = dict(ITEM, provider="silo", sourceId="silo:fixture", type="episode")
        result = self.trace(focus(item, scope), {"kind": "dwell", "nowMs": 1200}, detail(scope=scope, item=item))[-1]
        self.assertEqual({"itemId": "101", "fileId": "version-1", "startPositionMs": 0,
                          "qualityPreference": "720p", "bandwidthCapKbps": 2500}, result["effects"][0]["params"])
        self.assertNotIn("purpose", result["effects"][0]["params"])

    def test_editorial_start_prefers_resume_then_earliest_usable_intro(self):
        markers = [{"type": "intro", "startMs": 12000, "endMs": 18000},
                   {"type": "intro", "startMs": 0, "endMs": 25000},
                   {"type": "intro", "startMs": 0, "endMs": 20000},
                   {"type": "intro", "startMs": -1, "endMs": 1000},
                   {"type": "intro", "startMs": 0, "endMs": 120000},
                   {"type": "credits", "startMs": 0, "endMs": 2000}]
        self.assertEqual(75000, self.call("PreviewStartPositionMs", dict(ITEM, resumeMs=75000), markers))
        self.assertEqual(20000, self.call("PreviewStartPositionMs", ITEM, markers))

    def test_editorial_movie_fallback_is_bounded_and_episode_starts_at_zero(self):
        for duration, expected in ((120000, 45000), (9000, 8000), (500, 0), (0, 45000)):
            self.assertEqual(expected, self.call("PreviewStartPositionMs", dict(ITEM, durationMs=duration), []))
        self.assertEqual(0, self.call("PreviewStartPositionMs", dict(ITEM, type="episode"), []))

    def test_selected_version_markers_determine_editorial_start(self):
        data = detail()["data"]
        data["markers"] = [{"type": "intro", "startMs": 0, "endMs": 3000}]
        data["versions"][0]["markers"] = [{"type": "intro", "startMs": 0, "endMs": 18000}]
        result = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(data=data))[-1]
        self.assertEqual(0, result["effects"][0]["params"]["startPositionMs"])
        self.assertEqual(18000, result["state"]["current"]["previewPositionMs"])

    def test_selected_version_id_is_resolved_after_fresh_detail_reorders_versions(self):
        data = detail()["data"]
        data["versions"] = [{"versionId": "other"}, {"versionId": "selected", "markers": [{"type": "intro", "startMs": 0, "endMs": 23000}]}]
        result = self.trace(focus(versionIndex=0, versionId="selected"), {"kind": "dwell", "nowMs": 1200}, detail(data=data))[-1]
        params = result["effects"][0]["params"]
        self.assertEqual("selected", params["versionId"])
        self.assertEqual(1, params["versionIndex"])
        self.assertEqual(0, params["startPositionMs"])
        self.assertEqual(23000, result["state"]["current"]["previewPositionMs"])

    def test_missing_selected_version_id_cannot_fall_back_to_another_version(self):
        result = self.trace(focus(versionIndex=0, versionId="missing"), {"kind": "dwell", "nowMs": 1200}, detail())[-1]
        self.assertNotIn("request", self.kinds(result))

    def test_selected_version_index_without_id_uses_that_fresh_version(self):
        data = detail()["data"]
        data["versions"].append({"versionId": "second"})
        result = self.trace(focus(versionIndex=1), {"kind": "dwell", "nowMs": 1200}, detail(data=data))[-1]
        self.assertEqual("second", result["effects"][0]["params"]["versionId"])
        self.assertEqual(1, result["effects"][0]["params"]["versionIndex"])

    def test_returned_wrong_version_plan_is_cleaned_without_starting_video(self):
        event = plan()
        event["plan"]["versionId"] = "wrong"
        result = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), event)[-1]
        self.assertEqual(["cleanup"], self.kinds(result))

    def test_stale_detail_and_missing_exact_version_cannot_allocate(self):
        prefix = [focus(), {"kind": "dwell", "nowMs": 1200}]
        for event in (detail(preview="preview-old"), detail(scope=dict(SCOPE, generation=5))):
            self.assertEqual([], self.trace(*prefix, event)[-1]["effects"])
        for data in ({"item": ITEM, "versions": []}, {"item": dict(ITEM, itemId="other"), "versions": [{"versionId": "v"}]}):
            result = self.trace(*prefix, detail(data=data))[-1]
            self.assertNotIn("request", self.kinds(result))
            self.assertFalse(result["busy"])

    def test_retired_detail_is_replaceable_without_waiting_for_its_result(self):
        second = dict(ITEM, itemId="202")
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, focus(second, now=1300),
                           {"kind": "dwell", "nowMs": 2500}, detail())
        self.assertEqual("preview-2", trace[2]["effects"][0]["previewId"])
        self.assertEqual([], trace[4]["effects"])
        self.assertEqual("preview-2", trace[4]["state"]["current"]["previewId"])

    def test_current_plan_starts_only_one_preview_with_captured_bounds(self):
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(), native("playing"), plan())
        start = trace[3]["effects"][0]
        self.assertEqual("start", start["kind"])
        self.assertEqual("preview-1", start["attemptId"])
        self.assertEqual("preview", start["mode"])
        self.assertEqual(BOUNDS, start["bounds"])
        self.assertEqual(45000, start["previewPositionMs"])
        self.assertEqual(plan()["plan"], start["plan"])
        self.assertEqual("active", trace[4]["state"]["phase"])
        self.assertEqual([], trace[5]["effects"])

    def test_retired_inflight_plan_blocks_allocation_but_prepares_latest_focus(self):
        second = dict(ITEM, itemId="202")
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), focus(second, now=1300),
                           detail(preview="preview-2", item=second, nowMs=1400),
                           {"kind": "dwell", "nowMs": 2500}, plan(nowMs=2600), cleanup())
        self.assertTrue(trace[3]["busy"])
        self.assertEqual("preview_detail", trace[3]["effects"][0]["purpose"])
        self.assertEqual([], trace[4]["effects"])
        self.assertNotIn("request", self.kinds(trace[5]))
        self.assertEqual(["cleanup"], self.kinds(trace[6]))
        self.assertEqual(SCOPE, trace[6]["effects"][0]["scope"])
        self.assertEqual("preview-2", trace[7]["effects"][0]["previewId"])
        self.assertEqual("preview_plan", trace[7]["effects"][0]["purpose"])

    def test_non_ok_retired_plan_still_cleans_allocated_session(self):
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), {"kind": "release", "reason": "play", "nowMs": 1300},
                           plan(ok=False, plan={"sessionId": "allocated", "installationId": "roku-fixture"}), cleanup())
        self.assertTrue(trace[3]["busy"])
        self.assertEqual(["cleanup"], self.kinds(trace[4]))
        self.assertEqual("allocated", trace[4]["effects"][0]["plan"]["sessionId"])
        self.assertEqual([{"kind": "idle", "blocked": False}], trace[5]["effects"])
        self.assertFalse(trace[5]["busy"])

    def test_failed_plan_preserves_cleanup_only_stop_id_and_never_starts_video(self):
        failed = plan(ok=False, plan={"sessionId": "allocated", "installationId": "roku-fixture",
                                     "stopId": "preview-fixture-provider-stop", "persistProgress": False})
        result = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), failed)[-1]
        self.assertEqual(["cleanup"], self.kinds(result))
        self.assertEqual("preview-fixture-provider-stop", result["effects"][0]["stopId"])

    def test_malformed_successful_plan_is_cleaned_without_starting_video(self):
        for changes in ({"itemId": "other"}, {"url": "bad"}, {"streamFormat": []}, {"headers": []}):
            event = plan()
            event["plan"].update(changes)
            result = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), event)[-1]
            self.assertEqual(["cleanup"], self.kinds(result))

    def test_plans_native_owner_would_reject_are_cleaned_before_starting(self):
        for changes in ({"relativeTimeline": "true"}, {"subtitleTracks": {}},
                        {"headers": {"Bad:Header": "value"}}, {"startPositionMs": "bad"}):
            event = plan()
            event["plan"].update(changes)
            result = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), event)[-1]
            self.assertEqual(["cleanup"], self.kinds(result))

    def test_malformed_identities_never_crash_or_release_the_current_lease(self):
        for changes in ({"sourceId": []}, {"provider": {}}, {"availability": []}, {"uiAction": {}}):
            result = self.trace(focus(dict(ITEM, **changes)))[0]
            self.assertIsNone(result["state"]["wanted"])
        prefix = [focus(), {"kind": "dwell", "nowMs": 1200}]
        for event in (detail(preview=[]), detail(scope=dict(SCOPE, provider=[])), detail(scope=dict(SCOPE, sourceId=[]))):
            trace = self.trace(*prefix, event)
            self.assertEqual(trace[1]["state"], trace[2]["state"])
        prefix.extend([detail(), plan()])
        for event in (native(attempt=[]), native(mode=[]), native(state=[])):
            trace = self.trace(*prefix, event)
            self.assertEqual(trace[3]["state"], trace[4]["state"])

    def test_cleanup_from_another_scope_cannot_release_preview_barrier(self):
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(),
                           {"kind": "release", "nowMs": 1400}, native(), cleanup(scope=dict(SCOPE, generation=5)))
        self.assertEqual([], trace[-1]["effects"])
        self.assertTrue(trace[-1]["busy"])

    def test_cleanup_without_captured_scope_cannot_release_preview_barrier(self):
        event = cleanup()
        event.pop("scope")
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(),
                           {"kind": "release", "nowMs": 1400}, native(), event)
        self.assertEqual([], trace[-1]["effects"])
        self.assertTrue(trace[-1]["busy"])

    def test_late_allocated_plan_holds_detail_before_another_allocation(self):
        old = dict(SCOPE, profileId="former", generation=3)
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, plan(preview="preview-old", scope=old), detail(),
                           cleanup(preview="preview-old", scope=old))
        self.assertNotIn("preview_plan", str(trace[3]["effects"]))
        self.assertEqual("preview_plan", trace[4]["effects"][0]["purpose"])

    def test_active_replacement_waits_for_both_native_stop_and_provider_cleanup(self):
        second = dict(ITEM, itemId="202")
        prefix = [focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(), focus(second, now=1400),
                  detail(preview="preview-2", item=second, nowMs=1500), {"kind": "dwell", "nowMs": 2600}]
        for acknowledgments in ((native(), cleanup()), (cleanup(), native())):
            with self.subTest(order=acknowledgments[0]["kind"]):
                trace = self.trace(*prefix, *acknowledgments)
                self.assertEqual({"stop", "cleanup", "request", "timer"}, set(self.kinds(trace[4])))
                self.assertNotIn("request", self.kinds(trace[7]))
                self.assertEqual("preview-2", trace[8]["effects"][0]["previewId"])
                self.assertEqual("preview_plan", trace[8]["effects"][0]["purpose"])

    def test_cleanup_failure_blocks_and_retry_reuses_stop_identity(self):
        second = dict(ITEM, itemId="202")
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(), focus(second, now=1400), native(),
                           cleanup(False), detail(preview="preview-2", item=second, nowMs=2750),
                           {"kind": "dwell", "nowMs": 2800}, {"kind": "retry_cleanup", "nowMs": 2900}, cleanup(nowMs=3000))
        original = [e for e in trace[4]["effects"] if e["kind"] == "cleanup"][0]
        self.assertTrue(trace[6]["state"]["blocked"])
        self.assertEqual([{"kind": "idle", "blocked": True}], trace[6]["effects"])
        self.assertNotIn("request", self.kinds(trace[8]))
        retry = trace[9]["effects"][0]
        self.assertEqual(original["stopId"], retry["stopId"])
        self.assertEqual(original["plan"], retry["plan"])
        self.assertEqual("preview-2", trace[10]["effects"][0]["previewId"])
        self.assertEqual("preview_plan", trace[10]["effects"][0]["purpose"])

    def test_direct_plex_release_needs_native_stop_without_provider_cleanup(self):
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(session=""),
                           {"kind": "release", "nowMs": 1400}, native())
        self.assertEqual(["stop"], self.kinds(trace[4]))
        self.assertTrue(trace[4]["busy"])
        self.assertEqual([{"kind": "idle", "blocked": False}], trace[5]["effects"])

    def test_repeated_release_and_late_native_playing_do_not_escape_teardown(self):
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(), {"kind": "release", "nowMs": 1400},
                           {"kind": "release", "nowMs": 1500}, native("playing"), native(attempt="other"), cleanup(), native())
        self.assertEqual([], trace[5]["effects"])
        self.assertEqual("retiring", trace[6]["state"]["phase"])
        self.assertTrue(trace[7]["busy"])
        self.assertFalse(trace[-1]["busy"])

    def test_native_errors_release_once_without_progress_reports(self):
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(), native("error", errorCode=-3), native("error", errorCode=-3))
        self.assertEqual({"stop", "cleanup"}, set(self.kinds(trace[4])))
        self.assertEqual([], trace[5]["effects"])
        self.assertNotIn("playback_progress", str(trace))
        self.assertNotIn("persistProgress", str(trace))

    def test_latest_focus_wins_while_old_lease_is_tearing_down(self):
        second, third = dict(ITEM, itemId="202"), dict(ITEM, itemId="303")
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(), focus(second, now=1400),
                           focus(third, now=1500), detail(preview="preview-3", item=third, nowMs=1600),
                           detail(preview="preview-2", item=second, nowMs=1700),
                           {"kind": "dwell", "nowMs": 2700}, native(), cleanup(nowMs=2800))
        self.assertEqual("303", trace[-1]["effects"][0]["params"]["itemId"])

    def test_dwell_expiration_before_detail_waits_without_allocating(self):
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(nowMs=1500))
        self.assertEqual([], trace[1]["effects"])
        self.assertFalse(trace[1]["busy"])
        self.assertEqual("preview_plan", trace[2]["effects"][0]["purpose"])

    def test_duplicate_selected_focus_after_preparation_preserves_original_deadline(self):
        data = detail()["data"]
        data["versions"] = [{"versionId": "other"}, {"versionId": "selected"}]
        trace = self.trace(focus(versionId="selected"), detail(data=data, nowMs=100),
                           focus(versionId="selected", now=1000), {"kind": "dwell", "nowMs": 1200})
        self.assertEqual([], trace[2]["effects"])
        self.assertEqual(1200, trace[2]["state"]["wanted"]["dueMs"])
        self.assertEqual(1, trace[3]["effects"][0]["params"]["versionIndex"])
        self.assertEqual("preview-1", trace[3]["effects"][0]["previewId"])

    def test_duplicate_selected_version_id_ignores_changed_stale_index_hint(self):
        data = detail()["data"]
        data["versions"] = [{"versionId": "other"}, {"versionId": "selected"}]
        trace = self.trace(focus(versionId="selected", versionIndex=0), detail(data=data, nowMs=100),
                           focus(versionId="selected", versionIndex=1, now=900), {"kind": "dwell", "nowMs": 1200})
        self.assertEqual([], trace[2]["effects"])
        self.assertEqual(1200, trace[2]["state"]["wanted"]["dueMs"])
        self.assertEqual("preview-1", trace[3]["effects"][0]["previewId"])
        self.assertEqual(1, trace[3]["effects"][0]["params"]["versionIndex"])

    def test_saved_resume_is_backend_intent_and_editorial_target_for_both_providers(self):
        for provider in ("plex", "silo"):
            scope = dict(SCOPE, provider=provider, sourceId=provider + ":fixture")
            item = dict(ITEM, provider=provider, sourceId=scope["sourceId"], resumeMs=75000)
            trace = self.trace(focus(item, scope), detail(scope=scope, item=item, nowMs=100),
                               {"kind": "dwell", "nowMs": 1200}, plan(scope=scope))
            self.assertEqual(75000, trace[2]["effects"][0]["params"]["startPositionMs"])
            self.assertEqual(75000, trace[3]["effects"][0]["previewPositionMs"])

    def test_show_resolves_leaf_and_retains_original_candidate_identity(self):
        show = dict(ITEM, itemId="show-1", type="show", playable=False)
        leaf = dict(ITEM, itemId="episode-3", type="episode", resumeMs=12000)
        data = detail(item=leaf)["data"]
        data["candidateItemId"] = "show-1"
        trace = self.trace(focus(show), detail(data=data, nowMs=100), focus(show, now=900),
                           {"kind": "dwell", "nowMs": 1200})
        self.assertEqual({"itemId": "show-1", "type": "show"}, trace[0]["effects"][0]["params"])
        self.assertEqual([], trace[2]["effects"])
        self.assertEqual("show-1", trace[3]["state"]["current"]["candidateItemId"])
        self.assertEqual("episode-3", trace[3]["effects"][0]["params"]["itemId"])
        self.assertEqual(12000, trace[3]["effects"][0]["params"]["startPositionMs"])
        self.assertEqual(data, trace[3]["effects"][0]["params"]["detail"])

    def test_silo_series_alias_requests_show_episode_resolution(self):
        scope = dict(SCOPE, provider="silo", sourceId="silo:fixture")
        show = dict(ITEM, provider="silo", sourceId=scope["sourceId"], type="series")
        request = self.trace(focus(show, scope))[0]["effects"][0]
        self.assertEqual({"itemId": "101", "type": "show"}, request["params"])

    def test_show_rejects_unresolved_wrong_candidate_foreign_or_non_episode_detail(self):
        show = dict(ITEM, itemId="show-1", type="show")
        leaf = dict(ITEM, itemId="episode-3", type="episode")
        valid = detail(item=leaf)["data"]
        valid["candidateItemId"] = "show-1"
        broken = [dict(valid, candidateItemId="other"), dict(valid, candidateItemId=[]),
                  dict(valid, item=dict(leaf, sourceId="plex:other")),
                  dict(valid, item=dict(leaf, type="movie")), dict(valid, item=show),
                  dict(valid, item=dict(leaf, playable=False))]
        for data in broken:
            result = self.trace(focus(show), detail(data=data, nowMs=1300))[-1]
            self.assertNotIn("request", self.kinds(result))
            self.assertFalse(result["busy"])

    def test_supplied_fresh_detail_skips_read_but_waits_original_dwell(self):
        data = detail()["data"]
        trace = self.trace(focus(detail=data), focus(detail=data, now=900), {"kind": "dwell", "nowMs": 1200})
        self.assertEqual([{"kind": "timer", "milliseconds": 1200}], trace[0]["effects"])
        self.assertEqual("dwell", trace[0]["state"]["phase"])
        self.assertEqual([], trace[1]["effects"])
        self.assertEqual(data, trace[2]["effects"][0]["params"]["detail"])

    def test_supplied_detail_must_match_candidate_source_item_and_selected_version(self):
        valid = detail()["data"]
        broken = [dict(valid, candidateItemId="other"), dict(valid, item=dict(ITEM, itemId="other")),
                  dict(valid, item=dict(ITEM, sourceId="plex:other")),
                  dict(valid, versions=[{"versionId": "other"}])]
        for data in broken:
            trace = self.trace(focus(detail=data, versionId="version-1"), {"kind": "dwell", "nowMs": 1200})
            self.assertIsNone(trace[0]["state"]["wanted"])
            self.assertNotIn("request", self.kinds(trace[0]))
            self.assertNotIn("request", self.kinds(trace[1]))

    def test_startup_timeout_retires_waiting_native_and_provider_receipts(self):
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(),
                           native("stopping", errorCode=-1001), cleanup(), native())
        self.assertEqual(["cleanup"], self.kinds(trace[4]))
        self.assertEqual("retiring", trace[4]["state"]["phase"])
        self.assertTrue(trace[4]["busy"])
        self.assertTrue(trace[5]["busy"])
        self.assertFalse(trace[6]["busy"])
        self.assertEqual("idle", trace[6]["state"]["phase"])

    def test_unseekable_or_before_offset_editorial_target_abandons_provider_plan(self):
        for changes in ({"canSeekAnywhere": False, "startPositionMs": 0},
                        {"relativeTimeline": True, "timelineOffsetMs": 50000},
                        {"canSeekAnywhere": "true"}):
            event = plan()
            event["plan"].update(changes)
            result = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), event)[-1]
            self.assertEqual(["cleanup"], self.kinds(result))
            self.assertTrue(result["busy"])

    def test_scope_switch_preserves_original_cleanup_scope(self):
        switched = dict(SCOPE, profileId="other", generation=5)
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, detail(), plan(), focus(scope=switched, now=1400))
        effect = next(e for e in trace[-1]["effects"] if e["kind"] == "cleanup")
        self.assertEqual(SCOPE, effect["scope"])
        self.assertEqual(switched, trace[-1]["state"]["wanted"]["scope"])

    def test_late_plan_is_abandoned_under_original_scope_without_starting(self):
        old = dict(SCOPE, profileId="former", generation=3)
        trace = self.trace(focus(), {"kind": "dwell", "nowMs": 1200}, plan(preview="preview-old", scope=old))
        self.assertEqual(["cleanup"], self.kinds(trace[-1]))
        self.assertEqual(old, trace[-1]["effects"][0]["scope"])
        self.assertEqual("preview-old", trace[-1]["effects"][0]["previewId"])
        self.assertTrue(trace[-1]["busy"])


if __name__ == "__main__":
    unittest.main()
