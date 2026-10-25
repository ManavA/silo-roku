"""Services show exact owned identities from a bounded source/profile cache."""

import json
from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/ServicePolicy.brs"
SCRIPTS = [ROOT / "source/adapters/MetadataAdapter.brs",
           ROOT / "source/core/MetadataUiPolicy.brs", POLICY]
SCOPE = {"sourceId": "plex:synthetic-server", "profileId": "profile-1"}


class ServicePolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "Services ownership policy is missing")
        return run_function(SCRIPTS, name, list(args))

    def owned(self, item_id="501", **changes):
        return {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": item_id,
                "type": "movie", "title": "Synthetic Moon", "year": 2026,
                "guids": ["tmdb://101", "imdb://tt0000101"], **changes}

    def seed(self, **changes):
        return {"provider": "metadata", "title": "Synthetic Moon", "type": "movie",
                "tmdbId": "101", "imdbId": "tt0000101", **changes}

    def index(self, items, scope=SCOPE, existing=None, limit=500):
        return self.call("ServiceOwnedIndexAdd", existing, items, scope, limit)

    def entries(self, seeds, index, scope=SCOPE, limit=100):
        return self.call("ServiceOwnedEntries", {"items": seeds}, index, scope, limit)

    def test_owned_index_keeps_normalized_ids_and_drops_private_transport_fields(self):
        index = self.index([self.owned(token="synthetic-secret", headers={"Authorization": "synthetic-secret"},
                                       versions=[{"url": "https://private.test/stream"}],
                                       thumbKey="https://private.test/art")])
        self.assertEqual(SCOPE["sourceId"], index["sourceId"])
        self.assertEqual(SCOPE["profileId"], index["profileId"])
        card = index["items"][0]
        self.assertEqual(("501", "101", "tt0000101"),
                         (card["itemId"], card["tmdbId"], card["imdbId"]))
        self.assertNotIn("synthetic-secret", json.dumps(index))
        self.assertNotIn("private.test", json.dumps(index))

    def test_index_keeps_newest_native_identity_and_retires_lost_ownership_evidence(self):
        initial = self.index([self.owned(), self.owned("502", guids=["tmdb://102"])])
        updated = self.index([self.owned(title="Updated Moon")], existing=initial)
        self.assertEqual(["501", "502"], [item["itemId"] for item in updated["items"]])
        self.assertEqual("Updated Moon", updated["items"][0]["title"])
        for incoming in (self.owned(guids=[]), self.owned(owned=False)):
            retired = self.index([incoming], existing=updated)
            self.assertEqual(["502"], [item["itemId"] for item in retired["items"]])

    def test_index_rejects_global_wrong_source_kind_and_unsafe_ids(self):
        values = [self.owned(provider="metadata"), self.owned(sourceId="plex:other"),
                  self.owned("global:501"), self.owned(type="episode"), self.owned(owned=False),
                  self.owned(guids=[]), self.owned("bad?token=synthetic-secret")]
        self.assertEqual([], self.index(values)["items"])

    def test_index_scope_includes_profile_and_source(self):
        initial = self.index([self.owned()])
        for changed in ({**SCOPE, "profileId": "profile-2"},
                        {**SCOPE, "sourceId": "plex:other"}):
            self.assertEqual([], self.index([], changed, initial)["items"])
            result = self.entries([self.seed()], initial, changed)
            self.assertEqual([], result["items"])
            self.assertFalse(result["ownershipComplete"])
        for scope in (None, {}, {"sourceId": "metadata:global", "profileId": ""},
                      {"sourceId": SCOPE["sourceId"], "profileId": 5}):
            self.assertEqual([], self.index([self.owned()], scope)["items"])

    def test_index_has_item_and_scan_bounds(self):
        values = [self.owned(str(i + 1), guids=[f"tmdb://{i + 1}"]) for i in range(550)]
        self.assertEqual(500, len(self.index(values, limit=5000)["items"]))
        self.assertEqual(3, len(self.index(values, limit=3)["items"]))
        self.assertEqual([], self.index(values, limit=0)["items"])
        self.assertEqual([], self.index([None] * 1000 + [self.owned()])["items"])

    def test_service_entries_are_exact_owned_native_cards_in_catalog_order(self):
        index = self.index([self.owned("502", guids=["tmdb://102"]), self.owned()])
        seeds = [self.seed(owned=True, itemId="fake", sourceId="plex:other"),
                 self.seed(tmdbId="999", imdbId="", title="Not owned"),
                 self.seed(tmdbId="102", imdbId="", title="Second catalog title")]
        result = self.entries(seeds, index)
        self.assertTrue(result["ok"])
        self.assertFalse(result["ownershipComplete"])
        self.assertEqual(["501", "502"], [item["itemId"] for item in result["items"]])
        self.assertTrue(all(item["owned"] and item["canPlay"] for item in result["items"]))
        self.assertTrue(all(item["sourceId"] == SCOPE["sourceId"] and item["provider"] == "plex"
                            for item in result["items"]))

    def test_title_only_match_wrong_kind_and_conflicting_namespace_cannot_show_as_owned(self):
        for card in (self.owned(guids=["tmdb://999"]), self.owned(type="show"),
                     self.owned(guids=["tmdb://101", "imdb://tt999"])):
            self.assertEqual([], self.entries([self.seed()], self.index([card]))["items"])
        self.assertEqual([], self.entries([self.seed(tmdbId="", imdbId="")],
                                         self.index([self.owned()]))["items"])

    def test_service_entries_preserve_row_label_and_only_public_catalog_artwork(self):
        private = self.seed(thumbKey="https://private.test/art?token=synthetic-secret",
                            token="synthetic-secret", headers={"Authorization": "synthetic-secret"})
        data = {"rows": [{"title": "Picks\nToday", "items": [private]}]}
        result = self.call("ServiceOwnedEntries", data, self.index([self.owned()]), SCOPE, 100)
        self.assertEqual("Picks Today", result["items"][0]["rowTitle"])
        self.assertNotIn("synthetic-secret", json.dumps(result))
        self.assertNotIn("private.test", json.dumps(result))

    def test_exact_service_match_marks_validated_public_poster_in_its_profile(self):
        url = "https://image.tmdb.org/t/p/w342/synthetic_path.jpg"
        item = self.entries([self.seed(thumbKey=url)], self.index([self.owned()]))["items"][0]
        self.assertEqual(url, item["thumbKey"])
        self.assertEqual("metadata_owned_match", item.get("artworkProvenance"))
        self.assertEqual(SCOPE["profileId"], item.get("artworkProfileId"))
        self.assertEqual("501", item["itemId"])
        self.assertEqual(SCOPE["sourceId"], item["sourceId"])

    def test_service_artwork_provenance_cannot_be_imported_from_owned_cards_or_catalog(self):
        url = "https://image.tmdb.org/t/p/w342/synthetic_path.jpg"
        forged = {"artworkProvenance": "metadata_owned_match", "artworkProfileId": SCOPE["profileId"]}
        index = self.index([self.owned(thumbKey=url, **forged)])
        self.assertNotIn("artworkProvenance", index["items"][0])
        self.assertNotIn("artworkProfileId", index["items"][0])
        for thumb in ("", "https://private.test/art?token=synthetic-secret", url + "?sig=synthetic-secret"):
            with self.subTest(thumb=thumb):
                item = self.entries([self.seed(thumbKey=thumb, **forged)], index)["items"][0]
                self.assertEqual("", item["thumbKey"])
                self.assertNotIn("artworkProvenance", item)
                self.assertNotIn("artworkProfileId", item)

    def test_silo_exact_owned_service_poster_reaches_the_native_browse_policy(self):
        scope = {"sourceId": "silo:synthetic-server", "profileId": "profile-1"}
        url = "https://image.tmdb.org/t/p/w342/synthetic_path.jpg"
        raw = self.owned("series-501", provider="silo", sourceId=scope["sourceId"], type="series",
                         guids=[], tmdbId="101", imdbId="tt0000101")
        item = self.entries([self.seed(type="show", thumbKey=url)], self.index([raw], scope), scope)["items"][0]
        browse_scope = {**scope, "provider": "silo", "generation": 3,
                        "route": "service_catalog", "listKind": "items"}
        plan = run_function(ROOT / "source/core/BrowseArtworkPolicy.brs", "BrowseArtworkPlan",
                            [item, browse_scope, browse_scope, ""])
        self.assertEqual(url, plan["uri"])
        self.assertTrue(plan["visible"])
        self.assertEqual("series-501", item["itemId"])

    def test_silo_detail_identity_matches_show_without_borrowing_catalog_native_id(self):
        scope = {"sourceId": "silo:synthetic-server", "profileId": "profile-1"}
        raw = self.owned("series-501", provider="silo", sourceId=scope["sourceId"], type="series",
                         guids=[], tmdbId="101", imdbId="tt0000101")
        result = self.entries([self.seed(type="show")], self.index([raw], scope), scope)
        self.assertEqual(1, len(result["items"]))
        item = result["items"][0]
        self.assertEqual(("silo", "series-501", "show", False),
                         (item["provider"], item["itemId"], item["type"], item["canPlay"]))

    def test_silo_owned_ids_use_the_existing_native_id_grammar(self):
        scope = {"sourceId": "silo:synthetic-server", "profileId": "profile-1"}
        for item_id in ("content.501:edition-1", "a" * 256):
            raw = self.owned(item_id, provider="silo", sourceId=scope["sourceId"],
                             guids=[], tmdbId="101", imdbId="tt0000101")
            index = self.index([raw], scope)
            self.assertEqual([item_id], [item["itemId"] for item in index["items"]])
            result = self.entries([self.seed()], index, scope)
            self.assertEqual(item_id, result["items"][0]["itemId"])

    def test_service_entries_deduplicate_native_ids_and_cap_rendered_catalog(self):
        index = self.index([self.owned()])
        seeds = [self.seed(), self.seed(tmdbId="", imdbId="tt0000101")]
        self.assertEqual(1, len(self.entries(seeds, index)["items"]))
        values = [self.owned(str(i + 1), guids=[f"tmdb://{i + 1}"]) for i in range(120)]
        seeds = [self.seed(tmdbId=str(i + 1), imdbId="") for i in range(120)]
        self.assertEqual(100, len(self.entries(seeds, self.index(values), limit=500)["items"]))
        self.assertEqual(3, len(self.entries(seeds, self.index(values), limit=3)["items"]))

    def test_catalog_failure_and_empty_intersection_keep_a_focusable_source_search(self):
        decoded = self.call("DecodeMetadataResponse", "service_catalog", " " * 2097153, {})
        self.assertEqual("response_too_large", decoded["errorCode"])
        failed = self.call("ServiceViewEntries", decoded.get("data"), None, SCOPE, 100)
        self.assertEqual([], failed["items"][:-1])
        action = failed["items"][-1]
        self.assertEqual(("Search your source", "service_search"),
                         (action["title"], action["uiAction"]))
        self.assertNotIn("itemId", action)
        self.assertFalse(failed["ownershipComplete"])
        result = self.call("ServiceViewEntries", {"items": [self.seed()]},
                           self.index([self.owned()]), SCOPE, 100)
        self.assertEqual(["501", "service_search"],
                         [entry.get("itemId", entry.get("uiAction")) for entry in result["items"]])


if __name__ == "__main__":
    unittest.main()
