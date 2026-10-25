"""Exercise production MP4 capability and adapter/worker boundaries without IO."""

import json
from pathlib import Path
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]

BOUNDARY = '''
function FixtureNativeType(value as Dynamic) as String
    kind = type(value)
    if kind = "Integer" or kind = "roInt" then return m.numericAlias
    return kind
end function
function FixtureVideoQuery(query as Object) as Dynamic
    m.videoQueries.Push(query)
    if m.rejectDimensions and (query.DoesExist("width") or query.DoesExist("height")) then return {result:false,updated:"height",height:"n.a."}
    return m.videoResult
end function
function FixtureAudioQuery(query as Object) as Dynamic
    m.audioQueries.Push(query)
    return m.audioResult
end function
function FixtureVideoMode() as Dynamic
    m.modeQueries.Push(m.videoMode)
    return m.videoMode
end function
function FixtureDevice() as Object
    return {CanDecodeVideo:FixtureVideoQuery,CanDecodeAudio:FixtureAudioQuery,GetVideoMode:FixtureVideoMode,
        videoQueries:m.videoQueries,audioQueries:m.audioQueries,modeQueries:m.modeQueries,
        videoResult:m.videoResult,audioResult:m.audioResult,videoMode:m.videoMode,rejectDimensions:m.rejectDimensions}
end function
sub FixturePrepare(video as Dynamic, audio as Dynamic, videoMode as Dynamic, alias as String, rejectDimensions as Boolean)
    m.numericAlias = alias
    m.rejectDimensions = rejectDimensions
    m.videoResult = video
    m.audioResult = audio
    m.videoMode = videoMode
    m.videoQueries = []
    m.audioQueries = []
    m.modeQueries = []
end sub
function FixtureSupport(plans as Object, mode as Dynamic, video as Dynamic, audio as Dynamic, alias as String, rejectDimensions as Boolean) as Object
    results = []
    for each plan in plans
        FixturePrepare(video,audio,mode,alias,rejectDimensions)
        supported = TaskDirectPlexSupported(plan)
        results.Push({supported:supported,videoQueries:m.videoQueries,audioQueries:m.audioQueries,modeQueries:m.modeQueries})
    end for
    return results
end function
function TaskUniqueId() as String
    return "fixture-transcode-session"
end function
function SessionRevision(provider as String) as Integer
    return 0
end function
function HttpRequest(request as Object, timeoutMs = 9000 as Integer) as Object
    m.requests.Push(request)
    if m.responses.Count()=0 then return {ok:false,errorCode:"network_error"}
    return m.responses.Shift()
end function
function FixtureStart(session as Object, detailBody as String, params as Object, video as Dynamic, audio as Dynamic, mode as Dynamic, responses as Object) as Object
    FixturePrepare(video,audio,mode,"roInteger",true)
    m.requests = []
    m.responses = responses
    decoded = DecodePlexResponse("detail",detailBody,{sourceId:session.sourceId})
    params["detail"] = decoded.data
    outcome = TaskStartPlayback("plex",session,params,0)
    return {outcome:outcome,requests:m.requests,videoQueries:m.videoQueries,audioQueries:m.audioQueries}
end function
'''


def plan(**changes):
    value = dict(ok=True, streamFormat="mp4", container="mp4", videoCodec="h264",
                 audioCodec="aac", audioChannels=2, width=1920, height=1080,
                 url="https://synthetic.example.test/file.mp4",
                 headers={"X-Plex-Token": "synthetic-private-token"}, startPositionMs=90500)
    value.update(changes)
    return value


