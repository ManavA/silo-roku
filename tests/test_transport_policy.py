"""Execute the pure transport policy; native time is always route-relative."""

from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/TransportPolicy.brs"

TRACE = '''
function TransportTrace(options as Object, events as Object) as Object
    state = TransportCreate(options)
    result = []
    for each event in events
        decision = TransportReduce(state,event)
        state = decision.state
        result.Push(decision)
    end for
    return result
end function
'''


def options(**changes):
    return {"attemptId": "play-1", "positionMs": 60000, "durationMs": 120000,
            "canSeek": True, "paused": False, "buttons": ["play_pause", "audio", "info"],
            "nowMs": 0, **changes}


def native(now=0, state="playing", position=60, **changes):
    status = {"attemptId": "play-1", "mode": "playback", "state": state,
              "clipId": 7, "position": position, "duration": 120, "errorCode": 0,
              "renderedPosition": position, "renderedClipId": 7, "renderedEpoch": 0, **changes}
    return {"kind": "native", "attemptId": "play-1", "nowMs": now, "status": status}


def key(name, now=100, press=True, **changes):
    return {"kind": "key", "attemptId": "play-1", "nowMs": now,
            "key": name, "press": press, **changes}


def tick(decision, now):
    return {"kind": "tick", "attemptId": "play-1", "nowMs": now,
            "token": decision["state"]["timerToken"]}


def commands(decision):
    return [effect["command"] for effect in decision["effects"] if effect["kind"] == "command"]


