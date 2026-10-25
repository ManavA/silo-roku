"""Native recovery retains only the current same-lease cleanup authority."""
import unittest

from tests import test_silo_ui_subtitle_off_flow as subtitle_flow


PREPARE = '''FixtureInventory(m.playPlan)
 acceptedPlan.Delete("cleanupOwner")
 acceptedPlan["subtitleMode"]="render"
 acceptedPlan.siloPlayback.selectedTracks["subtitle"]={id:"file:f1:subtitle:0",index:0}
 FixtureInventory(acceptedPlan)
 acceptedPlan["selectedSubtitle"]={kind:"sidecar_ready",mode:"render",renderingReady:true,trackId:"file:f1:subtitle:0",combinedIndex:0,language:"eng",format:"vtt",mimeType:"text/vtt"}
 acceptedPlan["subtitleArtifact"]={uri:"tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt",format:"vtt",mimeType:"text/vtt",timingOriginSeconds:0,owner:{sourceId:m.sourceId,profileId:m.profileId,generation:7,requestId:1,sessionRevision:0,sessionId:acceptedPlan.sessionId,planAttemptKey:"plan-key-0002",fileId:"f1",selectedOrdinal:0,timelineOffsetMs:120000}}
 m.recoveringNative=true
 ApiOwned("playback_replan",{},"play_recover",m.playToken,m.playPlan.cleanupOwner)
'''
DELIVER = '''event={payload:{requestId:1,ok:true,plan:acceptedPlan},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
'''


