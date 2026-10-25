"""Ordinary cold PlayerInit/PlayItem → Task → allocation callback → Video → Back.

The 0589 wire DTO is SOURCE-DERIVED, with synthetic identities, not a captured
Start response. Its shape follows apiv2/playback.go playbackDecision/playbackSource
and protocol_v3.go (string file IDs; strip2 claims; split1 null claims; V2 quality
projection). The separate 96-check host proof and 11906 native observation do not
turn this SDK/interpreter regression into native decoding or exact-response proof.

Separate interpreter invocations model the ApiTask thread boundary. Only SG node,
HTTP, device and HTTP-agent SDK boundaries are faked; ordinary policy is untouched.
PlayerInit is real; full Scene boot, registry and renderer are outside this test.
"""
import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tools.brightscript import run_brightscript
from tests import test_silo_compat_continuation as continuation
from tests.test_silo_playback_task import BOUNDARIES

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/silo/hdr10_split_0589_source_derived.json'

SDK = '''
sub FixtureObserveField(field as String, callback as String)
end sub
function FixtureDialog() as Object
 return {observeField:sub(field as String, callback as String)
 end sub}
end function
function FixtureTask() as Object
 return {observeField:sub(field as String, callback as String)
  GetGlobalAA().tasks.Push({job:ParseJson(FormatJson(m.job)),nativeControl:GetGlobalAA().video.control})
 end sub,unobserveField:sub(field as String)
 end sub}
end function
function FixtureAgent() as Object
 return {SetCertificatesFile:sub(path as String)
 end sub,AddHeader:sub(name as String,value as String)
 end sub}
end function
sub FixtureSetHttpAgent(agent as Object)
end sub
function FixtureEvent(payload as Object) as Object
 return {payload:payload,getData:function() as Object
  return m.payload
 end function}
end function
'''
DEVICE = BOUNDARIES.split('function FixtureSiloDevice()', 1)[1].split('function RunSiloCapabilities', 1)[0]
SDK += 'function FixtureSiloDevice()' + DEVICE.replace('return "1080p"', 'return "2160p60"').replace('major:"15",minor:"3",revision:"4",build:"2402"', 'major:"16",minor:"0",revision:"4",build:"834"')

