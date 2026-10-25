"""Bounded Silo problems become codes while server text stays inside the Task."""

import json
from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
HTTP = ROOT / "source/network/Http.brs"
TASK = ROOT / "components/ApiTask.brs"
SILO = ROOT / "source/adapters/SiloAdapter.brs"
FILES = [HTTP, SILO, TASK]


def problem(status, code, **changes):
    body = {"status": status, "type": "https://siloserver.org/docs/api/v2/problems/" + code,
            "title": "private title", "detail": "private-token", "instance": "private-url"}
    body.update(changes)
    return json.dumps(body)


class SiloHttpErrorTests(unittest.TestCase):
    def response(self, request, status, body):
        self.assertTrue("function HttpResponse(" in HTTP.read_text(), "bounded HTTP completion policy is missing")
        return run_function(HTTP, "HttpResponse", [request, status, body])

    def public_error(self, status, body, fallback="forbidden"):
        self.assertTrue("function TaskSiloHttpError(" in TASK.read_text(), "Silo Task error decoder is missing")
        response = {"ok": False, "statusCode": status, "errorCode": fallback, "body": body}
        return run_function(FILES, "TaskSiloHttpError", [response])

    def test_http_errors_dispose_server_text_without_explicit_opt_in(self):
        self.assertEqual({"ok": False, "statusCode": 403, "errorCode": "forbidden"},
                         self.response({}, 403, "private-token"))

    def test_silo_request_explicitly_opts_into_bounded_problem_decoding(self):
        result = run_function(SILO, "BuildSiloRequest", ["device_capability", {"baseUrl": "https://silo.example"}, {}])
        self.assertEqual(8192, result.get("errorBodyLimit"))

    def test_http_error_retention_honors_a_small_limit_and_never_exceeds_8kib(self):
        for limit, size, retained in ((8, 8, True), (8, 9, False), (8192, 8192, True),
                                      (8192, 8193, False), (1000000, 8193, False), (1000000, 1, False),
                                      (0, 1, False), (-1, 1, False), ("8192", 1, False)):
            with self.subTest(limit=limit, size=size):
                result = self.response({"errorBodyLimit": limit}, 403, "x" * size)
                self.assertEqual(retained, "body" in result)
                self.assertEqual("forbidden", result["errorCode"])
        result = self.response({"errorBodyLimit": 8192}, 403, "é" * 5000)
        self.assertNotIn("body", result, "the cap measures UTF-8 bytes, not characters")

    def test_native_http_error_retention_uses_the_same_validated_opt_in(self):
        self.assertTrue("function HttpErrorBodyLimit(" in HTTP.read_text())
        for request, expected in (({}, 0), ({"errorBodyLimit": 1}, 1), ({"errorBodyLimit": 8192}, 8192),
                                  ({"errorBodyLimit": 8193}, 0), ({"errorBodyLimit": -1}, 0),
                                  ({"errorBodyLimit": "8192"}, 0), ({"errorBodyLimit": True}, 0)):
            with self.subTest(request=request):
                self.assertEqual(expected, run_function(HTTP, "HttpErrorBodyLimit", [request]))
        self.assertTrue("transfer.RetainBodyOnError(HttpErrorBodyLimit(request) > 0)" in HTTP.read_text())

    def test_successful_http_responses_keep_the_existing_body_contract(self):
        self.assertEqual({"ok": True, "statusCode": 200, "body": "response"},
                         self.response({}, 200, "response"))
        self.assertEqual({"ok": True, "statusCode": 204, "body": ""},
                         self.response({}, 204, None))

    def test_known_silo_problems_return_only_a_public_code(self):
        for status, code in ((403, "profile_locked"), (403, "profile_required"),
                             (403, "profile_pin_required"), (403, "device_login_disabled"),
                             (422, "validation_failed")):
            with self.subTest(status=status, code=code):
                self.assertEqual({"ok": False, "errorCode": code}, self.public_error(status, problem(status, code)))

    def test_http_auth_and_retry_statuses_override_problem_body_types(self):
        for status, code in ((401, "auth_required"), (408, "network_timeout"),
                             (425, "server_error"), (429, "rate_limited"), (503, "server_error")):
            with self.subTest(status=status):
                result = self.public_error(status, problem(status, "profile_locked"), code)
                self.assertEqual({"ok": False, "errorCode": code}, result)

    def test_invalid_or_mismatched_problems_keep_the_http_error(self):
        for body in ("{", "[]", "null", "{}", "private-token", problem(401, "profile_locked"),
                     problem("403", "profile_locked"), problem(403, "profile_locked", type="")):
            with self.subTest(body=body):
                self.assertEqual({"ok": False, "errorCode": "forbidden"}, self.public_error(403, body))

    def test_unknown_problem_types_cannot_echo_private_fields(self):
        for kind in ("/", "private-token", "https://private.example/path?token=private-token"):
            with self.subTest(kind=kind):
                result = self.public_error(403, problem(403, "unknown", type=kind))
                self.assertEqual({"ok": False, "errorCode": "silo_problem"}, result)

    def test_task_does_not_decode_oversized_body_even_if_transport_is_bypassed(self):
        body = problem(403, "profile_locked", detail="x" * 8192)
        self.assertEqual({"ok": False, "errorCode": "forbidden"}, self.public_error(403, body))
        body = problem(403, "profile_locked", detail="é" * 5000)
        self.assertEqual({"ok": False, "errorCode": "forbidden"}, self.public_error(403, body))

    def test_error_decoding_is_wired_for_auth_catalog_and_playback_fetch(self):
        source = TASK.read_text()
        dispatch = source.split("function ExecuteApiAction(", 1)[1].split("end function", 1)[0]
        self.assertIn('TaskString(TaskSiloHttpError(response), "errorCode")', dispatch)
        self.assertIn('TaskAuthTransportFailure(provider, action, response,', dispatch)
        fetch = source.split("function TaskSiloFetch(", 1)[1].split("end function", 1)[0]
        self.assertTrue("if response.ok <> true then return TaskSiloHttpError(response)" in fetch)
        http = HTTP.read_text().split("function HttpRequest(", 1)[1].split("end function", 1)[0]
        self.assertTrue("return HttpResponse(request, status, body, headers)" in http)


if __name__ == "__main__":
    unittest.main()
