"""Artwork failures use bounded same-item images independently of video capabilities."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import run_function, run_brightscript
ROOT=Path(__file__).resolve().parents[1]

class SiloUIArtworkRecoveryTests(unittest.TestCase):
    def test_card_candidates_are_same_item_images_for_dv_hdr_and_sdr(self):
        with tempfile.TemporaryDirectory() as directory:
            for hdr in ['DV', 'HDR10', 'SDR']:
                item={'title':'Film','type':'movie','badges':{'hdr':hdr}}
                art={'poster':'/poster','backdrop':'/backdrop','still':'/still'}
                result=run_function([ROOT/'source/core/SiloUIFormat.brs'],'SiloUIItemFields',[item,art,False,'https://server.test'],root=Path(directory))
                self.assertEqual(result['artCandidates'],['https://server.test/poster','https://server.test/still','https://server.test/backdrop'])
    def test_episode_portraits_use_loaded_series_cover_and_keep_landscape_stills(self):
        with tempfile.TemporaryDirectory() as directory:
            source=ROOT/'source/core/SiloUIFormat.brs'
            episode={'sourceId':'silo','itemId':'ep','seriesId':'series','type':'episode','title':'Episode'}
            art={'poster':'/episode-still','still':'/episode-still','backdrop':'/scene'}
            rows=[{'items':[{'sourceId':'silo','itemId':'series','type':'series','art':{'poster':'/series-cover'}}]}]
            posters=run_function([source],'SiloUISeriesPosters',[rows],root=Path(directory))
            portrait=run_function([source],'SiloUIEpisodePortraitArt',[episode,art,posters],root=Path(directory))
            fields=run_function([source],'SiloUIItemFields',[episode,portrait,False,'https://server.test'],root=Path(directory))
            self.assertEqual(fields['artCandidates'],['https://server.test/series-cover'])
            landscape=run_function([source],'SiloUIItemFields',[episode,art,True,'https://server.test'],root=Path(directory))
            self.assertEqual(landscape['artCandidates'],['https://server.test/episode-still','https://server.test/scene'])
            episode['sourceId']='other'
            missing=run_function([source],'SiloUIEpisodePortraitArt',[episode,art,posters],root=Path(directory))
            self.assertEqual(missing,{})

    def test_episode_without_loaded_parent_uses_only_verified_non_still_poster(self):
        with tempfile.TemporaryDirectory() as directory:
            source=ROOT/'source/core/SiloUIFormat.brs'
            episode={'sourceId':'silo','seriesId':'missing','type':'episode','title':'Episode'}
            for flag in (False,True,None):
                art={'poster':'/cover','still':'/frame','backdrop':'/scene'}
                if flag is not None:
                    art['posterIsEpisodeStill']=flag
                portrait=run_function([source],'SiloUIEpisodePortraitArt',[episode,art,{}],root=Path(directory))
                fields=run_function([source],'SiloUIItemFields',[episode,portrait,False,'https://server.test'],root=Path(directory))
                self.assertEqual(fields['artCandidates'],['https://server.test/cover'] if flag is False else [])
            art['posterIsEpisodeStill']=False
            portrait=run_function([source],'SiloUIEpisodePortraitArt',[episode,art,{'silo':{'missing':'/parent'}}],root=Path(directory))
            self.assertEqual(portrait,{'poster':'/parent','posterFallback':'/cover'})

    def test_parent_cover_retries_only_a_distinct_verified_child_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            source=ROOT/'source/core/SiloUIFormat.brs'
            episode={'sourceId':'silo','seriesId':'series','type':'episode','title':'Episode'}
            parents={'silo':{'series':'/parent'}}
            for flag, child, expected in [(False,'/child',['https://server.test/parent','https://server.test/child']),
                                          (False,'/parent',['https://server.test/parent']),
                                          (False,'https://server.test/parent',['https://server.test/parent']),
                                          (True,'/frame',['https://server.test/parent']),
                                          (None,'/unknown',['https://server.test/parent'])]:
                art={'poster':child,'still':'/frame','backdrop':'/scene'}
                if flag is not None:
                    art['posterIsEpisodeStill']=flag
                portrait=run_function([source],'SiloUIEpisodePortraitArt',[episode,art,parents],root=Path(directory))
                fields=run_function([source],'SiloUIItemFields',[episode,portrait,False,'https://server.test'],root=Path(directory))
                self.assertEqual(fields['artCandidates'],expected)

    def test_episode_parent_failure_displays_child_cover_then_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            source=(ROOT/'components/PosterCard.brs').read_text()
            source=re.sub(r'sub layoutChips\(.*?\nend sub','sub layoutChips()\nend sub',source,count=1,flags=re.S)
            fixture=Path(directory)/'card.brs';fixture.write_text(source)
            result=json.loads(run_brightscript([ROOT/'source/core/SiloUIFormat.brs',fixture],'''
                item={sourceId:"silo",seriesId:"series",type:"episode",title:"Episode"}
                art=SiloUIEpisodePortraitArt(item,{poster:"/child",posterIsEpisodeStill:false,still:"/frame",backdrop:"/scene"},{silo:{series:"/parent"}})
                c=SiloUIItemFields(item,art,false,"https://server.test")
                c.observeField=sub(a,b)
                end sub
                c.unobserveField=sub(a)
                end sub
                m.top={itemContent:c,width:150}:m.landscape=false
                m.art={loadStatus:"loading"}:m.fallback={}:m.caption={}:m.chipLeft={}:m.chipRight={}:m.codec={}:m.codecBg={}:m.track={}:m.progress={}
                onContent():first=m.art.uri
                m.art.loadStatus="failed":onArt():second=m.art.uri
                m.art.loadStatus="ready":onArt():shown=m.art.opacity=1 and not m.fallback.visible
                m.art.loadStatus="failed":onArt():onArt()
                print FormatJson({first:first,second:second,shown:shown,last:m.art.uri,fallback:m.fallback.visible})
            ''',root=Path(directory)))
            self.assertEqual(result,dict(first='https://server.test/parent',second='https://server.test/child',shown=True,last='https://server.test/child',fallback=True))

    def test_shipping_card_binding_rejects_stale_profile_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            source=(ROOT/'components/SiloUIScene.brs').read_text()
            binding=source[source.index('function ItemNode('):source.index('function ArtField(')]
            fixture=Path(directory)/'binding.brs'
            fixture.write_text(binding+"""
