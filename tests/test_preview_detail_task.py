"""Preview target resolution runs scoped worker dispatch and real provider decoders."""

import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "source/core/ServerUrlPolicy.brs", ROOT / "source/core/MediaScope.brs",
         ROOT / "source/auth/SessionPolicy.brs", ROOT / "source/adapters/PlexAdapter.brs",
         ROOT / "source/adapters/SiloAdapter.brs"]
BOUNDARIES = '''
function LoadSession(provider as String) as Object
    return m.fixtureSession
end function
function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function
function SaveSession(provider as String, session as Object, revision as Integer) as Boolean
    if revision <> m.fixtureRevision then return false
    m.fixtureSession = session
    return true
end function
function TaskDeviceSession(provider as String, session as Object) as Object
    return session
end function
function TaskNowMs() as Double
    return m.elapsedMs
end function
function TaskPreviewElapsedMs(context as Object) as Integer
    return m.elapsedMs
end function
function HttpRequest(request as Object, timeoutMs = 9000 as Integer) as Object
    m.requests.Push(request)
    m.timeouts.Push(timeoutMs)
    m.elapsedMs = m.elapsedMs + m.elapsedStep
    if m.changeRevision then m.fixtureRevision = m.fixtureRevision + 1
    if m.changedSession <> invalid then m.fixtureSession = m.changedSession
    if m.responses.Count() = 0 then return {ok:false,errorCode:"network_timeout"}
    return m.responses.Shift()
end function
function RunPreviewDetail(job as Object, session as Object, responses as Object, changedSession as Dynamic, changeRevision as Boolean, elapsedStep as Integer) as Object
    m.fixtureSession = session
    m.fixtureRevision = 0
    m.responses = responses
    m.requests = []
    m.timeouts = []
    m.changedSession = changedSession
    m.changeRevision = changeRevision
    m.elapsedMs = 0
    m.elapsedStep = elapsedStep
    m.top = {job:job,result:invalid}
    runJob()
    return {outcome:m.top.result,requests:m.requests,timeouts:m.timeouts}
end function
'''


