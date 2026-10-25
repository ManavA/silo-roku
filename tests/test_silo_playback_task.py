"""Silo progress acknowledgment requires a supported decoded mutation receipt.

Contract inspected at Android 78d2df93d72c7a81ee8d3467cd7fe63851dc29d3:
docs/planning/silo-api/openapi.json documents HTTP 200 PlaybackMutation for
progress and stop, with required string outcome and optional accepted/stop_id.
The Android SiloProgressApiTest uses accepted; existing Roku decoder tests use
updated for progress and stopped for stop. These synthetic fixtures are not
recordings of a live server. Neither route documents 204 or duplicate outcomes.
Server cce24de PlaybackMutation and StopPlaybackV2 additionally define replayed
for an already stopped session; the stop replay fixture below follows that schema.

Playback options inspected at Android fd95c7dd41558f83e32f8ccbbee6b78af2658570:
PlaybackStartBodyDto supports quality_preference, nullable bandwidth_cap_kbps,
and explicit audio/subtitle IDs and indices. SiloPlaybackApi maps the five
quality values exercised below. Preview intent remains local to the client.
"""

import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/silo"
FILES = [ROOT / "source/core/RuntimeIdentity.brs", ROOT / "source/auth/SessionPolicy.brs", ROOT / "source/adapters/SiloAdapter.brs",
         ROOT / "source/core/PlaybackPolicy.brs", ROOT / "source/core/SiloPlaybackPolicy.brs", ROOT / "source/core/SiloOriginalPlaybackPolicy.brs",
         ROOT / "source/core/MediaScope.brs", ROOT / "components/TaskSiloReplan.brs",
         ROOT / "source/core/SiloCompatCapability.brs", ROOT / "source/core/SiloCompatPlaybackPolicy.brs"]

# The network/device boundary is synthetic. Actual request construction,
# HTTP status mapping, worker flow and mutation decoding execute unchanged.
BOUNDARIES = '''
function TaskUniqueId() as String
    return "10000000-0000-4000-8000-000000000001"
end function

function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    m.requests.Push(request)
    m.timeouts.Push(HttpTimeoutMs(request, timeoutMs))
    if m.changeRevision and request.method = "POST" and Instr(1,request.url,"/playback/start") > 0 then m.fixtureRevision = m.fixtureRevision + 1
    if m.enforceCurrentPlan = true and request.method = "POST" and Instr(1,request.url,"/replan") > 0
        body = ParseJson(request.body)
        if body.failed_plan_id <> m.currentPlanId or body.plan_attempt_key <> m.currentPlanKey then return HttpResponse(request,409,"{""code"":""stale_playback_plan""}")
    end if
    response = m.responses.Shift()
    if m.enforceCurrentPlan = true and request.method = "POST" and Instr(1,request.url,"/replan") > 0
        accepted = ParseJson(response.body)
        if SiloObject(accepted.playback_plan)
            m.currentPlanId = accepted.playback_plan.plan_id
            m.currentPlanKey = accepted.playback_plan.plan_attempt_key
        end if
    end if
    if m.bindDecisionToRequest = true and request.method = "POST" and Instr(1,request.url,"/playback/start") > 0
        body = ParseJson(request.body):decision = ParseJson(response.body)
        if not SiloObject(decision.playback_plan) then return HttpResponse(request,response.statusCode,response.body)
        decision.playback_plan.requested_media_file_id = body.file_id
        effective = body.file_id
        if m.forceOtherEffective = true then effective = "f1"
        decision.playback_plan.effective_media_file_id = effective
        decision.playback_plan.source.media_file_id = effective
        response.body = FormatJson(decision)
    end if
    if TaskValue(response,"throws",false) then throw "private-token https://private.example"
    return HttpResponse(request,response.statusCode,response.body)
end function

function LoadSession(provider as String) as Object
    return m.fixtureSession
end function

function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function

function FixtureSiloDevice() as Object
    if m.fixtureDevice <> invalid then return m.fixtureDevice
    m.fixtureDevice = {uuids:["10000000-0000-4000-8000-000000000001","10000000-0000-4000-8000-000000000002"],
    GetChannelClientId:function() as String
        return "fixture-client"
    end function,
    GetRandomUUID:function() as String
        return m.uuids.Shift()
    end function,
    GetModel:function() as String
        return "C000X"
    end function,
    GetModelType:function() as String
        return "TV"
    end function,
    GetModelDetails:function() as Object
        return {ModelNumber:"C208X"}
    end function,
    GetOSVersion:function() as Object
        if m.osVersion <> invalid then return m.osVersion
        return {major:"15",minor:"3",revision:"4",build:"2402"}
    end function,
    CanDecodeVideo:function(format as Object) as Object
        if m.videoQueries = invalid then m.videoQueries = []
        m.videoQueries.Push(format)
        if m.rejectMain10 = true and format.profile = "main 10" then return {result:false}
        return {result:true}
    end function,
    CanDecodeAudio:function(format as Object) as Object
        if m.audioQueries = invalid then m.audioQueries = []
        m.audioQueries.Push(format)
        if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}
        if format.passthru = 1 then return {result:format.codec="eac3" and format.chcnt<=6}
        return {result:format.chcnt<=2 and format.codec="aac"}
    end function,
    GetVideoMode:function() as String
        if m.videoMode <> invalid then return m.videoMode
        return "1080p"
    end function,
    GetDisplayProperties:function() as Object
        if m.displayUnknown = true then return {}
        if m.displayPartial = true then return {hdr10:true}
        return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}
    end function}
    return m.fixtureDevice
end function

function RunSiloCapabilities(unknown as Boolean) as Object
    device = FixtureSiloDevice()
    device.displayUnknown = unknown
    caps = TaskRokuSiloCapabilities(device)
    context = TaskRokuSiloContext(device,caps)
    return {caps:caps,context:context,queries:device.audioQueries,videoQueries:device.videoQueries}
end function

function RunCompatibleAudio(version as Object, selected as Object, context as Object) as Dynamic
    return TaskSiloCompatibleAudio(version,selected,FixtureSiloDevice(),context)
end function

function RunVersionProof(version as Object, caps as Object, context as Object) as Dynamic
    device = FixtureSiloDevice():device.videoMode = "2160p60"
    return TaskSiloVersionProof(version,device,caps,context)
end function

function RunSilo4KCapabilities(rejectMain10 as Boolean) as Object
    device = FixtureSiloDevice()
    device.videoMode = "2160p60"
    device.rejectMain10 = rejectMain10
    return TaskRokuSiloCapabilities(device)
end function

function RunSiloModeCapabilities(mode as String) as Object
    device = FixtureSiloDevice()
    device.videoMode = mode
    return TaskRokuSiloCapabilities(device)
end function

function RunPartialHdrCapabilities() as Object
    device = FixtureSiloDevice()
    device.displayPartial = true
    caps = TaskRokuSiloCapabilities(device)
    return caps
end function

function RunSiloHLSNegotiation(server as Object, unknownDisplay as Boolean, osVersion = invalid as Dynamic, videoMode = "2160p60" as String, rejectMain10 = false as Boolean) as Object
    device = FixtureSiloDevice()
    device.displayUnknown = unknownDisplay
    device.osVersion = osVersion
    device.videoMode = videoMode
    device.rejectMain10 = rejectMain10
    caps = TaskRokuSiloCapabilities(device)
    context = TaskRokuSiloContext(device,caps)
    context = TaskNegotiateSiloHLS(context,device,server,caps)
    return {caps:caps,context:context,queries:device.audioQueries}
end function

function RunUniquePlaybackIds() as Object
    return {first:UnusedTaskUniqueId(),second:UnusedTaskUniqueId()}
end function

' The host FormatJson mistakes repeated array references for cycles. Deep
' clone the real context output so request serialization still runs unchanged.
function TaskRokuSiloContext(device as Object, capabilities as Object) as Object
    return FixtureDeepClone(UnusedTaskRokuSiloContext(device,capabilities))
end function

function FixtureDeepClone(value as Dynamic) as Dynamic
    if type(value) = "roAssociativeArray"
        copy = {}
        for each key in value
            copy[key] = FixtureDeepClone(value[key])
        end for
        return copy
    else if type(value) = "roArray"
        copy = []
        for each entry in value
            copy.Push(FixtureDeepClone(entry))
        end for
        return copy
    end if
    return value
end function

function RunSiloPlaybackEvent(action as String, session as Object, params as Object, responses as Object) as Object
    m.requests = []
    m.timeouts = []
    m.responses = responses
    m.fixtureRevision = 0
    m.changeRevision = false
    outcome = TaskPlaybackEvent("silo",session,action,params,0)
    return {outcome:outcome,requests:m.requests,timeouts:m.timeouts}
end function

function RunSiloNativeBestStart(session as Object, params as Object, responses as Object, outputMode = "2160p60" as String, rejectMain10 = false as Boolean, forceOtherEffective = false as Boolean) as Object
    device = FixtureSiloDevice()
    device.videoMode = outputMode
    device.rejectMain10 = rejectMain10
    m.bindDecisionToRequest = true
    m.forceOtherEffective = forceOtherEffective
    return RunSiloPlaybackStart(session,params,responses,false)
end function

function RunSiloPlaybackStart(session as Object, params as Object, responses as Object, changeRevision as Boolean) as Object
    m.requests = []
    m.timeouts = []
    m.responses = responses
    m.fixtureRevision = 0
    m.changeRevision = changeRevision
    m.fixtureSession = session
    ' The real Task owns a job/cancellation node even for this older worker seam.
    m.top=CreateObject("roSGNode","Node")
    m.top.AddFields({cancelled:false,job:{provider:"silo",sourceId:session.sourceId,profileId:session.profileId,generation:7,requestId:41,action:"playback_start",params:params}})
    outcome = TaskStartPlayback("silo",session,params,0)
    return {outcome:outcome,requests:m.requests,timeouts:m.timeouts}
end function
'''


