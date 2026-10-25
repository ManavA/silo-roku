"""The development interpreter must preserve Roku's documented JSON semantics."""

from pathlib import Path
import unittest

from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class BrightScriptJsonTests(unittest.TestCase):
    def test_parse_json_preserves_case_sensitive_duplicate_names(self):
        actual = run_brightscript([], '''
payload = ParseJson("{""guid"":""plex://movie/global-a"",""Guid"":[{""id"":""tmdb://123""}]}")
print payload.Lookup("guid")
print payload.Lookup("Guid")[0].id
''')
        self.assertEqual(actual.splitlines(), ["plex://movie/global-a", "tmdb://123"])

    def test_parse_json_case_insensitive_flag_keeps_last_duplicate(self):
        actual = run_brightscript([], '''
payload = ParseJson("{""Name"":""first"",""name"":""last""}", "i")
print payload.Lookup("NAME")
''')
        self.assertEqual(actual, "last")

    def test_parse_json_nested_objects_and_malformed_input(self):
        actual = run_brightscript([], '''
payload = ParseJson("{""items"":[{""Title"":""first"",""title"":""second""}]}")
print payload.items[0].Lookup("Title")
print payload.items[0].Lookup("title")
print ParseJson("bad-json") = invalid
''')
        self.assertEqual(actual.splitlines(), ["first", "second", "true"])


if __name__ == "__main__":
    unittest.main()
