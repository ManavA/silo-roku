"""Native track handles fence transient Roku IDs and report observed selections."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/NativeTrackPolicy.brs"


def bind(attempt="play-1", version="version-1", mode="playback", caption="Instant replay"):
    return {"kind": "bind", "attemptId": attempt, "versionId": version, "mode": mode, "captionMode": caption}


def audio():
    return [{"Track": "native-a1", "Name": "English AAC", "Language": "eng"},
            {"Track": "native-a2", "Name": "Spanish AAC", "Language": "spa"}]


def subtitles():
    return [{"TrackName": "https://fixture.test/cc.vtt?signature=private-fixture", "Description": "English", "Language": "eng"}]


def sample(now=0, **changes):
    return {"kind": "sample", "attemptId": "play-1", "versionId": "version-1", "mode": "playback",
            "clipId": 7, "state": "playing", "errorCode": 0, "captionMode": "Instant replay",
            "audio": audio(), "subtitles": subtitles(), "currentAudioTrack": "native-a1",
            "currentSubtitleTrack": subtitles()[0]["TrackName"], "nowMs": now, **changes}


def command(command_id=1, kind="audio", intent="select", handle="a-1-1", **changes):
    return {"kind": "command", "nowMs": 100,
            "command": {"commandId": command_id, "attemptId": "play-1", "versionId": "version-1", "clipId": 7,
                        "inventoryRevision": 1, "kind": kind, "intent": intent, "handle": handle, **changes}}


class NativeTrackPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "native track policy is missing")
        return run_function(POLICY, name, list(args))

    def trace(self, *events, integer_alias=None):
        self.assertTrue(POLICY.is_file(), "native track policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-native-tracks-") as directory:
            script = Path(directory) / "policy.brs"
            source = POLICY.read_text()
            facade = ""
            if integer_alias:
                source = source.replace("type(", "NtFixtureType(")
                facade = f'''function NtFixtureType(value as Dynamic) as String
    kind = Type(value)
    if kind = "Integer" or kind = "roInt" then return "{integer_alias}"
    return kind
end function
'''
            script.write_text(source + facade + '''
function NtFixtureTrace(events as Object) as Object
    state = NativeTrackCreate()
    trace = []
    for each event in events
        decision = NativeTrackReduce(state,event)
        state = decision.state
        decision["status"] = NativeTrackStatus(state)
        trace.Push(decision)
    end for
    return trace
end function
''')
            return run_function(script, "NtFixtureTrace", [events], root=Path(directory))

    def test_inventory_publishes_only_transient_handles_and_actual_selected_flags(self):
        result = self.trace(bind(), sample())[-1]
        status = result["status"]
        self.assertTrue(status["available"])
        self.assertEqual(("play-1", "version-1", 7, 1), tuple(status[key]
                         for key in ("attemptId", "versionId", "clipId", "inventoryRevision")))
        self.assertEqual([{"handle": "a-1-0", "label": "English AAC", "selected": True},
                          {"handle": "a-1-1", "label": "Spanish AAC", "selected": False}], status["audio"])
        self.assertEqual("a-1-0", status["currentAudioHandle"])
        self.assertEqual("s-1-0", status["currentSubtitleHandle"])
        for raw in ("native-a1", "native-a2", "https:", "private-fixture", "TrackName"):
            self.assertNotIn(raw, str(status))

    def test_select_issues_only_private_field_instruction_without_claiming_success(self):
        result = self.trace(bind(), sample(), command())[-1]
        self.assertTrue(result["accepted"])
        self.assertEqual("native-a2", next(effect["trackId"] for effect in result["effects"] if effect["kind"] == "audio"))
        self.assertEqual("a-1-0", result["status"]["currentAudioHandle"])
        self.assertEqual("issued", result["status"]["lastCommand"]["result"])
        self.assertEqual({"commandId": 1, "kind": "audio", "intent": "select", "handle": "a-1-1"}, result["status"]["pending"])
        self.assertTrue(any(effect["kind"] == "timer" and effect["milliseconds"] == 5000 for effect in result["effects"]))

    def test_audio_fallback_is_observed_then_timeout_does_not_manufacture_requested_selection(self):
        tick = {"kind": "tick", "attemptId": "play-1", "versionId": "version-1", "clipId": 7,
                "inventoryRevision": 1, "commandId": 1, "nowMs": 5100}
        trace = self.trace(bind(), sample(), command(), sample(now=1000), tick)
        self.assertEqual("a-1-0", trace[3]["status"]["currentAudioHandle"])
        self.assertIsNotNone(trace[3]["status"]["pending"])
        self.assertEqual("not_selected", trace[4]["status"]["lastCommand"]["result"])
        self.assertIsNone(trace[4]["status"]["pending"])
        self.assertEqual("a-1-0", trace[4]["status"]["currentAudioHandle"])

    def test_actual_native_track_change_completes_pending_selection(self):
        result = self.trace(bind(), sample(), command(), sample(now=200, currentAudioTrack="native-a2"))[-1]
        self.assertEqual("a-1-1", result["status"]["currentAudioHandle"])
        self.assertTrue(result["status"]["audio"][1]["selected"])
        self.assertEqual("applied", result["status"]["lastCommand"]["result"])
        self.assertIsNone(result["status"]["pending"])

    def test_observed_already_selected_lane_is_applied_without_write_or_timer(self):
        for current, request in ((sample(), command(handle="a-1-0")),
                                 (sample(captionMode="Off"), command(kind="subtitle", intent="off", handle="")),
                                 (sample(captionMode="On"), command(kind="subtitle", handle="s-1-0"))):
            with self.subTest(request=request):
                result = self.trace(bind(), current, request)[-1]
                self.assertTrue(result["accepted"])
                self.assertEqual([], result["effects"])
                self.assertEqual("applied", result["status"]["lastCommand"]["result"])
                self.assertIsNone(result["status"]["pending"])

    def test_scope_clip_revision_and_unknown_handle_commands_are_rejected(self):
        for changes in ({"attemptId": "other"}, {"versionId": "other"}, {"clipId": 8},
                        {"inventoryRevision": 0}, {"handle": "native-a2"}, {"handle": "a-1-99"}):
            with self.subTest(changes=changes):
                result = self.trace(bind(), sample(), command(**changes))[-1]
                self.assertFalse(result["accepted"])
                self.assertEqual([], result["effects"])
                self.assertEqual("a-1-0", result["status"]["currentAudioHandle"])

    def test_preview_startup_stopping_error_and_missing_version_fail_closed(self):
        pairs = [(bind(mode="preview"), sample(mode="preview")), (bind(), sample(state="buffering")),
                 (bind(), sample(state="stopping")), (bind(), sample(state="error", errorCode=-3)),
                 (bind(version=""), sample(versionId=""))]
        for start, current in pairs:
            with self.subTest(mode=start["mode"], state=current["state"]):
                result = self.trace(start, current, command(versionId=start["versionId"]))[-1]
                self.assertFalse(result["status"]["available"])
                self.assertFalse(result["accepted"])
                self.assertEqual([], result["effects"])

    def test_duplicate_and_out_of_order_command_ids_cannot_write_again_across_attempts(self):
        trace = self.trace(bind(), sample(), command(2), command(2), command(1),
                           sample(currentAudioTrack="native-a2"), bind("play-2"),
                           sample(attemptId="play-2"), command(2, attemptId="play-2", inventoryRevision=3))
        self.assertFalse(trace[3]["accepted"])
        self.assertEqual([], trace[3]["effects"])
        self.assertFalse(trace[4]["accepted"])
        self.assertFalse(trace[-1]["accepted"])

    def test_repeated_target_does_not_restart_pending_deadline_and_other_select_is_busy(self):
        trace = self.trace(bind(), sample(), command(1), command(2),
                           command(3, kind="subtitle", handle="s-1-0"))
        self.assertFalse(trace[3]["accepted"])
        self.assertEqual([], trace[3]["effects"])
        self.assertEqual("duplicate", trace[3]["status"]["lastCommand"]["result"])
        self.assertFalse(trace[4]["accepted"])
        self.assertEqual("busy", trace[4]["status"]["lastCommand"]["result"])
        self.assertEqual(1, trace[4]["status"]["pending"]["commandId"])

    def test_subtitle_off_works_without_inventory_and_preserves_actual_lane_when_present(self):
        empty = sample(audio=[], subtitles=[], currentAudioTrack="", currentSubtitleTrack="", captionMode="On")
        trace = self.trace(bind(caption="On"), empty, command(kind="subtitle", intent="off", handle=""),
                           sample(audio=[], subtitles=[], currentAudioTrack="", currentSubtitleTrack="", captionMode="Off", now=200))
        self.assertTrue(trace[2]["accepted"])
        self.assertEqual(["caption", "timer"], [effect["kind"] for effect in trace[2]["effects"]])
        self.assertEqual("Off", trace[2]["effects"][0]["mode"])
        self.assertEqual("applied", trace[3]["status"]["lastCommand"]["result"])
        present = self.trace(bind(), sample(captionMode="Off"))[-1]["status"]
        self.assertEqual("s-1-0", present["currentSubtitleHandle"])
        self.assertFalse(present["subtitles"][0]["selected"])

    def test_caption_on_requires_actual_subtitle_and_caption_mode_confirmation(self):
        trace = self.trace(bind(caption="Off"), sample(captionMode="Off", currentSubtitleTrack=""),
                           command(kind="subtitle", handle="s-1-0"),
                           sample(now=200, captionMode="On", currentSubtitleTrack=""), sample(now=300, captionMode="On"))
        self.assertTrue(trace[2]["accepted"])
        self.assertTrue(any(effect["kind"] == "subtitle" for effect in trace[2]["effects"]))
        self.assertTrue(any(effect["kind"] == "caption" and effect["mode"] == "On" for effect in trace[2]["effects"]))
        self.assertIsNotNone(trace[3]["status"]["pending"])
        self.assertEqual("applied", trace[4]["status"]["lastCommand"]["result"])

    def test_auto_is_unsupported_and_no_requested_empty_id_is_written(self):
        result = self.trace(bind(), sample(), command(kind="subtitle", intent="auto", handle=""))[-1]
        self.assertFalse(result["accepted"])
        self.assertFalse(result["status"]["autoSupported"])
        self.assertEqual("unsupported", result["status"]["lastCommand"]["result"])
        self.assertEqual([], result["effects"])

    def test_teardown_restores_only_app_changed_caption_mode_once(self):
        trace = self.trace(bind(caption="When mute"), sample(captionMode="When mute"),
                           command(kind="subtitle", intent="off", handle=""), {"kind": "retire"}, {"kind": "retire"})
        restores = [effect for effect in trace[3]["effects"] if effect["kind"] == "caption"]
        self.assertEqual([{"kind": "caption", "mode": "When mute"}], restores)
        self.assertEqual([], trace[4]["effects"])
        untouched = self.trace(bind(), sample(), {"kind": "retire"})[-1]
        self.assertFalse(any(effect["kind"] == "caption" for effect in untouched["effects"]))
        self.assertFalse(untouched["status"]["available"])

    def test_identical_samples_and_actual_selection_updates_do_not_change_inventory_revision(self):
        trace = self.trace(bind(), sample(), sample(now=100), sample(now=200, currentAudioTrack="native-a2"))
        self.assertEqual([1, 1, 1], [step["status"]["inventoryRevision"] for step in trace[1:]])
        self.assertEqual(trace[1]["status"], trace[2]["status"])

    def test_confirmed_clip_keeps_controls_available_during_buffering_and_waits_for_actual_receipt(self):
        trace = self.trace(bind(), sample(), sample(now=50, state="buffering"), command(),
                           sample(now=200, state="buffering"),
                           sample(now=300, state="buffering", currentAudioTrack="native-a2"))
        self.assertEqual(trace[1]["status"], trace[2]["status"])
        self.assertTrue(trace[2]["status"]["available"])
        self.assertTrue(trace[3]["accepted"])
        self.assertEqual("issued", trace[3]["status"]["lastCommand"]["result"])
        self.assertEqual("a-1-0", trace[4]["status"]["currentAudioHandle"])
        self.assertIsNotNone(trace[4]["status"]["pending"])
        self.assertEqual("applied", trace[5]["status"]["lastCommand"]["result"])
        self.assertEqual("a-1-1", trace[5]["status"]["currentAudioHandle"])
        self.assertEqual([1] * 5, [step["status"]["inventoryRevision"] for step in trace[1:]])

    def test_startup_buffering_inventory_cannot_establish_clip_readiness(self):
        trace = self.trace(bind(), sample(state="buffering"), sample(now=100, state="buffering"), command())
        self.assertTrue(trace[1]["status"]["audio"])
        self.assertFalse(trace[1]["status"]["available"])
        self.assertEqual(trace[1]["status"], trace[2]["status"])
        self.assertFalse(trace[3]["accepted"])
        self.assertEqual([], trace[3]["effects"])

    def test_bind_reusing_clip_number_requires_new_playing_or_paused_confirmation(self):
        trace = self.trace(bind(), sample(), bind("play-2"),
                           sample(state="buffering", attemptId="play-2"),
                           command(2, attemptId="play-2", inventoryRevision=3, handle="a-3-1"),
                           sample(state="paused", attemptId="play-2"),
                           command(3, attemptId="play-2", inventoryRevision=3, handle="a-3-1"))
        self.assertFalse(trace[3]["status"]["available"])
        self.assertFalse(trace[4]["accepted"])
        self.assertEqual([], trace[4]["effects"])
        self.assertTrue(trace[5]["status"]["available"])
        self.assertTrue(trace[6]["accepted"])

    def test_buffering_new_clip_resets_readiness_and_rejects_old_and_current_handles_until_confirmed(self):
        trace = self.trace(bind(), sample(), sample(state="buffering", clipId=8), command(),
                           command(2, clipId=8, inventoryRevision=2, handle="a-2-1"),
                           sample(state="paused", clipId=8), command(3, clipId=8, inventoryRevision=2, handle="a-2-1"))
        self.assertFalse(trace[2]["status"]["available"])
        self.assertEqual(2, trace[2]["status"]["inventoryRevision"])
        self.assertFalse(trace[3]["accepted"])
        self.assertFalse(trace[4]["accepted"])
        self.assertTrue(trace[5]["status"]["available"])
        self.assertTrue(trace[6]["accepted"])

    def test_terminal_or_error_sample_drops_readiness_before_subsequent_buffering(self):
        for state in ("stopping", "stopped", "finished", "error", "none"):
            with self.subTest(state=state):
                terminal = sample(state=state, errorCode=-3 if state == "error" else 0)
                trace = self.trace(bind(), sample(), terminal, sample(state="buffering"), command())
                self.assertFalse(trace[2]["status"]["available"])
                self.assertFalse(trace[3]["status"]["available"])
                self.assertFalse(trace[4]["accepted"])
                self.assertEqual([], trace[4]["effects"])
        trace = self.trace(bind(), sample(), sample(state="playing", errorCode=-3), sample(state="buffering"), command())
        self.assertFalse(trace[-1]["accepted"])

    def test_buffering_confirmed_clip_off_with_empty_inventory_restores_caption_mode(self):
        trace = self.trace(bind(caption="When mute"), sample(), sample(state="buffering", audio=[], subtitles=[],
                           currentAudioTrack="", currentSubtitleTrack="", captionMode="When mute"),
                           command(kind="subtitle", intent="off", handle="", inventoryRevision=2),
                           sample(state="buffering", audio=[], subtitles=[], currentAudioTrack="", currentSubtitleTrack="", captionMode="Off"),
                           {"kind": "retire"})
        self.assertTrue(trace[2]["status"]["available"])
        self.assertTrue(trace[2]["status"]["offSupported"])
        self.assertTrue(trace[3]["accepted"])
        self.assertEqual("issued", trace[3]["status"]["lastCommand"]["result"])
        self.assertEqual("applied", trace[4]["status"]["lastCommand"]["result"])
        self.assertEqual([{"kind": "caption", "mode": "When mute"}], trace[5]["effects"])

    def test_inventory_reorder_invalidates_handles_and_pending_but_never_selects_by_old_index(self):
        reordered = list(reversed(audio()))
        trace = self.trace(bind(), sample(), command(), sample(now=200, audio=reordered), command(2))
        self.assertEqual(2, trace[3]["status"]["inventoryRevision"])
        self.assertEqual("a-2-1", trace[3]["status"]["currentAudioHandle"])
        self.assertIsNone(trace[3]["status"]["pending"])
        self.assertEqual("inventory_changed", trace[3]["status"]["lastCommand"]["result"])
        self.assertFalse(trace[4]["accepted"])
        self.assertEqual([], trace[4]["effects"])

    def test_clip_change_and_late_timer_cannot_touch_replacement(self):
        old_tick = {"kind": "tick", "attemptId": "play-1", "versionId": "version-1", "clipId": 7,
                    "inventoryRevision": 1, "commandId": 1, "nowMs": 5100}
        trace = self.trace(bind(), sample(), command(), sample(clipId=8), old_tick,
                           command(2, clipId=8, inventoryRevision=2, handle="a-2-1"))
        self.assertFalse(trace[4]["accepted"])
        self.assertEqual([], trace[4]["effects"])
        self.assertTrue(trace[5]["accepted"])

    def test_inventories_labels_and_raw_scan_are_bounded_and_url_labels_are_redacted(self):
        tracks = [{"Track": f"raw-{index}", "Name": "x" * 200} for index in range(100)]
        tracks[0]["Name"] = "https://fixture.test/path?signature=private-fixture"
        subs = [{"TrackName": f"sub-{index}", "Description": "y" * 200} for index in range(100)]
        status = self.trace(bind(), sample(audio=tracks, subtitles=subs))[-1]["status"]
        self.assertEqual(24, len(status["audio"]))
        self.assertEqual(32, len(status["subtitles"]))
        self.assertEqual("Audio 1", status["audio"][0]["label"])
        self.assertTrue(all(len(track["label"]) <= 80 for track in status["audio"] + status["subtitles"]))
        self.assertNotIn("private-fixture", str(status))
        self.assertNotIn("raw-", str(status))

    def test_malformed_native_fields_commands_and_native_integer_aliases_are_safe(self):
        for changes in ({"commandId": "1"}, {"commandId": 1.5}, {"clipId": []}, {"inventoryRevision": "1"},
                        {"kind": []}, {"intent": {}}, {"handle": []}):
            with self.subTest(changes=changes):
                result = self.trace(bind(), sample(), command(**changes))[-1]
                self.assertFalse(result["accepted"])
                self.assertEqual([], result["effects"])
        malformed = self.trace(bind(), sample(audio=[{}, None, {"Track": []}], subtitles=[]))[-1]["status"]
        self.assertEqual([], malformed["audio"])
        self.assertTrue(malformed["offSupported"])
        for alias in ("roInteger", "roLongInteger"):
            with self.subTest(alias=alias):
                self.assertTrue(self.trace(bind(), sample(), command(), integer_alias=alias)[-1]["accepted"])


if __name__ == "__main__":
    unittest.main()