class SiloPlaybackTaskTests(unittest.TestCase):
    def test_hd_output_caps_worker_quality_at_720p(self):
        for mode in ['720p','480p','480i']:
            with self.subTest(mode=mode):
                self.assertEqual('720p',self.worker('RunSiloModeCapabilities',[mode])['max_resolution'])
    def test_remux_uses_hls_without_disabling_range_capable_original_files(self):
        servers = [{}, {'deliveries': ['server_transcode_hls']},
                   {'deliveries': ['server_remux_hls'],
                    'features': ['native_hls_mpegts_v1']},
                   {'deliveries': ['server_remux_hls'],
                    'features': ['native_hls_separate_audio_v1']}]
        for server in servers:
            with self.subTest(server=server):
                value = self.worker('RunSiloHLSNegotiation', [server, False])
                deliveries = value['context']['deliveries']
                self.assertFalse(deliveries['progressive']['enabled'])
                self.assertFalse(deliveries['progressive']['supported_on_device'])
                self.assertTrue(deliveries['original_http']['enabled'])
                self.assertIn('hevc', deliveries['original_http']['video_codecs'])
                self.assertEqual('2160p', value['caps']['max_resolution'])
                self.assertEqual(bool(server), deliveries['hls']['enabled'])

    def test_dv8_requires_the_validated_device_os_and_separate_audio_evidence(self):
        os = {'major':'15','minor':'3','revision':'4','build':'2402'}
        bounds = self.worker('RokuSiloDVProfileBounds',['C000X','TV','C208X',os,9])
        self.assertEqual([5,8],[row['profile'] for row in bounds])
        self.assertEqual(6,bounds[1]['max_level'])
        for model,kind,number,version in [('C000X','TV','other',os),('4850X','STB','4850X',os),('C000X','TV','C208X',{**os,'revision':'5'})]:
            value = self.worker('RokuSiloDVProfileBounds',[model,kind,number,version,9])
            self.assertEqual([5],[row['profile'] for row in value])
        self.assertEqual([],self.worker('RokuSiloDVProfileBounds',['3830X','STB','3830X',os,9]))

    def test_os16_dv8_stays_within_the_qualified_build_and_fresh_decoder_limit(self):
        os = {'major':'16','minor':'0','revision':'4','build':'834'}
        for maximum, expected in [(9,6),(5,5)]:
            bounds = self.worker('RokuSiloDVProfileBounds',['C000X','TV','C208X',os,maximum])
            self.assertEqual({'profile':8,'max_level':expected,'bl_compatibility_ids':[1]}, bounds[-1])
        for model, kind, number, version in [
                ('A000X','TV','C208X',os), ('C000X','STB','C208X',os),
                ('C000X','TV','C209X',os),
                ('C000X','TV','C208X',{**os,'build':'835'}),
                ('C000X','TV','C208X',{**os,'revision':'5'})]:
            with self.subTest(model=model,kind=kind,number=number,version=version):
                bounds = self.worker('RokuSiloDVProfileBounds',[model,kind,number,version,9])
                self.assertNotIn(8,[row['profile'] for row in bounds])

    def test_os16_dv8_negotiation_does_not_authorize_original_or_progressive(self):
        os = {'major':'16','minor':'0','revision':'4','build':'834'}
        server = {'features':['native_hls_separate_audio_v1','server_dv7_to_dv81_v1'],
                  'deliveries':['server_remux_hls']}
        value = self.worker('RunSiloHLSNegotiation',[server,False,os])
        deliveries = value['context']['deliveries']
        self.assertEqual([5,8],deliveries['hls']['hdr_details']['dolby_vision_profiles'])
        self.assertIn('server_dv7_to_dv81_v1',deliveries['hls']['features'])
        for name in ['original_http','progressive']:
            self.assertEqual([],deliveries[name]['hdr_details']['dolby_vision_profiles'])
        plan = {'delivery':'original_http', 'source':{'dolby_vision_profile':8,
                'dolby_vision_level':6,'dv_bl_compat_id':1},
                'effective_recipe':{'dynamic_range':'dolby_vision'},'transformations':[]}
        self.assertFalse(self.worker('SiloNativeDVReceiptSupported',[plan,value['context']]))
        plan.update(delivery='server_remux_hls',stream={'protocol':'hls'})
        self.assertTrue(self.worker('SiloNativeDVReceiptSupported',[plan,value['context']]))
        for features, unknown, mode, reject in [
                (['native_hls_mpegts_v1','server_dv7_to_dv81_v1'],False,'2160p60',False),
                (server['features'],True,'2160p60',False),
                (server['features'],False,'1080p',False),
                (server['features'],False,'2160p60',True)]:
            with self.subTest(features=features,unknown=unknown,mode=mode,reject=reject):
                denied = self.worker('RunSiloHLSNegotiation',[
                    {**server,'features':features},unknown,os,mode,reject])
                hls = denied['context']['deliveries']['hls']
                self.assertNotIn(8,hls.get('hdr_details',{}).get('dolby_vision_profiles',[]))
                self.assertNotIn('server_dv7_to_dv81_v1',hls['features'])

    def test_fresh_server_features_enable_only_implemented_hls_recipes(self):
        server = {'features': ['native_hls_mpegts_v1', 'native_hls_separate_audio_v1',
                              'server_dv7_to_dv81_v1', 'header_authenticated_media_v1'],
                  'deliveries': ['server_remux_hls', 'server_transcode_hls']}
        value = self.worker('RunSiloHLSNegotiation', [server, False])
        hls = value['context']['deliveries']['hls']
        self.assertTrue(hls['enabled'])
        self.assertEqual(['h264', 'hevc'], hls['video_codecs'])
        self.assertEqual(['aac'], hls['audio_decode_codecs'])
        self.assertEqual(['eac3'], hls['audio_passthrough_codecs'])
        self.assertNotIn('header_authenticated_media_v1', hls['features'])
        self.assertNotIn(7, hls['hdr_details']['dolby_vision_profiles'])
        self.assertEqual([], value['context']['deliveries']['progressive']['hdr_details']['dolby_vision_profiles'])
        self.assertIn({'codec': 'aac', 'container': 'ts', 'passthru': 0}, value['queries'])

    def test_request_facts_distinguish_device_hevc_from_negotiated_hls_hevc(self):
        for native in (False, True):
            with self.subTest(native=native):
                server = {'deliveries': ['server_remux_hls' if native else 'server_transcode_hls'],
                          'features': ['native_hls_mpegts_v1'] if native else []}
                value = self.worker('RunSiloHLSNegotiation', [server, False])
                facts = self.worker('TaskSiloStartRequestFacts',
                                    [None, {}, {}, '', {}, value['caps'], value['context']])
                self.assertIs(facts['hevcAdmitted'], True)
                self.assertIs(facts['hlsHevcAdmitted'], native)

    def test_old_server_only_enables_the_existing_h264_transcode_fallback(self):
        value = self.worker('RunSiloHLSNegotiation', [
            {'features': [], 'deliveries': ['server_transcode_hls']}, True])
        hls = value['context']['deliveries']['hls']
        self.assertTrue(hls['enabled'])
        self.assertEqual(['h264'], hls['video_codecs'])
        self.assertEqual(['native_hls_playback_v1'], hls['features'])
        self.assertNotIn('hdr_details', hls)

    def test_negotiated_hls_start_preserves_owned_lease_and_allows_preflight_time(self):
        # Source-derived0589 recipe retains the declared delivered EAC3-six
        # layout; the former hand-built Original recipe omitted all audio facts.
        raw = json.loads((FIXTURES / 'hdr10_split_0589_source_derived.json').read_text())
        features = ['native_hls_separate_audio_v1', 'server_dv7_to_dv81_v1']
        value = self.run_start(params={'itemId':'fixture-item','fileId':'731','startPositionMs':0},
                               decision=raw, capability_features=features)
        self.assertTrue(value['outcome']['ok'])
        self.assertEqual(['GET', 'POST'], [request['method'] for request in value['requests']])
        body = json.loads(value['requests'][1]['body'])
        self.assertEqual(['native_hls_separate_audio_v1'], body['client_features'])
        self.assertEqual('hls', value['outcome']['plan']['streamFormat'])
        self.assertEqual([6000, 90000], value['timeouts'])

    def test_unpatched_legacy_hls_start_gets_90_seconds_without_fork_features(self):
        value = self.run_start(capability_features=[],
                               capability_deliveries=['original_http', 'server_transcode_hls'])
        self.assertTrue(value['outcome']['ok'], value['outcome'])
        body = json.loads(value['requests'][1]['body'])
        self.assertEqual([], body['client_features'])
        self.assertEqual(['native_hls_playback_v1'],
                         body['client_playback_context']['deliveries']['hls']['features'])
        self.assertEqual([6000, 90000], value['timeouts'])

    def test_playback_identifiers_do_not_collide_when_two_attempts_share_a_wall_clock_second(self):
        result = self.worker("RunUniquePlaybackIds", [])
        self.assertNotEqual(result["first"], result["second"])

    def session(self):
        return {"baseUrl": "https://silo.example", "sourceId": "silo:https://silo.example",
                "profileId": "fixture-owner", "deviceId": "fixture-device",
                "accessToken": "synthetic-access-token", "profileToken": "synthetic-profile-token"}

    def worker(self, function, arguments, *, real_ids=False):
        with tempfile.TemporaryDirectory(prefix="silo-silo-playback-") as directory:
            temporary = Path(directory)
            worker = temporary / "ApiTask.brs"
            worker.write_text((ROOT / "components/ApiTask.brs").read_text().replace(
                "function TaskUniqueId(", "function TaskUniqueId(" if real_ids else "function UnusedTaskUniqueId(", 1).replace(
                "function TaskRokuSiloContext(", "function UnusedTaskRokuSiloContext(", 1).replace(
                'CreateObject("roDeviceInfo")', "FixtureSiloDevice()"))
            http = temporary / "Http.brs"
            http.write_text((ROOT / "source/network/Http.brs").read_text().replace(
                "function HttpRequest(", "function UnusedHttpRequest(", 1))
            boundary = temporary / "boundaries.brs"
            boundary.write_text(BOUNDARIES.replace("function TaskUniqueId(", "function FixtureUnusedTaskUniqueId(") if real_ids else BOUNDARIES)
            return run_function([*FILES, http, worker, boundary], function, arguments, root=temporary)

    def run_event(self, action="playback_progress", body=None, *, status=200, params=None):
        if body is None:
            fixture = "playback_stopped.json" if action == "playback_stop" else "playback_progress_accepted.json"
            body = (FIXTURES / fixture).read_text()
        if params is None:
            params = {"itemId": "fixture-item", "sessionId": "sess/1", "installationId": "fixture-installation",
                      "positionMs": 12500, "durationMs": 7200000, "sequence": 2, "isPaused": False,
                      "state": "stopped" if action == "playback_stop" else "playing"}
            if action == "playback_stop":
                params["stopId"] = "10000000-0000-4000-8000-000000000001"
        return self.worker("RunSiloPlaybackEvent",
                           [action, self.session(), params, [{"statusCode": status, "body": body}]])

    def run_start(self, params=None, decision=None, *, cleanup_status=200, cleanup_body=None,
                  change_revision=False, installation_id="server-install", cleanup_raises=False, capability_features=None, capability_deliveries=None):
        if params is None:
            params = {"itemId": "fixture-item", "fileId": "f1", "startPositionMs": 0}
        if decision is None:
            decision = (FIXTURES / "playback_decision_plan.json").read_text()
        if not isinstance(decision, str):
            decision = json.dumps(decision)
        capability = json.loads((FIXTURES / "playback_capabilities.json").read_text())
        capability["installation_id"] = installation_id
        if capability_features is not None: capability["features"] = capability_features
        if capability_deliveries is not None: capability["deliveries"] = capability_deliveries
        if cleanup_body is None:
            cleanup_body = (FIXTURES / "playback_stopped.json").read_text()
        responses = [{"statusCode": 200, "body": json.dumps(capability)},
                     {"statusCode": 200, "body": decision},
                     {"statusCode": cleanup_status, "body": cleanup_body, "throws": cleanup_raises}]
        return self.worker("RunSiloPlaybackStart", [self.session(), params, responses, change_revision])

    def assert_abandoned(self, result, code, *, cleanup_closed=False):
        self.assert_public_error(result, code, cleanup_closed=cleanup_closed)
        self.assertEqual(["GET", "POST", "DELETE"], [r["method"] for r in result["requests"]])
        self.assertEqual([6000, 12000, 5000], result["timeouts"])
        request = result["requests"][2]
        self.assertEqual("/api/v2/playback/sess-1", urlsplit(request["url"]).path)
        self.assertEqual({"installation_id": "server-install", "stop_id": "10000000-0000-4000-8000-000000000001"},
                         json.loads(request["body"]))

    def native_best_start(self, *, hdr=False, incompatible=False, dv=False, lossless=False, unknown=False, all_unknown=False, inconsistent_hdr=False, explicit=False, equal=False, avc4k=False, el_only=False, high_fps=False, unknown_fps=False, short_resume=False, track_selector=None, native_default_second=False, server_alternate=False, output_mode="2160p60", reject_main10=False, compatible_audio=False, missing_recipe=False, audio_terminal=False, hd_fallback=False, hd_oversize=False, hd_unsupported=False, hd_audio_rejected=False, quality_explicit=False, hd_all_terminal=False):
        raw=json.loads((FIXTURES / "catalog_item_detail_movie.json").read_text())
        raw["content_id"]="fixture-item"
        first={**raw["versions"][0],"file_id":"f1","resolution":"1080p","codec_video":"h264","codec_audio":"eac3","hdr":False,"bitrate":12000,
               "video_tracks":[{"codec":"h264","profile":"high","level":40,"width":1920,"height":1080,"bit_depth":8,"frame_rate":"24000/1001","dv_config_present":False,"dv_bl_compat_id_present":False,"interlaced":False}]}
        second={**first,"file_id":"f2","resolution":"2160p","codec_video":"hevc","hdr":hdr,"bitrate":40000,
                "video_tracks":[{"codec":"hevc","profile":"Main 10","level":153,"width":3840,"height":2160,"bit_depth":10,"frame_rate":"24000/1001","dv_config_present":False,"dv_bl_compat_id_present":False,"interlaced":False,"color_transfer":"smpte2084" if hdr else "bt709"}]}
        if avc4k:
            second["codec_video"]="h264"
            second["video_tracks"][0].update(codec="h264",profile="high",level=51,bit_depth=8)
        if el_only: second["video_tracks"][0]["dv_enhancement_layer"]="FEL"
        if high_fps: second["video_tracks"][0]["frame_rate"]="120/1"
        if unknown_fps: second["video_tracks"][0].pop("frame_rate")
        if short_resume: second["duration"]=60
        if inconsistent_hdr: second["video_tracks"][0]["color_transfer"]="smpte2084"
        if incompatible or lossless: second["codec_audio"]="truehd"
        if incompatible or dv:
            second["video_tracks"][0].update(dv_profile=7,dv_el_present=True,dv_config_present=True,video_range="dolbyvision")
        if unknown or all_unknown: second["video_tracks"][0].pop("profile")
        if all_unknown: first["video_tracks"][0].pop("profile")
        if equal:
            second={**first,"file_id":"f2"}
        if compatible_audio or audio_terminal:
            second['codec_audio'] = 'truehd'
            second['audio_tracks'] = [
                {'index':0,'codec':'truehd','channels':8,'language':'eng','title':'Main','default':True},
                {'index':1,'codec':'eac3','channels':6,'language':'eng','title':'Main'}]
        raw["versions"]=[first,second]
        raw["playback_variants"]=[{"variant_id":"native","part_count":1,"parts":[{"part_index":1,"default_file_id":"f2" if native_default_second else "f1","versions":raw["versions"]}]}]
        if hd_fallback:
            raw['versions']=[second]
            raw['playback_variants'][0]['parts'][0].update(default_file_id='f2',versions=[second])
        detail=self.worker("DecodeSiloResponse",["detail",json.dumps(raw),{"sourceId":self.session()["sourceId"]}])["data"]
        detail["item"]["sourceId"]=self.session()["sourceId"]
        capability=json.loads((FIXTURES / "playback_capabilities.json").read_text());capability["installation_id"]="server-install"
        decision=json.loads((FIXTURES / "playback_decision_plan.json").read_text())
        if compatible_audio:
            capability['features'] = ['native_hls_separate_audio_v1']
            decision['playback_plan']['selected_tracks'] = {'audio':{'id':'file:f2:audio:0','index':0}}
            decision['playback_plan']['effective_media_file_id'] = 'f2'
            decision['playback_plan']['source']['media_file_id'] = 'f2'
            decision['playback_plan']['requested_media_file_id'] = 'f2'
            replacement = json.loads(json.dumps(decision))
            replacement['playback_plan'].update(plan_id='plan-0002',plan_attempt_key='plan-key-0002')
            replacement['playback_plan']['selected_tracks'] = {'audio':{'id':'file:f2:audio:1','index':1}}
            replies = [raw,capability,decision,capability,replacement,{'outcome':'stopped'}]
        else:
            replies = [raw,capability,decision,{'outcome':'stopped'}]
        if missing_recipe:
            terminal = {'protocol_version':3,'server_features':[],'outcome':'adaptation_unavailable','terminal':{'reason':'adaptation_exhausted','message':'No supported route.','retryable':False}}
            replies = [raw,capability,terminal,raw,capability,decision]
        if hd_fallback:
            capability['deliveries']=['original_http','server_transcode_hls']
            capability['features']=[]
            terminal = {'protocol_version':3,'server_features':[],'outcome':'adaptation_unavailable','terminal':{'reason':'adaptation_exhausted','message':'No supported route.','retryable':False}}
            replies=[raw,capability,terminal,raw,capability,decision]
            if hd_oversize:
                oversized=json.loads(json.dumps(decision))
                oversized['playback_plan'].update(delivery='server_transcode_hls',effective_recipe={'video_codec':'h264','audio_codec':'aac','dynamic_range':'sdr','width':3840,'height':2160},transformations=[{'name':'video_to_h264','executor':'server','recipe_version':'2'},{'name':'audio_to_aac','executor':'server','recipe_version':'4'}])
                oversized['playback_plan']['stream'].update(protocol='hls',container='hls')
                replies=[raw,capability,oversized,{'outcome':'stopped'},raw,capability,decision]
            if hd_unsupported:
                unsupported=json.loads(json.dumps(decision))
                unsupported['playback_plan'].update(delivery='server_remux_hls',
                    effective_recipe={'video_codec':'hevc','audio_codec':'eac3','dynamic_range':'dolby_vision'},
                    transformations=[])
                unsupported['playback_plan']['stream'].update(protocol='hls',container='hls')
                replies=[raw,capability,unsupported,{'outcome':'stopped'},raw,capability,decision]
            if hd_audio_rejected:
                unsupported=json.loads(json.dumps(decision))
                unsupported['playback_plan'].update(delivery='server_transcode_hls',
                    effective_recipe={'video_codec':'h264','audio_codec':'aac','audio_channels':6,'dynamic_range':'sdr','width':1920,'height':1080},
                    transformations=[{'name':'video_to_h264','executor':'server','recipe_version':'2'},{'name':'audio_to_aac','executor':'server','recipe_version':'4'}])
                unsupported['playback_plan']['stream'].update(protocol='hls',container='hls')
                replies=[raw,capability,unsupported,{'outcome':'stopped'},raw,capability,decision]
            if hd_all_terminal: replies=[raw,capability,terminal]*4
        if audio_terminal:
            capability['features'] = ['native_hls_separate_audio_v1']
            decision['playback_plan']['selected_tracks'] = {'audio':{'id':'file:f2:audio:1','index':1}}
            terminal = {'protocol_version':3,'server_features':[],'outcome':'adaptation_unavailable','terminal':{'reason':'adaptation_exhausted','message':'No supported route.','retryable':False}}
            replies = [raw,capability,terminal,raw,capability,decision]
        responses=[{"statusCode":200,"body":json.dumps(x)} for x in replies]
        params={"itemId":"fixture-item","fileId":"f1","detail":detail,"autoVersion":not explicit,"qualityPreference":"original","qualityExplicit":quality_explicit}
        if hd_fallback: params["fileId"]="f2"
        if short_resume: params["startPositionMs"]=100000
        if track_selector: params[track_selector]="source-track" if track_selector.endswith("Id") else 1
        return self.worker("RunSiloNativeBestStart",[self.session(),params,responses,output_mode,reject_main10,server_alternate])

    def test_hd_roku_automatic_fallback_uses_720p_for_a_720p_output(self):
        result = self.native_best_start(hd_fallback=True, output_mode='720p')
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        starts = [json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(['720p','480p'],[body['quality_preference'] for body in starts])

    def test_unpatched_refused_hevc_hls_can_request_same_file_compatible_sdr(self):
        result=self.native_best_start(hd_fallback=True,hd_unsupported=True)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        starts=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(['original','1080p'],[b['quality_preference'] for b in starts])
        self.assertEqual(['f2','f2'],[b['file_id'] for b in starts])
        self.assertEqual(['GET','GET','POST','DELETE','GET','GET','POST'],
                         [r['method'] for r in result['requests']])

    def test_unsupported_delivered_hls_audio_retries_auto_quality_after_cleanup(self):
        result=self.native_best_start(hd_fallback=True,hd_audio_rejected=True)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        starts=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(['original','1080p'],[b['quality_preference'] for b in starts])
        self.assertEqual(['f2','f2'],[b['file_id'] for b in starts])
        self.assertEqual(1,sum(r['method']=='DELETE' for r in result['requests']))

    def test_unsupported_delivered_hls_audio_preserves_explicit_quality(self):
        result=self.native_best_start(hd_fallback=True,hd_audio_rejected=True,explicit=True,quality_explicit=True)
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
        starts=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(['original'],[b['quality_preference'] for b in starts])
        self.assertEqual(1,sum(r['method']=='DELETE' for r in result['requests']))

    def test_refused_hevc_hls_never_lowers_explicit_original_quality(self):
        result=self.native_best_start(hd_fallback=True,hd_unsupported=True,explicit=True,quality_explicit=True)
        self.assertFalse(result['outcome']['ok'])
        starts=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(['original'],[b['quality_preference'] for b in starts])

    def test_automatic_same_file_quality_ladder_exhausts_once_at_480p(self):
        result=self.native_best_start(hd_fallback=True,hd_all_terminal=True)
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('adaptation_exhausted',result['outcome'].get('reason'))
        starts=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(['original','1080p','720p','480p'],[b['quality_preference'] for b in starts])
        self.assertTrue(all(b['file_id']=='f2' for b in starts))
        self.assertEqual(12,len(result['requests']))

    def test_quality_retry_failure_retains_sanitized_start_attempts(self):
        result = self.native_best_start(hd_fallback=True, hd_all_terminal=True)
        attempts = result['outcome']['startAttempts']
        self.assertEqual(['original', '1080p', '720p', '480p'],
                         [a['request']['quality'] for a in attempts])
        self.assertEqual(['adaptation_unavailable'] * 4, [a['outcome'] for a in attempts])
        self.assertTrue(all(a['httpStatus'] == 200 for a in attempts))
        self.assertNotIn('startAttempts', json.dumps(result['requests']))
        for private in ('https:', 'sess-1', 'f2', 'No supported route.'):
            self.assertNotIn(private, json.dumps(attempts))

    def test_automatic_original_uses_hd_sdr_as_last_resort_when_no_native_alternative_remains(self):
        for oversized in (False,True):
            result=self.native_best_start(hd_fallback=True,hd_oversize=oversized)
            self.assertTrue(result['outcome']['ok'],result['outcome'])
            starts=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
            self.assertEqual(['original','1080p'],[b['quality_preference'] for b in starts])
            self.assertEqual(['f2','f2'],[b['file_id'] for b in starts])
            self.assertEqual(int(oversized),sum(r['method']=='DELETE' for r in result['requests']))

    def test_terminal_lossless_route_retries_unambiguous_native_audio_before_another_file(self):
        result = self.native_best_start(audio_terminal=True)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        starts = [json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(['f2','f2'],[body['file_id'] for body in starts])
        self.assertEqual(1,starts[-1]['audio_track_index'])

    def test_auto_tries_remaining_native_version_when_recipe_is_unavailable(self):
        result = self.native_best_start(missing_recipe=True)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        starts = [json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(['f2','f1'],[body['file_id'] for body in starts])
        self.assertEqual('f1',result['outcome']['plan']['versionId'])

    def test_startup_replans_compatible_audio_on_the_same_lease(self):
        result = self.native_best_start(compatible_audio=True)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST','GET','POST'],[r['method'] for r in result['requests']])
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual(1,body['selected_tracks']['audio']['index'])
        self.assertEqual('file:f2:audio:1',result['outcome']['plan']['siloPlayback']['selectedTracks']['audio']['id'])

    def test_unsupported_server_audio_uses_matching_main_surround_lane(self):
        tracks = [{"id":"0","index":0,"codec":"truehd","channels":8,"language":"eng","title":"Main"},
                  {"id":"1","index":1,"codec":"aac","channels":2,"language":"eng","title":"Main"},
                  {"id":"2","index":2,"codec":"eac3","channels":6,"language":"eng","title":"Main"},
                  {"id":"3","index":3,"codec":"eac3","channels":6,"language":"fra","title":"Main"},
                  {"id":"4","index":4,"codec":"eac3","channels":6,"language":"eng","title":"Commentary"}]
        context = {"deliveries":{"hls":{"enabled":True,"supported_on_device":True,
                   "features":["native_hls_playback_v1","native_hls_separate_audio_v1"]}}}
        value = self.worker('RunCompatibleAudio',[{"audioTracks":tracks},{"index":0},context])
        self.assertEqual(2,value['index'])
        self.assertIsNone(self.worker('RunCompatibleAudio',[{"audioTracks":tracks},{"index":2},context]))
        tracks[2]['channels'] = 8
        value = self.worker('RunCompatibleAudio',[{"audioTracks":tracks},{"index":0},context])
        self.assertEqual(1,value['index'])
        tracks[0]['language'] = 'jpn'
        self.assertIsNone(self.worker('RunCompatibleAudio',[{"audioTracks":tracks},{"index":0},context]))
        tracks[0].update(language='eng',hearingImpaired=True)
        self.assertIsNone(self.worker('RunCompatibleAudio',[{"audioTracks":tracks},{"index":0},context]))
        tracks[2].update(channels=6,hearingImpaired=True)
        self.assertEqual(2,self.worker('RunCompatibleAudio',[{"audioTracks":tracks},{"index":0},context])['index'])

    def test_server_adaptable_dv7_can_rank_without_claiming_native_profile7(self):
        version = {"container":"mkv","videoCodec":"hevc","audioCodec":"truehd","hdr":True,"bitrateKbps":40000,
                   "videoTracks":[{"codec":"hevc","profile":"Main 10","level":153,"width":3840,"height":2160,
                       "bit_depth":10,"frame_rate":"24000/1001","interlaced":False,"video_range":"dolbyvision",
                       "dv_profile":7,"dv_level":6,"dv_config_present":True,"dv_bl_present":True,
                       "dv_rpu_present":True,"dv_el_present":True,"dv_bl_compat_id_present":True,"dv_bl_compat_id":6}]}
        context = {"deliveries":{"hls":{"enabled":True,"supported_on_device":True,
                   "features":["native_hls_playback_v1","native_hls_separate_audio_v1"],"audio_decode_codecs":["aac"]}}}
        caps = {"hdr_details":{"hdr10":True,"dolby_vision_profiles":[]}}
        result = self.worker("RunVersionProof", [version,caps,context])
        self.assertEqual(3840*2160,result['pixels'])
        self.assertEqual(1,result['hdrScore'])
        self.assertIsNone(self.worker("RunVersionProof",[version,caps,{}]))
        version['videoTracks'][0]['dv_bl_compat_id'] = 0
        self.assertIsNone(self.worker("RunVersionProof",[version,caps,context]))

    def test_auto_selects_proven_plain_4k_sdr_and_hdr10_before_original_start(self):
        for hdr in [False,True]:
            result=self.native_best_start(hdr=hdr)
            self.assertTrue(result["outcome"]["ok"],result["outcome"])
            body=json.loads(result["requests"][2]["body"])
            self.assertEqual(body["file_id"],"f2")
            self.assertEqual(body["quality_preference"],"original")

    def test_auto_pins_proven_anchor_and_rejects_server_substitution(self):
        result=self.native_best_start()
        body=json.loads(result["requests"][2]["body"])
        self.assertFalse(body["allow_alternate_versions"])
        self.assertEqual(result["outcome"]["plan"]["siloPlayback"]["fileId"],"f2")
        rejected=self.native_best_start(server_alternate=True)
        self.assertFalse(rejected["outcome"]["ok"])
        self.assertEqual(rejected["requests"][-1]["method"],"DELETE")

    def test_initial_source_track_selectors_pin_the_ui_file(self):
        for field in ["audioTrackId","audioTrackIndex","subtitleTrackId","subtitleTrackIndex"]:
            result=self.native_best_start(track_selector=field,native_default_second=True)
            self.assertTrue(result["outcome"]["ok"],result["outcome"])
            body=json.loads(result["requests"][2]["body"])
            self.assertEqual(body["file_id"],"f1")
            self.assertFalse(body["allow_alternate_versions"])

    def test_source_upgrade_requires_avc_ceiling_no_el_and_known_supported_fps_resume(self):
        for options in [{"avc4k":True},{"el_only":True,"hdr":True},{"high_fps":True},{"unknown_fps":True},{"short_resume":True}]:
            with self.subTest(options=options):
                result=self.native_best_start(**options)
                self.assertTrue(result["outcome"]["ok"],result["outcome"])
                self.assertEqual(json.loads(result["requests"][2]["body"])["file_id"],"f1")

    def test_auto_retains_default_for_dv7_truehd_unknown_ties_and_explicit(self):
        for options in [{"incompatible":True},{"dv":True},{"lossless":True},{"unknown":True},{"all_unknown":True},{"equal":True},{"explicit":True},{"output_mode":"1080p"},{"output_mode":""},{"reject_main10":True},{"inconsistent_hdr":True}]:
            result=self.native_best_start(**options)
            self.assertTrue(result["outcome"]["ok"],result["outcome"])
            self.assertEqual(json.loads(result["requests"][2]["body"])["file_id"],"f1")

    def test_fresh_auto_default_survives_vanished_ui_anchor_but_explicit_rejects(self):
        raw=json.loads((FIXTURES / "catalog_item_detail_movie.json").read_text())
        raw["content_id"]="fixture-item"
        helper=self.worker("DecodeSiloResponse",["detail",json.dumps(raw),{"sourceId":self.session()["sourceId"]}])["data"]
        helper["item"]["sourceId"]=self.session()["sourceId"]
        raw["versions"][0]["file_id"]="f2"
        raw["playback_variants"]=[{"variant_id":"native","part_count":1,"parts":[{"part_index":1,"default_file_id":"f2","versions":raw["versions"]}]}]
        capability=json.loads((FIXTURES / "playback_capabilities.json").read_text());capability["installation_id"]="server-install"
        decision=json.loads((FIXTURES / "playback_decision_plan.json").read_text())
        decision["playback_plan"].update(requested_media_file_id="f2",effective_media_file_id="f2")
        decision["playback_plan"]["source"]["media_file_id"]="f2"
        responses=[{"statusCode":200,"body":json.dumps(x)} for x in [raw,capability,decision]]
        params={"itemId":"fixture-item","fileId":"f1","detail":helper,"autoVersion":True}
        result=self.worker("RunSiloPlaybackStart",[self.session(),params,responses,False])
        self.assertTrue(result["outcome"]["ok"],result["outcome"])
        self.assertEqual(json.loads(result["requests"][2]["body"])["file_id"],"f2")
        params["autoVersion"]=False
        result=self.worker("RunSiloPlaybackStart",[self.session(),params,responses,False])
        self.assertFalse(result["outcome"]["ok"])
        self.assertEqual(len(result["requests"]),1)

    def test_auto_native_default_and_effective_file_survive_worker(self):
        raw=json.loads((FIXTURES / "catalog_item_detail_movie.json").read_text())
        raw["content_id"]="fixture-item"
        version=raw["versions"][0]
        version["file_id"]="f1"
        other={**version,"file_id":"f2","resolution":"2160p"}
        raw["versions"]=[version,other]
        raw["playback_variants"]=[{"variant_id":"native","part_count":1,"parts":[{"part_index":1,"default_file_id":"f2","versions":[version,other]}]}]
        detail=self.worker("DecodeSiloResponse",["detail",json.dumps(raw),{"sourceId":self.session()["sourceId"]}])["data"]
        detail["item"]["itemId"]="fixture-item"
        detail["item"]["sourceId"]=self.session()["sourceId"]
        for row in detail["versions"]: row["itemId"]="fixture-item"
        decision=json.loads((FIXTURES / "playback_decision_plan.json").read_text())
        plan=decision["playback_plan"]
        plan["requested_media_file_id"]="f2"
        plan["effective_media_file_id"]="f2"
        plan["source"]["media_file_id"]="f2"
        capability=json.loads((FIXTURES / "playback_capabilities.json").read_text())
        capability["installation_id"]="server-install"
        responses=[{"statusCode":200,"body":json.dumps(x)} for x in [raw,capability,decision]]
        result=self.worker("RunSiloPlaybackStart",[self.session(),{"itemId":"fixture-item","fileId":"f1","detail":detail,"autoVersion":True,"qualityPreference":"original","qualityExplicit":False},responses,False])
        self.assertTrue(result["outcome"]["ok"],result["outcome"])
        start=json.loads(result["requests"][2]["body"])
        self.assertEqual(start["file_id"],"f2")
        self.assertFalse(start["allow_alternate_versions"])
        self.assertEqual(start["quality_preference"],"1080p")
        self.assertEqual(result["outcome"]["plan"]["versionId"],"f2")
        accepted=result["outcome"]["plan"]
        self.assertEqual(accepted["siloPlayback"]["fileId"],"f2")
        self.assertFalse(accepted["siloPlayback"]["allowAlternateVersions"])
        self.assertEqual(accepted["sessionId"],"sess-1")
        self.assertEqual(accepted["installationId"],"server-install")
        self.assertEqual(result["outcome"]["data"]["effectiveMarkers"],detail["versions"][1]["markers"])

    def test_display_evidence_uses_live_validated_exact_or_unknown_contract(self):
        known=self.worker("RunSiloCapabilities",[False])
        unknown=self.worker("RunSiloCapabilities",[True])
        self.assertEqual(known["context"]["output"]["display"]["hdr_evidence"],"exact")
        self.assertEqual(unknown["context"]["output"]["display"]["hdr_evidence"],"unknown")

    def test_partial_hdr10_facts_do_not_require_unrelated_display_flags(self):
        result=self.worker("RunPartialHdrCapabilities",[])
        self.assertTrue(result["hdr"])
        self.assertEqual(result["hdr_details"],{"hdr10":True,"hdr10_plus":False,"hlg":False,"dolby_vision_profiles":[]})

    def test_native_output_and_profile_queries_bound_4k_hdr_claims(self):
        supported=self.worker("RunSilo4KCapabilities",[False])
        self.assertEqual(supported["max_resolution"],"2160p")
        self.assertTrue(supported["hdr_details"]["hdr10"])
        failed=self.worker("RunSilo4KCapabilities",[True])
        self.assertFalse(failed["hdr"])
        self.assertFalse(failed["hdr_details"]["hdr10"])

    def test_generic_av1_vp9_support_does_not_claim_original_container_routes(self):
        result=self.worker("RunSiloCapabilities",[False])
        self.assertEqual(result["caps"]["codecs_video"],["h264","hevc"])
        for delivery in result["context"]["deliveries"].values():
            self.assertNotIn("av1",delivery["video_codecs"])
            self.assertNotIn("vp9",delivery["video_codecs"])

    def test_hevc_profiles_are_probed_without_invented_hardware_claims(self):
        result=self.worker("RunSiloCapabilities",[False])
        self.assertIn({"codec":"hevc","profile":"main","level":"5.1"},result["videoQueries"])
        self.assertIn({"codec":"hevc","profile":"main 10","level":"5.1"},result["videoQueries"])
        self.assertNotIn("video_decode",result["caps"])
        self.assertEqual(result["caps"]["codecs_video_hardware"],[])

    def test_unknown_display_does_not_become_attested_hdr(self):
        result=self.worker("RunSiloCapabilities",[True])
        self.assertFalse(result["caps"]["hdr"])
        self.assertNotIn("hdr_details",result["caps"])
        self.assertEqual(result["context"]["output"]["display"],{"hdr_evidence":"unknown"})
        for query in result["queries"]:
            self.assertEqual(set(query),{"codec","container","passthru"})
            self.assertIn(query["passthru"],[0,1])

    def test_audio_queries_distinguish_decode_passthrough_and_channels(self):
        result=self.run_start()
        body=json.loads(result["requests"][1]["body"])
        caps=body["client_capabilities"]; context=body["client_playback_context"]
        self.assertEqual(caps["codecs_audio"],["aac"])
        self.assertNotIn("audio_passthrough",caps)
        self.assertNotIn("audio_passthrough",context["output"])
        self.assertNotIn("hls",caps["containers"])
        self.assertFalse(context["deliveries"]["hls"]["enabled"])
        self.assertTrue(caps["hdr"])
        for delivery in context["deliveries"].values():
            self.assertNotIn("max_channels",delivery)
            if delivery["enabled"]: self.assertEqual(delivery["audio_passthrough_codecs"],["eac3"])
            self.assertEqual(delivery["hdr_details"],caps["hdr_details"])
        self.assertEqual(context["output"]["hdr_details"],caps["hdr_details"])
        self.assertEqual(caps["hdr_details"]["dolby_vision_profiles"],[])

    def test_start_forwards_quality_bandwidth_and_selected_tracks_without_wire_purpose(self):
        for quality in ("original", "4k", "1080p_high", "1080p", "720p", "480p"):
            with self.subTest(quality=quality):
                result = self.run_start(params={"itemId": "fixture-item", "fileId": "f1",
                                               "qualityPreference": quality, "bandwidthCapKbps": 1200,
                                               "audioTrackId": "a1", "audioTrackIndex": 0,
                                               "subtitleTrackId": "s1", "subtitleTrackIndex": 2,
                                               "purpose": "PREVIEW"})
                self.assertTrue(result["outcome"]["ok"])
                self.assertEqual(2, len(result["requests"]))
                body = json.loads(result["requests"][1]["body"])
                self.assertEqual(quality, body["quality_preference"])
                self.assertIn("bandwidth_cap_kbps", body)
                self.assertEqual(1200, body["bandwidth_cap_kbps"])
                self.assertEqual(("a1", 0, "s1", 2), (body["audio_track_id"], body["audio_track_index"],
                                                    body["subtitle_track_id"], body["subtitle_track_index"]))
                self.assertNotIn("purpose", body)
                self.assertEqual("server", body["progress_persistence"])

    def test_start_keeps_foreground_quality_and_no_bandwidth_cap_by_default(self):
        result = self.run_start()
        self.assertTrue(result["outcome"]["ok"])
        body = json.loads(result["requests"][1]["body"])
        self.assertEqual("original", body["quality_preference"])
        self.assertNotIn("bandwidth_cap_kbps", body)

    def test_invalid_quality_or_bandwidth_is_rejected_before_network(self):
        cases = [{"qualityPreference": value} for value in ("preview", "720P", "", 720, None)]
        cases += [{"bandwidthCapKbps": value} for value in (0, 200001, 1.5, "1200", True, None)]
        for limits in cases:
            with self.subTest(limits=limits):
                result = self.run_start(params={"itemId": "fixture-item", "fileId": "f1", **limits})
                self.assertEqual({"ok": False, "errorCode": "invalid_request"}, result["outcome"])
                self.assertEqual([], result["requests"])

    def test_allocated_malformed_plan_is_abandoned_without_final_progress(self):
        for plan in ({}, {"stream": []}, {"stream": {}, "timeline": []}):
            with self.subTest(plan=plan):
                self.assert_abandoned(self.run_start(decision={"protocol_version": 3, "outcome": "plan",
                                                              "session_id": "sess-1", "playback_plan": plan}),
                                      "invalid_response", cleanup_closed=True)

    def test_allocated_unsupported_routes_are_abandoned(self):
        cases = [("protocol", "rtsp", "unsupported_stream"),
                 ("header_refresh", "periodic", "unsupported_header_refresh"),
                 ("url", "https://private@example.test/stream", "invalid_stream_url")]
        for field, value, code in cases:
            with self.subTest(field=field):
                decision = json.loads((FIXTURES / "playback_decision_plan.json").read_text())
                decision["playback_plan"]["stream"][field] = value
                self.assert_abandoned(self.run_start(decision=decision), code, cleanup_closed=True)

    def test_allocated_unsupported_protocol_or_outcome_is_abandoned(self):
        for patch, code in (({"protocol_version": 2}, "unsupported_protocol"),
                            ({"outcome": "unexpected"}, "invalid_response")):
            with self.subTest(patch=patch):
                decision = json.loads((FIXTURES / "playback_decision_plan.json").read_text())
                decision.update(patch)
                self.assert_abandoned(self.run_start(decision=decision), code, cleanup_closed=True)

    def test_decoder_rejection_after_a_valid_plan_still_abandons_session(self):
        decision = json.loads((FIXTURES / "playback_decision_plan.json").read_text())
        decision.update({"status": 503, "type": "https://private.example/problem",
                         "title": "private-title", "detail": "private-token"})
        self.assert_abandoned(self.run_start(decision=decision), "silo_problem")

    def test_malformed_protocol_and_outcome_types_cannot_skip_session_cleanup(self):
        for field in ("protocol_version", "outcome"):
            for value in ({}, []):
                with self.subTest(field=field, value=value):
                    decision = json.loads((FIXTURES / "playback_decision_plan.json").read_text())
                    decision[field] = value
                    self.assert_abandoned(self.run_start(decision=decision), "invalid_response")

    def test_catchable_cleanup_failure_retains_retry_plan_without_exception_text(self):
        result = self.run_start(decision={"protocol_version": 3, "outcome": "plan",
                                          "session_id": "sess-1", "playback_plan": {}}, cleanup_raises=True)
        self.assertIs(result["outcome"]["cleanupLeaseKnown"], True)
        for fact in ("cleanupLeaseKnown", "cleanupLeaseClosed"):
            self.assertNotIn(fact, json.dumps(result["requests"]))
        self.assertEqual({"ok": False, "errorCode": "invalid_response", "cleanupLeaseKnown": True, "plan": {
            "sessionId": "sess-1", "installationId": "server-install",
            "stopId": "10000000-0000-4000-8000-000000000001", "persistProgress": False}}, self.assert_safe_start_response_facts(result))

    def test_success_data_uses_the_safe_nested_session_identity(self):
        decision = json.loads((FIXTURES / "playback_decision_plan.json").read_text())
        decision["session_id"] = "https://private.example/?token=private-token"
        decision["playback_plan"]["session_id"] = "sess-1"
        result = self.run_start(decision=decision)
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual("sess-1", result["outcome"]["data"]["sessionId"])
        self.assertNotIn("private", json.dumps(result["outcome"]["data"]))

    def test_session_revision_change_abandons_captured_allocation(self):
        self.assert_abandoned(self.run_start(change_revision=True), "session_changed")

    def test_changed_session_cleanup_failure_keeps_captured_retry_identity(self):
        result = self.run_start(change_revision=True, cleanup_status=503)
        self.assertEqual({"ok": False, "errorCode": "session_changed", "plan": {
            "sessionId": "sess-1", "installationId": "server-install",
            "stopId": "10000000-0000-4000-8000-000000000001", "persistProgress": False}}, result["outcome"])

    def test_terminal_decision_with_allocated_session_is_abandoned(self):
        decision = json.loads((FIXTURES / "playback_decision_terminal.json").read_text())
        decision["session_id"] = "sess-1"
        self.assert_abandoned(self.run_start(decision=decision), "playback_terminal", cleanup_closed=True)

    def test_final_prepare_error_carries_attempt_receipt_for_optional_report(self):
        decision={'protocol_version':3,'outcome':'terminal',
                  'terminal':{'reason':'hdr_transcode_unsupported','retryable':False}}
        value=self.run_start(decision=decision)['outcome']
        self.assertEqual('hdr_transcode_unsupported',value.get('reason'))
        self.assertEqual('start',value.get('stage'))
        self.assertEqual({'installationId':'server-install',
                          'playbackAttemptId':'10000000-0000-4000-8000-000000000001'},value.get('report'))
        self.assertNotIn('synthetic-access',json.dumps(value))

    def test_playable_response_without_safe_session_identity_is_rejected(self):
        for session_id in (None, "https://private.example/?token=private-token"):
            with self.subTest(session_id=session_id):
                decision = json.loads((FIXTURES / "playback_decision_plan.json").read_text())
                decision["session_id"] = session_id
                result = self.run_start(decision=decision)
                self.assert_public_error(result)
                self.assertEqual(2, len(result["requests"]))

    def test_unsafe_installation_identity_is_rejected_before_allocation(self):
        for installation_id in ("https://private.example/token", "private\nheader", "s" * 257):
            with self.subTest(installation_id=installation_id):
                result = self.run_start(installation_id=installation_id)
                self.assert_public_error(result, "invalid_capabilities")
                self.assertEqual(1, len(result["requests"]))

    def test_failed_or_unverified_abandon_exposes_only_retry_identity_and_stable_stop_id(self):
        for status, body in ((503, '{"detail":"private-token"}'), (200, "{}"),
                             (204, ""), (200, '{"outcome":"accepted"}')):
            with self.subTest(status=status, body=body):
                result = self.run_start(decision={"protocol_version": 3, "outcome": "plan",
                                                  "session_id": "sess/1", "playback_plan": {}},
                                        cleanup_status=status, cleanup_body=body)
                expected = {"sessionId": "sess/1", "installationId": "server-install",
                            "stopId": "10000000-0000-4000-8000-000000000001", "persistProgress": False}
                self.assertIs(result["outcome"]["cleanupLeaseKnown"], True)
                for fact in ("cleanupLeaseKnown", "cleanupLeaseClosed"):
                    self.assertNotIn(fact, json.dumps(result["requests"]))
                self.assertEqual({"ok": False, "errorCode": "invalid_response", "cleanupLeaseKnown": True, "plan": expected},
                                 self.assert_safe_start_response_facts(result))
                self.assertEqual("/api/v2/playback/sess%2F1", urlsplit(result["requests"][2]["url"]).path)
                retry = self.run_event("playback_stop", params=result["outcome"]["plan"])
                self.assertTrue(retry["outcome"]["ok"])
                self.assertEqual(json.loads(result["requests"][2]["body"]),
                                 json.loads(retry["requests"][0]["body"]))
                for private in ("private-token", "https://", "headers", "synthetic", "position", "sequence"):
                    self.assertNotIn(private, json.dumps(result["outcome"]))

    def test_nested_session_identity_can_release_rejected_plan_without_top_level_identity(self):
        result = self.run_start(decision={"protocol_version": 3, "outcome": "plan",
                                          "playback_plan": {"session_id": "sess-1"}})
        self.assert_abandoned(result, "invalid_response", cleanup_closed=True)

    def test_untrusted_session_identity_never_enters_a_stop_or_retry_plan(self):
        for session_id in (None, 7, "", "https://private.example/?token=private-token",
                           "private\nheader", "s" * 257):
            with self.subTest(session_id=session_id):
                result = self.run_start(decision={"protocol_version": 3, "outcome": "plan",
                                                  "session_id": session_id, "playback_plan": {}})
                self.assert_public_error(result)
                self.assertEqual(2, len(result["requests"]))

    def test_nonobject_start_response_returns_public_error_without_attempting_cleanup(self):
        for body in ("{", "null", "[]", '"private-token"'):
            with self.subTest(body=body):
                result = self.run_start(decision=body)
                self.assert_public_error(result)
                self.assertEqual(2, len(result["requests"]))

    def assert_safe_start_response_facts(self, result):
        # Validate the optional presentation-only addition before comparing the
        # original exact error/cleanup outcome. Never allow arbitrary nested data.
        outcome = dict(result['outcome'])
        attempts = outcome.pop('startAttempts', [])
        self.assertLessEqual(len(attempts), 8)
        for attempt in attempts:
            self.assertEqual({'request', 'httpStatus', 'outcome', 'originalReason'}, set(attempt))
            self.assert_safe_start_response_facts({'outcome': {'startRequestFacts': attempt['request']}, 'requests': []})
        request = outcome.pop('startRequestFacts', None)
        if request is not None:
            self.assertLessEqual(set(request), {'quality','selection','videoCodec','audioCodec','hdr10','dolbyVision','mpegts','separateAudio','dv7To81','hevcAdmitted','hlsEnabled','hlsSupported','originalEnabled','originalSupported','width','height','dvProfile','dvBaseCompatibility','hlsHevcAdmitted','copyMpegts'})
            enums = {
                'quality': {'unknown','auto','original','2160p','1080p','720p','480p'},
                'selection': {'auto','manual'},
                'videoCodec': {'unknown','h264','hevc','av1','vp9','mpeg2','mpeg4'},
                'audioCodec': {'unknown','aac','ac3','eac3','truehd','dts','flac','opus','mp3','pcm'},
                'hdr10': {'unknown','yes','no'}, 'dolbyVision': {'unknown','yes','no'},
            }
            for field, allowed in enums.items():
                self.assertIs(type(request[field]), str)
                self.assertIn(request[field], allowed)
            for field in ('copyMpegts','mpegts','separateAudio','dv7To81','hevcAdmitted','hlsEnabled','hlsSupported','originalEnabled','originalSupported'):
                self.assertIs(type(request[field]), bool)
            if 'hlsHevcAdmitted' in request:
                self.assertIs(type(request['hlsHevcAdmitted']), bool)
            for field in ('width','height','dvProfile','dvBaseCompatibility'):
                if field in request:
                    self.assertIs(type(request[field]), int)
                    self.assertGreaterEqual(request[field], 0)
                    self.assertLessEqual(request[field], 15 if field.startswith('dv') else 16384)
            self.assertNotIn('startRequestFacts', json.dumps(result['requests']))
        if 'startResponseFacts' not in outcome:
            return outcome
        facts = outcome.pop('startResponseFacts')
        categories = {
            'protocol': {'v3', 'other', 'missing', 'null', 'invalid'},
            'outcome': {'plan', 'playable', 'terminal', 'adaptation_unavailable',
                        'other', 'missing', 'null', 'invalid'},
            'sessionId': {'missing', 'null', 'empty', 'valid', 'invalid'},
            'planSessionId': {'missing', 'null', 'empty', 'valid', 'invalid', 'unavailable'},
        }
        booleans = {'playbackPlanPresent', 'playbackPlanObject', 'terminalShapeValid'}
        self.assertIs(type(facts), dict)
        self.assertEqual({'httpStatus', *categories, *booleans}, set(facts))
        status = facts['httpStatus']
        self.assertTrue(status == 'unknown' if type(status) is str else
                        type(status) in (int, float) and 100 <= status <= 599 and status == int(status))
        for field, allowed in categories.items():
            self.assertIs(type(facts[field]), str)
            self.assertIn(facts[field], allowed)
        for field in booleans:
            self.assertIs(type(facts[field]), bool)
        self.assertNotIn('startResponseFacts', json.dumps(result['requests']))
        return outcome

    def assert_public_error(self, result, code="invalid_response", *, cleanup_closed=False):
        outcome=self.assert_safe_start_response_facts(result)
        self.assertEqual({'ok':False,'errorCode':code},{k:outcome[k] for k in ('ok','errorCode')})
        allowed = {'ok','errorCode','stage','reason','report'}
        if cleanup_closed:
            self.assertIs(outcome.get('cleanupLeaseClosed'), True)
            self.assertNotIn('plan', outcome)
            self.assertNotIn('cleanupLeaseKnown', outcome)
            allowed.add('cleanupLeaseClosed')
        self.assertLessEqual(set(outcome), allowed)
        for fact in ('cleanupLeaseKnown','cleanupLeaseClosed'):
            self.assertNotIn(fact, json.dumps(result['requests']))
        if code in ('unsupported_protocol','unsupported_stream','playback_terminal'):
            self.assertEqual('start',outcome.get('stage'))
        if 'reason' in outcome:self.assertEqual('no_playable_source',outcome['reason'])
        if 'report' in outcome:
            self.assertEqual({'installationId':'server-install',
                              'playbackAttemptId':'10000000-0000-4000-8000-000000000001'},outcome['report'])
        serialized = json.dumps(result["outcome"])
        for private in ("private-token", "private-title", "https://private", "synthetic-access", "body", "headers"):
            self.assertNotIn(private, serialized)

    def test_accepted_fixture_acknowledges_progress_through_actual_worker(self):
        result = self.run_event()
        self.assertEqual({"ok": True, "data": {"state": "saved"}}, result["outcome"])
        self.assertEqual([5000], result["timeouts"])
        request = result["requests"][0]
        self.assertEqual("POST", request["method"])
        self.assertEqual("/api/v2/playback/sess%2F1/progress", urlsplit(request["url"]).path)
        self.assertEqual({"installation_id": "fixture-installation", "position": 12.5, "sequence": 2,
                          "is_paused": False}, json.loads(request["body"]))
        self.assertNotIn("synthetic", json.dumps(result["outcome"]))

    def test_live_applied_receipts_acknowledge_progress_and_stop(self):
        for action in ("playback_progress", "playback_stop"):
            with self.subTest(action=action):
                result = self.run_event(action, body='{"outcome":"applied"}')
                self.assertEqual({"ok": True, "data": {"state": "saved"}}, result["outcome"])

    def test_rejected_plan_cleanup_also_uses_a_canonical_stop_uuid(self):
        cleanup = self.worker("TaskSiloCleanupPlan", [{"session_id": "sess-1"}, "server-install"], real_ids=True)
        self.assertRegex(cleanup["stopId"], r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
        self.assertIs(cleanup["persistProgress"], False)

    def test_generated_stop_id_is_a_canonical_uuid(self):
        params = {"sessionId": "sess/1", "installationId": "fixture-installation"}
        result = self.run_event("playback_stop", params=params)
        self.assertTrue(result["outcome"]["ok"])
        self.assertEqual("10000000-0000-4000-8000-000000000001",
                         json.loads(result["requests"][0]["body"])["stop_id"])

    def test_start_preserves_original_mkv_but_does_not_offer_generated_progressive(self):
        result = self.run_start()
        self.assertTrue(result["outcome"]["ok"])
        context = json.loads(result["requests"][1]["body"])["client_playback_context"]
        self.assertTrue(context["deliveries"]["original_http"]["enabled"])
        self.assertIn("mkv", context["deliveries"]["original_http"]["containers"])
        self.assertFalse(context["deliveries"]["progressive"]["enabled"])
        self.assertFalse(context["deliveries"]["progressive"]["supported_on_device"])

    def test_updated_fixture_is_the_existing_supported_progress_outcome(self):
        result = self.run_event(body=(FIXTURES / "playback_progress_updated.json").read_text())
        self.assertEqual({"ok": True, "data": {"state": "saved"}}, result["outcome"])

    def test_stopped_fixture_acknowledges_stop_without_exposing_receipt(self):
        result = self.run_event("playback_stop")
        self.assertEqual({"ok": True, "data": {"state": "saved"}}, result["outcome"])
        self.assertEqual("DELETE", result["requests"][0]["method"])
        self.assertEqual("10000000-0000-4000-8000-000000000001", json.loads(result["requests"][0]["body"])["stop_id"])
        self.assertNotIn("stop_id", result["outcome"]["data"])

    def test_durable_replayed_receipt_acknowledges_only_http_200_stop(self):
        # cce24de StopPlaybackV2 replays the original durable receipt for any
        # later stop ID; its accepted sample need not be this cleanup's position.
        receipt = json.loads((FIXTURES / "playback_stop_replayed.json").read_text())
        params = {"sessionId": "sess/1", "installationId": "fixture-installation",
                  "stopId": "10000000-0000-4000-8000-000000000001",
                  "persistProgress": False, "positionMs": 300000, "sequence": 9}
        for action, status, outcome, saved in (
                ("playback_stop", 200, "replayed", True),
                ("playback_progress", 200, "replayed", False),
                ("playback_stop", 204, "replayed", False),
                ("playback_stop", 200, "unknown", False)):
            with self.subTest(action=action, status=status, outcome=outcome):
                body = json.dumps({**receipt, "outcome": outcome})
                event_params = params if action == "playback_stop" else None
                result = self.run_event(action, body, status=status, params=event_params)
                self.assertEqual(1, len(result["requests"]))
                if saved:
                    self.assertEqual({"ok": True, "data": {"state": "saved"}}, result["outcome"])
                    request = result["requests"][0]
                    self.assertEqual("DELETE", request["method"])
                    self.assertEqual("/api/v2/playback/sess%2F1", urlsplit(request["url"]).path)
                    self.assertEqual({"installation_id": "fixture-installation",
                                      "stop_id": params["stopId"]}, json.loads(request["body"]))
                    self.assertEqual([5000], result["timeouts"])
                else:
                    self.assert_public_error(result)

    def test_unlanded_resume_closes_session_without_sending_a_position(self):
        params = {"itemId": "fixture-item", "sessionId": "sess/1",
                  "installationId": "fixture-installation", "positionMs": 0,
                  "durationMs": 7200000, "sequence": 2, "isPaused": False,
                  "state": "stopped", "stopId": "10000000-0000-4000-8000-000000000001", "persistProgress": False}
        result = self.run_event("playback_stop", params=params)
        self.assertTrue(result["outcome"]["ok"])
        body = json.loads(result["requests"][0]["body"])
        self.assertEqual({"installation_id": "fixture-installation", "stop_id": "10000000-0000-4000-8000-000000000001"}, body)

    def test_success_status_cannot_acknowledge_empty_or_malformed_receipt(self):
        for action in ("playback_progress", "playback_stop"):
            for body in ("", " ", "private-token", "{", "[]", "null", "{}", '{"outcome":null}', '{"outcome":42}'):
                with self.subTest(action=action, body=body):
                    self.assert_public_error(self.run_event(action, body))

    def test_unknown_refused_and_wrong_action_outcomes_are_not_saved(self):
        cases = (("playback_progress", "stopped"), ("playback_stop", "accepted"),
                 ("playback_stop", "updated"), ("playback_progress", "refused"),
                 ("playback_stop", "already_stopped"), ("playback_stop", "duplicate"),
                 ("playback_progress", "https://private.example/?token=private-token"))
        for action, outcome in cases:
            with self.subTest(action=action, outcome=outcome):
                body = json.dumps({"outcome": outcome, "detail": "private-token", "title": "private-title"})
                self.assert_public_error(self.run_event(action, body))

    def test_undocumented_204_and_other_success_statuses_do_not_acknowledge(self):
        for action in ("playback_progress", "playback_stop"):
            for status in (201, 202, 204, 206):
                with self.subTest(action=action, status=status):
                    body = "" if status == 204 else json.dumps({"outcome": "stopped" if action == "playback_stop" else "accepted"})
                    self.assert_public_error(self.run_event(action, body, status=status))

    def test_http_failures_keep_retryable_codes_without_receipt_text(self):
        for status, code in ((408, "network_timeout"), (429, "rate_limited"), (503, "server_error"),
                             (404, "not_found")):
            with self.subTest(status=status):
                body = json.dumps({"detail": "private-token", "outcome": "accepted"})
                self.assert_public_error(self.run_event(body=body, status=status), code)

    def test_problem_disguised_as_success_is_not_an_acknowledgment(self):
        body = json.dumps({"status": 503, "type": "https://private.example/problem",
                           "title": "private-title", "detail": "private-token", "outcome": "accepted"})
        self.assert_public_error(self.run_event(body=body))

    def test_automatic_audio_preserves_1080p_when_server_menu_has_only_original(self):
        class CaptureScenario(SiloPlaybackTaskTests):
            def worker(self, function, arguments, **kwargs):
                if function == 'RunSiloNativeBestStart':
                    return arguments
                return super().worker(function, arguments, **kwargs)
        arguments = CaptureScenario().native_best_start(compatible_audio=True)
        arguments[1].update(qualityPreference='1080p', qualityExplicit=True)
        for response in arguments[2]:
            raw = json.loads(response['body'])
            if 'playback_plan' in raw:
                raw['playback_plan']['available_qualities'] = [{'label': 'original', 'preserves_source': True}]
            response['body'] = json.dumps(raw)
        result = self.worker('RunSiloNativeBestStart', arguments)
        self.assertTrue(result['outcome']['ok'], result)
        posted = [json.loads(r['body']) for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual(['1080p', '1080p'], [body['quality_preference'] for body in posted])
        self.assertEqual('track_change', posted[-1]['operation'])
        self.assertEqual(1, posted[-1]['selected_tracks']['audio']['index'])
        self.assertEqual([{'label': 'original', 'preservesSource': True}],
                         result['outcome']['plan']['siloPlayback']['availableQualities'])




if __name__ == "__main__":
    unittest.main()
