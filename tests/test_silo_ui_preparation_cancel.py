"""Browse navigation cancels foreground preparation and collects late leases."""
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class PreparationCancel(unittest.TestCase):
    def scene(self, code, before_play=""):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = '\n'.join((ROOT/'components'/name).read_text() for name in
                               ('SiloUIScene.brs', 'SiloUIPlayer.brs', 'SiloUIRobustness.brs'))
            for name in ('PlayerStart', 'PlayerResetChrome', 'PlayerShowFailure',
                         'SiloUICleanupUuid', 'SetZone', 'SiloUIFocusTrace'):
                source = re.sub(r'(?im)^(sub|function) '+name+r'\(', r'\1 Unused'+name+'(', source, count=1)
            fixture = folder/'scene.brs'
            fixture.write_text(source.replace('CreateObject("roSGNode", "ApiTask")','FixtureTask()'))
            boundary = folder/'boundary.brs'
            boundary.write_text('''sub HomeCacheYield()
end sub
sub HomeCacheSave()
end sub
function FixtureTask() as Object
 return {unobserveField:sub(field)
 end sub,observeField:sub(field,callback)
  job=m.job
  owner={provider:job.provider,sourceId:job.sourceId,profileId:job.profileId,generation:job.generation}
  if job.sessionRevision<>invalid then owner.sessionRevision=job.sessionRevision
  GetGlobalAA()["fixtureRequests"].Push({id:job.requestId,action:job.action,params:job.params,owner:owner})
 end sub}
end function
sub PlayerStart(plan as Object,bound=false as Boolean)
 m.starts.Push(plan.sessionId)
 m.playPlan=plan:m.playLoading=false:m.view="player"
end sub
sub PlayerResetChrome()
end sub
sub PlayerShowFailure(stage as String,result as Dynamic)
 m.errors.Push(stage)
end sub
function SiloUICleanupUuid() as String
 return "10000000-0000-4000-8000-000000000001"
end function
sub SetZone(zone as String)
 m.zone=zone
end sub
sub DetailPhotosClear()
end sub
sub DetailPhotosStart()
end sub
sub HomeSyncTimer()
end sub
sub HomeRefreshHero()
end sub
sub SiloUIFocusTrace(stage as String,key as String)
end sub
function HomeProgressScope() as String
 return "scope"
end function
function ResultEvent(value as Object) as Object
 return {value:value,getData:function() as Object
 return m.value
 end function}
end function
''')
            setup = '''m.provider="silo":m.sourceId="silo:one":m.profileId="profile":m.generation=2
 m.playToken=1:m.playLoading=false:m.view="detail":m.zone="detailButtons":m.requestId=0
 m.pending={}:m.cleanupTickets={}:m.requests=[]:GetGlobalAA()["fixtureRequests"]=m.requests:m.starts=[]:m.errors=[]:m.preferences={quality:"original",subtitles:"off"}
 m.top={findNode:function(name as String) as Object
 return {}
 end function}
 m.nav={}:m.video={}:m.backdrop={}:m.backdropOld={}:m.backdropTimer={}:m.backdropFade={}:m.toast={text:""}:m.toastTimer={}
 m.history=[{view:"home",zone:"heroButtons"}]
 item={itemId:"movie",type:"movie",title:"Fixture"}
 detail={item:item,versions:[{versionId:"file",sourceId:m.sourceId,itemId:"movie"}]}
''' + before_play + '''
 PlayItem(item,0)
'''
            files = [fixture, boundary, ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'components/SiloUISubtitleArtifact.brs', ROOT/'source/core/SiloUIFormat.brs',
                     ROOT/'source/core/SiloUIDetailPolicy.brs', ROOT/'source/core/SiloUISettingsPolicy.brs']
            output = run_brightscript(files, setup+code, root=folder)
            return json.loads(output.strip().splitlines()[-1])

    def test_foreground_waits_for_retired_ready_preload_cleanup(self):
        result = self.scene('''onApiResult(ResultEvent({requestId:2,ok:true,data:detail}))
 before={requests:m.requests.Count(),errors:m.errors.Count(),loading:m.playLoading}
 onApiResult(ResultEvent({requestId:1,ok:true}))
 print FormatJson({before:before,requests:m.requests.Count(),errors:m.errors,loading:m.playLoading})''', before_play='''m.prebuf={token:1,ready:true,itemId:"movie",startMs:9000,plan:{sessionId:"preload",installationId:"install",cleanupOwner:{provider:"silo",sourceId:m.sourceId,profileId:m.profileId,generation:2,sessionRevision:7}}}''')
        self.assertEqual(dict(before=dict(requests=2,errors=0,loading=True),requests=3,errors=[],loading=True), result)

    def test_foreground_waits_for_late_preload_in_both_callback_orders(self):
        for detail_first in (True, False):
            with self.subTest(detail_first=detail_first):
                detail_event = 'onApiResult(ResultEvent({requestId:2,ok:true,data:detail}))'
                preload_event = 'onApiResult(ResultEvent({requestId:1,ok:true,sessionRevision:7,plan:{sessionId:"preload",installationId:"install"}}))'
                events = [detail_event, preload_event] if detail_first else [preload_event, detail_event]
                result = self.scene('\n'.join(events)+'''
 before={requests:m.requests.Count(),errors:m.errors.Count(),loading:m.playLoading}
 onApiResult(ResultEvent({requestId:3,ok:true}))
 print FormatJson({before:before,requests:m.requests.Count(),last:m.requests[m.requests.Count()-1].action,errors:m.errors})''', before_play='''m.requestId=1
 m.prebuf={token:1,ready:false,itemId:"movie"}
 task=FixtureTask():task.job={requestId:1}
 m.pending["1"]={task:task,purpose:"play_prebuf",extra:1,generation:2,owner:SiloUIOwner()}''')
                self.assertEqual(dict(before=dict(requests=2,errors=0,loading=True),requests=3,last='playback_start',errors=[]), result)

    def test_retired_preload_wait_cannot_restart_after_back_or_scope_change(self):
        for cancel in ('onKeyEvent("back",true)', 'm.generation=3', 'm.sourceId="silo:other"', 'm.profileId="other"', 'm.playToken=99'):
            with self.subTest(cancel=cancel):
                result = self.scene('''onApiResult(ResultEvent({requestId:2,ok:true,data:detail}))
 '''+cancel+'''
 onApiResult(ResultEvent({requestId:1,ok:true}))
 print FormatJson({requests:m.requests.Count(),starts:m.starts,errors:m.errors})''', before_play='''m.prebuf={token:1,ready:true,itemId:"movie",startMs:9000,plan:{sessionId:"preload",installationId:"install",cleanupOwner:{provider:"silo",sourceId:m.sourceId,profileId:m.profileId,generation:2,sessionRevision:7}}}''')
                self.assertEqual(dict(requests=2,starts=[],errors=[]), result)

    def test_failed_preload_cleanup_requires_explicit_play_after_retry(self):
        result = self.scene('''onApiResult(ResultEvent({requestId:2,ok:true,data:detail}))
 onApiResult(ResultEvent({requestId:1,ok:false,errorCode:"network_error"}))
 failed={requests:m.requests.Count(),loading:m.playLoading,errors:m.errors.Count()}
 SiloUIRetryCleanup()
 onApiResult(ResultEvent({requestId:3,ok:true}))
 after=m.requests.Count()
 PlayItem(item,0)
 onApiResult(ResultEvent({requestId:4,ok:true,data:detail}))
 print FormatJson({failed:failed,after:after,requests:m.requests.Count(),errors:m.errors,last:m.requests[m.requests.Count()-1].action})''', before_play='''m.prebuf={token:1,ready:true,itemId:"movie",startMs:9000,plan:{sessionId:"preload",installationId:"install",cleanupOwner:{provider:"silo",sourceId:m.sourceId,profileId:m.profileId,generation:2,sessionRevision:7}}}''')
        self.assertEqual(dict(failed=dict(requests=2,loading=False,errors=1),after=3,requests=5,errors=['session'],last='playback_start'), result)

    def test_replacement_play_keeps_retired_preload_wait(self):
        for detail_first in (True, False):
            with self.subTest(detail_first=detail_first):
                detail_event='onApiResult(ResultEvent({requestId:3,ok:true,data:detail}))'
                preload_event='onApiResult(ResultEvent({requestId:1,ok:true,sessionRevision:7,plan:{sessionId:"preload",installationId:"install"}}))'
                events=[detail_event,preload_event] if detail_first else [preload_event,detail_event]
                result=self.scene('PlayItem(item,0)\nonApiResult(ResultEvent({requestId:2,ok:true,data:detail}))\n'+'\n'.join(events)+'''
 before={requests:m.requests.Count(),errors:m.errors.Count()}
 onApiResult(ResultEvent({requestId:4,ok:true}))
 print FormatJson({before:before,requests:m.requests.Count(),last:m.requests[m.requests.Count()-1].action,errors:m.errors})''', before_play='''m.requestId=1
 m.prebuf={token:1,ready:false,itemId:"movie"}
 task=FixtureTask():task.job={requestId:1}
 m.pending["1"]={task:task,purpose:"play_prebuf",extra:1,generation:2,owner:SiloUIOwner()}''')
                self.assertEqual(dict(before=dict(requests=3,errors=0),requests=4,last='playback_start',errors=[]),result)

    def test_play_after_back_waits_for_previously_retired_preload(self):
        for detail_first in (True, False):
            with self.subTest(detail_first=detail_first):
                detail_event='onApiResult(ResultEvent({requestId:3,ok:true,data:detail}))'
                preload_event='onApiResult(ResultEvent({requestId:1,ok:true,sessionRevision:7,plan:{sessionId:"preload",installationId:"install"}}))'
                events=[detail_event,preload_event] if detail_first else [preload_event,detail_event]
                result=self.scene('onKeyEvent("back",true):PlayItem(item,0)\n'+'\n'.join(events)+'''
 before={requests:m.requests.Count(),errors:m.errors.Count()}
 onApiResult(ResultEvent({requestId:4,ok:true}))
 print FormatJson({before:before,requests:m.requests.Count(),last:m.requests[m.requests.Count()-1].action,errors:m.errors})''', before_play='''m.requestId=1
 m.prebuf={token:1,ready:false,itemId:"movie"}
 task=FixtureTask():task.job={requestId:1}
 m.pending["1"]={task:task,purpose:"play_prebuf",extra:1,generation:2,owner:SiloUIOwner()}''')
                self.assertEqual(dict(before=dict(requests=3,errors=0),requests=4,last='playback_start',errors=[]),result)

    def test_failed_cleanup_retires_delayed_detail_even_after_retry(self):
        result=self.scene('''onApiResult(ResultEvent({requestId:1,ok:false,errorCode:"network_error"}))
 SiloUIRetryCleanup()
 onApiResult(ResultEvent({requestId:3,ok:true}))
 onApiResult(ResultEvent({requestId:2,ok:true,data:detail}))
 print FormatJson({requests:m.requests.Count(),errors:m.errors,loading:m.playLoading})''', before_play='''m.prebuf={token:1,ready:true,itemId:"movie",startMs:9000,plan:{sessionId:"preload",installationId:"install",cleanupOwner:{provider:"silo",sourceId:m.sourceId,profileId:m.profileId,generation:2,sessionRevision:7}}}''')
        self.assertEqual(dict(requests=3,errors=['session'],loading=False),result)

    def test_compatible_preload_still_promotes_without_requests(self):
        result = self.scene('''print FormatJson({requests:m.requests.Count(),starts:m.starts,errors:m.errors})''', before_play='''m.prebuf={token:1,ready:true,itemId:"movie",startMs:0,item:item,versions:detail.versions,markers:[],plan:{sessionId:"preload"}}''')
        self.assertEqual(dict(requests=0,starts=['preload'],errors=[]), result)

    def test_back_before_detail_result_cancels_without_start_or_error(self):
        result = self.scene('''before=m.playToken:onKeyEvent("back",true)
 onApiResult(ResultEvent({requestId:1,ok:true,data:detail}))
 print FormatJson({view:m.view,loading:m.playLoading,invalidated:m.playToken>before,requests:m.requests.Count(),starts:m.starts,errors:m.errors})''')
        self.assertEqual(dict(view='home', loading=False, invalidated=True, requests=1, starts=[], errors=[]), result)

    def test_back_during_allocation_cleans_success_once_without_binding(self):
        result = self.scene('''onApiResult(ResultEvent({requestId:1,ok:true,data:detail}))
 onKeyEvent("back",true)
 late={requestId:2,ok:true,sessionRevision:7,plan:{url:"https://example.invalid/media",sessionId:"old-lease",installationId:"install"}}
 onApiResult(ResultEvent(late)):onApiResult(ResultEvent(late))
 cleanupCall={params:{},owner:{}}
 if m.requests.Count()>2 then cleanupCall=m.requests[2]
 print FormatJson({view:m.view,loading:m.playLoading,starts:m.starts,errors:m.errors,requests:m.requests.Count(),action:cleanupCall.action,persist:cleanupCall.params.persistProgress,lease:cleanupCall.params.sessionId,revision:cleanupCall.owner.sessionRevision,tickets:m.cleanupTickets.Count()})''')
        self.assertEqual(dict(view='home', loading=False, starts=[], errors=[], requests=3,
                              action='playback_stop', persist=False, lease='old-lease', revision=7, tickets=1), result)

    def test_cancelled_failure_is_silent_and_does_not_stop_new_attempt(self):
        result = self.scene('''onApiResult(ResultEvent({requestId:1,ok:true,data:detail}))
 onKeyEvent("back",true)
 PlayItem(item,0)
 onApiResult(ResultEvent({requestId:2,ok:false,errorCode:"network_error"}))
 onApiResult(ResultEvent({requestId:3,ok:true,data:detail}))
 onApiResult(ResultEvent({requestId:4,ok:true,sessionRevision:7,plan:{url:"https://example.invalid/new",sessionId:"new-lease",installationId:"install"}}))
 print FormatJson({starts:m.starts,errors:m.errors,requests:m.requests.Count(),loading:m.playLoading})''')
        self.assertEqual(dict(starts=['new-lease'], errors=[], requests=4, loading=False), result)

    def test_back_cancelled_failed_allocation_is_silent(self):
        result = self.scene('''onApiResult(ResultEvent({requestId:1,ok:true,data:detail}))
 onKeyEvent("back",true)
 onApiResult(ResultEvent({requestId:2,ok:false,errorCode:"network_error"}))
 print FormatJson({view:m.view,loading:m.playLoading,starts:m.starts,errors:m.errors,requests:m.requests.Count()})''')
        self.assertEqual(dict(view='home', loading=False, starts=[], errors=[], requests=2), result)

    def test_late_lease_cleanup_blocks_new_dispatch_until_ack_then_explicit_play(self):
        result = self.scene('''onApiResult(ResultEvent({requestId:1,ok:true,data:detail}))
 onKeyEvent("back",true):PlayItem(item,0)
 late={requestId:2,ok:true,sessionRevision:7,plan:{url:"https://example.invalid/old",sessionId:"old-lease",installationId:"install"}}
 onApiResult(ResultEvent(late)):onApiResult(ResultEvent(late))
 onApiResult(ResultEvent({requestId:3,ok:true,data:detail}))
 waiting={starts:m.starts.Count(),requests:m.requests.Count(),tickets:m.cleanupTickets.Count()}
 onApiResult(ResultEvent({requestId:4,ok:true}))
 PlayItem(item,0)
 onApiResult(ResultEvent({requestId:5,ok:true,data:detail}))
 onApiResult(ResultEvent({requestId:6,ok:true,sessionRevision:7,plan:{url:"https://example.invalid/new",sessionId:"new-lease",installationId:"install"}}))
 cleanupCall=m.requests[3]
 print FormatJson({waiting:waiting,starts:m.starts,errors:m.errors,requests:m.requests.Count(),action:cleanupCall.action,lease:cleanupCall.params.sessionId,persist:cleanupCall.params.persistProgress,active:m.playPlan.sessionId})''')
        self.assertEqual(dict(waiting=dict(starts=0,requests=4,tickets=1),starts=['new-lease'], errors=['session'], requests=6, action='playback_stop',
                              lease='old-lease', persist=False, active='new-lease'), result)

    def test_home_back_also_cancels_even_without_a_view_change(self):
        result = self.scene('''m.view="home":m.zone="heroButtons":before=m.playToken
 onKeyEvent("back",true)
 onApiResult(ResultEvent({requestId:1,ok:true,data:detail}))
 print FormatJson({view:m.view,zone:m.zone,loading:m.playLoading,invalidated:m.playToken>before,requests:m.requests.Count(),errors:m.errors})''')
        self.assertEqual(dict(view='home', zone='nav', loading=False, invalidated=True, requests=1, errors=[]), result)

    def test_navigation_to_another_view_cancels_preparation(self):
        result = self.scene('''ShowView("library")
 onApiResult(ResultEvent({requestId:1,ok:true,data:detail}))
 print FormatJson({view:m.view,loading:m.playLoading,requests:m.requests.Count(),errors:m.errors})''')
        self.assertEqual(dict(view='library', loading=False, requests=1, errors=[]), result)

    def test_new_detail_visit_cancels_even_when_view_name_is_unchanged(self):
        result = self.scene('''ShowView("detail")
 onApiResult(ResultEvent({requestId:1,ok:true,data:detail}))
 print FormatJson({view:m.view,loading:m.playLoading,requests:m.requests.Count(),errors:m.errors})''')
        self.assertEqual(dict(view='detail', loading=False, requests=1, errors=[]), result)
