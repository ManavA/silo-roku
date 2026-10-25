"""Retained pure AVA candidate cache policies; legacy scene integration is retired."""

import json
import os
from pathlib import Path
import unittest
from tools.brightscript import interpreter_available, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/AvaCandidatePolicy.brs"
SCRIPTS = [ROOT / "source/adapters/MetadataAdapter.brs",
           ROOT / "source/core/MetadataUiPolicy.brs",
           ROOT / "source/core/ServicePolicy.brs", POLICY]
SCOPE = {"sourceId": "plex:synthetic-server", "profileId": "owner"}


class AvaCandidateCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not interpreter_available():
            message = "install runtime tests: npm ci --prefix tools/brightscript --ignore-scripts"
            if os.environ.get("SILO_REQUIRE_BRS") == "1":
                raise RuntimeError(message)
            raise unittest.SkipTest(message)


    def call(self, name, *arguments):
        self.assertTrue(POLICY.is_file(), "AVA candidate cache policy is missing")
        return run_function(SCRIPTS, name, list(arguments))


    def card(self, item_id="501", **changes):
        return {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": item_id,
                "title": "Synthetic Moon", "type": "movie", "year": 2026,
                "guids": ["tmdb://101", "imdb://tt0000101"], "genres": ["Drama"],
                "rating": 8, **changes}


    def cache(self, values, existing=None, scope=SCOPE, limit=180):
        return self.call("AvaCandidateCacheAdd", existing, values, scope, limit)


    def test_cache_accumulates_newest_native_ids_and_retains_prior_pages(self):
        first = self.cache([self.card(), self.card("502")])
        next_page = self.cache([self.card("503"), self.card(title="Updated Moon"),
                                self.card(title="Duplicate")], existing=first)
        self.assertEqual(["503", "501", "502"], [card["itemId"] for card in next_page["items"]])
        self.assertEqual("Updated Moon", next_page["items"][1]["title"])
        self.assertEqual(next_page, self.cache([], existing=next_page))


    def test_revoked_native_card_tombstones_older_owned_candidate(self):
        first = self.cache([self.card(), self.card("502")])
        retired = self.cache([self.card(owned=False)], existing=first)
        self.assertEqual(["502"], [card["itemId"] for card in retired["items"]])


    def test_id_loss_replaces_old_external_ids_with_current_title_only_facts(self):
        first = self.cache([self.card()])
        next_page = self.cache([self.card(guids=[])], existing=first)
        self.assertEqual(["501"], [card["itemId"] for card in next_page["items"]])
        self.assertEqual(("", ""), (next_page["items"][0]["tmdbId"], next_page["items"][0]["imdbId"]))


    def test_episode_empty_and_malformed_lists_keep_existing_movie_show_candidates(self):
        first = self.cache([self.card(), self.card("502", type="show")])
        for values in ([], None, {}, [None], [self.card("503", type="episode")]):
            with self.subTest(values=values):
                self.assertEqual(first, self.cache(values, existing=first))


    def test_cache_scope_and_submission_include_active_source_and_profile(self):
        first = self.cache([self.card()])
        for scope in ({**SCOPE, "profileId": "child"}, {**SCOPE, "sourceId": "plex:other"}):
            with self.subTest(scope=scope):
                self.assertEqual([], self.cache([], existing=first, scope=scope)["items"])
                self.assertEqual([], self.call("AvaCandidateCacheItems", first, scope))
        for scope in (None, {}, {"sourceId": "metadata:global", "profileId": "owner"},
                      {**SCOPE, "profileId": 5}, {**SCOPE, "sourceId": "plex"}):
            with self.subTest(scope=scope):
                self.assertEqual([], self.cache([self.card()], scope=scope)["items"])
                self.assertEqual([], self.call("AvaCandidateCacheItems", first, scope))


    def test_wrong_source_provider_kind_and_unsafe_native_ids_are_rejected(self):
        values = [self.card(sourceId="plex:other"), self.card(provider="metadata"),
                  self.card(type="episode"), self.card(type="person"), self.card(owned=False),
                  self.card("global:501"), self.card("501?token=synthetic-secret")]
        self.assertEqual([], self.cache(values)["items"])


    def test_silo_title_only_series_candidates_are_preserved(self):
        scope = {"sourceId": "silo:synthetic-server", "profileId": "owner"}
        raw = self.card("series-501", provider="silo", sourceId=scope["sourceId"], type="series", guids=[])
        cache = self.cache([raw], scope=scope)
        self.assertEqual(("show", "", ""), (cache["items"][0]["type"],
                                             cache["items"][0]["tmdbId"], cache["items"][0]["imdbId"]))
        self.assertEqual(cache["items"], self.call("AvaCandidateCacheItems", cache, scope))


    def test_cache_has_180_item_and_1000_raw_slot_bounds(self):
        values = [self.card(str(i + 1)) for i in range(220)]
        first = self.cache(values, limit=5000)
        self.assertEqual(180, len(first["items"]))
        updated = self.cache([self.card("999")], existing=first)
        self.assertEqual((180, "999", "179"), (len(updated["items"]),
                                             updated["items"][0]["itemId"], updated["items"][-1]["itemId"]))
        self.assertEqual(3, len(self.cache(values, limit=3)["items"]))
        self.assertEqual([], self.cache(values, limit=0)["items"])
        self.assertEqual([], self.cache([None] * 1000 + [self.card()])["items"])
        forged = {**SCOPE, "items": values}
        self.assertEqual(180, len(self.call("AvaCandidateCacheItems", forged, SCOPE)))


    def test_cache_and_submission_whitelist_fields_from_forged_existing_cards(self):
        raw = self.card(token="synthetic-secret", headers={"X-Plex-Token": "synthetic-secret"},
                        url="https://private.example/stream", thumbKey="https://private.example/art",
                        versions=[{"url": "https://private.example/stream"}], title="T" * 200,
                        genres=["Drama"] * 20, rating=20, year=5000)
        cache = self.cache([raw])
        self.assertNotIn("synthetic-secret", json.dumps(cache))
        self.assertNotIn("private.example", json.dumps(cache))
        card = cache["items"][0]
        self.assertEqual((120, 0, ["Drama"]), (len(card["title"]), card["year"], card["genres"]))
        self.assertNotIn("rating", card)
        forged = {**SCOPE, "items": [raw]}
        self.assertEqual(cache["items"], self.call("AvaCandidateCacheItems", forged, SCOPE))
