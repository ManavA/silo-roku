"""Focused native artwork recovery uses exact metadata without startup fanout."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class SiloUIPublicArtworkTests(unittest.TestCase):
    def trace(self, script):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Path(directory)/'bridge.brs'
            bridge.write_text('''
function SiloUIArtworkNow()
 return m.now
end function
sub ApiOwned(action,params,purpose,extra,owner)
 m.calls.Push({action:action,params:params,extra:extra,owner:owner})
end sub
sub SetBackdrop(uri)
 m.pendingBackdrop=uri
 m.backdropSets=m.backdropSets+1
end sub
''')
            glue = (ROOT/'components/SiloUIArtwork.brs').read_text()
            glue = glue.replace('function SiloUIArtworkNow()', 'function UnusedArtworkNow()')
            local = Path(directory)/'artwork.brs';local.write_text(glue)
            output = run_brightscript([ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/adapters/MetadataAdapter.brs',ROOT/'source/core/PublicArtworkPolicy.brs',local,bridge], '''
 m.now=0:m.calls=[]:m.backdropSets=0:m.provider="silo":m.sourceId="silo:https://server.test":m.profileId="p":m.generation=1
 m.view="home":m.zone="nav":m.memoryHigh=false
 m.publicArtwork=PublicArtworkCreate():m.publicArtworkTimer={control:"stop"}
 m.backdrop={uri:"dead",loadStatus:"failed"}:m.pendingBackdrop="dead"
 item={sourceId:m.sourceId,itemId:"one",type:"movie",title:"Film"}
 node={item:item,artCandidates:["dead"],HDPosterUrl:"dead"}
 m.heroItem=item
 '''+script,root=Path(directory))
            return json.loads(output)

    def test_debounce_one_pending_task_and_failed_source_keeps_public_fallback(self):
        result=self.trace('''
 SiloUIArtworkFocus(node):m.now=240:onPublicArtworkTimer():onPublicArtworkTimer()
 before=m.calls.Count():owner=m.calls[0].extra
 data={type:"movie",tmdbId:"1",posterUri:"https://image.tmdb.org/t/p/w342/cover.jpg",backdropUri:"https://image.tmdb.org/t/p/w780/scene.jpg"}
 SiloUIArtworkResult({ok:true,data:data},owner)
 print FormatJson({calls:before,candidates:node.artCandidates,backdrop:m.pendingBackdrop,request:m.calls[0].params})
 ''')
        self.assertEqual(result,dict(calls=1,candidates=['dead','https://image.tmdb.org/t/p/w342/cover.jpg'],backdrop='https://image.tmdb.org/t/p/w780/scene.jpg',request=dict(type='movie',itemId='one',itemType='movie')))

    def test_retiring_focus_prevents_late_reply_and_does_not_start_second_task(self):
        result=self.trace('''
 SiloUIArtworkFocus(node):m.now=240:onPublicArtworkTimer():owner=m.calls[0].extra
 SiloUIArtworkRetire()
 data={type:"movie",tmdbId:"1",posterUri:"https://image.tmdb.org/t/p/w342/cover.jpg",backdropUri:"https://image.tmdb.org/t/p/w780/scene.jpg"}
 SiloUIArtworkResult({ok:true,data:data},owner)
 print FormatJson({calls:m.calls.Count(),candidates:node.artCandidates,backdrop:m.pendingBackdrop,timer:m.publicArtworkTimer.control})
 ''')
        self.assertEqual(result,dict(calls=1,candidates=['dead'],backdrop='dead',timer='stop'))

    def test_profile_change_drops_reply_before_it_can_touch_same_id(self):
        result=self.trace('''
 SiloUIArtworkFocus(node):m.now=240:onPublicArtworkTimer():owner=m.calls[0].extra
 m.profileId="next"
 data={type:"movie",tmdbId:"1",posterUri:"https://image.tmdb.org/t/p/w342/cover.jpg",backdropUri:"https://image.tmdb.org/t/p/w780/scene.jpg"}
 SiloUIArtworkResult({ok:true,data:data},owner)
 print FormatJson({candidates:node.artCandidates,backdrop:m.pendingBackdrop})
 ''')
        self.assertEqual(result,dict(candidates=['dead'],backdrop='dead'))

    def test_home_navigation_and_hero_render_do_not_issue_metadata(self):
        result=self.trace('''
 m.rows={content:invalid}:m.detailItem=invalid
 SiloUIArtworkFocused():m.now=1000:onPublicArtworkTimer()
 print FormatJson({calls:m.calls.Count(),timer:m.publicArtworkTimer.control})
 ''')
        self.assertEqual(result,dict(calls=0,timer='stop'))

    def test_ready_source_poster_stays_visible_when_public_fallback_arrives(self):
        import re
        with tempfile.TemporaryDirectory() as directory:
            source=(ROOT/'components/PosterCard.brs').read_text()
            source=re.sub(r'sub layoutChips\(.*?\nend sub','sub layoutChips()\nend sub',source,count=1,flags=re.S)
            fixture=Path(directory)/'card.brs';fixture.write_text(source)
            output=run_brightscript([ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/core/SiloUIRatingPolicy.brs',fixture],'''
 c={title:"Film",landscape:false,artCandidates:["dead","source"],observeField:sub(a,b)
 end sub,unobserveField:sub(a)
 end sub}
 m.top={itemContent:c,width:150}:m.landscape=false
 m.art={loadStatus:"loading"}:m.fallback={}:m.caption={}:m.chipLeft={}:m.chipRight={}:m.codec={}:m.codecBg={}:m.track={}:m.progress={}
 onContent():m.art.loadStatus="failed":onArt():m.art.loadStatus="ready":onArt()
 c.artCandidates=["dead","source","public"]:onContent()
 print FormatJson({uri:m.art.uri,opacity:m.art.opacity,index:m.artCandidateIndex})
 ''',root=Path(directory))
            self.assertEqual(json.loads(output),dict(uri='source',opacity=1,index=1))

    def test_memory_retires_cache_and_failed_public_backdrop_is_not_retried(self):
        result=self.trace('''
 SiloUIArtworkFocus(node):m.now=240:onPublicArtworkTimer():owner=m.calls[0].extra
 data={type:"movie",tmdbId:"1",posterUri:"https://image.tmdb.org/t/p/w342/cover.jpg",backdropUri:"https://image.tmdb.org/t/p/w780/scene.jpg"}
 SiloUIArtworkResult({ok:true,data:data},owner)
 SiloUIArtworkBackdrop():SiloUIArtworkBackdrop():sets=m.backdropSets
 m.publicArtwork.cache=[{type:"movie"}]:m.memoryHigh=true:SiloUIArtworkRetire()
 print FormatJson({sets:sets,cache:m.publicArtwork.cache.Count(),active:PublicArtworkProjection(m.publicArtwork).active})
 ''')
        self.assertEqual(result,dict(sets=1,cache=0,active=False))

    def test_previous_failure_does_not_replace_pending_source_backdrop(self):
        result=self.trace('''
 SiloUIArtworkFocus(node):m.now=240:onPublicArtworkTimer():owner=m.calls[0].extra
 m.backdrop.uri="previous":m.pendingBackdrop="new-source"
 data={type:"movie",tmdbId:"1",posterUri:"https://image.tmdb.org/t/p/w342/cover.jpg",backdropUri:"https://image.tmdb.org/t/p/w780/scene.jpg"}
 SiloUIArtworkResult({ok:true,data:data},owner)
 print FormatJson({backdrop:m.pendingBackdrop,sets:m.backdropSets})
 ''')
        self.assertEqual(result,dict(backdrop='new-source',sets=0))

    def test_memory_pressure_blocks_late_public_reply_cache_until_recovery(self):
        result=self.trace('''
 item.provider="metadata":item.tmdbId="1":item.catalogId="metadata:movie:1"
 SiloUIArtworkFocus(node):m.now=240:onPublicArtworkTimer():owner=m.calls[0].extra
 m.memoryHigh=true:SiloUIArtworkRetire()
 data={type:"movie",tmdbId:"1",posterUri:"https://image.tmdb.org/t/p/w342/cover.jpg",backdropUri:"https://image.tmdb.org/t/p/w780/scene.jpg"}
 SiloUIArtworkResult({ok:true,data:data},owner)
 blocked={cache:m.publicArtwork.cache.Count(),disabled:m.publicArtwork.disabled,candidates:node.artCandidates}
 m.memoryHigh=false:SiloUIArtworkFocus(node):m.now=480:onPublicArtworkTimer()
 print FormatJson({blocked:blocked,calls:m.calls.Count(),disabled:m.publicArtwork.disabled})
 ''')
        self.assertEqual(result,dict(blocked=dict(cache=0,disabled=True,candidates=['dead']),calls=2,disabled=False))
