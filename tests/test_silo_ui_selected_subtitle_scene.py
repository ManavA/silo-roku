"""Scene-facing selected-caption validation, independent of Task-private URLs."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'components/SiloUISubtitleArtifact.brs'
TRACKS = ROOT / 'source/core/TrackPreference.brs'
URI = 'tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt'


def ready_plan():
    return {
        'provider': 'silo', 'sourceId': 'silo:synthetic', 'versionId': 'f1',
        'sessionId': 'sess-1', 'subtitleMode': 'render',
        'timelineOffsetMs': 0,
        'siloPlayback': {'sourceId': 'silo:synthetic', 'profileId': 'profile',
                         'fileId': 'f1', 'sessionId': 'sess-1',
                         'sessionRevision': 2, 'planAttemptKey': 'attempt-1'},
        'selectedSubtitle': {'kind': 'sidecar_ready', 'renderingReady': True,
                             'combinedIndex': 1, 'trackId': 'file:f1:subtitle:1',
                             'language': 'eng', 'format': 'vtt', 'mimeType': 'text/vtt'},
        'subtitleArtifact': {'uri': URI, 'format': 'vtt', 'mimeType': 'text/vtt',
                             'timingOriginSeconds': 0,
                             'owner': {'sourceId': 'silo:synthetic', 'profileId': 'profile',
                                       'generation': 7, 'requestId': 42, 'sessionRevision': 2,
                                       'sessionId': 'sess-1', 'planAttemptKey': 'attempt-1',
                                       'fileId': 'f1', 'selectedOrdinal': 1, 'timelineOffsetMs': 0}},
    }


class SelectedSubtitleScenePolicy(unittest.TestCase):
    def call(self, name, *args):
        return run_function([POLICY], name, list(args))

    def test_ready_sidecar_produces_one_safe_local_track(self):
        result = self.call('SiloUISubtitleBinding', ready_plan(), 7, 42)
        self.assertEqual(URI, result['uri'])
        self.assertEqual('eng', result['language'])
        self.assertEqual(1, result['selectedOrdinal'])
        self.assertIn('1', result['description'])
        self.assertIn('01234567', result['description'])
        self.assertNotIn('silo:', result['description'])

    def test_wrong_owner_or_receipt_cannot_bind(self):
        for mutate in (
            lambda p: p['subtitleArtifact']['owner'].update(generation=8),
            lambda p: p['subtitleArtifact']['owner'].update(requestId=43),
            lambda p: p['subtitleArtifact']['owner'].update(fileId='f2'),
            lambda p: p['subtitleArtifact']['owner'].update(planAttemptKey='other'),
            lambda p: p['subtitleArtifact']['owner'].update(timelineOffsetMs=1000),
            lambda p: p['selectedSubtitle'].update(trackId='file:f1:subtitle:0'),
            lambda p: p['selectedSubtitle'].update(renderingReady=False),
            lambda p: p['subtitleArtifact'].update(uri='tmp:/other.vtt'),
            lambda p: p['subtitleArtifact'].update(uri=URI+'?token=x'),
            lambda p: p.update(subtitleMode='off'),
        ):
            plan = copy.deepcopy(ready_plan())
            mutate(plan)
            with self.subTest(plan=plan):
                self.assertIsNone(self.call('SiloUISubtitleBinding', plan, 7, 42))

    def test_optional_failed_fetch_or_burn_never_binds(self):
        for kind, mode in [('fetch_failed', 'render'), ('unsupported', 'convert'),
                           ('off', 'off'), ('burn_in', 'burn_in')]:
            plan = ready_plan()
            plan['selectedSubtitle']['kind'] = kind
            plan['subtitleMode'] = mode
            self.assertIsNone(self.call('SiloUISubtitleBinding', plan, 7, 42))

    def test_failed_optional_caption_fetch_has_safe_playback_notice(self):
        plan = ready_plan()
        plan['selectedSubtitle']['kind'] = 'fetch_failed'
        plan.pop('subtitleArtifact')
        self.assertEqual('Subtitles could not load. Playback continues.',
                         self.call('SiloUISubtitleStartupNotice', plan))
        self.assertEqual('', self.call('SiloUISubtitleStartupNotice', ready_plan()))

    def test_embedded_render_retains_native_subtitle_preference_lane(self):
        plan = ready_plan()
        plan['selectedSubtitle']['kind'] = 'embedded_render'
        plan.pop('subtitleArtifact')
        self.assertEqual('preference', self.call('SiloUISubtitleIntent', plan))
        plan['selectedSubtitle']['kind'] = 'unsupported'
        self.assertEqual('preference', self.call('SiloUISubtitleIntent', plan))
        plan['selectedSubtitle']['kind'] = 'fetch_failed'
        self.assertEqual('selected', self.call('SiloUISubtitleIntent', plan))

    def test_subtitle_intent_distinguishes_provider_off_from_default_off(self):
        plan = ready_plan()
        plan['subtitleMode'] = 'off'
        plan['selectedSubtitle'] = {'kind': 'off'}
        self.assertEqual('preference', self.call('SiloUISubtitleIntent', plan))
        plan['siloPlayback']['subtitleOffRequired'] = True
        self.assertEqual('off', self.call('SiloUISubtitleIntent', plan))
        plan['subtitleMode'] = 'burn_in'
        self.assertEqual('burn_in', self.call('SiloUISubtitleIntent', plan))

    def test_provider_off_native_override_rematches_exact_lane_without_old_id(self):
        plan = ready_plan()
        plan.update(subtitleMode='off', selectedSubtitle={'kind': 'off'})
        plan['siloPlayback']['subtitleOffRequired'] = True
        scope = {'provider': 'silo', 'sourceId': 'silo:synthetic',
                 'profileId': 'profile', 'generation': 7}
        choice = {'kind': 'subtitle', 'trackId': 'native-old',
                  'name': 'French', 'language': 'fra'}
        old = [{'TrackName': 'native-old', 'Description': 'French', 'Language': 'fra'}]
        override = run_function([POLICY, TRACKS], 'SiloUISubtitleOverrideCapture',
                                [plan, scope, choice, old])
        self.assertIsNotNone(override)
        recovered = [{'TrackName': 'native-new', 'Description': 'French', 'Language': 'fre'}]
        self.assertEqual('native-new', run_function([POLICY, TRACKS],
                         'SiloUISubtitleOverrideCandidate', [override, plan, scope, recovered]))
        self.assertIsNone(run_function([POLICY, TRACKS], 'SiloUISubtitleOverrideCandidate',
                          [override, plan, scope, [{'TrackName': 'english', 'Description': 'English', 'Language': 'eng'}]]))
        self.assertIsNone(run_function([POLICY, TRACKS], 'SiloUISubtitleOverrideCandidate',
                          [override, plan, scope, recovered + recovered]))
        changed = copy.deepcopy(plan)
        changed['versionId'] = 'f2'
        self.assertIsNone(run_function([POLICY, TRACKS], 'SiloUISubtitleOverrideCandidate',
                          [override, changed, scope, recovered]))

    def test_integral_timeline_offset_accepts_wire_number_shape(self):
        plan = ready_plan()
        plan['timelineOffsetMs'] = 120000.0
        plan['subtitleArtifact']['owner']['timelineOffsetMs'] = 120000.0
        self.assertIsNotNone(self.call('SiloUISubtitleBinding', plan, 7, 42))

    def test_actual_task_double_milliseconds_bind_without_json_type_collapse(self):
        payload = json.dumps(ready_plan()).replace('"', '""')
        with tempfile.TemporaryDirectory() as directory:
            output = run_brightscript([POLICY], f'''plan=ParseJson("{payload}")
 offset=120 * 1000#
 plan["timelineOffsetMs"]=offset
 plan.subtitleArtifact.owner["timelineOffsetMs"]=offset
 binding=SiloUISubtitleBinding(plan,7,42)
 print FormatJson({{kind:Type(offset),accepted:binding<>invalid}})''', root=Path(directory))
        self.assertEqual({'kind': 'Double', 'accepted': True}, json.loads(output.strip().splitlines()[-1]))

    def test_unique_native_identifier_requires_metadata_and_current_match(self):
        binding = self.call('SiloUISubtitleBinding', ready_plan(), 7, 42)
        inventory = [{'TrackName': 'unrelated', 'Description': 'Other', 'Language': 'eng'},
                     {'TrackName': 'native-7', 'Description': binding['description'], 'Language': 'en'}]
        self.assertEqual('native-7', self.call('SiloUISubtitleNativeCandidate', binding, inventory))
        self.assertIsNone(self.call('SiloUISubtitleNativeCandidate', binding, inventory + [inventory[1]]))
        self.assertFalse(self.call('SiloUISubtitleCurrentMatches', binding, 'unrelated', inventory))
        self.assertTrue(self.call('SiloUISubtitleCurrentMatches', binding, 'native-7', inventory))

    def test_content_and_native_language_use_same_iso_639_2b_identity(self):
        for source, native, expected in [('fr', 'fre', 'fre'), ('fra', 'fre', 'fre'),
                                         ('fre', 'fre', 'fre'), ('de', 'ger', 'ger'),
                                         ('deu', 'ger', 'ger'), ('ger', 'ger', 'ger'),
                                         ('zh', 'chi', 'chi'), ('zho', 'chi', 'chi'),
                                         ('chi', 'chi', 'chi')]:
            with self.subTest(source=source):
                plan = ready_plan()
                plan['selectedSubtitle']['language'] = source
                binding = self.call('SiloUISubtitleBinding', plan, 7, 42)
                self.assertEqual(expected, binding['language'])
                inventory = [{'TrackName': 'native-7', 'Description': binding['description'],
                              'Language': native}]
                self.assertEqual('native-7', self.call('SiloUISubtitleNativeCandidate', binding, inventory))
        plan = ready_plan()
        plan['selectedSubtitle']['language'] = 'zz'
        self.assertEqual('und', self.call('SiloUISubtitleBinding', plan, 7, 42)['language'])

    def test_actual_inventory_callback_keeps_explicit_caption_selection(self):
        payload = json.dumps(ready_plan()).replace('"', '""')
        with tempfile.TemporaryDirectory() as directory:
            output = run_brightscript(
                [ROOT / 'components/SiloUIPlayer.brs', POLICY],
                f'''m.view="player":m.generation=7:m.trackPref={{}}
 m.playPlan=ParseJson("{payload}")
 m.video={{content:{{id:"current",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}},availableAudioTracks:[],availableSubtitleTracks:[],currentSubtitleTrack:"",globalCaptionMode:"Off",subtitleTrack:""}}
 binding=SiloUISubtitleBinding(m.playPlan,7,42):binding["content"]=m.video.content
 m.subtitleBinding=binding
 audioEvent={{GetField:function() as String
 return "availableAudioTracks"
 end function}}
 subtitleEvent={{GetField:function() as String
 return "availableSubtitleTracks"
 end function}}
 currentEvent={{GetField:function() as String
 return "currentSubtitleTrack"
 end function}}
 onPlayerTracks(audioEvent)
 before=m.video.globalCaptionMode
 m.video.availableSubtitleTracks=[{{TrackName:"native-7",Description:binding.description,Language:"en"}}]
 onPlayerTracks(subtitleEvent)
 selected={{mode:m.video.globalCaptionMode,track:m.video.subtitleTrack}}
 m.video.currentSubtitleTrack="native-7"
 onPlayerTracks(currentEvent):onPlayerTracks(audioEvent)
 verified={{mode:m.video.globalCaptionMode,current:m.subtitleBinding.currentVerified}}
 m.video.availableSubtitleTracks=[]
 onPlayerTracks(subtitleEvent)
 print FormatJson({{before:before,selected:selected,verified:verified,missing:m.video.globalCaptionMode}})''',
                root=Path(directory))
        observed = json.loads(output.strip().splitlines()[-1])
        self.assertEqual('Off', observed['before'])
        self.assertEqual({'mode': 'Off', 'track': 'native-7'}, observed['selected'])
        self.assertEqual({'mode': 'On', 'current': True}, observed['verified'])
        self.assertEqual('Off', observed['missing'])

    def test_provider_off_native_choice_callback_requires_fresh_exact_readback(self):
        plan = ready_plan()
        plan.update(subtitleMode='off', selectedSubtitle={'kind': 'off'})
        plan['siloPlayback']['subtitleOffRequired'] = True
        payload = json.dumps(plan).replace('"', '""')
        with tempfile.TemporaryDirectory() as directory:
            output = run_brightscript([ROOT / 'components/SiloUIPlayer.brs', POLICY, TRACKS, ROOT / 'components/SiloUIRobustness.brs'], f'''m.view="player":m.provider="silo":m.sourceId="silo:synthetic":m.profileId="profile":m.generation=7
 m.playPlan=ParseJson("{payload}"):m.trackPref={{subtitle:"off"}}
 current={{id:"content",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}}
 m.video={{content:current,availableAudioTracks:[],availableSubtitleTracks:[{{TrackName:"native-new",Description:"French",Language:"fre"}}],currentSubtitleTrack:"",globalCaptionMode:"Off",subtitleTrack:""}}
 m.nativeSubtitleContent=current:m.nativeSubtitleInventoryFresh=false
 m.nativeSubtitleOverride={{sourceId:m.sourceId,profileId:m.profileId,generation:7,sessionId:"sess-1",fileId:"f1",language:"fra",name:"French"}}
 subtitleEvent={{GetField:function() as String
 return "availableSubtitleTracks"
 end function}}
 currentEvent={{GetField:function() as String
 return "currentSubtitleTrack"
 end function}}
 onPlayerTracks(subtitleEvent)
 pending={{mode:m.video.globalCaptionMode,track:m.video.subtitleTrack}}
 m.video.currentSubtitleTrack="native-new":onPlayerTracks(currentEvent)
 accepted=m.video.globalCaptionMode
 m.video.availableSubtitleTracks=[{{TrackName:"english",Description:"English",Language:"eng"}}]
 onPlayerTracks(subtitleEvent)
 print FormatJson({{pending:pending,accepted:accepted,missing:m.video.globalCaptionMode}})''', root=Path(directory))
        observed = json.loads(output.strip().splitlines()[-1])
        self.assertEqual({'mode': 'Off', 'track': 'native-new'}, observed['pending'])
        self.assertEqual('On', observed['accepted'])
        self.assertEqual('Off', observed['missing'])

    def test_public_menu_native_override_is_scoped_and_explicit_off_clears_it(self):
        plan = ready_plan()
        plan.update(subtitleMode='off', selectedSubtitle={'kind': 'off'})
        plan['siloPlayback']['subtitleOffRequired'] = True
        payload = json.dumps(plan).replace('"', '""')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = (ROOT / 'components/SiloUIPlayer.brs').read_text()
            source = source.replace('CreateObject("roSGNode", "ContentNode")','FakeContent()')
            fixture = folder / 'player.brs'
            fixture.write_text(source + '''
function FakeContent() as Object
 return {createChild:function(kind as String) as Object
 return {}
 end function}
end function
sub Toast(message as String)
 m.message=message
end sub
''')
            output = run_brightscript([fixture, POLICY, TRACKS, ROOT/'components/SiloUIPlaybackChoices.brs', ROOT/'source/core/SiloUIPlayerPolicy.brs', ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'source/core/SiloUIFormat.brs'], f'''m.view="player":m.provider="silo":m.sourceId="silo:synthetic":m.profileId="profile":m.generation=7
 m.playPlan=ParseJson("{payload}"):m.trackPref={{}}:m.trackPrefLanes={{}}
 m.video={{setFocus:sub(value as Boolean)
 m.focused=value
 end sub,availableAudioTracks:[],availableSubtitleTracks:[{{TrackName:"native-old",Description:"French",Language:"fra"}}],subtitleTrack:"",globalCaptionMode:"Off"}}
 m.top={{findNode:function(id as String) as Object
 return {{visible:false}}
 end function}}
 m.trackList={{itemSelected:1,setFocus:sub(value as Boolean)
 m.focused=value
 end sub}}
 PlayerShowTracks()
 onPlayerTrackChoice()
 selected={{track:m.video.subtitleTrack,mode:m.video.globalCaptionMode,owner:m.nativeSubtitleOverride.sessionId}}
 firstClosedRows=m.trackChoices.Count()
 PlayerShowTracks():m.trackList.itemSelected=0
 onPlayerTrackChoice()
 print FormatJson({{selected:selected,off:m.video.globalCaptionMode,override:m.nativeSubtitleOverride,closedRows:[firstClosedRows,m.trackChoices.Count()],videoFocused:m.video.focused}})''', root=folder)
        observed = json.loads(output.strip().splitlines()[-1])
        self.assertEqual({'track': 'native-old', 'mode': 'On', 'owner': 'sess-1'}, observed['selected'])
        self.assertEqual('Off', observed['off'])
        self.assertIsNone(observed['override'])
        self.assertEqual([0, 0], observed['closedRows'])
        self.assertTrue(observed['videoFocused'])

    def test_embedded_and_default_off_callbacks_keep_existing_native_lane(self):
        embedded = ready_plan()
        embedded['selectedSubtitle'] = {'kind': 'embedded_render'}
        default_off = ready_plan()
        default_off.update(subtitleMode='off', selectedSubtitle={'kind': 'off'})
        payload = json.dumps([embedded, default_off]).replace('"', '""')
        with tempfile.TemporaryDirectory() as directory:
            output = run_brightscript([ROOT / 'components/SiloUIPlayer.brs', POLICY, TRACKS], f'''plans=ParseJson("{payload}")
 m.view="player":m.trackPref={{subtitle:"fra"}}:m.trackPrefLanes={{subtitle:"French"}}
 m.video={{availableAudioTracks:[],availableSubtitleTracks:[{{TrackName:"mkv/7",Description:"French",Language:"fra"}}],subtitleTrack:"mkv/7",globalCaptionMode:"On"}}
 result=[]
 for each plan in plans
  m.playPlan=plan:m.video.globalCaptionMode="On":onPlayerTracks()
  result.Push({{mode:m.video.globalCaptionMode,track:m.video.subtitleTrack}})
 end for
 print FormatJson(result)''', root=Path(directory))
        self.assertEqual([{'mode': 'On', 'track': 'mkv/7'}] * 2,
                         json.loads(output.strip().splitlines()[-1]))

    def test_public_player_bind_sets_track_and_config_before_content(self):
        payload = json.dumps(ready_plan()).replace('"', '""')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = (ROOT / 'components/SiloUIPlayer.brs').read_text()
            source = source.replace('CreateObject("roSGNode", "ContentNode")', 'FixtureContent()')
            source = source.replace('CreateObject("roHttpAgent")', 'FixtureAgent()')
            source = re.sub(r'(?m)^sub PlayerOriginalClear\(', 'sub UnusedPlayerOriginalClear(', source, count=1)
            fixture = folder / 'player.brs'
            fixture.write_text(source + '''
sub PlayerOriginalClear()
end sub
function FixtureContent() as Object
 return {id:"new",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}
end function
function FixtureAgent() as Object
 return {SetCertificatesFile:sub(path as String)
 end sub,AddHeader:sub(name as String,value as String)
 end sub}
end function
''')
            output = run_brightscript([fixture, POLICY, ROOT / 'source/core/SiloUIFormat.brs'], f'''m.generation=7:m.subtitleResultRequestId=42:m.subtitleBindingGeneration=0:m.playVersions=[]
 m.view="detail":m.trackPref={{}}
 m.video={{subtitleTrack:"",content:invalid,availableAudioTracks:[],availableSubtitleTracks:[],globalCaptionMode:"Off",SetHttpAgent:sub(agent as Object)
 end sub}}
 m.playPlan=ParseJson("{payload}")
 PlayerBind(m.playPlan,"Synthetic movie")
 content=m.video.content
 m.video.availableSubtitleTracks=[{{TrackName:"native-7",Description:m.subtitleBinding.description,Language:"en"}}]
 event={{GetField:function() as String
 return "availableSubtitleTracks"
 end function}}
 onPlayerTracks(event)
 latched=m.subtitleBinding.inventoryFresh
 m.view="player":m.video.currentSubtitleTrack="native-7":onPlayerTracks()
 print FormatJson({{uri:m.video.subtitleTrack,tracks:content.SubtitleTracks,config:content.SubtitleConfig,bound:m.subtitleBinding.uri,latched:latched,mode:m.video.globalCaptionMode}})''',
                root=folder)
        observed = json.loads(output.strip().splitlines()[-1])
        self.assertEqual(URI, observed['uri'])
        self.assertEqual(URI, observed['bound'])
        self.assertTrue(observed['latched'])
        self.assertEqual('On', observed['mode'])
        self.assertEqual([{'Language': 'eng', 'Description': 'Source subtitle 1 01234567', 'TrackName': URI}], observed['tracks'])
        self.assertEqual({'TrackName': URI}, observed['config'])

    def test_stale_start_callback_deletes_local_file_without_binding(self):
        payload = json.dumps(ready_plan()).replace('"', '""')
        recovery = re.search(r'(?ms)^function SiloUIRecoveryResult\(.*?^end function',
                             (ROOT / 'components/SiloUIRobustness.brs').read_text()).group(0)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            policy = (ROOT / 'components/SiloUISubtitleArtifact.brs').read_text()
            policy = policy.replace('DeleteFile(uri)', 'FixtureDeleteFile(uri)', 1)
            fixture = folder / 'policy.brs'
            fixture.write_text(policy + '\n' + recovery + '\n' + '''
sub FixtureDeleteFile(uri as Dynamic)
 m.deleted.Push(uri)
end sub
function SiloUIAllocationResult(entry as Object,result as Object) as Boolean
 return true
end function
sub SiloUIDrainMaybeDone()
end sub
''')
            output = run_brightscript([ROOT / 'components/SiloUIScene.brs', fixture], f'''m.generation=8:m.pending={{}}:m.deleted=[]
 task={{unobserveField:sub(name as String)
 end sub}}
 m.pending["42"]={{task:task,purpose:"play_start",generation:7,extra:1,owner:{{sourceId:"silo:synthetic",profileId:"profile",generation:7,sessionRevision:2}}}}
 plan=ParseJson("{payload}")
 event={{payload:{{requestId:42,ok:true,plan:plan}},getData:function() as Object
 return m.payload
 end function}}
 onApiResult(event)
 print FormatJson({{deleted:m.deleted,pending:m.pending.Count(),bound:m.subtitleBinding}})''', root=folder)
        observed = json.loads(output.strip().splitlines()[-1])
        self.assertEqual([URI], observed['deleted'])
        self.assertEqual(0, observed['pending'])
        self.assertIsNone(observed['bound'])

    def test_detached_old_file_waits_for_stopped_and_cannot_delete_new_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            policy = (ROOT / 'components/SiloUISubtitleArtifact.brs').read_text()
            policy = policy.replace('DeleteFile(uri)', 'FixtureDeleteFile(uri)', 1)
            fixture = folder / 'policy.brs'
            fixture.write_text(policy + '''
sub FixtureDeleteFile(uri as Dynamic)
 m.deleted.Push(uri)
end sub
''')
            output = run_brightscript([fixture], f'''m.deleted=[]
 old={{id:"old",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}}
 newer={{id:"new",isSameNode:function(other as Object) as Boolean
 return m.id=other.id
 end function}}
 m.video={{state:"playing",content:old,control:"play"}}
 m.subtitleBinding={{uri:"{URI}",content:old,bindingGeneration:1}}
 SiloUISubtitleRetireBound():SiloUISubtitleDrainRetired()
 before=m.deleted.Count()
 m.video.content=newer
 m.subtitleBinding={{uri:"tmp:/silo-subtitle-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.vtt",content:newer,bindingGeneration:2}}
 m.video.state="stopped":SiloUISubtitleDrainRetired()
 print FormatJson({{before:before,deleted:m.deleted,current:m.subtitleBinding.uri,retired:m.subtitleRetired.Count()}})''', root=folder)
        observed = json.loads(output.strip().splitlines()[-1])
        self.assertEqual(0, observed['before'])
        self.assertEqual([URI], observed['deleted'])
        self.assertEqual('tmp:/silo-subtitle-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.vtt', observed['current'])
        self.assertEqual(0, observed['retired'])

    def test_retirement_signals_task_cancel_without_dropping_result_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = run_brightscript([ROOT / 'components/SiloUIRobustness.brs'], '''m.pending={}
 m.pending["1"]={purpose:"play_start",task:{cancelled:false}}
 m.pending["2"]={purpose:"play_recover",task:{cancelled:false}}
 m.pending["3"]={purpose:"subtitle_off",task:{cancelled:false}}
 m.pending["4"]={purpose:"cleanup_stop",task:{cancelled:false}}
 SiloUICancelPendingPlayback()
 print FormatJson({count:m.pending.Count(),start:m.pending["1"].task.cancelled,replan:m.pending["2"].task.cancelled,off:m.pending["3"].task.cancelled,cleanup:m.pending["4"].task.cancelled})''', root=Path(directory))
        observed = json.loads(output.strip().splitlines()[-1])
        self.assertEqual({'count': 4, 'start': True, 'replan': True,
                          'off': True, 'cleanup': False}, observed)


if __name__ == '__main__':
    unittest.main()
