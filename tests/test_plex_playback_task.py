"""Plex native resume and lease cleanup use the actual adapter and worker."""

import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/core/PlexReplacementPolicy.brs",
         ROOT / "source/adapters/PlexAdapter.brs"]

# The standalone interpreter cannot query Roku decoders or the registry, and
# these synthetic requests must not leave the process. The actual planner,
# request builder, fixture decoder and timeline conversion still execute.
BOUNDARIES = '''
function TaskDirectPlexSupported(plan as Object) as Boolean
    m.directChecks = m.directChecks + 1
    return m.directSupported
end function

function TaskUniqueId() as String
    return "fixture-transcode-session"
end function

function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function

function HttpRequest(request as Object, timeoutMs = 9000 as Integer) as Object
    m.requests.Push(request)
    m.timeouts.Push(timeoutMs)
    if m.changeRevision then m.fixtureRevision = m.fixtureRevision + 1
    if m.responses.Count() = 0 then return {ok:true, body:""}
    return m.responses.Shift()
end function

function RunPlexPlayback(action as String, session as Object, detailBody as String, params as Object, directSupported as Boolean, responses as Object, changeRevision as Boolean) as Object
    m.directSupported = directSupported
    m.directChecks = 0
    m.responses = responses
    m.requests = []
    m.timeouts = []
    m.fixtureRevision = 0
    m.changeRevision = changeRevision
    if action = "playback_start"
        decoded = DecodePlexResponse("detail", detailBody, {sourceId:session.sourceId})
        params["detail"] = decoded.data
        outcome = TaskStartPlayback("plex", session, params, 0)
    else
        outcome = TaskPlaybackEvent("plex", session, action, params, 0)
    end if
    return {outcome:outcome, requests:m.requests, timeouts:m.timeouts, directChecks:m.directChecks}
end function
'''


