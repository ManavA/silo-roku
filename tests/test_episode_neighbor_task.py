"""Read-only episode lookup executes the real policy and provider adapters."""

import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "components/EpisodeNeighborTask.brs"
POLICY = ROOT / "source/core/EpisodeNeighbors.brs"
FILES = [ROOT / "source/core/ServerUrlPolicy.brs",
         ROOT / "source/core/MediaScope.brs",
         ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/adapters/PlexAdapter.brs",
         ROOT / "source/adapters/SiloAdapter.brs", POLICY]

BOUNDARIES = '''
function LoadSession(provider as String) as Object
    return m.fixtureSession
end function

function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function

function EpisodeNeighborDeviceSession(provider as String, session as Object) as Object
    return session
end function

function EpisodeNeighborElapsedMs() as Integer
    return m.elapsedMs
end function

function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    m.requests.Push(request)
    m.timeouts.Push(timeoutMs)
    if m.elapsedSteps.Count() > 0 then m.elapsedMs = m.elapsedMs + m.elapsedSteps.Shift()
    if m.changeRevision then m.fixtureRevision = m.fixtureRevision + 1
    if m.changedSession <> invalid then m.fixtureSession = m.changedSession
    if m.responses.Count() = 0 then return {ok:false,errorCode:"network_timeout"}
    return m.responses.Shift()
end function

function RunEpisodeNeighborJob(job as Object, session as Object, responses as Object, elapsedSteps as Object, changedSession as Dynamic, changeRevision as Boolean) as Object
    m.fixtureSession = session
    m.fixtureRevision = 0
    m.requests = []
    m.timeouts = []
    m.responses = responses
    m.elapsedSteps = elapsedSteps
    m.elapsedMs = 0
    m.changedSession = changedSession
    m.changeRevision = changeRevision
    m.top = {job:job,result:invalid}
    runNeighborJob()
    return {outcome:m.top.result,requests:m.requests,timeouts:m.timeouts}
end function
'''


