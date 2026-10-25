"""Plex delivery reports a bounded failed phase without relaxing receipts."""

from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlsplit

from tests import test_plex_playback_task as playback
from tools.brightscript import run_function


class PlexDeliveryDiagnosticsTests(unittest.TestCase):
    def event(self, action="playback_stop", *, responses, **changes):
        fixture = playback.PlexPlaybackTaskTests()
        return fixture.run_playback(action, fixture.event_params(**changes), responses=responses)

    def assert_failure(self, result, phase, code, status=None):
        expected = {"ok": False, "errorCode": code, "deliveryPhase": phase}
        if status is not None:
            expected.update(transportStatus=status, statusCode=status)
        self.assertEqual(expected, result["outcome"])

    def test_final_timeline_404_is_identified_and_still_closes_the_transcode(self):
        result = self.event(responses=[{"ok": False, "errorCode": "not_found", "statusCode": 404},
                                       {"ok": True, "statusCode": 200}])
        self.assert_failure(result, "timeline", "not_found", 404)
        self.assertEqual(["/:/timeline", "/video/:/transcode/universal/stop"],
                         [urlsplit(request["url"]).path for request in result["requests"]])
        self.assertEqual([5000, 5000], result["timeouts"])

    def test_transcode_stop_404_remains_failed_after_a_saved_timeline(self):
        result = self.event(responses=[{"ok": True, "statusCode": 200},
                                       {"ok": False, "errorCode": "not_found", "statusCode": 404}])
        self.assert_failure(result, "transcode_stop", "not_found", 404)

    def test_cleanup_only_stop_404_is_not_a_progress_or_success_receipt(self):
        result = self.event(persistProgress=False,
                            responses=[{"ok": False, "errorCode": "not_found", "statusCode": 404}])
        self.assert_failure(result, "transcode_stop", "not_found", 404)
        self.assertEqual(["/video/:/transcode/universal/stop"],
                         [urlsplit(request["url"]).path for request in result["requests"]])

    def test_first_timeline_failure_survives_a_different_stop_failure(self):
        result = self.event(responses=[{"ok": False, "errorCode": "not_found", "statusCode": 404},
                                       {"ok": False, "errorCode": "server_error", "statusCode": 503}])
        self.assert_failure(result, "timeline", "not_found", 404)
        self.assertEqual(2, len(result["requests"]))

    def test_progress_failure_names_timeline_without_closing_an_active_session(self):
        result = self.event("playback_progress",
                            responses=[{"ok": False, "errorCode": "timeout", "statusCode": -28}])
        self.assert_failure(result, "timeline", "timeout", -28)
        self.assertEqual(["/:/timeline"], [urlsplit(request["url"]).path for request in result["requests"]])

    def test_invalid_timeline_request_retains_phase_and_still_closes_known_session(self):
        result = self.event(itemId="", responses=[{"ok": True, "statusCode": 200}])
        self.assert_failure(result, "timeline", "invalid_request")
        self.assertEqual(["/video/:/transcode/universal/stop"],
                         [urlsplit(request["url"]).path for request in result["requests"]])

    def test_transport_failure_does_not_copy_private_or_unbounded_fields(self):
        for status in ("404", 404.5, True, None, 0, 99, 600, -1000):
            with self.subTest(status=status):
                result = self.event("playback_progress", responses=[{
                    "ok": False, "errorCode": "network_error", "statusCode": status,
                    "body": "synthetic-private-body", "message": "synthetic-private-message",
                    "url": "https://private.example.test/stream", "token": "synthetic-private-token"}])
                self.assert_failure(result, "timeline", "network_error")

    def test_native_boxed_integer_statuses_keep_real_values_and_bounds(self):
        helpers = '''
function FixtureNativeType(value as Dynamic) as String
    kind = type(value)
    if kind = "Integer" or kind = "roInt" then return m.nativeNumericType
    return kind
end function
function NativeDeliveryFailures(alias as String) as Object
    m.nativeNumericType = alias
    return {http:TaskPlexDeliveryFailure("transcode_stop",{errorCode:"not_found",statusCode:404}),
        network:TaskPlexDeliveryFailure("timeline",{errorCode:"timeout",statusCode:-28}),
        high:TaskPlexDeliveryFailure("timeline",{errorCode:"network_error",statusCode:600}),
        text:TaskPlexDeliveryFailure("timeline",{errorCode:"not_found",statusCode:"404"})}
end function
'''
        with tempfile.TemporaryDirectory(prefix="silo-plex-delivery-native-") as directory:
            temporary = Path(directory)
            worker = temporary / "ApiTask.brs"
            worker.write_text(re.sub(r"\btype\s*\(", "FixtureNativeType(",
                                     (playback.ROOT / "components/ApiTask.brs").read_text(), flags=re.I))
            boundary = temporary / "native-type.brs"
            boundary.write_text(helpers)
            for alias in ("roInteger", "roLongInteger"):
                with self.subTest(alias=alias):
                    result = run_function([worker, boundary], "NativeDeliveryFailures", [alias], root=temporary)
                    self.assert_failure({"outcome": result["http"]}, "transcode_stop", "not_found", 404)
                    self.assert_failure({"outcome": result["network"]}, "timeline", "timeout", -28)
                    self.assert_failure({"outcome": result["high"]}, "timeline", "network_error")
                    self.assert_failure({"outcome": result["text"]}, "timeline", "not_found")


if __name__ == "__main__":
    unittest.main()
