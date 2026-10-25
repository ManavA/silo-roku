import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUIHomePolicy.brs'
class SiloUIHomePolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.exists(), 'Home policy missing')
        with tempfile.TemporaryDirectory() as root:
            return run_function([POLICY], name, list(args), root=Path(root))
    def test_rotation_requires_home_hero_focus_and_caps_at_six(self):
        self.assertEqual(self.call('SiloUIHomeNextHero','home','heroButtons',5,9),0)
        self.assertEqual(self.call('SiloUIHomeNextHero','home','rows',2,9),2)
        self.assertEqual(self.call('SiloUIHomeNextHero','detail','heroButtons',2,9),2)
        self.assertEqual(self.call('SiloUIHomeNextHero','home','heroButtons',0,0),0)
    def test_progress_updates_only_matching_source_and_preserves_other_rows(self):
        item = dict(itemId='a',sourceId='s',type='episode',resumeMs=4,watched=True)
        rows = [dict(sectionType='continue_watching',rowId='cw',title='Continue',items=[item,dict(item,sourceId='other')]),dict(sectionType='custom',items=[])]
        change = dict(item, resumeMs=50000,watched=False)
        actual=self.call('SiloUIHomeApplyProgress',rows,[change])
        self.assertEqual(actual[0]['items'][0]['resumems'],50000)
        self.assertFalse(actual[0]['items'][0]['watched'])
        self.assertEqual(actual[0]['items'][1]['resumeMs'],4)
        self.assertEqual(actual[1],rows[1])
        done=self.call('SiloUIHomeApplyProgress',rows,[dict(change,watched=True,resumeMs=0)])
        self.assertEqual(len(done[0]['items']),1)
    def test_missing_continue_row_is_created_and_unwatched_item_added(self):
        change=dict(itemId='a',sourceId='s',resumeMs=50000,watched=False)
        actual=self.call('SiloUIHomeApplyProgress',[],[change])
        self.assertEqual(actual[0]['sectionType'],'continue_watching')
        self.assertEqual(actual[0]['items'],[change])

    def test_scene_tick_pauses_outside_hero_and_rotates_first_row(self):
        from tools.brightscript import run_brightscript
        import re, json
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'components/SiloUIHome.brs').read_text()
            source=re.sub(r'sub HeroShow\(.*?\nend sub', 'sub HeroShow(item as Object)\n m.shown = item.itemId\nend sub', source,count=1,flags=re.S)
            source += '\nsub HomePaintDots()\nend sub\n' if 'sub HomePaintDots()' not in source else ''
            fixture=Path(root)/'home.brs';fixture.write_text(source)
            output=run_brightscript([POLICY,fixture], '''
                m.view="home":m.zone="rows":m.heroIndex=0
                m.homeRows=[{items:[]},{items:[{itemId:"a"},{itemId:"b"}]}]
                onHeroTick()
                paused=m.heroIndex
                m.zone="heroButtons"
                onHeroTick()
                print FormatJson({paused:paused,index:m.heroIndex,shown:m.shown})
            ''',root=Path(root))
        self.assertEqual(json.loads(output),dict(paused=0,index=1,shown='b'))

    def test_scene_timer_stops_on_rows_and_non_home_views(self):
        from tools.brightscript import run_brightscript
        import json
        with tempfile.TemporaryDirectory() as root:
            stub=Path(root)/'stub.brs'
            stub.write_text('sub PlayerSyncHeroPrebuffer()\nend sub\n')
            output=run_brightscript([ROOT/'components/SiloUIHome.brs',stub], '''
                m.heroTimer={control:"stop"}
                m.view="home":m.zone="heroButtons"
                HomeSyncTimer():active=m.heroTimer.control
                m.zone="rows":HomeSyncTimer():rows=m.heroTimer.control
                m.view="detail":m.zone="heroButtons":HomeSyncTimer()
                print FormatJson([active,rows,m.heroTimer.control])
            ''',root=Path(root))
        self.assertEqual(json.loads(output),['start','stop','stop'])

    def test_hero_uses_first_nonempty_section(self):
        self.assertEqual(self.call('SiloUIHomeHeroRow',[{'items':[]},{'items':[{'itemId':'a'}]}]),1)
        self.assertEqual(self.call('SiloUIHomeHeroRow',[{'items':[]}]),-1)

    def test_focus_follows_section_and_item_after_continue_insert(self):
        rows=[dict(rowId='cw',sectionType='continue_watching',items=[dict(sourceId='s',itemId='x')]),dict(rowId='recent',sectionType='recent',items=[dict(sourceId='s',itemId='b'),dict(sourceId='s',itemId='a')])]
        self.assertEqual(self.call('SiloUIHomeRestoreFocus',rows,dict(rowId='recent',sectionType='recent'),dict(sourceId='s',itemId='a'),[0,0]),[1,1])

    def test_recent_overlay_is_bounded_and_latest_wins(self):
        changes=[dict(sourceId='s',itemId=str(i),resumeMs=i,watched=False) for i in range(40)]
        latest=dict(sourceId='s',itemId='0',resumeMs=999,watched=True)
        result=self.call('SiloUIHomeRememberProgress',changes,latest)
        self.assertEqual(len(result),40)
        self.assertEqual(result[-1]['resumeMs'],999)
        result=self.call('SiloUIHomeRememberProgress',changes,dict(sourceId='s',itemId='new',resumeMs=1,watched=False))
        self.assertEqual(len(result),40)
        self.assertEqual(result[0]['itemId'],'1')

    def test_old_playback_cannot_add_progress_after_generation_change(self):
        from tools.brightscript import run_brightscript
        import json
        with tempfile.TemporaryDirectory() as root:
            output=run_brightscript([POLICY,ROOT/'components/SiloUIHome.brs',ROOT / 'source/core/SiloUIFormat.brs', ROOT / 'components/SiloUIScene.brs'], '''
                m.generation=2:m.provider="silo":m.sourceId="s":m.profileId="p"
                m.homeProgressScope="1:silo:s:p"
                m.homeProgress=[{sourceId:"s",itemId:"old"}]
                HomeUpdateProgress({sourceId:"s",itemId:"old",resumeMs:50},"1:silo:s:p")
                print FormatJson(m.homeProgress)
            ''',root=Path(root))
        self.assertEqual(json.loads(output),[])

    def test_focus_position_rejects_unset_malformed_and_out_of_bounds(self):
        for focus in (None, [], [-1,-1], [0], ['0',0], [0,'0'], [0,-1], [1,0], [0,2], [0.5,0], [True,0]):
            with self.subTest(focus=focus):
                self.assertIsNone(self.call('SiloUIHomeFocusPosition',focus,1,2))
        self.assertEqual(self.call('SiloUIHomeFocusPosition',[0,1],1,2),[0,1])

    def test_player_return_without_home_focus_updates_progress_without_indexing(self):
        from tools.brightscript import run_brightscript
        import re, json
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'components/SiloUIHome.brs').read_text()
            for name in ('HomeSetRows','HomePaintDots'):
                source=re.sub(r'sub '+name+r'\(.*?\nend sub', 'sub '+name+'(rows = invalid as Dynamic)\nend sub',source,count=1,flags=re.S)
            fixture=Path(root)/'home.brs';fixture.write_text(source)
            output=run_brightscript([POLICY,fixture,ROOT/'source/core/SiloUIFormat.brs'], '''
                m.generation=1:m.provider="silo":m.sourceId="s":m.profileId="p"
                m.homeRows=[]:m.heroIndex=0:m.heroItem=invalid
                m.rows={rowItemFocused:[],content:invalid}
                HomeUpdateProgress({sourceId:"s",itemId:"episode",resumeMs:50},"1:silo:s:p")
                first=HomeFocusedItem()
                m.rows.rowItemFocused=[-1,-1]
                HomeUpdateProgress({sourceId:"s",itemId:"episode",resumeMs:60},"1:silo:s:p")
                print FormatJson({progress:m.homeProgress[0].resumeMs,first:first,second:HomeFocusedItem()})
            ''',root=Path(root))
        self.assertEqual(json.loads(output),dict(progress=60,first=None,second=None))

    def test_focused_item_checks_native_content_bounds_before_get_child(self):
        from tools.brightscript import run_brightscript
        import json
        with tempfile.TemporaryDirectory() as root:
            output=run_brightscript([POLICY,ROOT/'components/SiloUIHome.brs'], '''
                m.rows={content:{getChildCount:function()
                    return 1
                end function, getChild:function(index)
                    if index <> 0 then stop
                    return {getChildCount:function()
                        return 1
                    end function, getChild:function(index)
                        if index <> 0 then stop
                        return {item:{itemId:"valid"}}
                    end function}
                end function}}
                results=[]
                for each focus in [[],[-1,-1],[0,-1],[1,0],[0,1],["0",0],[0,"0"],[0,0]]
                    m.rows.rowItemFocused=focus
                    results.Push(HomeFocusedItem())
                end for
                print FormatJson(results)
            ''',root=Path(root))
        self.assertEqual(json.loads(output),[None]*7+[dict(itemId='valid')])
