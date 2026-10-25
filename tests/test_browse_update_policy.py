"""Browse redraws preserve native focus ownership and bounded stable identities."""

import json
from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/BrowseUpdatePolicy.brs"
SCOPE = {"provider": "plex", "sourceId": "plex:fixture", "profileId": "owner",
         "generation": 8, "route": "search", "listKind": "items"}


class BrowseUpdatePolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "Browse update policy is missing")
        return run_function(POLICY, name, list(args))

    def item(self, item_id="101", title="Synthetic title", **changes):
        return {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": item_id,
                "type": "movie", "title": title, **changes}

    def plan(self, incoming, previous=None, index=0, owner="catalog", reason="refresh", scope=None):
        return self.call("BrowseUpdatePlan", previous, incoming, scope or SCOPE, index, owner, reason)

    def snapshot(self, items, scope=None):
        return self.plan(items, reason="enter", scope=scope)["state"]

    def test_async_search_reranking_preserves_selected_native_item(self):
        previous = self.snapshot([self.item(), self.item("102", "Selected")])
        items = [self.item("103", "Fresh first result"), self.item(), self.item("102", "Selected hydrated")]
        decision = self.plan(items, previous, 1)
        self.assertEqual(2, decision["index"])
        self.assertEqual("102", decision["items"][decision["index"]]["itemId"])
        self.assertEqual("keep", decision["focusTarget"])
        self.assertTrue(decision["rebuild"])

    def test_async_updates_never_steal_navigation_or_modal_focus(self):
        previous = self.snapshot([self.item()])
        for owner in ("nav", "catalog", "other"):
            with self.subTest(owner=owner):
                decision = self.plan([self.item("102"), self.item()], previous, owner=owner)
                self.assertEqual("keep", decision["focusTarget"])
                self.assertEqual(owner, decision["focusOwner"])

    def test_first_async_result_from_empty_list_keeps_navigation_focus(self):
        previous = self.snapshot([])
        decision = self.plan([self.item()], previous, owner="nav")
        self.assertEqual("keep", decision["focusTarget"])
        self.assertEqual("nav", decision["focusOwner"])
        self.assertEqual(0, decision["index"])

    def test_refresh_that_empties_the_catalog_does_not_request_focus(self):
        decision = self.plan([], self.snapshot([self.item()]))
        self.assertEqual("keep", decision["focusTarget"])
        self.assertEqual("catalog", decision["focusOwner"])
        self.assertEqual(0, decision["index"])

    def test_explicit_enter_focuses_catalog_or_empty_navigation(self):
        self.assertEqual("catalog", self.plan([self.item()], owner="nav", reason="enter")["focusTarget"])
        self.assertEqual("nav", self.plan([], reason="enter")["focusTarget"])

    def test_restore_honors_saved_owner_and_identity_across_route_generation(self):
        previous = self.snapshot([self.item(), self.item("102")])
        scope = {**SCOPE, "generation": 9}
        for owner, target in (("nav", "nav"), ("catalog", "catalog"), ("other", "keep")):
            decision = self.plan([self.item("102"), self.item()], previous, 1, owner, "restore", scope)
            self.assertEqual(0, decision["index"])
            self.assertEqual(target, decision["focusTarget"])

    def test_refresh_cannot_reuse_selection_across_source_profile_route_or_generation(self):
        previous = self.snapshot([self.item(), self.item("102")])
        for change in ({"sourceId": "plex:other"}, {"profileId": "child"},
                       {"provider": "silo"}, {"route": "library"}, {"listKind": "libraries"},
                       {"generation": 9}):
            decision = self.plan([self.item(), self.item("102")], previous, 1, scope={**SCOPE, **change})
            self.assertEqual(0, decision["index"])
            self.assertFalse(decision["matched"])
            self.assertTrue(decision["rebuild"])

    def test_restore_never_reuses_focus_across_viewer_or_route_scope(self):
        previous = self.snapshot([self.item(), self.item("102")])
        for change in ({"sourceId": "plex:other"}, {"profileId": "child"}, {"route": "home"}):
            decision = self.plan([self.item(), self.item("102")], previous, 1, reason="restore", scope={**SCOPE, **change})
            self.assertEqual(0, decision["index"])
            self.assertFalse(decision["matched"])

    def test_home_identity_includes_row_so_repeated_titles_restore_the_right_shelf(self):
        scope = {**SCOPE, "route": "home"}
        history = self.item(rowId="home.continue", rowTitle="Continue")
        shelf = self.item(rowId="section.1.latest", rowTitle="Latest")
        previous = self.snapshot([history, shelf], scope)
        decision = self.plan([self.item("102", rowId="home.continue"), history, shelf], previous, 1, scope=scope)
        self.assertEqual(2, decision["index"])
        self.assertEqual("section.1.latest", decision["items"][2]["rowId"])

    def test_removed_identity_uses_nearest_existing_index_without_jumping_to_top(self):
        previous = self.snapshot([self.item(), self.item("102"), self.item("103"), self.item("104")])
        self.assertEqual(2, self.plan([self.item(), self.item("102"), self.item("104")], previous, 2)["index"])
        self.assertEqual(1, self.plan([self.item(), self.item("102")], previous, 3)["index"])

    def test_fresh_metadata_updates_items_without_rebuilding_identical_labels(self):
        original = self.item(resumeMs=0, watched=False)
        previous = self.snapshot([original])
        updated = {**original, "resumeMs": 40000, "watched": True, "summary": "Fresh summary"}
        decision = self.plan([updated], previous)
        self.assertFalse(decision["rebuild"])
        self.assertFalse(decision["contentChanged"])
        self.assertEqual(40000, decision["items"][0]["resumeMs"])

    def test_label_rendering_exactly_matches_current_native_label_list(self):
        for item, expected in (({"title": "Title", "name": "Name"}, "Title"),
                               ({"name": "Name"}, "Name"), ({}, "Untitled"),
                               ({"title": None, "name": "Name"}, "Name"),
                               ({"title": "", "name": "Name"}, ""),
                               ({"title": "  Title  ", "rowTitle": "  Row  ", "hasPin": True},
                                "  Row   ·   Title   (PIN required)")):
            self.assertEqual(expected, self.call("BrowseItemLabel", item))

    def test_label_identity_order_and_pin_changes_require_rebuild(self):
        previous = self.snapshot([self.item(), self.item("102")])
        for items in ([self.item(title="Renamed"), self.item("102")],
                      [self.item(hasPin=True), self.item("102")],
                      [self.item(rowTitle="New shelf"), self.item("102")],
                      [self.item("102"), self.item()], [self.item("999"), self.item("102")]):
            self.assertTrue(self.plan(items, previous)["rebuild"])

    def test_nonmedia_controls_have_stable_identity_separate_from_titles(self):
        cases = [({"uiAction": "next_page", "title": "Next page"}, "title"),
                 ({"profileId": "p1", "name": "Viewer"}, "name"),
                 ({"machineId": "server1", "title": "Server"}, "title"),
                 ({"libraryId": "l1", "title": "Library"}, "title"),
                 ({"personId": "p1", "title": "Person"}, "title"),
                 ({"catalogId": "metadata:movie:1", "title": "Discover"}, "title"),
                 ({"versionId": "plex:fixture:101:1:2", "itemId": "101", "title": "Version"}, "title"),
                 ({"uiAction": "person_search", "name": "Person", "title": "Person · Role"}, "title")]
        for control, label_field in cases:
            with self.subTest(control=control):
                previous = self.snapshot([self.item(), control])
                changed = {**control, label_field: "Hydrated label"}
                decision = self.plan([changed, self.item()], previous, 1)
                self.assertEqual(0, decision["index"])
                self.assertTrue(decision["matched"])

    def test_duplicate_keys_or_anonymous_labels_do_not_claim_exact_identity(self):
        for items in ([self.item(), self.item()], [{"title": "Same"}, {"title": "Same"}]):
            previous = self.snapshot(items)
            decision = self.plan(items, previous, 1)
            self.assertEqual(1, decision["index"])
            self.assertFalse(decision["matched"])

    def test_native_id_and_row_segments_cannot_alias_on_delimiter_characters(self):
        first = self.item("a|b", rowId="c")
        second = self.item("b", rowId="c|a")
        self.assertNotEqual(self.call("BrowseItemKey", first, SCOPE), self.call("BrowseItemKey", second, SCOPE))

    def test_planner_caps_results_and_snapshot_at_101_without_mutating_input(self):
        items = [self.item(str(i)) for i in range(140)]
        decision = self.plan(items, index=139, reason="enter")
        self.assertEqual(101, len(decision["items"]))
        self.assertEqual(101, len(decision["state"]["keys"]))
        self.assertEqual(101, len(decision["state"]["labels"]))
        self.assertEqual(100, decision["index"])
        self.assertEqual(140, len(items))

    def test_snapshot_keeps_no_raw_cards_headers_or_artwork(self):
        item = self.item(summary="do-not-retain-summary", headers={"X-Token": "do-not-retain-secret"},
                         thumbKey="https://art.example.test/private", versions=[{"versionId": "hidden"}])
        state = self.snapshot([item])
        serialized = json.dumps(state)
        for forbidden in ("do-not-retain", "https://", "headers", "thumbKey", "versions", "summary"):
            self.assertNotIn(forbidden, serialized)

    def test_oversized_labels_are_bounded_and_never_falsely_count_as_unchanged(self):
        item = self.item(title="X"*4000)
        state = self.snapshot([item])
        self.assertLessEqual(len(state["labels"][0]), 512)
        changed = self.plan([self.item(title="X"*3999+"Y")], state)
        self.assertTrue(changed["rebuild"])

    def test_malformed_snapshot_items_and_index_fail_without_requesting_focus(self):
        for index in (None, True, -1, 99, "1", {}, 1.5):
            decision = self.plan([self.item()], {"keys": "bad", "labels": []}, index)
            self.assertEqual(0, decision["index"])
            self.assertEqual("keep", decision["focusTarget"])
        decision = self.plan(None)
        self.assertEqual([], decision["items"])
        self.assertEqual("keep", decision["focusTarget"])


if __name__ == "__main__":
    unittest.main()
