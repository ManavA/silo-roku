import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]
class SiloUISpeedTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory() as root:
            return run_function([ROOT/'source/core/SiloUISettingsPolicy.brs'], name, list(args), root=Path(root))
    def test_output_cap_only_for_implicit_silo_4k_on_known_hd_output(self):
        for mode,expected in [('1080p','1080p'),('720p','720p'),('480p','720p')]:
            self.assertEqual(self.call('SiloUISpeedQuality','silo','original',False,'2160p',mode),expected)
        for provider,explicit,resolution,mode in [('plex',False,'2160p','1080p'),('silo',True,'2160p','1080p'),('silo',False,'1080p','1080p'),('silo',False,'2160p','2160p60'),('silo',False,'2160p','')]:
            self.assertEqual(self.call('SiloUISpeedQuality',provider,'original',explicit,resolution,mode),'original')
        self.assertEqual(self.call('SiloUISpeedQuality','silo','720p',True,'4k','1080p'),'720p')
    def test_hero_only_first_continue_item_at_hero_focus(self):
        rows=[{'sectionType':'recently_added','items':[{'itemId':'x'}]},{'sectionType':'continue_watching','items':[{'itemId':'a'},{'itemId':'b'}]}]
        self.assertTrue(self.call('SiloUISpeedHero',rows,'a','home','heroButtons'))
        for item,view,zone in [('b','home','heroButtons'),('x','home','heroButtons'),('a','home','rows'),('a','detail','heroButtons')]:
            self.assertFalse(self.call('SiloUISpeedHero',rows,item,view,zone))
    def test_hero_request_fences_late_detail_and_does_not_churn(self):
        from tests.test_silo_ui_settings_policy import SiloUISettingsPolicyTests
        actual = SiloUISettingsPolicyTests().component('SiloUIPlayer.brs', '''
            m.calls=[] : m.provider="silo" : m.view="home" : m.zone="heroButtons"
            m.generation=1 : m.playToken=0 : m.homeRows=[{sectionType:"continue_watching",items:[{itemId:"a"}]}]
            m.heroItem={itemId:"a"} : m.top={memoryPressure:20}
            PlayerSyncHeroPrebuffer()
            token=m.heroPrebufferRequest
            m.heroItem={itemId:"b"} : PlayerSyncHeroPrebuffer()
            PlayerResult("play_hero_detail",{ok:true},{item:{itemId:"a"},versions:[{versionId:"f"}]},token)
            m.heroItem={itemId:"a"} : PlayerSyncHeroPrebuffer()
            print FormatJson(m.calls)
        ''', helpers='''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
        ''')
        self.assertEqual(actual,['detail'])
    def test_selected_file_quality_uses_native_mode_probe_and_explicit_flag(self):
        from tests.test_silo_ui_settings_policy import SiloUISettingsPolicyTests
        actual=SiloUISettingsPolicyTests().component('SiloUIPlayer.brs','''
            m.provider="silo" : m.preferences={quality:"original"} : m.qualityExplicit=false
            automatic=PlayerSpeedQuality({resolution:"2160p"})
            m.qualityExplicit=true
            print FormatJson([automatic,PlayerSpeedQuality({resolution:"2160p"})])
        ''',[('PlayerVideoMode','function PlayerVideoMode() as String\n return "1080p"\nend function')])
        self.assertEqual(actual,['1080p','original'])
    def test_hero_skips_multiple_versions_and_memory_cancels_pending_detail(self):
        from tests.test_silo_ui_settings_policy import SiloUISettingsPolicyTests
        actual=SiloUISettingsPolicyTests().component('SiloUIPlayer.brs','''
            m.calls=[] : m.provider="silo" : m.view="home" : m.zone="heroButtons"
            m.generation=1 : m.playToken=0 : m.homeRows=[{sectionType:"continue_watching",items:[{itemId:"a"}]}]
            m.heroItem={itemId:"a"} : m.top={memoryPressure:20}
            PlayerSyncHeroPrebuffer() : token=m.heroPrebufferRequest
            PlayerResult("play_hero_detail",{ok:true},{item:{itemId:"a"},versions:[{versionId:"f"},{versionId:"g"}]},token)
            m.heroPrebufferAttempt=false : PlayerSyncHeroPrebuffer() : token=m.heroPrebufferRequest
            m.top.memoryPressure=80 : onPlayerMemoryPressure()
            PlayerResult("play_hero_detail",{ok:true},{item:{itemId:"a"},versions:[{versionId:"f"}]},token)
            print FormatJson(m.calls)
        ''',helpers='''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
        ''')
        self.assertEqual(actual,['detail','detail'])
