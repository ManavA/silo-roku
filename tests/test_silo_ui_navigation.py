"""App-wide native navigation preference policy."""
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
class SiloUINavigationTests(unittest.TestCase):
    def call(self,name,*args):
        with tempfile.TemporaryDirectory() as root:
            return run_function([ROOT/'source/core/SiloUINavigationPolicy.brs'],name,list(args),root=Path(root))
    def test_top_menu_renders_all_destinations_and_selects_settings(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.navPills=m.top.findNode("navPills"):m.navPills.translation=[0,0]
            m.navPills.createChild=function(kind)
                child=NativeNode()
                child.getParent=function()
                    return {isSameNode:function(other)
                        return true
                    end function}
                end function
                m.children.Push(child)
                return child
            end function
            m.nav=m.top.findNode("nav"):m.manualFocus=m.top.findNode("manualFocus")
            m.speculationDisabled=true:m.history=[]
            LibrariesNavigation()
            labels=[]
            for each pill in m.pillGroups.nav.pills
                labels.Push(pill.label.text)
            end for
            if labels.Count() = 8 then NavSelect(labels.Count()-1)
            print FormatJson({labels:labels,view:m.view,page:m.obPage})
        ''')
        self.assertEqual(actual['labels'],['Home','Search','Movies','Shows','Libraries','Audiobooks','Books','Settings'])
        self.assertEqual((actual['view'],actual['page']),('onboarding','settings'))

    def test_top_avatar_opens_secondary_destinations_and_back_returns_home(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.navigationMode="top":m.view="home":m.zone="avatar"
            m.sourceId="source":m.obMode="":m.heroItem=invalid
            m.backdropTimer=m.top.findNode("backdropTimer")
            m.backdrop=m.top.findNode("backdrop"):m.backdropOld=m.top.findNode("backdropOld")
            m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
            m.speculationDisabled=true:m.history=[]
            onKeyEvent("OK",true)
            choices=m.obChoices
            onKeyEvent("OK",false)
            OnboardingKey("back")
            print FormatJson({choices:choices,view:m.view,zone:m.zone})
        ''')
        self.assertEqual([c['label'] for c in actual['choices']],
                         ['Switch profile','Audiobooks','Books','Settings','Back'])
        self.assertEqual((actual['view'],actual['zone']),('home','nav'))

    def test_top_default_and_explicit_left_overlay(self):
        for value in [None,'','bad','oled',{},1]:
            self.assertEqual(self.call('SiloUINavigationMode',value),'top')
        self.assertEqual(self.call('SiloUINavigationMode','left'),'left')
    def test_settings_persists_navigation_independently_and_launch_restores(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            ObChoose({action:"navigation"})
            choices=m.obChoices
            ObChoose({action:"navigation_select",value:"left"})
            m.navigationMode=invalid
            SiloUINavigationInit()
            print FormatJson({choices:choices,mode:m.navigationMode,appearance:m.nativeRegistry.Read("appearance"),preferences:m.preferences})
        ''')
        self.assertEqual([x.get('value') for x in actual['choices'][:-1]],['top','left'])
        self.assertEqual(actual['mode'],'left')
        self.assertEqual(actual['appearance'],'')
        self.assertEqual(actual['preferences'],dict(quality='720p',subtitles='forced'))
    def test_switching_from_drawer_settings_to_top_restores_primary_focus(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.pillGroups.nav={index:6,pills:[{},{},{},{}]}
            SiloUINavigationSave("top")
            print FormatJson({mode:m.navigationMode,index:m.pillGroups.nav.index})
        ''')
        self.assertEqual(actual,dict(mode='top',index=0))

    def test_menu_opens_vertical_drawer_and_back_restores_content_then_opens_again(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.manualFocus=m.top.findNode("manualFocus")
            m.nav=m.top.findNode("nav")
            m.navItems=["Home","Search","Movies","Shows","Settings"]
            m.pillGroups.nav={index:0,pills:[]}
            m.heroButtons=m.top.findNode("heroButtons")
            m.pillGroups.heroButtons={index:0,pills:[]}
            m.speculationDisabled=true:m.history=[]
            SiloUINavigationInit()
            SiloUINavigationBuild()
            m.navigationMode="left":m.view="home":m.zone="heroButtons"
            SetZone("nav")
            onKeyEvent("left",true)
            onKeyEvent("down",true)
            opened={open:m.drawerOpen,zone:m.zone,index:m.drawerIndex}
            onKeyEvent("back",true)
            closed={open:m.drawerOpen,zone:m.zone}
            onKeyEvent("back",true)
            reopened=m.drawerOpen
            dismissalHandled=onKeyEvent("back",true)
            print FormatJson({opened:opened,closed:closed,reopened:reopened,dismissalHandled:dismissalHandled})
        ''')
        self.assertEqual(actual['opened'],dict(open=True,zone='drawer',index=1))
        self.assertEqual(actual['closed'],dict(open=False,zone='heroButtons'))
        self.assertTrue(actual['reopened'])
        self.assertTrue(actual['dismissalHandled'])
    def test_destination_selection_closes_drawer_and_focuses_existing_search(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
            m.backdrop=m.top.findNode("backdrop"):m.backdropOld=m.top.findNode("backdropOld")
            m.navItems=["Home","Search","Movies","Shows","Settings"]
            m.pillGroups.nav={index:0,pills:[]}:m.keyboard=m.top.findNode("keyboard")
            m.speculationDisabled=true:m.history=[]
            SiloUINavigationInit():SiloUINavigationBuild()
            m.navigationMode="left":m.view="home":m.zone="heroButtons"
            SetZone("nav"):onKeyEvent("left",true):onKeyEvent("down",true):onKeyEvent("OK",true)
            print FormatJson({view:m.view,zone:m.zone,open:m.drawerOpen,visible:m.top.nodes.navDrawer.visible,focused:m.keyboard.focused})
        ''')
        self.assertEqual(actual,dict(view='search',zone='keyboard',open=False,visible=False,focused=True))
    def test_view_change_clears_open_drawer_and_its_focus_target(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
            m.backdrop=m.top.findNode("backdrop"):m.backdropOld=m.top.findNode("backdropOld")
            m.speculationDisabled=true:m.navigationMode="left":m.drawerOpen=true:m.zone="drawer"
            m.navigationReturn={view:"home",zone:"rows"}:m.view="home"
            ShowView("onboarding")
            print FormatJson({open:m.drawerOpen,zone:m.zone,target:m.navigationReturn,visible:m.nav.visible})
        ''')
        self.assertEqual(actual,dict(open=False,zone='nav',target=None,visible=False))
    def test_settings_resume_then_drawer_dismiss_never_focuses_hidden_onboarding(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
            m.backdrop=m.top.findNode("backdrop"):m.backdropOld=m.top.findNode("backdropOld")
            m.navItems=["Home","Search","Movies","Shows","Settings"]
            m.pillGroups.nav={index:0,pills:[]}
            m.speculationDisabled=true:m.history=[]
            SiloUINavigationInit():SiloUINavigationBuild():m.navigationMode="left"
            OnboardingSettings()
            ObChoose({action:"resume"})
            onKeyEvent("left",true):onKeyEvent("right",true)
            print FormatJson({zone:m.zone,open:m.drawerOpen,manual:m.manualFocus.focused})
        ''')
        self.assertEqual(actual,dict(zone='nav',open=False,manual=True))
    def test_pop_view_to_navigation_then_dismiss_keeps_valid_home_navigation(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
            m.backdrop=m.top.findNode("backdrop"):m.backdropOld=m.top.findNode("backdropOld")
            m.navItems=["Home","Search","Movies","Shows","Settings"]:m.pillGroups.nav={index:0,pills:[]}
            m.speculationDisabled=true:m.history=[{view:"home",zone:"nav"}]
            SiloUINavigationInit():SiloUINavigationBuild():m.navigationMode="left"
            m.view="search":m.zone="keyboard"
            PopView():onKeyEvent("left",true):onKeyEvent("back",true)
            print FormatJson({view:m.view,zone:m.zone,open:m.drawerOpen})
        ''')
        self.assertEqual(actual,dict(view='home',zone='nav',open=False))
    def test_empty_native_content_and_changed_owner_cannot_receive_restored_focus(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        for change in ['', 'm.rows.content=invalid','m.rows.content=NativeNode()','m.rows.content.children[0].children=[]','m.generation=2','m.profileId="other"','m.sourceId="other"','m.provider="plex"']:
            with self.subTest(change=change):
                actual=SiloUIAppearanceTests().native_flow('''
                    m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
                    m.rows=m.top.findNode("rows"):m.rows.content=NativeNode()
                    m.rows.content.children=[NativeNode()]:m.rows.content.children[0].children=[NativeNode()]
                    m.navItems=["Home","Search","Movies","Shows","Settings"]:m.pillGroups.nav={index:0,pills:[]}
                    m.speculationDisabled=true:m.history=[]:m.generation=1
                    SiloUINavigationInit():SiloUINavigationBuild():m.navigationMode="left"
                    m.view="home":m.zone="rows":SetZone("nav"):onKeyEvent("left",true)
                '''+change+'''
                    onKeyEvent("right",true)
                    print FormatJson({zone:m.zone,open:m.drawerOpen})
                ''')
                self.assertEqual(actual,dict(zone='rows' if change == '' else 'nav',open=False))
    def test_opening_settings_gesture_cannot_select_back_home_after_key_release(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
            m.backdrop=m.top.findNode("backdrop"):m.backdropOld=m.top.findNode("backdropOld")
            m.navItems=["Home","Search","Movies","Shows","Settings"]:m.pillGroups.nav={index:4,pills:[]}
            m.backdropTimer=m.top.findNode("backdropTimer")
            m.speculationDisabled=true:m.history=[]:m.view="home":m.zone="nav"
            onKeyEvent("OK",true):onKeyEvent("OK",false)
            m.obButtons.itemSelected=0:onObSelected()
            opening=m.view
            nativeBefore=m.obButtons.focused=true
            onObEntryTimer()
            nativeAfter=m.obButtons.focused=true
            m.obButtons.itemSelected=0:onObSelected()
            print FormatJson({opening:opening,nextSelection:m.view,nativeBefore:nativeBefore,nativeAfter:nativeAfter})
        ''')
        self.assertEqual(actual,dict(opening='onboarding',nextSelection='home',nativeBefore=False,nativeAfter=True))
    def edge_flow(self, setup, key, extra_fields=""):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        return SiloUIAppearanceTests().native_flow('''
            m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
            m.navItems=["Home","Search","Movies","Shows","Settings"]:m.pillGroups.nav={index:0,pills:[]}
            m.speculationDisabled=true:m.history=[]
            SiloUINavigationInit():SiloUINavigationBuild():m.navigationMode="left"
        '''+setup+f'''
            handled=onKeyEvent("{key}",true)
            opened=m.drawerOpen=true
            if opened then onKeyEvent("right",true)
            print FormatJson({{opened:opened,zone:m.zone,handled:handled{extra_fields}}})
        ''')
    def test_left_at_first_manual_action_opens_and_restores_that_action(self):
        for view,zone in [('home','heroButtons'),('detail','detailButtons'),('detail','seasons'),('library','libraryTabs')]:
            with self.subTest(zone=zone):
                actual=self.edge_flow(f'm.view="{view}":m.zone="{zone}":m.pillGroups.{zone}={{index:0,pills:[]}}:m.detailSeasons=[{{}}]', 'left')
                self.assertEqual(actual,dict(opened=True,zone=zone,handled=True))
    def test_collapsed_profile_back_opens_drawer_and_dismiss_keeps_collapsed_focus(self):
        actual=self.edge_flow('m.view="home":m.zone="nav"', 'back')
        self.assertEqual(actual,dict(opened=True,zone='nav',handled=True))
    def test_back_at_each_manual_left_edge_opens_drawer(self):
        for view,zone in [('home','heroButtons'),('detail','detailButtons'),('detail','seasons'),('library','libraryTabs')]:
            with self.subTest(zone=zone):
                actual=self.edge_flow(f'm.view="{view}":m.zone="{zone}":m.pillGroups.{zone}={{index:0,pills:[]}}:m.detailSeasons=[{{}}]', 'back')
                self.assertEqual(actual,dict(opened=True,zone=zone,handled=True))
    def test_left_from_profile_icon_opens_drawer(self):
        self.assertEqual(self.edge_flow('m.view="home":m.zone="nav"','left'),dict(opened=True,zone='nav',handled=True))
    def test_home_first_card_back_opens_without_resetting_lower_row(self):
        actual=self.edge_flow('''
            m.view="home":m.zone="rows":m.rows=m.top.findNode("rows")
            m.rows.content=NativeNode():row=NativeNode():row.children=[NativeNode()]:m.rows.content.children=[row]
            m.rows.rowItemFocused=[3,0]
        ''','back', ',focusedRow:m.rows.rowItemFocused,jump:m.rows.jumpToRowItem')
        self.assertEqual(actual,dict(opened=True,zone='rows',handled=True,focusedRow=[3,0],jump=None))
    def test_left_on_wrapping_rows_and_keyboard_is_not_intercepted(self):
        for view,zone in [('home','rows'),('detail','episodes'),('detail','detailCast'),('detail','detailSimilar'),('search','keyboard')]:
            with self.subTest(zone=zone):
                self.assertEqual(self.edge_flow(f'm.view="{view}":m.zone="{zone}"','left'),dict(opened=False,zone=zone,handled=False))
    def test_search_result_left_still_returns_to_keyboard(self):
        actual=self.edge_flow('m.view="search":m.zone="searchGrid":m.keyboard=m.top.findNode("keyboard")','left')
        self.assertEqual(actual,dict(opened=False,zone='keyboard',handled=True))
    def test_library_grid_only_uses_first_column_when_left_bubbles(self):
        for index in [0,7,8]:
            with self.subTest(index=index):
                actual=self.edge_flow(f'''
                    m.view="library":m.zone="grid":m.grid=m.top.findNode("grid")
                    m.grid.numColumns=7:m.grid.itemFocused={index}
                    m.grid.content=NativeNode():m.grid.content.children=[NativeNode()]
                ''','left')
                self.assertEqual(actual,dict(opened=index in [0,7],zone='grid',handled=index in [0,7]))
    def test_sidebar_is_translucent_with_the_lightest_panel_in_glass(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            SiloUINavigationInit():SiloUINavigationBuild():m.navigationMode="left"
            colors=[]
            for each mode in ["glass","oled","silo_blue","light_blue"]
                SiloUIApplyAppearance(mode)
                colors.Push(m.top.findNode("navDrawerBackground").color)
            end for
            print FormatJson(colors)
        ''')
        self.assertEqual(actual,['0x080C1480','0x080C1499','0x080C1499','0x080C1499'])

    def test_collapsed_profile_glyph_has_no_fill_and_keeps_a_focus_outline(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            SiloUINavigationInit():SiloUINavigationBuild():m.navigationMode="left"
            m.zone="heroButtons":SiloUINavigationSync()
            resting=m.top.findNode("navMenuFocus").opacity
            m.zone="nav":SiloUINavigationSync()
            print FormatJson({resting:resting,focused:m.top.findNode("navMenuFocus").opacity,outline:m.top.findNode("navMenuFocus").uri,text:m.top.findNode("navMenuLabel").color})
        ''')
        self.assertEqual(actual,dict(resting=0,focused=1,outline='pkg:/images/ui/card_focus.9.png',text='0xFFFFFFFF'))
    def test_manual_left_away_from_edge_keeps_normal_action_movement(self):
        actual=self.edge_flow('''
            m.view="home":m.zone="heroButtons"
            BuildPills(m.top.findNode("heroButtons"),"heroButtons",["Play","More info"],10)
            m.pillGroups.heroButtons.index=1
        ''','left', ',index:m.pillGroups.heroButtons.index')
        self.assertEqual(actual,dict(opened=False,zone='heroButtons',handled=True,index=0))
    def test_back_away_from_home_row_edge_preserves_reset_behavior(self):
        actual=self.edge_flow('''
            m.view="home":m.zone="rows":m.rows=m.top.findNode("rows")
            m.rows.rowItemFocused=[3,2]
        ''','back', ',jump:m.rows.jumpToRowItem')
        self.assertEqual(actual,dict(opened=False,zone='rows',handled=True,jump=[0,0]))

    def test_open_drawer_keeps_profile_header_and_top_right_brand(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        actual=SiloUIAppearanceTests().native_flow('''
            SiloUINavigationInit():SiloUINavigationBuild():m.navigationMode="left"
            m.drawerOpen=true:m.drawerIndex=0:m.zone="drawer"
            m.top.findNode("avatarText").text="M"
            SiloUINavigationKey("up")
            header={index:m.drawerIndex,profile:m.top.findNode("navMenu").visible,brand:m.top.findNode("navSiloLogo").visible,focus:m.top.findNode("navMenuFocus").opacity}
            SiloUINavigationKey("down")
            print FormatJson({header:header,index:m.drawerIndex,focus:m.top.findNode("navMenuFocus").opacity})
        ''')
        self.assertEqual(actual,dict(header=dict(index=-1,profile=True,brand=True,focus=1),index=0,focus=0))

    def test_silo_libraries_destination_rebuilds_after_provider_is_known(self):
        from tests.test_silo_ui_libraries import LibrariesTests
        actual=LibrariesTests().run_flow('''
            m.navPills={}
            m.provider="":LibrariesNavigation()
            initial=m.navItems
            m.provider="silo":LibrariesNavigation()
            silo=m.navItems
            top=m.pillGroups.nav.pills.Count()
            m.provider="plex":LibrariesNavigation()
            print FormatJson({initial:initial,silo:silo,top:top,plex:m.navItems,requests:m.pending})
        ''')
        self.assertNotIn('Libraries',actual['initial'])
        self.assertEqual(actual['silo'],['Home','Search','Movies','Shows','Libraries','Audiobooks','Books','Settings'])
        self.assertEqual(actual['top'],8)
        self.assertNotIn('Libraries',actual['plex'])
        self.assertIsNone(actual['requests'])

    def test_libraries_single_column_left_and_back_open_drawer_and_restore_selection(self):
        from tests.test_silo_ui_appearance import SiloUIAppearanceTests
        for key in ('left','back'):
            with self.subTest(key=key):
                actual=SiloUIAppearanceTests().native_flow('''
                    m.manualFocus=m.top.findNode("manualFocus"):m.nav=m.top.findNode("nav")
                    m.navItems=["Home","Search","Movies","Shows","Libraries"]
                    m.pillGroups.nav={index:4,pills:[]}
                    m.sourceId="source":m.profileId="profile":m.generation=1
                    SiloUINavigationInit():SiloUINavigationBuild():m.navigationMode="left"
                    m.view="libraries":m.zone="librariesList"
                    m.librariesList=m.top.findNode("librariesList")
                    m.librariesList.content=NativeNode()
                    m.librariesList.content.children=[NativeNode(),NativeNode(),NativeNode()]
                    m.librariesList.itemFocused=2
                    handled=SiloUINavigationKey("'''+key+'''")
                    opened=m.drawerOpen
                    if opened then SiloUINavigationKey("right")
                    print FormatJson({handled:handled,opened:opened,zone:m.zone,index:m.librariesList.itemFocused,focused:m.librariesList.focused})
                ''')
                self.assertEqual(actual,dict(handled=True,opened=True,zone='librariesList',index=2,focused=True))