class RecoveryOwnerTests(unittest.TestCase):
    def scene(self, body):
        return subtitle_flow.SubtitleOffFlow().scene(body, actual_results=True, actual_start=True)

    def test_actual_recovery_retains_owner_and_binds_fresh_selected_plan(self):
        result = self.scene(PREPARE + DELIVER + '''
 PlaybackSelectSourceSubtitle({trackId:"file:f1:subtitle:1",combinedIndex:1})
 print FormatJson({owner:m.playPlan.cleanupOwner,plan:m.playPlan.planId,selected:m.playPlan.siloPlayback.selectedTracks.subtitle,bound:m.subtitleBinding<>invalid,sequence:m.progressSequence,back:m.playerReturn,captions:m.savedCaptionMode,contentCount:m.contentCount,selectionPending:m.subtitleChange<>invalid})''')
        self.assertEqual({'provider':'silo','sourceId':'silo:synthetic','profileId':'owner','generation':7,'sessionRevision':0}, result['owner'])
        self.assertEqual('plan-0002', result['plan'])
        self.assertEqual({'id':'file:f1:subtitle:0','index':0}, result['selected'])
        self.assertTrue(result['bound'])
        self.assertEqual(9, result['sequence'])
        self.assertEqual({'view':'home','zone':'heroButtons'}, result['back'])
        self.assertEqual('On', result['captions'])
        self.assertEqual(1, result['contentCount'])
        self.assertTrue(result['selectionPending'])

    def test_actual_recovery_refuses_foreign_or_mismatched_authority(self):
        for edit in (
            'acceptedPlan.siloPlayback["profileId"]="foreign"',
            'acceptedPlan.siloPlayback["sourceId"]="silo:foreign":acceptedPlan["sourceId"]="silo:foreign"',
            'acceptedPlan.siloPlayback["fileId"]="f2":acceptedPlan["versionId"]="f2"',
            'acceptedPlan.siloPlayback["sessionRevision"]=1',
            'acceptedPlan.siloPlayback["installationId"]="foreign-install":acceptedPlan["installationId"]="foreign-install"',
            'm.playPlan["cleanupOwner"]=ParseJson(FormatJson(m.playPlan.cleanupOwner)):m.playPlan.cleanupOwner["profileId"]="foreign"',
            'm.playPlan["cleanupOwner"]=ParseJson(FormatJson(m.playPlan.cleanupOwner)):m.playPlan.cleanupOwner["generation"]=8',
        ):
            with self.subTest(edit=edit):
                result = self.scene(PREPARE + edit + '\n' + DELIVER + '''
 print FormatJson({starts:m.contentCount,owner:acceptedPlan.cleanupOwner,view:m.view,deleted:m.deleted})''')
                self.assertIsNone(result['starts'])
                self.assertIsNone(result['owner'])
                self.assertEqual('home', result['view'])
                if 'installationId' in edit or 'm.playPlan[' in edit:
                    self.assertEqual(['tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt'], result['deleted'])

    def test_stale_recovery_callback_never_receives_cleanup_authority(self):
        for edit in ('m.playToken=5', 'm.generation=8:m.sourceId="silo:next"'):
            with self.subTest(edit=edit):
                result = self.scene(PREPARE + edit + '\n' + DELIVER + '''
 print FormatJson({starts:m.contentCount,owner:acceptedPlan.cleanupOwner,deleted:m.deleted})''')
                self.assertIsNone(result['starts'])
                self.assertIsNone(result['owner'])
                self.assertEqual(['tmp:/silo-subtitle-01234567-89ab-cdef-0123-456789abcdef.vtt'], result['deleted'])

    def test_cancelled_recovery_latest_receipt_drains_before_actual_source_transition(self):
        result = subtitle_flow.SubtitleOffFlow().scene('''m.recoveringNative=true
 Api("playback_replan",{plan:m.playPlan},"play_recover",m.playToken)
 receipt=SpCopy(m.playPlan.siloPlayback)
 receipt.planId="plan-0003":receipt.planAttemptKey="plan-key-0003":receipt.attemptCount=2
 receipt.attemptedPlanKeys=["plan-key-0001","plan-key-0002"]
 PlayerClose(false)
 SiloUIBeginTransition({action:"sources"})
 event={payload:{requestId:1,ok:false,errorCode:"cancelled",sessionRevision:0,controlReceipt:receipt,leaseUncertain:true},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 before={generation:m.generation,pending:m.pending.Count(),tickets:SpField(m.cleanupTickets,"missing",invalid)}
 if m.cleanupTickets<>invalid then before.tickets=m.cleanupTickets.Count()
 cleanup=m.pending["2"]
 params=invalid
 if cleanup<>invalid then params=cleanup.task.job.params
 event.payload={requestId:2,ok:true}
 onApiResult(event)
 print FormatJson({before:before,params:params,generation:m.generation,choices:m.transitionChoices,starts:m.starts.Count()})''', actual_results=True,actual_owned=True)
        self.assertEqual(dict(generation=7,pending=1,tickets=1),result['before'])
        self.assertEqual(('session-0001',False),(result['params']['sessionId'],result['params']['persistProgress']))
        self.assertEqual((8,1,0),(result['generation'],result['choices'],result['starts']))

    def test_late_recovery_never_stops_newer_active_plan_on_same_lease(self):
        result=subtitle_flow.SubtitleOffFlow().scene('''Api("playback_replan",{plan:m.playPlan},"play_recover",m.playToken)
 receipt=SpCopy(m.playPlan.siloPlayback):receipt.planId="plan-0003":receipt.planAttemptKey="plan-key-0003":receipt.attemptCount=2
 m.playPlan=acceptedPlan:m.playToken=5
 event={payload:{requestId:1,ok:false,errorCode:"cancelled",sessionRevision:0,controlReceipt:receipt,leaseUncertain:true},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({pending:m.pending.Count(),tickets:SpField(m.cleanupTickets,"missing",invalid),view:m.view,plan:m.playPlan.planId})''',actual_results=True,actual_owned=True)
        self.assertEqual(dict(pending=0,tickets=None,view='player',plan='plan-0002'),result)

    def test_late_recovery_never_stops_newer_active_same_lease_after_generation_change(self):
        result=subtitle_flow.SubtitleOffFlow().scene('''Api("playback_replan",{plan:m.playPlan},"play_recover",m.playToken)
 receipt=SpCopy(m.playPlan.siloPlayback):receipt.planId="plan-0003":receipt.planAttemptKey="plan-key-0003":receipt.attemptCount=2
 m.playPlan=acceptedPlan:m.playToken=5:m.generation=8
 m.playPlan.cleanupOwner.generation=8
 event={payload:{requestId:1,ok:false,errorCode:"cancelled",sessionRevision:0,controlReceipt:receipt,leaseUncertain:true},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({pending:m.pending.Count(),tickets:SpField(m.cleanupTickets,"missing",invalid),view:m.view,plan:m.playPlan.planId})''',actual_results=True,actual_owned=True)
        self.assertEqual(dict(pending=0,tickets=None,view='player',plan='plan-0002'),result)

    def test_identical_session_text_on_other_source_does_not_abandon_captured_cleanup(self):
        result=subtitle_flow.SubtitleOffFlow().scene('''Api("playback_replan",{plan:m.playPlan},"play_recover",m.playToken)
 m.playPlan=acceptedPlan:m.playToken=5:m.generation=8:m.sourceId="silo:other"
 m.playPlan["sourceId"]="silo:other":m.playPlan.siloPlayback["sourceId"]="silo:other"
 event={payload:{requestId:1,ok:false,errorCode:"cancelled",sessionRevision:0,leaseUncertain:true},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 cleanup=m.pending["2"]
 source=""
 if cleanup<>invalid then source=cleanup.owner.sourceId
 print FormatJson({pending:m.pending.Count(),source:source,view:m.view,plan:m.playPlan.planId,valid:SiloPlaybackContext(m.playPlan,SiloUIOwner())<>invalid})''',actual_results=True,actual_owned=True)
        self.assertEqual(dict(pending=1,source='silo:synthetic',view='player',plan='plan-0002',valid=True),result)

    def test_late_recovery_never_stops_returned_a_recipe_with_advanced_attempt_count(self):
        for generation in (7,8):
            with self.subTest(generation=generation):
                body='''Api("playback_replan",{plan:m.playPlan},"play_recover",m.playToken)
 m.playPlan=SpCopy(m.playPlan):m.playToken=5:m.generation=GENERATION
 m.playPlan.cleanupOwner.generation=GENERATION
 m.playPlan.siloPlayback.attemptCount=2
 m.playPlan.siloPlayback.attemptedPlanKeys=["plan-key-0001","plan-key-0002"]
 event={payload:{requestId:1,ok:false,errorCode:"cancelled",sessionRevision:0,leaseUncertain:true},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 print FormatJson({pending:m.pending.Count(),bound:m.subtitleBinding,view:m.view,valid:SiloPlaybackContext(m.playPlan,SiloUIOwner())<>invalid})'''.replace('GENERATION',str(generation))
                result=subtitle_flow.SubtitleOffFlow().scene(body,actual_results=True,actual_owned=True)
                self.assertEqual(dict(pending=0,bound=None,view='player',valid=True),result)

    def test_source_transition_with_unchanged_displayed_control_still_drains_captured_lease(self):
        result=subtitle_flow.SubtitleOffFlow().scene('''Api("playback_replan",{plan:m.playPlan},"play_recover",m.playToken)
 SiloUIBeginTransition({action:"sources"})
 event={payload:{requestId:1,ok:false,errorCode:"cancelled",sessionRevision:0,leaseUncertain:true},getData:function() as Object
 return m.payload
 end function}
 onApiResult(event)
 before={generation:m.generation,pending:m.pending.Count(),tickets:m.cleanupTickets.Count()}
 event.payload={requestId:2,ok:true}
 onApiResult(event)
 print FormatJson({before:before,generation:m.generation,pending:m.pending.Count(),choices:m.transitionChoices})''',actual_results=True,actual_owned=True)
        self.assertEqual(dict(before=dict(generation=7,pending=1,tickets=1),generation=8,pending=0,choices=1),result)
