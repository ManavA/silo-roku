"""Only exact original-file duration becomes native ContentNode.Length."""
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_brightscript, run_function

ROOT=Path(__file__).resolve().parents[1]
PLAYER=ROOT/'components/SiloUIPlayer.brs'


def plan(**updates):
    value=dict(provider='silo',sourceId='silo:one',itemId='movie',versionId='wanted',
               url='https://example.invalid/original',streamFormat='mkv',startPositionMs=0,
               playbackDiagnostics={'delivery':'original_http'},timelineOffsetMs=0,
               headers={'X-Test':'fixture'})
    value.update(updates)
    return value


def versions(duration=7200123):
    return [dict(sourceId='silo:one',itemId='movie',versionId='other',durationMs=900000),
            dict(sourceId='silo:one',itemId='movie',versionId='wanted',durationMs=duration)]


class SiloUIContentLength(unittest.TestCase):
    def length(self,value=None,rows=None):
        return run_function(PLAYER,'PlayerOriginalLength',[plan() if value is None else value,
                                                          versions() if rows is None else rows])

    def test_exact_selected_file_duration_is_seconds_with_bounds(self):
        self.assertEqual(7200,self.length())
        self.assertEqual(1,self.length(rows=versions(1000)))
        self.assertEqual(604800,self.length(rows=versions(604800000)))

    def test_missing_duplicate_or_foreign_file_never_supplies_length(self):
        self.assertIsNone(self.length(plan(versionId='missing')))
        self.assertIsNone(self.length(plan(versionId='')))
        self.assertIsNone(self.length(rows=versions()+versions()))
        for field in ('sourceId','itemId'):
            rows=versions();rows[1][field]='foreign'
            self.assertIsNone(self.length(rows=rows))

    def test_invalid_duration_is_omitted(self):
        for duration in (None,0,-1,999,604800001,True,'7200000'):
            with self.subTest(duration=duration):
                self.assertIsNone(self.length(rows=versions(duration)))

    def test_only_original_http_without_rebased_timeline_is_qualified(self):
        for delivery in ('server_remux_hls','server_transcode_hls','server_remux_progressive',''):
            self.assertIsNone(self.length(plan(playbackDiagnostics={'delivery':delivery})))
        self.assertIsNone(self.length(plan(provider='plex')))
        self.assertIsNone(self.length(plan(playbackDiagnostics=None)))
        self.assertIsNone(self.length(plan(timelineOffsetMs=25000)))

    def bind(self,code):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            text=PLAYER.read_text().replace('CreateObject("roSGNode", "ContentNode")','FixtureContent()').replace('CreateObject("roHttpAgent")','FixtureAgent()')
            text=re.sub(r'(?im)^sub PlayerOriginalClear\(', 'sub UnusedPlayerOriginalClear(',text,count=1)
            text=re.sub(r'    print "Silo play timing.*\n','',text)
            player=root/'player.brs';player.write_text(text)
            boundary=root/'boundary.brs';boundary.write_text('''sub PlayerOriginalClear()
end sub
function FixtureContent() as Object
 return {}
end function
function FixtureAgent() as Object
 return {headers:[],SetCertificatesFile:sub(path as String)
 m.certificates=path
 end sub,AddHeader:sub(name as String,value as String)
 m.headers.Push(name+": "+value)
 end sub}
end function
''')
            setup='accepted=ParseJson("'+json.dumps(plan()).replace('"','""')+'")\n'
            setup+='rows=ParseJson("'+json.dumps(versions()).replace('"','""')+'")\n'
            setup+='''m.video={SetHttpAgent:sub(agent as Object)
 m.agent=agent
 end sub}
'''
            output=run_brightscript([player,ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'source/core/SiloUIFormat.brs',boundary],setup+code,root=root)
            return json.loads(output.strip().splitlines()[-1])

    def test_real_bind_keeps_zero_start_headers_and_dedicated_agent(self):
        actual=self.bind('''m.playVersions=rows
 PlayerBind(accepted,"Movie")
 print FormatJson({length:m.video.content.Length,start:m.video.content.playStart,headers:m.video.content.HttpHeaders,agentHeaders:m.video.agent.headers,certificates:m.video.agent.certificates})''')
        self.assertEqual(dict(length=7200,start=0,headers=['X-Test: fixture'],agentHeaders=['X-Test: fixture'],certificates='common:/certs/ca-bundle.crt'),actual)

    def test_prebuffer_bind_uses_its_own_versions_not_foreground_metadata(self):
        actual=self.bind('''m.playVersions=[{sourceId:"silo:one",itemId:"movie",versionId:"wanted",durationMs:999000}]
 m.prebuf={token:5,title:"Preview",versions:rows}
 PlayerResult("play_prebuf",{ok:true,plan:accepted},{},5)
 print FormatJson({length:m.video.content.Length,start:m.video.content.playStart,ready:m.prebuf.ready})''')
        self.assertEqual(dict(length=7200,start=0,ready=True),actual)


if __name__=='__main__':unittest.main()
