"""Real BrightScript transitions for bounded playback progress delivery."""

from pathlib import Path
import json
import re
import tempfile
import unittest

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/ProgressDeliveryPolicy.brs"
URL_POLICY = ROOT / "source/core/ServerUrlPolicy.brs"
SCOPE = {"provider": "silo", "sourceId": "silo:fixture-server", "profileId": "fixture-owner",
         "generation": 7, "sessionId": "fixture-session"}


class ProgressDeliveryTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "Playback progress delivery policy is missing")
        self.assertRegex(POLICY.read_text(), r"(?i)function\s+" + re.escape(name) + r"\(")
        return run_function([POLICY, URL_POLICY], name, list(args))

    def state(self, scope=SCOPE):
        return self.call("ProgressDeliveryBind", None, scope)

    def sample(self, **changes):
        return {"itemId": "fixture-item", "sessionId": SCOPE["sessionId"], "positionMs": 10000,
                "durationMs": 7200000, "state": "playing", "sequence": 1, "isPaused": False,
                "installationId": "fixture-installation", **changes}

    def offer(self, delivery_state, action="playback_progress", now=0, scope=SCOPE, **changes):
        return self.call("ProgressDeliveryOffer", delivery_state, scope, action, self.sample(**changes), now)

    def take(self, state, now=0, scope=SCOPE):
        return self.call("ProgressDeliveryTake", state, scope, now)

    def complete(self, taken, ok=True, error="", now=0, scope=SCOPE):
        return self.call("ProgressDeliveryComplete", taken["state"], scope,
                         taken["event"]["eventId"], ok, error, now)

    def test_bind_is_empty_and_retains_only_exact_delivery_scope(self):
        state = self.state()
        self.assertEqual(SCOPE, state["scope"])
        self.assertIsNone(state["pending"])
        self.assertIsNone(state["inFlight"])
        self.assertFalse(state["terminal"])
        offered = self.offer(state)["state"]
        self.assertEqual(offered, self.call("ProgressDeliveryBind", offered, SCOPE))
        for field, value in (("provider", "plex"), ("sourceId", "silo:other"),
                             ("profileId", "other"), ("generation", 8), ("sessionId", "other")):
            with self.subTest(field=field):
                changed = {**SCOPE, field: value}
                if field == "provider":
                    changed["sourceId"] = "plex:other"
                rebound = self.call("ProgressDeliveryBind", offered, changed)
                self.assertIsNone(rebound["pending"])
                self.assertEqual(changed, rebound["scope"])

    def test_native_boxed_integer_types_survive_bind_offer_and_take(self):
        # The host boxes AA integers as roInt; OS 15.3 reports roInteger.
        # Substitute only that native type accessor, retaining real arithmetic.
        source = POLICY.read_text().replace("kind = type(value)", "kind = PdFixtureNumericType(value)")
        helper = '''
function PdFixtureNumericType(value as Dynamic) as String
    kind = type(value)
    if kind = "Integer" or kind = "roInt" then return m.nativeNumericType
    return kind
end function
function PdFixtureRoundTrip(alias as String) as Object
    m.nativeNumericType = alias
    scope = {provider:"plex",sourceId:"plex:fixture",profileId:"owner",generation:7,sessionId:"s1"}
    state = ProgressDeliveryBind(invalid,scope)
    if state = invalid then return {bound:false,accepted:false,event:false}
    offered = ProgressDeliveryOffer(state,scope,"playback_stop",{itemId:"101",sessionId:"s1",positionMs:0,
        durationMs:0,state:"stopped",sequence:1,isPaused:false,persistProgress:false,stopId:"fixture-stop"},0)
    if not offered.accepted then return {bound:true,accepted:false,event:false}
    taken = ProgressDeliveryTake(offered.state,scope,0)
    return {bound:true,accepted:true,event:taken.event<>invalid}
end function
'''
        with tempfile.TemporaryDirectory(prefix="silo-pd-native-type-") as directory:
            script = Path(directory) / "policy.brs"
            script.write_text(source + helper)
            for alias in ("roInteger", "roLongInteger"):
                with self.subTest(alias=alias):
                    self.assertEqual(run_function([URL_POLICY, script], "PdFixtureRoundTrip", [alias]),
                                     {"bound": True, "accepted": True, "event": True})

    def test_newest_sample_replaces_pending_even_when_position_moves_backwards(self):
        state = self.offer(self.state(), positionMs=50000)["state"]
        state = self.offer(state, positionMs=3000, state="paused", isPaused=True)["state"]
        event = self.take(state)["event"]
        self.assertEqual(3000, event["params"]["positionMs"])
        self.assertTrue(event["params"]["isPaused"])
        self.assertEqual(2, event["params"]["sequence"])
        self.assertEqual(1, event["attempts"])

    def test_take_serializes_one_flight_and_keeps_latest_waiting_sample(self):
        first = self.take(self.offer(self.state())["state"])
        state = self.offer(first["state"], positionMs=20000)["state"]
        busy = self.take(state)
        self.assertIsNone(busy["event"])
        self.assertEqual(first["event"], busy["state"]["inFlight"])
        self.assertEqual(20000, busy["state"]["pending"]["params"]["positionMs"])
        done = self.call("ProgressDeliveryComplete", state, SCOPE, first["event"]["eventId"], True, "", 0)
        self.assertEqual(20000, self.take(done)["event"]["params"]["positionMs"])

    def test_success_acknowledges_only_the_exact_flight(self):
        taken = self.take(self.offer(self.state())["state"])
        wrong = self.call("ProgressDeliveryComplete", taken["state"], SCOPE, "wrong-event", True, "", 0)
        self.assertEqual(taken["state"], wrong)
        done = self.complete(taken)
        self.assertIsNone(done["pending"])
        self.assertIsNone(done["inFlight"])

    def test_retries_transient_failure_at_one_and_two_seconds_then_stops(self):
        first = self.take(self.offer(self.state())["state"])
        state = self.complete(first, False, "timeout", 10)
        early = self.take(state, 1009)
        self.assertIsNone(early["event"])
        self.assertEqual(1, early["waitMs"])
        second = self.take(state, 1010)
        self.assertEqual(first["event"]["eventId"], second["event"]["eventId"])
        self.assertEqual(first["event"]["params"], second["event"]["params"])
        self.assertEqual(2, second["event"]["attempts"])
        state = self.complete(second, False, "network_error", 1010)
        self.assertEqual(2000, self.take(state, 1010)["waitMs"])
        third = self.take(state, 3010)
        self.assertEqual(3, third["event"]["attempts"])
        exhausted = self.complete(third, False, "timeout", 3010)
        self.assertIsNone(self.take(exhausted, 999999)["event"])

    def test_permanent_failure_never_replays(self):
        for error in ("unauthorized", "auth_expired", "session_changed", "not_found", "invalid_request", "profile_locked"):
            with self.subTest(error=error):
                first = self.take(self.offer(self.state())["state"])
                self.assertIsNone(self.take(self.complete(first, False, error), 999999)["event"])

    def test_task_allocation_failure_retries_terminal_cleanup_with_bounded_backoff(self):
        taken = self.take(self.offer(self.state(), "playback_stop", stopId="fixture-stop")["state"])
        original = taken["event"]["params"]
        now = 0
        for attempt, delay in ((1, 1000), (2, 2000)):
            state = self.complete(taken, False, "task_unavailable", now)
            self.assertIsNone(state["inFlight"])
            self.assertEqual(delay, self.take(state, now)["waitMs"])
            now += delay
            taken = self.take(state, now)
            self.assertEqual(taken["event"]["params"], original)
            self.assertEqual(taken["event"]["attempts"], attempt + 1)
        exhausted = self.complete(taken, False, "task_unavailable", now)
        self.assertIsNone(exhausted["pending"])
        self.assertIsNone(exhausted["inFlight"])

    def test_retry_uses_the_actual_http_timeout_and_unavailable_codes(self):
        for error in ("network_timeout", "network_unavailable", "server_error", "rate_limited"):
            with self.subTest(error=error):
                first = self.take(self.offer(self.state())["state"])
                retry = self.take(self.complete(first, False, error), 1000)
                self.assertIsNotNone(retry["event"])
                self.assertEqual(first["event"]["params"], retry["event"]["params"])

    def test_newer_pending_sample_supersedes_failed_flight_without_backoff(self):
        first = self.take(self.offer(self.state())["state"])
        state = self.offer(first["state"], positionMs=20000)["state"]
        done = self.call("ProgressDeliveryComplete", state, SCOPE, first["event"]["eventId"], False, "timeout", 20)
        newest = self.take(done, 20)
        self.assertEqual(20000, newest["event"]["params"]["positionMs"])
        self.assertNotEqual(first["event"]["eventId"], newest["event"]["eventId"])
        self.assertEqual(1, newest["event"]["attempts"])

    def test_stop_supersedes_pending_progress_and_rejects_every_later_sample(self):
        state = self.offer(self.state())["state"]
        stopped = self.offer(state, "playback_stop", stopId="fixture-stop", positionMs=25000)
        self.assertTrue(stopped["accepted"])
        self.assertTrue(stopped["state"]["terminal"])
        for action in ("playback_progress", "playback_stop"):
            later = self.offer(stopped["state"], action, stopId="different-stop", positionMs=30000)
            self.assertFalse(later["accepted"])
            self.assertEqual(stopped["state"], later["state"])
        event = self.take(stopped["state"])["event"]
        self.assertEqual("playback_stop", event["action"])
        self.assertEqual("stopped", event["params"]["state"])
        self.assertFalse(event["params"]["isPaused"])
        self.assertEqual(2, event["params"]["sequence"])

    def test_failed_older_progress_cannot_replay_ahead_of_pending_stop(self):
        first = self.take(self.offer(self.state())["state"])
        state = self.offer(first["state"], "playback_stop", stopId="fixture-stop")["state"]
        done = self.call("ProgressDeliveryComplete", state, SCOPE, first["event"]["eventId"], False, "timeout", 0)
        stop = self.take(done)
        self.assertEqual("playback_stop", stop["event"]["action"])
        self.assertEqual("fixture-stop", stop["event"]["params"]["stopId"])
        failed = self.complete(stop, False, "network_error", 0)
        retry = self.take(failed, 1000)
        self.assertEqual(stop["event"]["params"], retry["event"]["params"])
        self.assertEqual(stop["event"]["eventId"], retry["event"]["eventId"])
        done = self.complete(retry)
        self.assertTrue(done["terminal"])
        self.assertFalse(self.offer(done)["accepted"])

    def test_unlanded_resume_stop_keeps_cleanup_only_flag_across_retry(self):
        offered = self.offer(self.state(), "playback_stop", stopId="fixture-stop",
                             persistProgress=False)
        self.assertTrue(offered["accepted"])
        taken = self.take(offered["state"])
        self.assertFalse(taken["event"]["params"]["persistProgress"])
        failed = self.complete(taken, False, "timeout", 0)
        retried = self.take(failed, 1000)
        self.assertFalse(retried["event"]["params"]["persistProgress"])

    def test_sequence_floor_is_monotonic_across_progress_and_stop(self):
        state = self.offer(self.state(), sequence=40)["state"]
        state = self.offer(state, sequence=2)["state"]
        self.assertEqual(41, state["pending"]["params"]["sequence"])
        state = self.offer(state, "playback_stop", sequence=41, stopId="fixture-stop")["state"]
        self.assertEqual(42, state["pending"]["params"]["sequence"])

    def test_all_transition_paths_fence_provider_source_profile_generation_session(self):
        first = self.take(self.offer(self.state())["state"])
        for field, value in (("provider", "plex"), ("sourceId", "silo:other"),
                             ("profileId", "other"), ("generation", 8), ("sessionId", "other")):
            with self.subTest(field=field):
                scope = {**SCOPE, field: value}
                offered = self.offer(first["state"], scope=scope)
                self.assertFalse(offered["accepted"])
                self.assertEqual(first["state"], offered["state"])
                self.assertIsNone(self.take(first["state"], scope=scope)["event"])
                self.assertEqual(first["state"], self.complete(first, scope=scope))
                self.assertEqual(first["state"], self.call("ProgressDeliveryDispatchFailed", first["state"], scope, first["event"]["eventId"]))

    def test_dispatch_rejection_restores_identity_without_spending_retry(self):
        first = self.take(self.offer(self.state(), "playback_stop", stopId="fixture-stop")["state"])
        state = self.call("ProgressDeliveryDispatchFailed", first["state"], SCOPE, first["event"]["eventId"])
        self.assertIsNone(state["inFlight"])
        retry = self.take(state)
        self.assertEqual(first["event"], retry["event"])
        wrong = self.call("ProgressDeliveryDispatchFailed", retry["state"], SCOPE, "wrong-event")
        self.assertEqual(retry["state"], wrong)

    def test_dispatch_rejection_keeps_newer_pending_event(self):
        first = self.take(self.offer(self.state())["state"])
        state = self.offer(first["state"], "playback_stop", stopId="fixture-stop")["state"]
        state = self.call("ProgressDeliveryDispatchFailed", state, SCOPE, first["event"]["eventId"])
        self.assertEqual("playback_stop", self.take(state)["event"]["action"])

    def test_state_and_payload_drop_credentials_urls_and_unbounded_extras(self):
        raw_scope = {**SCOPE, "token": "synthetic-secret", "url": "https://fixture.test/private"}
        state = self.state(raw_scope)
        params = self.sample(token="synthetic-secret", url="https://fixture.test/private",
                             headers={"Authorization": "synthetic-secret"}, extras=list(range(1000)))
        offered = self.call("ProgressDeliveryOffer", state, SCOPE, "playback_progress", params, 0)
        self.assertTrue(offered["accepted"])
        text = str(offered)
        self.assertNotIn("synthetic-secret", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("headers", text)
        self.assertNotIn("extras", text)
        self.assertLess(len(text), 2000)

    def test_malformed_samples_and_foreign_payload_session_are_rejected(self):
        for changes in ({"sessionId": "other"}, {"positionMs": -1}, {"positionMs": "1000"},
                        {"positionMs": True}, {"durationMs": -1}, {"sequence": -1},
                        {"sequence": True}, {"itemId": "https://fixture.test/private"},
                        {"installationId": "https://fixture.test/private"}, {"state": "buffering"}):
            with self.subTest(changes=changes):
                result = self.offer(self.state(), **changes)
                self.assertFalse(result["accepted"])
                self.assertIsNone(result["state"]["pending"])
        self.assertFalse(self.offer(self.state(), "playback_stop")["accepted"])

    def test_plex_progress_accepts_numeric_native_item_and_direct_empty_session(self):
        scope = {**SCOPE, "provider": "plex", "sourceId": "plex:fixture-server"}
        result = self.offer(self.state(scope), "playback_stop", scope=scope, itemId="123",
                            transcodeSessionId="", stopId="")
        self.assertTrue(result["accepted"])
        self.assertEqual("", self.take(result["state"], scope=scope)["event"]["params"]["transcodeSessionId"])

    def test_plex_direct_progress_and_stop_have_no_server_session(self):
        scope = {**SCOPE, "provider": "plex", "sourceId": "plex:fixture", "sessionId": ""}
        state = self.state(scope)
        self.assertIsNotNone(state)
        progress = self.offer(state, scope=scope, itemId="123", sessionId="", transcodeSessionId="")
        self.assertTrue(progress["accepted"])
        taken = self.take(progress["state"], scope=scope)
        self.assertEqual("", taken["event"]["params"]["sessionId"])
        self.assertEqual("", taken["event"]["params"]["transcodeSessionId"])
        done = self.complete(taken, scope=scope)
        stop = self.offer(done, "playback_stop", scope=scope, itemId="123", sessionId="", transcodeSessionId="")
        self.assertTrue(stop["accepted"])
        stop_taken = self.take(stop["state"], scope=scope)
        retry = self.take(self.complete(stop_taken, False, "network_timeout", scope=scope), 1000, scope)
        self.assertEqual(stop_taken["event"]["params"], retry["event"]["params"])
        self.assertEqual("playback_stop", retry["event"]["action"])

    def test_silo_still_requires_nonempty_playback_session(self):
        self.assertIsNone(self.state({**SCOPE, "sessionId": ""}))

    def test_rejected_silo_plan_can_be_abandoned_without_a_media_identity(self):
        offered = self.offer(self.state(), "playback_stop", itemId="", stopId="fixture-stop", persistProgress=False)
        self.assertTrue(offered["accepted"])
        params = self.take(offered["state"])["event"]["params"]
        self.assertEqual(params["itemId"], "")
        self.assertFalse(params["persistProgress"])
        self.assertFalse(self.offer(self.state(), itemId="")["accepted"])
        self.assertFalse(self.offer(self.state(), "playback_stop", itemId="", stopId="fixture-stop")["accepted"])

    def test_opaque_silo_session_ids_and_scene_stop_ids_remain_valid(self):
        scope = {**SCOPE, "sessionId": "sess/1"}
        offered = self.offer(self.state(scope), "playback_stop", scope=scope, sessionId="sess/1",
                             stopId="silo.123:2026-10-13:1")
        self.assertTrue(offered["accepted"])
        taken = self.take(offered["state"], scope=scope)
        self.assertEqual("sess/1", taken["event"]["params"]["sessionId"])
        retry = self.take(self.complete(taken, False, "network_timeout", scope=scope), 1000, scope)
        self.assertEqual(taken["event"]["params"], retry["event"]["params"])

    def test_fractional_native_milliseconds_are_sanitized_without_losing_sample(self):
        # ParseJson intentionally creates single-precision Float decimals. Build
        # the native player's Double fields explicitly so the input still has
        # its sub-millisecond fraction when the real policy receives it.
        scope_json = json.dumps(SCOPE).replace('"', '""')
        sample_json = json.dumps(self.sample()).replace('"', '""')
        output = run_brightscript([POLICY, URL_POLICY], f'''
scope = ParseJson("{scope_json}")
sample = ParseJson("{sample_json}")
sample["positionMs"] = 10000.75#
sample["durationMs"] = 7200000.5#
offered = ProgressDeliveryOffer(ProgressDeliveryBind(invalid,scope),scope,"playback_progress",sample,0)
taken = ProgressDeliveryTake(offered.state,scope,0)
print FormatJson(taken.event)''')
        event = json.loads(output.strip())
        self.assertEqual(10000, event["params"]["positionMs"])
        self.assertEqual(7200000, event["params"]["durationMs"])

    def test_actual_silo_source_identity_accepts_normalized_selected_server_url(self):
        for source_id in ("silo:https://silo.example", "silo:https://silo.example:8443/silo",
                          "silo:http://192.168.1.2:9000", "silo:https://[2001:db8::1]/silo"):
            with self.subTest(source_id=source_id):
                scope = {**SCOPE, "sourceId": source_id}
                state = self.state(scope)
                self.assertIsNotNone(state)
                offered = self.offer(state, scope=scope)
                self.assertTrue(offered["accepted"])
                self.assertEqual(source_id, self.take(offered["state"], scope=scope)["state"]["scope"]["sourceId"])

    def test_source_identity_rejects_credentials_queries_fragments_and_controls(self):
        for source_id in ("silo:https://user:secret@silo.example", "silo:https://silo.example?token=secret",
                          "silo:https://silo.example#secret", "silo:https://silo.example\n",
                          "silo:https://silo.example\\secret", "plex:https://silo.example"):
            with self.subTest(source_id=source_id):
                self.assertIsNone(self.state({**SCOPE, "sourceId": source_id}))


if __name__ == "__main__":
    unittest.main()
