"""Retained pure public-artwork eligibility and scope policies."""

from pathlib import Path
import unittest

from tools.brightscript import run_function


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/BrowseArtworkPolicy.brs"
SCOPE = {"provider": "plex", "sourceId": "plex:fixture", "profileId": "owner",
         "generation": 3, "route": "discover", "listKind": "metadata"}
URL = "https://image.tmdb.org/t/p/w342/synthetic_path.jpg"
SERVICE_SCOPE = {**SCOPE, "route": "service_catalog", "listKind": "items"}


class BrowseArtworkTests(unittest.TestCase):
    def plan(self, item, current="", active=None, rendered=None):
        self.assertTrue(POLICY.is_file(), "Browse artwork policy is missing")
        return run_function(POLICY, "BrowseArtworkPlan",
                            [item, active or SCOPE, rendered or SCOPE, current])

    def card(self, **changes):
        return {"provider": "metadata", "catalogId": "metadata:movie:1", "type": "movie",
                "title": "Fixture film", "thumbKey": URL, **changes}

    def owned_card(self, **changes):
        return {"provider": "plex", "sourceId": SERVICE_SCOPE["sourceId"], "itemId": "101",
                "type": "movie", "owned": True, "thumbKey": URL,
                "artworkProvenance": "metadata_owned_match",
                "artworkProfileId": SERVICE_SCOPE["profileId"], **changes}

    def service_plan(self, item, current="", scope=None, rendered=None):
        active = scope or SERVICE_SCOPE
        return self.plan(item, current, active=active, rendered=rendered or active)

    def test_public_tmdb_poster_is_selected_and_same_uri_is_not_reloaded(self):
        first = self.plan(self.card())
        self.assertEqual(URL, first["uri"])
        self.assertTrue(first["changed"])
        self.assertTrue(first["visible"])
        again = self.plan(self.card(), current=URL)
        self.assertFalse(again["changed"])

    def test_foreign_signed_or_malformed_urls_are_rejected(self):
        bad = ["http://image.tmdb.org/t/p/w342/synthetic_path.jpg",
               "https://image.tmdb.org.evil.test/t/p/w342/synthetic_path.jpg",
               "https://user:secret@image.tmdb.org/t/p/w342/synthetic_path.jpg",
               URL + "?token=secret", URL + "#secret",
               "https://image.tmdb.org/t/p/original/synthetic_path.jpg",
               "https://image.tmdb.org/t/p/w342/../private.jpg"]
        for value in bad:
            with self.subTest(value=value):
                self.assertEqual("", self.plan(self.card(thumbKey=value))["uri"])

    def test_provider_owned_cards_and_action_rows_cannot_load_raw_artwork(self):
        self.assertEqual("", self.plan({"provider": "plex", "itemId": "101",
                                         "type": "movie", "thumbKey": URL})["uri"])
        self.assertEqual("", self.plan(self.card(uiAction="next_page"))["uri"])
        self.assertEqual("", self.plan(self.card(type="person"))["uri"])

    def test_verified_owned_service_poster_is_selected_without_reloading_the_same_uri(self):
        for provider, item_id, kind in (("plex", "101", "movie"), ("silo", "series-101", "show")):
            with self.subTest(provider=provider):
                scope = {**SERVICE_SCOPE, "provider": provider, "sourceId": provider + ":fixture"}
                card = self.owned_card(provider=provider, sourceId=scope["sourceId"], itemId=item_id, type=kind)
                result = self.service_plan(card, scope=scope)
                self.assertEqual(URL, result["uri"])
                self.assertTrue(result["visible"])
                self.assertTrue(result["changed"])
                again = self.service_plan(card, current=URL, scope=scope)
                self.assertFalse(again["changed"])

    def test_raw_or_forged_owned_provider_thumb_key_has_no_service_provenance(self):
        for marker in (None, "", "plex", "metadata", True):
            with self.subTest(marker=marker):
                card = self.owned_card(artworkProvenance=marker)
                self.assertEqual("", self.service_plan(card)["uri"])
        raw = self.owned_card()
        del raw["artworkProvenance"]
        self.assertEqual("", self.service_plan(raw)["uri"])

    def test_service_poster_requires_matching_native_provider_source_and_profile(self):
        for change in ({"provider": "silo"}, {"sourceId": "plex:other"}, {"sourceId": "plex"},
                       {"artworkProfileId": "child"}, {"artworkProfileId": None}, {"owned": False},
                       {"itemId": ""}, {"itemId": "global:101"}, {"itemId": "101?token=secret"}):
            with self.subTest(change=change):
                result = self.service_plan(self.owned_card(**change), current=URL)
                self.assertEqual("", result["uri"])
                self.assertTrue(result["changed"])

    def test_service_poster_requires_current_services_render_scope(self):
        for change in ({"provider": "silo"}, {"sourceId": "plex:other"}, {"profileId": "child"},
                       {"generation": 4}, {"route": "home"}, {"listKind": "services"}):
            with self.subTest(change=change):
                rendered = {**SERVICE_SCOPE, **change}
                self.assertEqual("", self.service_plan(self.owned_card(), current=URL, rendered=rendered)["uri"])
        for change in ({"route": "home"}, {"listKind": "metadata"}, {"provider": "silo"}):
            with self.subTest(active_change=change):
                self.assertEqual("", self.service_plan(self.owned_card(), scope={**SERVICE_SCOPE, **change})["uri"])

    def test_service_poster_rejects_actions_unsupported_types_and_private_urls(self):
        for change in ({"uiAction": "service_search"}, {"type": "episode"}, {"type": "person"},
                       {"type": "series"}, {"thumbKey": "/library/metadata/101/thumb"},
                       {"thumbKey": URL + "?token=secret"}, {"thumbKey": URL + "#secret"},
                       {"thumbKey": "https://image.tmdb.org.evil.test/t/p/w342/synthetic_path.jpg"}):
            with self.subTest(change=change):
                self.assertEqual("", self.service_plan(self.owned_card(**change))["uri"])

    def test_stale_scope_clears_prior_poster(self):
        for change in ({"sourceId": "plex:other"}, {"profileId": "child"},
                       {"generation": 4}, {"route": "home"}):
            with self.subTest(change=change):
                result = self.plan(self.card(), current=URL, rendered={**SCOPE, **change})
                self.assertEqual("", result["uri"])
                self.assertTrue(result["changed"])

    def test_empty_selection_clears_prior_poster(self):
        result = self.plan(None, current=URL)
        self.assertEqual("", result["uri"])
        self.assertFalse(result["visible"])


if __name__ == "__main__":
    unittest.main()
