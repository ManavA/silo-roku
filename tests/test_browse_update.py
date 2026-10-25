"""Pure browse update policy: preserve D-pad identity without list churn."""

from pathlib import Path
import unittest

from tools.brightscript import run_function


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/BrowseUpdatePolicy.brs"
SCOPE = {"provider": "plex", "sourceId": "plex:server-a", "profileId": "owner",
         "generation": 4, "route": "search", "listKind": "items"}


class BrowseUpdateTests(unittest.TestCase):
    def plan(self, previous, items, index=0, owner="catalog", reason="refresh", scope=None):
        self.assertTrue(POLICY.is_file(), "Browse update policy is missing")
        return run_function(POLICY, "BrowseUpdatePlan",
                            [previous, items, scope or SCOPE, index, owner, reason])

    def card(self, item_id, title="Fixture title", **changes):
        return {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": item_id,
                "title": title, "type": "movie", **changes}

    def test_refresh_keeps_selected_title_when_server_results_rerank(self):
        initial = [self.card("101", "Moon Returns"), self.card("102", "Moon")]
        first = self.plan(None, initial, 1, "catalog", "enter")
        changed = [self.card("102", "Moon", resumeMs=4000), self.card("101", "Moon Returns")]
        next_plan = self.plan(first["state"], changed, 1)
        self.assertEqual(0, next_plan["index"])
        self.assertEqual("keep", next_plan["focusTarget"])
        self.assertTrue(next_plan["rebuild"])
        self.assertEqual(4000, next_plan["items"][0]["resumeMs"])

    def test_home_rows_distinguish_duplicate_item_id(self):
        scope = {**SCOPE, "route": "home"}
        first = self.plan(None, [self.card("101", rowId="home.continue"),
                                 self.card("101", rowId="plex.1.recent")], 1, "catalog", "enter", scope)
        refreshed = self.plan(first["state"], [self.card("101", rowId="plex.1.recent"),
                                                self.card("101", rowId="home.continue")], 1, "catalog", "refresh", scope)
        self.assertEqual(0, refreshed["index"])

    def test_metadata_only_refresh_updates_card_without_rebuilding_content(self):
        first = self.plan(None, [self.card("101", resumeMs=1000)], 0, "catalog", "enter")
        next_plan = self.plan(first["state"], [self.card("101", resumeMs=2000)], 0)
        self.assertFalse(next_plan["rebuild"])
        self.assertFalse(next_plan["contentChanged"])
        self.assertEqual(2000, next_plan["items"][0]["resumeMs"])

    def test_label_change_rebuilds_even_if_identity_is_same(self):
        first = self.plan(None, [self.card("101", "Old")], 0, "catalog", "enter")
        next_plan = self.plan(first["state"], [self.card("101", "New")], 0)
        self.assertTrue(next_plan["rebuild"])
        self.assertTrue(next_plan["contentChanged"])

    def test_nav_owner_stays_on_nav_during_async_refresh(self):
        first = self.plan(None, [self.card("101")], 0, "catalog", "enter")
        next_plan = self.plan(first["state"], [self.card("102")], 0, "nav")
        self.assertEqual("keep", next_plan["focusTarget"])
        self.assertEqual("nav", next_plan["focusOwner"])

    def test_enter_and_restore_focus_are_explicit(self):
        entered = self.plan(None, [self.card("101")], 0, "other", "enter")
        self.assertEqual("catalog", entered["focusTarget"])
        restored_nav = self.plan(None, [self.card("101")], 0, "nav", "restore")
        self.assertEqual("nav", restored_nav["focusTarget"])
        restored_catalog = self.plan(None, [self.card("101")], 0, "catalog", "restore")
        self.assertEqual("catalog", restored_catalog["focusTarget"])
        empty = self.plan(None, [], 0, "catalog", "enter")
        self.assertEqual("nav", empty["focusTarget"])

    def test_scope_change_does_not_reuse_old_selected_identity(self):
        first = self.plan(None, [self.card("101"), self.card("102")], 1, "catalog", "enter")
        other = {**SCOPE, "profileId": "child"}
        next_plan = self.plan(first["state"], [self.card("102"), self.card("101")], 1,
                              "catalog", "refresh", other)
        self.assertEqual(0, next_plan["index"])
        self.assertTrue(next_plan["rebuild"])

    def test_state_is_compact_bounded_and_omits_sensitive_card_data(self):
        items = [self.card(str(i), "Title " + str(i), token="synthetic-secret",
                           url="https://private.test/watch") for i in range(150)]
        result = self.plan(None, items, 149, "catalog", "enter")
        self.assertEqual(101, len(result["items"]))
        self.assertEqual(100, result["index"])
        self.assertLessEqual(len(result["state"]["keys"]), 101)
        self.assertNotIn("synthetic-secret", str(result["state"]))
        self.assertNotIn("private.test", str(result["state"]))

    def test_action_and_source_selectors_have_stable_identity(self):
        first = self.plan(None, [{"title": "Next page", "uiAction": "next_page"},
                                 {"name": "Server A", "machineId": "machine-a"}], 1,
                          "catalog", "enter")
        next_plan = self.plan(first["state"], [{"name": "Server A", "machineId": "machine-a"},
                                                {"title": "Next page", "uiAction": "next_page"}], 1)
        self.assertEqual(0, next_plan["index"])


if __name__ == "__main__":
    unittest.main()
