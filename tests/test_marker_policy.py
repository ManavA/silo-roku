"""Marker reads and skips are scoped, optional, and use rendered native time."""
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import ROOT as BRIDGE_ROOT, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/MarkerPolicy.brs"
SCOPE_POLICY = BRIDGE_ROOT / "source/core/ServerUrlPolicy.brs"
SCOPE = {"provider": "silo", "sourceId": "silo:fixture", "profileId": "adult", "generation": 9}


def config(**changes):
    return {"scope": SCOPE, "attemptId": "app-1", "itemId": "101", "versionId": "file-a",
            "durationMs": 120000, "canSeek": True, "relativeTimeline": True, "timelineOffsetMs": 10000, **changes}


def native(state="playing", rendered=20, **changes):
    status = {"attemptId": "app-1", "mode": "playback", "state": state, "clipId": 7, "errorCode": 0,
              "position": 999, "duration": 110, "renderedPosition": rendered, "renderedClipId": 7, "renderedEpoch": 0}
    status.update(changes.pop("status", {}))
    return {"kind": "native", "scope": SCOPE, "attemptId": "app-1", "versionId": "file-a",
            "landed": True, "status": status, **changes}


def result(markers=None, **changes):
    data = {"itemId": "101", "versionId": "file-a", "markers": markers if markers is not None else
            [{"type": "intro", "startMs": 20000, "endMs": 40000, "isFinal": False}]}
    data.update(changes.pop("data", {}))
    return {"kind": "result", "scope": SCOPE, "attemptId": "app-1", "versionId": "file-a", "itemId": "101",
            "clipId": 7, "ok": True, "data": data, **changes}


def action(**changes):
    return {"kind": "skip", "scope": SCOPE, "attemptId": "app-1", "versionId": "file-a", "itemId": "101",
            "clipId": 7, "renderedEpoch": 0, "actionId": "marker-1-0", **changes}