class TransportPolicyTests(unittest.TestCase):
    def call(self, name, arguments, integer_type=None):
        self.assertTrue(POLICY.is_file(), "pure transport policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-transport-") as directory:
            root = Path(directory)
            policy = POLICY
            if integer_type is not None:
                policy = root / "policy.brs"
                source = POLICY.read_text().replace("type(", "FixtureNativeType(")
                source += f'''
function FixtureNativeType(value as Dynamic) as String
    kind = Type(value)
    if kind = "Integer" or kind = "roInt" then return "{integer_type}"
    return kind
end function
'''
                policy.write_text(source)
            trace = root / "trace.brs"
            trace.write_text(TRACE)
            return run_function([policy, trace], name, arguments, root=root)

    def trace(self, events, config=None, integer_type=None):
        return self.call("TransportTrace", [options() if config is None else config, events], integer_type)

    def reduce(self, state, event):
        return self.call("TransportReduce", [state, event])

    def test_create_is_small_private_free_and_not_ready_until_native_playback(self):
        state = self.call("TransportCreate", [options(url="https://secret.test", headers={"Token": "private"})])
        self.assertEqual("hidden", state["phase"])
        self.assertFalse(state["ready"])
        self.assertFalse(state["retired"])
        self.assertEqual(-1, state["cursorMs"])
        self.assertEqual(-1, state["seekTargetMs"])
        self.assertNotIn("private", str(state))
        self.assertNotIn("https:", str(state))
        decision = self.reduce(state, key("right"))
        self.assertFalse(decision["accepted"])
        self.assertEqual([], decision["effects"])

    def test_ok_reveals_bar_before_toggling_and_play_key_does_not_activate_buttons(self):
        result = self.trace([native(), key("OK", 100), key("OK", 200),
                             native(300, "paused"), key("down", 400), key("right", 500), key("play", 600)])
        self.assertEqual("bar", result[1]["state"]["phase"])
        self.assertEqual([], commands(result[1]))
        self.assertEqual([{"action": "pause", "attemptId": "play-1"}], commands(result[2]))
        self.assertEqual("buttons", result[5]["state"]["phase"])
        self.assertEqual("audio", result[5]["render"]["buttonId"])
        self.assertEqual([{"action": "resume", "attemptId": "play-1"}], commands(result[6]))
        self.assertFalse(any(effect["kind"] == "action" for effect in result[6]["effects"]))

    def test_button_focus_is_clamped_and_ok_emits_an_action_without_native_seek(self):
        result = self.trace([native(), key("down", 100), key("right", 200), key("right", 300),
                             key("right", 400), key("OK", 500), key("left", 600),
                             key("left", 700), key("left", 800), key("up", 900)])
        self.assertEqual(2, result[4]["state"]["buttonIndex"])
        self.assertEqual([{"kind": "action", "attemptId": "play-1", "action": "info"}], result[5]["effects"])
        self.assertEqual(0, result[8]["state"]["buttonIndex"])
        self.assertEqual("bar", result[9]["state"]["phase"])
        self.assertFalse(any(c["action"] == "seek" for d in result for c in commands(d)))

    def test_cursor_movement_never_seeks_and_ok_commits_native_relative_ms_once(self):
        result = self.trace([native(), key("right", 100), key("left", 200), key("OK", 300)])
        self.assertEqual("scrub", result[1]["state"]["phase"])
        self.assertEqual(75000, result[1]["state"]["cursorMs"])
        self.assertEqual(60000, result[2]["state"]["cursorMs"])
        self.assertEqual([], commands(result[1]))
        self.assertEqual([], commands(result[2]))
        # The cursor returned to the already-rendered position: no decoder work.
        self.assertEqual([], commands(result[3]))
        moved = self.trace([native(), key("right", 100), key("OK", 200)])
        self.assertEqual([{"action": "seek", "attemptId": "play-1", "positionMs": 75000}], commands(moved[-1]))
        self.assertEqual(75000, moved[-1]["state"]["seekTargetMs"])

    def test_dpad_auto_commit_is_480_ms_after_latest_input_and_rejects_old_timer(self):
        state = self.trace([native(), key("right", 100)])[-1]
        stale_timer = tick(state, 580)
        advanced = self.reduce(state["state"], key("right", 300))
        self.assertEqual(780, advanced["state"]["timerAtMs"])
        rejected = self.reduce(advanced["state"], stale_timer)
        self.assertFalse(rejected["accepted"])
        early = self.reduce(advanced["state"], tick(advanced, 779))
        self.assertFalse(early["accepted"])
        committed = self.reduce(advanced["state"], tick(advanced, 780))
        self.assertEqual([{"action": "seek", "attemptId": "play-1", "positionMs": 90000}], commands(committed))
        repeated = self.reduce(committed["state"], tick(advanced, 780))
        self.assertFalse(repeated["accepted"])

    def test_repeat_ramp_clamps_endpoints_and_reversal_resets_acceleration(self):
        result = self.trace([native(), key("right", 100), key("right", 200), key("right", 300),
                             key("right", 400), key("left", 500)])
        self.assertEqual(120000, result[3]["state"]["cursorMs"])
        self.assertEqual(120000, result[4]["state"]["cursorMs"])
        self.assertEqual(105000, result[5]["state"]["cursorMs"])
        low = self.trace([native(position=2), key("left", 100)])[-1]
        self.assertEqual(0, low["state"]["cursorMs"])
        self.assertEqual([], commands(low))

    def test_held_scan_ticks_only_cursor_and_release_schedules_commit(self):
        scan = self.trace([native(), key("fastforward", 100)])[-1]
        self.assertEqual("scan", scan["state"]["phase"])
        self.assertEqual(75000, scan["state"]["cursorMs"])
        advanced = self.reduce(scan["state"], tick(scan, 300))
        self.assertEqual(90000, advanced["state"]["cursorMs"])
        self.assertEqual([], commands(advanced))
        faster = self.reduce(advanced["state"], key("fastforward", 320))
        self.assertEqual(2, faster["state"]["scanRate"])
        released = self.reduce(faster["state"], key("fastforward", 400, press=False))
        self.assertEqual("scrub", released["state"]["phase"])
        self.assertEqual(880, released["state"]["timerAtMs"])
        committed = self.reduce(released["state"], tick(released, 880))
        self.assertEqual([{"action": "seek", "attemptId": "play-1", "positionMs": 105000}], commands(committed))

    def test_back_cancels_cursor_then_hides_chrome_then_exits_without_stop_or_seek(self):
        result = self.trace([native(), key("right", 100), key("back", 200),
                             key("back", 300), key("back", 400)])
        self.assertEqual("bar", result[2]["state"]["phase"])
        self.assertEqual(-1, result[2]["state"]["cursorMs"])
        self.assertEqual("hidden", result[3]["state"]["phase"])
        self.assertEqual([{"kind": "exit", "attemptId": "play-1"}], result[4]["effects"])
        self.assertFalse(any(c["action"] in ("seek", "stop") for d in result for c in commands(d)))

    def test_back_dismisses_overlay_before_cursor_and_chrome(self):
        result = self.trace([native(), key("right", 100),
            {"kind": "overlay", "attemptId": "play-1", "nowMs": 200, "overlay": "info"}, key("back", 300)])
        self.assertEqual("scrub", result[-1]["state"]["phase"])
        self.assertEqual("none", result[-1]["state"]["overlay"])
        self.assertIn({"kind": "dismiss", "attemptId": "play-1", "overlay": "info"}, result[-1]["effects"])

    def test_play_pause_drops_cursor_and_toggles_without_committing_seek(self):
        result = self.trace([native(), key("right", 100), key("play", 200)])[-1]
        self.assertEqual(-1, result["state"]["cursorMs"])
        self.assertEqual([{"action": "pause", "attemptId": "play-1"}], commands(result))

    def test_down_drops_cursor_without_seek_and_keeps_buttons_pinned(self):
        result = self.trace([native(), key("right", 100), key("down", 200)])[-1]
        self.assertEqual("buttons", result["state"]["phase"])
        self.assertEqual(-1, result["state"]["timerAtMs"])
        self.assertEqual([], commands(result))

    def test_only_idle_playing_bar_auto_hides_and_hidden_native_samples_do_not_render(self):
        shown = self.trace([native(), key("OK", 100)])[-1]
        self.assertEqual(3100, shown["state"]["timerAtMs"])
        hidden = self.reduce(shown["state"], tick(shown, 3100))
        self.assertEqual("hidden", hidden["state"]["phase"])
        self.assertEqual({"visible": False}, hidden["render"])
        sample = self.reduce(hidden["state"], native(3200, position=63))
        self.assertIsNone(sample["render"])
        self.assertEqual(63000, sample["state"]["positionMs"])
        revealed = self.reduce(sample["state"], key("OK", 3300))
        self.assertEqual(63000, revealed["render"]["positionMs"])
        for events in ([native(state="paused"), key("OK", 100)],
                       [native(), key("down", 100)], [native(), key("right", 100), key("OK", 200)]):
            with self.subTest(events=events):
                pinned = self.trace(events)[-1]
                self.assertEqual(-1, pinned["state"]["hideAtMs"])

    def test_paused_seek_repauses_only_after_rendered_landing(self):
        committed = self.trace([native(state="paused"), key("right", 100), key("OK", 200)])[-1]
        self.assertEqual([{"action": "seek", "attemptId": "play-1", "positionMs": 75000}], commands(committed))
        resumed = self.reduce(committed["state"], native(300, position=75, renderedPosition=60))
        self.assertEqual([], commands(resumed))
        self.assertEqual(75000, resumed["state"]["seekTargetMs"])
        duplicate = self.reduce(resumed["state"], native(400, position=75, renderedPosition=60))
        self.assertEqual([], commands(duplicate))
        landed = self.reduce(duplicate["state"], native(500, position=75, renderedPosition=75))
        self.assertEqual([{"action": "pause", "attemptId": "play-1"}], commands(landed))
        self.assertEqual(-1, landed["state"]["seekTargetMs"])
        self.assertTrue(landed["state"]["desiredPaused"])
        self.assertEqual(-1, landed["state"]["hideAtMs"])

    def test_new_cursor_and_pause_during_settling_defer_pause_until_new_playing_edge(self):
        committed = self.trace([native(), key("right", 100), key("OK", 200)])[-1]
        cursor = self.reduce(committed["state"], key("left", 250))
        self.assertEqual([], commands(cursor))
        self.assertEqual(75000, cursor["state"]["seekTargetMs"])
        paused = self.reduce(cursor["state"], key("play", 275))
        self.assertEqual([], commands(paused))
        self.assertTrue(paused["state"]["rePausePending"])
        buffered = self.reduce(paused["state"], native(300, "buffering", position=75, renderedPosition=60))
        self.assertEqual([], commands(buffered))
        playing = self.reduce(buffered["state"], native(400, position=75, renderedPosition=75))
        self.assertEqual([{"action": "pause", "attemptId": "play-1"}], commands(playing))
        self.assertEqual(-1, playing["state"]["seekTargetMs"])

    def test_optimistic_stale_missing_utc_or_unchanged_render_does_not_settle_seek(self):
        committed = self.trace([native(), key("right", 100), key("OK", 200)])[-1]
        for fields in ({"renderedPosition": -1}, {"renderedClipId": 6}, {"renderedEpoch": 1},
                       {"renderedPosition": 60}, {"renderedPosition": "75"}):
            with self.subTest(fields=fields):
                outcome = self.reduce(committed["state"], native(300, position=75, **fields))
                self.assertEqual(75000, outcome["state"]["seekTargetMs"])
        landed = self.reduce(committed["state"], native(300, position=75))
        self.assertEqual(-1, landed["state"]["seekTargetMs"])

    def test_seek_watchdog_is_bounded_and_never_invents_landing_or_position(self):
        committed = self.trace([native(), key("right", 100), key("OK", 200)])[-1]
        self.assertEqual(8200, committed["state"]["timerAtMs"])
        expired = self.reduce(committed["state"], tick(committed, 8200))
        self.assertIn({"kind": "settle_timeout", "attemptId": "play-1", "seekId": 1}, expired["effects"])
        self.assertEqual(60000, expired["state"]["positionMs"])
        self.assertEqual(-1, expired["state"]["seekTargetMs"])

    def test_paused_seek_timeout_preserves_intent_until_late_rendered_landing(self):
        committed = self.trace([native(state="paused"), key("right", 100), key("OK", 200)])[-1]
        buffered = self.reduce(committed["state"], native(300, "buffering", position=60))
        expired = self.reduce(buffered["state"], tick(buffered, 8200))
        self.assertTrue(expired["state"]["desiredPaused"])
        self.assertTrue(expired["state"]["rePausePending"])
        self.assertEqual(75000, expired["state"].get("rePauseTargetMs"))
        self.assertEqual(-1, expired["state"]["seekTargetMs"])
        self.assertEqual(60000, expired["state"]["positionMs"])
        self.assertEqual([], commands(expired))
        premature = self.reduce(expired["state"], native(9000, position=75, renderedPosition=60))
        self.assertEqual([], commands(premature))
        self.assertTrue(premature["state"]["desiredPaused"])
        landed = self.reduce(premature["state"], native(9300, position=75))
        self.assertEqual([{"action": "pause", "attemptId": "play-1"}], commands(landed))
        self.assertFalse(landed["state"]["rePausePending"])
        self.assertEqual(-1, landed["state"]["rePauseTargetMs"])
        duplicate = self.reduce(landed["state"], native(9400, position=75))
        self.assertEqual([], commands(duplicate))
        self.assertTrue(duplicate["state"]["desiredPaused"])

    def test_playing_edge_and_watchdog_never_repause_without_rendered_landing(self):
        committed = self.trace([native(state="paused"), key("right", 100), key("OK", 200)])[-1]
        before_frame = self.reduce(committed["state"], native(300, position=75, renderedPosition=60))
        self.assertEqual([], commands(before_frame))
        expired = self.reduce(before_frame["state"], tick(before_frame, 8200))
        self.assertEqual([], commands(expired))
        self.assertTrue(expired["state"]["rePausePending"])
        self.assertEqual(60000, expired["state"]["renderedMs"])
        self.assertEqual(75000, expired["state"]["positionMs"])
        landed = self.reduce(expired["state"], native(9000, position=75))
        self.assertEqual([{"action": "pause", "attemptId": "play-1"}], commands(landed))

    def test_explicit_resume_overrides_paused_seek_intent_after_timeout(self):
        committed = self.trace([native(state="paused"), key("right", 100), key("OK", 200)])[-1]
        buffered = self.reduce(committed["state"], native(300, "buffering", position=60))
        expired = self.reduce(buffered["state"], tick(buffered, 8200))
        self.assertTrue(expired["state"]["rePausePending"])
        resumed = self.reduce(expired["state"], key("play", 8500))
        self.assertEqual([{"action": "resume", "attemptId": "play-1"}], commands(resumed))
        self.assertFalse(resumed["state"]["rePausePending"])
        self.assertEqual(-1, resumed["state"]["rePauseTargetMs"])
        playing = self.reduce(resumed["state"], native(9000, position=75))
        self.assertEqual([], commands(playing))
        self.assertFalse(playing["state"]["desiredPaused"])

    def test_buffering_chrome_stays_visible_until_native_playing_rearms_hide(self):
        result = self.trace([native(), key("OK", 100), native(200, "buffering")])[-1]
        self.assertEqual("bar", result["state"]["phase"])
        self.assertEqual(-1, result["state"]["hideAtMs"])
        self.assertEqual(-1, result["state"]["timerAtMs"])
        playing = self.reduce(result["state"], native(300))
        self.assertEqual(3300, playing["state"]["hideAtMs"])

    def test_next_cursor_uses_latest_seek_intent_and_old_render_cannot_settle_new_target(self):
        committed = self.trace([native(), key("right", 100), key("OK", 200)])[-1]
        for name in ("left", "rewind"):
            with self.subTest(key=name):
                cursor = self.reduce(committed["state"], key(name, 250))
                self.assertEqual(60000, cursor["state"]["cursorMs"])
                self.assertEqual([], commands(cursor))
                newest = self.reduce(cursor["state"], key("OK", 300))
                self.assertEqual([{"action": "seek", "attemptId": "play-1", "positionMs": 60000}], commands(newest))
                late = self.reduce(newest["state"], native(400, position=75))
                self.assertEqual(60000, late["state"]["seekTargetMs"])
                self.assertEqual(2, late["state"]["seekId"])

    def test_native_rev_fwd_names_preserve_press_and_release_scan_contract(self):
        for name, target in (("fwd", 75000), ("rev", 45000)):
            with self.subTest(key=name):
                scan = self.trace([native(), key(name, 100)])[-1]
                self.assertEqual("scan", scan["state"]["phase"])
                self.assertEqual(target, scan["state"]["cursorMs"])
                self.assertEqual([], commands(scan))
                released = self.reduce(scan["state"], key(name, 200, press=False))
                self.assertEqual("scrub", released["state"]["phase"])
                self.assertEqual(680, released["state"]["timerAtMs"])

    def test_unseekable_and_unknown_duration_keys_reveal_without_cursor_or_seek(self):
        for config, sample in ((options(canSeek=False), native()), (options(durationMs=0), native(duration=0))):
            with self.subTest(config=config):
                result = self.trace([sample, key("right", 100), key("fastforward", 200)], config)[-1]
                self.assertEqual("bar", result["state"]["phase"])
                self.assertEqual(-1, result["state"]["cursorMs"])
                self.assertEqual([], commands(result))

    def test_attempt_clip_and_monotonic_fences_reject_stale_native_keys_and_timers(self):
        current = self.trace([native(), key("right", 100)])[-1]
        events = [key("OK", 200, attemptId="old"), native(200, attemptId="old"),
                  native(200, clipId=6), native(99), tick(current, 579)]
        events.append({"kind": "tick", "attemptId": "old", "nowMs": 580, "token": current["state"]["timerToken"]})
        for event in events:
            with self.subTest(event=event):
                outcome = self.reduce(current["state"], event)
                self.assertFalse(outcome["accepted"])
                self.assertEqual(current["state"], outcome["state"])
                self.assertEqual([], outcome["effects"])

    def test_retirement_and_native_terminal_state_cancel_all_transport_work(self):
        current = self.trace([native(), key("right", 100), key("OK", 200)])[-1]
        for event in ({"kind": "retire", "attemptId": "play-1", "nowMs": 300},
                      native(300, "stopping"), native(300, "stopped", clipId=-1)):
            with self.subTest(event=event):
                outcome = self.reduce(current["state"], event)
                self.assertTrue(outcome["state"]["retired"])
                self.assertEqual("hidden", outcome["state"]["phase"])
                self.assertEqual(-1, outcome["state"]["seekTargetMs"])
                self.assertEqual(-1, outcome["state"]["timerAtMs"])
                self.assertFalse(self.reduce(outcome["state"], key("right", 400))["accepted"])

    def test_six_chrome_buttons_are_reachable_and_seven_button_config_is_rejected(self):
        buttons = ["play_pause", "audio", "subtitles", "versions", "info", "next"]
        state = self.call("TransportCreate", [options(buttons=buttons)])
        self.assertEqual(buttons, state["buttons"])
        events = [native(), key("down", 100)]
        events.extend(key("right", now) for now in (200, 300, 400, 500, 600, 700))
        events.append(key("OK", 800))
        outcome = self.trace(events, options(buttons=buttons))[-1]
        self.assertEqual(5, outcome["state"]["buttonIndex"])
        self.assertEqual([{"kind": "action", "attemptId": "play-1", "action": "next"}], outcome["effects"])
        self.assertIsNone(self.call("TransportCreate", [options(buttons=buttons + ["extras"])]))

    def test_malformed_config_events_and_native_integer_aliases(self):
        for changes in ({"attemptId": "https://private"}, {"durationMs": True}, {"durationMs": -1},
                        {"positionMs": "7"}, {"positionMs": 1e308}, {"canSeek": "true"},
                        {"buttons": ["https://private"]}, {"nowMs": -1}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.call("TransportCreate", [options(**changes)]))
        current = self.trace([native()])[-1]["state"]
        for event in (None, {}, key("right", press="true"), key("right", now=-1),
                      native(100, clipId="7"), {"kind": [], "attemptId": "play-1", "nowMs": 100}):
            with self.subTest(event=event):
                outcome = self.reduce(current, event)
                self.assertFalse(outcome["accepted"])
                self.assertEqual(current, outcome["state"])
        for alias in ("roInteger", "roLongInteger"):
            with self.subTest(alias=alias):
                result = self.trace([native(position=7), key("right", 100), key("OK", 200)],
                                    options(positionMs=7000), alias)[-1]
                self.assertEqual([{"action": "seek", "attemptId": "play-1", "positionMs": 22000}], commands(result))


if __name__ == "__main__":
    unittest.main()
