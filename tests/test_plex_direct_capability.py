"""Original capability evidence; neither codec approval nor this probe starts Video."""

from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from tools.brightscript import run_function
from tools.package import build_archive

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/PlexDirectCapability.brs"

BOUNDARY = '''
function FixtureNativeType(value as Dynamic) as String
    kind = type(value)
    if kind = "Integer" or kind = "roInt" then return m.numericAlias
    return kind
end function
function FixtureVideoQuery(query as Object) as Dynamic
    m.videoQueries.Push(query)
    ' Actual C208X control: codec/container passes; width/height makes it false.
    if m.rejectDimensions and (query.DoesExist("width") or query.DoesExist("height")) then return {result:false,updated:"height",height:"n.a."}
    return m.videoResult
end function
function FixtureAudioQuery(query as Object) as Dynamic
    m.audioQueries.Push(query)
    return m.audioResult
end function
function FixtureVideoMode() as String
    return "1080p"
end function
function FixtureVideoDevice() as Object
    return {CanDecodeVideo:FixtureVideoQuery,CanDecodeAudio:FixtureAudioQuery,GetVideoMode:FixtureVideoMode,
        videoQueries:m.videoQueries,audioQueries:m.audioQueries,
        videoResult:m.videoResult,audioResult:m.audioResult,rejectDimensions:m.rejectDimensions}
end function
function FixtureProbe(plan as Dynamic, video as Dynamic, audio as Dynamic, alias as String) as Object
    m.numericAlias = alias
    m.rejectDimensions = true
    m.videoQueries = []
    m.audioQueries = []
    m.videoResult = video
    m.audioResult = audio
    queries = PlexDirectCapabilityQueries(plan)
    return {queries:queries, accepted:PlexDirectCapabilityAccepted(queries,video,audio),
        probe:PlexDirectCapabilityProbe(plan,FixtureVideoDevice()),
        videoQueries:m.videoQueries,audioQueries:m.audioQueries}
end function
function FixtureQueries(plans as Object, alias as String) as Object
    m.numericAlias = alias
    result = []
    for each plan in plans
        result.Push(PlexDirectCapabilityQueries(plan))
    end for
    return result
end function
function FixtureResults(queries as Dynamic, results as Object) as Object
    accepted = []
    for each result in results
        accepted.Push(PlexDirectCapabilityAccepted(queries,result,result))
    end for
    return accepted
end function
function FixtureProductionSupport(plan as Object, rejectDimensions = false as Boolean) as Object
    m.rejectDimensions = rejectDimensions
    m.videoQueries = []
    m.audioQueries = []
    m.videoResult = {result:true}
    m.audioResult = {result:true}
    return {supported:TaskDirectPlexSupported(plan),videoQueries:m.videoQueries,audioQueries:m.audioQueries}
end function
'''


def plan(**changes):
    value = {"ok": True, "streamFormat": "mkv", "container": "mkv", "videoCodec": "h264",
             "audioCodec": "aac", "audioChannels": 2, "width": 1920, "height": 1080,
             "url": "https://synthetic.example.test/library/parts/11/22/file.mkv",
             "headers": {"X-Plex-Token": "synthetic-private-token"}, "startPositionMs": 90500}
    value.update(changes)
    return value