class MarkerPolicyTests(unittest.TestCase):
    def trace(self, *events, setup=None, numeric_alias=None):
        self.assertTrue(POLICY.is_file(), "marker policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-marker-policy-") as directory:
            source = POLICY.read_text()
            if numeric_alias:
                source = source.replace("type(", "MarkerFixtureType(") + f'''
function MarkerFixtureType(value as Dynamic) as String
    kind = Type(value)
    if kind = "Integer" or kind = "roInt" then return "{numeric_alias}"
    return kind
end function
'''
            source += '''
function MarkerTrace(config as Object, events as Object) as Object
    state = MarkerCreate(config)
    trace = []
    for each event in events
        decision = MarkerReduce(state,event)
        state = decision.state
        decision["projection"] = MarkerProjection(state)
        trace.Push(decision)
    end for
    return trace
end function
'''
            path = Path(directory) / "policy.brs"
            path.write_text(source)
            return run_function([SCOPE_POLICY, path], "MarkerTrace", [setup or config(), list(events)], root=Path(directory))

    def test_read_once_after_first_committed_playing_without_waiting_for_resume_landing(self):
        trace = self.trace(native("buffering"), native("paused"), native(landed=False), native("paused"), native())
        self.assertEqual([], trace[0]["effects"])
        self.assertEqual([], trace[1]["effects"])
        request = trace[2]["effects"][0]
        self.assertEqual(("request", "markers", "player_markers"), tuple(request[key] for key in ("kind", "action", "purpose")))
        self.assertEqual({"itemId": "101"}, request["params"])
        self.assertEqual([], trace[3]["effects"])
        self.assertEqual([], trace[4]["effects"])
        self.assertFalse(trace[2]["projection"]["available"])

    def test_plex_uses_supported_detail_read_and_captures_exact_version(self):
        scope = {**SCOPE, "provider": "plex", "sourceId": "plex:fixture"}
        trace = self.trace(native(scope=scope), setup=config(scope=scope))
        self.assertEqual("detail", trace[0]["effects"][0]["action"])
        self.assertEqual("file-a", trace[0]["effects"][0]["owner"]["versionId"])

    def test_skip_uses_rendered_clock_and_subtracts_explicit_relative_offset_once(self):
        trace = self.trace(native(), result(), action())
        projected = trace[1]["projection"]["action"]
        self.assertEqual(("Skip Intro", 30000), (projected["label"], projected["nativeTargetMs"]))
        seek = trace[2]["effects"][0]
        self.assertEqual("seek", seek["kind"])
        self.assertEqual(30000, seek["positionMs"])
        self.assertEqual({"versionId": "file-a", "clipId": 7, "renderedEpoch": 0}, seek["markerFence"])
        absolute = self.trace(native(rendered=30), result(), action(), setup=config(relativeTimeline=False))[-1]
        self.assertEqual(40000, absolute["effects"][0]["positionMs"])

    def test_recap_multiple_credits_and_final_identity_are_supported_in_start_order(self):
        marks = [{"type": "credits", "startMs": 80000, "endMs": 100000},
                 {"type": "recap", "startMs": 20000, "endMs": 45000},
                 {"type": "intro", "startMs": 25000, "endMs": 35000},
                 {"type": "credits", "startMs": 105000, "endMs": 120000, "isFinal": True}]
        trace = self.trace(native(), result(marks), native(rendered=80), native(rendered=100))
        self.assertEqual("Skip Recap", trace[1]["projection"]["action"]["label"])
        self.assertEqual("credits", trace[2]["projection"]["action"]["type"])
        self.assertFalse(trace[2]["projection"]["action"]["isFinal"])
        self.assertTrue(trace[3]["projection"]["action"]["isFinal"])

    def test_unlanded_resume_wrong_rendered_clip_or_epoch_optimistic_position_cannot_enable_skip(self):
        for current in (native(landed=False), native(status={"renderedPosition": -1}),
                        native(status={"renderedClipId": 8}), native(status={"renderedEpoch": 2})):
            with self.subTest(current=current):
                trace = self.trace(current, result(), action())
                self.assertFalse(trace[1]["projection"]["available"])
                self.assertFalse(trace[2]["accepted"])
                self.assertEqual([], trace[2]["effects"])

    def test_read_and_action_scope_attempt_version_file_clip_and_epoch_are_fenced(self):
        for changes in ({"scope": {**SCOPE, "sourceId": "silo:other"}}, {"scope": {**SCOPE, "profileId": "other"}},
                        {"scope": {**SCOPE, "generation": 8}}, {"attemptId": "old"}, {"versionId": "file-b"},
                        {"itemId": "102"}, {"clipId": 8}, {"data": {"versionId": "file-b"}}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.trace(native(), result(**changes))[-1]["projection"]["action"])
        for changes in ({"attemptId": "old"}, {"versionId": "file-b"}, {"clipId": 8}, {"renderedEpoch": 1},
                        {"actionId": "marker-0-0"}, {"scope": {**SCOPE, "generation": 8}}):
            self.assertFalse(self.trace(native(), result(), action(**changes))[-1]["accepted"])

    def test_optional_failure_and_retirement_never_restart_read_or_send_progress(self):
        trace = self.trace(native(), result(ok=False), native(), {"kind": "retire"}, result(), action())
        self.assertEqual([], trace[2]["effects"])
        self.assertFalse(trace[4]["accepted"])
        self.assertFalse(trace[5]["accepted"])
        self.assertFalse(any(effect["kind"] in ("progress", "stop", "start") for step in trace for effect in step["effects"]))

    def test_invalid_intervals_duration_minimum_remaining_nonseek_and_negative_native_target_hide_actions(self):
        bad = [{"type": "intro", "startMs": -1, "endMs": 40000}, {"type": "recap", "startMs": 30000, "endMs": 30000},
               {"type": "credits", "startMs": 20000, "endMs": 120001}, {"type": "intro", "startMs": "20000", "endMs": 40000},
               {"type": "intro", "startMs": 20000, "endMs": float("inf")}, {"type": "unknown", "startMs": 20000, "endMs": 40000}]
        # JSON cannot represent nonfinite numbers; exercise finite bounds with a huge number instead.
        bad[4]["endMs"] = 1e30
        self.assertIsNone(self.trace(native(), result(bad))[-1]["projection"]["action"])
        for setup in (config(canSeek=False), config(durationMs=0), config(timelineOffsetMs=50000)):
            self.assertIsNone(self.trace(native(), result(), setup=setup)[-1]["projection"]["action"])
        self.assertIsNone(self.trace(native(rendered=29.8), result())[-1]["projection"]["action"])

    def test_marker_work_is_bounded_and_native_numeric_aliases_keep_real_flow(self):
        marks = [{"type": "intro", "startMs": i * 1000, "endMs": i * 1000 + 40000} for i in range(100)]
        state = self.trace(native(), result(marks))[-1]["state"]
        self.assertLessEqual(len(state["markers"]), 32)
        self.assertNotIn("url", state)
        for alias in ("roInteger", "roLongInteger", "roDouble", "roFloat"):
            self.assertTrue(self.trace(native(), result(), action(), numeric_alias=alias)[-1]["accepted"])

    def test_clock_updates_inside_same_marker_do_not_republish_actions_or_repeat_reads(self):
        trace = self.trace(native(), result(), native(rendered=21), native(rendered=22))
        self.assertIsNone(trace[2]["render"])
        self.assertIsNone(trace[3]["render"])
        self.assertEqual([], trace[2]["effects"])
        self.assertEqual([], trace[3]["effects"])

    def test_small_utc_epoch_cannot_be_interpreted_as_vod_relative_marker_clock(self):
        trace = self.trace(native(status={"renderedEpoch": 1}), result(), action(renderedEpoch=1))
        self.assertFalse(trace[1]["projection"]["available"])
        self.assertFalse(trace[2]["accepted"])
        self.assertEqual([], trace[2]["effects"])

    def test_private_canonical_silo_url_scope_is_preserved_but_never_rendered(self):
        scope = {**SCOPE, "sourceId": "silo:https://synthetic.example.test"}
        trace = self.trace(native(scope=scope), result(scope=scope), action(scope=scope), setup=config(scope=scope))
        self.assertIsNotNone(trace[0]["state"])
        self.assertEqual(scope["sourceId"], trace[0]["effects"][0]["scope"]["sourceId"])
        self.assertTrue(trace[2]["accepted"])
        for entry in trace:
            self.assertNotIn("synthetic.example.test", str(entry["projection"]))
            self.assertNotIn("https:", str(entry["projection"]))
        foreign = {**scope, "sourceId": "silo:https://foreign.example.test"}
        rejected = self.trace(native(scope=scope), result(scope=foreign), setup=config(scope=scope))[-1]
        self.assertFalse(rejected["accepted"])
        self.assertIsNone(rejected["projection"]["action"])

    def test_malformed_private_scope_id_is_rejected_without_normalizing_identity(self):
        for value in ([], "silo:https://synthetic.example.test\r\n", "silo:https://synthetic.example.test x",
                      "silo:" + "x" * 4097, "plex:https://synthetic.example.test", "silo:ftp://synthetic.example.test"):
            with self.subTest(value=value):
                state = run_function([SCOPE_POLICY, POLICY], "MarkerCreate", [config(scope={**SCOPE, "sourceId": value})])
                self.assertIsNone(state)


if __name__ == "__main__":
    unittest.main()
