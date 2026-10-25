"""Every catalog identity presented to the scene belongs to the selected source."""

from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/MediaScope.brs"


class MediaScopeTests(unittest.TestCase):
    def test_rows_pages_and_detail_are_scoped_without_mutating_input(self):
        original = {"rows": [{"title": "Continue", "items": [{"itemId": "m1", "sourceId": "silo"}]}],
                    "items": [{"itemId": "m2", "sourceId": "silo"}],
                    "item": {"itemId": "m3", "sourceId": "silo"},
                    "libraries": [{"libraryId": "lib1", "sourceId": "silo"}],
                    "versions": [{"versionId": "f1"}]}
        scoped = run_function(POLICY, "ScopeCatalogData", [original, "silo:https://one"])
        self.assertEqual(scoped["rows"][0]["items"][0]["sourceId"], "silo:https://one")
        self.assertEqual(scoped["items"][0]["sourceId"], "silo:https://one")
        self.assertEqual(scoped["item"]["sourceId"], "silo:https://one")
        self.assertEqual(scoped["libraries"][0]["sourceId"], "silo:https://one")
        self.assertEqual(scoped["versions"][0]["sourceId"], "silo:https://one")
        self.assertEqual(original["item"]["sourceId"], "silo")

    def test_detail_extras_and_people_are_scoped(self):
        original = {"extras": [{"itemId": "trailer", "sourceId": "silo"}],
                    "cast": [{"personId": "p1", "sourceId": "silo"}],
                    "crew": [{"personId": "p2", "sourceId": "silo"}],
                    "person": {"personId": "p3", "sourceId": "silo"}}
        scoped = run_function(POLICY, "ScopeCatalogData", [original, "silo:active"])
        self.assertEqual("silo:active", scoped["extras"][0]["sourceId"])
        self.assertEqual("silo:active", scoped["cast"][0]["sourceId"])
        self.assertEqual("silo:active", scoped["crew"][0]["sourceId"])
        self.assertEqual("silo:active", scoped["person"]["sourceId"])


if __name__ == "__main__":
    unittest.main()
