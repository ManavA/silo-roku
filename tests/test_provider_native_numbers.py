"""Keep numeric values real while emulating Roku's boxed Type() names."""

import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
OWNED = [ROOT / "components/ApiTask.brs", ROOT / "source/network/Http.brs",
         ROOT / "source/adapters/SiloAdapter.brs", ROOT / "source/adapters/MetadataAdapter.brs"]
DEPENDENCIES = [ROOT / "source/core/TrackPreference.brs", ROOT / "source/adapters/PlexAdapter.brs",
                ROOT / "source/auth/SessionPolicy.brs"]
HELPERS = '''
function FixtureNativeType(value as Dynamic) as String
    kind = type(value)
    if kind = "Integer" or kind = "roInt" then return m.nativeNumericType
    return kind
end function

function NativeHttpContracts(alias as String) as Object
    m.nativeNumericType = alias
    return {timeout:HttpTimeoutMs({timeoutMs:12000},0),boundedTimeout:HttpTimeoutMs({timeoutMs:1000000},0),
        errorLimit:HttpErrorBodyLimit({errorBodyLimit:8192}),invalidErrorLimit:HttpErrorBodyLimit({errorBodyLimit:8193}),
        responseLimit:HttpResponseBodyLimit({responseBodyLimit:3}),
        oversized:HttpResponse({responseBodyLimit:3},200,"four"),
        errorBody:HttpResponse({errorBodyLimit:5},404,"error")}
end function

function NativeSiloContracts(alias as String, session as Object, startParams as Object, plan as Object) as Object
    m.nativeNumericType = alias
    pairing = DecodeSiloResponse("device_capability",FormatJson({state:"available",protocol_versions:[2]}),{})
    playback = DecodeSiloResponse("playback_capabilities",FormatJson({state:"available",allowed:true,protocol_versions:[3],installation_id:"fixture-install"}),{})
    malformed = DecodeSiloResponse("device_capability",FormatJson({state:"available",protocol_versions:["2"]}),{})
    plan.playback_plan.timeline.player_start_seconds = 12
    plan.playback_plan.timeline.timeline_offset_seconds = 30
    return {pairing:pairing,playback:playback,malformed:malformed,
        start:BuildSiloRequest("playback_start",session,startParams),plan:SiloPlaybackPlan(plan,session)}
end function

function NativeWorkerContracts(alias as String) as Object
    m.nativeNumericType = alias
    record = {schemaVersion:1,sourceId:"plex:fixture",profileId:"owner",subtitleMode:"off",
        subtitleLanguage:"",subtitleName:"",audioLanguage:"",audioName:""}
    validRecord = TaskTrackPreferenceRecordValid(record)
    record.schemaVersion = 2
    return {bandwidth:TaskPlaybackOptionsValid("plex",{maxVideoBitrate:2500,videoResolution:"1280x720"}),
        siloBandwidth:TaskPlaybackOptionsValid("silo",{bandwidthCapKbps:2500,qualityPreference:"720p"}),
        low:TaskPlaybackBandwidthValid(0),high:TaskPlaybackBandwidthValid(200001),fractional:TaskPlaybackBandwidthValid(1.5),
        status:TaskAuthTransportFailure("silo","device_capability",{statusCode:404},"silo_api_unavailable"),
        stringStatus:TaskAuthTransportFailure("silo","device_capability",{statusCode:"404"},"silo_api_unavailable"),
        validRecord:validRecord,wrongVersion:TaskTrackPreferenceRecordValid(record)}
end function

function NativeMetadataContracts(alias as String) as Object
    m.nativeNumericType = alias
    body = {page:2,total_pages:5,results:[{id:101,media_type:"movie",title:"Synthetic",release_date:"2026-01-01"}]}
    return {request:BuildMetadataRequest("discover_trending",{baseUrl:"https://metadata.example.test"},{page:2}),
        bounded:BuildMetadataRequest("discover_trending",{baseUrl:"https://metadata.example.test"},{page:100}),
        decoded:DecodeMetadataResponse("discover_trending",FormatJson(body),{}),
        year:HmNumber(2026,0),text:HmNumber("2026",0)}
end function
'''