class PlexPlaybackTaskTests(unittest.TestCase):
    def test_playback_start_requires_fresh_detail_even_with_item_and_version_index(self):
        result = run_function([*FILES, ROOT / "components/ApiTask.brs"], "TaskStartPlexPlayback",
                              [{"sourceId": "plex:fixture-server"},
                               {"itemId": "1", "versionIndex": 0, "startPositionMs": 0}, 0])
        self.assertEqual({"ok": False, "errorCode": "detail_required"}, result)

    def run_playback(self, action="playback_start", params=None, *, direct=False,
                     responses=None, change_revision=False):
        session = {"clientId": "fixture-client", "sourceId": "plex:fixture-server",
                   "baseUrl": "https://server.example.test", "local": False,
                   "accountToken": "synthetic-account-token", "token": "synthetic-server-token"}
        detail = json.loads((ROOT / "tests/fixtures/plex/movie_detail.json").read_text())
        detail["MediaContainer"]["Metadata"][0]["viewOffset"] = 120000
        if params is None:
            params = {"versionIndex": 0, "startPositionMs": 90500}
        if responses is None:
            responses = [{"ok": True, "body": (ROOT / "tests/fixtures/plex/decision-copy.json").read_text()}]
        with tempfile.TemporaryDirectory(prefix="silo-plex-playback-") as directory:
            temporary = Path(directory)
            worker = temporary / "ApiTask.brs"
            source = (ROOT / "components/ApiTask.brs").read_text()
            for name in ("TaskDirectPlexSupported", "TaskUniqueId"):
                source = source.replace(f"function {name}(", f"function Unused{name}(", 1)
            worker.write_text(source)
            boundary = temporary / "boundaries.brs"
            boundary.write_text(BOUNDARIES)
            return run_function([*FILES, worker, boundary], "RunPlexPlayback",
                                [action, session, json.dumps(detail), params, direct,
                                 responses, change_revision], root=temporary)

    def test_hls_resume_uses_zero_manifest_offset_and_absolute_native_timeline(self):
        result = self.run_playback()
        self.assertTrue(result["outcome"]["ok"])
        plan = result["outcome"]["plan"]
        self.assertEqual(["0"], parse_qs(urlsplit(plan["url"]).query)["offset"])
        self.assertEqual(90500, plan["startPositionMs"])
        self.assertEqual(90500, plan["originalResumeMs"])
        self.assertEqual(0, plan["timelineOffsetMs"])
        self.assertFalse(plan["relativeTimeline"])
        self.assertEqual([7000], result["timeouts"])
        self.assertNotIn("synthetic-server-token", plan["url"])

    def test_explicit_playback_limits_reach_decision_and_manifest_with_selected_audio(self):
        result = self.run_playback(params={"versionIndex": 0, "startPositionMs": 0,
                                          "maxVideoBitrate": 1200, "videoResolution": "960x540",
                                          "audioStreamId": "a/1", "purpose": "PREVIEW"})
        self.assertTrue(result["outcome"]["ok"])
        for url in (result["requests"][0]["url"], result["outcome"]["plan"]["url"]):
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(["1200"], query["maxVideoBitrate"])
            self.assertEqual(["960x540"], query["videoResolution"])
            self.assertEqual(["a/1"], query["audioStreamID"])
            self.assertNotIn("purpose", query)

    def test_omitted_playback_limits_keep_foreground_defaults(self):
        result = self.run_playback()
        for url in (result["requests"][0]["url"], result["outcome"]["plan"]["url"]):
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(["8000"], query["maxVideoBitrate"])
            self.assertEqual(["1920x1080"], query["videoResolution"])

    def test_invalid_explicit_limits_fail_before_network_or_direct_selection(self):
        cases = [{"maxVideoBitrate": value} for value in (0, 200001, 1.5, "1200", True, None)]
        cases += [{"videoResolution": value} for value in ("0x540", "3841x2160", "1920x2161",
                                                          "960x540&private=token", "", 540, None)]
        for limits in cases:
            with self.subTest(limits=limits):
                result = self.run_playback(params={"versionIndex": 1, **limits}, direct=True)
                self.assertEqual({"ok": False, "errorCode": "invalid_request"}, result["outcome"])
                self.assertEqual([], result["requests"])
                self.assertEqual(0, result["directChecks"])

    def test_beginning_overrides_a_stale_detail_resume_position(self):
        result = self.run_playback(params={"versionIndex": 0, "startPositionMs": 0})
        plan = result["outcome"]["plan"]
        self.assertEqual(0, plan["startPositionMs"])
        self.assertEqual(0, plan["originalResumeMs"])
        self.assertEqual(0, plan["timelineOffsetMs"])

    def test_hls_default_resume_keeps_detail_position_without_timeline_offset(self):
        result = self.run_playback(params={"versionIndex": 0})
        plan = result["outcome"]["plan"]
        self.assertEqual(120000, plan["startPositionMs"])
        self.assertEqual(0, plan["timelineOffsetMs"])

    def test_direct_play_keeps_requested_position_and_makes_no_preflight_request(self):
        result = self.run_playback(params={"versionIndex": 1, "startPositionMs": 90500}, direct=True)
        plan = result["outcome"]["plan"]
        self.assertEqual("mp4", plan["streamFormat"])
        self.assertEqual("direct", plan["delivery"])
        self.assertEqual(90500, plan["startPositionMs"])
        self.assertFalse(plan["relativeTimeline"])
        self.assertEqual([], result["requests"])

    def test_explicit_retry_uses_hls_even_when_the_native_mp4_was_supported(self):
        result = self.run_playback(params={"versionIndex": 1, "startPositionMs": 90500,
                                          "forceTranscode": True}, direct=True)
        self.assertTrue(result["outcome"]["ok"])
        plan = result["outcome"]["plan"]
        self.assertEqual("hls", plan["streamFormat"])
        self.assertEqual("transcode", plan["delivery"])
        self.assertEqual("plex:fixture-server", plan["sourceId"])
        self.assertEqual("1", plan["itemId"])
        self.assertEqual("plex:fixture-server:1:2002:3002", plan["versionId"])
        self.assertEqual((1, 0), (plan["mediaIndex"], plan["partIndex"]))
        self.assertEqual(90500, plan["startPositionMs"])
        self.assertEqual(90500, plan["originalResumeMs"])
        self.assertEqual(0, result["directChecks"])
        self.assertEqual(["/video/:/transcode/universal/decision"],
                         [urlsplit(request["url"]).path for request in result["requests"]])
        self.assertEqual([7000], result["timeouts"])
        query = parse_qs(urlsplit(plan["url"]).query)
        self.assertEqual(["/library/metadata/1"], query["path"])
        self.assertEqual(["1"], query["mediaIndex"])
        self.assertEqual(["0"], query["partIndex"])
        self.assertEqual(["0"], query["offset"])
        self.assertNotIn("synthetic-server-token", plan["url"])

    def test_false_retry_flag_preserves_normal_direct_selection(self):
        result = self.run_playback(params={"versionIndex": 1, "startPositionMs": 0,
                                          "forceTranscode": False}, direct=True)
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual("direct", result["outcome"]["plan"]["delivery"])
        self.assertEqual("mp4", result["outcome"]["plan"]["streamFormat"])
        self.assertEqual([], result["requests"])
        self.assertEqual(1, result["directChecks"])

    def test_retry_rejects_a_reordered_or_missing_selected_version_before_network(self):
        for version_id in ("plex:fixture-server:1:2001:3001", "", None, 1):
            with self.subTest(version_id=version_id):
                result = self.run_playback(params={"versionIndex": 1, "versionId": version_id,
                                                  "startPositionMs": 90500, "forceTranscode": True},
                                           direct=True)
                self.assertFalse(result["outcome"]["ok"])
                self.assertEqual("version_required", result["outcome"]["errorCode"])
                self.assertNotIn("plan", result["outcome"])
                self.assertEqual([], result["requests"])
                self.assertEqual(0, result["directChecks"])

    def test_retry_accepts_the_same_selected_version_identity(self):
        version_id = "plex:fixture-server:1:2002:3002"
        result = self.run_playback(params={"versionIndex": 1, "versionId": version_id,
                                          "startPositionMs": 90500, "forceTranscode": True},
                                   direct=True)
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual("hls", result["outcome"]["plan"]["streamFormat"])
        self.assertEqual(version_id, result["outcome"]["plan"]["versionId"])
        self.assertEqual(1, len(result["requests"]))

    def test_retry_decision_timeout_returns_error_without_retrying_native_or_hls(self):
        result = self.run_playback(params={"versionIndex": 1, "startPositionMs": 90500,
                                          "forceTranscode": True}, direct=True,
                                   responses=[{"ok": False, "errorCode": "timeout"}])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("timeout", result["outcome"]["errorCode"])
        self.assertNotIn("plan", result["outcome"])
        self.assertEqual(0, result["directChecks"])
        self.assertEqual(1, len(result["requests"]))

    def test_retry_preserves_explicit_beginning_and_selected_audio_request(self):
        result = self.run_playback(params={"versionIndex": 1, "startPositionMs": 0,
                                          "audioStreamId": "4005", "forceTranscode": True},
                                   direct=True)
        plan = result["outcome"]["plan"]
        self.assertEqual("hls", plan["streamFormat"])
        self.assertEqual(0, plan["startPositionMs"])
        self.assertEqual(0, plan["timelineOffsetMs"])
        query = parse_qs(urlsplit(plan["url"]).query)
        self.assertEqual(["4005"], query["audioStreamID"])
        self.assertEqual(["4005"], parse_qs(urlsplit(result["requests"][0]["url"]).query)["audioStreamID"])

    def test_retry_revision_change_releases_hls_session_and_returns_no_plan(self):
        result = self.run_playback(params={"versionIndex": 1, "startPositionMs": 90500,
                                          "forceTranscode": True}, direct=True,
                                   change_revision=True)
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("session_changed", result["outcome"]["errorCode"])
        self.assertNotIn("plan", result["outcome"])
        self.assertEqual(["/video/:/transcode/universal/decision", "/video/:/transcode/universal/stop"],
                         [urlsplit(request["url"]).path for request in result["requests"]])

    def test_revision_change_cancels_the_plan_and_releases_transcode_session(self):
        result = self.run_playback(change_revision=True)
        self.assertEqual("session_changed", result["outcome"]["errorCode"])
        self.assertNotIn("plan", result["outcome"])
        self.assertEqual(["/video/:/transcode/universal/decision", "/video/:/transcode/universal/stop"],
                         [urlsplit(request["url"]).path for request in result["requests"]])

    def event_params(self, **changes):
        params = {"itemId": "1", "transcodeSessionId": "fixture-transcode-session",
                  "positionMs": 100250, "durationMs": 7200000, "state": "playing"}
        params.update(changes)
        return params

    def test_failed_final_timeline_still_releases_transcode_and_preserves_error(self):
        result = self.run_playback("playback_stop", self.event_params(),
                                   responses=[{"ok": False, "errorCode": "network_error"}, {"ok": True}])
        self.assertEqual(["/:/timeline", "/video/:/transcode/universal/stop"],
                         [urlsplit(request["url"]).path for request in result["requests"]])
        self.assertEqual("network_error", result["outcome"]["errorCode"])
        self.assertEqual([5000, 5000], result["timeouts"])
        self.assertNotIn("synthetic", json.dumps(result["outcome"]))

    def test_invalid_final_timeline_still_releases_a_known_transcode_session(self):
        result = self.run_playback("playback_stop", self.event_params(itemId=""), responses=[])
        self.assertEqual(["/video/:/transcode/universal/stop"],
                         [urlsplit(request["url"]).path for request in result["requests"]])
        self.assertEqual("invalid_request", result["outcome"]["errorCode"])

    def test_failed_transcode_stop_is_not_reported_as_saved(self):
        result = self.run_playback("playback_stop", self.event_params(),
                                   responses=[{"ok": True}, {"ok": False, "errorCode": "timeout"}])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual("timeout", result["outcome"]["errorCode"])

    def test_progress_failure_does_not_stop_active_transcode(self):
        result = self.run_playback("playback_progress", self.event_params(),
                                   responses=[{"ok": False, "errorCode": "timeout"}])
        self.assertEqual(["/:/timeline"], [urlsplit(request["url"]).path for request in result["requests"]])
        self.assertEqual("timeout", result["outcome"]["errorCode"])

    def test_direct_stop_only_reports_absolute_provider_timeline(self):
        result = self.run_playback("playback_stop", self.event_params(transcodeSessionId=""),
                                   responses=[{"ok": True}])
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(1, len(result["requests"]))
        query = parse_qs(urlsplit(result["requests"][0]["url"]).query)
        self.assertEqual(["100250"], query["time"])
        self.assertEqual(["stopped"], query["state"])

    def test_unlanded_resume_skips_plex_timeline_but_releases_transcode(self):
        result = self.run_playback("playback_stop",
                                   self.event_params(persistProgress=False),
                                   responses=[{"ok": True}])
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual(["/video/:/transcode/universal/stop"],
                         [urlsplit(request["url"]).path for request in result["requests"]])


if __name__ == "__main__":
    unittest.main()