class PreviewDetailTaskTests(unittest.TestCase):
    def test_playback_resolver_keeps_valid_empty_episode_for_one_ui_refresh(self):
        show=self.silo_item('1','series',playable=False);show['play_content_id']='100'
        result=self.run_job('silo',job=self.job('silo','series',action='playback_detail'),
                            responses=[self.response(show),self.response(self.silo_item(playable=False))])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual('100',result['outcome']['data']['item']['itemId'])
        self.assertEqual('1',result['outcome']['data']['candidateItemId'])
        self.assertEqual([],result['outcome']['data']['versions'])
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])

    def session(self, provider="plex", **changes):
        value = {"sourceId": provider + ":fixture-server", "profileId": "fixture-profile",
                 "baseUrl": "https://server.example.test", "clientId": "fixture-client",
                 "token": "synthetic-private-token", "accessToken": "synthetic-private-access",
                 "profileToken": "synthetic-private-profile"}
        value.update(changes)
        return value

    def job(self, provider="plex", kind="show", item_id="1", **changes):
        value = {"provider": provider, "action": "preview_detail",
                 "sourceId": provider + ":fixture-server", "profileId": "fixture-profile",
                 "generation": 7, "requestId": "fixture-preview",
                 "params": {"itemId": item_id, "type": kind}}
        value.update(changes)
        return value

    def response(self, body):
        return {"ok": True, "statusCode": 200, "body": json.dumps(body)}

    def plex_item(self, item_id="100", kind="episode", season=1, number=1,
                  parent="10", series="1", resume=0, watched=False, playable=True):
        item = {"ratingKey": item_id, "type": kind, "title": "Synthetic " + item_id,
                "parentRatingKey": parent, "grandparentRatingKey": series,
                "parentIndex": season, "index": number, "viewOffset": resume,
                "viewCount": int(watched), "duration": 1200000}
        if kind == "season":
            item.update(index=season, parentRatingKey=series)
        if playable:
            item["Media"] = [{"id": "2001", "container": "mp4", "videoCodec": "h264",
                              "audioCodec": "aac", "Part": [{"id": "3001", "container": "mp4",
                                                             "key": "/library/parts/3001/file.mp4"}]}]
        return item

    def plex_detail(self, item):
        return self.response({"MediaContainer": {"Metadata": [item], "size": 1}})

    def plex_page(self, items, offset=0, total=None):
        page = {"Metadata": items, "size": len(items), "offset": offset}
        page["totalSize"] = len(items) + offset if total is None else total
        return self.response({"MediaContainer": page})

    def silo_item(self, item_id="100", kind="episode", season=1, number=1,
                  series="1", resume=0, watched=False, playable=True):
        item = {"content_id": item_id, "type": kind, "title": "Synthetic " + item_id,
                "series_id": series, "season_number": season, "episode_number": number,
                "duration_seconds": 1200, "position_seconds": resume / 1000,
                "user_state": {"played": watched}, "versions": []}
        if playable:
            item["versions"] = [{"file_id": "fixture-file", "container": "mp4",
                                 "codec_video": "h264", "codec_audio": "aac", "duration": 1200000}]
        return item

    def run_job(self, provider="plex", *, job=None, responses=None, session=None,
                changed_session=None, change_revision=False, elapsed_step=0):
        if job is None:
            job = self.job(provider)
        if session is None:
            session = self.session(provider)
        with tempfile.TemporaryDirectory(prefix="silo-preview-detail-") as directory:
            temporary = Path(directory)
            worker = temporary / "ApiTask.brs"
            source = (ROOT / "components/ApiTask.brs").read_text()
            for name in ("TaskDeviceSession", "TaskNowMs", "TaskPreviewElapsedMs"):
                source = source.replace("function " + name + "(", "function Unused" + name + "(", 1)
            worker.write_text(source)
            boundary = temporary / "boundaries.brs"
            boundary.write_text(BOUNDARIES)
            return run_function([*FILES, ROOT / "components/TaskSiloReplan.brs", worker, boundary], "RunPreviewDetail",
                                [job, session, responses or [], changed_session,
                                 change_revision, elapsed_step], root=temporary)

    def test_movie_and_episode_use_fresh_detail_and_preserve_worker_scope(self):
        for provider in ("plex", "silo"):
            for kind in ("movie", "episode"):
                with self.subTest(provider=provider, kind=kind):
                    item = self.plex_item(kind=kind, resume=123000) if provider == "plex" else self.silo_item(kind=kind, resume=123000)
                    response = self.plex_detail(item) if provider == "plex" else self.response(item)
                    result = self.run_job(provider, job=self.job(provider, kind, "100"), responses=[response])
                    outcome = result["outcome"]
                    self.assertTrue(outcome["ok"], outcome)
                    self.assertEqual(("preview_detail", provider + ":fixture-server", "fixture-profile", 7, "fixture-preview"),
                                     tuple(outcome[key] for key in ("action", "sourceId", "profileId", "generation", "requestId")))
                    self.assertEqual("100", outcome["data"]["candidateItemId"])
                    self.assertEqual(123000, outcome["data"]["item"]["resumeMs"])
                    self.assertEqual(provider + ":fixture-server", outcome["data"]["item"]["sourceId"])
                    self.assertEqual(1, len(result["requests"]))
                    self.assertEqual("GET", result["requests"][0]["method"])
                    self.assertNotIn("plan", outcome)
                    self.assertNotIn("synthetic-private", json.dumps(outcome))

    def test_plex_declared_on_deck_gets_exact_fresh_episode_without_inventory_scan(self):
        show = self.plex_item("1", "show", playable=False)
        for on_deck in ({"Metadata": [self.plex_item()]}, [self.plex_item()], self.plex_item()):
            with self.subTest(on_deck=on_deck):
                show["OnDeck"] = on_deck
                result = self.run_job(responses=[self.plex_detail(show), self.plex_detail(self.plex_item(resume=90000))])
                self.assertTrue(result["outcome"]["ok"], result)
                self.assertEqual("1", result["outcome"]["data"]["candidateItemId"])
                self.assertEqual("100", result["outcome"]["data"]["item"]["itemId"])
                self.assertEqual(["/library/metadata/1", "/library/metadata/100"],
                                 [urlsplit(request["url"]).path for request in result["requests"]])

    def test_silo_declared_target_uses_existing_detail_route_and_profile_headers(self):
        show = self.silo_item("1", "show", playable=False)
        show["play_content_id"] = "100"
        result = self.run_job("silo", responses=[self.response(show), self.response(self.silo_item(resume=90000))])
        self.assertTrue(result["outcome"]["ok"], result)
        self.assertEqual("1", result["outcome"]["data"]["candidateItemId"])
        self.assertEqual("100", result["outcome"]["data"]["item"]["itemId"])
        self.assertEqual(["/api/v2/catalog/items/1", "/api/v2/catalog/items/100"],
                         [urlsplit(request["url"]).path for request in result["requests"]])
        self.assertTrue(all(request["headers"]["X-Profile-Id"] == "fixture-profile" for request in result["requests"]))

    def test_silo_wire_series_type_resolves_as_show_without_changing_wire_request(self):
        show = self.silo_item("1", "series", playable=False)
        show["play_content_id"] = "100"
        for kind in ("show", "series"):
            with self.subTest(kind=kind):
                result = self.run_job("silo", job=self.job("silo", kind),
                                     responses=[self.response(show), self.response(self.silo_item())])
                self.assertTrue(result["outcome"]["ok"], result)
                self.assertEqual("episode", result["outcome"]["data"]["item"]["type"])

    def test_declared_target_rejects_special_foreign_changed_or_unplayable_episode_without_fallback(self):
        for provider in ("plex", "silo"):
            for changes in ({"season": 0}, {"series": "other"}, {"item_id": "999"}, {"playable": False}):
                with self.subTest(provider=provider, changes=changes):
                    show = self.plex_item("1", "show", playable=False) if provider == "plex" else self.silo_item("1", "show", playable=False)
                    leaf = self.plex_item(**changes) if provider == "plex" else self.silo_item(**changes)
                    if provider == "plex":
                        show["OnDeck"] = {"Metadata": [self.plex_item()]}
                        responses = [self.plex_detail(show), self.plex_detail(leaf)]
                    else:
                        show["play_content_id"] = "100"
                        responses = [self.response(show), self.response(leaf)]
                    result = self.run_job(provider, responses=responses)
                    self.assertFalse(result["outcome"]["ok"])
                    self.assertEqual("preview_unavailable", result["outcome"]["errorCode"])
                    self.assertEqual(2, len(result["requests"]))

    def test_complete_plex_inventory_prefers_resume_and_skips_specials(self):
        show = self.plex_item("1", "show", playable=False)
        seasons = [self.plex_item("0", "season", season=0, playable=False), self.plex_item("10", "season", playable=False)]
        episodes = [self.plex_item("101", watched=False), self.plex_item("102", number=2, resume=90000)]
        result = self.run_job(responses=[self.plex_detail(show), self.plex_page(seasons), self.plex_page(episodes),
                                        self.plex_detail(episodes[1])])
        self.assertTrue(result["outcome"]["ok"], result)
        self.assertEqual("102", result["outcome"]["data"]["item"]["itemId"])
        self.assertNotIn("/library/metadata/0/children", [urlsplit(r["url"]).path for r in result["requests"]])

    def test_complete_silo_inventory_selects_first_unwatched_normal_episode(self):
        show = self.silo_item("1", "show", playable=False)
        seasons = [self.silo_item("10", "season", playable=False)]
        episodes = [self.silo_item("100", watched=True), self.silo_item("101", number=2)]
        result = self.run_job("silo", responses=[self.response(show), self.response({"items": seasons}),
                             self.response({"items": episodes}), self.response(episodes[1])])
        self.assertTrue(result["outcome"]["ok"], result)
        self.assertEqual("101", result["outcome"]["data"]["item"]["itemId"])

    def test_known_resume_does_not_wait_for_later_season_directories(self):
        show = self.plex_item("1", "show", playable=False)
        seasons = [self.plex_item("10", "season", playable=False),
                   self.plex_item("20", "season", season=2, playable=False)]
        target = self.plex_item(resume=90000)
        result = self.run_job(responses=[self.plex_detail(show), self.plex_page(seasons),
                                        self.plex_page([target]), self.plex_detail(target)])
        self.assertTrue(result["outcome"]["ok"], result["outcome"])
        self.assertEqual("100", result["outcome"]["data"]["item"]["itemId"])
        self.assertEqual(4, len(result["requests"]))
        self.assertNotIn("/library/metadata/20/children", [urlsplit(request["url"]).path for request in result["requests"]])

    def test_silo_catalog_auth_refresh_preserves_original_scope_and_fresh_detail(self):
        session = self.session("silo", refreshToken="synthetic-private-refresh")
        refresh = {"ok": True, "body": (ROOT / "tests/fixtures/silo/refresh.json").read_text()}
        result = self.run_job("silo", job=self.job("silo", "movie", "100"), session=session,
                             responses=[{"ok": False, "errorCode": "auth_required", "statusCode": 401},
                                        refresh, self.response(self.silo_item(kind="movie"))])
        self.assertTrue(result["outcome"]["ok"], result["outcome"])
        self.assertEqual("fixture-profile", result["outcome"]["profileId"])
        self.assertEqual(["/api/v2/catalog/items/100", "/api/v2/auth/refresh", "/api/v2/catalog/items/100"],
                         [urlsplit(request["url"]).path for request in result["requests"]])
        self.assertTrue(all(timeout <= 4000 for timeout in result["timeouts"]), result["timeouts"])

    def test_partial_silo_inventory_is_unresolved_without_invented_cursor(self):
        show = self.silo_item("1", "show", playable=False)
        partial = {"items": [self.silo_item("10", "season", playable=False)],
                   "page": {"has_more": True, "next_cursor": "unsupported"}}
        result = self.run_job("silo", responses=[self.response(show), self.response(partial)])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("incomplete_inventory", result["outcome"]["errorCode"])
        self.assertEqual(2, len(result["requests"]))
        self.assertTrue(all("cursor" not in request["url"] for request in result["requests"]))

    def test_bad_candidate_scope_or_type_is_rejected_without_http(self):
        for changes in ({"sourceId": "plex:other"}, {"profileId": "other"}, {"profileId": None},
                        {"params": {"itemId": "1", "type": "season"}}):
            with self.subTest(changes=changes):
                result = self.run_job(job=self.job(**changes))
                self.assertFalse(result["outcome"]["ok"])
                self.assertEqual([], result["requests"])

    def test_identity_or_revision_change_during_read_discards_result(self):
        for changes in ({"changed_session": self.session(sourceId="plex:other")},
                        {"changed_session": self.session(profileId="other")}, {"change_revision": True}):
            with self.subTest(changes=changes):
                result = self.run_job(job=self.job(kind="movie", item_id="100"),
                                     responses=[self.plex_detail(self.plex_item(kind="movie"))], **changes)
                self.assertFalse(result["outcome"]["ok"])
                self.assertEqual("session_changed", result["outcome"]["errorCode"])
                self.assertEqual(1, len(result["requests"]))

    def test_late_detail_exceeding_wall_budget_is_discarded(self):
        result = self.run_job(job=self.job(kind="movie", item_id="100"), elapsed_step=20000,
                             responses=[self.plex_detail(self.plex_item(kind="movie"))])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("lookup_budget", result["outcome"]["errorCode"])

    def test_plex_paging_does_not_choose_before_later_resume_or_claim_empty_partial(self):
        show = self.plex_item("1", "show", playable=False)
        episodes = [self.plex_item(str(100 + i), number=i + 1, watched=True) for i in range(48)]
        target = self.plex_item("148", number=49, resume=90000)
        result = self.run_job(responses=[self.plex_detail(show), self.plex_page([self.plex_item("10", "season", playable=False)]),
                                        self.plex_page(episodes, total=49), self.plex_page([target], offset=48, total=49),
                                        self.plex_detail(target)])
        self.assertTrue(result["outcome"]["ok"], result)
        self.assertEqual("148", result["outcome"]["data"]["item"]["itemId"])
        self.assertIn("X-Plex-Container-Start=48", result["requests"][3]["url"])

    def test_plex_incomplete_empty_page_does_not_prove_end(self):
        show = self.plex_item("1", "show", playable=False)
        result = self.run_job(responses=[self.plex_detail(show), self.plex_page([], total=20)])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("incomplete_inventory", result["outcome"]["errorCode"])

    def test_bad_first_on_deck_cannot_borrow_later_valid_reference(self):
        show = self.plex_item("1", "show", playable=False)
        show["OnDeck"] = {"Metadata": [{"title": "Unidentified"}, self.plex_item()]}
        result = self.run_job(responses=[self.plex_detail(show)])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("preview_unavailable", result["outcome"]["errorCode"])
        self.assertEqual(1, len(result["requests"]))

    def test_inventory_and_fresh_detail_must_agree_on_physical_episode_identity(self):
        show = self.plex_item("1", "show", playable=False)
        for changes in ({"season": 2}, {"number": 2}, {"parent": "20"}):
            with self.subTest(changes=changes):
                result = self.run_job(responses=[self.plex_detail(show), self.plex_page([self.plex_item("10", "season", playable=False)]),
                                                self.plex_page([self.plex_item()]), self.plex_detail(self.plex_item(**changes))])
                self.assertFalse(result["outcome"]["ok"])
                self.assertEqual("preview_unavailable", result["outcome"]["errorCode"])

    def test_malformed_season_membership_is_rejected_instead_of_selecting_foreign_episode(self):
        show = self.plex_item("1", "show", playable=False)
        foreign = self.plex_item(series="other")
        result = self.run_job(responses=[self.plex_detail(show), self.plex_page([self.plex_item("10", "season", playable=False)]),
                                        self.plex_page([foreign])])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("invalid_inventory", result["outcome"]["errorCode"])
        self.assertEqual(3, len(result["requests"]))

    def test_silo_explicit_foreign_membership_is_not_overwritten_by_decode_context(self):
        show = self.silo_item("1", "series", playable=False)
        result = self.run_job("silo", responses=[self.response(show),
                             self.response({"items": [self.silo_item("10", "season", playable=False)]}),
                             self.response({"items": [self.silo_item(series="other")]}),
                             self.response(self.silo_item())])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("invalid_inventory", result["outcome"]["errorCode"])
        self.assertEqual(3, len(result["requests"]))

    def test_same_native_episode_id_in_two_seasons_is_ambiguous(self):
        show = self.plex_item("1", "show", playable=False)
        seasons = [self.plex_item("10", "season", playable=False), self.plex_item("20", "season", season=2, playable=False)]
        second = self.plex_item(season=2, parent="20")
        result = self.run_job(responses=[self.plex_detail(show), self.plex_page(seasons),
                                        self.plex_page([self.plex_item(watched=True)]),
                                        self.plex_page([second]), self.plex_detail(second)])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("invalid_inventory", result["outcome"]["errorCode"])
        self.assertEqual(4, len(result["requests"]))

    def test_all_watched_or_no_normal_seasons_stays_unavailable(self):
        show = self.silo_item("1", "series", playable=False)
        for seasons in ([], [self.silo_item("0", "season", season=0, playable=False)],
                        [self.silo_item("10", "season", playable=False)]):
            with self.subTest(seasons=seasons):
                responses = [self.response(show), self.response({"items": seasons})]
                if seasons and seasons[0]["season_number"] > 0:
                    responses.append(self.response({"items": [self.silo_item(watched=True)]}))
                result = self.run_job("silo", responses=responses)
                self.assertFalse(result["outcome"]["ok"])
                self.assertEqual("preview_unavailable", result["outcome"]["errorCode"])

    def test_native_read_and_inventory_budgets_stay_unresolved(self):
        show = self.silo_item("1", "series", playable=False)
        seasons = [self.silo_item(str(10 + i), "season", season=i + 1, playable=False) for i in range(12)]
        result = self.run_job("silo", responses=[self.response(show), self.response({"items": seasons}),
                             *[self.response({"items": []}) for _ in seasons]])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("lookup_budget", result["outcome"]["errorCode"])
        self.assertEqual(12, len(result["requests"]))
        items = [self.silo_item(str(100 + i), number=i + 1) for i in range(193)]
        result = self.run_job("silo", responses=[self.response(show), self.response({"items": seasons[:1]}),
                             self.response({"items": items})])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("lookup_budget", result["outcome"]["errorCode"])
        self.assertEqual(3, len(result["requests"]))


if __name__ == "__main__":
    unittest.main()
