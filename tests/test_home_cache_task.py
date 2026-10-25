"""Run Home cache ownership/read boundaries and live-response publication handlers."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT/'source/core/HomeCachePolicy.brs'
OWNER = 'a'*64
SCOPE = {'provider':'silo','sourceId':'silo:https://fixture.test','profileId':'p1','generation':2,'token':5}
SESSION = {'accountId':'account-1','sourceId':SCOPE['sourceId'],'profileId':'p1','accessToken':'synthetic','profileToken':'profile'}
ROW = {'rowId':'recent','title':'Recently added','sectionType':'recently_added','items':[{'itemId':'1','title':'Fixture','type':'movie','art':{'poster':f'cachefs:/silo-home-v1-{OWNER}-0.img'}}]}

BOUNDARY = '''
function LoadSession(provider as String) as Object
    return m.current
end function
function SessionRevision(provider as String) as Integer
    return m.revision
end function
function HomeCacheFileBytes(path as String, maximum as Integer) as Dynamic
    if m.nativeStat then return NativeHomeCacheFileBytes(path,maximum)
    if Right(path,5) = ".json"
        bytes = CreateObject("roByteArray")
        bytes.FromAsciiString(m.json)
        return bytes
    end if
    return m.image
end function
function FixtureDate() as Object
    return {AsSeconds:function() as Integer
        return 100000
    end function}
end function
function HomeCacheTransfer(url as String, head as Boolean) as Dynamic
    if m.nativeTransfer then return NativeHomeCacheTransfer(url,head)
    m.requestCount++
    if m.changeAt = m.requestCount then m.current.profileId = "other"
    return {status:200,headers:{"content-length":"24"}}
end function
function FixtureWrite(bytes as Object, path as String) as Boolean
    if Right(path,5) = ".part" then m.metadata = ParseJson(bytes.ToAsciiString(),"i")
    m.written.Push(path)
    return true
end function
function RunWrite(rows as Object, changeAt as Integer) as Object
    m.current = {accountId:"account-1",sourceId:"silo:https://fixture.test",profileId:"p1",accessToken:"synthetic",profileToken:"profile"}
    m.cacheSession = ParseJson(FormatJson(m.current),"i")
    m.revision = 3:m.cacheRevision = 3
    m.cacheJob = {provider:"silo",sourceId:"silo:https://fixture.test",profileId:"p1",rows:rows}
    m.top = {cancelled:false}
    m.cacheOwner = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    m.cacheClock = {TotalMilliseconds:function() as Integer
        return 0
    end function}
    m.nativeTransfer = changeAt = -3 or changeAt = -4
    m.oversized = changeAt = -4
    m.failedDelete = changeAt = -1
    m.existingFiles = changeAt = -2
    m.cacheFs = {global:m,GetDirectoryListing:function(path as String) as Object
        if m.global.existingFiles
            files = CreateObject("roList")
            files.AddTail("silo-home-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json")
            files.AddTail("silo-home-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-0.img")
            return files
        end if
        if m.global.failedDelete then return ["silo-home-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json","silo-home-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-0.img"]
        return []
    end function,Delete:function(path as String) as Boolean
        m.global.deleted.Push(path)
        return not m.global.failedDelete
    end function,Exists:function(path as String) as Boolean
        return m.global.failedDelete
    end function,Stat:function(path as String) as Dynamic
        if m.global.oversized then return {size:262145}
        if not m.global.failedDelete then return {}
        return {size:100}
    end function,Rename:function(fromPath as String, toPath as String) as Boolean
        return true
    end function}
    m.image = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,150,0,0,0,225]
    m.requestCount = 0:m.changeAt = changeAt:m.written = []:m.metadata = invalid:m.deleted=[]
    HomeCacheWrite()
    return {written:m.written,metadata:m.metadata,requests:m.requestCount,deleted:m.deleted}
end function
function FixtureTransfer() as Object
    return {SetMessagePort:sub(port as Object)
    end sub,SetUrl:sub(url as String)
    end sub,SetCertificatesFile:sub(path as String)
    end sub,EnablePeerVerification:sub(enabled as Boolean)
    end sub,EnableHostVerification:sub(enabled as Boolean)
    end sub,RetainBodyOnError:sub(enabled as Boolean)
    end sub,AddHeader:sub(key as String,value as String)
    end sub,AsyncHead:function() as Boolean
        return true
    end function,AsyncGetToFile:function(path as String) as Boolean
        return true
    end function,GetIdentity:function() as Integer
        return 1
    end function,AsyncCancel:sub()
    end sub}
end function
function FixtureWait(timeout as Integer, port as Object) as Object
    return {GetSourceIdentity:function() as Integer
        return 1
    end function,GetResponseCode:function() as Integer
        return 200
    end function,GetResponseHeaders:function() as Object
        return {"content-length":"24"}
    end function}
end function
function RunMissingRead(stat as Dynamic) as Object
    m.nativeStat = true
    m.stat = stat
    m.cacheOwner = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    m.cacheFs = {global:m,Stat:function(path as String) as Dynamic
        return m.global.stat
    end function}
    return HomeCacheRead()
end function
function RunRead(session as Object, current as Object, snapshot as Object, cancelled as Boolean) as Object
    m.cacheSession = session
    m.current = current
    m.revision = 3
    m.cacheRevision = 3
    m.cacheJob = {provider:"silo",sourceId:"silo:https://fixture.test",profileId:"p1"}
    m.top = {cancelled:cancelled}
    m.cacheOwner = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    m.json = FormatJson(snapshot)
    m.image = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,150,0,0,0,225]
    return HomeCacheRead()
end function
function SiloUIOwner() as Object
    return m.scope
end function
function NumberOr(value as Dynamic, fallback as Integer) as Integer
    if value = invalid then return fallback
    return value
end function
sub HomeSetRows(rows as Object)
    m.published = rows
end sub
function SiloUIHomeHeroRow(rows as Dynamic) as Integer
    return 0
end function
function RunYield(action as String, view as String, fresh as Boolean, pendingPurge as Boolean, reload = false as Boolean) as Object
    m.homeCacheEnabled = true
    m.view = "home":m.provider = "silo":m.homeCacheFresh = fresh
    m.homeCacheSaved = false:m.homeSnapshotScope = "scope"
    m.homeRows = [{title:"Previous library",items:[{itemId:"old"}]}]
    m.homeReload = reload
    m.homeCacheJob = {action:action}
    task = {cancelled:false,unobserveField:sub(name as String)
    end sub}
    m.homeCacheTask = task
    HomeCacheYield()
    m.view = view
    m.homeCachePurgePending = pendingPurge
    event = {getData:function() as Object
        return {ok:false}
    end function}
    onHomeCacheResult(event)
    cancelled = task.cancelled
    afterDrain = m.started
    m.view = "home":m.homeCacheYielded = false
    HomeCacheSave()
    return {cancelled:cancelled,afterDrain:afterDrain,afterReturn:m.started}
end function
function FixtureCacheTask() as Object
    m.taskCount = NumberOr(m.taskCount,0) + 1
    return {global:m,observeField:sub(field as String, callback as String)
        m.global.started = m.job.action
    end sub}
end function
function RunCacheGate(enabled as Boolean, action as String) as Object
    m.homeCacheEnabled = enabled
    m.view = "home":m.provider = "silo":m.homeSnapshotScope = "scope"
    m.homeRows = []:m.homeCacheFresh = true
    m.taskCount = 0
    if action = "save"
        HomeCacheSave()
    else
        HomeCacheStart(action)
    end if
    return {tasks:m.taskCount,started:m.started}
end function
function SiloUIHomeHydration(rows as Object, scope as String) as Object
    return {rows:rows}
end function
function HomeProgressScope() as String
    return "scope"
end function
sub HomeHydrationPump()
end sub
function RunPublication(scope as Object, fresh as Boolean, pendingPurge as Boolean, view = "home" as String, cancelled = false as Boolean) as Object
    m.homeCacheEnabled = true
    m.view = view
    m.scope = scope
    m.homeCacheFresh = false
    m.homeCachePurgePending = pendingPurge
    m.homeToken = 5
    m.homeCacheJob = {provider:"silo",sourceId:"silo:https://fixture.test",profileId:"p1",generation:2,token:5,action:"read"}
    m.homeCacheTask = {cancelled:cancelled,unobserveField:sub(name as String)
    end sub}
    m.published = invalid
    if fresh then HomeResult("home_silo",{ok:true},{rows:[]},{token:5,scope:"scope"})
    event = {getData:function() as Object
        return {ok:true,rows:[{title:"Cached"}]}
    end function}
    onHomeCacheResult(event)
    return {published:m.published,started:m.started,loadedScope:m.homeLoadedScope,fresh:m.homeCacheFresh}
end function
'''

class HomeCacheTaskTests(unittest.TestCase):
    def call(self, function, args):
        with tempfile.TemporaryDirectory(prefix='silo_ui-home-cache-') as directory:
            temporary = Path(directory)
            worker = (ROOT/'components/HomeCacheTask.brs').read_text().replace('function HomeCacheFileBytes(', 'function NativeHomeCacheFileBytes(',1).replace('CreateObject("roDateTime")','FixtureDate()').replace('function HomeCacheTransfer(', 'function NativeHomeCacheTransfer(',1).replace('bytes.WriteFile(path+".part")','FixtureWrite(bytes,path+".part")').replace('return bytes.WriteFile(path)','return FixtureWrite(bytes,path)')
            worker = worker.replace('CreateObject("roUrlTransfer")','FixtureTransfer()').replace('wait(50,port)','FixtureWait(50,port)').replace('type(event) = "roUrlEvent"','type(event) = "roAssociativeArray"')
            (temporary/'worker.brs').write_text(worker)
            home=(ROOT/'components/SiloUIHome.brs').read_text()
            handlers='\n'.join(re.search(r'(?ms)^sub '+name+r'\(.*?^end sub',home).group(0) for name in ('HomeResult','onHomeCacheResult','HomeCacheSave','HomeCacheYield','HomeCacheStart'))
            (temporary/'handler.brs').write_text(handlers.replace('CreateObject("roSGNode","HomeCacheTask")','FixtureCacheTask()'))
            (temporary/'fixture.brs').write_text(BOUNDARY)
            return run_function([POLICY,temporary/'worker.brs',temporary/'handler.brs',temporary/'fixture.brs'],function,args)

    def snapshot(self, **changes):
        return {'schema':1,'owner':OWNER,'savedAt':99900,'row':ROW,'hero':'',**changes}

    def test_shipping_cache_gate_blocks_optional_tasks_but_allows_cleanup(self):
        for action in ['read','write','save']:
            self.assertEqual(0,self.call('RunCacheGate',[False,action])['tasks'])
        self.assertEqual('purge',self.call('RunCacheGate',[False,'purge'])['started'])
        self.assertEqual('read',self.call('RunCacheGate',[True,'read'])['started'])
        home = (ROOT/'components/SiloUIHome.brs').read_text()
        init = re.search(r'(?ms)^sub HomeInit\(.*?^end sub',home).group(0)
        self.assertIn('m.homeCacheEnabled = false',init)

    def test_evicted_or_unavailable_manifest_is_a_read_miss(self):
        for stat in [{}, {'size':None}, {'size':'unknown'}, {'size':False}]:
            with self.subTest(stat=stat):
                self.assertEqual({'ok':False}, self.call('RunMissingRead',[stat]))

    def test_restart_read_restores_local_art_but_no_personal_state(self):
        result=self.call('RunRead',[SESSION,SESSION,self.snapshot(),False])
        self.assertTrue(result['ok'])
        self.assertTrue(result['rows'][0]['items'][0]['homeCached'])
        self.assertNotIn('synthetic',json.dumps(result))
        self.assertNotIn('resumeMs',result['rows'][0]['items'][0])

    def test_owner_ttl_path_and_session_changes_fail_closed(self):
        for snapshot in [self.snapshot(owner='b'*64),self.snapshot(savedAt=1),self.snapshot(schema=2),self.snapshot(row={**ROW,'items':[{'itemId':'1','title':'Bad','type':'movie','art':{'poster':'cachefs:/unrelated.img'}}]})]:
            with self.subTest(snapshot=snapshot):
                self.assertFalse(self.call('RunRead',[SESSION,SESSION,snapshot,False])['ok'])
        for current in [{**SESSION,'accountId':'other'},{**SESSION,'profileId':'p2'},{**SESSION,'accessToken':''},{**SESSION,'accountId':''}]:
            self.assertFalse(self.call('RunRead',[SESSION,current,self.snapshot(),False])['ok'])
        self.assertFalse(self.call('RunRead',[SESSION,SESSION,self.snapshot(),True])['ok'])

    def test_live_empty_home_is_authoritative_over_late_snapshot(self):
        self.assertIsNone(self.call('RunPublication',[SCOPE,True,False])['published'])
        self.assertIsNotNone(self.call('RunPublication',[SCOPE,False,False])['published'])
        self.assertIsNone(self.call('RunPublication',[{**SCOPE,'profileId':'p2'},False,False])['published'])
        retiring=self.call('RunPublication',[SCOPE,False,True])
        self.assertIsNone(retiring['published'])
        self.assertEqual('purge',retiring['started'])

    def test_foreground_and_navigation_yield_before_competing_work(self):
        scene = (ROOT/'components/SiloUIScene.brs').read_text()
        show = re.search(r'(?ms)^sub ShowView\(.*?^end sub',scene).group(0)
        self.assertIn('if m.view = "home" and view <> "home" then HomeCacheYield()',show)
        self.assertIn('m.homeCacheYielded = false',show)
        player = (ROOT/'components/SiloUIPlayer.brs').read_text()
        play = re.search(r'(?ms)^sub PlayItem\(.*?^end sub',player).group(0)
        self.assertLess(play.index('HomeCacheYield()'),play.index('SiloUIPlaybackAdmissionBlocked()'))
        prebuffer = re.search(r'(?ms)^sub PlayerPrebuffer\(.*?^end sub',player).group(0)
        self.assertLess(prebuffer.index('HomeCacheYield()'),prebuffer.index('Api("playback_start"'))

    def test_return_home_defers_cache_save_until_pending_reload_is_resolved(self):
        result = self.call('RunYield',['read','detail',True,False,True])
        self.assertIsNone(result['afterDrain'])
        self.assertIsNone(result['afterReturn'])

    def test_navigation_yields_and_drains_without_purge_then_home_can_save(self):
        result = self.call('RunYield',['write','detail',True,False])
        self.assertTrue(result['cancelled'])
        self.assertIsNone(result['afterDrain'])
        self.assertEqual('write',result['afterReturn'])
        retired = self.call('RunYield',['write','detail',True,True])
        self.assertEqual('purge',retired['afterDrain'])
        purge = self.call('RunYield',['purge','detail',False,False])
        self.assertFalse(purge['cancelled'])

    def test_late_read_does_not_publish_after_leaving_home(self):
        self.assertIsNone(self.call('RunPublication',[SCOPE,False,False,'detail'])['published'])
        self.assertIsNone(self.call('RunPublication',[SCOPE,False,False,'home',True])['published'])

    def test_write_keeps_signed_urls_volatile_and_stops_before_metadata_after_owner_change(self):
        row = {**ROW, 'items':[{'itemId':str(i),'title':'Fixture','type':'movie','resumeMs':3000,
                               'art':{'poster':'https://images.test/'+str(i)+'?signed=private'}} for i in range(2)]}
        result = self.call('RunWrite',[[row],0])
        self.assertEqual(4,result['requests'])
        self.assertEqual(2,len(result['metadata']['row']['items']))
        self.assertNotIn('private',json.dumps(result['metadata']))
        self.assertNotIn('resumeMs',json.dumps(result['metadata']))
        changed = self.call('RunWrite',[[row],4])
        self.assertIsNone(changed['metadata'])

    def test_failed_manifest_delete_preserves_old_art_and_aborts_before_download(self):
        row = {**ROW,'items':[{'itemId':'new','title':'New','type':'movie','art':{'poster':'https://images.test/new'}}]}
        result = self.call('RunWrite',[[row],-1])
        self.assertEqual([],result['written'])
        self.assertEqual(0,result['requests'])
        self.assertFalse(any(path.endswith('.img') for path in result['deleted']))

    def test_download_polls_before_temp_file_exists_and_rejects_oversize(self):
        row = {**ROW,'items':[{'itemId':'new','title':'New','type':'movie','art':{'poster':'https://images.test/new'}}]}
        completed = self.call('RunWrite',[[row],-3])
        self.assertEqual('new',completed['metadata']['row']['items'][0]['itemId'])
        oversized = self.call('RunWrite',[[row],-4])
        self.assertEqual([],oversized['written'])
        self.assertIsNone(oversized['metadata'])

    def test_fresh_personal_first_rail_retires_previous_catalog_snapshot(self):
        result = self.call('RunWrite',[[{'rowId':'resume','sectionType':'continue_watching','items':[]}],-2])
        self.assertEqual([],result['written'])
        self.assertEqual(0,result['requests'])
        self.assertTrue(any(path.endswith('.json') for path in result['deleted']))
        self.assertTrue(any(path.endswith('.img') for path in result['deleted']))
