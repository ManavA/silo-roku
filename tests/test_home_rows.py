"""Home RowList projection keeps flat catalog identity and D-pad positions aligned."""

from pathlib import Path
import unittest

from tools.brightscript import run_function


POLICY = Path(__file__).resolve().parents[1] / "source/core/HomeRowsPolicy.brs"


class HomeRowsPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        return run_function(POLICY, name, list(args))

    def card(self, ident, row="continue", label="Continue watching"):
        return {"itemId": ident, "title": f"Title {ident}", "rowId": row,
                "rowTitle": label, "sourceId": "plex:fixture"}

    def test_contiguous_shelves_keep_flat_positions(self):
        items = [self.card("a"), self.card("b"),
                 self.card("c", "recent", "Recently added"),
                 self.card("d", "recent", "Recently added")]
        plan = self.call("HomeRowsPlan", items)
        self.assertEqual([("Continue watching", 0, 2), ("Recently added", 2, 2)],
                         [(row["title"], row["start"], row["count"]) for row in plan["rows"]])
        self.assertEqual([[0, 0], [0, 1], [1, 0], [1, 1]], plan["positions"])
        self.assertEqual(3, self.call("HomeRowsIndexAt", plan, [1, 1]))
        self.assertEqual([1, 0], self.call("HomeRowsPositionFor", plan, 2))

    def test_repeated_identity_in_separate_segments_does_not_merge(self):
        plan = self.call("HomeRowsPlan", [self.card("a"), self.card("b", "other", "Other"),
                                          self.card("c")])
        self.assertEqual([1, 1, 1], [row["count"] for row in plan["rows"]])
        self.assertEqual([[0, 0], [1, 0], [2, 0]], plan["positions"])

    def test_empty_and_invalid_native_positions_are_safe(self):
        empty = self.call("HomeRowsPlan", [])
        self.assertEqual([], empty["rows"])
        self.assertEqual(-1, self.call("HomeRowsIndexAt", empty, [0, 0]))
        self.assertEqual([-1, -1], self.call("HomeRowsPositionFor", empty, 0))
        plan = self.call("HomeRowsPlan", [self.card("a"), self.card("b")])
        for position in ([-1, 0], [0, -1], [1, 0], [0, 2], [], "0,1", [0, "1"]):
            with self.subTest(position=position):
                self.assertEqual(-1, self.call("HomeRowsIndexAt", plan, position))
        self.assertEqual([-1, -1], self.call("HomeRowsPositionFor", plan, 2))

    def test_projection_caps_items_and_handles_untrusted_labels(self):
        items = [self.card(str(i), "", "") for i in range(140)]
        plan = self.call("HomeRowsPlan", items)
        self.assertEqual(101, len(plan["positions"]))
        self.assertEqual("Home", plan["rows"][0]["title"])
        self.assertEqual(101, plan["rows"][0]["count"])
        malformed = self.call("HomeRowsPlan", [{"title": "One", "rowId": 4,
                                                "rowTitle": "a" * 300}])
        self.assertEqual("Home", malformed["rows"][0]["title"])


if __name__ == "__main__":
    unittest.main()
