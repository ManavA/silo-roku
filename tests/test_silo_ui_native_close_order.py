"""Native close ordering at the actual Scene ApiTask dispatch boundary."""
import unittest
from tests import test_silo_ui_subtitle_off_flow as subtitle_flow

class NativeCloseOrder(unittest.TestCase):
    def scene(self, body, **kwargs):
        return subtitle_flow.SubtitleOffFlow().scene(body, actual_results=True, actual_owned=True,
                                       actual_report=True, **kwargs)

    def test_native_stop_requested_before_logical_stop_with_pre_stop_sample(self):
        for state in ('playing', 'paused'):
            with self.subTest(state=state):
                value=self.scene('''m.video.state="'''+state+'''":m.video.control="play"
 m.resetAtTaskBoundary=true
 PlayerClose(false,false)
 print FormatJson({control:m.fixtureTasks[0].nativeControl,job:m.fixtureTasks[0].job,sequence:m.progressSequence})''')
                self.assertEqual('stop',value['control'])
                self.assertEqual('playback_stop',value['job']['action'])
                self.assertEqual(157500,value['job']['params']['positionMs'])
                self.assertEqual(state=='paused',value['job']['params']['isPaused'])
                self.assertEqual(10,value['job']['params']['sequence'])
                self.assertEqual(10,value['sequence'])

    def test_guarded_original_stop_reset_preserves_final_paused_sample(self):
        value=self.scene('''m.video.control="play":m.video.state="paused"
 m.originalPlayback={phase:"verified_playing"}
 m.video.SetFields=sub(fields as Object)
 m.control=fields.control:m.state="stopped":m.position=0
 end sub
 PlayerClose(false,false)
 print FormatJson({control:m.fixtureTasks[0].nativeControl,params:m.fixtureTasks[0].job.params})''')
        self.assertEqual('stop',value['control'])
        self.assertEqual(157500,value['params']['positionMs'])
        self.assertTrue(value['params']['isPaused'])
        self.assertEqual(10,value['params']['sequence'])

    def test_unverified_original_keeps_pinned_resume_and_does_not_finish(self):
        value=self.scene('''m.playLastPositionMs=123456:m.playItem={resumeMs:5,watched:false}
 m.originalPlayback={phase:"loading"}:m.video.state="paused"
 m.video.SetFields=sub(fields as Object)
 m.control=fields.control:m.state="stopped":m.position=0
 end sub
 PlayerClose(true,false)
 print FormatJson({params:m.fixtureTasks[0].job.params,resume:m.playItem.resumeMs,watched:m.playItem.watched})''')
        self.assertEqual(123456,value['params']['positionMs'])
        self.assertTrue(value['params']['isPaused'])
        self.assertEqual(123456,value['resume'])
        self.assertFalse(value['watched'])

    def test_plex_mapping_uses_captured_pause_and_source_position(self):
        for paused in (False,True):
            with self.subTest(paused=paused):
                value=self.scene('''m.provider="plex":m.video.control="play"
 m.video.state="'''+('paused' if paused else 'playing')+'''"
 m.playPlan["itemId"]="plex-item":m.playPlan["durationMs"]=200000:m.playPlan["transcodeSessionId"]="plex-transcode"
 m.originalPlayback={phase:"verified_playing"}
 m.video.SetFields=sub(fields as Object)
 m.control=fields.control:m.state="stopped":m.position=0
 end sub
 PlayerClose(false,false)
 print FormatJson({control:m.fixtureTasks[0].nativeControl,job:m.fixtureTasks[0].job})''')
                self.assertEqual('stop',value['control'])
                self.assertEqual('plex',value['job']['provider'])
                self.assertEqual(dict(itemId='plex-item',durationMs=200000,
                                      transcodeSessionId='plex-transcode',positionMs=157500,
                                      state='paused' if paused else 'playing'),value['job']['params'])

    def test_seek_close_keeps_captured_owner_trusted_sample_and_desired_pause(self):
        value=self.scene('''m.video.control="play":m.video.state="playing"
 m.playPlan["stopId"]="stable-close-id"
 m.seekReanchor={targetMs:190000,lastObservedMs:123456,desiredPaused:true,owner:m.playPlan.cleanupOwner}
 PlayerClose(false,false)
 ticket=m.cleanupTickets[m.cleanupTickets.Keys()[0]]
 print FormatJson({control:m.fixtureTasks[0].nativeControl,job:m.fixtureTasks[0].job,owner:ticket.owner})''')
        self.assertEqual('stop',value['control'])
        self.assertEqual(123456,value['job']['params']['positionMs'])
        self.assertTrue(value['job']['params']['isPaused'])
        self.assertTrue(value['job']['params']['persistProgress'])
        self.assertEqual('stable-close-id',value['job']['params']['stopId'])
        self.assertEqual(10,value['job']['params']['sequence'])
        self.assertEqual(7,value['owner']['generation'])
        self.assertEqual(0,value['owner']['sessionRevision'])
        self.assertEqual('silo:synthetic',value['job']['sourceId'])
        self.assertEqual('owner',value['job']['profileId'])

    def test_progress_without_final_sample_keeps_live_pause_and_next_sequence(self):
        value=self.scene('''m.video.state="paused":m.video.control="play"
 PlayerReport("playback_progress")
 print FormatJson({control:m.fixtureTasks[0].nativeControl,params:m.fixtureTasks[0].job.params})''')
        self.assertEqual('play',value['control'])
        self.assertEqual(157500,value['params']['positionMs'])
        self.assertTrue(value['params']['isPaused'])
        self.assertEqual(10,value['params']['sequence'])

    def test_outside_player_without_sequence_still_retires_original_before_return(self):
        value=self.scene('''m.view="home":m.progressSequence=invalid
 m.originalPlayback={phase:"loading"}:m.originalTimer={}
 m.video.SetFields=sub(fields as Object)
 m.control=fields.control:m.state="stopped":m.position=0
 end sub
 PlayerClose(false,false)
 print FormatJson({view:m.view,originalCleared:m.originalPlayback=invalid,control:m.video.control,requests:m.requestId,sequence:m.progressSequence})''')
        self.assertEqual(dict(view='home',originalCleared=True,control='stop',
                              requests=0,sequence=None),value)
