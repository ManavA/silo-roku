"""Player timing and identity decisions without a Roku device."""
import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function, run_brightscript as execute_brightscript
ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUIPlayerPolicy.brs'
def run_brightscript(files, body, *, root):
    return execute_brightscript([ROOT / 'components/SiloUIRobustness.brs', ROOT / 'components/SiloUISubtitleArtifact.brs', ROOT / 'components/SiloUICompatPlayback.brs', *files], body, root=root)
class SiloUIPlayerPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.is_file(), 'SiloUI player policy missing')
        with tempfile.TemporaryDirectory() as root:
            result = run_function([POLICY], name, list(args), root=Path(root))
            if name == "SiloUIPlayerActions":
                result = [{key.lower(): value for key, value in entry.items()} for entry in result]
            if name == "SiloUIPlayerCue":
                result = {key.lower(): value for key, value in result.items()}
            return result
    def test_friendly_track_names_hide_internal_ids_and_preserve_descriptions(self):
        cases = [
            ('#uniq:(1)', 'eng', 'audio', 1, 'English'),
            ('#uniq:(1)', '', 'audio', 1, 'Audio 1'),
            ('eng', 'eng', 'subtitle', 1, 'English'),
            ('SDH', 'eng', 'subtitle', 2, 'English · SDH'),
            ('Latin American', 'spa', 'subtitle', 3, 'Latin American'),
            ('Director commentary', 'eng', 'audio', 2, 'Director commentary'),
            ('', 'es', 'audio', 2, 'Spanish'),
        ]
        for name, language, kind, index, expected in cases:
            with self.subTest(name=name, language=language):
                self.assertEqual(self.call('SiloUIPlayerTrackLabel', name, language, kind, index), expected)

    def test_cue_layout_keeps_countdown_separate_from_long_title(self):
        intro = self.call('SiloUIPlayerCuePresentation', False, 10)
        self.assertEqual(intro['hint'], 'Pause to skip intro')
        self.assertEqual((intro['width'], intro['height']), (260, 46))
        next_cue = self.call('SiloUIPlayerCuePresentation', True, 9)
        self.assertEqual(next_cue['hint'], '9 seconds · Pause for next')
        self.assertEqual((next_cue['width'], next_cue['height']), (420, 160))
        import xml.etree.ElementTree as ET
        root = ET.parse(ROOT / 'components/SiloUIScene.xml').getroot()
        title = root.find(".//Label[@id='playerCueTitle']")
        self.assertIsNotNone(title)
        self.assertEqual(title.get('height'), '64')
        self.assertEqual(title.get('color'), '0x101725FF')

    def test_intro_boundaries_and_credits_trigger(self):
        markers = [{'kind':'intro','startMs':1000,'endMs':5000}, {'kind':'credits','startMs':80000,'endMs':90000}]
        self.assertEqual(self.call('SiloUIPlayerCue',markers,1000,90000,True,False), {'introendms':5000,'upnext':False})
        self.assertEqual(self.call('SiloUIPlayerCue',markers,5000,90000,True,False)['introendms'],0)
        self.assertTrue(self.call('SiloUIPlayerCue',markers,80000,120000,True,False)['upnext'])
        self.assertFalse(self.call('SiloUIPlayerCue',markers,85000,90000,True,True)['upnext'])
        self.assertFalse(self.call('SiloUIPlayerCue',[],100,0,True,False)['upnext'])
    def test_next_requires_same_source_series_season_and_exact_successor(self):
        current = dict(type='episode',itemId='1',sourceId='s',seriesId='show',seasonNumber=2,episodeNumber=3)
        good = dict(current,itemId='2',episodeNumber=4)
        self.assertEqual(self.call('SiloUIPlayerNext',current,[dict(good,sourceId='other'),dict(good,seasonNumber=3),good]),good)
        self.assertIsNone(self.call('SiloUIPlayerNext',current,[dict(good,episodeNumber=5)]))
        self.assertIsNone(self.call('SiloUIPlayerNext',dict(current,seriesId=''),[good]))

    def test_back_dismisses_once_and_stops_countdown(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([ROOT / 'components/SiloUIPlayer.brs'], '''
                m.playerCue = {visible:true}
                m.upNextTimer = {control:"start"}
                m.upNextActive = true
                m.view = "player"
                m.upNextSeconds = 7
                handled = PlayerKey("back")
                onUpNextTick()
                print FormatJson({handled:handled, dismissed:m.upNextDismissed, visible:m.playerCue.visible, control:m.upNextTimer.control, seconds:m.upNextSeconds})
            ''', root=Path(root))
        import json
        self.assertEqual(json.loads(output), dict(handled=True,dismissed=True,visible=False,control='stop',seconds=7))

    def test_ambiguous_or_malformed_candidates_are_rejected(self):
        item = dict(type='episode',sourceId='s',seriesId='show',seasonNumber=1,episodeNumber=1,itemId='a')
        candidate = dict(item,itemId='b',episodeNumber=2)
        self.assertIsNone(self.call('SiloUIPlayerNext',item,[candidate,dict(candidate,itemId='c')]))
        self.assertIsNone(self.call('SiloUIPlayerNext',item,[None, 'bad', dict(candidate,type='movie')]))
    def test_seek_away_cancels_countdown_without_resetting_dismissal(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([POLICY, ROOT / 'components/SiloUIPlayer.brs', ROOT / 'source/core/SiloUIFormat.brs', ROOT / 'components/SiloUIScene.brs'], '''
                m.top = {findNode:function(name)
                    return {uri:""}
                end function}
                m.view = "player"
                m.playPlan = {}
                m.playItem = {durationMs:100000}
                m.playMarkers = []
                m.video = {position:20,duration:100}
                m.playNext = {itemId:"next"}
                m.upNextDismissed = false
                m.introDismissed = false
                m.upNextActive = true
                m.playerCue = {visible:true}
                m.playerCueText = {text:""}
                m.upNextTimer = {control:"start"}
                onPlayerPosition()
                print FormatJson({active:m.upNextActive,visible:m.playerCue.visible,control:m.upNextTimer.control,dismissed:m.upNextDismissed})
            ''', root=Path(root))
        import json
        self.assertEqual(json.loads(output),dict(active=False,visible=False,control='stop',dismissed=False))

    def test_track_selection_and_preloaded_language_reapply(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([ROOT / 'components/SiloUIPlayer.brs', ROOT / 'source/core/TrackPreference.brs'], '''
                m.view = "player"
                m.playPlan = {}
                m.trackPref = {}
                m.video = {setFocus:sub(focused)
                end sub, availableAudioTracks:[{Track:"audio-new",Language:"fra",Name:"French"}], availableSubtitleTracks:[{TrackName:"sub-new",Language:"fra",Description:"French"}]}
                m.trackDialog = {visible:true}
                m.trackList = {itemSelected:0}
                m.trackChoices = [{kind:"audio",language:"fra",trackId:"audio-old"}]
                onPlayerTrackChoice()
                m.trackDialog = {visible:true}
                m.trackChoices = [{kind:"subtitle",language:"fra",trackId:"sub-old"}]
                onPlayerTrackChoice()
                onPlayerTracks()
                print FormatJson({audio:m.video.audioTrack,subtitle:m.video.subtitleTrack,mode:m.video.globalCaptionMode,pref:m.trackPref})
            ''', root=Path(root))
        import json
        self.assertEqual(json.loads(output),dict(audio='audio-new',subtitle='sub-new',mode='On',pref=dict(audio='fra',subtitle='fra')))

    def test_advance_closes_without_browse_refresh_before_starting_next(self):
        import re
        with tempfile.TemporaryDirectory() as root:
            source = (ROOT / 'components/SiloUIPlayer.brs').read_text()
            source = re.sub(r'sub PlayerClose\(.*?\nend sub', '''sub PlayerClose(finished as Boolean, refresh = true as Boolean)
                m.calls.Push({action:"close",finished:finished,refresh:refresh})
            end sub''', source, count=1, flags=re.S)
            source = re.sub(r'sub PlayItem\(.*?\nend sub', '''sub PlayItem(item as Object, startMs as Dynamic)
                m.calls.Push({action:"play",itemId:item.itemId,startMs:startMs})
            end sub''', source, count=1, flags=re.S)
            fixture = Path(root) / 'player.brs'
            fixture.write_text(source)
            output = run_brightscript([fixture], '''
                m.calls = []
                m.playNext = {itemId:"next"}
                PlayerAdvance()
                print FormatJson(m.calls)
            ''', root=Path(root))
        import json
        self.assertEqual(json.loads(output),[dict(action='close',finished=True,refresh=False),dict(action='play',itemId='next',startMs=0)])

    def test_natural_finish_advances_only_undismissed_next(self):
        import re
        with tempfile.TemporaryDirectory() as root:
            source = (ROOT / 'components/SiloUIPlayer.brs').read_text()
            source = re.sub(r'sub PlayerClose\(.*?\nend sub', 'sub PlayerClose(finished as Boolean, refresh = true as Boolean)\n m.result = "close"\nend sub', source, count=1, flags=re.S)
            source = re.sub(r'sub PlayerAdvance\(.*?\nend sub', 'sub PlayerAdvance(automatic=false as Boolean)\n m.result = "advance"\nend sub', source, count=1, flags=re.S)
            fixture = Path(root) / 'player.brs'
            fixture.write_text(source)
            output = run_brightscript([ROOT/'source/core/SiloUISettingsPolicy.brs', ROOT/'source/core/SiloUIFormat.brs',fixture], '''
                m.view = "player"
                m.playPlan = {}
                m.nativeSeenPlaying = true
                m.video = {state:"finished",position:100,duration:100}
                m.playNext = {itemId:"next"}
                m.upNextActive = true
                m.upNextDismissed = false
                onVideoState()
                first = m.result
                m.upNextDismissed = true
                onVideoState()
                print FormatJson([first,m.result])
            ''', root=Path(root))
        import json
        self.assertEqual(json.loads(output),['advance','close'])

    def test_detail_callback_cannot_prebuffer_over_pending_foreground_start(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([ROOT / 'components/SiloUIPlayer.brs'], '''
                m.provider = "silo"
                m.view = "detail"
                m.playLoading = true
                m.playToken = 12
                PlayerPrebuffer({itemId:"old"}, [{versionId:"old-file"}], [])
                print m.playToken
            ''', root=Path(root))
        self.assertEqual(output.strip(),'12')

    def test_dismissing_intro_does_not_suppress_later_up_next(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([POLICY, ROOT / 'components/SiloUIPlayer.brs'], '''
                m.playerCue = {visible:true}
                m.upNextTimer = {control:"stop"}
                m.upNextActive = false
                m.upNextDismissed = false
                m.introDismissed = false
                PlayerKey("back")
                cue = SiloUIPlayerCue([], 80000, 100000, true, m.upNextDismissed)
                print FormatJson({intro:m.introDismissed,upNext:cue.upNext})
            ''', root=Path(root))
        import json
        self.assertEqual({key.lower():value for key,value in json.loads(output).items()},dict(intro=True,upnext=True))

    def test_native_duration_fallback_uses_source_timeline_offset(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([POLICY, ROOT / 'components/SiloUIPlayer.brs', ROOT / 'source/core/SiloUIFormat.brs', ROOT / 'components/SiloUIScene.brs'], '''
                m.top = {findNode:function(name)
                    return {uri:""}
                end function}
                m.view = "player"
                m.playPlan = {timelineOffsetMs:60000}
                m.playItem = {}
                m.playMarkers = []
                m.video = {position:50,duration:100}
                m.playNext = {title:"Next",art:{}}
                m.upNextDismissed = false
                m.introDismissed = false
                m.upNextActive = false
                m.playerCue = {visible:false}
                m.playerCueText = {text:""}
                m.upNextTimer = {control:"stop"}
                onPlayerPosition()
                print FormatJson({active:m.upNextActive,visible:m.playerCue.visible})
            ''', root=Path(root))
        import json
        self.assertEqual(json.loads(output),dict(active=False,visible=False))

    def test_native_actions_keep_fixed_indices_and_disable_inapplicable_cues(self):
        inactive = self.call('SiloUIPlayerActions',dict(introEndMs=0,upNext=False),False)
        active = self.call('SiloUIPlayerActions',dict(introEndMs=12000,upNext=True),False)
        self.assertEqual([entry['text'] for entry in active],['Audio and subtitles','Skip intro','Next episode'])
        self.assertEqual([entry['buttonisdisabled'] for entry in inactive],[False,True,True])
        self.assertEqual([entry['buttonisdisabled'] for entry in active],[False,False,False])
        self.assertTrue(self.call('SiloUIPlayerActions',dict(introEndMs=12000,upNext=False),True)[1]['buttonisdisabled'])

    def test_native_selection_revalidates_cue_and_marker_seek_offset(self):
        self.assertEqual(self.call('SiloUIPlayerAction',0,dict(introEndMs=0,upNext=False),False,2000),dict(kind='tracks'))
        self.assertEqual(self.call('SiloUIPlayerAction',1,dict(introEndMs=12000,upNext=False),False,2000),dict(kind='seek',seconds=10))
        for index, cue, dismissed in [(1,dict(introEndMs=0,upNext=False),False),(1,dict(introEndMs=12000,upNext=False),True),(2,dict(introEndMs=0,upNext=False),False),(-1,dict(introEndMs=12000,upNext=True),False),(3,dict(introEndMs=12000,upNext=True),False)]:
            with self.subTest(index=index,cue=cue,dismissed=dismissed):
                self.assertIsNone(self.call('SiloUIPlayerAction',index,cue,dismissed,2000))
        self.assertEqual(self.call('SiloUIPlayerAction',2,dict(introEndMs=0,upNext=True),False,0),dict(kind='next'))

    def test_native_action_callback_rechecks_current_position_and_ignores_stale_session(self):
        import re
        with tempfile.TemporaryDirectory() as root:
            source = (ROOT / 'components/SiloUIPlayer.brs').read_text()
            source = re.sub(r'sub PlayerShowTracks\(.*?\nend sub', 'sub PlayerShowTracks()\n m.tracksOpened = true\nend sub', source, count=1, flags=re.S)
            source = re.sub(r'sub PlayerAdvance\(.*?\nend sub', 'sub PlayerAdvance()\n m.advanced = true\nend sub', source, count=1, flags=re.S)
            fixture = Path(root) / 'player.brs'
            fixture.write_text(source)
            output = run_brightscript([POLICY,fixture,ROOT / 'source/core/SiloUIFormat.brs', ROOT / 'components/SiloUIScene.brs'], '''
                m.view = "player"
                m.playPlan = {timelineOffsetMs:2000}
                m.playItem = {durationMs:100000}
                m.playMarkers = [{kind:"intro",startMs:1000,endMs:12000}]
                m.playNext = {itemId:"next"}
                m.upNextDismissed = false
                m.introDismissed = false
                m.playerCue = {visible:true}
                m.video = {position:2,duration:98,state:"paused",playbackActionButtonSelected:1,setFocus:function(focused)
                    m.focusRecovered = focused
                    m.focusAfterDisabled = m.playbackActionButtons[1].buttonIsDisabled
                end function}
                onPlayerNativeAction()
                sought = m.video.seek
                resumed = m.video.control
                focusRecovered = m.video.focusRecovered
                focusAfterDisabled = m.video.focusAfterDisabled
                m.video.position = 20
                m.video.seek = -1
                onPlayerNativeAction()
                rejected = m.video.seek
                m.video.playbackActionButtonSelected = 2
                m.advanced = false
                onPlayerNativeAction()
                inactiveNext = m.advanced
                m.video.position = 90
                onPlayerNativeAction()
                activeNext = m.advanced
                m.video.playbackActionButtonSelected = 0
                onPlayerNativeAction()
                opened = m.tracksOpened
                m.tracksOpened = false
                m.view = "home"
                onPlayerNativeAction()
                print FormatJson({sought:sought,resumed:resumed,focusRecovered:focusRecovered,focusAfterDisabled:focusAfterDisabled,rejected:rejected,inactive:inactiveNext,active:activeNext,opened:opened,stale:m.tracksOpened})
            ''',root=Path(root))
        import json
        self.assertEqual(json.loads(output),dict(sought=10,resumed='resume',focusRecovered=True,focusAfterDisabled=True,rejected=-1,inactive=False,active=True,opened=True,stale=False))

    def test_native_action_buttons_update_only_when_applicability_changes(self):
        with tempfile.TemporaryDirectory() as root:
            output = run_brightscript([POLICY,ROOT / 'components/SiloUIPlayer.brs'], '''
                m.video = {}
                m.introDismissed = false
                PlayerUpdateNativeActions({introEndMs:12000,upNext:false})
                m.video.playbackActionButtons = ["sentinel"]
                PlayerUpdateNativeActions({introEndMs:14000,upNext:false})
                retained = m.video.playbackActionButtons[0] = "sentinel"
                PlayerUpdateNativeActions({introEndMs:0,upNext:false})
                print FormatJson({retained:retained,disabled:m.video.playbackActionButtons[1].buttonIsDisabled})
            ''',root=Path(root))
        import json
        self.assertEqual(json.loads(output),dict(retained=True,disabled=True))

    def test_marker_lookup_result_requires_current_item_and_version(self):
        markers = [dict(kind='intro',startMs=1000,endMs=12000)]
        data = dict(itemId='item',versionId='file',markers=markers)
        self.assertEqual(self.call('SiloUIPlayerMarkerResult',data,'item','file'),markers)
        for changed in [dict(data,itemId='old'),dict(data,versionId='old'),dict(data,versionId=''),dict(data,markers=None)]:
            self.assertIsNone(self.call('SiloUIPlayerMarkerResult',changed,'item','file'))

    def test_marker_lookup_runs_once_after_playing_and_rejects_stale_result(self):
        import re
        with tempfile.TemporaryDirectory() as root:
            source = (ROOT / 'components/SiloUIPlayer.brs').read_text()
            source = re.sub(r'sub onPlayerPosition\(.*?\nend sub', 'sub onPlayerPosition()\n m.updated = true\nend sub',source,count=1,flags=re.S)
            source += '''
                sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
                    m.requests.Push({action:action,purpose:purpose,extra:extra})
                end sub
                function FixtureUnusedTextOr(value as Dynamic) as String
                    if value = invalid then return ""
                    return value
                end function
            '''
            fixture = Path(root) / 'player.brs'
            fixture.write_text(source)
            output = run_brightscript([POLICY,ROOT/'source/core/SiloUIFormat.brs',fixture], '''
                m.view = "player"
                m.provider = "silo"
                m.playToken = 5
                m.playPlan = {itemId:"item",versionId:"file"}
                m.playItem = {itemId:"item"}
                m.playMarkers = []
                m.markerLookupStarted = false
                m.requests = []
                m.video = {state:"playing",position:0,duration:100}
                onVideoState()
                onVideoState()
                markers = [{kind:"intro",startMs:1000,endMs:12000}]
                PlayerResult("play_markers",{ok:true},{itemId:"item",versionId:"file",markers:markers},4)
                staleCount = m.playMarkers.Count()
                PlayerResult("play_markers",{ok:true},{itemId:"item",versionId:"old",markers:markers},5)
                wrongCount = m.playMarkers.Count()
                PlayerResult("play_markers",{ok:true},{itemId:"item",versionId:"file",markers:markers},5)
                print FormatJson({requests:m.requests,stale:staleCount,wrong:wrongCount,count:m.playMarkers.Count(),updated:m.updated})
            ''',root=Path(root))
        import json
        self.assertEqual(json.loads(output),dict(requests=[dict(action='markers',purpose='play_markers',extra=5)],stale=0,wrong=0,count=1,updated=True))

    def test_native_track_entry_focuses_picker_and_back_restores_video(self):
        with tempfile.TemporaryDirectory() as root:
            source = (ROOT / 'components/SiloUIPlayer.brs').read_text().replace('CreateObject("roSGNode", "ContentNode")','FakeContent()')
            source += '''
                function FakeContent() as Object
                    return {createChild:function(kind)
                        return {}
                    end function}
                end function
            '''
            fixture = Path(root) / 'player.brs'
            fixture.write_text(source)
            output = run_brightscript([POLICY,fixture,ROOT / 'source/core/SiloUIFormat.brs', ROOT / 'components/SiloUIScene.brs',ROOT / 'source/core/TrackPreference.brs',ROOT / 'components/SiloUIPlaybackChoices.brs',ROOT / 'source/core/SiloPlaybackPolicy.brs'], '''
                m.top = {findNode:function(name)
                    return {visible:false}
                end function}
                m.trackList = {setFocus:sub(focused)
                    m.focused = focused
                end sub}
                m.video = {position:10,duration:100,state:"paused",control:"pause",playbackActionButtonSelected:0,availableAudioTracks:[],availableSubtitleTracks:[],setFocus:sub(focused)
                    m.focused = focused
                end sub}
                m.view = "player"
                m.nativeActionsActive = true
                m.playPlan = {}
                m.playItem = {durationMs:100000}
                m.playMarkers = []
                m.playNext = invalid
                m.upNextDismissed = false
                m.introDismissed = false
                onPlayerNativeAction()
                focused = m.trackList.focused
                shown = m.trackDialog.visible
                PlayerKey("back")
                print FormatJson({focused:focused,shown:shown,video:m.video.focused,closed:m.trackDialog = invalid,control:m.video.control})
            ''',root=Path(root))
        import json
        self.assertEqual(json.loads(output),dict(focused=True,shown=True,video=True,closed=True,control="pause"))
