import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript as execute_brightscript
ROOT=Path(__file__).resolve().parents[1]
def run_brightscript(files, body, *, root):
    return execute_brightscript([ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'components/SiloUISubtitleArtifact.brs', *files], body, root=root)
class SiloUIRobustnessTests(unittest.TestCase):
    def component(self, body, helpers=''):
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'components/SiloUIRobustness.brs').read_text()
            if 'function SiloUICleanupUuid' in helpers:
                import re
                source=re.sub(r'function SiloUICleanupUuid\(.*?end function','',source,flags=re.S)
            fixture=Path(root)/'fixture.brs'
            fixture.write_text(source+'''
                sub ApiOwned(action as String, params as Object, purpose as String, extra as Dynamic, owner as Object)
                    m.calls.Push({action:action,params:ParseJson(FormatJson(params)),purpose:purpose,extra:extra,owner:ParseJson(FormatJson(owner))})
                end sub
                sub PlayerResetChrome()
                    m.chromeReset=true
                end sub
                sub PlayerDiscardPrebuffer()
                end sub
                sub ObChoose(choice as Object)
                    m.calls.Push({choice:choice})
                end sub
                sub ObScreen(a as String,b as String,c as String,d as String,e as Object)
                    m.screens=1
                    m.screenBody=c
                end sub
                sub Toast(text as String)
                end sub
                function NumberOr(value as Dynamic, fallback as Dynamic) as Dynamic
                    if value=invalid then return fallback
                    return value
                end function
                function TextOr(value as Dynamic) as String
                    if value=invalid then return ""
                    return value
                end function
            '''+helpers)
            return json.loads(run_brightscript([ROOT/'components/SiloUIDetail.brs', ROOT/'components/SiloUITrickplay.brs',fixture], '''m.calls=[] : m.pending={} : m.cleanupTickets={} : m.provider="silo" : m.sourceId="silo:a" : m.profileId="p" : m.generation=2 : m.playToken=1
m.video={} : m.progressTimer={} : m.upNextTimer={}
'''+body,root=Path(root)).splitlines()[-1])
    def test_cancelled_allocation_is_cleaned_before_generation_drop_once(self):
        actual=self.component('''
            owner={provider:"silo",sourceId:"silo:a",profileId:"p",generation:1}
            entry={purpose:"play_start",extra:0,owner:owner,generation:1}
            result={ok:true,sessionRevision:7,plan:{sessionId:"lease",installationId:"device"}}
            first=SiloUIAllocationResult(entry,result)
            again=SiloUIAllocationResult(entry,result)
            print FormatJson({first:first,again:again,calls:m.calls})
        ''', 'function SiloUICleanupUuid() as String\n return "same-uuid"\nend function')
        self.assertTrue(actual['first'])
        self.assertTrue(actual['again'])
        self.assertEqual(len(actual['calls']),1)
        call=actual['calls'][0]
        self.assertEqual(call['owner']['sessionRevision'],7)
        self.assertFalse(call['params']['persistProgress'])
        self.assertEqual(call['params']['stopId'],'same-uuid')
    def test_cancelled_version_recovery_allocation_is_cleaned_once(self):
        actual=self.component('''
            owner={provider:"silo",sourceId:"silo:a",profileId:"p",generation:2}
            entry={purpose:"play_recover_version",extra:0,owner:owner,generation:2}
            result={ok:true,sessionRevision:7,plan:{sessionId:"replacement-lease",installationId:"device"}}
            cancelled=SiloUIAllocationResult(entry,result)
            SiloUIAllocationResult(entry,result)
            print FormatJson({cancelled:cancelled,calls:m.calls})
        ''', 'function SiloUICleanupUuid() as String\n return "same-uuid"\nend function')
        self.assertTrue(actual['cancelled'])
        self.assertEqual(1,len(actual['calls']))
        self.assertEqual('replacement-lease',actual['calls'][0]['params']['sessionId'])

    def test_failed_cleanup_keeps_exact_ticket_for_retry_and_barrier(self):
        actual=self.component('''
            owner={provider:"silo",sourceId:"silo:a",profileId:"p",generation:2,sessionRevision:3}
            SiloUIQueueCleanup({sessionId:"lease",installationId:"device",stopId:"fixed"},owner)
            key=m.calls[0].extra
            SiloUICleanupResult({ok:false,errorCode:"network_error"},key)
            SiloUIRetryCleanup()
            print FormatJson({calls:m.calls,tickets:m.cleanupTickets.Count()})
        ''')
        self.assertEqual(actual['tickets'],1)
        self.assertEqual(actual['calls'][0],actual['calls'][1])
    def test_transition_coalesces_and_waits_for_pending_start(self):
        actual=self.component('''
            m.pending={one:{purpose:"play_recover_version"},two:{purpose:"play_recover"}}
            first=SiloUIBeginTransition({action:"sources"})
            again=SiloUIBeginTransition({action:"signout"})
            waiting=m.calls.Count()
            m.pending={}
            SiloUIDrainMaybeDone()
            print FormatJson({first:first,again:again,waiting:waiting,calls:m.calls})
        ''')
        self.assertTrue(actual['first'])
        self.assertTrue(actual['again'])
        self.assertEqual(actual['waiting'],0)
        self.assertEqual(actual['calls'],[{'choice':{'action':'sources'}}])
    def test_memory_pressure_clears_offscreen_arrays_backdrops_and_fences_requests(self):
        actual=self.component('''
            m.view="detail" : m.homeToken=4 : m.libraryToken=5 : m.searchToken=6
            m.backdrop={uri:"art"} : m.backdropOld={uri:"old"} : m.backdropTimer={} : m.backdropFade={} : m.heroTimer={} : m.searchTimer={}
            m.rows={content:{}} : m.grid={content:{}} : m.searchGrid={content:{}} : m.heroLogo={uri:"logo"}
            m.homeRows=[{}] : m.heroItem={} : m.detailEpisodes=[{itemId:"focused"}] : m.top={memoryPressure:80}
            SiloUIMemoryPressure()
            print FormatJson({home:m.homeRows,episodes:m.detailEpisodes,backdrop:m.backdrop.uri,old:m.backdropOld.uri,pending:m.pendingBackdrop,rows:m.rows.content,grid:m.grid.content,tokens:[m.homeToken,m.libraryToken,m.searchToken]})
        ''')
        self.assertEqual(actual,{'home':[],'episodes':[{'itemId':'focused'}],'backdrop':'','old':'','pending':'','rows':None,'grid':None,'tokens':[5,6,7]})
    def test_auth_expiry_once_only_current_scope_permits_signin(self):
        actual=self.component('''
            m.pollTimer={} : m.history=[] : m.playPlan={sessionId:"lease"}
            entry={generation:2,owner:{provider:"silo",sourceId:"silo:a",profileId:"p"}}
            SiloUIAuthExpired(entry)
            SiloUIAuthExpired(entry)
            SiloUIAuthExpired({generation:1,owner:{provider:"silo",sourceId:"other",profileId:"p"}})
            print FormatJson({calls:m.calls,generation:m.generation,tickets:m.cleanupTickets.Count(),unconfirmed:m.cleanupUnconfirmed})
        ''','''
            sub ObResetScope()
                m.generation=m.generation+1
            end sub
            sub ObScreen(a as String,b as String,c as String,d as String,e as Object)
                m.calls.Push("expired")
            end sub
        '''.replace('sub ObScreen','sub ExpiryScreen'))
        self.assertEqual(actual['generation'],3)
        self.assertTrue(actual['unconfirmed'])
    def test_idle_auth_expiry_does_not_invent_previous_playback_cleanup(self):
        actual=self.component('''
            m.pollTimer={}
            SiloUIAuthExpired({generation:2,owner:{provider:"silo",sourceId:"silo:a",profileId:"p"}})
            print FormatJson({unconfirmed:m.cleanupUnconfirmed=true,body:m.screenBody,expired:m.authExpiredProviders.silo,page:m.obPage})
        ''','''sub ObResetScope()\n m.generation=m.generation+1\nend sub\n''')
        self.assertEqual(actual,{'unconfirmed':False,'body':'Sign in to reconnect your library.','expired':True,'page':'expired'})
    def test_auth_expiry_keeps_cleanup_warning_for_owned_or_uncertain_playback(self):
        cases = {
            'native': 'm.playPlan={sessionId:"lease"}',
            'native_content': 'm.video.content={url:"fixture"}',
            'audio': 'm.audioPlan={sessionId:"lease"}',
            'audio_next': 'm.audioNext={index:1}',
            'audio_sync': 'm.audioSyncFlight={sequence:1}',
            'audio_sync_pending': 'm.audioSyncPending={sequence:2}',
            'prebuffer': 'm.prebuf={ready:false}',
            'prebuffer_foreground': 'm.prebufferForeground={token:1}',
            'compatibility': 'm.compatPreparation={holderId:"holder"}',
            'native_stop_failed': 'm.compatNativeStopFailure={provider:"silo",sourceId:"silo:a",profileId:"p",generation:2}',
            'unresolved_allocation': 'm.unresolvedAllocation={reason:"allocation_identity_unknown"}',
            'cleanup_ticket': 'm.cleanupTickets={one:{seekFinal:false}}',
            'seek': 'm.seekReanchor={phase:"pending"}',
            'seek_cleanup': 'm.seekCleanupUnconfirmed=true',
            'previous_uncertainty': 'm.cleanupUnconfirmed=true',
            'previous_failure': 'm.cleanupFailed=true',
            'pending_stop': 'm.pending={one:{purpose:"report",task:{job:{action:"playback_stop"}}}}',
        }
        for purpose in ['play_start','play_prebuf','play_recover','play_recover_version','audio_start','audio_select','seek_reanchor','subtitle_off','subtitle_select']:
            cases['pending_'+purpose]='m.pending={one:{purpose:"'+purpose+'",task:{}}}'
        for label,setup in cases.items():
            with self.subTest(label=label):
                actual=self.component('''m.pollTimer={}
                    '''+setup+'''
                    SiloUIAuthExpired({generation:2,owner:{provider:"silo",sourceId:"silo:a",profileId:"p"}})
                    print FormatJson({unconfirmed:m.cleanupUnconfirmed,body:m.screenBody})
                ''','''
sub ObResetScope()
 m.generation=m.generation+1
 m.pending={}
end sub
sub SiloUICompatCancel()
 m.compatPreparation=invalid
end sub
''')
                self.assertEqual(actual,{'unconfirmed':True,'body':'Cleanup of the previous server session remains unconfirmed.'})
    def test_home_retry_rejects_late_fanout_and_is_focusable(self):
        from tests.test_silo_ui_settings_policy import SiloUISettingsPolicyTests
        actual=SiloUISettingsPolicyTests().component('SiloUIHome.brs','''
            m.homeToken=2 : m.calls=[] : m.homeRetry=false : m.homeErrors=0
            HomeResult("home_plex_sections",{ok:true},{sections:[{sectionId:"old"}]},{token:1})
            HomeResult("home_silo",{ok:false},{},{token:2})
            m.zone="homeRetry" : HomeKey("OK")
            print FormatJson(m.calls)
        ''',[('HomeLoad','sub HomeLoad(skipImages=false as Boolean)\n m.calls.Push("load")\nend sub'),('HomeShowRetry','sub HomeShowRetry()\n m.calls.Push("retry")\nend sub')],'''sub Api(a as String,b as Object,c as String,d=invalid as Dynamic,e="" as String)\n m.calls.Push("unexpected")\nend sub''')
        self.assertEqual(actual,['retry','load'])
    def test_library_failure_retains_cursor_and_blocks_auto_paging_until_retry(self):
        from tests.test_silo_ui_settings_policy import SiloUISettingsPolicyTests
        actual=SiloUISettingsPolicyTests().component('SiloUILibrary.brs','''
            m.libraryToken=4 : m.libraryCursor="page2" : m.libraryOffset=60 : m.libraryMore=true : m.libraryLoading=true
            m.libraryEmpty={} : m.calls=[] : m.grid={content:{getChildCount:function() as Integer\n return 60\nend function},itemFocused:59}
            LibraryResult("lib_page",{ok:false},{},4)
            onGridFocus()
            m.zone="libraryRetry" : LibraryKey("OK")
            print FormatJson({cursor:m.libraryCursor,offset:m.libraryOffset,calls:m.calls})
        ''',[('LibraryQuery','sub LibraryQuery(reset as Boolean)\n m.calls.Push(reset)\nend sub'),('LibraryShowRetry','sub LibraryShowRetry()\n m.calls.Push("retry")\nend sub')])
        self.assertEqual(actual,{'cursor':'page2','offset':60,'calls':['retry',False]})

    def test_current_failed_allocation_routes_failure_and_tracks_rejected_cleanup(self):
        actual=self.component('''entry={purpose:"play_start",extra:1,owner:{provider:"silo",sourceId:"silo:a",profileId:"p",generation:2},generation:2}
            consumed=SiloUIAllocationResult(entry,{ok:false,sessionRevision:7,plan:{sessionId:"lease",installationId:"device",stopId:"fixed"}})
            print FormatJson({consumed:consumed,calls:m.calls.Count()})''')
        self.assertEqual(actual,{'consumed':False,'calls':1})
    def test_back_exact_sequence_including_first_row_later_item_and_release(self):
        from tests.test_silo_ui_plex_policy import SiloUIPlexPolicyTests
        actual=SiloUIPlexPolicyTests().scene('SiloUILibrary.brs','''
            m.view="home" : m.zone="rows" : m.rows={rowItemFocused:[0,3]} : m.history=[]
            a=onKeyEvent("back",true)
            first=m.rows.jumpToRowItem
            m.rows.rowItemFocused=[0,0]
            b=onKeyEvent("back",true) : hero=m.zone
            release=onKeyEvent("back",false) : released=m.zone
            c=onKeyEvent("back",true) : nav=m.zone
            d=onKeyEvent("back",true)
            print FormatJson({first:first,hero:hero,released:released,nav:nav,exit:d,release:release})
        ''',[('SetZone','sub SetZone(zone as String)\n m.zone=zone\nend sub\nfunction PlayerFailureBack() as Boolean\n return false\nend function')])
        self.assertEqual(actual,{'first':[0,0],'hero':'heroButtons','released':'heroButtons','nav':'nav','exit':False,'release':False})
    def test_late_allocation_from_expired_epoch_cannot_block_reauthentication(self):
        actual=self.component('''
            m.expiredGeneration=1
            entry={purpose:"play_prebuf",extra:0,owner:{provider:"silo",sourceId:"silo:a",profileId:"p",generation:1},generation:1}
            consumed=SiloUIAllocationResult(entry,{ok:true,sessionRevision:7,plan:{sessionId:"lease"}})
            print FormatJson({tickets:m.cleanupTickets.Count(),unconfirmed:m.cleanupUnconfirmed,calls:m.calls.Count()})
        ''')
        self.assertEqual(actual,{'tickets':0,'unconfirmed':True,'calls':0})
    def test_pending_transition_locks_old_actions_and_unlocks_after_receipts(self):
        actual=self.component('''
            m.pending={one:{purpose:"play_start"}}
            SiloUIBeginTransition({action:"sources"})
            blocked=m.obBusy
            m.pending={} : SiloUIDrainMaybeDone()
            print FormatJson({blocked:blocked,unlocked:m.obBusy,calls:m.calls})
        ''')
        self.assertEqual(actual,{'blocked':True,'unlocked':False,'calls':[{'choice':{'action':'sources'}}]})
    def test_auth_hides_native_video_and_clears_player_chrome(self):
        actual=self.component('''
            m.pollTimer={} : m.video={visible:true} : m.playPlan={sessionId:"lease"}
            SiloUIAuthExpired({generation:2,owner:{provider:"silo",sourceId:"silo:a",profileId:"p"}})
            print FormatJson({visible:m.video.visible,plan:m.playPlan,chrome:m.chromeReset})
        ''','''sub ObResetScope()\n m.generation=m.generation+1\nend sub
''')
        self.assertEqual(actual,{'visible':False,'plan':None,'chrome':True})
    def test_library_retry_preserves_items_and_appends_each_identity_once(self):
        from tests.test_silo_ui_plex_policy import SiloUIPlexPolicyTests
        actual=SiloUIPlexPolicyTests().scene('SiloUILibrary.brs','''
            m.provider="silo" : m.libraryToken=1 : m.libraryCursor="second" : m.libraryOffset=1
            m.libraryEmpty={} : m.grid={content:CreateObject("roSGNode","ContentNode")}
            m.grid.content.appendChild(ItemNode({itemId:"one"}))
            LibraryResult("lib_page",{ok:false},{},1)
            cursor=m.libraryCursor
            LibraryResult("lib_page",{ok:true},{items:[{itemId:"one"},{itemId:"two"}],nextCursor:"third",hasMore:true},1)
            print FormatJson({cursor:cursor,count:m.grid.content.getChildCount(),next:m.libraryCursor})
        ''',[('ItemNode','function ItemNode(item as Object,landscape=false as Boolean) as Object\n n=CreateObject("roSGNode","ContentNode")\n n.addFields({item:item})\n return n\nend function'),('LibraryShowRetry','sub LibraryShowRetry()\nend sub')])
        self.assertEqual(actual,{'cursor':'second','count':2,'next':'third'})
    def test_worker_rejects_cleanup_revision_source_and_profile_before_http(self):
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'components/ApiTask.brs').read_text()
            import re
            source=re.sub(r'function TaskDeviceSession\(.*?\nend function','function TaskDeviceSession(provider as String,session as Object) as Object\n return session\nend function',source,flags=re.S)
            source+='''
function SessionRevision(provider as String) as Integer
 return 5
end function
function LoadSession(provider as String) as Object
 return {sourceId:"silo:a",profileId:"p"}
end function
'''
            fixture=Path(root)/'worker.brs';fixture.write_text(source)
            actual=run_brightscript([fixture],'''
                a=ExecuteApiAction("silo","playback_stop",{persistProgress:false},{sessionRevision:4,sourceId:"silo:a",profileId:"p"})
                b=ExecuteApiAction("silo","playback_stop",{persistProgress:false},{sessionRevision:5,sourceId:"silo:b",profileId:"p"})
                c=ExecuteApiAction("silo","playback_stop",{persistProgress:false},{sessionRevision:5,sourceId:"silo:a",profileId:"q"})
                print FormatJson([a.errorCode,b.errorCode,c.errorCode])
            ''',root=Path(root))
            self.assertEqual(json.loads(actual.splitlines()[-1]),['session_changed']*3)
    def integrated(self, body, replacements=()):
        import re
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'source/core/SiloUIFormat.brs').read_text()+'\n'+'\n'.join((ROOT/'components'/name).read_text() for name in ['SiloUIScene.brs','SiloUIPlayer.brs','SiloUIRobustness.brs'])
            source+='\n'+(ROOT/'source/core/SiloUIPlayerPolicy.brs').read_text()
            source+='\n'+re.search(r'(?ms)^function SiloObject\(.*?^end function', (ROOT/'source/adapters/SiloAdapter.brs').read_text()).group(0)
            source=source.replace('CreateObject("roSGNode", "Dialog")','FixtureDialog()')
            for name,replacement in [
                ('ApiOwned','''sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
                    m.calls.Push({action:action,params:ParseJson(FormatJson(params)),purpose:purpose,extra:extra,owner:ParseJson(FormatJson(owner))})
                end sub'''),
                ('SiloUICleanupUuid','function SiloUICleanupUuid() as String\n return "10000000-0000-4000-8000-000000000001"\nend function'), *replacements]:
                source=re.sub(r'(?:sub|function) '+name+r'\(.*?\nend (?:sub|function)',replacement,source,count=1,flags=re.S)
            if any(name == 'ShowView' for name, _ in replacements):
                source+='\nsub HomeUpdateProgress(item as Object,scope as Dynamic)\nend sub\nsub DetailOpen(item as Object)\n m.calls.Push({reload:item.itemId})\nend sub\n'
            source+='''
function FixtureDialog() as Object
 return {observeField:sub(field,handler)
 end sub}
end function
sub ObScreen(a as String,b as String,c as String,d as String,e as Object)
end sub
sub ObChoose(choice as Object)
 m.calls.Push({choice:choice})
end sub
'''
            fixture=Path(root)/'integrated.brs';fixture.write_text(source)
            return json.loads(run_brightscript([fixture],'''m.provider="silo" : m.sourceId="silo:a" : m.profileId="p" : m.generation=2 : m.playToken=4
m.pending={} : m.cleanupTickets={} : m.calls=[] : m.video={} : m.top={}
'''+body,root=Path(root)).splitlines()[-1])
    def test_ready_prebuffer_transition_waits_for_validated_cleanup_receipt(self):
        actual=self.integrated('''
            m.prebuf={ready:true,plan:{sessionId:"lease",installationId:"device",cleanupOwner:{provider:"silo",sourceId:"silo:a",profileId:"p",generation:2,sessionRevision:7}}}
            consumed=SiloUIBeginTransition({action:"signout"})
            before=m.calls.Count() : ticket=m.calls[0].extra
            SiloUICleanupResult({ok:true},ticket)
            print FormatJson({before:before,calls:m.calls,stopped:m.video.control,content:m.video.content})
        ''')
        self.assertEqual(actual['before'],1)
        self.assertEqual(actual['calls'][0]['action'],'playback_stop')
        self.assertEqual(actual['calls'][0]['owner']['sessionRevision'],7)
        self.assertEqual(actual['calls'][1],{'choice':{'action':'signout'}})
        self.assertEqual(actual['stopped'],'stop')
        self.assertIsNone(actual['content'])
    def test_scene_stale_start_cleanup_precedes_generation_drop_and_never_binds_video(self):
        actual=self.integrated('''
            task={unobserveField:function(name as String) as Boolean
                return true
            end function}
            m.pending={one:{task:task,purpose:"play_start",extra:1,generation:1,owner:{provider:"silo",sourceId:"silo:a",profileId:"p",generation:1}}}
            event={getData:function() as Object
                return {requestId:"one",ok:true,sessionRevision:7,plan:{sessionId:"lease",installationId:"device",url:"synthetic"}}
            end function}
            onApiResult(event)
            print FormatJson({calls:m.calls,pending:m.pending.Count(),video:m.video})
        ''')
        self.assertEqual(len(actual['calls']),1)
        self.assertFalse(actual['calls'][0]['params']['persistProgress'])
        self.assertEqual(actual['pending'],0)
        self.assertEqual(actual['video'],{})
    def test_cleanup_without_captured_owner_never_uses_current_credentials(self):
        actual=self.integrated('''
            PlayerStopSession({sessionId:"unknown"},false)
            print FormatJson({calls:m.calls.Count(),unconfirmed:m.cleanupUnconfirmed})
        ''')
        self.assertEqual(actual,{'calls':0,'unconfirmed':True})
    def test_cleanup_without_captured_revision_never_uses_current_credentials(self):
        actual=self.integrated('''
            PlayerStopSession({sessionId:"unknown",cleanupOwner:{provider:"silo",sourceId:"silo:a",profileId:"p",generation:2}},false)
            print FormatJson({calls:m.calls.Count(),unconfirmed:m.cleanupUnconfirmed})
        ''')
        self.assertEqual(actual,{'calls':0,'unconfirmed':True})

    def test_current_start_failure_reaches_player_error_ui(self):
        actual=self.integrated('''m.playLoading=true : m.playClock=CreateObject("roTimespan") : m.toast={} : m.toastTimer={}
            task={unobserveField:function(name as String) as Boolean
                return true
            end function}
            m.pending={one:{task:task,purpose:"play_start",extra:4,generation:2,owner:{provider:"silo",sourceId:"silo:a",profileId:"p",generation:2}}}
            event={getData:function() as Object
                return {requestId:"one",ok:false,errorCode:"network_error",sessionRevision:7,plan:{sessionId:"lease",installationId:"device"}}
            end function}
            onApiResult(event)
            print FormatJson({loading:m.playLoading,message:m.top.dialog.message,tickets:m.cleanupTickets.Count()})''')
        self.assertFalse(actual['loading'])
        self.assertIn('#2001',actual['message'])
        self.assertNotIn('network_error',actual['message'])
        self.assertEqual(actual['tickets'],1)
    def test_player_return_reloads_evicted_detail_instead_of_empty_episode_zone(self):
        actual=self.integrated('''m.view="player" : m.video={position:1} : m.progressTimer={} : m.progressSequence=0
            m.playItem={itemId:"episode"} : m.playerReturn={view:"detail",zone:"episodes"}
            m.detailReloadItem={itemId:"series",type:"series",title:"Series"}
            PlayerClose(false)
            print FormatJson(m.calls)''',[
            ('PlayerResetChrome','sub PlayerResetChrome()\nend sub'),
            ('PlayerReport','sub PlayerReport(action as String, positionMs=invalid as Dynamic, finalSample=invalid as Dynamic)\nend sub'),
            ('ShowView','sub ShowView(view as String)\n m.view=view\nend sub')])
        self.assertEqual(actual,[{'reload':'series'}])
    def test_late_home_failure_preserves_search_focus(self):
        from tests.test_silo_ui_settings_policy import SiloUISettingsPolicyTests
        actual=SiloUISettingsPolicyTests().component('SiloUIHome.brs','''
            m.view="search" : m.zone="keyboard" : m.homeRows=[] : m.homeRetryButtons={}
            HomeShowRetry()
            print FormatJson({zone:m.zone,retry:m.homeRetry})
        ''',[('HeroShow','sub HeroShow(item as Object)\nend sub')],'''sub BuildButtons(a as Object,b as String,c as Object)\nend sub
sub SetZone(zone as String)\n m.zone=zone\nend sub''')
        self.assertEqual(actual,{'zone':'keyboard','retry':True})
    def test_expired_source_selection_and_saved_status_require_fresh_login(self):
        from tests.test_silo_ui_settings_policy import SiloUISettingsPolicyTests
        for provider,poll,data,completed in [('silo','ob_device_poll','{status:"approved"}','ob_profile_set')]:
            actual=SiloUISettingsPolicyTests().component('SiloUIOnboarding.brs','''
                m.calls=[] : m.obStatus={} : m.authExpiredProviders={'''+provider+''':true}
                ObChoose({action:"'''+provider+'''"})
                OnboardingResult("ob_source_status",{ok:true},{connected:true},"'''+provider+'''")
                blocked=m.calls.Count()
                m.obMode="'''+provider+'''"
                OnboardingResult("'''+poll+'''",{ok:true},'''+data+''',invalid)
                OnboardingResult("'''+completed+'''",{ok:true},{},invalid)
                ObChoose({action:"'''+provider+'''"})
                print FormatJson({calls:m.calls,blocked:blocked,expired:m.authExpiredProviders.'''+provider+'''})
            ''',[
                ('ObStartSilo','sub ObStartSilo()\n m.calls.Push("fresh_silo")\nend sub'),
                ('ObStartPlex','sub ObStartPlex()\n m.calls.Push("fresh_plex")\nend sub')],'''
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
 m.calls.Push(action)
end sub
sub EnterSource(provider as String,status as Object)
 m.calls.Push("entered_"+provider)
end sub
''')
            self.assertEqual(actual['calls'][:2],['fresh_'+provider]*2)
            self.assertEqual(actual['blocked'],2)
            self.assertFalse(actual['expired'])
            self.assertEqual(actual['calls'][-2:],['entered_'+provider,'session_status'])
    def test_scope_reset_clears_remaining_private_detail_references(self):
        from tests.test_silo_ui_settings_policy import SiloUISettingsPolicyTests
        actual=SiloUISettingsPolicyTests().component('SiloUIOnboarding.brs','''
            m.generation=1 : m.keyboard={} : m.searchTimer={}
            m.detailSeasons=[{itemId:"old"}] : m.detailPlexSeasons=[{itemId:"old"}]
            m.detailFocusEpisode={itemId:"old"} : m.detailReloadItem={itemId:"old"}
            m.detailCast={content:{getChild:function(index)
                return invalid
            end function}} : m.detailCastCount=2
            ObResetScope()
            print FormatJson({cacheRetired:m.cacheRetired,seasons:m.detailSeasons,plex:m.detailPlexSeasons,episode:m.detailFocusEpisode,reload:m.detailReloadItem,cast:m.detailCast.content,count:m.detailCastCount})
        ''',helpers='''sub HomeCacheRetire()
 m.cacheRetired=true
end sub
sub PlayerDiscardPrebuffer()\nend sub
sub PlexClearImages()\nend sub''')
        self.assertEqual(actual,{'cacheRetired':True,'seasons':[],'plex':[],'episode':None,'reload':None,'cast':None,'count':0})
