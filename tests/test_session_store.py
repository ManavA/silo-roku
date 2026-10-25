"""The registry round trip must preserve mixed-case session field lookups."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "source/auth/SessionPolicy.brs", ROOT / "source/auth/SessionStore.brs"]


class SessionStoreTests(unittest.TestCase):
    def test_saved_login_survives_new_runtime_version_until_explicit_signout(self):
        # Replace only native registry/device boundaries. Production storage,
        # launch metadata refresh and public connection policy execute together.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "store.brs"
            store.write_text(FILES[1].read_text().replace(
                'AppRegistrySection(provider)',
                'FixtureSection("silo." + provider)'))
            device_session = re.search(
                r"function TaskDeviceSession\(.*?^end function",
                (ROOT / "components/ApiTask.brs").read_text(), re.S | re.M).group()
            native = root / "native.brs"
            native.write_text(device_session.replace(
                'CreateObject("roDeviceInfo")', 'FixtureDevice()') + '''
function FixtureDevice()
    return {GetChannelClientId:function()
        return "fixture-device"
    end function, GetModel:function()
        return "fixture-model"
    end function, GetOSVersion:function()
        return {major:"15",minor:"3",revision:"4"}
    end function}
end function
function RuntimeAppVersion()
    return m.installedVersion
end function
function FixtureSection(name)
    if not m.sections.DoesExist(name)
        m.sections[name] = {values:{},Exists:function(key)
            return m.values.DoesExist(key)
        end function,Read:function(key)
            return m.values[key]
        end function,Write:function(key,value)
            m.values[key]=value
            return true
        end function,Delete:function(key)
            m.values.Delete(key)
            return true
        end function,Flush:function()
            return true
        end function}
    end if
    return m.sections[name]
end function
''')
            output = run_brightscript([FILES[0], store, native], '''
m.sections={}:results=[]
for each provider in ["silo","plex"]
    m.installedVersion="0.2.30"
    session={baseUrl:"https://fixture.example",sourceId:provider+":fixture",profileId:"profile",accessToken:"synthetic-access",refreshToken:"synthetic-refresh",accountToken:"synthetic-account",token:"synthetic-server"}
    saved=SaveSession(provider,TaskDeviceSession(provider,session),0)
    m.installedVersion="0.2.31"
    restored=TaskDeviceSession(provider,LoadSession(provider))
    status=PublicSessionStatus(provider,restored)
    results.Push({saved:saved,connected:status.connected,version:SessionText(restored,"appVersion"),refresh:SessionText(restored,"refreshToken")="synthetic-refresh",account:SessionText(restored,"accountToken")="synthetic-account",revision:SessionRevision(provider)})
    FixtureSection("silo." + provider).Write("recentSearches","synthetic history")
    cleared=ClearSession(provider)
    results.Push({cleared:cleared,connected:PublicSessionStatus(provider,LoadSession(provider)).connected,revision:SessionRevision(provider),history:FixtureSection("silo." + provider).Exists("recentSearches")})
end for
print FormatJson(results)
''', root=root)
        expected_login = dict(saved=True, connected=True, version="0.2.31",
                              refresh=True, account=True, revision=0)
        expected_logout = dict(cleared=True, connected=False, revision=1, history=False)
        self.assertEqual([expected_login, expected_logout] * 2, json.loads(output))

    def test_decoded_registry_fields_are_available_to_next_task(self):
        output = run_brightscript(FILES,
            'session = DecodeStoredSession("{""accounttoken"":""synthetic"",""sourceid"":""plex:one""}")\n'
            'print SessionText(session, "accountToken")\n'
            'print SessionText(session, "sourceId")')
        self.assertIn("synthetic", output)
        self.assertIn("plex:one", output)

    def test_bad_registry_record_becomes_empty_session(self):
        output = run_brightscript(FILES,
            'session = DecodeStoredSession("bad")\nprint session.Count()')
        self.assertIn("0", output)


if __name__ == "__main__":
    unittest.main()
