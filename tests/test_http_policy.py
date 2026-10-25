"""HTTP errors shown to the scene have stable codes and no response text."""

from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/network/Http.brs"


class HttpPolicyTests(unittest.TestCase):
    def test_status_mapping(self):
        expected = {401: "auth_required", 403: "forbidden", 404: "not_found",
                    408: "network_timeout", 425: "server_error",
                    429: "rate_limited", 500: "server_error", 503: "server_error",
                    418: "http_error", 0: "network_error", -1: "network_error"}
        for status, code in expected.items():
            with self.subTest(status=status):
                self.assertEqual(run_function(POLICY, "HttpErrorCode", [status]), code)

    def test_request_timeout_is_bounded_and_explicit_callers_keep_their_budget(self):
        cases = [({}, 0, 9000), ({"timeoutMs": 30000}, 0, 30000),
                 ({"timeoutMs": 12000}, 5000, 5000), ({"timeoutMs": 1000000}, 0, 30000),
                 ({"timeoutMs": "secret"}, 0, 9000), ({"timeoutMs": -1}, 0, 9000),
                 ({}, 45000, 30000),
                 ({"siloPlaybackPreparation": True}, 45000, 45000),
                 ({"siloPlaybackPreparation": True}, 90000, 90000),
                 ({"siloPlaybackPreparation": True}, 1000000, 90000),
                 ({"siloPlaybackPreparation": True}, 0, 9000),
                 ({"siloPlaybackPreparation": True}, 12000, 12000),
                 ({"siloPlaybackPreparation": True, "timeoutMs": 45000}, 5000, 5000),
                 ({"siloPlaybackPreparation": False}, 45000, 30000)]
        for request, override, expected in cases:
            with self.subTest(request=request, override=override):
                self.assertEqual(expected, run_function(POLICY, "HttpTimeoutMs", [request, override]))


if __name__ == "__main__":
    unittest.main()
