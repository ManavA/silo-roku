"""Change only native Type names; keep real numeric values and shipping flows."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class SiloUINativeNumbersTests(unittest.TestCase):
 def test_boxed_integer_transport_settings_handshake_and_row_focus(self):
  with tempfile.TemporaryDirectory() as d:
   files=[]
   for name in ['source/core/SiloUITransportPolicy.brs','source/core/SiloUISettingsPolicy.brs','source/core/SiloUIHomePolicy.brs','components/SiloUISettings.brs']:
    target=Path(d)/Path(name).name
    target.write_text(re.sub(r'\btype\s*\(', 'NativeNumberType(', (ROOT/name).read_text(),flags=re.I))
    files.append(target)
   boundary=Path(d)/'native.brs';boundary.write_text('''
function NativeNumberType(value as Dynamic) as String
 kind=type(value)
 if kind="Integer" or kind="roInt" then return "roInteger"
 if kind="String" then return "roString"
 return kind
end function
sub Api(action,params,purpose,extra)
 m.calls.Push(action)
end sub
sub Toast(message)
end sub
''')
   out=run_brightscript(files+[boundary],'''
    cue=SiloUITransportSkipCue([{kind:"intro",startMs:0,endMs:5000}],1000,"ask")
    chapters=SiloUITransportChapters([{start_seconds:0,end_seconds:20,title:"Opening"},{start_seconds:20,end_seconds:40,title:"Next"}],60000)
    invalidNumber=SiloUITransportNumber("20") or SiloUITransportNumber(-1) or SiloUITransportNumber(604800001)
    prefs=SiloUISettingsPreferences({promptSeconds:30,stillWatching:5})
    m.calls=[]:m.settingsEpoch=0:m.settingsScope="profile":m.settingsRevision=0:m.settingsReady=false:m.settingsKeys=[]:m.preferences={}
    m.localPreferences={subtitles:"off"}
    SiloUISettingsResult("settings_caps",{ok:true},{api_version:1,allowed:true,state:"available",manifest_revision:3,scopes:["profile"]},0)
    SiloUISettingsResult("settings_manifest",{ok:true},{revision:3,definitions:[{key:"playback.subtitle_mode",introduced_in:1,persistence:"remote",allowed_scopes:["profile"]}]},0)
    SiloUISettingsResult("settings_values",{ok:true},{revision:3,items:[{key:"playback.subtitle_mode",value:"always"}]},0)
    hydration=SiloUIHomeHydration([{rowId:"section",totalCount:2,items:[]}],"scope")
    print FormatJson({hydration:hydration.queue,cue:cue,chapters:chapters,invalidNumber:invalidNumber,prefs:prefs,calls:m.calls,ready:m.settingsReady,keys:m.settingsKeys,subtitles:m.preferences.subtitles,focus:SiloUIHomeFocusPosition([0,1],2,3)})
   ''',root=Path(d))
  r=json.loads(out)
  self.assertEqual(r['cue'],dict(endMs=5000,label='skip intro'))
  self.assertEqual(r['chapters'],[dict(positionMs=0,title='Opening'),dict(positionMs=20000,title='Next')])
  self.assertFalse(r['invalidNumber'])
  self.assertEqual(r['prefs']['promptSeconds'],30);self.assertEqual(r['prefs']['stillWatching'],5)
  self.assertEqual(r['calls'],['settings_contract','settings_effective'])
  self.assertTrue(r['ready']);self.assertEqual(r['keys'],['playback.subtitle_mode'])
  self.assertEqual(r['subtitles'],'always');self.assertEqual(r['focus'],[0,1])
  self.assertEqual(r['hydration'],[0])