class PlexDirectCapabilityTests(unittest.TestCase):
    def call(self, name, *args, native_alias=False, worker=False):
        with tempfile.TemporaryDirectory(prefix="silo-mkv-boundary-") as directory:
            root = Path(directory)
            policy = root / POLICY.name
            source = POLICY.read_text()
            if native_alias:
                source = re.sub(r"\btype\s*\(", "FixtureNativeType(", source, flags=re.I)
            policy.write_text(source)
            helper = root / "boundary.brs"
            helper.write_text(BOUNDARY)
            files = [policy, helper]
            if worker:
                native = root / "ApiTask.brs"
                native.write_text((ROOT / "components/ApiTask.brs").read_text().replace(
                    'CreateObject("roDeviceInfo")', 'FixtureVideoDevice()'))
                files.append(native)
            return run_function(files, name, list(args), root=root)

    def probe(self, value=None, video=None, audio=None, alias="roInteger"):
        if value is None:
            value = plan()
        return self.call("FixtureProbe", value, {"result": True} if video is None else video,
                         {"result": True} if audio is None else audio, alias, native_alias=True)

    def test_native_container_probe_does_not_send_rejected_dimension_properties(self):
        result = self.probe()
        self.assertEqual({"ok": True, "videoSupported": True, "audioSupported": True}, result["probe"])
        self.assertEqual([{"codec": "mpeg4 avc", "container": "mkv"}], result["videoQueries"])

    def test_mkv_h264_queries_keep_dimensions_separate_from_native_container_audio_queries(self):
        result = self.probe()
        self.assertEqual({"ok": True,
                          "video": {"codec": "mpeg4 avc", "container": "mkv"},
                          "dimensions": {"width": 1920, "height": 1080},
                          "audio": {"codec": "aac", "container": "mkv", "chcnt": 2}}, result["queries"])
        self.assertTrue(result["accepted"])
        self.assertEqual([result["queries"]["video"]], result["videoQueries"])
        self.assertEqual([result["queries"]["audio"]], result["audioQueries"])
        self.assertEqual({"ok": True, "videoSupported": True, "audioSupported": True}, result["probe"])

    def test_selected_aac_ac3_eac3_channel_facts_reach_native_query(self):
        values = [plan(audioCodec=codec, audioChannels=channels)
                  for codec, channels in (("aac", 2), ("ac3", 6), ("eac3", 8))]
        results = self.call("FixtureQueries", values, "roInteger", native_alias=True)
        self.assertEqual([{"codec": codec, "container": "mkv", "chcnt": channels}
                          for codec, channels in (("aac", 2), ("ac3", 6), ("eac3", 8))],
                         [result.get("audio") for result in results])

    def test_only_real_associative_array_boolean_true_is_approval(self):
        queries = self.probe()["queries"]
        results = [None, [], True, "true", 1, {}, {"result": False}, {"result": "true"},
                   {"result": 1}, {"result": None}, {"result": True}]
        accepted = self.call("FixtureResults", queries, results)
        self.assertEqual([False] * 10 + [True], accepted)

    def test_video_or_audio_rejection_never_approves_the_probe(self):
        for video, audio in (({"result": False}, {"result": True}),
                             ({"result": True}, {"result": False})):
            with self.subTest(video=video, audio=audio):
                result = self.probe(video=video, audio=audio)
                self.assertFalse(result["accepted"])
                self.assertEqual({"ok": False, "errorCode": "capability_rejected"}, result["probe"])

    def test_invalid_plan_facts_fail_closed_before_native_queries(self):
        invalid = [None, [], "mkv", plan(ok=False), plan(ok="true"), plan(streamFormat="ts"),
                   plan(container="mp4"), plan(videoCodec="vp9"), plan(audioCodec="dts")]
        for field in ("width", "height", "audioChannels"):
            for value in (None, True, "2", 0, -1, 1.5, 1e30):
                invalid.append(plan(**{field: value}))
            missing = plan()
            del missing[field]
            invalid.append(missing)
        invalid.append(plan(audioChannels=9))
        results = self.call("FixtureQueries", invalid, "roInteger", native_alias=True)
        self.assertEqual([{"ok": False, "errorCode": "invalid_capability_facts"}] * len(invalid), results)
        result = self.probe(value=plan(audioChannels="6"))
        self.assertEqual([], result["videoQueries"])
        self.assertEqual([], result["audioQueries"])

    def test_numeric_type_aliases_preserve_real_dimension_and_channel_values(self):
        for alias in ("Integer", "roInt", "roInteger", "LongInteger", "roLongInteger", "Float", "roFloat", "Double", "roDouble"):
            with self.subTest(alias=alias):
                result = self.probe(value=plan(audioCodec="ac3", audioChannels=6), alias=alias)
                self.assertTrue(result["accepted"])
                self.assertEqual((1920, 1080, 6),
                                 (result["queries"]["dimensions"]["width"], result["queries"]["dimensions"]["height"],
                                  result["queries"]["audio"]["chcnt"]))

    def test_queries_and_status_never_contain_private_plan_fields(self):
        original = plan()
        result = self.probe(value=original)
        self.assertTrue(result["accepted"])
        self.assertNotIn("synthetic-private-token", str(result))
        self.assertNotIn("synthetic.example.test", str(result))
        self.assertNotIn("headers", str(result))
        self.assertNotIn("startPositionMs", str(result))

    def test_mp4_codec_mapping_remains_supported(self):
        values = [plan(streamFormat="mp4", container="mp4", videoCodec=codec)
                  for codec in ("h264", "hevc")]
        results = self.call("FixtureQueries", values, "roInteger", native_alias=True)
        self.assertEqual(["mpeg4 avc", "hevc"], [result.get("video", {}).get("codec") for result in results])
        self.assertTrue(all(result.get("ok") for result in results))

    def test_production_mkv_route_remains_disabled_even_when_device_would_approve(self):
        result = self.call("FixtureProductionSupport", plan(), worker=True)
        self.assertEqual({"supported": False, "videoQueries": [], "audioQueries": []}, result)

    def test_production_mp4_route_remains_available(self):
        result = self.call("FixtureProductionSupport", plan(streamFormat="mp4", container="mp4"), worker=True)
        self.assertTrue(result["supported"])

    def test_production_gate_explicitly_uses_corrected_native_query_shape(self):
        result = self.call("FixtureProductionSupport", plan(streamFormat="mp4", container="mp4"), True, worker=True)
        self.assertTrue(result["supported"])
        self.assertEqual([{"codec": "mpeg4 avc", "container": "mp4"}], result["videoQueries"])
        self.assertEqual([{"codec": "aac", "container": "mp4", "chcnt": 2}], result["audioQueries"])


class MkvManifestTests(unittest.TestCase):
    def test_candidate_manifest_enables_mkv_library_at_launch(self):
        lines = (ROOT / "manifest").read_text().splitlines()
        self.assertEqual(["requires_mkv=1"], [line for line in lines if line.startswith("requires_mkv=")])

    def test_shipping_package_preserves_mkv_requirement_at_zip_root(self):
        with tempfile.TemporaryDirectory(prefix="silo-mkv-package-") as directory:
            archive = Path(directory) / "candidate.zip"
            build_archive(ROOT, archive)
            with zipfile.ZipFile(archive) as channel:
                lines = channel.read("manifest").decode().splitlines()
                self.assertEqual(["requires_mkv=1"], [line for line in lines if line.startswith("requires_mkv=")])
                self.assertIn('CreateScene("SiloUIScene")', channel.read("source/main.brs").decode())


if __name__ == "__main__":
    unittest.main()
