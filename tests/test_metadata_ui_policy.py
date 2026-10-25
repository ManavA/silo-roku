"""Global discovery cards resolve only through exact active-source identity."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import interpreter_available, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/MetadataUiPolicy.brs"
ADAPTER = ROOT / "source/adapters/MetadataAdapter.brs"
SOURCE = "plex:synthetic-server"


class MetadataUiPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not interpreter_available():
            message = "install runtime tests: npm ci --prefix tools/brightscript --ignore-scripts"
            if os.environ.get("SILO_REQUIRE_BRS") == "1":
                raise RuntimeError(message)
            raise unittest.SkipTest(message)
        cls.package_root = tempfile.TemporaryDirectory(prefix="metadata-ui-policy-")

    @classmethod
    def tearDownClass(cls):
        cls.package_root.cleanup()

    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "Metadata UI policy is not implemented")
        return run_function([ADAPTER, POLICY], name, list(args), root=Path(self.package_root.name))

    def seed(self, **changes):
        return {"provider": "metadata", "catalogId": "metadata:movie:101",
                "title": "Synthetic Moon", "type": "movie", "tmdbId": "101",
                "imdbId": "tt0000101", "year": 2026, **changes}

    def owned(self, source=SOURCE, **changes):
        return {"provider": "plex" if source.startswith("plex:") else "silo",
                "sourceId": source, "itemId": "501", "type": "movie",
                "title": "Synthetic Moon", "year": 2026,
                "guids": ["tmdb://101", "imdb://tt0000101"], **changes}

    def resolve(self, items, provider="plex", source=SOURCE, **page):
        return self.call("UiMetadataResolveOwnedSearch", self.seed(), provider, source,
                         {"items": items, **page})

    def test_rows_become_non_playable_entries_without_provider_identity_or_secrets(self):
        raw = self.seed(itemId="501", sourceId=SOURCE, canPlay=True, owned=True,
                        url="https://private.example/stream", token="fixture-secret",
                        headers={"Authorization": "fixture-secret"},
                        thumbKey="https://image.tmdb.org/t/p/w342/synthetic.jpg")
        entries = self.call("UiMetadataEntries", {"rows": [{"title": "Picks\nToday", "items": [raw]}]}, 100)
        self.assertEqual(1, len(entries))
        item = entries[0]
        self.assertEqual(("metadata", "metadata:movie:101", "Picks Today"),
                         (item["provider"], item["catalogId"], item["rowTitle"]))
        self.assertEqual((False, False, "unresolved"), (item["canPlay"], item["owned"], item["availability"]))
        self.assertEqual(raw["thumbKey"], item["thumbKey"])
        for key in ("sourceId", "itemId", "token", "headers", "url"):
            self.assertNotIn(key, item)
        self.assertNotIn("fixture-secret", json.dumps(entries))

    def test_item_entries_deduplicate_canonical_identity_and_reject_invalid_global_cards(self):
        values = [self.seed(), self.seed(catalogId="fake", title="Alternate label"),
                  self.seed(type="tv", tmdbId="202", imdbId=""),
                  self.seed(provider="plex"), self.seed(type="person"),
                  self.seed(tmdbId="", imdbId=""), None]
        entries = self.call("UiMetadataEntries", {"items": values}, 100)
        self.assertEqual(["metadata:movie:101", "metadata:show:202"], [item["catalogId"] for item in entries])
        self.assertEqual("show", entries[1]["type"])
        self.assertEqual([], self.call("UiMetadataEntries", None, 100))

    def test_entry_and_scan_limits_are_bounded_and_unsafe_artwork_is_dropped(self):
        values = [self.seed(tmdbId=str(i + 1), imdbId="", title="T" * 200,
                            summary="S" * 3000, thumbKey="https://private.example/art?token=fixture-secret")
                  for i in range(140)]
        entries = self.call("UiMetadataEntries", {"items": values}, 500)
        self.assertEqual(100, len(entries))
        self.assertEqual((120, 2000, ""), (len(entries[0]["title"]), len(entries[0]["summary"]), entries[0]["thumbKey"]))
        self.assertEqual(3, len(self.call("UiMetadataEntries", {"items": values}, 3)))
        self.assertEqual([], self.call("UiMetadataEntries", {"items": [None] * 180 + [self.seed()]}, 100))

    def test_provider_search_requests_use_only_title_with_bounded_page_size(self):
        private = self.seed(token="fixture-secret", itemId="global-id", url="private")
        plex = self.call("UiMetadataSearchRequest", private, "plex", SOURCE)
        silo = self.call("UiMetadataSearchRequest", self.seed(type="show"), "silo", "silo:synthetic")
        self.assertEqual((True, "search", {"query": "Synthetic Moon", "limit": 100}),
                         (plex["ok"], plex["action"], plex["params"]))
        self.assertEqual(("catalog_query", {"query": "Synthetic Moon", "limit": 100, "type": "series"}),
                         (silo["action"], silo["params"]))
        self.assertNotIn("fixture-secret", json.dumps(plex))
        self.assertNotIn("itemId", plex["params"])

    def test_search_rejects_invalid_seed_or_mismatched_provider_scope(self):
        for seed, provider, source in ((self.seed(title=""), "plex", SOURCE),
                                       (self.seed(provider="plex"), "plex", SOURCE),
                                       (self.seed(), "silo", SOURCE),
                                       (self.seed(), "plex", ""),
                                       (self.seed(), "unknown", SOURCE)):
            with self.subTest(provider=provider, source=source):
                self.assertFalse(self.call("UiMetadataSearchRequest", seed, provider, source)["ok"])

    def test_plex_exact_owned_resolution_uses_guid_identity_and_keeps_native_id(self):
        result = self.resolve([self.owned(itemId="502", guids=["tmdb://999"]), self.owned(title="Provider title")])
        self.assertEqual((True, "owned", "501", "plex", SOURCE),
                         (result["ok"], result["state"], result["item"]["itemId"],
                          result["item"]["provider"], result["item"]["sourceId"]))
        self.assertTrue(result["item"]["canPlay"])

    def test_title_agreement_wrong_source_conflicts_and_global_ids_do_not_grant_ownership(self):
        for item in (self.owned(guids=[]), self.owned(source="plex:other"),
                     self.owned(guids=["tmdb://101", "imdb://tt999"]),
                     self.owned(itemId="metadata:movie:101"), self.owned(owned=False),
                     self.owned(provider="silo")):
            with self.subTest(item=item):
                result = self.resolve([item])
                self.assertEqual("not_in_search_page", result["state"])
                self.assertNotIn("item", result)

    def test_silo_summary_without_external_ids_requests_detail_hydration_without_title_guessing(self):
        source = "silo:synthetic"
        summary = self.owned(source, itemId="content-501", guids=[])
        result = self.resolve([summary, self.owned(source, itemId="content-502", title="Other title", guids=[])],
                              provider="silo", source=source)
        self.assertEqual("needs_detail_hydration", result["state"])
        self.assertEqual(["content-501", "content-502"], [item["itemId"] for item in result["hydrationCandidates"]])
        self.assertNotIn("item", result)

    def test_silo_hydrated_series_alias_matches_show_seed_by_external_identity(self):
        source = "silo:synthetic"
        item = self.owned(source, itemId="series-501", type="series", guids=[], tmdbId="101", imdbId="tt0000101")
        result = self.call("UiMetadataResolveOwnedSearch", self.seed(type="show"), "silo", source, {"items": [item]})
        self.assertEqual(("owned", "show", False, "silo"),
                         (result["state"], result["item"]["type"], result["item"]["canPlay"], result["item"]["provider"]))

    def test_hydration_candidates_are_bounded_deduplicated_and_exclude_private_fields(self):
        source = "silo:synthetic"
        item = self.owned(source, itemId="content-1", guids=[], token="fixture-secret", url="private")
        values = [item, item] + [self.owned(source, itemId=f"content-{i}", guids=[]) for i in range(2, 30)]
        result = self.resolve(values, provider="silo", source=source)
        self.assertEqual(12, len(result["hydrationCandidates"]))
        self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertNotIn("url", result["hydrationCandidates"][0])

    def test_invalid_search_page_and_seed_fail_explicitly(self):
        for data in (None, {}, {"items": None}, {"items": "invalid"}):
            result = self.call("UiMetadataResolveOwnedSearch", self.seed(), "plex", SOURCE, data)
            self.assertEqual((False, "invalid_response"),
                             (result["ok"], result["state"]))
        result = self.call("UiMetadataResolveOwnedSearch", self.seed(tmdbId="", imdbId=""), "plex", SOURCE, {"items": []})
        self.assertEqual((False, "invalid_seed"), (result["ok"], result["state"]))

    def test_library_candidates_keep_only_current_provider_owned_movie_or_series_cards(self):
        private = self.owned(token="fixture-secret", headers={"X-Plex-Token": "fixture-secret"},
                             thumbKey="https://private.example/art", url="private", genres=["Drama"], rating=8)
        values = [private, private, self.owned(source="plex:other"), self.owned(owned=False),
                  self.owned(type="episode"), self.owned(itemId="bad?token=x"), self.owned(provider="silo")]
        result = self.call("UiMetadataLibraryCandidates", values, SOURCE, 180)
        self.assertEqual(1, len(result))
        self.assertEqual((SOURCE, "501", "101", "tt0000101", ["Drama"], 8),
                         (result[0]["sourceId"], result[0]["itemId"], result[0]["tmdbId"],
                          result[0]["imdbId"], result[0]["genres"], result[0]["rating"]))
        self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertNotIn("url", result[0])
        self.assertNotIn("thumbKey", result[0])

    def test_library_candidates_bound_scans_and_normalize_silo_series(self):
        source = "silo:synthetic"
        values = [self.owned(source, itemId=f"content-{i}", type="series", guids=[]) for i in range(220)]
        result = self.call("UiMetadataLibraryCandidates", values, source, 500)
        self.assertEqual(180, len(result))
        self.assertEqual("show", result[0]["type"])
        self.assertEqual(3, len(self.call("UiMetadataLibraryCandidates", values, source, 3)))
        self.assertEqual([], self.call("UiMetadataLibraryCandidates", [None] * 1000 + [values[0]], source, 180))
        self.assertEqual([], self.call("UiMetadataLibraryCandidates", values, "metadata:global", 180))


if __name__ == "__main__":
    unittest.main()
