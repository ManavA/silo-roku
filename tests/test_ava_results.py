"""Retained AVA adapter and exact-ownership policies; legacy scene routes are retired."""

import json
import unittest
from tests.test_ava_candidate_cache import ROOT, SCRIPTS
from tools.brightscript import run_function

SCOPE = {"sourceId": "plex:fixture", "profileId": "owner"}


class AvaResultTests(unittest.TestCase):
    def card(self, item_id="501", provider="plex", **changes):
        return {"provider": provider, "sourceId": provider + ":fixture", "itemId": item_id,
                "title": "Synthetic Moon", "type": "movie", "owned": True,
                "tmdbId": "101", "imdbId": "tt0000101", **changes}


    def match(self, **changes):
        return {"title": "Synthetic Moon", "mediaType": "movie", "tmdbId": None,
                "imdbId": None, **changes}


    def call(self, function, *args):
        # A missing policy is a feature assertion, not an interpreter error.
        if function.startswith("UiAva"):
            self.assertTrue("function " + function + "(" in (ROOT / "source/core/AvaCandidatePolicy.brs").read_text(), function + " is not implemented")
        return run_function(SCRIPTS, function, list(args))


    def entries(self, matches, cached=None, scope=SCOPE, limit=30):
        decoded = self.call("DecodeMetadataResponse", "ava_recommend", json.dumps({"matches": matches}), {"limit": limit})
        cache = self.call("AvaCandidateCacheAdd", None, cached or [], scope, 180)
        return self.call("UiAvaEntries", decoded["data"], cache, scope, limit), cache


    def resolve(self, match=None, cached=None, scope=SCOPE):
        entries, cache = self.entries([match or self.match()], cached, scope)
        self.assertEqual(1, len(entries))
        return self.call("UiAvaResolveOwned", entries[0], cache, scope)


    def test_response_keeps_nullable_id_title_only_matches_as_unowned_nonplayable_facts(self):
        raw = self.match(itemId="501", sourceId=SCOPE["sourceId"], owned=True,
                         token="fixture-private", url="https://private.example/media", headers={"Authorization": "private"})
        decoded = self.call("DecodeMetadataResponse", "ava_recommend", json.dumps({"matches": [raw, self.match(mediaType="tv"), self.match(mediaType="person"), self.match(mediaType=None)]}), {})
        items = decoded["data"]["items"]
        self.assertEqual(["movie", "show"], [item["type"] for item in items])
        self.assertEqual((False, False, "unresolved"), (items[0]["owned"], items[0]["canPlay"], items[0]["availability"]))
        self.assertNotIn("fixture-private", json.dumps(items))
        for field in ("sourceId", "itemId", "url", "headers"):
            self.assertNotIn(field, items[0])


    def test_title_only_owned_candidate_body_contains_only_library_facts(self):
        card = self.card(tmdbId="", imdbId="", token="fixture-private", url="private", headers={"Authorization": "private"})
        request = self.call("BuildMetadataRequest", "ava_recommend", {"baseUrl": "https://metadata.example.test"}, {"sourceId": SCOPE["sourceId"], "prompt": "Some drama", "libraryCandidates": [card]})
        body = json.loads(request["body"])
        self.assertEqual([{"title": "Synthetic Moon", "mediaType": "movie", "genres": []}], body["libraryCandidates"])
        self.assertNotIn("fixture-private", json.dumps(body))
        self.assertNotIn("itemId", json.dumps(body))


    def test_title_only_response_deduplicates_kind_title_and_bounds_output_and_scan(self):
        values = [self.match(), self.match(title=" synthetic moon "), self.match(mediaType="tv")]
        values += [self.match(title=f"Synthetic {i}") for i in range(100)]
        decoded = self.call("DecodeMetadataResponse", "ava_recommend", json.dumps({"matches": values}), {"limit": 5})
        self.assertEqual(5, len(decoded["data"]["items"]))
        self.assertEqual(["movie", "show"], [item["type"] for item in decoded["data"]["items"][:2]])
        decoded = self.call("DecodeMetadataResponse", "ava_recommend", json.dumps({"matches": [None] * 180 + [self.match()]}), {})
        self.assertEqual([], decoded["data"]["items"])


    def test_discover_and_services_continue_to_drop_title_only_global_items(self):
        decoded = self.call("DecodeMetadataResponse", "service_catalog", json.dumps({"rows": [{"id": "r", "items": [{"title": "Synthetic Moon", "type": "movie"}]}]}), {})
        self.assertEqual([], decoded["data"]["rows"][0]["items"])
        self.assertEqual([], self.call("UiMetadataEntries", {"items": [{"provider": "metadata", "title": "Synthetic Moon", "type": "movie"}]}, 100))


    def test_unique_exact_kind_title_can_resolve_title_only_owned_cache_item(self):
        result = self.resolve(cached=[self.card(tmdbId="", imdbId=""), self.card("502", type="show")])
        self.assertEqual(("owned", "501", SCOPE["sourceId"], "plex"), (result["state"], result["item"]["itemId"], result["item"]["sourceId"], result["item"]["provider"]))
        for match in (self.match(title="synthetic moon"), self.match(title="Synthetic"), self.match(mediaType="show")):
            resolved = self.resolve(match, [self.card()])
            self.assertEqual("owned" if match["title"] == "synthetic moon" else "search_required", resolved["state"])


    def test_ambiguous_native_titles_and_external_ids_require_user_selected_search(self):
        for match in (self.match(), self.match(tmdbId="101", imdbId="tt0000101")):
            result = self.resolve(match, [self.card(), self.card("502")])
            self.assertEqual(("search_required", "ambiguous"), (result["state"], result["reason"]))
            self.assertNotIn("item", result)


    def test_external_ids_resolve_unique_exact_match_without_title_fallback_or_conflicts(self):
        match = self.match(tmdbId="101", imdbId="tt0000101")
        result = self.resolve(match, [self.card(title="Provider title"), self.card("502", tmdbId="999", imdbId="tt0000999")])
        self.assertEqual("501", result["item"]["itemId"])
        for candidate in (self.card(tmdbId="999", imdbId="tt0000999"), self.card(tmdbId="", imdbId=""), self.card(imdbId="tt0000999")):
            self.assertEqual("search_required", self.resolve(match, [candidate])["state"])


    def test_resolution_revalidates_scope_revocation_and_updated_native_facts_at_selection(self):
        entries, cache = self.entries([self.match()], [self.card()])
        for scope in ({**SCOPE, "profileId": "child"}, {**SCOPE, "sourceId": "plex:other"}):
            result = self.call("UiAvaResolveOwned", entries[0], cache, scope)
            self.assertNotEqual("owned", result["state"])
            self.assertNotIn("item", result)
        for updated in (self.card(owned=False), self.card(title="Updated title")):
            changed = self.call("AvaCandidateCacheAdd", cache, [updated], SCOPE, 180)
            self.assertEqual("search_required", self.call("UiAvaResolveOwned", entries[0], changed, SCOPE)["state"])
        self.assertEqual("search_required", self.call("UiAvaResolveOwned", entries[0], None, SCOPE)["state"])


    def test_unresolved_entry_offers_bounded_title_only_source_search(self):
        for provider, kind, action in (("plex", "movie", "search"), ("silo", "tv", "catalog_query")):
            scope = {**SCOPE, "sourceId": provider + ":fixture"}
            entries, _ = self.entries([self.match(mediaType=kind, token="private", url="private")], scope=scope)
            self.assertEqual("Search your source", entries[0]["rowTitle"])
            request = self.call("UiAvaSearchRequest", entries[0], provider, scope)
            self.assertEqual(action, request["action"])
            self.assertEqual("Synthetic Moon", request["params"]["query"])
            self.assertEqual(100, request["params"]["limit"])
            self.assertNotIn("private", json.dumps(request))
            self.assertNotIn("itemId", request["params"])
            if provider == "silo":
                self.assertEqual("series", request["params"]["type"])