class EpisodeNeighborTaskTests(unittest.TestCase):
    def session(self, provider="plex", **changes):
        session = {"sourceId": provider + ":fixture-server", "profileId": "fixture-profile",
                   "baseUrl": "https://server.example.test", "clientId": "fixture-client"}
        if provider == "plex":
            session.update(accountToken="synthetic-private-account", token="synthetic-private-token")
        else:
            session.update(accessToken="synthetic-private-access", profileToken="synthetic-private-profile")
        session.update(changes)
        return session

    def anchor(self, provider="plex", **changes):
        item = {"provider": provider, "sourceId": provider + ":fixture-server", "itemId": "100",
                "type": "episode", "title": "Synthetic episode", "seasonNumber": 1,
                "episodeNumber": 1, "seasonItemId": "10", "parentItemId": "10",
                "seriesItemId": "1", "seriesId": "1"}
        item.update(changes)
        return item

    def job(self, provider="plex", anchor=None, **changes):
        if anchor is None:
            anchor = self.anchor(provider)
        value = {"provider": provider, "sourceId": provider + ":fixture-server",
                 "profileId": "fixture-profile", "generation": 7, "lookupId": "fixture-lookup",
                 "anchorItemId": anchor["itemId"], "playbackSessionId": "fixture-playback",
                 "params": {"anchor": anchor}, "private": "synthetic-private-job"}
        value.update(changes)
        return value

    def response(self, body):
        return {"ok": True, "statusCode": 200, "body": json.dumps(body)}

    def plex_episode(self, item_id="100", number=1, season=1, parent="10", series="1", playable=False):
        item = {"ratingKey": item_id, "type": "episode", "title": "Synthetic " + item_id,
                "parentRatingKey": parent, "grandparentRatingKey": series,
                "parentIndex": season, "index": number, "duration": 1200000}
        if playable:
            item["Media"] = [{"id": "2001", "container": "mp4", "videoCodec": "h264",
                              "audioCodec": "aac", "Part": [{"id": "3001", "container": "mp4",
                                                             "key": "/library/parts/3001/file.mp4"}]}]
        return item

    def plex_page(self, items, offset=0, total=None):
        container = {"Metadata": items, "size": len(items), "offset": offset}
        if total is not None:
            container["totalSize"] = total
        return self.response({"MediaContainer": container})

    def plex_detail(self, item=None, **changes):
        if item is None:
            item = self.plex_episode("101", 2, playable=True)
        item.update(changes)
        return self.response({"MediaContainer": {"Metadata": [item], "size": 1}})

    def silo_episode(self, item_id="100", number=1, season=1, playable=False):
        item = {"content_id": item_id, "type": "episode", "title": "Synthetic " + item_id,
                "series_id": "1", "season_number": season, "episode_number": number,
                "duration_seconds": 1200}
        if playable:
            item["versions"] = [{"file_id": "fixture-file", "container": "mp4",
                                 "codec_video": "h264", "codec_audio": "aac", "duration": 1200000}]
        return item

    def run_job(self, job=None, *, provider="plex", session=None, responses=None,
                elapsed_steps=None, changed_session=None, change_revision=False):
        self.assertTrue(WORKER.is_file(), "dedicated read-only episode neighbor worker is missing")
        self.assertTrue(POLICY.is_file(), "episode neighbor policy must be shared with the worker")
        if job is None:
            job = self.job(provider)
        if session is None:
            session = self.session(provider)
        if responses is None:
            responses = [self.plex_page([self.plex_episode(), self.plex_episode("101", 2)], total=2),
                         self.plex_detail()]
        with tempfile.TemporaryDirectory(prefix="silo-neighbor-worker-") as directory:
            temporary = Path(directory)
            worker = temporary / "EpisodeNeighborTask.brs"
            source = WORKER.read_text()
            for name in ("EpisodeNeighborDeviceSession", "EpisodeNeighborElapsedMs"):
                source = source.replace("function " + name + "(", "function Unused" + name + "(", 1)
            worker.write_text(source)
            boundary = temporary / "boundaries.brs"
            boundary.write_text(BOUNDARIES)
            return run_function([*FILES, worker, boundary], "RunEpisodeNeighborJob",
                                [job, session, responses, elapsed_steps or [], changed_session,
                                 change_revision], root=temporary)

    def test_native_task_declares_only_read_only_worker_dependencies(self):
        path = ROOT / "components/EpisodeNeighborTask.xml"
        self.assertTrue(path.is_file(), "episode neighbor SceneGraph Task is missing")
        component = ET.parse(path).getroot()
        self.assertEqual("Task", component.get("extends"))
        scripts = [node.get("uri") for node in component.findall("script")]
        for script in (*FILES, WORKER, ROOT / "source/auth/SessionStore.brs", ROOT / "source/network/Http.brs"):
            self.assertIn("pkg:/" + script.relative_to(ROOT).as_posix(), scripts)
        self.assertNotIn("pkg:/components/ApiTask.brs", scripts)
        self.assertEqual({"job", "result"}, {node.get("id") for node in component.findall("interface/field")})

    def test_call_and_wall_budget_admission_preserves_native_timeout_floor(self):
        self.assertTrue(WORKER.is_file(), "bounded read-only worker is missing")
        for calls, elapsed, allowed, timeout in ((0, 0, True, 4000), (11, 0, True, 4000),
                                                 (12, 0, False, 0), (0, 18750, True, 1000),
                                                 (0, 18751, False, 0), (0, 20000, False, 0)):
            with self.subTest(calls=calls, elapsed=elapsed):
                result = run_function(WORKER, "EpisodeNeighborAdmission", [calls, elapsed])
                self.assertEqual(allowed, result["allowed"])
                self.assertEqual(timeout, result["timeoutMs"])
                if not allowed:
                    self.assertEqual("lookup_budget", result["errorCode"])

    def test_complete_same_season_candidate_is_verified_by_native_detail(self):
        result = self.run_job()
        outcome = result["outcome"]
        self.assertEqual("known", outcome["status"])
        self.assertEqual("101", outcome["candidate"]["itemId"])
        self.assertEqual("100", outcome["proof"]["currentItemId"])
        self.assertEqual("101", outcome["proof"]["nextItemId"])
        self.assertEqual(["/library/metadata/10/children", "/library/metadata/101"],
                         [urlsplit(request["url"]).path for request in result["requests"]])
        self.assertTrue(all(request["method"] == "GET" for request in result["requests"]))
        for key in ("provider", "sourceId", "profileId", "generation", "lookupId", "anchorItemId", "playbackSessionId"):
            self.assertEqual(self.job()[key], outcome[key])
        self.assertNotIn("synthetic-private", json.dumps(outcome))
        self.assertNotIn("server.example.test", json.dumps(outcome))

    def test_plex_current_children_follows_the_server_offset_to_complete_inventory(self):
        first = [self.plex_episode(str(100 + index), index + 1) for index in range(48)]
        result = self.run_job(responses=[self.plex_page(first, total=49),
                                        self.plex_page([self.plex_episode("148", 49)], offset=48, total=49),
                                        self.plex_detail()])
        self.assertEqual("known", result["outcome"]["status"])
        queries = [parse_qs(urlsplit(request["url"]).query) for request in result["requests"][:2]]
        self.assertEqual([["0"], ["48"]], [query["X-Plex-Container-Start"] for query in queries])
        self.assertEqual([["48"], ["48"]], [query["X-Plex-Container-Size"] for query in queries])

    def test_cross_season_candidate_requires_complete_show_seasons_and_native_detail(self):
        seasons = [{"ratingKey": "10", "type": "season", "title": "Season 1", "index": 1, "parentRatingKey": "1"},
                   {"ratingKey": "20", "type": "season", "title": "Season 2", "index": 2, "parentRatingKey": "1"}]
        result = self.run_job(responses=[self.plex_page([self.plex_episode()], total=1),
                                        self.plex_page(seasons, total=2),
                                        self.plex_page([self.plex_episode("200", 1, 2, "20")], total=1),
                                        self.plex_detail(self.plex_episode("200", 1, 2, "20", playable=True))])
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual("200", result["outcome"]["candidate"]["itemId"])
        self.assertEqual("20", result["outcome"]["proof"]["nextSeasonItemId"])
        self.assertEqual(["/library/metadata/10/children", "/library/metadata/1/children",
                          "/library/metadata/20/children", "/library/metadata/200"],
                         [urlsplit(request["url"]).path for request in result["requests"]])

    def test_authoritative_final_episode_returns_verified_end_without_allocating_playback(self):
        season = {"ratingKey": "10", "type": "season", "title": "Season 1", "index": 1, "parentRatingKey": "1"}
        result = self.run_job(responses=[self.plex_page([self.plex_episode()], total=1),
                                        self.plex_page([season], total=1)])
        self.assertEqual("verified_end", result["outcome"]["status"])
        self.assertNotIn("candidate", result["outcome"])
        self.assertNotIn("proof", result["outcome"])
        self.assertEqual(2, len(result["requests"]))
        self.assertTrue(all(request["method"] == "GET" for request in result["requests"]))

    def test_missing_plex_series_context_is_hydrated_from_native_parent_detail(self):
        anchor = self.anchor(seriesItemId="", seriesId="", seasonItemId="")
        season = {"ratingKey": "10", "type": "season", "title": "Season 1", "index": 1, "parentRatingKey": "1"}
        result = self.run_job(self.job(anchor=anchor), responses=[self.plex_detail(season),
                                        self.plex_page([self.plex_episode(), self.plex_episode("101", 2)], total=2),
                                        self.plex_detail()])
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual("/library/metadata/10", urlsplit(result["requests"][0]["url"]).path)
        self.assertEqual("1", result["outcome"]["proof"]["seriesId"])

    def test_silo_has_more_keeps_lookup_unresolved_without_undocumented_cursor(self):
        body = {"items": [self.silo_episode(), self.silo_episode("101", 2)],
                "page": {"has_more": True, "next_cursor": "synthetic-unsupported-cursor"}}
        result = self.run_job(provider="silo", responses=[self.response(body)])
        self.assertIn(result["outcome"]["status"], ("retryable", "ambiguous"))
        self.assertEqual("incomplete_inventory", result["outcome"]["errorCode"])
        self.assertIsNone(result["outcome"].get("candidate"))
        self.assertEqual(1, len(result["requests"]))
        self.assertEqual("/api/v2/catalog/series/1/seasons/1/episodes", urlsplit(result["requests"][0]["url"]).path)
        self.assertNotIn("cursor", result["requests"][0]["url"])

    def test_silo_complete_next_episode_is_verified_and_scoped(self):
        body = {"items": [self.silo_episode(), self.silo_episode("101", 2)], "page": {"has_more": False}}
        result = self.run_job(provider="silo", responses=[self.response(body), self.response(self.silo_episode("101", 2, playable=True))])
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual("silo:fixture-server", result["outcome"]["candidate"]["sourceId"])
        self.assertEqual("101", result["outcome"]["candidate"]["itemId"])
        self.assertEqual("/api/v2/catalog/items/101", urlsplit(result["requests"][-1]["url"]).path)
        self.assertEqual("fixture-profile", result["requests"][0]["headers"]["X-Profile-Id"])

    def test_silo_complete_inventory_over_one_hundred_items_is_not_silently_truncated(self):
        anchor = self.anchor("silo", itemId="200", episodeNumber=101, parentItemId="", seasonItemId="")
        items = [self.silo_episode(str(100 + index), index + 1) for index in range(102)]
        result = self.run_job(self.job("silo", anchor=anchor), provider="silo",
                             responses=[self.response({"items": items, "page": {"has_more": False}}),
                                        self.response(self.silo_episode("201", 102, playable=True))])
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual("201", result["outcome"]["candidate"]["itemId"])

    def test_silo_oversized_complete_inventory_stays_unresolved(self):
        items = [self.silo_episode(str(100 + index), index + 1) for index in range(193)]
        result = self.run_job(provider="silo", responses=[self.response({"items": items, "page": {"has_more": False}})])
        self.assertEqual("retryable", result["outcome"]["status"])
        self.assertEqual("lookup_budget", result["outcome"]["errorCode"])
        self.assertNotIn("candidate", result["outcome"])
        self.assertEqual(1, len(result["requests"]))

    def test_candidate_detail_without_playable_versions_does_not_become_known(self):
        result = self.run_job(responses=[self.plex_page([self.plex_episode(), self.plex_episode("101", 2)], total=2),
                                        self.plex_detail(self.plex_episode("101", 2))])
        self.assertIn(result["outcome"]["status"], ("retryable", "ambiguous"))
        self.assertEqual("unavailable_candidate", result["outcome"]["errorCode"])
        self.assertIsNone(result["outcome"].get("candidate"))

    def test_stale_or_missing_explicit_source_profile_is_rejected_without_http(self):
        for changes in ({"sourceId": "plex:another"}, {"profileId": "another"},
                        {"profileId": None}, {"anchorItemId": "999"}):
            with self.subTest(changes=changes):
                result = self.run_job(self.job(**changes))
                self.assertNotEqual("known", result["outcome"]["status"])
                self.assertEqual([], result["requests"])

    def test_scope_or_revision_change_during_io_discards_candidate(self):
        for changes in ({"changed_session": self.session(sourceId="plex:another")},
                        {"changed_session": self.session(profileId="another")},
                        {"change_revision": True}):
            with self.subTest(changes=changes):
                result = self.run_job(**changes)
                self.assertEqual("retryable", result["outcome"]["status"])
                self.assertEqual("session_changed", result["outcome"]["errorCode"])
                self.assertIsNone(result["outcome"].get("candidate"))
                self.assertEqual(1, len(result["requests"]))

    def test_twenty_second_wall_budget_discards_late_responses_and_stops_lookup(self):
        result = self.run_job(elapsed_steps=[20000])
        self.assertEqual("retryable", result["outcome"]["status"])
        self.assertEqual("lookup_budget", result["outcome"]["errorCode"])
        self.assertIsNone(result["outcome"].get("candidate"))
        self.assertEqual(1, len(result["requests"]))
        self.assertLessEqual(result["timeouts"][0], 4000)

    def test_remaining_wall_budget_bounds_each_http_timeout(self):
        result = self.run_job(elapsed_steps=[18000, 100])
        self.assertEqual("known", result["outcome"]["status"])
        self.assertEqual(2, len(result["timeouts"]))
        self.assertGreaterEqual(result["timeouts"][1], 1000)
        self.assertLessEqual(result["timeouts"][1], 1750)

    def test_http_failure_is_compact_and_never_echoes_private_body(self):
        result = self.run_job(responses=[{"ok": False, "errorCode": "network_timeout",
                                          "body": "synthetic-private-error"}])
        self.assertEqual("retryable", result["outcome"]["status"])
        self.assertEqual("network_timeout", result["outcome"]["errorCode"])
        self.assertNotIn("synthetic-private", json.dumps(result["outcome"]))


if __name__ == "__main__":
    unittest.main()
