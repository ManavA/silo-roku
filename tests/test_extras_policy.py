"""Extras use native source identity and their own timeline before route planning."""

from copy import deepcopy
from pathlib import Path
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/ExtrasPolicy.brs"
PLEX = ROOT / "source/adapters/PlexAdapter.brs"
SILO = ROOT / "source/adapters/SiloAdapter.brs"
MEDIA_SCOPE = ROOT / "source/core/MediaScope.brs"


class ExtrasPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "extras policy is not implemented")
        return run_function(POLICY, name, list(args))

    def scope(self, source="plex:server-a", **changes):
        return {"sourceId": source, "profileId": "owner", "generation": 7, **changes}

    def native_extra(self, item_id="501", kind="trailer", source="plex:server-a", **changes):
        return {"sourceId": source, "provider": "plex", "itemId": item_id,
                "title": "Synthetic Extra", "type": "movie", "extraType": kind,
                "durationMs": 90000, "resumeMs": 50000, **changes}

    def detail(self, extras=None, source="plex:server-a"):
        return {"item": {"sourceId": source, "itemId": "parent", "type": "movie", "resumeMs": 3600000},
                "extras": [self.native_extra(source=source)] if extras is None else extras}

    def playlist(self, extras=None, source="plex:server-a"):
        scope = self.scope(source)
        return self.call("BuildExtrasPlaylist", self.detail(extras, source), scope, scope)

    def plex_version(self, version_id="video-version", **changes):
        return {"sourceId": "plex:server-a", "itemId": "501", "versionId": version_id,
                "videoCodec": "h264", "mediaIndex": 2, "partIndex": 1,
                "partKey": "/library/parts/3501/file.mp4", **changes}

    def extra_detail(self, versions=None, **item_changes):
        return {"item": self.native_extra(**item_changes),
                "versions": [self.plex_version()] if versions is None else versions}

    def test_plex_decoder_extras_form_native_playlist_and_preserve_server_order(self):
        decoded = run_function(PLEX, "DecodePlexResponse", ["detail", (ROOT / "tests/fixtures/plex/detail_extras.json").read_text(), {"sourceId": "plex:server-a"}])
        playlist = self.call("BuildExtrasPlaylist", decoded["data"], self.scope(), self.scope())
        self.assertTrue(playlist["ok"])
        self.assertEqual("available", playlist["state"])
        self.assertEqual(["501", "502"], [item["itemId"] for item in playlist["items"]])
        self.assertEqual(["trailer", "featurette"], [item["extraType"] for item in playlist["items"]])
        self.assertEqual(self.scope(), playlist["scope"])

    def test_empty_extras_are_distinct_from_unavailable_provider_data(self):
        empty = self.playlist([])
        self.assertTrue(empty["ok"])
        self.assertEqual(("empty", []), (empty["state"], empty["items"]))
        missing = self.detail()
        del missing["extras"]
        result = self.call("BuildExtrasPlaylist", missing, self.scope(), self.scope())
        self.assertEqual((False, "unsupported", "extras_not_normalized"),
                         (result["ok"], result["state"], result["errorCode"]))

    def test_current_silo_detail_explicitly_reports_missing_extras_capability(self):
        decoded = run_function(SILO, "DecodeSiloResponse", ["detail", (ROOT / "tests/fixtures/silo/catalog_item_detail_markers_credits.json").read_text(), {}])
        # Bind the fixture through the same source normalization as the worker.
        scoped = run_function(MEDIA_SCOPE, "ScopeCatalogData", [decoded["data"], "silo:server-a"])
        scope = self.scope("silo:server-a")
        result = self.call("BuildExtrasPlaylist", scoped, scope, scope)
        self.assertEqual((False, "unsupported", "extras_not_normalized", []),
                         (result["ok"], result["state"], result["errorCode"], result["items"]))

    def test_source_profile_and_generation_changes_invalidate_playlist_creation(self):
        for change in ({"sourceId": "plex:server-b"}, {"profileId": "child"}, {"generation": 8}):
            with self.subTest(change=change):
                result = self.call("BuildExtrasPlaylist", self.detail(), self.scope(), self.scope(**change))
                self.assertEqual((False, "stale", "scope_changed", []),
                                 (result["ok"], result["state"], result["errorCode"], result["items"]))
        for invalid in ({}, {"sourceId": "plex:server-a", "profileId": "owner"}, None):
            with self.subTest(invalid=invalid):
                self.assertFalse(self.call("BuildExtrasPlaylist", self.detail(), invalid, invalid)["ok"])

    def test_parent_from_other_source_is_rejected(self):
        result = self.call("BuildExtrasPlaylist", self.detail(source="plex:server-b"), self.scope(), self.scope())
        self.assertEqual("source_mismatch", result["errorCode"])
        self.assertEqual([], result["items"])

    def test_native_items_are_filtered_by_source_type_and_safe_identifier(self):
        extras = [
            self.native_extra(source="plex:server-b"),
            self.native_extra(item_id="501?X-Plex-Token=synthetic"),
            self.native_extra(item_id="../501"),
            self.native_extra(item_id="502", type="show"),
            self.native_extra(item_id="503", extraType=""),
            self.native_extra(item_id="504", provider="silo"),
            self.native_extra(item_id="505"),
        ]
        result = self.playlist(extras)
        self.assertEqual(["505"], [item["itemId"] for item in result["items"]])

    def test_external_metadata_and_plex_watchlist_ids_are_not_native_playback_items(self):
        extras = [{"site": "YouTube", "key": "syntheticKey", "type": "trailer", "title": "Metadata Trailer"},
                  {"sourceId": "plex-watchlist:account", "itemId": "global-id", "type": "movie", "extraType": "trailer"}]
        result = self.playlist(extras)
        self.assertEqual((False, "unsupported", "no_native_extras", []),
                         (result["ok"], result["state"], result["errorCode"], result["items"]))
        scope = self.scope("plex-watchlist:account")
        global_detail = self.detail([], source="plex-watchlist:account")
        self.assertEqual("unsupported_source", self.call("BuildExtrasPlaylist", global_detail, scope, scope)["errorCode"])

    def test_external_metadata_cannot_borrow_native_item_fields(self):
        disguised = self.native_extra(site="YouTube", key="syntheticKey")
        result = self.playlist([disguised])
        self.assertFalse(result["ok"])
        self.assertEqual((False, "no_native_extras", []), (result["ok"], result["errorCode"], result["items"]))

    def test_parent_title_cannot_be_reused_as_its_own_extra(self):
        result = self.playlist([self.native_extra("parent")])
        self.assertFalse(result["ok"])
        self.assertEqual((False, "no_native_extras", []), (result["ok"], result["errorCode"], result["items"]))

    def test_playlist_is_bounded_deduplicated_and_excludes_credentials_and_urls(self):
        duplicate = self.native_extra("1", url="https://synthetic.example/extra?token=synthetic", token="synthetic", headers={"X-Plex-Token": "synthetic"})
        extras = [duplicate, deepcopy(duplicate)] + [self.native_extra(str(i)) for i in range(2, 60)]
        result = self.playlist(extras)
        self.assertEqual(24, len(result["items"]))
        self.assertEqual([str(i) for i in range(1, 25)], [item["itemId"] for item in result["items"]])
        self.assertEqual(0, result["items"][0]["resumeMs"])
        for key in ("token", "headers", "url"):
            self.assertNotIn(key, result["items"][0])
        self.assertEqual(50000, extras[0]["resumeMs"])

    def test_playlist_and_version_scans_stop_at_declared_bounds(self):
        extras = [None] * 128 + [self.native_extra()]
        self.assertEqual("no_native_extras", self.playlist(extras)["errorCode"])
        versions = [self.plex_version(videoCodec="")] * 20 + [self.plex_version()]
        result = self.call("ResolveExtraPlayback", self.playlist(), 0, self.extra_detail(versions), self.scope())
        self.assertEqual("native_video_required", result["errorCode"])

    def test_item_selection_requests_own_detail_and_refuses_out_of_bounds_index(self):
        playlist = self.playlist()
        selected = self.call("ExtrasPlaylistItem", playlist, 0, self.scope())
        self.assertTrue(selected["ok"])
        self.assertEqual({"itemId": "501"}, selected["params"])
        self.assertEqual("detail", selected["action"])
        for index in (-1, 1, 24, 0.5, "0", None):
            with self.subTest(index=index):
                result = self.call("ExtrasPlaylistItem", playlist, index, self.scope())
                self.assertEqual((False, "index_out_of_range"), (result["ok"], result["errorCode"]))

    def test_playlist_selection_and_advance_refuse_stale_profile_and_source(self):
        playlist = self.playlist([self.native_extra("501"), self.native_extra("502")])
        for change in ({"sourceId": "plex:server-b"}, {"profileId": "child"}, {"generation": 8}):
            with self.subTest(change=change):
                for function in ("ExtrasPlaylistItem", "AdvanceExtrasPlaylist"):
                    result = self.call(function, playlist, 0, self.scope(**change))
                    self.assertEqual("scope_changed", result["errorCode"])

    def test_playlist_advances_once_and_finishes_without_wrapping(self):
        playlist = self.playlist([self.native_extra("501"), self.native_extra("502")])
        next_item = self.call("AdvanceExtrasPlaylist", playlist, 0, self.scope())
        self.assertEqual((True, "502", 1), (next_item["ok"], next_item["item"]["itemId"], next_item["index"]))
        finished = self.call("AdvanceExtrasPlaylist", playlist, 1, self.scope())
        self.assertEqual((False, "complete", "playlist_complete"),
                         (finished["ok"], finished["state"], finished["errorCode"]))
        self.assertEqual("index_out_of_range", self.call("AdvanceExtrasPlaylist", playlist, -1, self.scope())["errorCode"])

    def test_fixture_clip_resolves_to_own_native_video_route_at_zero(self):
        decoded = run_function(PLEX, "DecodePlexResponse", ["detail", (ROOT / "tests/fixtures/plex/clip_detail.json").read_text(), {"sourceId": "plex:server-a"}])
        result = self.call("ResolveExtraPlayback", self.playlist(), 0, decoded["data"], self.scope())
        self.assertTrue(result["ok"])
        self.assertEqual(("501", "501", 0), (result["metadataItemId"], result["playbackItemId"], result["params"]["startPositionMs"]))
        self.assertEqual(0, result["params"]["versionIndex"])
        self.assertEqual("501", result["params"]["detail"]["item"]["itemId"])
        self.assertEqual("plex:server-a:501:2501:3501", result["versionId"])

    def test_resolution_selects_video_version_instead_of_audio_only_entry(self):
        versions = [self.plex_version("audio", videoCodec="", audioCodec="aac"), self.plex_version("video")]
        result = self.call("ResolveExtraPlayback", self.playlist(), 0, self.extra_detail(versions), self.scope())
        self.assertEqual((True, "video", 1, 1),
                         (result["ok"], result["versionId"], result["params"]["versionIndex"], result["params"]["partIndex"]))

    def test_plex_external_cinema_paths_and_unsafe_parts_are_not_resolved(self):
        for path in ("", "https://cdn.synthetic.example/trailer.mp4", "/library/metadata/501", "/library/parts/3501/file.mp4?X-Plex-Token=synthetic", "/library/parts/../file.mp4"):
            with self.subTest(path=path):
                result = self.call("ResolveExtraPlayback", self.playlist(), 0, self.extra_detail([self.plex_version(partKey=path)]), self.scope())
                self.assertEqual((False, "unsupported", "native_video_required"),
                                 (result["ok"], result["state"], result["errorCode"]))

    def test_detail_resolution_refuses_wrong_item_source_profile_and_version_identity(self):
        playlist = self.playlist()
        for detail, scope, expected in (
            (self.extra_detail(itemId="parent"), self.scope(), "item_mismatch"),
            (self.extra_detail(sourceId="plex:server-b"), self.scope(), "source_mismatch"),
            (self.extra_detail(), self.scope(profileId="child"), "scope_changed"),
            (self.extra_detail([self.plex_version(sourceId="plex:server-b")]), self.scope(), "native_video_required"),
            (self.extra_detail([self.plex_version(itemId="parent")]), self.scope(), "native_video_required"),
            (self.extra_detail([self.plex_version(mediaIndex=-1)]), self.scope(), "native_video_required"),
        ):
            with self.subTest(expected=expected, detail=detail):
                result = self.call("ResolveExtraPlayback", playlist, 0, detail, scope)
                self.assertEqual((False, expected), (result["ok"], result["errorCode"]))

    def test_resolving_normalized_silo_extra_keeps_metadata_and_playback_ids_separate(self):
        # Future adapter data can reuse the policy once native extras are normalized;
        # this synthetic shape does not claim current Silo transport support.
        source = "silo:server-a"
        scope = self.scope(source)
        extra = self.native_extra("extra-c1", source=source, provider="silo")
        playlist = self.call("BuildExtrasPlaylist", self.detail([extra], source), scope, scope)
        own_detail = {"item": {**extra, "playItemId": "extra-play-c1", "resumeMs": 20000},
                      "versions": [{"sourceId": source, "versionId": "extra-file-1", "videoCodec": "h264"}]}
        selected = self.call("ExtrasPlaylistItem", playlist, 0, scope)
        self.assertEqual({"itemId": "extra-c1"}, selected["params"])
        result = self.call("ResolveExtraPlayback", playlist, 0, own_detail, scope)
        self.assertEqual(("extra-c1", "extra-play-c1"), (result["metadataItemId"], result["playbackItemId"]))
        self.assertEqual({"itemId": "extra-play-c1", "fileId": "extra-file-1", "startPositionMs": 0}, result["params"])
        self.assertEqual(20000, own_detail["item"]["resumeMs"])

    def test_invalid_detail_and_missing_video_version_return_explicit_unsupported_states(self):
        playlist = self.playlist()
        for detail in (None, {}, {"item": self.native_extra(), "versions": []}, self.extra_detail([self.plex_version(videoCodec="")])):
            with self.subTest(detail=detail):
                result = self.call("ResolveExtraPlayback", playlist, 0, detail, self.scope())
                self.assertFalse(result["ok"])
                self.assertEqual("unsupported", result["state"])


if __name__ == "__main__":
    unittest.main()
