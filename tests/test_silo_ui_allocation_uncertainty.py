"""Scene allocation ownership, through real callbacks and native SDK seams."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class AllocationUncertainty(unittest.TestCase):
    def scene(self, body):
        files = [ROOT / s.attrib['uri'].removeprefix('pkg:/')
                 for s in ET.parse(ROOT / 'components/SiloUIScene.xml').getroot().findall('script')]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ('SiloUIScene.brs', 'SiloUIPlayer.brs', 'SiloUIRobustness.brs', 'SiloUIAudio.brs'):
                path = folder / name
                path.write_text((ROOT / 'components' / name).read_text()
                    .replace('CreateObject("roSGNode", "ApiTask")', 'FixtureTask()')
                    .replace('CreateObject("roSGNode", "Dialog")', 'FixtureDialog()')
                    .replace('CreateObject("roDeviceInfo")', 'FixtureDevice()')
                    .replace('CreateObject("roHttpAgent")', 'FixtureHttpAgent()'))
                files = [path if p.name == name else p for p in files]
            metadata = folder / 'MetadataStore.brs'
            metadata.write_text((ROOT / 'source/auth/MetadataStore.brs').read_text().replace(
                'function MetadataRequestConfig(', 'function FixtureUnusedMetadataRequestConfig(', 1))
            files = [metadata if p.name == 'MetadataStore.brs' else p for p in files]
            sdk = folder / 'sdk.brs'
            sdk.write_text('''function MetadataRequestConfig(version as String) as Object
 return {baseUrl:"",appVersion:version}
end function
function FixtureTask() as Object
 m.jobs++
 return {observeField:sub(a,b)
 end sub,unobserveField:sub(a)
 end sub}
end function
function FixtureDialog() as Object
 m.dialogCount++
 return {id:m.dialogCount,buttonSelected:0,observeField:sub(a,b)
 end sub,isSameNode:function(other)
 return m.id=other.id
 end function}
end function
function FixtureEvent(data) as Object
 return {data:data,getData:function()
 return m.data
 end function,getRoSGNode:function()
 return m.data
 end function}
end function
function FixtureDevice() as Object
 return {GetRandomUUID:function()
 return "fixture-stop"
 end function}
end function
function FixtureHttpAgent() as Object
 return {SetCertificatesFile:sub(path)
 end sub}
end function
function FixtureNode() as Object
 return {text:"",visible:false,setHttpAgent:sub(agent)
 end sub,setFocus:function(value)
 return true
 end function,boundingRect:function()
 return {height:10}
 end function}
end function
''')
            setup = '''m.provider="silo":m.sourceId="silo:fixture":m.profileId="profile":m.generation=3:m.playToken=8
 m.pending={}:m.cleanupTickets={}:m.requestId=0:m.jobs=0:m.dialogCount=0:m.view="detail":m.zone=""
 m.top={dialog:invalid,memoryPressure:0,nodes:{},findNode:function(name)
 if not m.nodes.DoesExist(name) then m.nodes[name]=FixtureNode()
 return m.nodes[name]
 end function}:m.playLoading=true:m.playClock=CreateObject("roTimespan")
 m.upNextTimer={}:m.playerCue={}:m.video={}:m.preferences=SiloUISettingsPreferences(invalid):m.toast={}:m.toastTimer={}
 m.nav={}:m.backdrop={}:m.backdropOld={}:m.backdropTimer={}:m.backdropFade={}:m.pillGroups={}:m.manualFocus=FixtureNode()
 m.obEyebrow=FixtureNode():m.obTitle=FixtureNode():m.obBody=FixtureNode():m.obCode=FixtureNode():m.obButtons=FixtureNode():m.navSource=FixtureNode()
 m.audioTimer={}:m.audioToken=0:m.history=[]
 '''
            output = run_brightscript([*files, sdk], setup + body, root=folder)
            return json.loads(output.strip().splitlines()[-1])

    def test_current_unknown_start_blocks_manual_replay_and_keeps_device_info(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent({requestId:1,ok:false,errorCode:"unsupported_stream",leaseUncertain:true,sessionRevision:5}))
 first=m.top.dialog.message:d=m.top.dialog:d.close=true:onPlayerFailureClosed(FixtureEvent(d))
 PlayItem({itemId:"item"},0)
 d=m.top.dialog:d.buttonSelected=1:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({first:first,message:m.playbackFailureMessage,info:d.title,jobs:m.jobs,pending:m.pending.Count(),loading:m.playLoading})''')
        self.assertEqual(1, value['jobs'])
        self.assertEqual(0, value['pending'])
        self.assertFalse(value['loading'])
        self.assertIn('Playback session identity or cleanup could not be confirmed', value['first'])
        self.assertIn('new playback is paused', value['message'])
        self.assertEqual('Device info', value['info'])

    def test_dispatch_drops_queued_allocations_after_stale_result_without_pending_or_spinner(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 m.generation=4:m.sourceId="other":m.profileId="other":m.playToken=9
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,sessionRevision:5}))
 staleDialog=m.top.dialog
 Api("playback_start",{},"play_start",m.playToken)
 Api("playback_start",{},"play_prebuf",m.playToken)
 Api("audio_start",{},"audio_start",1)
 print FormatJson({jobs:m.jobs,pending:m.pending.Count(),loading:m.playLoading,audioLoading:m.audioLoading,staleDialog:staleDialog,message:SpField(m.top.dialog,"message")})''')
        self.assertEqual(1, value['jobs'])
        self.assertEqual(0, value['pending'])
        self.assertFalse(value['loading'])
        self.assertFalse(value['audioLoading'])
        self.assertIsNone(value['staleDialog'])
        self.assertIn('#3004', value['message'])

    def test_known_retained_lease_reopens_only_after_matching_cleanup_ack(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,cleanupLeaseKnown:true,provider:"silo",action:"playback_start",sourceId:"silo:fixture",profileId:"profile",generation:3,sessionRevision:5,plan:{sessionId:"lease",installationId:"installation",stopId:"stop"}}))
 key=m.pending["2"].extra
 onApiResult(FixtureEvent({requestId:2,ok:false,errorCode:"network_error"}))
 PlayItem({itemId:"item"},0):blocked=m.jobs
 SiloUIRetryCleanup()
 onApiResult(FixtureEvent({requestId:3,ok:true}))
 PlayItem({itemId:"item"},0)
 print FormatJson({blocked:blocked,jobs:m.jobs,pending:m.pending.Count(),tickets:m.cleanupTickets.Count(),last:SpField(m.pending["4"],"purpose")})''')
        self.assertEqual(2, value['blocked'])
        self.assertEqual(4, value['jobs'])
        self.assertEqual(0, value['tickets'])
        self.assertEqual('play_detail', value['last'])

    def test_normal_entry_cleanup_failed_is_not_global_play_prohibition(self):
        value = self.scene('''m.cleanupFailed=true
 PlayItem({itemId:"item"},0)
 print FormatJson({jobs:m.jobs,loading:m.playLoading,purpose:m.pending["1"].purpose})''')
        self.assertEqual({'jobs':1,'loading':True,'purpose':'play_detail'}, value)

    def test_unknown_refuses_transition_and_cancel_back_preserves_barrier(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,sessionRevision:5}))
 m.view="onboarding":m.playLoading=false:m.cleanupFailed=false
 SiloUIBeginTransition({action:"switch_profile"})
 waiting=m.transitionIntent:choices=m.obChoices:reason=m.obBody.text
 ObChoose({action:"cleanup_cancel"})
 OnboardingKey("back")
 PlayItem({itemId:"item"},0)
 print FormatJson({waiting:waiting,choices:choices,reason:reason,intent:m.transitionIntent,view:m.view,jobs:m.jobs,source:m.sourceId})''')
        self.assertEqual({'action':'switch_profile'}, value['waiting'])
        self.assertEqual([{'label':'Cancel switch','action':'cleanup_cancel'}], value['choices'])
        self.assertIn('no usable session identifier', value['reason'])
        self.assertIsNone(value['intent'])
        self.assertEqual('home', value['view'])
        self.assertEqual(1, value['jobs'])
        self.assertEqual('silo:fixture', value['source'])

    def test_unknown_blocks_speculative_producers_and_audio_before_side_effects(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,sessionRevision:5}))
 m.playLoading=false:m.speculationDisabled=false
 PlayerPrebuffer({itemId:"item"},[{versionId:"file"}],[],{})
 m.view="home":m.zone="heroButtons":m.heroItem={itemId:"hero"}:m.homeRows=[{sectionType:"continue_watching",items:[{itemId:"hero"}]}]
 PlayerSyncHeroPrebuffer()
 m.view="library":SiloUIAudioOpen("book")
 opened=m.view
 m.audioQueue=[{fileId:"part",durationMs:1000}]:m.audioNode=FixtureNode():m.audioNode.state="stopped"
 SiloUIAudioRequestPart(0,0)
 print FormatJson({jobs:m.jobs,opened:opened,next:m.audioNext,pre:m.prebuf,hero:m.heroPrebufferAttempt,loading:m.audioLoading})''')
        self.assertEqual(1, value['jobs'])
        self.assertEqual('library', value['opened'])
        self.assertIsNone(value['next'])
        self.assertIsNone(value['pre'])
        self.assertIsNone(value['hero'])
        self.assertFalse(value['loading'])

    def test_unknown_cancels_pending_audio_and_later_known_ack_cannot_erase_it(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 Api("audio_start",{},"audio_start",1):audioTask=m.pending["2"].task
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,sessionRevision:5}))
 onApiResult(FixtureEvent({requestId:2,ok:true,sessionRevision:5,plan:{sessionId:"audio-lease",installationId:"installation",stopId:"stop"}}))
 onApiResult(FixtureEvent({requestId:3,ok:true}))
 PlayItem({itemId:"item"},0)
 print FormatJson({cancelled:audioTask.cancelled,jobs:m.jobs,pending:m.pending.Count(),tickets:m.cleanupTickets.Count(),message:m.top.dialog.message,speculation:m.speculationDisabled})''')
        self.assertTrue(value['cancelled'])
        self.assertEqual(3, value['jobs'])
        self.assertEqual(0, value['pending'])
        self.assertEqual(0, value['tickets'])
        self.assertIn('new playback is paused', value['message'])
        self.assertTrue(value['speculation'])

    def test_actual_task_closed_malformed_terminal_does_not_latch_unknown_or_retry(self):
        from tests.test_silo_start_retry_authority import StartRetryAuthority
        mutation = 'decision.Delete("playback_plan"):decision.outcome="terminal":decision.terminal={reason:"no_playable_source",retryable:false}'
        task = StartRetryAuthority().start(mutation)
        outcome = task['outcome']
        self.assertFalse(outcome['ok'])
        self.assertEqual(1, sum('/playback/start' in r['url'] for r in task['requests']))
        self.assertIs(True, outcome.get('cleanupLeaseClosed'))
        payload = json.dumps(outcome).replace('"', '""')
        value = self.scene('m.sourceId="'+outcome['sourceId']+'":m.profileId="'+outcome['profileId']+'":m.generation='+str(outcome['generation'])+'''
 m.requestId=40:Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent(ParseJson("'''+payload+'''")))
 before=m.jobs:PlayItem({itemId:"item"},0)
 print FormatJson({added:m.jobs-before,purpose:SpField(m.pending[m.requestId.ToStr()],"purpose")})''')
        self.assertEqual({'added':1,'purpose':'play_detail'}, value)

    def test_mismatched_closed_fact_cannot_resolve_unknown(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,cleanupLeaseClosed:true,provider:"silo",action:"playback_start",sourceId:"other",profileId:"profile",generation:3,sessionRevision:5}))
 PlayItem({itemId:"item"},0)
 print FormatJson({jobs:m.jobs,message:m.top.dialog.message})''')
        self.assertEqual(1, value['jobs'])
        self.assertIn('new playback is paused', value['message'])

    def test_cancelled_or_stale_allocation_retains_unknown_without_wrong_modal(self):
        for change in ('PlayerCancelPreparation()', 'm.generation=4', 'm.sourceId="other"', 'm.profileId="other"', 'm.provider="plex"'):
            with self.subTest(change=change):
                value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 '''+change+'''
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,sessionRevision:5}))
 stale=m.top.dialog
 PlayItem({itemId:"item"},0)
 print FormatJson({jobs:m.jobs,stale:stale,message:m.top.dialog.message})''')
                self.assertEqual(1, value['jobs'])
                self.assertIsNone(value['stale'])
                self.assertIn('new playback is paused', value['message'])

    def test_false_malformed_and_nonallocating_flags_do_not_block_play(self):
        for flag, purpose in [('false','play_start'), ('"true"','play_start'), ('true','unrelated')]:
            with self.subTest(flag=flag,purpose=purpose):
                value = self.scene('Api("detail",{},"'+purpose+'",m.playToken)'+'''
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:'''+flag+''',sessionRevision:5}))
 PlayItem({itemId:"item"},0)
 print FormatJson({purpose:m.pending[m.requestId.ToStr()].purpose,loading:m.playLoading})''')
                self.assertEqual({'purpose':'play_detail','loading':True}, value)

    def test_actual_task_missing_lease_and_failed_stop_reach_distinct_scene_barriers(self):
        from tests.test_silo_start_retry_authority import StartRetryAuthority
        cases = [('decision.Delete("session_id"):decision.playback_plan.Delete("session_id"):unusedStop=m.responses.Shift()',None,0), (None,'{statusCode:503,body:"{}"}',1)]
        for mutation, stop, tickets in cases:
            with self.subTest(mutation=mutation,stop=stop):
                outcome = StartRetryAuthority().start(mutation,stop=stop)['outcome']
                payload = json.dumps(outcome).replace('"','""')
                value = self.scene('m.sourceId="'+outcome['sourceId']+'":m.profileId="'+outcome['profileId']+'":m.generation='+str(outcome['generation'])+'''
 m.requestId=40:Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent(ParseJson("'''+payload+'''")))
 before=m.jobs:PlayItem({itemId:"item"},0)
 print FormatJson({added:m.jobs-before,tickets:m.cleanupTickets.Count(),message:m.top.dialog.message})''')
                self.assertEqual(0,value['added'])
                self.assertEqual(tickets,value['tickets'])
                self.assertIn('Playback session identity or cleanup could not be confirmed' if tickets==0 else 'Retry session cleanup',value['message'])

    def test_remote_back_cancels_unknown_transition_and_next_play_explains_barrier(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,sessionRevision:5}))
 m.view="onboarding":m.playLoading=false:m.cleanupFailed=false
 SiloUIBeginTransition({action:"switch_profile"})
 OnboardingKey("back")
 m.top.dialog=invalid:PlayItem({itemId:"item"},0)
 print FormatJson({intent:m.transitionIntent,view:m.view,message:SpField(m.top.dialog,"message"),jobs:m.jobs})''')
        self.assertIsNone(value['intent'])
        self.assertEqual('home',value['view'])
        self.assertIn('new playback is paused',value['message'])
        self.assertEqual(1,value['jobs'])

    def test_stale_dispatch_refusal_cannot_replace_new_modal_or_loading_state(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 old=SiloUIOwner()
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,sessionRevision:5}))
 m.generation=4:m.playToken=9:m.playLoading=true
 fresh=FixtureDialog():fresh.title="Current modal":m.top.dialog=fresh
 ApiOwned("playback_start",{},"play_start",8,old)
 print FormatJson({title:m.top.dialog.title,loading:m.playLoading,jobs:m.jobs,pending:m.pending.Count()})''')
        self.assertEqual({'title':'Current modal','loading':True,'jobs':1,'pending':0},value)

    def test_one_matching_ack_does_not_release_another_cleanup_ticket(self):
        value = self.scene('''owner=SiloUIOwner():owner.sessionRevision=5
 SiloUIQueueCleanup({sessionId:"first",installationId:"installation",stopId:"stop-one"},owner)
 SiloUIQueueCleanup({sessionId:"second",installationId:"installation",stopId:"stop-two"},owner)
 onApiResult(FixtureEvent({requestId:1,ok:true}))
 PlayItem({itemId:"item"},0):blocked=m.jobs
 onApiResult(FixtureEvent({requestId:2,ok:true}))
 PlayItem({itemId:"item"},0)
 print FormatJson({blocked:blocked,jobs:m.jobs,purpose:m.pending["3"].purpose})''')
        self.assertEqual({'blocked':2,'jobs':3,'purpose':'play_detail'},value)

    def test_known_fact_with_missing_stop_identifier_cannot_erase_uncertainty(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,cleanupLeaseKnown:true,provider:"silo",action:"playback_start",sourceId:"silo:fixture",profileId:"profile",generation:3,sessionRevision:5,plan:{sessionId:"lease",installationId:"installation"}}))
 onApiResult(FixtureEvent({requestId:2,ok:true}))
 PlayItem({itemId:"item"},0)
 print FormatJson({jobs:m.jobs,message:m.top.dialog.message})''')
        self.assertEqual(2,value['jobs'])
        self.assertIn('new playback is paused',value['message'])

    def test_current_audio_success_after_unknown_is_cleaned_without_binding(self):
        value = self.scene('''Api("playback_start",{},"play_start",m.playToken)
 m.audioToken=1:m.view="audio":m.audioNode=FixtureNode():m.audioNode.control="untouched"
 Api("audio_start",{},"audio_start",m.audioToken)
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,sessionRevision:5}))
 onApiResult(FixtureEvent({requestId:2,ok:true,sessionRevision:5,plan:{sessionId:"current-audio-lease",installationId:"installation",stopId:"current-stop",url:"https://example.invalid/audio"}}))
 cleanupJob=invalid
 if m.pending["3"]<>invalid then cleanupJob=m.pending["3"].task.job
 onApiResult(FixtureEvent({requestId:3,ok:true}))
 PlayItem({itemId:"item"},0)
 print FormatJson({jobs:m.jobs,pending:m.pending.Count(),stop:cleanupJob,plan:m.audioPlan,control:m.audioNode.control,message:m.top.dialog.message})''')
        self.assertEqual(3, value['jobs'])
        self.assertEqual(0, value['pending'])
        self.assertEqual('playback_stop', value['stop']['action'])
        self.assertEqual('current-audio-lease', value['stop']['params']['sessionId'])
        self.assertEqual('current-stop', value['stop']['params']['stopId'])
        self.assertIs(False, value['stop']['params']['persistProgress'])
        self.assertIsNone(value['plan'])
        self.assertEqual('untouched', value['control'])
        self.assertIn('new playback is paused', value['message'])

    def test_real_start_facts_survive_first_barrier_and_repeated_play_without_new_work(self):
        from tests.test_silo_start_retry_authority import StartRetryAuthority
        outcome=StartRetryAuthority().start('decision.Delete("session_id"):decision.playback_plan.Delete("session_id"):unusedStop=m.responses.Shift()')['outcome']
        payload=json.dumps(outcome).replace('"','""')
        value=self.scene('m.sourceId="'+outcome['sourceId']+'":m.profileId="'+outcome['profileId']+'":m.generation='+str(outcome['generation'])+'''
 m.requestId=40:Api("playback_start",{},"play_start",m.playToken)
 onApiResult(FixtureEvent(ParseJson("'''+payload+'''")))
 first=m.top.dialog.buttons:m.top.dialog.close=true:onPlayerFailureClosed(FixtureEvent(m.top.dialog))
 before=m.jobs:PlayItem({itemId:"item"},0)
 d=m.top.dialog:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({first:first,title:d.title,lines:d.message.Split(Chr(10)),added:m.jobs-before,video:m.video})''')
        self.assertEqual(['OK','Device info','Response info','Request info'],value['first']);self.assertEqual('Play Start response',value['title']);self.assertEqual(7,len(value['lines']));self.assertEqual(0,value['added']);self.assertEqual({},value['video'])

    def test_first_barrier_snapshot_cannot_be_replaced_or_borrowed_by_other_scope(self):
        facts='{httpStatus:201,protocol:"v3",outcome:"plan",sessionId:"missing",playbackPlanPresent:true,playbackPlanObject:true,planSessionId:"missing",terminalShapeValid:false}'
        for change in ('','m.generation=4','m.sourceId="foreign"','m.profileId="foreign"','m.provider="plex"'):
            with self.subTest(change=change):
                value=self.scene('''Api("playback_start",{},"play_start",m.playToken)
 Api("playback_start",{},"play_start",m.playToken)
 facts='''+facts+'''
 result={requestId:1,ok:false,leaseUncertain:true,provider:"silo",action:"playback_start",sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,sessionRevision:5,startResponseFacts:facts}
 onApiResult(FixtureEvent(result)):facts.httpStatus=599
 result.requestId=2:result.startResponseFacts.httpStatus=202:onApiResult(FixtureEvent(result))
 '''+change+'''
 before=m.jobs:PlayItem({itemId:"item"},0)
 d=m.top.dialog:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({buttons:d.buttons,title:d.title,lines:d.message.Split(Chr(10)),added:m.jobs-before})''')
                self.assertEqual(0,value['added'])
                if not change:
                    self.assertEqual('Play Start response',value['title']);self.assertIn('HTTP 201','\n'.join(value['lines']));self.assertNotIn('202','\n'.join(value['lines']));self.assertNotIn('599','\n'.join(value['lines']))
                else:self.assertEqual(['OK','Device info'],value['buttons'])

    def test_unmatched_or_first_missing_facts_cannot_gain_response_info_from_later_result(self):
        for mismatch in ('result.sourceId="foreign"','m.pending["1"].task.job.requestId=99','result.sessionRevision="5"','result.action="detail"','result.Delete("startResponseFacts")','result.startResponseFacts.httpStatus="private-secret"'):
            with self.subTest(mismatch=mismatch):
                value=self.scene('''Api("playback_start",{},"play_start",m.playToken)
 Api("playback_start",{},"play_start",m.playToken)
 facts={httpStatus:200,protocol:"v3",outcome:"plan",sessionId:"missing",playbackPlanPresent:true,playbackPlanObject:true,planSessionId:"missing",terminalShapeValid:false}
 result={requestId:1,ok:false,leaseUncertain:true,provider:"silo",action:"playback_start",sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,sessionRevision:5,startResponseFacts:facts}
 '''+mismatch+'''
 onApiResult(FixtureEvent(result))
 result={requestId:2,ok:false,leaseUncertain:true,provider:"silo",action:"playback_start",sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,sessionRevision:5,startResponseFacts:facts}
 onApiResult(FixtureEvent(result))
 before=m.jobs:PlayItem({itemId:"item"},0)
 print FormatJson({buttons:m.top.dialog.buttons,added:m.jobs-before})''')
                self.assertEqual(['OK','Device info'],value['buttons']);self.assertEqual(0,value['added'])

    def test_actual_preload_start_facts_are_first_cause_on_manual_play_barrier(self):
        from tests.test_silo_start_retry_authority import StartRetryAuthority
        outcome=StartRetryAuthority().start('decision.Delete("session_id"):decision.playback_plan.Delete("session_id"):unusedStop=m.responses.Shift()')['outcome']
        payload=json.dumps(outcome).replace('"','""')
        value=self.scene('m.sourceId="'+outcome['sourceId']+'":m.profileId="'+outcome['profileId']+'":m.generation='+str(outcome['generation'])+'''
 m.requestId=40:m.prebuf={token:8}:Api("playback_start",{},"play_prebuf",8)
 onApiResult(FixtureEvent(ParseJson("'''+payload+'''")))
 first=m.top.dialog:before=m.jobs:PlayItem({itemId:"item"},0)
 d=m.top.dialog:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({first:first,title:d.title,lines:d.message.Split(Chr(10)),added:m.jobs-before})''')
        self.assertIsNone(value['first']);self.assertEqual('Preload Start response',value['title']);self.assertEqual(7,len(value['lines']));self.assertEqual(0,value['added'])

    def test_tampered_response_facts_never_grant_admission_or_clear_uncertainty(self):
        value=self.scene('''Api("playback_start",{},"play_start",m.playToken)
 facts={httpStatus:200,protocol:"v3",outcome:"adaptation_unavailable",sessionId:"missing",playbackPlanPresent:false,playbackPlanObject:false,planSessionId:"unavailable",terminalShapeValid:true,cleanupLeaseClosed:true}
 onApiResult(FixtureEvent({requestId:1,ok:false,leaseUncertain:true,provider:"silo",action:"playback_start",sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,sessionRevision:5,startResponseFacts:facts}))
 before=m.jobs:PlayItem({itemId:"item"},0)
 print FormatJson({added:m.jobs-before,blocked:SiloUIPlaybackAdmissionBlocked(),tickets:m.cleanupTickets.Count(),video:m.video})''')
        self.assertEqual({'added':0,'blocked':True,'tickets':0,'video':{}},value)

    def test_actual_cancelled_same_scope_attempts_keep_barrier_without_lending_facts(self):
        from tests.test_silo_start_retry_authority import StartRetryAuthority
        outcome=StartRetryAuthority().start('decision.Delete("session_id"):decision.playback_plan.Delete("session_id"):unusedStop=m.responses.Shift()')['outcome']
        payload=json.dumps(outcome).replace('"','""')
        for purpose,prepare,change in [('play_start','','PlayerCancelPreparation()'),('play_start','','m.playToken=9'),('play_prebuf','m.prebuf={token:8}:','PlayerDiscardPrebuffer()'),('play_prebuf','m.prebuf={token:8}:','m.prebuf.token=9'),('play_start','','m.pending["41"].task.cancelled=true')]:
            with self.subTest(purpose=purpose,change=change):
                value=self.scene('m.sourceId="'+outcome['sourceId']+'":m.profileId="'+outcome['profileId']+'":m.generation='+str(outcome['generation'])+'''
 m.requestId=40:'''+prepare+'Api("playback_start",{},"'+purpose+'",8)'+'''
 '''+change+'''
 onApiResult(FixtureEvent(ParseJson("'''+payload+'''")))
 before=m.jobs:PlayItem({itemId:"item"},0)
 print FormatJson({buttons:m.top.dialog.buttons,added:m.jobs-before,blocked:SiloUIPlaybackAdmissionBlocked(),video:m.video})''')
                self.assertEqual(['OK','Device info'],value['buttons']);self.assertEqual(0,value['added']);self.assertTrue(value['blocked']);self.assertEqual({},value['video'])
