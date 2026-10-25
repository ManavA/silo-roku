"""Login/settings keep their original registry ownership after a UI rename."""
import json
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class RegistryCompatibilityTests(unittest.TestCase):
    def execute_registry(self, body):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / 'store.brs'
            store.write_text((ROOT / 'source/auth/SessionStore.brs').read_text().replace(
                'CreateObject("roRegistrySection",', 'FixtureSection(').replace(
                'CreateObject("roRegistry")', 'FixtureRegistry()'))
            native = root / 'registry.brs'
            native.write_text('''
function FixtureRegistry()
    return {GetSectionList:function()
        return m.global.sections.Keys()
    end function, global:GetGlobalAA()}
end function
function FixtureSection(name)
    g=GetGlobalAA()
    if not g.sections.DoesExist(name)
        g.sections[name]={values:{},name:name,global:g,Exists:function(key)
            return m.values.DoesExist(key)
        end function,Read:function(key)
            if not m.values.DoesExist(key) then return ""
            return m.values[key]
        end function,Write:function(key,value)
            if m.name = "silo.registry" and m.global.failMarkerWrite = true then return false
            if m.global.trackMutations = true and m.name <> "silo.registry" then m.global.dataWrites++
            m.values[key]=value
            return true
        end function,Delete:function(key)
            if m.global.trackMutations = true then m.global.dataDeletes++
            m.values.Delete(key)
            return true
        end function,Flush:function()
            if m.name = "silo.registry" and m.global.failMarkerFlush = true then return false
            return true
        end function}
    end if
    return g.sections[name]
end function
''')
            return json.loads(run_brightscript([store, native], body, root=root))

    def test_existing_login_revision_preferences_and_signout_share_one_namespace(self):
        actual = self.execute_registry('''
g=GetGlobalAA():g.sections={}
session={sourceId:"silo:stable-server",baseUrl:"https://server.example",profileId:"stable-profile",accessToken:"synthetic-access",refreshToken:"synthetic-refresh"}
FixtureSection("legacy.silo").Write("session",FormatJson(session))
FixtureSection("legacy.silo").Write("revision","7")
FixtureSection("legacy.preferences").Write("appearance","glass")
restored=LoadSession("silo")
preference=AppRegistrySection("preferences").Read("appearance")
revision=SessionRevision("silo")
cleared=ClearSession("silo")
print FormatJson({source:restored.sourceId,profile:restored.profileId,refresh:restored.refreshToken,appearance:preference,revision:revision,cleared:cleared,afterRevision:SessionRevision("silo"),afterCount:LoadSession("silo").Count(),afterAppearance:AppRegistrySection("preferences").Read("appearance"),metadata:AppRegistrySection("metadata").Read("baseUrl")})
''')
        self.assertEqual(dict(source='silo:stable-server', profile='stable-profile', refresh='synthetic-refresh',appearance='glass',revision=7,cleared=True,afterRevision=8,afterCount=0,afterAppearance='glass',metadata=''),actual)

    def test_signed_out_install_keeps_its_validated_display_settings(self):
        actual = self.execute_registry('''
g=GetGlobalAA():g.sections={}
FixtureSection("legacy.silo").Write("revision","8")
FixtureSection("legacy.preferences").Write("appearance","glass")
print FormatJson({appearance:AppRegistrySection("preferences").Read("appearance"),revision:SessionRevision("silo"),login:LoadSession("silo").Count()})
''')
        self.assertEqual(dict(appearance="glass",revision=8,login=0),actual)

    def test_malformed_provider_record_cannot_select_a_foreign_namespace(self):
        actual = self.execute_registry('''
g=GetGlobalAA():g.sections={}
FixtureSection("foreign.silo").Write("session",FormatJson({sourceId:"plex:other",accessToken:"synthetic",baseUrl:"https://other.example"}))
FixtureSection("foreign.preferences").Write("appearance","glass")
print FormatJson({appearance:AppRegistrySection("preferences").Read("appearance"),login:LoadSession("silo").Count()})
''')
        self.assertEqual(dict(appearance="",login=0),actual)

    def test_plex_account_link_before_server_choice_survives_namespace_change(self):
        actual = self.execute_registry('''
g=GetGlobalAA():g.sections={}
FixtureSection("legacy.plex").Write("session",FormatJson({sourceId:"",accountToken:"synthetic-account"}))
print FormatJson({account:LoadSession("plex").accountToken})
''')
        self.assertEqual(dict(account="synthetic-account"),actual)

    def test_signed_out_install_keeps_saved_server_addresses_without_display_preferences(self):
        actual = self.execute_registry('''
g=GetGlobalAA():g.sections={}
FixtureSection("legacy.silo").Write("revision","1")
FixtureSection("legacy.servers").Write("silo",FormatJson(["https://server.example"]))
print FormatJson({servers:ParseJson(AppRegistrySection("servers").Read("silo")),revision:SessionRevision("silo")})
''')
        self.assertEqual(dict(servers=['https://server.example'],revision=1),actual)

    def test_marker_storage_failure_still_restores_original_login_and_settings(self):
        for failure in ("failMarkerWrite", "failMarkerFlush"):
            with self.subTest(failure=failure):
                actual = self.execute_registry('''
g=GetGlobalAA():g.sections={}
session={sourceId:"silo:stable-server",baseUrl:"https://server.example",profileId:"stable-profile",accessToken:"synthetic-access",refreshToken:"synthetic-refresh"}
original=FormatJson(session)
FixtureSection("legacy.silo").Write("session",original)
FixtureSection("legacy.silo").Write("revision","7")
FixtureSection("legacy.preferences").Write("appearance","glass")
g.FAILURE=true:g.trackMutations=true:g.dataWrites=0:g.dataDeletes=0
appearance=AppRegistrySection("preferences").Read("appearance")
restored=LoadSession("silo")
print FormatJson({appearance:appearance,source:restored.sourceId,profile:restored.profileId,refreshPreserved:restored.refreshToken="synthetic-refresh",revision:SessionRevision("silo"),originalPreserved:FixtureSection("legacy.silo").Read("session")=original,dataWrites:g.dataWrites,dataDeletes:g.dataDeletes})
'''.replace("FAILURE",failure))
                self.assertEqual(dict(appearance="glass",source="silo:stable-server",profile="stable-profile",refreshPreserved=True,revision=7,originalPreserved=True,dataWrites=0,dataDeletes=0),actual)
