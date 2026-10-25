"""Retained pure browse projection and navigation policies; component coordinator retired."""

import json
import unittest
from pathlib import Path
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/BrowseScreenPolicy.brs"
ROWS = ROOT / "source/core/HomeRowsPolicy.brs"


def model(items, **changes):
    return {"title": "Home", "status": "", "presentation": "grid", "items": items,
            "selectedIndex": 0, "navKey": "home", "scopeKey": "plex:fixture:owner:home",
            **changes}


def card(item_id, **changes):
    return {"itemId": item_id, "title": f"Title {item_id}", **changes}


class BrowseScreenPolicyTests(unittest.TestCase):
    def call(self, function, *args):
        self.assertTrue(POLICY.is_file(), "The fresh browse policy is missing")
        return run_function([POLICY, ROWS], function, list(args))

    def plan(self, value, previous=None, index=0, owner="content", restore=False):
        return self.call("BrowseScreenPlan", previous, value, index, owner, restore)

    def test_refresh_preserves_unique_stable_key_after_insertion(self):
        first = self.plan(model([card("a"), card("b")]))
        refreshed = self.plan(model([card("x"), card("a"), card("b", title="Hydrated")]),
                              first["state"], index=1)
        self.assertEqual(2, refreshed["index"])
        self.assertEqual("b", refreshed["items"][2]["key"])
        self.assertEqual("keep", refreshed["focusTarget"])

    def test_loading_and_first_results_keep_navigation_owner_and_selection_anchor(self):
        first = self.plan(model([card("a"), card("b")]))
        empty = self.plan(model([], status="Loading"), first["state"], index=1, owner="nav")
        self.assertEqual((0, "keep"), (empty["index"], empty["focusTarget"]))
        arrived = self.plan(model([card("x"), card("a"), card("b")]), empty["state"], owner="nav")
        self.assertEqual((2, "keep"), (arrived["index"], arrived["focusTarget"]))

    def test_changed_scope_resets_identity_and_index(self):
        first = self.plan(model([card("a"), card("b")]))
        changed = self.plan(model([card("b"), card("a")], scopeKey="silo:another:home"),
                            first["state"], index=1, owner="nav")
        self.assertEqual((0, "keep"), (changed["index"], changed["focusTarget"]))

    def test_long_distinct_scopes_do_not_share_a_truncated_identity(self):
        prefix = "x" * 256
        first = self.plan(model([card("a"), card("b")], scopeKey=prefix + "one"))
        changed = self.plan(model([card("a"), card("b")], scopeKey=prefix + "two"),
                            first["state"], index=1, owner="nav")
        self.assertEqual((0, True), (changed["index"], changed["rebuild"]))
        self.assertNotEqual(first["state"]["scopeKey"], changed["state"]["scopeKey"])

    def test_paging_does_not_replace_any_of_the_100_titles(self):
        result = self.plan(model([card(str(index)) for index in range(100)], hasNextPage=True))
        self.assertIs(True, result.get("hasNextPage"))
        self.assertEqual((100, "99"), (len(result["items"]), result["items"][-1]["key"]))
        self.assertIs(False, self.plan(model([])).get("hasNextPage"))

    def test_explicit_restore_uses_requested_index_without_acquiring_focus(self):
        first = self.plan(model([card("a"), card("b")]))
        restored = self.plan(model([card("a"), card("b")], selectedIndex=1),
                             first["state"], owner="nav", restore=True)
        self.assertEqual((1, "keep"), (restored["index"], restored["focusTarget"]))

    def test_identical_display_facts_skip_content_rebuild(self):
        first = self.plan(model([card("a", progressSeconds=1)]))
        refreshed = self.plan(model([card("a", progressSeconds=2, token="ignored")]),
                              first["state"])
        self.assertFalse(refreshed["rebuild"])
        for changed in (model([card("a", title="New title")]),
                        model([card("a")], presentation="rows")):
            self.assertTrue(self.plan(changed, first["state"])["rebuild"])

    def test_renderer_change_retains_content_ownership(self):
        first = self.plan(model([card("a"), card("b")]))
        changed = self.plan(model([card("a"), card("b")], presentation="list"),
                            first["state"], index=1)
        self.assertEqual((1, "content"), (changed["index"], changed["focusTarget"]))
        nav = self.plan(model([card("a"), card("b")], presentation="rows"),
                        first["state"], index=1, owner="nav")
        self.assertEqual("keep", nav["focusTarget"])

    def test_projection_caps_cards_and_retains_no_private_provider_fields(self):
        items = [card(str(index), token="private-secret", headers={"X-Token": "private-secret"},
                      url="https://media.example.test/private", summary="private-summary")
                 for index in range(140)]
        result = self.plan(model(items), index=139)
        self.assertEqual(100, len(result["items"]))
        self.assertEqual(100, len(result["state"]["keys"]))
        self.assertEqual(99, result["items"][-1]["nativeIndex"])
        serialized = json.dumps(result)
        for private in ("private-secret", "private-summary", "https://", "headers", '"url"'):
            self.assertNotIn(private, serialized)
        self.assertEqual(140, len(items))

    def test_url_and_malformed_identity_fall_back_to_anonymous_position(self):
        for unsafe in ("https://private.example.test/?token=secret", "a/b", "x" * 200, {}, None):
            result = self.plan(model([card(unsafe)]))
            self.assertEqual("", result["items"][0]["key"])
        explicit = self.plan(model([card("native", key="action:next_page")]))
        self.assertEqual("action:next_page", explicit["items"][0]["key"])

    def test_duplicate_identity_does_not_move_selection_to_first_match(self):
        first = self.plan(model([card("a"), card("a")]))
        result = self.plan(model([card("a"), card("a")]), first["state"], index=1)
        self.assertEqual(1, result["index"])

    def test_malformed_model_and_indices_produce_bounded_empty_display(self):
        for value in (None, [], "bad"):
            result = self.plan(value, owner="nav")
            self.assertEqual(([], 0, "list", "keep"),
                             (result["items"], result["index"], result["presentation"], result["focusTarget"]))
        for index in (None, True, -1, "1", {}, 1.5):
            result = self.plan(model([card("a"), card("b")], selectedIndex=index))
            self.assertEqual(0, result["index"])

    def test_titles_and_row_labels_are_bounded(self):
        result = self.plan(model([card("a", title="x" * 900, rowTitle="r" * 900)],
                                title="t" * 900, status="s" * 900))
        self.assertLessEqual(len(result["items"][0]["title"]), 256)
        self.assertLessEqual(len(result["items"][0]["rowTitle"]), 80)
        self.assertLessEqual(len(result["title"]), 160)
        self.assertLessEqual(len(result["status"]), 512)

    def test_native_left_boundary_and_navigation_keys(self):
        for presentation, index, position, expected in (
                ("grid", 6, [0, 0], True), ("grid", 5, [0, 0], False),
                ("rows", 2, [1, 0], True), ("rows", 1, [0, 1], False),
                ("list", 3, [0, 0], True)):
            self.assertEqual(expected, self.call("BrowseScreenLeftEdge", presentation, index, position))
        self.assertEqual(["home", "library", "search", "discover", "services", "ava", "watchlist", "settings"],
                         self.call("BrowseScreenNavigationKeys"))
