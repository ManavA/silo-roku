"""Run native episode continuity policy with bounded provider inventories."""

import json
from pathlib import Path
import unittest

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/EpisodeNeighbors.brs"
FIXTURES = ROOT / "tests/fixtures/episode_neighbors"
SCOPE = {"provider": "plex", "sourceId": "plex:fixture", "profileId": "owner",
         "generation": 8, "lookupId": "lookup-1", "anchorItemId": "101",
         "playbackSessionId": "player-1"}


class EpisodeNeighborsTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), "Episode continuity policy is missing")
        return run_function(POLICY, name, list(args))

    def episode(self, item_id="101", number=9, season=1, **changes):
        return {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": item_id,
                "type": "episode", "title": "Synthetic episode", "seriesItemId": "100",
                "parentItemId": "110", "seasonItemId": "110", "seasonNumber": season,
                "episodeNumber": number, "durationMs": 1200000, "resumeMs": 0, **changes}

    def season(self, item_id="110", number=1, **changes):
        return {"provider": "plex", "sourceId": SCOPE["sourceId"], "itemId": item_id,
                "type": "season", "title": "Localized season", "seriesItemId": "100",
                "parentItemId": "100", "seasonNumber": number, **changes}

    def page(self, items, offset=0, has_more=False, **changes):
        return {"ok": True, "data": {"items": items, "offset": offset, "pageSize": 48,
                "rawCount": len(items), "hasMore": has_more,
                "nextOffset": offset + len(items) if has_more else -1, **changes}}

    def detail(self, item, **changes):
        version = {"sourceId": item["sourceId"], "itemId": item["itemId"], "mediaId": "901",
                   "partId": "902", "versionId": item["sourceId"] + ":" + item["itemId"] + ":901:902"}
        return {"ok": True, "data": {"item": item, "versions": [version], **changes}}

    def drive(self, steps, anchor=None, scope=None, wire=False):
        self.assertTrue(POLICY.is_file(), "Episode continuity policy is missing")
        payload = json.dumps({"anchor": anchor or self.episode(), "scope": scope or SCOPE,
                              "steps": steps}, ensure_ascii=True).replace('"', '""')
        body = f'input = ParseJson("{payload}")\nstate = EpisodeNeighborsStart(input.anchor,input.scope)\nrequests = []\n'
        body += 'for each answer in input.steps\nrequest = EpisodeNeighborsRequest(state)\nrequests.Push(request)\n'
        body += 'if request = invalid then exit for\nresponse = answer\n'
        if wire:
            body += 'if input.scope.provider = "plex"\nresponse = DecodePlexResponse(request.action,FormatJson(answer),request.params)\nelse\nresponse = DecodeSiloResponse(request.action,FormatJson(answer),request.params)\nend if\n'
            body += 'response.data = ScopeCatalogData(response.data,input.scope.sourceId)\n'
        body += 'state = EpisodeNeighborsResult(state,request,response)\nend for\n'
        body += 'print FormatJson({outcome:EpisodeNeighborsOutcome(state),state:state,requests:requests,next:EpisodeNeighborsRequest(state)})'
        files = [POLICY]
        if wire:
            files += [ROOT / "source/adapters/PlexAdapter.brs", ROOT / "source/adapters/SiloAdapter.brs",
                      ROOT / "source/core/MediaScope.brs"]
        return json.loads(run_brightscript(files, body))

    def cross_steps(self):
        successor = self.episode("201", 1, 2, parentItemId="210", seasonItemId="210")
        return [self.page([self.episode()]), self.page([self.season(), self.season("210", 2)]),
                self.page([successor]), self.detail(successor)]

    def test_wire_plex_cross_season_candidate_has_scoped_proof(self):
        fixture = json.loads((FIXTURES / "plex_cross_season.json").read_text())
        result = self.drive(fixture, wire=True)
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual("201", result["outcome"]["candidate"]["itemId"])
        proof = result["outcome"]["proof"]
        self.assertEqual(("110", "210"), (proof["currentSeasonItemId"], proof["nextSeasonItemId"]))
        self.assertEqual((1, 2), (proof["currentSeasonNumber"], proof["nextSeasonNumber"]))
        self.assertEqual(["current", "seasons", "adjacent", "candidate_detail"],
                         [request["stage"] for request in result["requests"]])
        self.assertIsNone(result["next"])

    def test_wire_silo_uses_native_season_numbers_and_content_ids(self):
        fixture = json.loads((FIXTURES / "silo_cross_season.json").read_text())
        scope = {**SCOPE, "provider": "silo", "sourceId": "silo:fixture", "anchorItemId": "episode:a"}
        anchor = self.episode("episode:a", provider="silo", sourceId=scope["sourceId"], seriesId="series:a")
        result = self.drive(fixture, anchor, scope, wire=True)
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual("episode:b", result["outcome"]["candidate"]["itemId"])
        self.assertEqual(("season:a", "season:b"),
                         (result["outcome"]["proof"]["currentSeasonItemId"],
                          result["outcome"]["proof"]["nextSeasonItemId"]))
        self.assertEqual("episodes", result["requests"][0]["action"])

    def test_cross_page_adjacency_advances_by_raw_slots_not_episode_numbers(self):
        items = [self.episode(str(500+i), i+1) for i in range(47)] + [self.episode()]
        successor = self.episode("102", 12)
        result = self.drive([self.page(items, has_more=True), self.page([successor], offset=48),
                             self.detail(successor)])
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual(48, result["requests"][1]["params"]["offset"])
        self.assertEqual("102", result["outcome"]["candidate"]["itemId"])

    def test_provider_order_controls_season_transition_even_when_numbers_reverse(self):
        steps = self.cross_steps()
        steps[1] = self.page([self.season("210", 2), self.season(), self.season("310", 0)])
        successor = self.episode("301", 3, 0, parentItemId="310", seasonItemId="310")
        steps[2:] = [self.page([successor]), self.detail(successor)]
        result = self.drive(steps)
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual("301", result["outcome"]["candidate"]["itemId"])

    def test_complete_current_and_last_season_establish_verified_end(self):
        result = self.drive([self.page([self.episode()]), self.page([self.season()])])
        self.assertEqual("verified_end", result["outcome"]["status"])
        self.assertIsNone(result["outcome"]["candidate"])

    def test_missing_exact_anchor_never_requests_an_adjacent_season(self):
        result = self.drive([self.page([self.episode("999")])])
        self.assertEqual("ambiguous", result["outcome"]["status"])
        self.assertIsNone(result["next"])
        self.assertEqual(1, len(result["requests"]))

    def test_failure_is_retryable_and_never_establishes_a_boundary(self):
        result = self.drive([{"ok": False, "errorCode": "network_error", "message": "private body"}])
        self.assertEqual("retryable", result["outcome"]["status"])
        self.assertNotIn("private body", json.dumps(result))

    def test_adjacent_empty_or_failed_inventory_never_skips_to_a_later_season(self):
        for adjacent, status in ((self.page([]), "ambiguous"),
                                 ({"ok": False, "errorCode": "timeout"}, "retryable")):
            result = self.drive(self.cross_steps()[:2] + [adjacent])
            self.assertEqual(status, result["outcome"]["status"])
            self.assertIsNone(result["next"])

    def test_duplicate_or_foreign_current_leaves_are_ambiguous(self):
        for items in ([self.episode(), self.episode()],
                      [self.episode(), self.episode("102", seriesItemId="999")],
                      [self.episode(), self.episode("102", parentItemId="999")],
                      [self.episode(), self.episode("102", sourceId="plex:other")]):
            self.assertEqual("ambiguous", self.drive([self.page(items)])["outcome"]["status"])

    def test_duplicate_native_seasons_never_establish_end(self):
        result = self.drive([self.page([self.episode()]), self.page([self.season(), self.season()])])
        self.assertEqual("ambiguous", result["outcome"]["status"])

    def test_silo_partial_collection_is_unresolved_without_cursor_requests(self):
        scope = {**SCOPE, "provider": "silo", "sourceId": "silo:fixture", "anchorItemId": "episode:a"}
        anchor = self.episode("episode:a", provider="silo", sourceId=scope["sourceId"], seriesId="series:a")
        result = self.drive([{"ok": True, "data": {"items": [anchor], "hasMore": True, "nextCursor": "opaque"}}], anchor, scope)
        self.assertEqual("ambiguous", result["outcome"]["status"])
        self.assertIsNone(result["next"])

    def test_candidate_detail_must_match_native_identity_and_have_versions(self):
        for item, versions in ((self.episode("999", 1, 2), [{"versionId": "901"}]),
                               (self.cross_steps()[2]["data"]["items"][0], []),
                               (self.cross_steps()[2]["data"]["items"][0], [{"versionId": ""}])):
            steps = self.cross_steps()[:3] + [self.detail(item, versions=versions)]
            self.assertEqual("ambiguous", self.drive(steps)["outcome"]["status"])

    def test_candidate_detail_cannot_change_series_season_or_source(self):
        successor = self.cross_steps()[2]["data"]["items"][0]
        for changes in ({"seriesItemId": "999"}, {"parentItemId": "999"},
                        {"seasonNumber": 3}, {"episodeNumber": 2}, {"sourceId": "plex:other"}):
            result = self.drive(self.cross_steps()[:3] + [self.detail({**successor, **changes})])
            self.assertEqual("ambiguous", result["outcome"]["status"])

    def test_foreign_or_malformed_native_version_cannot_establish_availability(self):
        successor = self.cross_steps()[2]["data"]["items"][0]
        version = self.detail(successor)["data"]["versions"][0]
        for change in ({"sourceId": "plex:other"}, {"itemId": "999"}, {"mediaId": ""},
                       {"partId": ""}, {"versionId": "plex:other:201:901:902"}):
            response = self.detail(successor, versions=[{**version, **change}])
            result = self.drive(self.cross_steps()[:3] + [response])
            self.assertEqual("ambiguous", result["outcome"]["status"])

    def test_plex_page_metadata_must_be_complete_and_progress(self):
        for changes in ({"offset": 1}, {"hasMore": True, "nextOffset": 0},
                        {"rawCount": 0}, {"pageSize": 24}, {"hasMore": "false"}):
            result = self.drive([self.page([self.episode()], **changes)])
            self.assertEqual("ambiguous", result["outcome"]["status"])

    def test_missing_native_season_uses_unique_native_number_not_title(self):
        anchor = self.episode(parentItemId="", seasonItemId="")
        result = self.drive([self.page([self.season()]), self.page([anchor]), self.page([self.season()])], anchor)
        self.assertEqual("verified_end", result["outcome"]["status"])
        self.assertEqual("seasons", result["requests"][0]["stage"])
        self.assertEqual("110", result["requests"][1]["params"]["itemId"])

    def test_duplicate_season_numbers_without_exact_parent_are_ambiguous(self):
        anchor = self.episode(parentItemId="", seasonItemId="")
        result = self.drive([self.page([self.season(), self.season("210", 1)])], anchor)
        self.assertEqual("ambiguous", result["outcome"]["status"])
        self.assertEqual(1, len(result["requests"]))

    def test_missing_show_uses_native_season_detail_then_same_season_inventory(self):
        anchor = self.episode(seriesItemId="")
        successor = self.episode("102", 10)
        result = self.drive([self.detail(self.season()), self.page([self.episode(), successor]),
                             self.detail(successor)], anchor)
        self.assertEqual("season_detail", result["requests"][0]["stage"])
        self.assertEqual("known", result["outcome"]["status"])

    def test_wrong_scope_or_non_episode_start_has_no_requests(self):
        for changes in ({"sourceId": "plex:other"}, {"provider": "silo"},
                        {"type": "movie"}, {"extraType": "trailer"}, {"itemId": "bad/url"}):
            result = self.drive([], {**self.episode(), **changes})
            self.assertEqual("ambiguous", result["outcome"]["status"])
            self.assertIsNone(result["next"])
        for changes in ({"generation": -1}, {"lookupId": ""}, {"anchorItemId": "999"}):
            result = self.drive([], scope={**SCOPE, **changes})
            self.assertEqual("ambiguous", result["outcome"]["status"])

    def test_replayed_or_changed_request_cannot_advance_state(self):
        state = self.call("EpisodeNeighborsStart", self.episode(), SCOPE)
        request = self.call("EpisodeNeighborsRequest", state)
        changed = {**request, "sequence": request["sequence"] + 1}
        self.assertEqual(state, self.call("EpisodeNeighborsResult", state, changed, self.page([self.episode()])))
        advanced = self.call("EpisodeNeighborsResult", state, request, self.page([self.episode()]))
        self.assertEqual(advanced, self.call("EpisodeNeighborsResult", advanced, request, self.page([self.episode()])))

    def test_current_inventory_and_season_paging_caps_do_not_claim_end(self):
        current_pages = [self.page([self.episode(str(500+page*48+i), i+1) for i in range(48)],
                                   offset=page*48, has_more=True) for page in range(4)]
        result = self.drive(current_pages)
        self.assertEqual("ambiguous", result["outcome"]["status"])
        self.assertIsNone(result["next"])
        self.assertLessEqual(len(result["state"]["currentItems"]), 192)
        season_pages = [self.page([self.season(str(1000+page*48+i), i) for i in range(48)],
                                  offset=page*48, has_more=True) for page in range(2)]
        result = self.drive([self.page([self.episode()])] + season_pages)
        self.assertEqual("ambiguous", result["outcome"]["status"])
        self.assertIsNone(result["next"])
        self.assertLessEqual(len(result["state"]["seasons"]), 96)

    def test_oversized_silo_unpaged_collection_does_not_get_truncated(self):
        scope = {**SCOPE, "provider": "silo", "sourceId": "silo:fixture", "anchorItemId": "episode:a"}
        anchor = self.episode("episode:a", provider="silo", sourceId=scope["sourceId"], seriesId="series:a")
        items = [{**anchor, "itemId": "episode:"+str(i)} for i in range(193)]
        result = self.drive([{"ok": True, "data": {"items": items, "hasMore": False}}], anchor, scope)
        self.assertEqual("ambiguous", result["outcome"]["status"])

    def test_state_and_outcome_keep_compact_identity_without_urls_or_credentials(self):
        steps = self.cross_steps()
        steps[-1]["data"]["item"].update({"headers": {"X-Secret": "do-not-retain"},
            "thumbKey": "https://art.example.test/private", "url": "https://stream.example.test/private"})
        steps[-1]["data"]["versions"][0]["partKey"] = "/library/parts/901/file"
        result = self.drive(steps)
        serialized = json.dumps({"outcome": result["outcome"], "state": result["state"]})
        for forbidden in ("do-not-retain", "https://", "headers", "partKey", "versions"):
            self.assertNotIn(forbidden, serialized)

    def test_proof_validation_binds_every_native_identity_and_scope_field(self):
        result = self.drive(self.cross_steps())["outcome"]
        proof, successor = result["proof"], result["candidate"]
        self.assertTrue(self.call("EpisodeNeighborsProofMatches", proof, self.episode(), successor, SCOPE))
        for field, value in (("sourceId", "plex:other"), ("profileId", "other"), ("generation", 7),
                             ("provider", "silo"), ("status", "ambiguous"), ("lookupId", ""),
                             ("currentItemId", "999"), ("nextItemId", "999"), ("seriesId", "999"),
                             ("currentSeasonNumber", 3), ("nextSeasonNumber", 3),
                             ("currentSeasonItemId", "999"), ("nextSeasonItemId", "999")):
            with self.subTest(field=field):
                self.assertFalse(self.call("EpisodeNeighborsProofMatches", {**proof, field: value}, self.episode(), successor, SCOPE))

    def test_scope_and_proof_reject_untyped_or_url_shaped_context(self):
        result = self.drive(self.cross_steps())["outcome"]
        proof, successor = result["proof"], result["candidate"]
        self.assertFalse(self.call("EpisodeNeighborsProofMatches", {**proof, "profileId": 7},
                                  self.episode(), successor, {**SCOPE, "profileId": 7}))
        plain_scope = {key: value for key, value in SCOPE.items() if key != "lookupId"}
        self.assertFalse(self.call("EpisodeNeighborsProofMatches", {**proof, "lookupId": "https://private"},
                                  self.episode(), successor, plain_scope))
        for field, value in (("anchorItemId", None), ("playbackSessionId", "https://private")):
            started = self.call("EpisodeNeighborsStart", self.episode(), {**SCOPE, field: value})
            self.assertEqual("ambiguous", started["status"])
            self.assertNotIn("https://", json.dumps(started))

    def test_an_adjacent_season_cannot_reuse_a_native_id_from_current_inventory(self):
        duplicate = self.episode("100", 1, 2, parentItemId="210", seasonItemId="210")
        steps = self.cross_steps()[:2]
        steps[0] = self.page([self.episode("100", 8), self.episode()])
        result = self.drive(steps + [self.page([duplicate])])
        self.assertEqual("ambiguous", result["outcome"]["status"])
        self.assertIsNone(result["next"])


if __name__ == "__main__":
    unittest.main()
