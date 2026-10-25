"""Playback explanations at public policy and actual Scene callback boundaries."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tools.brightscript import run_function, run_brightscript

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUIPlayerPolicy.brs'

class PlaybackPresentation(unittest.TestCase):
    def test_missing_device_delivery_has_a_distinct_actionable_error(self):
        value = run_function([POLICY, ROOT/'source/core/SiloUIFormat.brs'],
                             'SiloUIPlaybackFailureMessage',
                             ['prepare', {'errorCode':'unsupported_device','message':'private-token'}])
        self.assertTrue(value.startswith('#2015:'), value)
        self.assertIn('compatible playback route', value)
        self.assertIn('Roku', value)
        self.assertNotIn('private', value)

    def scene(self, body):
        files = [ROOT/script.attrib['uri'].removeprefix('pkg:/')
                 for script in ET.parse(ROOT/'components/SiloUIScene.xml').getroot().findall('script')]
        setup = '''
 m.view="player":m.provider="plex":m.playToken=8:m.generation=3
 m.backdropTimer={}:m.backdropFade={}:m.backdrop={}:m.backdropOld={}
 m.playPlan={provider:"plex",playbackDiagnostics:{delivery:"server_remux_hls"}}
 m.playerStatusPanel=CreateObject("roSGNode","Group")
 m.playerStatusPanel.visible=false
 m.playerStatusTitle=CreateObject("roSGNode","Label")
 m.playerStatusDetail=CreateObject("roSGNode","Label")
 m.video=CreateObject("roSGNode","Node")
 m.video.AddFields({state:"buffering",mute:false,position:0,duration:100})
 '''
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            # The interpreter has no active SDK host for observeField. Emulate
            # only the Task node fields/observer registration, never Api bodies.
            local=folder/'SiloUIScene.brs'
            local.write_text((ROOT/'components/SiloUIScene.brs').read_text().replace(
                'CreateObject("roSGNode", "ApiTask")','FixturePresentationTask()'))
            files=[local if path.name=='SiloUIScene.brs' else path for path in files]
            sdk=folder/'sdk.brs'
            sdk.write_text('''function FixturePresentationTask() as Object
 return {job:invalid,result:invalid,control:"",cancelled:false,observeField:sub(field as String,callback as String)
 end sub}
end function''')
            output = run_brightscript([*files,sdk],setup+body,root=folder)
        return json.loads(output.strip().splitlines()[-1])

    def test_current_video_buffering_explains_confirmed_route_then_hides_on_pause(self):
        value=self.scene('''onVideoState()
 shown={visible:m.playerStatusPanel.visible,title:m.playerStatusTitle.text,detail:m.playerStatusDetail.text}
 m.video.state="paused":onVideoState()
 print FormatJson({shown:shown,afterPause:m.playerStatusPanel.visible})''')
        self.assertTrue(value['shown']['visible'])
        self.assertEqual('Buffering…',value['shown']['title'])
        self.assertEqual('Remux · Repackaging video without changing its codec.', value['shown']['detail'])
        self.assertFalse(value['afterPause'])

    def test_old_video_playing_cannot_dismiss_recovery_status(self):
        value=self.scene('''onVideoState()
 m.recoveringNative=true:m.playLoading=true
 m.video.state="playing":onVideoState()
 print FormatJson({visible:m.playerStatusPanel.visible})''')
        self.assertTrue(value['visible'])

    def test_playing_hides_status_and_stale_result_cannot_change_new_status(self):
        value=self.scene('''onVideoState()
 PlayerResult("play_start",{ok:false,errorCode:"private-token"},{},7)
 retained=m.playerStatusPanel.visible
 m.markerLookupStarted=true:m.video.state="playing":onVideoState()
 print FormatJson({retained:retained,playing:m.playerStatusPanel.visible})''')
        self.assertTrue(value['retained'])
        self.assertFalse(value['playing'])

    def test_cancel_preparation_retires_panel_and_late_failure_stays_dismissed(self):
        value=self.scene('''onVideoState()
 m.view="detail":m.playLoading=true
 PlayerCancelPreparation()
 PlayerResult("play_start",{ok:false,errorCode:"unsupported_device"},{},8)
 print FormatJson({visible:m.playerStatusPanel.visible,loading:m.playLoading,token:m.playToken})''')
        self.assertFalse(value['visible'])
        self.assertFalse(value['loading'])
        self.assertEqual(9,value['token'])

    def test_phase_explanations_never_claim_unconfirmed_route_or_echo_metadata(self):
        for phase in ('request','prepare','recovery','version'):
            with self.subTest(phase=phase):
                value=run_function([POLICY],'SiloUIPlaybackStatus',[phase,{'playbackDiagnostics':{'delivery':'server_transcode_hls'}}])
                self.assertTrue(value['title'])
                self.assertNotIn('Transcode',value['detail'])
        value=run_function([POLICY],'SiloUIPlaybackStatus',['buffering',{'playbackDiagnostics':{'delivery':'https://private.invalid/token'}}])
        self.assertEqual('Waiting for video from the server.',value['detail'])

    def test_old_playing_during_new_preparation_cannot_dismiss_status(self):
        value=self.scene('''onVideoState()
 m.playLoading=true:m.markerLookupStarted=true
 m.video.state="playing":onVideoState()
 print FormatJson({visible:m.playerStatusPanel.visible})''')
        self.assertTrue(value['visible'])

    def test_native_failures_explain_a_useful_next_action(self):
        for stage in ('native','timeout','recovery'):
            with self.subTest(stage=stage):
                value=run_function([POLICY,ROOT/'source/core/SiloUIFormat.brs'],
                                   'SiloUIPlaybackFailureMessage',[stage,{}])
                self.assertTrue(any(word in value for word in ('Try','Check','Choose')),value)


    def test_play_request_then_detail_callback_explains_real_queued_phase(self):
        value=self.scene('''m.view="detail":m.playPlan=invalid:m.provider="plex"
 m.sourceId="plex:fixture":m.profileId="owner":m.pending={}:m.requestId=0
 m.upNextTimer={}:m.playerCue={}:m.video.AddFields({playbackActionButtons:[]})
 PlayItem({itemId:"film",type:"movie",title:"Film"},0)
 opening={title:m.playerStatusTitle.text,action:m.pending["1"].task.job.action}
 PlayerResult("play_detail",{ok:true},{item:{itemId:"film",type:"movie"},versions:[{versionId:"file",resolution:"1080p"}]},m.playToken)
 print FormatJson({opening:opening,preparing:m.playerStatusTitle.text,action:m.pending["2"].task.job.action,visible:m.playerStatusPanel.visible})''')
        self.assertEqual({'title':'Opening title…','action':'detail'},value['opening'])
        self.assertEqual('Preparing playback…',value['preparing'])
        self.assertEqual('playback_start',value['action'])
        self.assertTrue(value['visible'])

    def test_optional_error_report_accepts_distinct_device_route_support_code(self):
        from tests.test_silo_error_reporting import PARAMS, EVENT_ID
        params=dict(PARAMS,supportCode='2015',errorCode='unsupported_device',eventId=EVENT_ID)
        value=run_function([ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/core/SiloPlaybackPolicy.brs'],
                           'SiloPlaybackErrorBody',[params])
        self.assertTrue(value['ok'],value)
        self.assertEqual('2015',value['body']['diagnostics']['error_code'])

    def test_navigation_retires_buffering_panel_before_cleanup_screen(self):
        value=self.scene('''onVideoState()
 m.top=CreateObject("roSGNode","Group")
 for each name in ["home","detail","library","libraries","search","onboarding","audio","audioBrowse","streaming","ebook","ebookBrowse","fadeLeft","fadeBottom"]
  node=m.top.createChild("Group"):node.id=name
 end for
 m.nav={}:m.backdrop={}:m.backdropOld={}
 ShowView("onboarding")
 print FormatJson({visible:m.playerStatusPanel.visible,view:m.view})''')
        self.assertFalse(value['visible'])
        self.assertEqual('onboarding',value['view'])

    def test_known_prepare_errors_explain_safe_cause_without_server_text(self):
        cases={'auth_required':'Sign in','forbidden':'permission','not_found':'endpoint',
               'network_timeout':'timed out','network_error':'connection',
               'rate_limited':'requests','server_error':'server','task_failed':'app'}
        for error,word in cases.items():
            with self.subTest(error=error):
                value=run_function([POLICY,ROOT/'source/core/SiloUIFormat.brs'],
                                   'SiloUIPlaybackFailureMessage',
                                   ['prepare',{'errorCode':error,'message':'private-token'}])
                self.assertTrue(value.startswith('#2001:'),value)
                self.assertIn(word,value)
                self.assertNotIn('private',value)