function HomeProgressScope()
    return m.profileId
end function
function ItemArt(item)
    return item.art
end function
""")
            result=json.loads(run_brightscript([ROOT/'source/core/SiloUIFormat.brs',fixture],'''
                m.provider="silo":m.profileId="first":m.baseUrl="https://server.test"
                m.seriesPostersScope="first":m.seriesPosters={silo:{series:"/cover"}}
                item={sourceId:"silo",itemId:"ep",seriesId:"series",type:"episode",title:"Episode",art:{poster:"/still",still:"/still"}}
                first=ItemNode(item):m.profileId="second":second=ItemNode(item)
                print FormatJson({first:first.artCandidates,second:second.artCandidates})
            ''',root=Path(directory)))
            self.assertEqual(result,{'first':['https://server.test/cover'],'second':[]})

    def test_card_failure_advances_and_stops_without_repeating_images(self):
        with tempfile.TemporaryDirectory() as directory:
            source=(ROOT/'components/PosterCard.brs').read_text()
            source=re.sub(r'sub layoutChips\(.*?\nend sub','sub layoutChips()\nend sub',source,count=1,flags=re.S)
            fixture=Path(directory)/'card.brs';fixture.write_text(source)
            output=run_brightscript([ROOT/'source/core/SiloUIFormat.brs',fixture],'''
                c={title:"DV film",landscape:false,HDPosterUrl:"https://server.test/poster",artCandidates:["https://server.test/poster","https://server.test/backdrop"],observeField:sub(a,b)
                end sub,unobserveField:sub(a)
                end sub}
                m.top={itemContent:c,width:150}:m.landscape=false
                m.art={loadStatus:"loading"}:m.fallback={}:m.caption={}:m.chipLeft={}:m.chipRight={}:m.codec={}:m.codecBg={}:m.track={}:m.progress={}
                onContent():uris=[m.art.uri]
                m.art.loadStatus="failed":onArt():uris.Push(m.art.uri)
                m.art.loadStatus="ready":onArt():shown=m.art.opacity=1 and not m.fallback.visible
                onContent():retained=m.art.uri
                m.art.loadStatus="failed":onArt():uris.Push(m.art.uri)
                onArt():uris.Push(m.art.uri)
                CardBindContent(false):layoutRetained=m.art.uri
                c2={title:"DV film",landscape:false,HDPosterUrl:"https://server.test/poster",artCandidates:["https://server.test/poster","https://server.test/backdrop"],observeField:sub(a,b)
                end sub,unobserveField:sub(a)
                end sub}
                m.top.itemContent=c2:onContent():rebound=m.art.uri
                print FormatJson({uris:uris,shown:shown,retained:retained,layoutRetained:layoutRetained,rebound:rebound,fallback:m.fallback.visible})
            ''',root=Path(directory))
            result=json.loads(output)
            self.assertEqual(result,dict(uris=['https://server.test/poster','https://server.test/backdrop','https://server.test/backdrop','https://server.test/backdrop'],shown=True,retained='https://server.test/backdrop',layoutRetained='https://server.test/backdrop',rebound='https://server.test/poster',fallback=True))


class SiloUIBackdropOwnershipTests(unittest.TestCase):
    def backdrop(self, script):
        with tempfile.TemporaryDirectory() as directory:
            source=(ROOT/'components/SiloUIScene.brs').read_text()
            source=source[source.index("function BackdropOwner()"):source.index("sub Api(")]
            fixture=Path(directory)/'backdrop.brs';fixture.write_text(source)
            return json.loads(run_brightscript([ROOT/'source/core/SiloUIFormat.brs',fixture],'''
                m.provider="silo":m.sourceId="source":m.profileId="profile":m.generation=1
                m.view="home":m.heroItem={itemId:"first"}:m.detailItem={itemId:"second"}
                m.backdrop={uri:"",opacity:0,loadStatus:"loading"}
                m.backdropOld={uri:"",opacity:0}:m.backdropFade={control:"stop"}:m.backdropTimer={control:"stop"}
            '''+script,root=Path(directory)))

    def test_different_title_clears_visible_art_before_debounced_load(self):
        result=self.backdrop('''
            SetBackdrop("first-art"):onBackdropTimer():m.backdrop.loadStatus="ready":onBackdropLoaded()
            m.backdrop.opacity=1:m.view="detail":SetBackdrop("second-art")
            print FormatJson({uri:m.backdrop.uri,old:m.backdropOld.uri,opacity:m.backdrop.opacity,fade:m.backdropFade.control})
        ''')
        self.assertEqual(result,dict(uri='',old='',opacity=0,fade='stop'))

    def test_late_ready_after_title_or_profile_change_cannot_start_fade(self):
        result=self.backdrop('''
            SetBackdrop("first-art"):onBackdropTimer()
            m.heroItem={itemId:"next"}:SetBackdrop("next-art")
            m.backdrop.loadStatus="ready":onBackdropLoaded()
            titleFade=m.backdropFade.control
            onBackdropTimer():m.profileId="other":onBackdropLoaded()
            print FormatJson({titleFade:titleFade,profileFade:m.backdropFade.control,old:m.backdropOld.uri})
        ''')
        self.assertEqual(result,dict(titleFade='stop',profileFade='stop',old=''))

    def test_same_title_replacement_keeps_loaded_art_and_failure_does_not_reveal_failed_image(self):
        result=self.backdrop('''
            SetBackdrop("first-art"):onBackdropTimer():m.backdrop.loadStatus="ready":onBackdropLoaded():m.backdrop.opacity=1
            SetBackdrop("better-art"):onBackdropTimer()
            retained=m.backdropOld.uri
            m.backdrop.loadStatus="failed":onBackdropLoaded()
            print FormatJson({retained:retained,oldOpacity:m.backdropOld.opacity,opacity:m.backdrop.opacity,fade:m.backdropFade.control})
        ''')
        self.assertEqual(result,dict(retained='first-art',oldOpacity=1,opacity=0,fade='stop'))

    def test_refocus_retries_failed_same_image_once_and_new_owner_gets_its_own_retry(self):
        result=self.backdrop('''
            SetBackdrop("first-art"):onBackdropTimer()
            m.backdrop.loadStatus="failed":onBackdropLoaded()
            SetBackdrop("first-art"):cleared=m.backdrop.uri
            onBackdropTimer():retried=m.backdrop.uri
            m.backdrop.loadStatus="failed":onBackdropLoaded()
            SetBackdrop("first-art"):exhausted=m.backdrop.uri
            onBackdropTimer()
            m.heroItem={itemId:"next"}:SetBackdrop("first-art"):onBackdropTimer()
            m.backdrop.loadStatus="failed":onBackdropLoaded()
            SetBackdrop("first-art"):nextCleared=m.backdrop.uri
            onBackdropTimer()
            print FormatJson({cleared:cleared,retried:retried,exhausted:exhausted,nextCleared:nextCleared,nextUri:m.backdrop.uri,opacity:m.backdrop.opacity,fade:m.backdropFade.control})
        ''')
        self.assertEqual(result,dict(cleared='',retried='first-art',exhausted='first-art',nextCleared='',nextUri='first-art',opacity=0,fade='stop'))

    def test_empty_art_cancels_pending_load_and_ready_cannot_restore_old_title(self):
        result=self.backdrop('''
            SetBackdrop("first-art"):onBackdropTimer():m.backdrop.loadStatus="ready":onBackdropLoaded():m.backdrop.opacity=1
            m.view="detail":SetBackdrop(""):onBackdropTimer():onBackdropLoaded()
            print FormatJson({uri:m.backdrop.uri,old:m.backdropOld.uri,opacity:m.backdrop.opacity,fade:m.backdropFade.control,timer:m.backdropTimer.control})
        ''')
        self.assertEqual(result,dict(uri='',old='',opacity=0,fade='stop',timer='stop'))
