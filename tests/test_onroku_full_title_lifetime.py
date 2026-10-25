"""Constructed full-title metadata; no media transfer, extraction or identity claim.

The 2,048-entry title represents 49 GiB using repeating 16/24/32/26 MiB
source lengths. Only playlist text and metadata are allocated. Publication visit
counts instrument the actual loop in a temporary source copy, not production.
"""
from pathlib import Path
import json
import tempfile
import unittest

from tools.brightscript import run_brightscript

SOURCE = Path(__file__).resolve().parents[1] / "tools/experiments/onroku_audio/multi_app/source"


class FullTitleLifetime(unittest.TestCase):
    def test_stock_hls_rounding_uses_stable_local_targets_and_keeps_audio_cap(self):
        # RFC 8216 section 4.3.3.1: EXTINF rounded to nearest integer must
        # fit upstream TARGETDURATION. Offline original P7 begins at 2.002s.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rounding.brs'
            path.write_text((SOURCE / 'Rolling.brs').read_text() + '\nfunction QaRemoteSize(path as String) as Double\n return 1#\nend function\nfunction QaAudioTrack(data as Dynamic) as Object\n return {codec:"ac-3"}\nend function\n')
            out = run_brightscript(path, '''
for each micros in [2002000,2499999,2500000,2878000]
 m.top={ready:false,failed:false}:m.routes={}
 r=QaRollingState("http://owned.test/title.m3u8")
 r.stock={token:""}:r.init=invalid:r.initPath="tmp:/init"
 r.descriptor={targetDuration:2,durations:[micros/1000000#],durationMicros:[micros],fragments:["part.m4s"],ended:false}
 r.source="tmp:/video":r.sourceSize=1#:r.sourceDigest="metadata"
 r.audioDigest="metadata":r.completedDuration=1.888#
 r.completedJob={target:"tmp:/audio",plan:{timescale:48000,trackid:2,samples:[{pts:6000}],bytes:1}}
 QaRollingFinishPair(r)
 if micros<2500000
  if not r.failed and r.index=1 and r.targets.video=3 and r.targets.audio=3
   video=ReadAsciiFile(m.routes["/g1/video.m3u8"].path)
   audio=ReadAsciiFile(m.routes["/g1/audio.m3u8"].path)
   if Instr(1,video,"#EXT-X-TARGETDURATION:3")>0 and Instr(1,audio,"#EXT-X-TARGETDURATION:3")>0 then print "VALID_PUBLISHED"
  end if
 else
  if r.failed and r.index=0 and r.entries.Count()=0 and m.routes.Count()=0 then print "UPSTREAM_REJECTED"
 end if
end for
''', root=Path(directory))
        self.assertEqual(2, out.count('VALID_PUBLISHED'))
        self.assertEqual(2, out.count('UPSTREAM_REJECTED'))

    def test_upstream_target_growth_does_not_grow_published_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.brs"
            path.write_text((SOURCE / "Rolling.brs").read_text())
            out = run_brightscript(path, '''
r=QaRollingState("http://owned.test/title.m3u8")
r.stock={token:""}:r.descriptor={targetDuration:2}
QaRollingSetTargets(r)
r.descriptor={targetDuration:3,durations:[2.878#],durationMicros:[2878000]}
QaRollingSetTargets(r)
if r.targets.video=3 and r.targets.audio=3 and QaRollingVideoDurationAllowed(r,0) then print "FIXED_TARGETS"
r.descriptor={targetDuration:4,durations:[3.002#],durationMicros:[3002000]}
QaRollingSetTargets(r)
if r.targets.video=3 and r.targets.audio=3 and not QaRollingVideoDurationAllowed(r,0) then print "LOCAL_CAP"
''', root=Path(directory))
        self.assertIn("FIXED_TARGETS", out)
        self.assertIn("LOCAL_CAP", out)

    def test_over_target_new_pair_fails_before_advancing_title(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "append.brs"
            path.write_text((SOURCE / "Rolling.brs").read_text() + '''
function QaRemoteSize(path as String) as Double
 return 1#
end function
''')
            out = run_brightscript(path, '''
for each bad in ["video","audio"]
 m.top={ready:false,failed:false}:m.routes={}
 r=QaRollingState("http://owned.test/title.m3u8")
 r.stock={token:""}:r.descriptor={targetDuration:8,durations:[6],fragments:["part.m4s"],ended:false}
 r.source="tmp:/video":r.sourceSize=16777216#:r.sourceDigest="unverified-source-metadata"
 r.audioDigest="unverified-audio-metadata":r.completedDuration=6
 if bad="video" then r.descriptor.durations[0]=9
 if bad="audio" then r.completedDuration=10
 r.completedJob={target:"tmp:/audio",plan:{timescale:48000,trackid:2,samples:[{pts:0}],bytes:1}}
 QaRollingFinishPair(r)
 if r.failed and m.top.failed and not r.ready and r.index=0 and r.entries.Count()=0 and r.sourceBytes=0 and r.endSeconds=0 and m.routes.Count()=0 then print "REJECTED_"+bad
end for
''', root=Path(directory))
        self.assertIn("REJECTED_video", out)
        self.assertIn("REJECTED_audio", out)

    def test_event_descriptor_appends_reloads_and_finishes_at_2048_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            out = run_brightscript(
                [SOURCE / "RemoteIngest.brs", SOURCE / "StockDescriptor.brs"],
                '''lf=Chr(10):q=Chr(34)
origin="http://owned.test":prefix="/Videos/r/remux-dv-v1/hls/s/":query="?MediaSourceId=m&PlaySessionId=s"
base=origin+prefix+"stream.m3u8"+query
text="#EXTM3U"+lf+"#EXT-X-PLAYLIST-TYPE:EVENT"+lf+"#EXT-X-TARGETDURATION:8"+lf+"#EXT-X-MEDIA-SEQUENCE:0"+lf+"#EXT-X-MAP:URI="+q+"init.mp4"+query+q+lf
for i=0 to 2046
 text+="#EXTINF:6,"+lf+"part-"+i.ToStr()+".m4s"+query+lf
end for
p=QaStockDescriptor(text,base,origin,"r","m","s")
text+="#EXTINF:8,"+lf+"part-2047.m4s"+query+lf
n=QaStockDescriptor(text,base,origin,"r","m","s")
reload=QaStockDescriptorRefresh(n,n)
done=QaStockDescriptor(text+"#EXT-X-ENDLIST"+lf,base,origin,"r","m","s")
if p<>invalid and n<>invalid and done<>invalid and reload<>invalid
 if QaStockDescriptorRefresh(p,n)<>invalid and QaStockDescriptorRefresh(n,done)<>invalid
  if not n.ended and done.ended and done.fragments.Count()=2048 and done.durationMicros[2047]=8000000 then print "APPEND_RELOAD_TRUE_END"
 end if
end if
print "DESCRIPTOR_BYTES=";Len(text)
''', root=Path(directory))
        self.assertIn("APPEND_RELOAD_TRUE_END", out)

    def test_publication_work_stays_bounded_after_full_title_turnover(self):
        # Observe actual historical validation visits at three title ages while
        # holding the visible window at four pairs. This avoids executing two
        # million redundant VM visits merely to demonstrate quadratic growth.
        rolling = (SOURCE / "Rolling.brs").read_text()
        check = "        if e.videoDuration>r.targets.video or e.audioDuration>r.targets.audio then return false\n"
        self.assertEqual(1, rolling.count(check), "update the diagnostic seam")
        rolling = rolling.replace(check, "        GetGlobalAA().visits+=1\n" + check)
        helpers = '''
function QaAudioTrack(data as Dynamic) as Object
 return {codec:"ec-3"}
end function
function QaRemoteSize(path as String) as Double
 return 1#
end function
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lifetime.brs"
            path.write_text(rolling + helpers)
            out = run_brightscript(path, '''
g=GetGlobalAA():results=[]
for each count in [64,128,2048]
 m.routes={}:m.top={ready:false,failed:false}
 r=QaRollingState("http://owned.test/title.m3u8")
 r.stock={token:""}:r.init=invalid:r.initPath="tmp:/init"
 r.descriptor={targetDuration:8,ended:false,fragments:[],durations:[]}
 sizes=[16777216#,25165824#,33554432#,27262976#]
 total=0#
 for i=0 to count-1
  total+=sizes[i mod 4]
  r.descriptor.fragments.Push("part-"+i.ToStr()+".m4s")
  r.descriptor.durations.Push(6)
  r.entries.Push({video:"tmp:/v"+i.ToStr(),audio:"tmp:/a"+i.ToStr(),videoDuration:6,audioDuration:6,endSeconds:(i+1)*6,evicted:i<count-4,resident:i>=count-4,fetching:false,sourceSize:sizes[i mod 4]})
 end for
 r.index=count:r.first=count-4:r.sourceBytes=total:r.endSeconds=count*6
 g.visits=0
 published=QaRollingPublish(r)
 video=ReadAsciiFile(m.routes["/g1/video.m3u8"].path)
 open=Instr(1,video,"ENDLIST")=0
 visits=g.visits
 ' A cold old route still schedules a bounded coalesced refill demand.
 oldDemand=QaRollingDemand(r,0):duplicate=QaRollingDemand(r,0)
 demandCount=r.demand.Count()
 ' A completion-only republication does not append entries or segment routes.
 oldCount=r.entries.Count():oldRoutes=m.routes.Count()
 r.descriptor.ended=true:g.visits=0
 finished=QaRollingPublish(r)
 video=ReadAsciiFile(m.routes["/g1/video.m3u8"].path)
 audio=ReadAsciiFile(m.routes["/g1/audio.m3u8"].path)
 closed=Instr(1,video,"ENDLIST")>0 and Instr(1,audio,"ENDLIST")>0
 results.Push({count:count,published:published,open:open,visits:visits,finished:finished,closed:closed,total:total,entries:r.entries.Count(),routes:m.routes.Count(),stable:oldCount=r.entries.Count() and oldRoutes=m.routes.Count(),demand:oldDemand and duplicate and demandCount=1})
end for
print "RESULT:";FormatJson(results)
''', root=Path(directory))
        rows = json.loads(next(line[7:] for line in out.splitlines() if line.startswith("RESULT:")))
        print("full-title metadata diagnostic: " + json.dumps(rows, separators=(",", ":")))
        for row in rows:
            self.assertTrue(all(row[key] for key in ("published", "open", "finished", "closed", "stable", "demand")), row)
        self.assertEqual(49 * 1024**3, rows[-1]["total"])
        # One cooperative publication must not rescan already retired history.
        # Four visible pairs should cost the same at all three title ages.
        self.assertLessEqual(rows[-1]["visits"], rows[0]["visits"], rows)
