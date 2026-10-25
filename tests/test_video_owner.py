"""Execute the single native Video owner's production state policy."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/VideoOwnerPolicy.brs"


def request(attempt="one", mode="playback", **extra):
    return {"attemptId": attempt, "mode": mode, "plan": {
        "url": "https://fixture.example.test/media.m3u8", "streamFormat": "hls",
        "headers": {"X-Plex-Token": "fixture-secret"}, "startPositionMs": 12500,
        "timelineOffsetMs": 900000, "relativeTimeline": True,
    }, **extra}


class VideoOwnerTests(unittest.TestCase):
    def native_integer_policy(self, name, arguments, integer_type="roInteger"):
        """Alias only native Type(); every supplied numeric value stays numeric."""
        with tempfile.TemporaryDirectory(prefix="silo-native-integer-") as directory:
            policy = Path(directory) / "policy.brs"
            source = POLICY.read_text().replace("type(", "FixtureNativeType(")
            source += f'''
function FixtureNativeType(value as Dynamic) as String
    kind = Type(value)
    if kind = "Integer" or kind = "roInt" then return "{integer_type}"
    return kind
end function
'''
            policy.write_text(source)
            return run_function(policy, name, arguments, root=Path(directory))

    def transition(self, owner, event):
        self.assertTrue(POLICY.exists(), "single Video owner policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owner-") as directory:
            return run_function(POLICY, "VideoOwnerTransition", [owner, event], root=Path(directory))

    def start(self, attempt="one", mode="playback", **extra):
        return self.transition(None, {"kind": "request", "request": request(attempt, mode, **extra)})

    def test_idle_request_starts_one_owner_with_default_hd_bounds(self):
        result = self.start()
        self.assertEqual(["start"], [effect["action"] for effect in result["effects"]])
        self.assertEqual("starting", result["owner"]["phase"])
        self.assertEqual({"x": 0, "y": 0, "width": 1280, "height": 720}, result["owner"]["active"]["bounds"])

    def test_native_associative_array_integer_type_admits_actual_numeric_plan_fields(self):
        for integer_type in ("roInteger", "roLongInteger"):
            with self.subTest(integer_type=integer_type):
                entry = request(mode="preview", previewPositionMs=945000,
                    bounds={"x": 7, "y": 7, "width": 320, "height": 180})
                result = self.native_integer_policy("VideoOwnerTransition", [None, {
                    "kind": "request", "request": entry}], integer_type)
                self.assertTrue(result["accepted"])
                self.assertEqual(45000, result["effects"][0]["request"]["plan"]["startPositionMs"])
                self.assertEqual(7, result["owner"]["active"]["bounds"]["x"])

    def test_native_numeric_type_alias_keeps_finite_and_non_number_guards(self):
        for integer_type in ("roInteger", "roLongInteger"):
            for value in (True, "7", {}, [], 2000000000000, 1e308):
                with self.subTest(integer_type=integer_type, value=value):
                    self.assertFalse(self.native_integer_policy("VoIsNumber", [value], integer_type))

    def test_invalid_requests_never_replace_an_active_owner(self):
        owner = self.start()["owner"]
        bad = [None, {}, request(mode="unknown"), request("https://secret.test/token")]
        for key, value in (("url", ""), ("url", "file:/movie"), ("headers", []),
                           ("startPositionMs", -1), ("relativeTimeline", "true"),
                           ("subtitleTracks", {})):
            entry = request("two")
            entry["plan"][key] = value
            bad.append(entry)
        bad.append(request("two", bounds={"x": 0, "y": 0, "width": 0, "height": 720}))
        bad.append(request("two", bounds="bad"))
        for entry in bad:
            with self.subTest(entry=entry):
                result = self.transition(owner, {"kind": "request", "request": entry})
                self.assertFalse(result["accepted"])
                self.assertEqual(owner, result["owner"])
                self.assertEqual([], result["effects"])

    def test_header_line_injection_is_rejected(self):
        for headers in ({"X-Test": "a\r\nb"}, {"Bad:Header": "value"}, {"X-Test": 7}):
            entry = request()
            entry["plan"]["headers"] = headers
            self.assertFalse(self.transition(None, {"kind": "request", "request": entry})["accepted"])

    def test_preview_editorial_target_uses_only_explicit_relative_timeline_offset(self):
        for relative, expected in ((True, 45000), (False, 945000), (None, 945000)):
            with self.subTest(relative=relative):
                entry = request(mode="preview", previewPositionMs=945000)
                entry["plan"].update({"canSeekAnywhere": True, "relativeTimeline": relative})
                if relative is None:
                    del entry["plan"]["relativeTimeline"]
                result = self.transition(None, {"kind": "request", "request": entry})
                self.assertTrue(result["accepted"])
                self.assertEqual(expected, result["effects"][0]["request"]["plan"]["startPositionMs"])
                self.assertEqual(945000, result["owner"]["active"]["previewPositionMs"])

    def test_preview_target_rejects_unreachable_routes_instead_of_changing_editorial_intent(self):
        for target, seekable, expected in ((912500, False, True), (945000, False, False),
                                           (45000, True, False), (900000, True, True)):
            with self.subTest(target=target, seekable=seekable):
                entry = request(mode="preview", previewPositionMs=target)
                entry["plan"]["canSeekAnywhere"] = seekable
                result = self.transition(None, {"kind": "request", "request": entry})
                self.assertEqual(expected, result["accepted"])
                if expected:
                    expected_start = 12500 if not seekable else 0
                    self.assertEqual(expected_start, result["owner"]["active"]["plan"]["startPositionMs"])
                else:
                    self.assertEqual([], result["effects"])
                    self.assertIsNone(result["owner"]["active"])

    def test_preview_target_and_seekability_require_safe_core_types(self):
        for target in (-1, "45000", {}, True):
            with self.subTest(target=target):
                entry = request(mode="preview", previewPositionMs=target)
                self.assertFalse(self.transition(None, {"kind": "request", "request": entry})["accepted"])
        for seekable in ("false", 0, {}, None):
            with self.subTest(seekable=seekable):
                entry = request(mode="preview")
                entry["plan"]["canSeekAnywhere"] = seekable
                self.assertFalse(self.transition(None, {"kind": "request", "request": entry})["accepted"])

    def test_nonseekable_native_owner_rejects_local_seek_command(self):
        entry = request(mode="preview")
        entry["plan"]["canSeekAnywhere"] = False
        owner = self.transition(None, {"kind": "request", "request": entry})["owner"]
        result = self.transition(owner, {"kind": "command", "command": {
            "action": "seek", "attemptId": "one", "positionMs": 45000}})
        self.assertFalse(result["accepted"])
        self.assertEqual([], result["effects"])
        self.assertEqual(owner, result["owner"])

    def test_native_preview_mapping_preserves_provider_resume_and_absent_target_behavior(self):
        probe = '''
function RequestProbe(request as Object) as Object
    native = VideoOwnerRequest(request)
    return {providerStartMs:request.plan.startPositionMs,nativeStartMs:native.plan.startPositionMs}
end function
'''
        with tempfile.TemporaryDirectory(prefix="silo-preview-start-") as directory:
            boundary = Path(directory) / "request_probe.brs"
            boundary.write_text(probe)
            for mode, target, expected in (("preview", 945000, 45000), ("prebuffer", 945000, 45000),
                                           ("playback", 945000, 12500), ("preview", None, 12500)):
                with self.subTest(mode=mode, target=target):
                    entry = request(mode=mode)
                    if target is not None:
                        entry["previewPositionMs"] = target
                    result = run_function([POLICY, boundary], "RequestProbe", [entry], root=Path(directory))
                    self.assertEqual({"providerStartMs": 12500, "nativeStartMs": expected}, result)

    def test_malformed_discriminators_and_flags_are_rejected_without_a_runtime_error(self):
        owner = self.start()["owner"]
        for mode in (7, [], {}, False):
            self.assertFalse(self.transition(owner, {"kind": "request", "request": request("two", mode)})["accepted"])
        for event in ({"kind": []}, {"kind": "command", "command": {"action": 3}},
                      {"kind": "command", "command": {"action": "stop", "attemptId": []}},
                      {"kind": "native", "attemptId": "one", "state": []},
                      {"kind": "native", "attemptId": 7, "state": "playing", "clipId": 7}):
            self.assertFalse(self.transition(owner, event)["accepted"])
        native = self.transition(owner, {"kind": "native", "attemptId": "one", "state": "buffering", "clipId": 7, "prebufferDone": "true"})
        self.assertEqual("starting", native["owner"]["phase"])

    def test_seek_pause_and_resume_require_current_attempt_and_cannot_run_while_stopping(self):
        owner = self.start()["owner"]
        for action, extra in (("seek", {"positionMs": 12500}), ("pause", {}), ("resume", {})):
            command = {"kind": "command", "command": {"action": action, "attemptId": "one", **extra}}
            result = self.transition(owner, command)
            self.assertEqual(action, result["effects"][0]["action"])
            if action == "seek":
                self.assertEqual(12.5, result["effects"][0]["position"])
            stopping = self.transition(owner, {"kind": "command", "command": {"action": "stop"}})["owner"]
            self.assertFalse(self.transition(stopping, command)["accepted"])

    def test_preview_promotion_accepts_explicit_bounds_and_rejects_invalid_bounds(self):
        owner = self.start(mode="preview")["owner"]
        command = {"action": "promote", "attemptId": "one", "bounds": {"x": 0, "y": 0, "width": 960, "height": 540}}
        result = self.transition(owner, {"kind": "command", "command": command})
        self.assertEqual(960, result["owner"]["active"]["bounds"]["width"])
        command["bounds"]["height"] = -1
        self.assertFalse(self.transition(owner, {"kind": "command", "command": command})["accepted"])

    def test_replacement_waits_for_stopped_and_only_latest_request_starts(self):
        owner = self.start()["owner"]
        second = self.transition(owner, {"kind": "request", "request": request("two", "prebuffer")})
        self.assertEqual(["stop"], [effect["action"] for effect in second["effects"]])
        self.assertEqual("one", second["owner"]["active"]["attemptId"])
        third = self.transition(second["owner"], {"kind": "request", "request": request("three", "preview")})
        self.assertEqual([], third["effects"])
        stopped = self.transition(third["owner"], {"kind": "native", "attemptId": "one", "state": "stopped", "clipId": 7})
        self.assertEqual(["cleanup", "start"], [effect["action"] for effect in stopped["effects"]])
        self.assertEqual("three", stopped["owner"]["active"]["attemptId"])

    def test_stop_retires_queued_request_and_is_idempotent(self):
        owner = self.start()["owner"]
        owner = self.transition(owner, {"kind": "request", "request": request("two")})["owner"]
        result = self.transition(owner, {"kind": "command", "command": {"action": "stop"}})
        self.assertIsNone(result["owner"]["queued"])
        self.assertEqual([{"action": "cancelled", "attemptId": "two", "mode": "playback"}], result["effects"])
        stopped = self.transition(result["owner"], {"kind": "native", "attemptId": "one", "state": "stopped", "clipId": 7})
        self.assertEqual(["cleanup"], [effect["action"] for effect in stopped["effects"]])
        duplicate = self.transition(stopped["owner"], {"kind": "native", "attemptId": "one", "state": "stopped", "clipId": 7})
        self.assertEqual([], duplicate["effects"])

    def test_stop_targeting_queued_attempt_cancels_it_while_active_attempt_finishes_stopping(self):
        owner = self.start()["owner"]
        owner = self.transition(owner, {"kind": "native", "attemptId": "one", "state": "playing", "clipId": 7})["owner"]
        owner = self.transition(owner, {"kind": "command", "command": {"action": "stop", "attemptId": "one"}})["owner"]
        owner = self.transition(owner, {"kind": "request", "request": request("two")})["owner"]
        cancelled = self.transition(owner, {"kind": "command", "command": {"action": "stop", "attemptId": "two"}})
        self.assertTrue(cancelled["accepted"])
        self.assertIsNone(cancelled["owner"]["queued"])
        self.assertEqual("one", cancelled["owner"]["active"]["attemptId"])
        self.assertEqual("stopping", cancelled["owner"]["phase"])
        self.assertEqual([{"action": "cancelled", "attemptId": "two", "mode": "playback"}], cancelled["effects"])
        stopped = self.transition(cancelled["owner"], {"kind": "native", "attemptId": "one", "state": "stopped", "clipId": 7})
        self.assertEqual(["cleanup"], [effect["action"] for effect in stopped["effects"]])
        self.assertIsNone(stopped["owner"]["active"])
        self.assertEqual("idle", stopped["owner"]["phase"])

    def test_stop_targeting_replaced_queue_entry_cannot_cancel_the_newest_request(self):
        owner = self.start()["owner"]
        owner = self.transition(owner, {"kind": "request", "request": request("two")})["owner"]
        owner = self.transition(owner, {"kind": "request", "request": request("three")})["owner"]
        stale = self.transition(owner, {"kind": "command", "command": {"action": "stop", "attemptId": "two"}})
        self.assertFalse(stale["accepted"])
        self.assertEqual(owner, stale["owner"])
        stopped = self.transition(stale["owner"], {"kind": "native", "attemptId": "one", "state": "stopped", "clipId": 7})
        self.assertEqual("three", stopped["owner"]["active"]["attemptId"])

    def test_unscoped_stop_cancels_all_queued_work_without_reissuing_native_stop(self):
        for native_playing in (False, True):
            with self.subTest(native_playing=native_playing):
                owner = self.start()["owner"]
                if native_playing:
                    owner = self.transition(owner, {"kind": "native", "attemptId": "one", "state": "playing", "clipId": 7})["owner"]
                replacement = self.transition(owner, {"kind": "request", "request": request("two")})
                self.assertEqual(["stop"], [effect["action"] for effect in replacement["effects"]])
                owner = self.transition(replacement["owner"], {"kind": "request", "request": request("three")})["owner"]
                stopped_request = self.transition(owner, {"kind": "command", "command": {"action": "stop"}})
                self.assertTrue(stopped_request["accepted"])
                self.assertIsNone(stopped_request["owner"]["queued"])
                self.assertEqual([{"action": "cancelled", "attemptId": "three", "mode": "playback"}], stopped_request["effects"])
                acknowledged = self.transition(stopped_request["owner"], {"kind": "native", "attemptId": "one", "state": "stopped", "clipId": 7})
                self.assertEqual(["cleanup"], [effect["action"] for effect in acknowledged["effects"]])
                self.assertIsNone(acknowledged["owner"]["active"])
                late = self.transition(acknowledged["owner"], {"kind": "native", "attemptId": "three", "state": "playing", "clipId": 8})
                self.assertFalse(late["accepted"])
                self.assertEqual([], late["effects"])

    def test_queued_preview_stop_emits_safe_terminal_effect_without_touching_native_owner(self):
        owner = self.start()["owner"]
        owner = self.transition(owner, {"kind": "native", "attemptId": "one", "state": "playing", "clipId": 7})["owner"]
        owner = self.transition(owner, {"kind": "request", "request": request("two", "preview")})["owner"]
        cancelled = self.transition(owner, {"kind": "command", "command": {"action": "stop", "attemptId": "two"}})
        self.assertEqual([{"action": "cancelled", "attemptId": "two", "mode": "preview"}], cancelled["effects"])
        self.assertNotIn("fixture-secret", str(cancelled["effects"]))
        self.assertNotIn("https:", str(cancelled["effects"]))
        self.assertEqual(owner["active"], cancelled["owner"]["active"])
        self.assertEqual(owner["clipId"], cancelled["owner"]["clipId"])
        self.assertEqual("stopping", cancelled["owner"]["nativeState"])

    def test_stale_attempt_and_retired_clip_cannot_update_new_owner(self):
        first = self.start()["owner"]
        first = self.transition(first, {"kind": "native", "attemptId": "one", "state": "playing", "clipId": 7})["owner"]
        pending = self.transition(first, {"kind": "request", "request": request("two")})["owner"]
        owner = self.transition(pending, {"kind": "native", "attemptId": "one", "state": "stopped", "clipId": 7})["owner"]
        for attempt, clip in (("one", 8), ("two", 7)):
            stale = self.transition(owner, {"kind": "native", "attemptId": attempt, "state": "playing", "clipId": clip})
            self.assertFalse(stale["accepted"])
            self.assertEqual(owner, stale["owner"])
        fresh = self.transition(owner, {"kind": "native", "attemptId": "two", "state": "playing", "clipId": 8})
        self.assertEqual(8, fresh["owner"]["clipId"])
        self.assertEqual("playing", fresh["owner"]["nativeState"])

    def test_late_playing_during_stop_cannot_escape_stopping(self):
        owner = self.transition(self.start()["owner"], {"kind": "command", "command": {"action": "stop"}})["owner"]
        result = self.transition(owner, {"kind": "native", "attemptId": "one", "state": "playing", "clipId": 7})
        self.assertFalse(result["accepted"])
        self.assertEqual("stopping", result["owner"]["phase"])

    def test_promotion_keeps_content_owner_and_sets_full_screen_bounds(self):
        owner = self.start(mode="prebuffer", bounds={"x": 20, "y": 30, "width": 320, "height": 180})["owner"]
        result = self.transition(owner, {"kind": "command", "command": {"action": "promote", "attemptId": "one"}})
        self.assertEqual(["promote"], [effect["action"] for effect in result["effects"]])
        self.assertEqual("playback", result["owner"]["active"]["mode"])
        self.assertEqual(1280, result["owner"]["active"]["bounds"]["width"])
        again = self.transition(result["owner"], {"kind": "command", "command": {"action": "promote", "attemptId": "one"}})
        self.assertEqual([], again["effects"])

    def test_commands_and_timers_are_attempt_scoped(self):
        owner = self.start()["owner"]
        for event in ({"kind": "deadline", "attemptId": "retired"},
                      {"kind": "cap", "attemptId": "retired"},
                      {"kind": "command", "command": {"action": "promote", "attemptId": "retired"}},
                      {"kind": "command", "command": {"action": "seek", "attemptId": "retired", "positionMs": 10}}):
            result = self.transition(owner, event)
            self.assertFalse(result["accepted"])
            self.assertEqual(owner, result["owner"])

    def test_deadline_and_preview_cap_stop_once(self):
        for kind, mode in (("deadline", "playback"), ("cap", "preview"), ("cap", "prebuffer")):
            owner = self.start(mode=mode)["owner"]
            result = self.transition(owner, {"kind": kind, "attemptId": "one"})
            self.assertEqual(["stop"], [effect["action"] for effect in result["effects"]])
            self.assertEqual("stopping", result["owner"]["phase"])
            repeated = self.transition(result["owner"], {"kind": kind, "attemptId": "one"})
            self.assertEqual([], repeated["effects"])

    def test_status_is_a_closed_safe_primitive_snapshot(self):
        owner = self.start()["owner"]
        owner = self.transition(owner, {"kind": "native", "attemptId": "one", "state": "playing", "clipId": 7})["owner"]
        snapshot = {"clipId": 7, "position": 12.5, "duration": 120, "positionInfo": {"epoch": 0, "video": 12.4, "clip_id": 7},
                    "bufferingStatus": {"prebufferDone": True, "actualStart": 12}, "errorCode": -3,
                    "errorMsg": "https://secret.test/?token=fixture-secret", "streamInfo": {"streamUrl": "secret"}}
        result = run_function(POLICY, "VideoOwnerStatus", [owner, snapshot])
        self.assertEqual("one", result["attemptId"])
        self.assertEqual(12.4, result["renderedPosition"])
        self.assertEqual(7, result["renderedClipId"])
        self.assertEqual(0, result["renderedEpoch"])
        self.assertTrue(result["prebufferDone"])
        self.assertEqual(12, result["actualStart"])
        self.assertNotIn("secret", str(result))
        self.assertTrue(all(isinstance(value, (str, int, float, bool)) for value in result.values()))
        malformed = deepcopy(snapshot)
        malformed.update({"position": "bad", "errorCode": "unsafe", "clipId": 8})
        malformed["positionInfo"] = {"epoch": 0, "video": 50, "clip_id": 8}
        stale = run_function(POLICY, "VideoOwnerStatus", [owner, malformed])
        self.assertEqual(-1, stale["position"])
        self.assertEqual(-1, stale["renderedPosition"])
        self.assertEqual(0, stale["errorCode"])

    def test_startup_timing_projection_uses_only_whitelisted_bounded_native_numbers(self):
        owner = self.transition(self.start()["owner"], {"kind": "native", "attemptId": "one",
            "state": "playing", "clipId": 7})["owner"]
        snapshot = {"clipId": 7, "timeToStartStreaming": 7.638, "playStartInfo": {
            "total_dur": 7.6, "manifest_dur": 0.738, "prebuf_dur": 6.862,
            "drm_load_dur": 0, "drm_lic_acq_dur": 0.1,
            "manifest_start": 1, "streamUrl": "https://private.test", "dbgmsg": "fixture-secret"}}
        result = run_function(POLICY, "VideoOwnerStatus", [owner, snapshot])
        expected = {"startupNativeMs": 7638, "startupTotalMs": 7600, "startupManifestMs": 738,
                    "startupPrebufferMs": 6862, "startupDrmLoadMs": 0, "startupDrmLicenseMs": 100}
        self.assertEqual(expected, {name: result.get(name) for name in expected})
        self.assertNotIn("_start", str(result))
        self.assertNotIn("fixture-secret", str(result))
        self.assertNotIn("https:", str(result))
        self.assertTrue(all(isinstance(value, (str, int, float, bool)) for value in result.values()))

    def test_startup_timings_are_unknown_outside_matching_playing_owner(self):
        for state, clip in (("buffering", 7), ("paused", 7), ("playing", 8)):
            with self.subTest(state=state, clip=clip):
                owner = self.transition(self.start()["owner"], {"kind": "native", "attemptId": "one",
                    "state": state, "clipId": 7})["owner"]
                snapshot = {"clipId": clip, "timeToStartStreaming": 7, "playStartInfo": {
                    "total_dur": 7, "manifest_dur": 1, "prebuf_dur": 6, "drm_load_dur": 0, "drm_lic_acq_dur": 0}}
                result = run_function(POLICY, "VideoOwnerStatus", [owner, snapshot])
                for name in ("Native", "Total", "Manifest", "Prebuffer", "DrmLoad", "DrmLicense"):
                    self.assertEqual(-1, result.get("startup" + name + "Ms"))

    def test_startup_timing_numbers_reject_malformed_outliers_and_keep_native_integer_aliases(self):
        owner = self.transition(self.start()["owner"], {"kind": "native", "attemptId": "one",
            "state": "playing", "clipId": 7})["owner"]
        for value in (True, "7", {}, -1, 121, 1e308):
            with self.subTest(value=value):
                snapshot = {"clipId": 7, "timeToStartStreaming": value, "playStartInfo": {
                    "total_dur": value, "manifest_dur": value, "prebuf_dur": value,
                    "drm_load_dur": value, "drm_lic_acq_dur": value}}
                result = run_function(POLICY, "VideoOwnerStatus", [owner, snapshot])
                for name in ("Native", "Total", "Manifest", "Prebuffer", "DrmLoad", "DrmLicense"):
                    self.assertEqual(-1, result.get("startup" + name + "Ms"))
        for alias in ("roInteger", "roLongInteger"):
            with self.subTest(alias=alias):
                result = self.native_integer_policy("VideoOwnerStatus", [owner, {
                    "clipId": 7, "timeToStartStreaming": 7, "playStartInfo": {"total_dur": 7}}], alias)
                self.assertEqual(7000, result.get("startupNativeMs"))
                self.assertEqual(7000, result.get("startupTotalMs"))


if __name__ == "__main__":
    unittest.main()
