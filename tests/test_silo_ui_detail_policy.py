import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'source/core/SiloUIDetailPolicy.brs'
class SiloUIDetailPolicyTests(unittest.TestCase):
    def call(self,name,*args):
        self.assertTrue(POLICY.exists(),'Detail policy missing')
        with tempfile.TemporaryDirectory() as root:
            return run_function([POLICY],name,list(args),root=Path(root))
    def test_episode_actions_keep_resume_restart_and_watched_without_detail(self):
        self.assertEqual(['Resume', 'From beginning', 'Mark unwatched', 'Cancel'],
                         self.scene('print FormatJson(SiloUIEpisodeActionLabels("silo",{itemId:"ep",type:"episode",resumeMs:42213,watched:true},[],""))'))

    def test_episode_resume_restart_and_mark_dispatch_exact_episode(self):
        result=self.render_scene('''m.detailEpisode={item:{itemId:"ep",type:"episode",resumeMs:42000},versions:[],selected:"",audio:invalid,active:true}
 DetailEpisodeChoose("Resume 42s")
 DetailEpisodeChoose("From beginning")
 DetailEpisodeChoose("Mark watched")
 print FormatJson({plays:m.plays,marked:m.marked})''')
        self.assertEqual(dict(plays=[dict(itemId='ep',startMs=42000,version=''),dict(itemId='ep',startMs=0,version='')],marked='ep'),result)

    def test_version_selection_rejects_missing_and_duplicate_ids(self):
        versions=[dict(versionId='a'),dict(versionId='b')]
        self.assertEqual(self.call('SiloUIDetailVersion',versions,'b'),'b')
        self.assertEqual(self.call('SiloUIDetailVersion',versions,''),'a')
        self.assertEqual(self.call('SiloUIDetailVersion',versions,'gone'),'')
        self.assertEqual(self.call('SiloUIDetailVersion',[dict(versionId='b'),dict(versionId='b')],'b'),'')
    def test_auto_version_restores_automatic_play_after_explicit_choice(self):
        actual=self.render_scene('''m.view="detail":m.detailToken=4:m.detailVersionVisit=4
 m.detailVersions=[{versionId:"a"},{versionId:"b"}]
 DetailRender({itemId:"movie",type:"movie"})
 m.detailVersionDialog={buttonSelected:2}
 onDetailVersion()
 DetailAction(0)
 explicit=m.detailSelectedVersion
 m.detailAudioChoice={trackId:"chosen"}:m.detailAudioTicket={}
 m.detailVersionDialog={buttonSelected:0}
 onDetailVersion()
 DetailAction(0)
 print FormatJson({explicit:explicit,selected:m.detailSelectedVersion,audio:m.detailAudioChoice,ticket:m.detailAudioTicket,plays:m.plays})''')
        self.assertEqual(dict(explicit='b',selected='',audio=None,ticket=None,
                             plays=[dict(itemId='movie',startMs=0,version='b'),dict(itemId='movie',startMs=0,version='')]),actual)

    def test_version_cancel_and_stale_visit_preserve_selection(self):
        actual=self.render_scene('''m.view="detail":m.detailToken=4:m.detailVersionVisit=4
 m.detailVersions=[{versionId:"a"},{versionId:"b"}]
 m.detailSelectedVersion="b":m.detailAudioChoice={trackId:"chosen"}
 m.detailVersionDialog={buttonSelected:3}
 onDetailVersion()
 cancelled=[m.detailSelectedVersion,m.detailAudioChoice.trackId]
 m.detailVersionVisit=3:m.detailVersionDialog={buttonSelected:0}
 onDetailVersion()
 print FormatJson([cancelled,[m.detailSelectedVersion,m.detailAudioChoice.trackId]])''')
        self.assertEqual([['b','chosen']]*2,actual)

    def test_auto_and_version_labels_omit_missing_or_invalid_bitrate(self):
        with tempfile.TemporaryDirectory() as root:
            actual=run_function([POLICY,ROOT/'source/core/SiloUIFormat.brs'],'SiloUIDetailVersionLabels',[
                [dict(versionId='a',videoCodec='hevc'),dict(versionId='b',videoCodec='hevc',bitrateKbps='private'),
                 dict(versionId='c',videoCodec='hevc',bitrateKbps=-1),dict(versionId='d',videoCodec='hevc',bitrateKbps=2000000)],''],root=Path(root))
        self.assertEqual(['Auto (selected)','Version 1  ·  HEVC','Version 2  ·  HEVC','Version 3  ·  HEVC','Version 4  ·  HEVC'],actual)

    def test_callbacks_require_live_visit_and_season(self):
        self.assertTrue(self.call('SiloUIDetailCurrent','detail',3,3,2,2))
        self.assertFalse(self.call('SiloUIDetailCurrent','home',3,3,2,2))
        self.assertFalse(self.call('SiloUIDetailCurrent','detail',4,3,2,2))
        self.assertFalse(self.call('SiloUIDetailCurrent','detail',3,3,2,1))
    def test_episode_heading(self):
        self.assertEqual(self.call('SiloUIDetailEpisodeHeading',dict(seasonNumber=2,episodeNumber=4,title='Arrival')),'Selected: S2 · E4 · Arrival')

    def scene(self,script,replace=(),helpers=""):
        from tools.brightscript import run_brightscript
        import json,re
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'components/SiloUIDetail.brs').read_text()+'\n'+(ROOT/'components/SiloUIScene.brs').read_text()
            for name,body in replace:
                source=re.sub(r'(?:sub|function) '+name+r'\(.*?\nend (?:sub|function)',body,source,count=1,flags=re.S)
            fixture=Path(root)/'detail.brs';fixture.write_text(source+'\n'+helpers)
            return json.loads(run_brightscript([POLICY,fixture,ROOT / 'source/core/SiloUIFormat.brs'],script,root=Path(root)))

    def render_scene(self, script):
        return self.scene('''m.provider="silo":m.zone="detailButtons":m.detailVersions=[]:m.detailSelectedVersion=""
 m.detailTitle={}:m.detailLogo={uri:""}:m.detailSub={}:m.detailMeta={}:m.detailQuality={}:m.detailSummary={}
 m.detailRatings={}:m.detailButtons={}:m.backdrop={}:m.backdropOld={}:m.pillGroups={}:m.detailSeasons=[]:m.plays=[]
'''+script, [
            ('DetailMark','sub DetailMark(item as Object)\n m.marked=item.itemId\nend sub'),
            ('DetailLayout','sub DetailLayout()\nend sub'),
            ('DetailCompactRender','sub DetailCompactRender()\nend sub'),
            ('DetailExperimentalProbe','sub DetailExperimentalProbe()\nend sub'),
            ('Toast','sub Toast(message as String)\nend sub'),
            ('BuildButtons','sub BuildButtons(parent as Object,name as String,labels as Object)\n m.rendered=labels\nend sub'),
            ('PaintButtons','sub PaintButtons(name as String,focused as Boolean)\nend sub'),
            ('SetBackdrop','sub SetBackdrop(uri as String)\nend sub'),
        ], helpers='''function RenderRatingChips(group as Object,item as Object) as Integer
 return 0
end function
sub PlayItem(item as Object,startMs as Dynamic,version="" as String,audio=invalid as Dynamic)
 m.plays.Push({itemId:item.itemId,startMs:startMs,version:version})
end sub
''')

    def test_subminute_resume_exposes_resume_and_restart_with_matching_dispatch(self):
        actual=self.render_scene('''DetailRender({itemId:"movie",type:"movie",resumeMs:42213})
 DetailAction(0)
 if m.detailActions[1]="From beginning" then DetailAction(1)
 print FormatJson({labels:m.rendered,plays:m.plays})''')
        self.assertEqual(dict(labels=['Resume 42s','From beginning','Mark watched'],plays=[dict(itemId='movie',startMs=42213,version=''),dict(itemId='movie',startMs=0,version='')]),actual)

    def test_invalid_resume_renders_play_and_starts_at_zero(self):
        actual=self.render_scene('''items=[{itemId:"movie",type:"movie"}]
 for each resume in [invalid,-1,"42213",true,{},[],1000000000000000#]
  items.Push({itemId:"movie",type:"movie",resumeMs:resume})
 end for
 labels=[]
 for each item in items
  DetailRender(item):labels.Push(m.rendered):DetailAction(0)
 end for
 print FormatJson({labels:labels,plays:m.plays})''')
        self.assertEqual(dict(labels=[['Play','Mark watched']]*8,plays=[dict(itemId='movie',startMs=0,version='')]*8),actual)

    def test_zero_long_and_series_resume_labels_preserve_play_targets(self):
        cases=[('movie',0,['Play','Mark watched'],'movie',0),
               ('movie',60000,['Resume 1m','From beginning','Mark watched'],'movie',60000),
               ('movie',75000,['Resume 1m','From beginning','Mark watched'],'movie',75000),
               ('episode',42213,['Resume 42s','From beginning','Mark watched'],'movie',42213),
               ('series',42213,['Play','Mark watched','Shuffle series'],'leaf',-1),
               ('show',75000,['Play','Mark watched','Shuffle series'],'leaf',-1)]
        for kind,resume,labels,target,start in cases:
            with self.subTest(kind=kind,resume=resume):
                actual=self.render_scene('''DetailRender({itemId:"movie",type:"'''+kind+'''",resumeMs:'''+str(resume)+''',playItemId:"leaf"})
 DetailAction(0)
 print FormatJson({labels:m.rendered,plays:m.plays})''')
                self.assertEqual(dict(labels=labels,plays=[dict(itemId=target,startMs=start,version='')]),actual)

    def test_watched_failure_and_stale_callbacks_do_not_mutate(self):
        actual=self.scene('''
            m.toast={}:m.toastTimer={}
            m.view="detail":m.detailToken=4:m.detailItem={itemId:"series"}
            ep={itemId:"ep",watched:false}:m.detailEpisodes=[ep]
            extra={visit:4,item:ep,watched:true}
            DetailResult("detail_mark",{ok:false},{},extra)
            failed=ep.watched
            DetailResult("detail_mark",{ok:true},{},{visit:3,item:ep,watched:true})
            stale=ep.watched
            DetailResult("detail_mark",{ok:true},{},extra)
            print FormatJson([failed,stale,ep.watched])
        ''', [('Toast','sub Toast(message as String)\nend sub')])
        self.assertEqual(actual,[False,False,True])

    def test_episode_focus_preserves_series_identity_and_actions(self):
        actual=self.scene('''
            m.view="detail":m.zone="episodes":m.detailItem={itemId:"series",title:"Series"}
            m.detailActions=["Play"]:m.detailSub={text:"Series"}:m.detailMeta={}:m.detailSummary={text:"Series summary"}
            m.detailCompactTitle={}:m.detailCompactMeta={}:m.detailCompactSummary={}
            onEpisodeFocus()
            print FormatJson({item:m.detailItem,actions:m.detailActions,heading:m.detailCompactTitle.text,summary:m.detailCompactSummary.text,overview:m.detailSummary.text})
        ''', [('DetailFocusedEpisode','function DetailFocusedEpisode() as Dynamic\n return {title:"Arrival",seasonNumber:2,episodeNumber:4,summary:"Episode summary",durationMs:60000}\nend function'),('DetailLayout','sub DetailLayout()\nend sub')])
        self.assertEqual(actual['item']['itemId'],'series')
        self.assertEqual(actual['actions'],['Play'])
        self.assertEqual(actual['summary'],'Episode summary')
        self.assertIn('Arrival',actual['heading'])
        self.assertEqual(actual['overview'],'Series summary')

    def test_old_season_and_closed_detail_results_are_ignored(self):
        actual=self.scene('''
            m.view="detail":m.detailToken=4:m.detailSeasonRequest=2
            m.detailItem={itemId:"series"}:m.detailEpisodes=[{itemId:"keep"}]
            DetailResult("detail_episodes",{ok:true},{items:[]},{visit:4,season:1})
            m.view="home"
            DetailResult("detail_item",{ok:true},{item:{itemId:"wrong"}},4)
            print FormatJson([m.detailItem.itemId,m.detailEpisodes[0].itemId])
        ''')
        self.assertEqual(actual,['series','keep'])

    def test_fresh_version_validation_precedes_playback_allocation(self):
        from tools.brightscript import run_brightscript
        import json,re
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'components/SiloUIPlayer.brs').read_text()
            source += '\n' + re.search(r'(?ms)^function SiloUIPlaybackAdmissionBlocked\(.*?^end function', (ROOT/'components/SiloUIRobustness.brs').read_text()).group(0)
            source=source.replace('sub PlayerShowFailure(', 'sub UnusedPlayerShowFailure(',1)
            source=re.sub(r'    print "Silo play timing.*\n','',source)
            source+='''
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.allocated=params.fileId
 m.request=params
end sub
sub PlayerShowFailure(stage as String, result as Dynamic)
 m.failureStage=stage
end sub
'''
            fixture=Path(root)/'player.brs';fixture.write_text(source)
            output=run_brightscript([POLICY,ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/core/SiloUISettingsPolicy.brs',fixture],'''
                m.provider="silo":m.playToken=1:m.playSelectedVersion="b":m.playStartMs=0:m.playLoading=true
                m.playItem={itemId:"movie"}
                data={versions:[{versionId:"a"},{versionId:"b"}],item:{itemId:"movie"}}
                PlayerResult("play_detail",{ok:true},data,1)
                chosen=m.allocated:m.allocated=""
                data.versions=[{versionId:"a"}]
                PlayerResult("play_detail",{ok:true},data,1)
                print FormatJson([chosen,m.allocated,m.playLoading,m.request.autoVersion,m.request.detail.item.itemId])
            ''',root=Path(root))
        self.assertEqual(json.loads(output),['b','',False,False,'movie'])

    def test_opening_select_is_consumed_before_play_action(self):
        actual=self.scene('''
            m.detailOpeningSelect=true
            m.zone="detailButtons":m.pillGroups={detailButtons:{index:0}}
            m.called=false
            consumed=DetailKey("OK")
            onKeyEvent("OK",false)
            DetailKey("OK")
            print FormatJson([consumed,m.called,m.detailOpeningSelect])
        ''',[('DetailAction','sub DetailAction(index as Integer)\n m.called=true\nend sub')])
        self.assertEqual(actual,[True,True,False])

    def test_selected_version_never_promotes_default_prebuffer(self):
        from tools.brightscript import run_brightscript
        import json,re
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'components/SiloUIPlayer.brs').read_text()
            source += '\n' + re.search(r'(?ms)^function SiloUIPlaybackAdmissionBlocked\(.*?^end function', (ROOT/'components/SiloUIRobustness.brs').read_text()).group(0)
            source += '\n' + re.search(r'(?ms)^function SiloUIOwner\(.*?^end function', (ROOT/'components/SiloUIRobustness.brs').read_text()).group(0)
            for name,body in [('PlayerResetChrome','sub PlayerResetChrome()\nend sub'),('PlayerDiscardPrebuffer','sub PlayerDiscardPrebuffer()\n m.prebuf=invalid\nend sub'),('PlayerStart','sub PlayerStart(plan as Object, preloaded=false as Boolean)\n m.promoted=true\nend sub')]:
                source=re.sub(r'sub '+name+r'\(.*?\nend sub',body,source,count=1,flags=re.S)
            source+='''
sub HomeCacheYield()
end sub
function HomeProgressScope() as String
 return "scope"
end function
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.request=purpose
end sub
sub Toast(message as String)
end sub
function TextOr(value as Dynamic) as String
 if value=invalid then return ""
 return value
end function
'''
            fixture=Path(root)/'player.brs';fixture.write_text(source)
            output=run_brightscript([fixture],'''
                m.provider="silo":m.view="detail":m.playToken=1:m.promoted=false
                m.sourceId="silo:one":m.profileId="profile":m.generation=2:m.pending={}:m.cleanupTickets={}
                m.prebuf={ready:true,itemId:"a",startMs:0,item:{itemId:"a"},plan:{}}
                PlayItem({itemId:"a"},0,"second")
                print FormatJson([m.promoted,m.request,m.playSelectedVersion])
            ''',root=Path(root))
        self.assertEqual(json.loads(output),[False,'play_detail','second'])

    def test_lower_viewport_keeps_header_and_focused_rows_on_screen(self):
        actual=self.scene('''
            m.detailBody={}:m.detailCompact={}:m.detailLowerViewport={}:m.detailLowerContent={}:m.nav={}
            m.pillGroups={}
            m.detailOverviewBottom=420:m.detailSeasonsY=0:m.detailEpisodesY=96:m.detailCastY=334:m.detailSimilarY=522
            result=[]
            for each zone in ["seasons","episodes","detailCast","detailSimilar","detailButtons","nav"]
                m.zone=zone:DetailScroll()
                result.Push({body:m.detailBody.translation,overview:m.detailBody.visible,compact:m.detailCompact.visible,viewport:m.detailLowerViewport.translation,lower:m.detailLowerContent.translation,nav:m.nav.visible})
            end for
            print FormatJson(result)
        ''')
        for index,anchor in enumerate([0,96,334,522]):
            state=actual[index]
            self.assertEqual(state['body'],[56,96])
            self.assertTrue(state['compact'])
            self.assertFalse(state['overview'])
            self.assertTrue(state['nav'])
            self.assertEqual(state['viewport'],[36,284])
            self.assertEqual(state['lower'],[20,-anchor])
        for state in actual[4:]:
            self.assertTrue(state['overview'])
            self.assertFalse(state['compact'])
            self.assertEqual(state['lower'],[20,0])

    def test_season_reveal_applies_translation_and_season_change_clears_episode_display(self):
        actual=self.scene('''
            m.pillGroups={seasons:{index:1,width:1500,pills:[{group:{translation:[0,0]},width:120,label:{text:"First"}},{group:{translation:[1300,0]},width:200,label:{text:"Late"}}]}}
            m.seasonPills={}:m.detailSeasonOffset=0
            DetailRevealSeason()
            translated=m.seasonPills.translation
            m.detailDisplayEpisode={title:"Old episode"}:m.detailItem={itemId:"series",title:"Series",summary:"Series summary"}
            m.detailCompactTitle={}:m.detailCompactMeta={}:m.detailCompactSummary={}
            m.detailSeasonRequest=7:m.detailToken=3:m.detailSeasons=[{}, {seasonNumber:29}]
            m.episodes={}:m.provider="silo"
            DetailLoadSeason(1)
            print FormatJson([translated,m.detailDisplayEpisode,m.detailCompactTitle.text,m.detailCompactSummary.text,m.detailSeasonRequest,m.request])
        ''', [('Api','sub Api(action as String, params as Object, purpose as String, extra as Dynamic)\n m.request=extra\nend sub')])
        self.assertEqual(actual,[[-332,0],None,'Series','Series summary',8,dict(visit=3,season=8)])

    def test_compact_header_has_bounded_text_and_independent_clipped_rows(self):
        import xml.etree.ElementTree as ET
        root=ET.parse(ROOT/'components/SiloUIScene.xml').getroot()
        compact=root.find('.//*[@id="detailCompact"]')
        title=compact.find('./Label[@id="detailCompactTitle"]')
        summary=compact.find('./Label[@id="detailCompactSummary"]')
        self.assertEqual((title.get('height'),title.get('maxLines')),('56','2'))
        self.assertEqual((summary.get('height'),summary.get('maxLines')),('72','3'))
        viewport=root.find('.//*[@id="detailLowerViewport"]')
        self.assertIsNotNone(viewport.find('./Group[@id="detailLowerContent"]'))
        self.assertIsNone(compact.find('.//*[@id="episodes"]'))
        detail=root.find('.//*[@id="detail"]')
        self.assertEqual(detail.find('./Rectangle').get('color'),'0x000000B3')

    def test_season_reveal_contains_first_middle_last_and_return(self):
        widths=[120]*29
        offset=0
        for index in [0,14,28,14,0,28]:
            left=index*132
            offset=self.call('SiloUIDetailSeasonOffset',offset,left,left+widths[index],3816,1168)
            self.assertGreaterEqual(left,offset)
            self.assertLessEqual(left+widths[index],offset+1168)
            self.assertGreaterEqual(offset,0)
            self.assertLessEqual(offset,3816-1168)

    def test_watched_receipt_refreshes_rendered_episode_only_after_success(self):
        actual=self.scene('''
            m.toast={}:m.toastTimer={}:m.view="detail":m.detailToken=4
            m.detailItem={itemId:"series"}
            ep={itemId:"ep",watched:false,resumeMs:40000}:m.detailEpisodes=[ep]
            card={item:{itemId:"ep",watched:false,resumeMs:40000},watched:false,resumeMs:40000}
            m.episodes={content:{getChild:function(index)
                return m.row
            end function}}
            m.episodes.content.row={getChildCount:function()
                return 1
            end function,getChild:function(index)
                return m.card
            end function,card:card}
            extra={visit:4,item:ep,watched:true}
            DetailResult("detail_mark",{ok:false},{},extra)
            failed=card.watched
            DetailResult("detail_mark",{ok:true},{},{visit:3,item:ep,watched:true})
            stale=card.watched
            DetailResult("detail_mark",{ok:true},{},extra)
            print FormatJson([failed,stale,card.watched,card.resumeMs,card.item.watched])
        ''')
        self.assertEqual(actual,[False,False,True,0,True])

    def test_card_observes_confirmed_watched_field_and_hides_progress(self):
        from tools.brightscript import run_brightscript
        import json,re
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT/'source/core/SiloUIFormat.brs').read_text()+'\n'+(ROOT/'components/PosterCard.brs').read_text()
            source=re.sub(r'sub layoutChips\(.*?\nend sub','sub layoutChips()\nend sub',source,count=1,flags=re.S)
            fixture=Path(root)/'card.brs';fixture.write_text(source)
            output=run_brightscript([fixture],'''
                c={landscape:false,title:"Episode",durationMs:100000,resumeMs:40000,watched:false,observeField:function(field,handler)
                    m[field+"Observer"]=handler
                end function,unobserveField:function(field)
                end function}
                m.top={itemContent:c,width:256}:m.landscape=false
                m.art={}:m.fallback={}:m.caption={}:m.chipLeft={}:m.chipRight={}:m.codec={}:m.codecBg={}:m.track={}:m.progress={}
                onContent():before=m.progress.visible
                c.watched=true
                if c.watchedObserver<>invalid then onCardProgress()
                print FormatJson([before,m.progress.visible,c.watchedObserver])
            ''',root=Path(root))
        self.assertEqual(json.loads(output),[True,False,'onCardProgress'])

    def test_landscape_card_uses_poster_when_still_and_backdrop_absent(self):
        from tools.brightscript import run_brightscript
        import json
        with tempfile.TemporaryDirectory() as root:
            source=(ROOT / 'source/core/SiloUIFormat.brs').read_text()+'\n'+(ROOT / 'components/SiloUIScene.brs').read_text().replace('node = CreateObject("roSGNode", "ContentNode")','node = FakeContentNode()')
            source+='''
function FakeContentNode() as Object
 return {addFields:sub(fields)
    for each key in fields
        m[key]=fields[key]
    end for
 end sub}
end function
'''
            fixture=Path(root)/'scene.brs';fixture.write_text(source)
            output=run_brightscript([fixture],'''
                node=ItemNode({title:"Movie",art:{poster:"https://example.test/poster"}},true)
                print FormatJson(node.HDPosterUrl)
            ''',root=Path(root))
        self.assertEqual(json.loads(output),'https://example.test/poster')

    def test_focus_diagnostic_labels_only_allow_fixed_names(self):
        self.assertEqual(self.call_scene_function('SiloUIFocusLabel','nav'),'nav')
        self.assertEqual(self.call_scene_function('SiloUIFocusLabel','https://private.example/title'),'other')
        self.assertEqual(self.call_scene_function('SiloUIFocusLabel','OK'),'OK')

    def call_scene_function(self,name,*args):
        with tempfile.TemporaryDirectory() as root:
            return run_function([ROOT / 'source/core/SiloUIFormat.brs', ROOT / 'components/SiloUIScene.brs'],name,list(args),root=Path(root))

    def test_focus_trace_is_bounded_and_sanitizes_values(self):
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as root:
            output=run_brightscript([ROOT / 'source/core/SiloUIFormat.brs', ROOT / 'components/SiloUIScene.brs'],'''
                m.focusTraceRemaining=1:m.view="private title":m.zone="nav"
                m.top={hasFocus:function()
                    return true
                end function,isInFocusChain:function()
                    return true
                end function}
                SiloUIFocusTrace("zoneAfter","private URL")
                SiloUIFocusTrace("zoneAfter","nav")
            ''',root=Path(root))
        self.assertEqual(output.strip(),'SiloUI focus stage=zoneAfter input=other view=other zone=nav topFocus=true topChain=true')
