import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT/'source/core/SiloUIHomeSectionsPolicy.brs'

class HomeSectionsTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory() as root:
            return run_function([POLICY], name, list(args), root=Path(root))

    def test_hide_preserves_entire_saved_set_and_exact_config_values(self):
        saved = [{'id':'other','section_id':'absent','position':None,'featured':False,'config':{'unknown':[None,False,0,{},[]]},'created_at':None}, {'id':'custom','section_id':'','is_user_added':True,'user_config':{},'user_title':''}]
        rows = [{'id':'a','is_custom':False,'hidden':False}]
        actual = self.call('HomeSectionsEdit', saved, rows, {'kind':'hidden','id':'a','value':True})
        self.assertTrue(actual['ok'])
        self.assertEqual(actual['overrides'], [{k:v for k,v in saved[0].items() if k != 'created_at'}, saved[1], {'section_id':'a','hidden':True}])

    def test_unknown_override_fields_refuse_write_but_nested_fields_survive(self):
        self.assertFalse(self.call('HomeSectionsEdit', [{'section_id':'a','future':1}], [{'id':'a'}], {'kind':'hidden','id':'a','value':False})['ok'])
        result = self.call('HomeSectionsEdit', [{'section_id':'a','config':{},'user_config':None,'featured':None,'position':0}], [{'id':'a'}], {'kind':'hidden','id':'a','value':False})
        self.assertEqual(result['overrides'], [{'section_id':'a','config':{},'user_config':None,'featured':None,'position':0,'hidden':False}])

    def test_move_includes_hidden_and_custom_rows_and_refuses_boundaries(self):
        rows = [{'id':'a'}, {'id':'custom','is_custom':True,'hidden':True}, {'id':'b'}]
        saved = [{'id':'custom','section_id':'','user_config':{'deep':{'future':False}}}, {'section_id':'gone','removed':True}]
        result = self.call('HomeSectionsEdit', saved, rows, {'kind':'move','id':'a','direction':1})
        self.assertTrue(result['ok'])
        self.assertEqual(result['overrides'], [dict(saved[0],position=0),saved[1],{'section_id':'a','position':1},{'section_id':'b','position':2}])
        for intent in [{'kind':'move','id':'a','direction':-1},{'kind':'move','id':'b','direction':1},{'kind':'hidden','id':'missing','value':True}]:
            self.assertFalse(self.call('HomeSectionsEdit', saved, rows, intent)['ok'])

    def test_adapter_fixed_home_scope_and_strict_empty_mutation_receipt(self):
        adapter = ROOT/'source/adapters/SiloAdapter.brs'
        SOURCES = adapter
        with tempfile.TemporaryDirectory() as root:
            session = {'baseUrl':'https://example.test','accessToken':'t','profileId':'p'}
            for action, method in [('home_sections_list','GET'),('home_sections_settings','GET'),('home_sections_save','PUT'),('home_sections_reset','DELETE')]:
                params = {'overrides':[]} if action.endswith('save') else {}
                request = run_function(SOURCES, 'BuildSiloRequest', [action,session,params], root=Path(root))
                self.assertTrue(request['ok'])
                self.assertEqual(request['method'],method)
                self.assertTrue(request['url'].endswith(('/profile/sections/settings' if action.endswith('settings') else '/profile/sections')+'?scope=home'))
                bad = run_function(SOURCES, 'BuildSiloRequest', [action,session,dict(params,scope='library')], root=Path(root))
                self.assertFalse(bad['ok'])
            for status, body, expected in [(204,'',True),(200,'',False),(204,'{}',False),(202,'',False)]:
                result=run_function(SOURCES,'DecodeSiloResponse',['home_sections_save',body,{'statusCode':status}],root=Path(root))
                self.assertEqual(result['ok'],expected)

    def component(self, body):
        from tools.brightscript import run_brightscript
        import json
        with tempfile.TemporaryDirectory() as root:
            helpers=Path(root)/'helpers.brs'
            helpers.write_text('''
function SessionRevision(provider as String) as Integer
 return 4
end function
function NumberOr(value as Dynamic, fallback as Dynamic) as Dynamic
 if value = invalid then return fallback
 return value
end function
function TextOr(value as Dynamic) as String
 if value = invalid then return ""
 return value
end function
function HomeProgressScope() as String
 return "1:silo:s:"+m.profile
end function
function SiloUIOwner() as Object
 return {provider:"silo",sourceId:"s",profileId:m.profile,generation:1}
end function
function BrowseCaptureContext() as Object
 return {owner:SiloUIOwner()}
end function
function BrowseContextCurrent(context as Object) as Boolean
 return context.owner.profileId=m.profile
end function
sub ApiOwned(action as String, params as Object, purpose as String, extra as Object, owner as Object)
 m.calls.Push({action:action,params:params,extra:extra,owner:owner})
end sub
sub Toast(message as String)
 m.messages.Push(message)
end sub
sub BrowsePagedChoices(title as String, choices as Object, handler as String, start=0 as Integer)
 m.labels=choices:m.browseDialogTicket={}
end sub
sub BrowseDialog(title as String, labels as Object, handler as String)
 m.browseDialog={buttonSelected:0}:m.browseDialogTicket={}
end sub
function BrowseTakeDialog(event as Object, handler as String) as Object
 return m.browseDialogTicket
end function
function BrowseChoiceIndex(event as Object) as Integer
 return event.index
end function
sub HomeSectionsChanged()
 m.changed=true
end sub
''')
            # The refresh helper is tested separately against the shipping Home module.
            import re
            source=(ROOT/'components/SiloUIHomeSections.brs').read_text()
            source=re.sub(r'sub HomeSectionsChanged\(\).*?\nend sub','',source,flags=re.S)
            component=Path(root)/'component.brs';component.write_text(source)
            output=run_brightscript([POLICY,component,helpers], 'm.provider="silo":m.profile="p":m.calls=[]:m.messages=[]:m.changed=false\n'+body,root=Path(root))
            return json.loads(output)

    def test_editor_serializes_fresh_reads_and_waits_for_receipt(self):
        actual=self.component('''
            HomeSectionsOpen()
            first=m.calls[0].extra
            HomeSectionsResult("home_sections_read",{ok:true,sessionRevision:4},{items:[{section_id:"other",config:{nested:0}}]},first)
            HomeSectionsResult("home_sections_rows",{ok:true,sessionRevision:4},{items:[{id:"a",title:"A",hidden:false}]},first)
            HomeSectionsBegin({kind:"hidden",id:"a",value:true})
            HomeSectionsBegin({kind:"hidden",id:"a",value:true})
            fresh=m.calls[2].extra
            HomeSectionsResult("home_sections_read",{ok:true,sessionRevision:4},{items:[{section_id:"new",config:{latest:false}}]},fresh)
            HomeSectionsResult("home_sections_rows",{ok:true,sessionRevision:4},{items:[{id:"a",title:"A",hidden:false}]},fresh)
            before=m.changed
            write=m.calls[4]
            HomeSectionsResult("home_sections_write",{ok:true,sessionRevision:4},{acknowledged:true},fresh)
            print FormatJson({actions:[m.calls[0].action,m.calls[1].action,m.calls[2].action,m.calls[3].action,write.action],body:write.params,before:before,changed:m.changed})
        ''')
        self.assertEqual(actual, {'actions':['home_sections_list','home_sections_settings','home_sections_list','home_sections_settings','home_sections_save'],'body':{'overrides':[{'section_id':'new','config':{'latest':False}},{'section_id':'a','hidden':True}]},'before':False,'changed':True})

    def test_stale_profile_serial_session_and_ambiguous_receipt_never_apply(self):
        actual=self.component('''
            HomeSectionsOpen():old={serial:0}
            current=m.calls[0].extra
            HomeSectionsResult("home_sections_read",{ok:true,sessionRevision:4},{items:[]},old)
            staleCount=m.calls.Count()
            HomeSectionsResult("home_sections_read",{ok:true,sessionRevision:4},{items:[]},current)
            HomeSectionsResult("home_sections_rows",{ok:true,sessionRevision:5},{items:[{id:"a"}]},current)
            sessionCount=m.calls.Count()
            m.profile="different"
            HomeSectionsResult("home_sections_write",{ok:true,sessionRevision:4},{acknowledged:true},current)
            print FormatJson({stale:staleCount,session:sessionCount,changed:m.changed})
        ''')
        self.assertEqual(actual,dict(stale=1,session=2,changed=False))

    def test_ambiguous_write_rereads_without_replay_and_all_hidden_menu_recovers(self):
        actual=self.component('''
            HomeSectionsOpen():extra=m.calls[0].extra
            HomeSectionsResult("home_sections_read",{ok:true,sessionRevision:4},{items:[]},extra)
            HomeSectionsResult("home_sections_rows",{ok:true,sessionRevision:4},{items:[{id:"a",title:"A",hidden:true}]},extra)
            labels=m.labels
            HomeSectionsBegin({kind:"hidden",id:"a",value:false}):fresh=m.calls[2].extra
            HomeSectionsResult("home_sections_read",{ok:true,sessionRevision:4},{items:[]},fresh)
            HomeSectionsResult("home_sections_rows",{ok:true,sessionRevision:4},{items:[{id:"a",title:"A",hidden:true}]},fresh)
            HomeSectionsResult("home_sections_write",{ok:false,sessionRevision:4},{},fresh)
            HomeSectionsResult("home_sections_write",{ok:true,sessionRevision:4},{acknowledged:true},fresh)
            print FormatJson({labels:labels,count:m.calls.Count(),last:m.calls[5].action,changed:m.changed,intent:m.homeSections.intent})
        ''')
        self.assertEqual(actual,dict(labels=['A (hidden)','Reset Home layout','Cancel'],count=6,last='home_sections_list',changed=False,intent=None))

    def test_worker_never_replays_mutation_and_rejects_session_changed_during_reply(self):
        from tools.brightscript import run_brightscript
        import json
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            worker=root/'worker.brs'
            worker.write_text((ROOT/'components/ApiTask.brs').read_text().replace('function TaskDeviceSession(', 'function UnusedTaskDeviceSession(',1))
            native=root/'native.brs'
            native.write_text('''
function SessionRevision(provider as String) as Integer
 return m.revision
end function
function LoadSession(provider as String) as Object
 return {baseUrl:"https://fixture.example",sourceId:"s",profileId:"p",accessToken:"synthetic",refreshToken:"synthetic"}
end function
function TaskDeviceSession(provider as String,session as Object) as Object
 return session
end function
function HttpRequest(request as Object,timeoutMs=0 as Integer) as Object
 m.calls.Push(request.method)
 if m.change=true then m.revision=5
 return m.reply
end function
''')
            http=root/'http.brs'
            http.write_text((ROOT/'source/network/Http.brs').read_text().replace('function HttpRequest(', 'function UnusedHttpRequest(',1))
            actual=run_brightscript([ROOT/'source/auth/SessionPolicy.brs',ROOT/'source/adapters/SiloAdapter.brs',worker,native,http],'''
                m.calls=[]:m.revision=4:m.change=false
                owner={sourceId:"s",profileId:"p",sessionRevision:4}
                m.reply={ok:false,statusCode:401,body:"",errorCode:"auth_required"}
                failed=ExecuteApiAction("silo","home_sections_save",{overrides:[]},owner)
                m.reply={ok:true,statusCode:204,body:""}:m.change=true
                stale=ExecuteApiAction("silo","home_sections_reset",{},owner)
                print FormatJson({calls:m.calls,failed:failed.ok,stale:stale.ok})
            ''',root=root)
        self.assertEqual(json.loads(actual),dict(calls=['PUT','DELETE'],failed=False,stale=False))

    def test_server_layout_does_not_recreate_hidden_continue_row_from_local_progress(self):
        with tempfile.TemporaryDirectory() as root:
            result=run_function(ROOT/'source/core/SiloUIHomePolicy.brs','SiloUIHomeApplyProgress',[[],[{'itemId':'a','sourceId':'s','resumeMs':10,'watched':False}],False],root=Path(root))
        self.assertEqual(result,[])

    def test_reset_requires_current_confirmation_then_reads_before_scoped_delete(self):
        actual=self.component('''
            HomeSectionsOpen():extra=m.calls[0].extra
            HomeSectionsResult("home_sections_read",{ok:true,sessionRevision:4},{items:[]},extra)
            HomeSectionsResult("home_sections_rows",{ok:true,sessionRevision:4},{items:[]},extra)
            onHomeSectionsMenu({index:0})
            m.browseDialog.buttonSelected=1
            onHomeSectionsReset({})
            cancelled=m.calls.Count()
            onHomeSectionsMenu({index:0})
            m.browseDialogTicket.homeSerial=0
            onHomeSectionsReset({})
            stale=m.calls.Count()
            onHomeSectionsMenu({index:0})
            m.browseDialogTicket.homeSerial=m.homeSections.serial
            m.browseDialog.buttonSelected=0
            onHomeSectionsReset({})
            fresh=m.calls[2].extra
            HomeSectionsResult("home_sections_read",{ok:true,sessionRevision:4},{items:[{future:1}]},fresh)
            HomeSectionsResult("home_sections_rows",{ok:true,sessionRevision:4},{items:[]},fresh)
            print FormatJson({cancelled:cancelled,stale:stale,action:m.calls[4].action,params:m.calls[4].params,changed:m.changed})
        ''')
        self.assertEqual(actual,dict(cancelled=2,stale=2,action='home_sections_reset',params={},changed=False))

    def test_continue_synthesis_requires_positive_visible_server_row(self):
        rows=[{'id':'cw','section_type':'continue_watching','hidden':False},{'id':'cw2','section_type':'continue_watching','hidden':True}]
        self.assertFalse(self.call('HomeSectionsContinueHidden',rows,None))
        self.assertTrue(self.call('HomeSectionsContinueHidden',rows,{'kind':'hidden','id':'cw','value':True}))
        self.assertFalse(self.call('HomeSectionsContinueHidden',[dict(rows[0],hidden=True)],{'kind':'hidden','id':'cw','value':False}))
        self.assertTrue(self.call('HomeSectionsContinueHidden',[dict(rows[0],hidden=True)],{'kind':'reset'}))
        self.assertTrue(self.call('HomeSectionsContinueHidden',[],None))
        self.assertTrue(self.call('HomeSectionsContinueHidden',[{'id':'other','section_type':'recently_added','hidden':False}],None))
        self.assertTrue(self.call('HomeSectionsContinueHidden',[dict(rows[0],removed=True)],None))
        self.assertTrue(self.call('HomeSectionsContinueHidden',[{'id':'cw','section_type':'continue_watching'}],None))
        with tempfile.TemporaryDirectory() as root:
            result=run_function(ROOT/'source/core/SiloUIHomePolicy.brs','SiloUIHomeApplyProgress',[[],[{'itemId':'a','sourceId':'s','resumeMs':10,'watched':False}]],root=Path(root))
        self.assertEqual(result[0]['rowId'],'local_continue')

    def test_lazy_visibility_checks_once_per_home_response_and_keeps_existing_updates_immediate(self):
        from tools.brightscript import run_brightscript
        import json,re
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            home=root/'home.brs'
            source=(ROOT/'components/SiloUIHome.brs').read_text()
            source=re.sub(r'sub HomeHydrationRender\(.*?\nend sub','sub HomeHydrationRender(rows as Object, refreshComplete = true as Boolean)\n m.renders++\nend sub',source,count=1,flags=re.S)
            home.write_text(source)
            helper=root/'helper.brs';helper.write_text('''
function SessionRevision(provider as String) as Integer
 return 4
end function
function HomeProgressScope() as String
 return m.scope
end function
function SiloUIOwner() as Object
 return {provider:"silo",sourceId:"s",profileId:"p",generation:1}
end function
sub ApiOwned(action as String, params as Object, purpose as String, extra as Object, owner as Object)
 m.calls.Push(extra)
end sub
sub Toast(message as String)
 m.messages.Push(message)
end sub
'''.replace('function HomeProgressScope()', 'function FixtureHomeProgressScope()'))
            # Keep the shipping scope implementation, supplying its normal Scene fields.
            result=run_brightscript([ROOT/'source/core/SiloUIHomePolicy.brs',ROOT/'source/core/SiloUIFormat.brs',POLICY,home,helper],'''
                m.provider="silo":m.sourceId="s":m.profileId="p":m.generation=1:m.homeToken=1:m.view="home"
                m.homeProgress=[]
                m.calls=[]:m.messages=[]:m.renders=0:m.homeRows=[]
                HomeVisibilityCheck([])
                startup=m.calls.Count()
                m.homeProgress=[{itemId:"a",sourceId:"s",resumeMs:10,watched:false}]
                HomeVisibilityCheck([{sectionType:"continue_watching",items:[]}])
                existing=m.calls.Count()
                HomeVisibilityCheck([]):HomeVisibilityCheck([])
                first=m.calls[0]
                HomeVisibilityResult({ok:true,sessionRevision:4},{items:[{id:"cw",section_type:"continue_watching",hidden:false}]},first)
                visible=m.homeContinueHidden
                HomeVisibilityCheck([])
                checked=m.calls.Count()
                m.homeToken=2
                HomeVisibilityCheck([])
                second=m.calls[1]
                HomeVisibilityResult({ok:true,sessionRevision:4},{items:[{id:"cw",section_type:"continue_watching",hidden:true}]},first)
                stale=m.homeContinueLayoutToken
                HomeVisibilityResult({ok:true,sessionRevision:4},{items:[{id:"cw",section_type:"continue_watching",hidden:true}]},second)
                hidden=m.homeContinueHidden
                m.homeToken=3
                HomeVisibilityCheck([])
                third=m.calls[2]
                HomeVisibilityResult({ok:true,sessionRevision:5},{items:[]},third)
                staleSession=m.homeContinueLayoutToken
                HomeVisibilityResult({ok:false,sessionRevision:4},{},third)
                HomeVisibilityCheck([])
                m.homeToken=4
                HomeVisibilityCheck([])
                fourth=m.calls[3]
                m.profileId="other"
                HomeVisibilityResult({ok:true,sessionRevision:4},{items:[]},fourth)
                staleProfile=m.homeContinueLayoutToken
                print FormatJson({startup:startup,existing:existing,visible:visible,checked:checked,count:m.calls.Count(),stale:stale,staleSession:staleSession,staleProfile:staleProfile,hidden:hidden,failed:m.homeContinueHidden,renders:m.renders,messages:m.messages.Count()})
            ''',root=root)
        self.assertEqual(json.loads(result),dict(startup=0,existing=0,visible=False,checked=1,count=4,stale=1,staleSession=2,staleProfile=3,hidden=True,failed=True,renders=3,messages=1))
