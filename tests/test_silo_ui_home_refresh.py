"""Home revalidation through shipping load/result handlers and rendered content."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class SiloUIHomeRefreshTests(unittest.TestCase):
    def scene(self, body):
        with tempfile.TemporaryDirectory() as directory:
            home = (ROOT / 'components/SiloUIHome.brs').read_text()
            for name, replacement in {
                'HeroShow': 'sub HeroShow(item as Object)\n m.heroItem=item\nend sub',
                'HomePaintDots': 'sub HomePaintDots()\nend sub',
                'HomeCacheStart': 'sub HomeCacheStart(action as String)\nend sub',
                'HomeSyncTimer': 'sub HomeSyncTimer()\nend sub',
            }.items():
                home = re.sub(r'sub ' + name + r'\(.*?\nend sub', replacement, home, count=1, flags=re.S)
            fixture = Path(directory) / 'home.brs'
            fixture.write_text(home)
            boundary = Path(directory) / 'boundary.brs'
            boundary.write_text('''
sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic)
 m.requests.Push({action:action,purpose:purpose,extra:extra})
end sub
sub ApiOwned(action as String, params as Object, purpose as String, extra as Dynamic, owner as Object)
 m.requests.Push({action:action,purpose:purpose,extra:extra,owner:owner})
end sub
function SessionRevision(provider as String) as Integer
 return 4
end function
sub PlayerDiscardPrebuffer()
end sub
sub BuildButtons(group as Object, name as String, labels as Object)
end sub
sub SetZone(zone as String)
 m.zone=zone
end sub
sub Toast(message as String)
 m.toast=message
end sub
function ItemNode(item as Object, landscape=false as Boolean) as Object
 node=CreateObject("roSGNode","ContentNode")
 node.addFields({item:item})
 return node
end function
sub StreamingRememberRows(rows as Object)
end sub
function StreamingHomeRows(rows as Object) as Object
 return rows
end function
''')
            output = run_brightscript([fixture, boundary, ROOT/'source/core/SiloUIHomePolicy.brs', ROOT/'source/core/SiloUIFormat.brs', ROOT/'components/SiloUIRobustness.brs', ROOT/'source/core/SiloUIHomeSectionsPolicy.brs'], '''
 m.provider="silo":m.sourceId="s":m.profileId="p":m.generation=1
 m.view="home":m.zone="rows":m.requests=[]:m.homeToken=0
 m.rows={rowItemFocused:[0,0]}:m.heroButtons={}:m.homeRetryButtons={visible:false}
 HomeSetRows([{rowId:"old",sectionType:"recent",title:"Old",items:[{itemId:"old",title:"Old",type:"movie"}]}])
''' + body, root=Path(directory))
            return json.loads(output.splitlines()[-1])

    def test_refresh_and_failure_keep_rendered_rows_hero_and_focus(self):
        actual = self.scene('''
 HomeLoad()
 during={rows:m.rows.content.getChildCount(),hero:m.heroItem.itemId,zone:m.zone}
 HomeResult("home_silo",{ok:false},{},m.requests[0].extra)
 print FormatJson({during:during,rows:m.rows.content.getChildCount(),hero:m.heroItem.itemId,retry:m.homeRetryButtons.visible,zone:m.zone})
''')
        self.assertEqual(actual, dict(during=dict(rows=1,hero='old',zone='rows'),rows=1,hero='old',retry=True,zone='rows'))

    def test_fresh_inline_rows_replace_snapshot_before_pending_sections(self):
        actual = self.scene('''
 HomeLoad()
 HomeResult("home_silo",{ok:true},{rows:[{rowId:"fresh",sectionType:"recent",title:"Fresh",items:[{itemId:"fresh",title:"Fresh",type:"movie"}]},{rowId:"pending",items:[],totalCount:1}]},m.requests[0].extra)
 print FormatJson({row:m.homeRows[0].rowId,hero:m.heroItem.itemId,request:m.requests[1].action})
''')
        self.assertEqual(actual, dict(row='fresh',hero='fresh',request='home_section_items'))

    def test_failed_section_refresh_keeps_snapshot_but_empty_success_replaces_it(self):
        actual = self.scene('''
 HomeLoad()
 HomeResult("home_silo",{ok:true},{rows:[{rowId:"pending",items:[],totalCount:1}]},m.requests[0].extra)
 HomeResult("home_silo_section",{ok:false},{},m.requests[1].extra)
 failed={rows:m.rows.content.getChildCount(),hero:m.heroItem.itemId,retry:m.homeRetryButtons.visible}
 HomeLoad()
 HomeResult("home_silo",{ok:true},{rows:[]},m.requests[2].extra)
 print FormatJson({failed:failed,rows:m.rows.content.getChildCount(),hero:m.heroItem.title,retry:m.homeRetryButtons.visible})
''')
        self.assertEqual(actual, dict(failed=dict(rows=1,hero='old',retry=True),rows=0,hero='Your library is empty',retry=False))

    def test_scope_changes_clear_snapshot_and_ignore_late_results(self):
        for field, value in [('provider','plex'), ('sourceId','other'), ('profileId','other'), ('generation',2)]:
            with self.subTest(field=field):
                actual = self.scene('''
 HomeLoad():old=m.requests[0].extra
 m.''' + field + '=' + json.dumps(value) + '''
 HomeLoad(true)
 HomeResult("home_silo",{ok:true},{rows:[{rowId:"late",items:[{itemId:"late"}]}]},old)
 print FormatJson({rows:m.rows.content.getChildCount(),hero:m.heroItem.title,retry:m.homeRetryButtons.visible})
''')
                self.assertEqual(actual, dict(rows=0,hero='Loading your library…',retry=False))

    def test_same_token_reply_is_fenced_when_scope_changes_before_reload(self):
        actual = self.scene('''
 HomeLoad():old=m.requests[0].extra
 m.profileId="other"
 HomeResult("home_silo",{ok:false},{},old)
 print FormatJson(m.homeRetryButtons.visible)
''')
        self.assertFalse(actual)

    def test_plex_failed_refresh_retains_snapshot_and_empty_success_replaces_it(self):
        actual = self.scene('''
 m.provider="plex":m.plexImageBase="https://synthetic.invalid"
 HomeSetRows([{rowId:"old",sectionType:"recent",title:"Old",items:[{itemId:"old",title:"Old",type:"movie"}]}])
 HomeLoad()
 for each request in m.requests
     HomeResult(request.purpose,{ok:false},{},request.extra)
 end for
 failed={rows:m.rows.content.getChildCount(),hero:m.heroItem.itemId,retry:m.homeRetryButtons.visible}
 m.requests=[]:HomeLoad()
 for each request in m.requests
     HomeResult(request.purpose,{ok:true},{items:[],sections:[]},request.extra)
 end for
 print FormatJson({failed:failed,rows:m.rows.content.getChildCount(),hero:m.heroItem.title,retry:m.homeRetryButtons.visible})
''')
        self.assertEqual(actual, dict(failed=dict(rows=1,hero='old',retry=True),rows=0,hero='Your library is empty',retry=False))

    def test_retry_returns_focus_to_visible_hero_while_rows_stay_usable(self):
        actual = self.scene('''
 HomeLoad()
 HomeResult("home_silo",{ok:false},{},m.requests[0].extra)
 m.zone="homeRetry"
 HomeLoad()
 print FormatJson({zone:m.zone,rows:m.rows.content.getChildCount(),retry:m.homeRetryButtons.visible})
''')
        self.assertEqual(actual, dict(zone='heroButtons',rows=1,retry=False))

    def test_local_progress_during_refresh_does_not_lose_snapshot_on_failure(self):
        actual = self.scene('''
 HomeLoad()
 HomeUpdateProgress({sourceId:"s",itemId:"old",resumeMs:50000,watched:false},HomeProgressScope())
 for each request in m.requests
     if request.purpose = "home_visibility" then HomeVisibilityResult({ok:true,sessionRevision:4},{items:[{id:"cw",section_type:"continue_watching",hidden:false}]},request.extra)
 end for
 HomeResult("home_silo",{ok:true},{rows:[{rowId:"pending",items:[],totalCount:1}]},m.requests[0].extra)
 for each request in m.requests
     if request.purpose = "home_silo_section" then HomeResult(request.purpose,{ok:false},{},request.extra)
 end for
 print FormatJson({rows:m.rows.content.getChildCount(),hero:m.heroItem.itemId,retry:m.homeRetryButtons.visible})
''')
        self.assertEqual(actual, dict(rows=2,hero='old',retry=True))

    def test_first_fresh_rows_preserve_surviving_row_and_column_focus(self):
        actual = self.scene('''
 HomeSetRows([{rowId:"old",sectionType:"recent",title:"Old",items:[{itemId:"a"},{itemId:"b"}]}])
 m.rows.rowItemFocused=[0,1]
 HomeLoad()
 HomeResult("home_silo",{ok:true},{rows:[{rowId:"new",items:[{itemId:"new"}]},{rowId:"old",items:[{itemId:"fresh-a"},{itemId:"fresh-b"}]}]},m.requests[0].extra)
 print FormatJson({focus:m.rows.jumpToRowItem,hero:m.heroItem.itemId})
''')
        self.assertEqual(actual, dict(focus=[1,1],hero='new'))