class PlexMp4GateTests(unittest.TestCase):
    def call(self, name, *args, alias=False):
        with tempfile.TemporaryDirectory(prefix="silo-mp4-gate-") as directory:
            temp = Path(directory)
            worker = temp / "ApiTask.brs"
            source = (ROOT / "components/ApiTask.brs").read_text()
            source = source.replace('CreateObject("roDeviceInfo")', "FixtureDevice()")
            source = source.replace("function TaskUniqueId(", "function UnusedTaskUniqueId(", 1)
            worker.write_text(source)
            policy = temp / "PlexDirectCapability.brs"
            source = (ROOT / "source/core/PlexDirectCapability.brs").read_text()
            if alias:
                source = re.sub(r"\btype\s*\(", "FixtureNativeType(", source, flags=re.I)
            policy.write_text(source)
            boundary = temp / "boundary.brs"
            boundary.write_text(BOUNDARY)
            return run_function([ROOT / "source/auth/SessionPolicy.brs",
                                 ROOT / "source/adapters/PlexAdapter.brs", policy,
                                 ROOT / "source/core/PlexReplacementPolicy.brs", worker, boundary], name, list(args), root=temp)

    def support(self, values=None, mode="1080p", video=None, audio=None,
                alias="roInteger", reject_dimensions=True):
        return self.call("FixtureSupport", values or [plan()], mode,
                         {"result": True} if video is None else video,
                         {"result": True} if audio is None else audio,
                         alias, reject_dimensions, alias=True)

    def start(self, *, position=90500, force=False, video=None, audio=None, version=None, overrides=None):
        session = dict(clientId="fixture-client", sourceId="plex:fixture-server",
                       baseUrl="https://server.example.test", local=False,
                       token="synthetic-server-token", accountToken="synthetic-account-token")
        detail = json.loads((ROOT / "tests/fixtures/plex/movie_detail.json").read_text())
        detail["MediaContainer"]["Metadata"][0]["viewOffset"] = 120000
        params = dict(versionIndex=1, startPositionMs=position, forceTranscode=force)
        params.update(overrides or {})
        if version is not None:
            params["versionId"] = version
        return self.call("FixtureStart", session, json.dumps(detail), params,
                         {"result": True} if video is None else video,
                         {"result": True} if audio is None else audio, "1080p",
                         [{"ok": True, "body": (ROOT / "tests/fixtures/plex/decision-copy.json").read_text()}])

    def test_task_component_loads_the_actual_capability_dependency(self):
        node = ET.parse(ROOT / "components/ApiTask.xml").getroot()
        scripts = [script.get("uri") for script in node.findall("./script")]
        self.assertIn("pkg:/source/core/PlexDirectCapability.brs", scripts)
        self.assertLess(scripts.index("pkg:/source/core/PlexDirectCapability.brs"), scripts.index("pkg:/components/ApiTask.brs"))

    def test_actual_dimension_query_rejection_does_not_block_bounded_mp4(self):
        result = self.support()[0]
        self.assertTrue(result["supported"])
        self.assertEqual([{"codec": "mpeg4 avc", "container": "mp4"}], result["videoQueries"])
        self.assertEqual([{"codec": "aac", "container": "mp4", "chcnt": 2}], result["audioQueries"])
        self.assertNotIn("synthetic-private-token", str(result))
        self.assertNotIn("synthetic.example.test", str(result))

    def test_output_mode_and_fixed_ceiling_bound_actual_file_dimensions(self):
        hd = self.support([plan(width=1280, height=720), plan()], mode="720p")
        self.assertEqual([True, False], [r["supported"] for r in hd])
        for mode in ("1080p", "1080p24", "2160p60", "2160p30Dv"):
            with self.subTest(mode=mode):
                result = self.support([plan(), plan(width=3840, height=2160), plan(width=2048)], mode=mode)
                self.assertEqual([True, False, False], [r["supported"] for r in result])
                self.assertEqual([], result[1]["videoQueries"])
                self.assertEqual([], result[2]["videoQueries"])
        for mode in ("", "unknown", "1080p-unrecognized", None, 1080):
            with self.subTest(mode=mode):
                result = self.support(mode=mode)[0]
                self.assertFalse(result["supported"])
                self.assertEqual([], result["videoQueries"])
                self.assertEqual([], result["audioQueries"])

    def test_unknown_fractional_or_malformed_dimensions_channels_reject_before_queries(self):
        invalid = []
        for field in ("width", "height", "audioChannels"):
            for value in (0, -1, True, "2", 1.5, [], {}):
                invalid.append(plan(**{field: value}))
            value = plan()
            del value[field]
            invalid.append(value)
        invalid += [plan(width=2147483648), plan(audioChannels=9)]
        for result in self.support(invalid, reject_dimensions=False):
            self.assertFalse(result["supported"])
            self.assertEqual([], result["videoQueries"])
            self.assertEqual([], result["audioQueries"])

    def test_strict_sdk_boolean_receipts_are_required_for_both_lanes(self):
        for receipt in ({"result": False}, {"result": 1}, {"result": "true"}, {}, True, [], "yes"):
            with self.subTest(receipt=receipt):
                self.assertFalse(self.support(video=receipt, reject_dimensions=False)[0]["supported"])
                self.assertFalse(self.support(audio=receipt, reject_dimensions=False)[0]["supported"])

    def test_codec_container_and_selected_audio_channel_queries_preserve_known_values(self):
        values = [plan(videoCodec=codec, audioCodec=audio, audioChannels=channels)
                  for codec in ("h264", "hevc") for audio, channels in (("aac", 2), ("ac3", 6), ("eac3", 6))]
        for value, result in zip(values, self.support(values)):
            self.assertTrue(result["supported"])
            self.assertEqual("mp4", result["videoQueries"][0]["container"])
            self.assertEqual(value["audioChannels"], result["audioQueries"][0]["chcnt"])
            self.assertEqual(value["audioCodec"], result["audioQueries"][0]["codec"])

    def test_mkv_and_unknown_container_codec_combinations_remain_ineligible(self):
        invalid = [plan(container="mkv", streamFormat="mkv"), plan(container="mkv"),
                   plan(container=""), plan(streamFormat="hls"), plan(videoCodec="vp9"),
                   plan(audioCodec="truehd"), plan(ok=1)]
        for result in self.support(invalid, reject_dimensions=False):
            self.assertFalse(result["supported"])
            self.assertEqual([], result["videoQueries"])
            self.assertEqual([], result["audioQueries"])

    def test_numeric_alias_guards_preserve_values_without_string_coercion(self):
        for alias in ("Integer", "roInt", "roInteger", "LongInteger", "roLongInteger", "Float", "roFloat", "Double", "roDouble"):
            with self.subTest(alias=alias):
                result = self.support([plan(audioCodec="eac3", audioChannels=6)], alias=alias)[0]
                self.assertTrue(result["supported"])
                self.assertEqual(6, result["audioQueries"][0]["chcnt"])

    def test_actual_adapter_worker_keeps_selected_version_and_resume_or_beginning(self):
        for position in (0, 90500):
            with self.subTest(position=position):
                result = self.start(position=position, version="plex:fixture-server:1:2002:3002")
                self.assertTrue(result["outcome"]["ok"])
                selected = result["outcome"]["plan"]
                self.assertEqual("direct", selected["delivery"])
                self.assertEqual("plex:fixture-server:1:2002:3002", selected["versionId"])
                self.assertEqual((1, 0, position), (selected["mediaIndex"], selected["partIndex"], selected["startPositionMs"]))
                self.assertEqual([], result["requests"])
                self.assertFalse(selected["relativeTimeline"])
                self.assertNotIn("synthetic-server-token", selected["url"])

    def test_forced_compatible_retry_preserves_exact_version_and_start_without_decoder_queries(self):
        for position in (0, 90500):
            with self.subTest(position=position):
                result = self.start(position=position, force=True, version="plex:fixture-server:1:2002:3002")
                self.assertTrue(result["outcome"]["ok"])
                selected = result["outcome"]["plan"]
                self.assertEqual("transcode", selected["delivery"])
                self.assertEqual("plex:fixture-server:1:2002:3002", selected["versionId"])
                self.assertEqual(position, selected["startPositionMs"])
                self.assertEqual(position, selected["originalResumeMs"])
                self.assertEqual([], result["videoQueries"])
                self.assertEqual([], result["audioQueries"])
                self.assertEqual(1, len(result["requests"]))
                query = parse_qs(urlsplit(result["requests"][0]["url"]).query)
                self.assertEqual(["1"], query["mediaIndex"])
                self.assertEqual(["0"], query["partIndex"])
                self.assertEqual(["0"], parse_qs(urlsplit(selected["url"]).query)["offset"])

    def test_explicit_provider_lane_or_quality_overrides_keep_existing_compatible_handling(self):
        for overrides, field in (({"audioStreamId": "4005"}, "audioStreamID"),
                                 ({"maxVideoBitrate": 1200}, "maxVideoBitrate"),
                                 ({"videoResolution": "960x540"}, "videoResolution")):
            with self.subTest(overrides=overrides):
                result = self.start(overrides=overrides, version="plex:fixture-server:1:2002:3002")
                self.assertTrue(result["outcome"]["ok"])
                selected = result["outcome"]["plan"]
                self.assertEqual("transcode", selected["delivery"])
                self.assertEqual("plex:fixture-server:1:2002:3002", selected["versionId"])
                self.assertEqual(90500, selected["startPositionMs"])
                self.assertEqual([], result["videoQueries"])
                self.assertEqual([], result["audioQueries"])
                self.assertEqual(1, len(result["requests"]))
                expected = str(next(iter(overrides.values())))
                for url in (result["requests"][0]["url"], selected["url"]):
                    self.assertEqual([expected], parse_qs(urlsplit(url).query)[field])

    def test_native_rejection_keeps_finite_existing_hls_fallback_and_resume(self):
        result = self.start(audio={"result": False})
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual("transcode", result["outcome"]["plan"]["delivery"])
        self.assertEqual(90500, result["outcome"]["plan"]["startPositionMs"])
        self.assertEqual(1, len(result["requests"]))

    def test_foreign_selected_version_rejects_before_device_or_provider_work(self):
        result = self.start(version="plex:fixture-server:1:wrong:file")
        self.assertEqual({"ok": False, "errorCode": "version_required"}, result["outcome"])
        self.assertEqual([], result["requests"])
        self.assertEqual([], result["videoQueries"])
        self.assertEqual([], result["audioQueries"])


if __name__ == "__main__":
    unittest.main()
