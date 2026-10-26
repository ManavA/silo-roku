"""Shipping appearance palettes and the settings/persistence boundary."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import run_function, run_brightscript
ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'source/core/SiloUIAppearancePolicy.brs'

class SiloUIAppearanceTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory() as root:
            return run_function([POLICY],name,list(args),root=Path(root))

    def test_mode_validation_defaults_to_oled(self):
        for value in [None,'', 'bogus', {'token':'private'}, 1]:
            self.assertEqual(self.call('SiloUIAppearanceMode',value),'oled')
        for value in ['oled','glass','silo_blue','light_blue']:
            self.assertEqual(self.call('SiloUIAppearanceMode',value),value)

    def test_referential_logo_does_not_repeat_silo_as_the_server_label(self):
        for value in [None, '', 'Silo', ' SILO ']:
            self.assertEqual(self.call('SiloUIAppearanceServerLabel',value),'')
        self.assertEqual(self.call('SiloUIAppearanceServerLabel','Living Room'),'Living Room')

    def test_every_appearance_keeps_a_dark_canvas_and_light_text(self):
        for mode in ['oled','glass','silo_blue','light_blue']:
            palette=self.call('SiloUIAppearancePalette',mode)
            with self.subTest(mode=mode):
                self.assertLess(max(int(palette['base'][i:i+2],16) for i in [2,4,6]),64)
                self.assertEqual(palette['text'],'0xFFFFFFFF')
                self.assertLess(max(int(palette['wash'][i:i+2],16) for i in [2,4,6]),64)

    def test_four_distinct_palettes_and_readable_text(self):
        palettes=[self.call('SiloUIAppearancePalette',mode) for mode in ['oled','glass','silo_blue','light_blue']]
        self.assertEqual(palettes[0]['base'],'0x000000FF')
        self.assertLess(int(palettes[1]['panel'][-2:],16),255)
        self.assertEqual(len({p['base'] for p in palettes}),4)
        def luminance(color):
            channels=[int(color[i:i+2],16)/255 for i in (2,4,6)]
            linear=[v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in channels]
            return sum(x*y for x,y in zip(linear,[.2126,.7152,.0722]))
        for palette in palettes:
            for text,background in [('text','base'),('muted','base'),('focustext','focus'),('muted','pill')]:
                values=sorted([luminance(palette[text]),luminance(palette[background])])
                self.assertGreaterEqual((values[1]+.05)/(values[0]+.05),4.5)

    def fixture(self, files, script, replacements=()):
        with tempfile.TemporaryDirectory() as root:
            source='\n'.join((ROOT/name).read_text() for name in files)
            for name,body in replacements:
                source=re.sub(r'(?:sub|function) '+name+r'\(.*?\nend (?:sub|function)',body,source,count=1,flags=re.S)
            source+='''
function MetadataRequestConfig(version)
    return {baseUrl:""}
end function
function HmBaseUrl(value)
    return ""
end function
'''
            p=Path(root)/'fixture.brs';p.write_text(source)
            return json.loads(run_brightscript([POLICY,p],script,root=Path(root)).splitlines()[-1])

    def native_flow(self, script):
        # Only OS registry and SceneGraph construction are replaced. The full
        # Settings -> palette -> node updates -> registry -> launch path is real.
        with tempfile.TemporaryDirectory() as root:
            names=['SiloUIOnboarding','SiloUIAppearance','SiloUIScene','SiloUIHome','SiloUIPlayer','SiloUINavigation','SiloUIDetail','SiloUILibrary','SiloUILibraries','SiloUIRobustness','SiloUILan']
            source='\n'.join((ROOT/'components'/f'{name}.brs').read_text() for name in names)
            source+='\n'+(ROOT/'source/core/SiloUIFormat.brs').read_text()
            source+='\n'+(ROOT/'source/core/SiloUINavigationPolicy.brs').read_text()
            source+='\n'+(ROOT/'components/SiloUIAccessibility.brs').read_text()
            source=source.replace('CreateObject(', 'NativeObject(')
            source+='''
function AppRegistrySection(suffix)
    return m.nativeRegistry
end function
function MetadataRequestConfig(version)
    return {baseUrl:""}
end function
function HmBaseUrl(value)
    return ""
end function
function NativeObject(kind as String, detail = invalid as Dynamic) as Dynamic
    if kind="roRegistrySection" then return m.nativeRegistry
    return NativeNode()
end function
function NativeNode() as Object
    return {text:"",children:[],removeChildrenIndex:sub(count,index)
        m.children=[]
    end sub,setFocus:sub(value)
        m.focused=value
    end sub,boundingRect:function()
        return {height:40,width:200}
    end function,createChild:function(kind)
        child=NativeNode()
        m.children.Push(child)
        return child
    end function,getChild:function(index)
        return m.children[index]
    end function,getChildCount:function()
        return m.children.Count()
    end function}
end function
'''
            fixture=Path(root)/'settings.brs';fixture.write_text(source)
            setup='''
                m.nativeRegistry={entries:{},Read:function(key)
                    if m.entries[key]=invalid then return ""
                    return m.entries[key]
                end function,Write:sub(key,value)
                    m.entries[key]=value
                end sub,Flush:sub()
                end sub}
                m.top={nodes:{},findNode:function(name)
                    if m.nodes[name]=invalid then m.nodes[name]=NativeNode()
                    return m.nodes[name]
                end function}
                m.view="onboarding":m.zone="":m.pillGroups={}:m.focusTraceRemaining=0
                m.provider="silo":m.navSource={text:""}
                for each name in ["backdropTimer","backdropFade","backdrop","backdropOld"]
                    m[name]=m.top.findNode(name)
                end for
                m.preferences={quality:"720p",subtitles:"forced"}
                m.nativeRegistry.entries.silo=FormatJson(m.preferences)
                for each name in ["obEyebrow","obTitle","obBody","obCode","obButtons"]
                    m[name]=m.top.findNode(name)
                end for
            '''
            return json.loads(run_brightscript([POLICY,fixture],setup+script,root=Path(root)).splitlines()[-1])

    def test_settings_changes_visible_theme_and_restores_it_on_launch(self):
        actual=self.native_flow('''
            ObChoose({action:"appearance"})
            choices=m.obChoices
            ObChoose({action:"appearance_select",value:"light_blue"})
            immediate={mode:m.top.appearanceMode,background:m.top.nodes.base.color,title:m.top.nodes.obTitle.color,focus:m.top.nodes.obButtons.focusBitmapBlendColor}
            m.top= {nodes:{},findNode:function(name)
                if m.nodes[name]=invalid then m.nodes[name]=NativeNode()
                return m.nodes[name]
            end function}
            m.appearanceMode=invalid:m.appearance=invalid
            SiloUIAppearanceInit()
            print FormatJson({choices:choices,immediate:immediate,restored:{mode:m.top.appearanceMode,background:m.top.nodes.base.color,title:m.top.nodes.obTitle.color},preferences:m.preferences,sourcePreferences:ParseJson(m.nativeRegistry.Read("silo"))})
        ''')
        self.assertEqual([c['value'] for c in actual['choices'][:-1]],['oled','glass','silo_blue','light_blue'])
        self.assertEqual(actual['immediate'],dict(mode='light_blue',background='0x07111FFF',title='0xFFFFFFFF',focus='0xB8E1FFFF'))
        self.assertEqual(actual['restored'],dict(mode='light_blue',background='0x07111FFF',title='0xFFFFFFFF'))
        self.assertEqual(actual['preferences'],dict(quality='720p',subtitles='forced'))
        self.assertEqual(actual['sourcePreferences'],dict(quality='720p',subtitles='forced'))

    def test_launch_uses_oled_for_invalid_saved_appearance(self):
        actual=self.native_flow('''
            m.nativeRegistry.entries.appearance="invalid"
            SiloUIAppearanceInit()
            print FormatJson({mode:m.top.appearanceMode,background:m.top.nodes.base.color})
        ''')
        self.assertEqual(actual,dict(mode='oled',background='0x000000FF'))

    def test_settings_native_focus_asset_fits_the_46_pixel_row(self):
        actual=self.native_flow('''
            ObChoose({action:"appearance_select",value:"oled"})
            print FormatJson({bitmap:m.obButtons.focusBitmapUri,row:m.obButtons.numRows})
        ''')
        import struct
        asset=ROOT/actual['bitmap'].removeprefix('pkg:/')
        width,height=struct.unpack('>II',asset.read_bytes()[16:24])
        self.assertLessEqual(height-2,46,'fixed 9-patch edges must fit a native Settings row')
        # Both full content edges prevent intrinsic padding from expanding a row.
        import zlib
        data=asset.read_bytes();offset=8;chunks=[]
        while offset<len(data):
            length=struct.unpack('>I',data[offset:offset+4])[0]
            if data[offset+4:offset+8]==b'IDAT':chunks.append(data[offset+8:offset+8+length])
            offset+=12+length
        pixels=zlib.decompress(b''.join(chunks));stride=width*4+1
        self.assertEqual(pixels[(height-1)*stride],0)
        bottom=pixels[(height-1)*stride+1:height*stride]
        self.assertTrue(all(bottom[x*4:x*4+4]==bytes([0,0,0,255]) for x in range(1,width-1)))

    def test_applier_updates_real_surfaces_and_preserves_artwork(self):
        actual=self.fixture(['components/SiloUIAppearance.brs'],'''
            m.pillGroups={}
            m.top={nodes:{backdrop:{uri:"fixture-art"}},findNode:function(name)
                if m.nodes[name]=invalid then m.nodes[name]={}
                return m.nodes[name]
            end function}
            SiloUIApplyAppearance("light_blue")
            light={base:m.top.nodes.base.color,panel:m.top.nodes.appearancePanel.color,text:m.top.nodes.heroTitle.color,focus:m.top.nodes.obButtons.focusBitmapBlendColor,mode:m.top.appearanceMode,rating:m.top.nodes.detailRatings.color}
            SiloUIApplyAppearance("oled")
            print FormatJson({light:light,black:m.top.nodes.base.color,art:m.top.nodes.backdrop.uri})
        ''')
        self.assertEqual(actual['light']['base'],'0x07111FFF')
        self.assertEqual(actual['light']['text'],'0xFFFFFFFF')
        self.assertEqual(actual['light']['mode'],'light_blue')
        self.assertEqual(actual['light']['rating'],'0xA7D9FFFF')
        self.assertEqual(actual['black'],'0x000000FF')
        self.assertEqual(actual['art'],'fixture-art')



    def test_text_contrast_includes_the_brightest_possible_backdrop(self):
        def rgb(color):
            return [int(color[i:i+2],16)/255 for i in (2,4,6)]
        def lum(channels):
            return sum(w*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4) for v,w in zip(channels,[.2126,.7152,.0722]))
        for mode in ['oled','glass','silo_blue','light_blue']:
            palette=self.call('SiloUIAppearancePalette',mode)
            alpha=int(palette['wash'][-2:],16)/255
            art=lum([v*alpha+1-alpha for v in rgb(palette['wash'])])
            for text in ['text','muted']:
                values=sorted([lum(rgb(palette[text])),art])
                with self.subTest(mode=mode,text=text):
                    self.assertGreaterEqual((values[1]+.05)/(values[0]+.05),4.5)

    def test_settings_header_omits_separator_without_distinct_server_name(self):
        for name,expected in [('', 'Silo'),('Living Room','Silo · Living Room')]:
            actual=self.fixture(['source/core/SiloUIFormat.brs','components/SiloUIOnboarding.brs'],f'''
                m.provider="silo":m.navSource={{text:"{name}"}}
                m.preferences={{quality:"original",subtitles:"off"}}
                OnboardingSettings()
                print FormatJson(m.heading)
            ''', [('ObScreen','sub ObScreen(a as String,b as String,c as String,d as String,e as Object)\n m.heading=b\nend sub')])
            self.assertEqual(actual,expected)

    def test_back_to_home_selection_does_not_reopen_settings_from_same_press(self):
        actual=self.native_flow('''
            m.speculationDisabled=true
            m.backdropTimer=m.top.findNode("backdropTimer")
            m.manualFocus=m.top.findNode("manualFocus")
            m.nav=m.top.findNode("nav")
            m.backdrop=m.top.findNode("backdrop"):m.backdropOld=m.top.findNode("backdropOld")
            m.navItems=["Home","Search","Movies","Shows","Settings"]
            m.pillGroups.nav={index:4,pills:[]}
            OnboardingSettings()
            m.obButtons.itemSelected=0
            onObSelected()
            handled=onKeyEvent("OK",true)
            returned=m.view
            onKeyEvent("OK",false)
            onKeyEvent("OK",true)
            print FormatJson({returned:returned,handled:handled,nextPress:m.view})
        ''')
        self.assertEqual(actual,dict(returned='home',handled=True,nextPress='onboarding'))
