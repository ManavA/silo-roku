"""Support messages and one fresh inventory read remain separate from decoding."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function, run_brightscript
ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT/'source/adapters/SiloAdapter.brs', ROOT/'components/SiloUIRobustness.brs', ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'source/core/SiloUIPlayerPolicy.brs', ROOT/'source/core/SiloUIFormat.brs', ROOT/'source/core/SiloUIDetailPolicy.brs', ROOT/'components/SiloUISubtitleArtifact.brs']

class SiloUIPlaybackErrors(unittest.TestCase):
    def test_native_error_number_is_retained_but_arbitrary_native_text_is_not(self):
        value=run_function(FILES,'SiloUIPlaybackFailureMessage',['native',{'nativeCode':-5}])
        self.assertIn('#3001',value)
        self.assertIn('Roku -5',value)
        for native in ('private-token',True,1234567,1.5):
            value=run_function(FILES,'SiloUIPlaybackFailureMessage',['native',{'nativeCode':native}])
            self.assertNotIn('(Roku ',value)
            self.assertNotIn('private',value)

    def test_native_video_error_is_captured_before_player_cleanup(self):
        value=self.result('''m.view="player":m.video={state:"error",errorCode:-5}
 onVideoState()''')
        self.assertEqual(['closed','dialog'],value['events'])
        self.assertIn('#3001',value['message'])
        self.assertIn('Roku -5',value['message'])

    def test_finished_requires_observed_selected_file_tail_before_watched_or_next(self):
        for position, expected in [(600000, False), (7195000, True)]:
            value=self.result('''m.view="player":m.nativeSeenPlaying=true
 m.playPlan={provider:"silo",sourceId:"silo:fixture",itemId:"item",versionId:"file"}
 m.playVersions=[{sourceId:"silo:fixture",itemId:"item",versionId:"file",durationMs:7200000}]
 m.video={state:"finished",position:0,duration:600}:m.playLastPositionMs='''+str(position)+"\n onVideoState()")
            self.assertEqual(expected,value['finished'])

    def test_short_selected_file_requires_its_tail(self):
        for position, expected in [(0, False), (200, False), (3000, True), (3900, True)]:
            value=self.result('''m.view="player":m.nativeSeenPlaying=true
 m.playPlan={sourceId:"silo:fixture",itemId:"item",versionId:"clip"}
 m.playVersions=[{sourceId:"silo:fixture",itemId:"item",versionId:"clip",durationMs:4000}]
 m.video={state:"finished",position:0,duration:0}:m.playLastPositionMs='''+str(position)+"\nonVideoState()")
            self.assertEqual(expected,value['finished'])

    def test_finished_before_paused_resume_lands_preserves_resume_and_pause_intent(self):
        value=self.result('''m.view="player":m.audioRestorePause=true:m.playLastPositionMs=119500
 m.playPlan={provider:"plex",startPositionMs:119500}
 m.video={state:"playing",position:0,duration:120}
 onVideoState()
 m.video.state="finished"
 onVideoState()''',provider='plex')
        self.assertFalse(value['finished'])
        self.assertTrue(value['restorePause'])
        self.assertEqual(119500,value['position'])

    def test_finished_uses_rebased_native_duration_and_preserves_unknown_resume(self):
        cases = [("m.playPlan.timelineOffsetMs=600000:m.video.duration=1200:m.video.position=1195", True),
                 ("m.video.duration=0", False),
                 ("m.video.duration=4:m.video.position=3.9", True),
                 ("m.video.duration=4:m.video.position=0.2", False)]
        for change, expected in cases:
            with self.subTest(change=change):
                value=self.result('''m.view="player":m.nativeSeenPlaying=true
 m.playPlan={provider:"plex"}:m.video={state:"finished",position:0,duration:0}:m.playLastPositionMs=600000
 '''+change+"\nonVideoState()")
                self.assertEqual(expected,value['finished'])
                if change == "m.video.duration=0": self.assertEqual(600000,value['position'])

    def test_finished_during_navigation_or_recovery_does_not_close(self):
        for change in ('m.view="detail"', 'm.transitionIntent={}', 'm.recoveringNative=true', 'm.seekReanchor={}', 'm.nativePlaybackOwner={provider:"silo",sourceId:"other"}', 'm.nativePlaybackOwner=SiloUIOwner():m.nativePlaybackToken=4'):
            value=self.result('''m.view="player":m.nativeSeenPlaying=true:m.playPlan={provider:"plex"}
 m.video={state:"finished",position:600,duration:7200}:m.playLastPositionMs=600000
 '''+change+"\nonVideoState()")
            self.assertEqual([],value['events'])

    def test_frozen_native_playing_uses_bounded_recovery_or_timeout(self):
        value=self.result('''m.view="player":m.playLoading=false:m.progressSequence=0
 m.playPlan={provider:"silo",sessionId:"session"}:m.video={state:"playing",position:60}
 m.nativePlaybackOwner=SiloUIOwner():m.nativePlaybackToken=5
 onProgressTimer()
 m.nativeMovementClock={TotalMilliseconds:function()
 return 120000
 end function}
 onProgressTimer()''')
        self.assertEqual(['closed','dialog'],value['events'])
        self.assertIn('#3002',value['message'])
        self.assertEqual(60000,value['position'])

    def test_native_movement_deadline_resets_on_movement_and_preserves_recovery(self):
        for change in ('m.video.position=61', 'm.video.position=30', 'm.recoveryAccepted=true'):
            with self.subTest(change=change):
                value=self.result(self.native_stall_setup()+change+"\nonProgressTimer()")
                self.assertEqual([],value['events'])
                if change == 'm.recoveryAccepted=true':
                    self.assertEqual('buffering_timeout',value['recoveryReason'])
                else:
                    self.assertIsNone(value['recoveryReason'])

    def test_native_movement_restarts_full_grace_period(self):
        value=self.result(self.native_stall_setup()+'''m.video.position=61
 onProgressTimer()
 m.nativeMovementClock={TotalMilliseconds:function()
 return 119999
 end function}
 onProgressTimer()''')
        self.assertEqual([],value['events'])
        self.assertIsNone(value['recoveryReason'])

    def test_native_movement_deadline_ignores_inactive_or_owned_routes(self):
        changes = ('m.video.state="paused"', 'm.audioRestorePause=true', 'm.pauseRestoreMuted=true',
                   'm.playbackChoiceBusy=true', 'm.subtitleChange={}', 'm.transitionIntent={}',
                   'm.view="detail"', 'm.recoveringNative=true', 'm.seekReanchor={}',
                   'm.nativePlaybackOwner.sourceId="other"', 'm.nativePlaybackToken=4',
                   'm.playPlan.originalPlayback={}', 'm.playPlan.experimentalOriginal=true', 'm.playPlan.transport="silo_compat"')
        for change in changes:
            with self.subTest(change=change):
                value=self.result(self.native_stall_setup()+change+"\nonProgressTimer()")
                self.assertEqual([],value['events'])
                self.assertIsNone(value['recoveryReason'])
                self.assertTrue(value['movementReset'])

    def native_stall_setup(self):
        return '''m.view="player":m.playLoading=false:m.progressSequence=0
 m.playPlan={provider:"silo",sessionId:"session"}:m.video={state:"playing",position:60}
 m.nativePlaybackOwner=SiloUIOwner():m.nativePlaybackToken=5
 onProgressTimer()
 m.nativeMovementClock={TotalMilliseconds:function()
 return 120000
 end function}
 '''

    def test_recovery_deadline_uses_existing_timeout_presentation(self):
        text=run_function(FILES,'SiloUIPlaybackFailureMessage',['recovery',{'errorCode':'network_timeout'}])
        self.assertEqual('#3002: Playback did not become ready in time. Check the connection and try a lower quality.',text)

    def test_support_codes_are_distinct_and_never_echo_untrusted_text(self):
        cases = [('inventory_empty','1001'),('inventory_invalid','1002'),
                 ('selected_missing','1003'),('detail','1004'),
                 ('native','3001'),('timeout','3002'),
                 ('recovery','3003'),('session','3004'),('prepare','2001')]
        for stage, code in cases:
            with self.subTest(stage=stage):
                text = run_function(FILES,'SiloUIPlaybackFailureMessage',
                    [stage, {'errorCode':'private-token','reason':'https://private.invalid/token','message':'secret'}])
                self.assertIn('#'+code, text)
                self.assertNotIn('private', text)
                self.assertNotIn('secret', text)
        text=run_function(FILES,'SiloUIPlaybackFailureMessage',['inventory_empty',{}])
        self.assertIn('profile',text)
        self.assertIn('library',text)

    def test_allowlisted_prepare_reasons_have_safe_specific_codes(self):
        for result, code in [({'reason':'hdr_transcode_unsupported'},'2004'),
                             ({'reason':'dv_conversion_unsupported'},'2004'),
                             ({'reason':'audio_conversion_unsupported'},'2005'),
                             ({'reason':'subtitle_conversion_unsupported'},'2006'),
                             ({'errorCode':'unsupported_playback_protocol'},'2007'),
                             ({'errorCode':'unsupported_stream'},'2008')]:
            with self.subTest(result=result):
                text=run_function(FILES,'SiloUIPlaybackFailureMessage',['prepare',result])
                self.assertIn('#'+code,text)

    def test_numeric_code_api_includes_no_source_and_no_alternate(self):
        for result, expected in [({'reason':'no_playable_source'},'2002'),({'reason':'no_alternate_version'},'2003')]:
            self.assertEqual(expected,run_function(FILES,'SiloUIPlaybackFailureCode',['prepare',result]))
            self.assertIn('#'+expected,run_function(FILES,'SiloUIPlaybackFailureMessage',['prepare',result]))
        message=run_function(FILES,'SiloUIPlaybackFailureMessage',['prepare',{'reason':'no_alternate_version'}])
        self.assertIn('selected version',message)
        self.assertIn('Auto',message)

    def test_server_policy_storage_and_tool_failures_have_distinct_numbers(self):
        for reason,number in [('transcoding_disabled','2009'),('conversion_tool_unavailable','2010'),
                              ('source_metadata_incomplete','2011'),('source_unreadable','2012'),
                              ('bitrate_policy_unavailable','2013'),('adaptation_exhausted','2014')]:
            self.assertEqual(number,run_function(FILES,'SiloUIPlaybackFailureCode',['prepare',{'reason':reason}]))

    def test_conversion_start_failure_has_local_code_while_unknown_and_network_failures_stay_general(self):
        failure={'errorCode':'playback_terminal','reason':'transcode_start_failed','message':'private server detail'}
        self.assertEqual('2016',run_function(FILES,'SiloUIPlaybackFailureCode',['prepare',failure]))
        message=run_function(FILES,'SiloUIPlaybackFailureMessage',['prepare',failure])
        self.assertEqual('#2016: The server could not start conversion for this playback. Check server conversion settings and try again.',message)
        self.assertNotIn('private',message)
        self.assertEqual('2001',run_function(FILES,'SiloUIPlaybackFailureCode',['prepare',{'errorCode':'playback_terminal','reason':'future_private_reason'}]))
        self.assertEqual('2001',run_function(FILES,'SiloUIPlaybackFailureCode',['prepare',{'errorCode':'network_error'}]))
        self.assertEqual('#2001: The app could not connect to the server. Check the server address and connection, then retry.',
                         run_function(FILES,'SiloUIPlaybackFailureMessage',['prepare',{'errorCode':'network_error'}]))

    def test_standard_failure_dialog_persists_and_ok_or_back_restores_focus(self):
        for method in ('ok','back'):
            with self.subTest(method=method):
                body='''PlayerShowFailure("inventory_empty",{})
 event={node:m.top.dialog,getRoSGNode:function()
 return m.node
 end function}
'''
                if method=='ok':body+='onPlayerFailureChoice(event)\n'
                body+='onPlayerFailureClosed(event)'
                value=self.result(body)
                self.assertEqual('Playback error',value['dialog']['title'])
                self.assertEqual(['OK','Device info'],value['dialog']['buttons'])
                self.assertIn('#1001',value['message'])
                self.assertEqual(['detailButtons'],value['restored'])
                if method=='ok':self.assertTrue(value['dialog']['close'])

    def test_stale_dialog_close_does_not_restore_old_focus(self):
        result=self.result('''PlayerShowFailure("detail",{})
 event={node:m.top.dialog,getRoSGNode:function()
 return m.node
 end function}
 PlayerShowFailure("inventory_empty",{})
 onPlayerFailureClosed(event)''')
        self.assertEqual([],result['restored'])
        self.assertIn('#1001',result['message'])

    def test_original_timeout_exhaustion_closes_then_shows_persistent_error(self):
        value=self.result('''PlayerOriginalApply({state:invalid,command:{kind:"recover",reason:"startup_timeout"}})''')
        self.assertEqual(['closed','dialog'],value['events'])
        self.assertIn('#3002',value['message'])

    def test_error_dialog_has_no_automatic_close_and_navigation_invalidates_focus_restore(self):
        value=self.result('PlayerShowFailure("detail",{})')
        self.assertIsNone(value['dialog']['close'])
        value=self.result('''PlayerShowFailure("detail",{})
 event={node:m.top.dialog,getRoSGNode:function()
 return m.node
 end function}
 m.generation=2
 onPlayerFailureClosed(event)''')
        self.assertEqual([],value['restored'])

    def test_report_is_queued_after_dialog_and_ack_is_required_for_sent_message(self):
        value=self.result('''PlayerShowFailure("prepare",{errorCode:"playback_terminal",reason:"hdr_transcode_unsupported",report:{installationId:"install",playbackAttemptId:"attempt-0001"}})''')
        self.assertEqual(['dialog','report'],value['events'])
        self.assertEqual('playback_error_report',value['sent'][0]['action'])
        self.assertEqual('2004',value['sent'][0]['params']['supportCode'])
        self.assertNotIn('Report sent',value['message'])
        value=self.result('''PlayerShowFailure("prepare",{errorCode:"playback_terminal",report:{installationId:"install",playbackAttemptId:"attempt-0001"}})
 PlayerResult("play_error_report",{ok:true},{reported:true},m.sent[0].extra)''')
        self.assertIn('Report sent to your Silo server.',value['message'])

    def test_inventory_never_reports_and_old_dialog_ack_cannot_update_new_error(self):
        value=self.result('''PlayerShowFailure("inventory_empty",{report:{installationId:"install",playbackAttemptId:"attempt-0001"}})''')
        self.assertEqual([],value['sent'])
        value=self.result('''PlayerShowFailure("prepare",{errorCode:"playback_terminal",report:{installationId:"install",playbackAttemptId:"attempt-0001"}})
 old=m.sent[0].extra
 PlayerShowFailure("inventory_empty",{})
 PlayerResult("play_error_report",{ok:true},{reported:true},old)''')
        self.assertNotIn('Report sent',value['message'])
        self.assertIn('#1001',value['message'])

    def test_native_attempt_snapshot_survives_cleanup_without_extra_private_fields(self):
        value=self.result('''m.playPlan={provider:"silo",sourceId:"silo:fixture",sessionId:"session",siloPlayback:{sourceId:"silo:fixture",profileId:"profile",sessionId:"session",installationId:"install",playbackAttemptId:"attempt-0001",planId:"private-plan"}}
 PlayerOriginalApply({state:invalid,command:{kind:"recover",reason:"startup_timeout"}})''')
        self.assertEqual(['closed','dialog','report'],value['events'])
        self.assertEqual({'installationId':'install','playbackAttemptId':'attempt-0001','sessionId':'session'},value['sent'][0]['params']['report'])
        self.assertEqual('3002',value['sent'][0]['params']['supportCode'])

    def test_report_ack_is_ignored_after_dismissal_or_scope_change_and_false_receipt(self):
        start='''PlayerShowFailure("prepare",{errorCode:"playback_terminal",report:{installationId:"install",playbackAttemptId:"attempt-0001"}})
 ticket=m.sent[0].extra
'''
        for change,receipt in [('m.profileId="other"','true'),('m.generation=2','true'),('m.playbackFailureDialog.close=true','true'),('','false')]:
            value=self.result(start+change+'\nPlayerResult("play_error_report",{ok:true},{reported:'+receipt+'},ticket)')
            self.assertNotIn('Report sent',value['message'])

    def result(self, code, provider='silo'):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerResetChrome(', 'sub UnusedPlayerResetChrome(',1).replace('sub PlayerDiscardPrebuffer(', 'sub UnusedPlayerDiscardPrebuffer(',1).replace('CreateObject("roSGNode", "Dialog")','FixtureDialog()').replace('sub PlayerClose(', 'sub UnusedPlayerClose(',1).replace('function PlayerRecoverNativeFailure(', 'function UnusedPlayerRecoverNativeFailure(',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''sub HomeCacheYield()
end sub
sub SiloUISeekObserve()
end sub
sub onSeekReanchorTimer()
end sub
sub PlayerClose(finished as Boolean)
 m.events.Push("closed")
 m.finished=finished
 m.closedPosition=m.playLastPositionMs
 if m.video <> invalid
     if m.video.state = "finished" then m.closedPosition=PlayerPositionMs()
 end if
 m.playPlan=invalid
 m.view="detail"
end sub
function PlayerRecoverNativeFailure(reason as String) as Boolean
 m.recoveryReason=reason
 return m.recoveryAccepted=true
end function
function FixtureDialog()
 m.events.Push("dialog")
 m.dialogId=m.dialogId+1
 return {id:m.dialogId,buttonSelected:0,observeField:sub(field,handler)
 end sub,isSameNode:function(other)
 return m.id=other.id
 end function}
end function
sub SetZone(zone as String)
 m.restored.Push(zone)
end sub
sub PlayerResetChrome()
end sub
sub PlayerDiscardPrebuffer()
end sub
function HomeProgressScope() as Object
 return {}
end function
function SiloUISettingsPlayback(provider as String, preferences as Dynamic) as Object
 return {}
end function
function SiloUISettingsPreferences(preferences as Dynamic) as Object
 return {subtitles:"auto",quality:"original"}
end function
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.sent.Push({action:action,params:params,purpose:purpose,extra:extra})
 if action="playback_error_report" then m.events.Push("report")
end sub
sub Toast(message as String)
 m.message=message
end sub
''')
            setup='m.provider="'+provider+'":m.playToken=5:m.playItem={itemId:"item"}:m.playLoading=true:m.playStartMs=0:m.playSelectedVersion="":m.playClock=CreateObject("roTimespan"):m.sent=[]:m.pending={}:m.top={}:m.dialogId=0:m.view="detail":m.zone="detailButtons":m.generation=1:m.restored=[]:m.events=[]:m.sourceId="silo:fixture":m.profileId="profile"\n'
            out=run_brightscript([*FILES,ROOT/'components/SiloUICompatPlayback.brs',player,boundary],setup+code+'\nmessage=m.message:dialog=m.top.dialog:shown=invalid\nif dialog<>invalid\n message=dialog.message\n shown={title:dialog.title,message:dialog.message,buttons:dialog.buttons,close:dialog.close}\nend if\nprint FormatJson({sent:m.sent,message:message,loading:m.playLoading,dialog:shown,restored:m.restored,events:m.events,finished:m.finished,position:m.closedPosition,restorePause:m.audioRestorePause,recoveryReason:m.recoveryReason,movementReset:m.nativeMovementClock=invalid})',root=root)
            return json.loads(out[out.index('{'):],strict=False)

    def test_empty_silo_inventory_gets_exactly_one_fresh_detail_then_access_hint(self):
        result=self.result('''PlayerResult("play_detail",{ok:true},{item:{itemId:"item"},versions:[]},5)
 PlayerResult("play_detail",{ok:true},{item:{itemId:"item"},versions:[]},5)''')
        self.assertEqual([{'action':'detail','params':{'itemId':'item'},'purpose':'play_detail','extra':5}],result['sent'])
        self.assertIn('#1001',result['message'])
        self.assertFalse(result['loading'])

    def test_retry_then_valid_inventory_prepares_once_without_another_detail(self):
        result=self.result('''PlayerResult("play_detail",{ok:true},{item:{itemId:"item"},versions:[]},5)
 PlayerResult("play_detail",{ok:true},{item:{itemId:"item",resumeMs:0},versions:[{versionId:"file"}]},5)''')
        self.assertEqual(['detail','playback_start'],[request['action'] for request in result['sent']])
        self.assertEqual('file',result['sent'][1]['params']['fileId'])

    def test_normal_inventory_has_no_extra_detail_and_selected_missing_has_own_code(self):
        result=self.result('''m.playStartMs=0:m.playSelectedVersion=""
 PlayerResult("play_detail",{ok:true},{item:{itemId:"item",resumeMs:0},versions:[{versionId:"file"}]},5)''')
        self.assertEqual(['playback_start'],[request['action'] for request in result['sent']])
        result=self.result('''m.playSelectedVersion="gone"
 PlayerResult("play_detail",{ok:true},{item:{itemId:"item"},versions:[{versionId:"file"}]},5)''')
        self.assertEqual([],result['sent'])
        self.assertIn('#1003',result['message'])

    def test_new_play_visit_resets_empty_retry_and_stale_response_cannot_consume_it(self):
        result=self.result('''m.playDetailEmptyRetries=1
 PlayItem({itemId:"new-item",title:"Title"},0)
 PlayerResult("play_detail",{ok:true},{item:{itemId:"item"},versions:[]},5)
 PlayerResult("play_detail",{ok:true},{item:{itemId:"new-item"},versions:[]},6)''')
        self.assertEqual(['detail','detail'],[request['action'] for request in result['sent']])
        self.assertTrue(all(request['extra']==6 for request in result['sent']))
        self.assertTrue(all(request['params']['itemId']=='new-item' for request in result['sent']))

    def test_invalid_failure_stale_and_plex_never_retry(self):
        for body,provider,expected in [
            ('PlayerResult("play_detail",{ok:true},{item:{itemId:"item"}},5)','silo','1002'),
            ('PlayerResult("play_detail",{ok:false},{versions:[]},5)','silo','1004'),
            ('PlayerResult("play_detail",{ok:true},{item:{itemId:"item"},versions:[]},4)','silo',None),
            ('PlayerResult("play_detail",{ok:true},{item:{itemId:"item"},versions:[]},5)','plex','1001')]:
            with self.subTest(body=body,provider=provider):
                result=self.result(body,provider)
                self.assertEqual([],result['sent'])
                if expected:self.assertIn('#'+expected,result['message'])

if __name__=='__main__': unittest.main()