class ProviderNativeNumbersTests(unittest.TestCase):
    def call(self, name, alias, *args):
        # Replace only the native Type accessor. ParseJson values, arithmetic,
        # request builders, decoders, and bounds execute as production code.
        with tempfile.TemporaryDirectory(prefix="silo-provider-native-type-") as directory:
            temporary = Path(directory)
            sources = []
            for original in OWNED:
                target = temporary / original.name
                target.write_text(re.sub(r"\btype\s*\(", "FixtureNativeType(", original.read_text(), flags=re.I))
                sources.append(target)
            helper = temporary / "native-types.brs"
            helper.write_text(HELPERS)
            return run_function([*DEPENDENCIES, *sources, helper], name, [alias, *args], root=temporary)

    def test_native_integer_http_limits_and_request_timeout_are_enforced(self):
        for alias in ("roInteger", "roLongInteger"):
            with self.subTest(alias=alias):
                result = self.call("NativeHttpContracts", alias)
                self.assertEqual((12000, 30000, 8192, 0, 3),
                                 tuple(result[key] for key in ("timeout", "boundedTimeout", "errorLimit", "invalidErrorLimit", "responseLimit")))
                self.assertEqual("response_too_large", result["oversized"]["errorCode"])
                self.assertEqual("error", result["errorBody"]["body"])

    def test_native_integer_silo_capabilities_start_and_timeline_plan(self):
        session = {"baseUrl": "https://silo.example", "accessToken": "synthetic-access",
                   "profileId": "fixture-profile", "profileToken": "synthetic-profile"}
        params = json.loads((ROOT / "tests/fixtures/silo/roku_start_input.json").read_text())
        params.update(startPositionMs=12000, bandwidthCapKbps=2500, qualityPreference="720p")
        plan = json.loads((ROOT / "tests/fixtures/silo/playback_decision_plan.json").read_text())
        for alias in ("roInteger", "roLongInteger"):
            with self.subTest(alias=alias):
                result = self.call("NativeSiloContracts", alias, session, params, plan)
                self.assertTrue(result["pairing"]["ok"])
                self.assertTrue(result["pairing"]["data"]["allowed"])
                self.assertTrue(result["playback"]["ok"])
                self.assertEqual([3], result["playback"]["data"]["protocolVersions"])
                self.assertFalse(result["malformed"]["ok"])
                self.assertTrue(result["start"]["ok"])
                body = json.loads(result["start"]["body"])
                self.assertEqual((12, 2500), (body["start_position"], body["bandwidth_cap_kbps"]))
                self.assertEqual((12000, 30000), (result["plan"]["startPositionMs"], result["plan"]["timelineOffsetMs"]))

    def test_native_worker_bandwidth_auth_status_and_compact_preference_validation(self):
        for alias in ("roInteger", "roLongInteger"):
            with self.subTest(alias=alias):
                result = self.call("NativeWorkerContracts", alias)
                self.assertTrue(result["bandwidth"])
                self.assertTrue(result["siloBandwidth"])
                self.assertFalse(result["low"])
                self.assertFalse(result["high"])
                self.assertFalse(result["fractional"])
                self.assertEqual(404, result["status"]["transportStatus"])
                self.assertNotIn("transportStatus", result["stringStatus"])
                self.assertEqual(alias == "roInteger", result["validRecord"])
                self.assertFalse(result["wrongVersion"])

    def test_native_metadata_integer_paging_and_identifiers_remain_numeric(self):
        for alias in ("roInteger", "roLongInteger"):
            with self.subTest(alias=alias):
                result = self.call("NativeMetadataContracts", alias)
                self.assertEqual(["2"], parse_qs(urlsplit(result["request"]["url"]).query)["page"])
                self.assertEqual(["20"], parse_qs(urlsplit(result["bounded"]["url"]).query)["page"])
                self.assertEqual((2, 3), (result["decoded"]["data"]["page"], result["decoded"]["data"]["nextPage"]))
                self.assertEqual("metadata:movie:101", result["decoded"]["data"]["rows"][0]["items"][0]["catalogId"])
                self.assertEqual((2026, 0), (result["year"], result["text"]))


if __name__ == "__main__":
    unittest.main()
