"""Startup scheduling at the real settings Scene/API boundary."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class SettingsStartupTests(unittest.TestCase):
    def test_cached_preferences_are_ready_before_contract_network_is_released(self):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d) / 'api.brs'
            settings=Path(d)/'settings.brs'
            settings.write_text((ROOT/'components/SiloUISettings.brs').read_text().replace('AppRegistrySection("preferences")','FixtureRegistry()'))
            stub.write_text('''
function FixtureRegistry()
 return {Read:function(key)
 return FormatJson(SiloUISettingsCachePut([],"silo:fixture","a",{quality:"720p"},true))
 end function}
end function

sub Api(action, params, purpose, extra)
 m.requests.Push({action:action,extra:extra,profile:m.profileId})
end sub
''')
            output = run_brightscript([ROOT/'source/core/SiloUISettingsPolicy.brs', settings, stub], '''
                m.requests=[]:m.sourceId="silo:fixture":m.profileId="a":m.provider="silo"
                SiloUISettingsLoad()
                before=m.requests.Count():quality=m.preferences.quality
                SiloUISettingsStart():SiloUISettingsStart()
                first=m.requests.Count()
                m.profileId="b":SiloUISettingsLoad()
                other=m.preferences.quality
                deferred=m.requests.Count()
                SiloUISettingsStart()
                print FormatJson({before:before,quality:quality,first:first,other:other,deferred:deferred,requests:m.requests})
            ''', root=Path(d))
        result=json.loads(output)
        self.assertEqual(result['before'],0)
        self.assertEqual(result['quality'],'720p')
        self.assertEqual(result['first'],1)
        self.assertEqual(result['other'],'original')
        self.assertEqual(result['deferred'],1)
        self.assertEqual([r['profile'] for r in result['requests']],['a','b'])

    def test_enter_source_dispatches_home_then_settings_without_waiting_for_home(self):
        import re
        with tempfile.TemporaryDirectory() as d:
            parts = []
            for name, file in [('EnterSource', 'SiloUIScene.brs'), ('HomeLoad', 'SiloUIHome.brs')]:
                source = (ROOT/'components'/file).read_text()
                parts.append(re.search(r'sub '+name+r'\(.*?\nend sub', source, re.S).group())
            scene = Path(d)/'scene.brs'
            scene.write_text('\n'.join(parts).replace('CreateObject("roSGNode", "ContentNode")', 'FixtureContent()'))
            settings = Path(d)/'settings.brs'
            settings.write_text((ROOT/'components/SiloUISettings.brs').read_text().replace('AppRegistrySection("preferences")', 'FixtureRegistry()'))
            stub = Path(d)/'native.brs'
            stub.write_text('''
function FixtureRegistry()
 return {Read:function(key)
 return FormatJson(SiloUISettingsCachePut([],"silo:fixture","a",{quality:"720p",subtitles:"always"},true))
 end function}
end function
function FixtureContent()
 return {}
end function
function TextOr(v)
 if v=invalid then return ""
 return v
end function
function NumberOr(v,fallback)
 if v=invalid then return fallback
 return v
end function
function SiloUIAppearanceServerLabel(value)
 return value
end function
function HomeProgressScope()
 return m.profileId
end function
sub HomeEnsureProgressScope()
end sub
sub PlexClearImages()
end sub
sub PlayerDiscardPrebuffer()
end sub
sub LibrariesNavigation()
end sub
sub HomeCacheStart(action)
end sub
sub ShowView(view)
 m.view=view
end sub
sub HeroShow(item)
end sub
sub BuildButtons(node,group,labels)
end sub
sub SetZone(zone)
end sub
sub SiloUILaunchTry()
 m.launchRequests=m.requests.Count()
end sub
sub Api(action,params,purpose,extra)
 m.requests.Push({action:action,profile:m.profileId,generation:m.generation,quality:m.preferences.quality,subtitles:m.preferences.subtitles,rendered:m.homeRendered=true})
end sub
''')
            out = run_brightscript([ROOT/'source/core/SiloUISettingsPolicy.brs', settings, scene, stub], '''
                m.generation=0:m.avatarText={}:m.navSource={}:m.pillGroups={nav:{}}:m.rows={}:m.heroButtons={}
                m.launchInitialized=true:m.requests=[]
                EnterSource("silo",{sourceId:"silo:fixture",profileId:"a",serverName:"Fixture"})
                firstLaunch=m.launchRequests
                SiloUISettingsStart()
                EnterSource("silo",{sourceId:"silo:fixture",profileId:"b",serverName:"Fixture"})
                print FormatJson({requests:m.requests,firstLaunch:firstLaunch,lastLaunch:m.launchRequests})
            ''', root=Path(d))
        result = json.loads(out)
        self.assertEqual(result['firstLaunch'], 2)
        self.assertEqual(result['lastLaunch'], 4)
        self.assertEqual(result['requests'], [
            {'action':'home','profile':'a','generation':1,'quality':'720p','subtitles':'always','rendered':False},
            {'action':'settings_capabilities','profile':'a','generation':1,'quality':'720p','subtitles':'always','rendered':False},
            {'action':'home','profile':'b','generation':2,'quality':'original','subtitles':'off','rendered':False},
            {'action':'settings_capabilities','profile':'b','generation':2,'quality':'original','subtitles':'off','rendered':False},
        ])
