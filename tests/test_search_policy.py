"""Bounded source-owned search cache and immediate result merge."""

from pathlib import Path
import re
import unittest

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/SearchPolicy.brs"
SOURCE = "plex:fixture-server"


class SearchPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "Search policy is missing")
        self.assertRegex(POLICY.read_text(), r"(?i)function\s+" + re.escape(name) + r"\(")
        return run_function(POLICY, name, list(args))

    def item(self, item_id="101", title="Synthetic Moon", **changes):
        return {"provider": "plex", "sourceId": SOURCE, "itemId": item_id,
                "title": title, "type": "movie", "year": 2026, **changes}

    def test_index_keeps_compact_owned_items_and_newest_copy_only(self):
        initial = self.call("SearchIndexAdd", [], [self.item(token="synthetic-secret", url="https://private.test/x"),
                                                      self.item("102", "Moonrise")], SOURCE, 500)
        self.assertEqual(["101", "102"], [entry["itemId"] for entry in initial])
        self.assertNotIn("synthetic-secret", str(initial))
        self.assertNotIn("private.test", str(initial))
        updated = self.call("SearchIndexAdd", initial, [self.item("101", "Synthetic Moon Reloaded")], SOURCE, 500)
        self.assertEqual(2, len(updated))
        self.assertEqual("Synthetic Moon Reloaded", updated[0]["title"])

    def test_index_rejects_global_wrong_source_and_unsafe_native_ids(self):
        candidates = [self.item(sourceId="plex:other"), self.item(provider="metadata"),
                      self.item(item_id="global:101"), self.item(item_id="1" * 21),
                      self.item(item_id="é101"), self.item(item_id="101", title=""),
                      {"sourceId": "plex-watchlist:account", "itemId": "101", "title": "Global", "type": "movie"}]
        self.assertEqual([], self.call("SearchIndexAdd", [], candidates, SOURCE, 500))
        silo = {"sourceId": "silo:fixture", "itemId": "content-1", "title": "Silo Show", "type": "series"}
        result = self.call("SearchIndexAdd", [], [silo], "silo:fixture", 500)
        self.assertEqual("silo", result[0]["provider"])
        self.assertEqual("series", result[0]["type"])

    def test_index_has_a_hard_bound_and_local_rank_keeps_source_scope(self):
        values = [self.item(str(i + 1), f"Moon {i}") for i in range(600)]
        index = self.call("SearchIndexAdd", [], values, SOURCE, 500)
        self.assertEqual(500, len(index))
        ranked = self.call("SearchLocalMatches", index + [self.item(sourceId="plex:other")], "moon 4", SOURCE, 25)
        self.assertEqual("Moon 4", ranked[0]["title"])
        self.assertLessEqual(len(ranked), 25)
        self.assertTrue(all(entry["sourceId"] == SOURCE for entry in ranked))
        self.assertEqual([], self.call("SearchLocalMatches", index, "m", SOURCE, 25))

    def test_server_merge_keeps_local_order_uses_fresh_duplicate_and_appends_unseen(self):
        local = [self.item("101", "Synthetic Moon"), self.item("102", "Moonrise")]
        server = [self.item("102", "Moonrise", resumeMs=4000), self.item("103", "Moonlight"),
                  self.item("999", "Wrong Source", sourceId="plex:other"),
                  {"title": "Next page", "uiAction": "next_page"}]
        result = self.call("SearchMergeResults", local, server, SOURCE, 100)
        self.assertEqual(["101", "102", "103"], [entry["itemId"] for entry in result])
        self.assertEqual(4000, result[1]["resumeMs"])

    def test_full_local_cache_cannot_hide_new_server_page_items(self):
        local = [self.item(str(i + 1), f"Local {i}") for i in range(100)]
        server = [self.item(str(i + 1001), f"Fresh {i}") for i in range(60)]
        result = self.call("SearchMergeResults", local, server, SOURCE, 100)
        self.assertEqual(100, len(result))
        self.assertEqual(60, sum(int(entry["itemId"]) >= 1001 for entry in result))

    def test_local_ranking_normalizes_case_punctuation_and_all_query_tokens(self):
        candidates = [self.item("106", "Unrelated"), self.item("105", "Moom Baze"),
                      self.item("104", "A Moonbeam Basecamp"), self.item("103", "Base Across Moon"),
                      self.item("102", "Moon Base Returns"), self.item("101", "MOON: BASE")]
        result = self.call("SearchLocalMatches", candidates, "  MOON--base!  ", SOURCE, 100)
        self.assertEqual(["101", "102", "104", "103", "105"], [item["itemId"] for item in result])
        self.assertEqual([], self.call("SearchLocalMatches", candidates, "---", SOURCE, 100))
        result = self.call("SearchLocalMatches", [self.item(title="Étoile—月")], "étoile 月", SOURCE, 100)
        self.assertEqual(["101"], [item["itemId"] for item in result])

    def test_local_typo_matching_uses_plain_levenshtein_and_minimum_token_length(self):
        cases = [("moon", "moom", True), ("moon", "mnoo", False),
                 ("cat", "cut", False), ("nightmoon", "nihtgmoon", True),
                 ("nightmoon", "nxxhtmxon", False), ("nightmoon", "night", True)]
        for title, query, matches in cases:
            with self.subTest(title=title, query=query):
                result = self.call("SearchLocalMatches", [self.item(title=title)], query, SOURCE, 100)
                self.assertEqual(matches, bool(result))
        self.assertEqual([], self.call("SearchLocalMatches", [self.item(title="Moon Base")], "moom missing", SOURCE, 100))

    def test_known_query_correction_only_promotes_its_verified_title(self):
        candidates = [self.item("101", "Reaper"), self.item("102", "Reaper Returns"), self.item("103", "Reacher")]
        result = self.call("SearchLocalMatches", candidates, "reaper", SOURCE, 100)
        self.assertEqual(["103", "101", "102"], [item["itemId"] for item in result])

    def test_equal_bucket_prefers_video_kinds_then_newer_single_token_titles(self):
        candidates = [self.item("101", "Moon", type="collection"),
                      self.item("102", "Moon", type="episode"),
                      self.item("103", "Moon", type="show", year=2005),
                      self.item("104", "Moon", type="movie", year=2026),
                      self.item("105", "Moon", type="movie", year=2026)]
        result = self.call("SearchLocalMatches", candidates, "moon", SOURCE, 100)
        self.assertEqual(["104", "105", "103", "102", "101"], [item["itemId"] for item in result])
        result = self.call("SearchLocalMatches", [self.item("101", "Moon Base", year=2005),
                                                  self.item("102", "Moon Base", year=2026)], "moon base", SOURCE, 100)
        self.assertEqual(["101", "102"], [item["itemId"] for item in result])

    def test_query_merge_ranks_exact_server_before_cached_partial_and_preserves_fresh_duplicate(self):
        local = [self.item("101", "Moon Returns"), self.item("102", "Moonrise")]
        server = [self.item("102", "Moon", resumeMs=9000, thumbKey="/library/synthetic"),
                  self.item("103", "Moon", year=2005),
                  self.item("104", "Backend metadata match"),
                  self.item("999", "Moon", sourceId="plex:other")]
        result = self.call("SearchMergeResults", local, server, SOURCE, 100, "moon")
        self.assertEqual(["102", "103", "101", "104"], [item["itemId"] for item in result])
        self.assertEqual(9000, result[0]["resumeMs"])
        self.assertEqual("/library/synthetic", result[0]["thumbKey"])

    def test_query_merge_ranks_before_result_limit_and_keeps_server_only_metadata_hits(self):
        local = [self.item(str(i + 1), f"Moon part {i}") for i in range(100)]
        server = [self.item("1001", "Moon"), self.item("1002", "A metadata-only hit")]
        result = self.call("SearchMergeResults", local, server, SOURCE, 1, "moon")
        self.assertEqual(["1001"], [item["itemId"] for item in result])
        result = self.call("SearchMergeResults", [], server, SOURCE, 100, "moon")
        self.assertEqual(["1001", "1002"], [item["itemId"] for item in result])

    def test_fuzzy_work_bounds_do_not_stop_later_exact_title_matches(self):
        candidates = [self.item(str(i + 1), "abcabcabc abcabcabd abcabcabe") for i in range(499)]
        candidates += [self.item("500", "Nightmoon"), self.item("501", "Nightmoon")]
        result = self.call("SearchLocalMatches", candidates, "nightmoon", SOURCE, 1000)
        self.assertEqual(["500"], [item["itemId"] for item in result])
        long_token = "a" * 40
        self.assertEqual([], self.call("SearchLocalMatches", [self.item(title=long_token + "b")], long_token + "c", SOURCE, 100))

    def test_bounded_edit_distance_rejects_excess_and_does_not_treat_transposition_as_one(self):
        self.assertEqual(1, self.call("SearchBoundedEditDistance", "moon", "moom", 1))
        self.assertEqual(2, self.call("SearchBoundedEditDistance", "moon", "mnoo", 1))
        self.assertEqual(2, self.call("SearchBoundedEditDistance", "nightmoon", "nihtgmoon", 2))
        self.assertEqual(3, self.call("SearchBoundedEditDistance", "nightmoon", "unrelated", 2))
        self.assertEqual(3, self.call("SearchBoundedEditDistance", "a" * 1000, "a" * 1000, 1000))

    def test_fuzzy_budget_decreases_only_for_edit_comparisons_and_keeps_exact_scan(self):
        output = run_brightscript(POLICY, '''
context = SearchQueryContext("nightmoon")
context.remaining = 1
first = SearchTitleBucket("nightmoom",context)
second = SearchTitleBucket("nightmoom",context)
exact = SearchTitleBucket("Nightmoon",context)
print FormatJson([first,second,exact,context.remaining])''')
        self.assertEqual("[3,4,0,0]", output.strip())


if __name__ == "__main__":
    unittest.main()