class OrdinaryNativeHdr10Scene(unittest.TestCase):
    def task(self, job, *, refused=False):
        def fixture(wire, decision):
            decision.clear()
            decision.update(json.loads(FIXTURE.read_text()))
            if refused:
                decision['playback_plan']['transformations'][0]['recipe_version'] = '999'
        def http(responses):
            if job['action'] == 'playback_stop':
                responses[:] = [dict(statusCode=200, body='{"outcome":"stopped"}')]
        return continuation.CompatContinuation().job(enabled=False, scope=job, mutate=fixture,
            device={'DolbyVision:true':'DolbyVision:false'}, features=['native_hls_separate_audio_v1'], http=http)

    def scene(self, outcomes=(), close=False, stop_outcome=None, home_rows=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = []
            xml = ET.parse(ROOT / 'components/SiloUIScene.xml').getroot()
            for script in xml.findall('script'):
                name = script.get('uri').removeprefix('pkg:/')
                text = (ROOT / name).read_text()
                text = text.replace('CreateObject("roSGNode", "ApiTask")', 'FixtureTask()').replace('CreateObject("roDeviceInfo")', 'FixtureSiloDevice()').replace('CreateObject("roHttpAgent")', 'FixtureAgent()').replace('m.video.SetHttpAgent(agent)', 'FixtureSetHttpAgent(agent)')
                text = text.replace('CreateObject("roSGNode", "Dialog")', 'FixtureDialog()')
                # Interpreter has no active SG host; field registration is an SDK seam.
                text = re.sub(r'm\.[A-Za-z0-9_.]+\.observeField\(', 'FixtureObserveField(', text)
                text = text.replace('m.top.findNode("video").observeField(', 'FixtureObserveField(')
                path = root / Path(name).name
                path.write_text(text)
                files.append(path)
            sdk = root / 'SDK.brs'
            sdk.write_text(SDK)
            files.append(sdk)
            ids = sorted({n.get('id') for n in xml.iter() if n.get('id')})
            encode = lambda x: json.dumps(x).replace('"', '""')
            body = '''
 m.provider="silo":m.sourceId="silo:https://silo.example":m.profileId="fixture-owner":m.generation=7
 m.view="search":m.zone="":m.pending={}:m.cleanupTickets={}:m.requestId=0
 m.preferences={subtitles:"off",quality:"original"}:m.pillGroups={}:m.detailEpisodes=[]
 m.top=CreateObject("roSGNode","Group")
 m.top.AddFields({memoryPressure:0})
 for each name in ParseJson("''' + encode(ids) + '''")
  child=m.top.createChild("Group"):child.id=name:child.translation=[0,0]
  child.AddFields({control:"stop",fire:false,text:"",content:invalid,position:0.0,duration:7200.0,state:"buffering",globalCaptionMode:"Off",availableAudioTracks:[],availableSubtitleTracks:[],currentSubtitleTrack:"",playbackActionButtons:[],playbackActionButtonSelected:0,mute:false,itemSelected:0,rowItemFocused:[0,0],streamingSegment:{}})
 end for
 m.nav=m.top.createChild("Group"):m.manualFocus=m.top.createChild("Group")
 m.backdrop=m.top.createChild("Group"):m.backdropOld=m.top.createChild("Group")
 m.backdropTimer=m.top.findNode("backdropTimer"):m.backdropFade=m.top.findNode("backdropFade")
 m.toast=m.top.createChild("Label"):m.toastTimer={control:"stop"}
 GetGlobalAA().tasks=[]
 PlayerInit()
 GetGlobalAA().video=m.video
 item={itemId:"fixture-item",sourceId:m.sourceId,type:"movie",title:"Fixture",durationMs:7200000,resumeMs:0,art:{}}
 if ''' + ('true' if home_rows else 'false') + '''
  m.view="home":m.zone="rows"
  m.backdropTimer=m.top.findNode("backdropTimer")
  HomeInit()
  HomeSetRows([{title:"Continue Watching",rowId:"synthetic-continue",sectionType:"continue_watching",items:[item]}])
  playHandled=HomeKey("play")
 else
  PlayItem(item,0)
 end if
 initialized={clock:m.playClock<>invalid,start:m.playStartMs,upNextDismissed:m.upNextDismissed,introDismissed:m.introDismissed}
 for each outcome in ParseJson("''' + encode(outcomes) + '''")
  onApiResult(FixtureEvent(outcome))
 end for
 beforeBackTasks=GetGlobalAA().tasks.Count()
 bound=m.video.content<>invalid
 boundControl=m.video.control
 boundFormat=""
 if bound then boundFormat=m.video.content.streamFormat
 if ''' + ('true' if close else 'false') + '''
  m.video.position=42.0:m.video.state="playing"
  handled=PlayerKey("back")
 end if
 if ParseJson("''' + encode(stop_outcome) + '''")<>invalid
  onApiResult(FixtureEvent(ParseJson("''' + encode(stop_outcome) + '''")))
 end if
 afterBackTasks=GetGlobalAA().tasks.Count()
 if ''' + ('true' if home_rows and close else 'false') + ''' then onHeroTick()
 heroTimerControl=""
 if m.heroTimer<>invalid then heroTimerControl=m.heroTimer.control
 print FormatJson({heroCandidateEligible:SiloUISpeedHero(m.homeRows,"fixture-item","home","heroButtons"),zone:m.zone,heroTimerControl:heroTimerControl,beforeBackTasks:beforeBackTasks,afterBackTasks:afterBackTasks,initialized:initialized,tasks:GetGlobalAA().tasks,bound:bound,boundControl:boundControl,boundFormat:boundFormat,view:m.view,detached:m.video.content=invalid,control:m.video.control,pending:m.pending.Count(),tickets:m.cleanupTickets.Count()})
'''
            output = run_brightscript(files, body, root=root)
            return json.loads(output.strip().splitlines()[-1])

    def test_ordinary_cold_start_combined_receipt_binds_and_back_stops(self):
        entry = self.scene()
        self.assertEqual(dict(clock=True, start=0, upNextDismissed=False, introDismissed=False), entry['initialized'])
        self.assertEqual(['detail'], [t['job']['action'] for t in entry['tasks']])
        detail = self.task(entry['tasks'][0]['job'])['outcome']
        self.assertTrue(detail['ok'], detail)
        selected = self.scene([detail])
        start_job = selected['tasks'][1]['job']
        self.assertEqual('playback_start', start_job['action'])
        started = self.task(start_job)
        self.assertTrue(started['outcome']['ok'], started['outcome'])
        self.assertNotIn('compatContinuation', started['outcome'])
        starts = [json.loads(r['body']) for r in started['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['731'], [s['file_id'] for s in starts])
        self.assertNotIn('audio_track_id', starts[0])  # Ordinary default-audio selection.
        self.assertEqual(dict(id='file:731:audio:0', index=0),
            started['outcome']['plan']['siloPlayback']['selectedTracks']['audio'])
        hls = starts[0]['client_playback_context']['deliveries']['hls']
        self.assertTrue(hls['hdr_details']['hdr10'])
        self.assertNotIn(8, hls['hdr_details']['dolby_vision_profiles'])
        self.assertNotIn('originalPlayback', started['outcome']['plan'])
        closed = self.scene([detail, started['outcome']], close=True)
        self.assertEqual((True, 'play', 'hls'), (closed['bound'], closed['boundControl'], closed['boundFormat']))
        self.assertEqual(('search', True, 'stop'), (closed['view'], closed['detached'], closed['control']))
        stop = closed['tasks'][2]
        self.assertEqual(('playback_stop', 'stop'), (stop['job']['action'], stop['nativeControl']))
        self.assertEqual(dict(provider='silo', sourceId='silo:https://silo.example', profileId='fixture-owner', generation=7),
            {key: stop['job'][key] for key in ('provider', 'sourceId', 'profileId', 'generation')})
        plan = started['outcome']['plan']
        self.assertEqual((plan['sessionId'], plan['installationId'], 42000, 1, False),
            tuple(stop['job']['params'][key] for key in ('sessionId', 'installationId', 'positionMs', 'sequence', 'isPaused')))
        stopped = self.task(stop['job'])
        self.assertEqual((stop['job']['requestId'], 0), (stopped['outcome']['requestId'], stopped['outcome']['sessionRevision']))
        self.assertTrue(stopped['outcome']['ok'], stopped['outcome'])
        body = self.assert_owned_delete(stopped)
        # Ordinary PlayerReport has no stopId: actual TaskPlaybackEvent allocates it
        # once from the deterministic SDK UUID source, without changing Scene policy.
        self.assertNotIn('stopId', stop['job']['params'])
        self.assertEqual('10000000-0000-4000-8000-000000000001', body['stop_id'])
        self.assertEqual(plan['installationId'], body['installation_id'])
        self.assertEqual((42, 1, False), (body['position'], body['sequence'], body['is_paused']))
        drained = self.scene([detail, started['outcome']], close=True, stop_outcome=stopped['outcome'])
        self.assertEqual((0, 0, True, 'stop'), (drained['pending'], drained['tickets'], drained['detached'], drained['control']))

    def test_refused_strip_recipe_never_binds_and_retires_exact_owned_session(self):
        entry = self.scene()
        detail = self.task(entry['tasks'][0]['job'])['outcome']
        selected = self.scene([detail])
        result = self.task(selected['tasks'][1]['job'], refused=True)
        self.assertFalse(result['outcome']['ok'])
        self.assertNotIn('plan', result['outcome'])
        self.assertNotIn('compatContinuation', result['outcome'])
        starts = [r for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(1, len(starts))
        self.assert_owned_delete(result)
        refused = self.scene([detail, result['outcome']])
        self.assertFalse(refused['bound'])
        self.assertEqual(0, refused['pending'])
        self.assertEqual(0, refused['tickets'])
        self.assertEqual(['detail', 'playback_start'], [t['job']['action'] for t in refused['tasks']])

    def assert_owned_delete(self, result):
        deletes = [r for r in result['requests'] if r['method'] == 'DELETE']
        self.assertEqual(1, len(deletes))
        self.assertTrue(deletes[0]['url'].endswith('/playback/session-fixture-01'))
        body = json.loads(deletes[0]['body'])
        self.assertEqual('server-install', body['installation_id'])
        self.assertRegex(body['stop_id'], r'^[0-9a-f-]{36}$')
        return body

    def test_home_rows_play_back_restores_rows_and_hero_tick_cannot_speculate(self):
        entry = self.scene(home_rows=True)
        self.assertEqual(['detail'], [t['job']['action'] for t in entry['tasks']])
        detail = self.task(entry['tasks'][0]['job'])['outcome']
        selected = self.scene([detail], home_rows=True)
        start_job = selected['tasks'][1]['job']
        started = self.task(start_job)
        self.assertTrue(started['outcome']['ok'], started['outcome'])
        closed = self.scene([detail, started['outcome']], close=True, home_rows=True)
        self.assertTrue(closed['heroCandidateEligible'])  # Eligible source; rows is the fence.
        self.assertEqual(('home', 'rows', True, 'stop'),
            (closed['view'], closed['zone'], closed['detached'], closed['heroTimerControl']))
        self.assertEqual((2, 3, 3), (closed['beforeBackTasks'], closed['afterBackTasks'], len(closed['tasks'])))
        self.assertEqual(['detail', 'playback_start', 'playback_stop'], [t['job']['action'] for t in closed['tasks']])
        self.assertEqual('stop', closed['tasks'][-1]['nativeControl'])
