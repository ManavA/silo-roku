"""Execute real policy functions; UI and network behavior still need a Roku."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from brightscript import interpreter_available, run_brightscript, run_function


class BrightScriptRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not interpreter_available():
            message = "install runtime tests: npm ci --prefix tools/brightscript --ignore-scripts"
            if os.environ.get("SILO_REQUIRE_BRS") == "1":
                raise RuntimeError(message)
            raise unittest.SkipTest(message)

    def test_executes_source_picker_policy_from_the_packaged_script(self):
        output = run_brightscript(
            [ROOT / "components" / "SourceSetup.brs"],
            'print FormatJson([sourceForIndex(0), sourceForIndex(1), sourceForIndex(-1), sourceForIndex(2)])',
        )
        self.assertEqual(output.strip(), '["plex","silo","",""]')

    def test_json_fixture_is_decoded_by_the_brightscript_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_root = Path(directory)
            (fixture_root / "fixture.json").write_text('{"items":[{"id":"fixture-item","title":"Example"}]}')
            output = run_brightscript(
                [],
                'fixture = ParseJson(ReadAsciiFile("pkg:/fixture.json"))\nprint fixture.items[0].id',
                root=fixture_root,
            )
            self.assertEqual(output.strip(), "fixture-item")

    def test_function_result_is_decoded_without_reimplementing_the_policy(self):
        self.assertEqual(
            run_function(ROOT / "components" / "SourceSetup.brs", "sourceForIndex", [1]),
            "silo",
        )

    def test_function_arguments_preserve_quotes_nested_values_and_null(self):
        with tempfile.TemporaryDirectory() as directory:
            function_path = Path(directory) / "echo.brs"
            function_path.write_text("function EchoFixture(value as Object) as Object\nreturn value\nend function\n")
            value = {"title": 'A "quoted" title', "parts": [1, True, None]}
            self.assertEqual(run_function(function_path, "EchoFixture", [value]), value)

    def test_runtime_failure_cannot_be_reported_as_a_passing_test(self):
        with self.assertRaisesRegex(RuntimeError, "BrightScript execution failed"):
            run_brightscript([], "print functionThatDoesNotExist()")

    def test_invalid_json_returns_invalid_for_adapter_error_classification(self):
        self.assertEqual(
            run_brightscript([], 'if ParseJson("{") = invalid then print "invalid"'),
            "invalid",
        )

    def test_syntax_error_cannot_be_reported_as_a_passing_test(self):
        with self.assertRaisesRegex(RuntimeError, "BrightScript execution failed"):
            run_brightscript([], "if then")

    def test_removed_detail_list_warning_is_rejected(self):
        native_warning = "Warning: XML component 'DetailActionList' extends unknown component 'LabelList'. Ignoring extension."
        result = SimpleNamespace(returncode=0, stdout='{"result":null,"stdout":"policy passed"}', stderr=native_warning + "\n")
        with patch("brightscript.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "BrightScript execution failed"):
                run_brightscript([], 'print "policy passed"')

    def test_person_photo_task_warning_allows_completed_native_boundary(self):
        warning = "Warning: XML component 'PersonPhotoTask' extends unknown component 'Task'. Ignoring extension."
        result = SimpleNamespace(returncode=0, stdout='{"result":null,"stdout":"photo policy passed"}', stderr=warning + "\n")
        with patch("brightscript.subprocess.run", return_value=result):
            self.assertEqual("photo policy passed", run_brightscript([], 'print "photo policy passed"'))

    def test_local_qr_task_warning_allows_completed_native_boundary(self):
        warning = "Warning: XML component 'SiloUIQrTask' extends unknown component 'Task'. Ignoring extension."
        result = SimpleNamespace(returncode=0, stdout='{"result":null,"stdout":"qr policy passed"}', stderr=warning + "\n")
        with patch("brightscript.subprocess.run", return_value=result):
            self.assertEqual("qr policy passed", run_brightscript([], 'print "qr policy passed"'))

    def test_native_widget_warning_never_hides_other_diagnostics_or_process_failure(self):
        native_warning = "Warning: XML component 'PersonPhotoTask' extends unknown component 'Task'. Ignoring extension."
        for status, diagnostic in (
            (0, "Warning: XML component 'UnexpectedList' extends unknown component 'LabelList'. Ignoring extension."),
            (0, "Error: a real policy function failed"),
            (0, "Warning: XML component 'UnknownPhotoTask' extends unknown component 'Task'. Ignoring extension."),
            (1, ""),
        ):
            with self.subTest(status=status, diagnostic=diagnostic):
                result = SimpleNamespace(returncode=status, stdout='{"result":null,"stdout":""}', stderr=native_warning + "\n" + diagnostic)
                with patch("brightscript.subprocess.run", return_value=result):
                    with self.assertRaisesRegex(RuntimeError, "BrightScript execution failed"):
                        run_brightscript([], "print 1")


if __name__ == "__main__":
    unittest.main()
