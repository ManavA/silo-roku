import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'source/core/SiloUIPlexPolicy.brs'
class SiloUIPlexPolicyTests(unittest.TestCase):
 def call(self,name,*args):
  self.assertTrue(POLICY.exists(),'Plex policy missing')
  with tempfile.TemporaryDirectory() as root:
   return run_function([POLICY],name,list(args),root=Path(root))
 def test_artwork_is_server_relative_and_token_free(self):
  self.assertEqual(self.call('SiloUIPlexArt','https://server.example','/library/metadata/1/thumb/2','poster'),'https://server.example/photo/:/transcode?width=300&height=450&url=%2Flibrary%2Fmetadata%2F1%2Fthumb%2F2')
  for key in ['https://other.example/image','//other/image','/image?X-Plex-Token=secret','/image#fragment']:
   self.assertEqual(self.call('SiloUIPlexArt','https://server.example',key,'poster'),'')
 def test_library_section_and_sort(self):
  sections=[dict(sectionId='1',type='show'),dict(sectionId='2',type='movie')]
  self.assertEqual(self.call('SiloUIPlexSection',sections,'series'),'1')
  self.assertEqual(self.call('SiloUIPlexSection',sections,'movie'),'2')
  self.assertEqual(self.call('SiloUIPlexSort','added_at','desc'),'addedAt:desc')
 def test_episode_children_use_season_identity(self):
  self.assertEqual(self.call('SiloUIPlexChildren',dict(itemId='20'),60,0),dict(itemId='20',limit=60,offset=0))
 def test_reports_include_timeline_and_transcode_identity(self):
  actual=self.call('SiloUIPlexReport',dict(itemId='1',durationMs=9000,transcodeSessionId='session'),2000,True)
  self.assertEqual(actual,dict(itemId='1',durationMs=9000,positionMs=2000,state='paused',transcodeSessionId='session'))

 def scene(self,component,script,replacements=()):
  import re,json
  from tools.brightscript import run_brightscript
  with tempfile.TemporaryDirectory() as root:
   source=(ROOT/'components'/component).read_text()+'\n'+(ROOT / 'source/core/SiloUIFormat.brs').read_text()+'\n'+(ROOT / 'components/SiloUIScene.brs').read_text()
   if component=='SiloUIOnboarding.brs': source+='\n'+(ROOT/'components/SiloUIHome.brs').read_text()
   for name,body in replacements:
    source=re.sub(r'(?:sub|function) '+name+r'\(.*?\nend (?:sub|function)',body,source,count=1,flags=re.S)
   fixture=Path(root)/'scene.brs';fixture.write_text(source)
   return json.loads(run_brightscript([ROOT/'components/SiloUIRobustness.brs',ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'source/core/SiloPlaybackPolicy.brs',POLICY,ROOT/'source/core/SiloUISettingsPolicy.brs',ROOT/'source/core/SiloUIDetailPolicy.brs',ROOT/'source/core/SiloUIPlayerPolicy.brs',fixture],script,root=Path(root)).splitlines()[-1])
 def test_search_dispatches_plex_query(self):
  self.assertEqual(self.scene('SiloUILibrary.brs','''
   m.provider="plex":m.sourceId="plex:synthetic-server":m.profileId="profile-1":m.generation=1
   m.view="search":m.zone="keyboard":m.keyboard={text:""}:m.searchToken=0:m.searchGrid={}:m.searchHint={}:m.searchTimer={}
   m.keyboard.text="Arrival"
   onSearchText()
   onSearchTimer()
   print FormatJson(m.sent)
  ''',[('Api','sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)\n m.sent={action:action,params:params,purpose:purpose}\nend sub')]),dict(action='search',params=dict(query='Arrival',limit=36),purpose='search_results'))
 def test_player_start_uses_fresh_detail_and_selected_version(self):
  actual=self.scene('SiloUIPlayer.brs','''
   m.provider="plex":m.playToken=4:m.playClock=CreateObject("roTimespan")
   m.playItem={itemId:"10"}
   m.playSelectedVersion="v2":m.playStartMs=-1
   data={item:{itemId:"10",resumeMs:1234},versions:[{versionId:"v1"},{versionId:"v2"}],markers:[]}
   PlayerResult("play_detail",{ok:true},data,4)
   print FormatJson(m.sent)
  ''',[('Api','sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)\n m.sent={action:action,params:params}\nend sub')])
  self.assertEqual(actual['action'],'playback_start')
  self.assertEqual({k.lower():v for k,v in actual['params'].items()}['versionindex'],1)
  self.assertEqual(actual['params']['detail']['item']['itemId'],'10')
  self.assertEqual(actual['params']['startPositionMs'],1234)
  self.assertNotIn('fileId',actual['params'])
 def test_home_rows_keep_continue_and_section_identity(self):
  actual=self.scene('SiloUIHome.brs','''
   m.plexPending=1:m.plexRows={"Continue Watching":{items:[{itemId:"one"}]},"On Deck":{items:[{itemId:"two"}]}}
   m.plexSections=[{sectionId:"7",title:"Movies"}]:m.plexRecent={"7":{items:[{itemId:"three"}]}}
   HomePlexMaybeDone()
   print FormatJson(m.captured)
  ''',[('HomeSetRows','sub HomeSetRows(rows as Object)\n m.captured=rows\nend sub')])
  self.assertEqual([row['sectionType'] for row in actual],['continue_watching','on_deck','recently_added'])
  self.assertEqual(actual[2]['rowId'],'plex_recent_7')
 def test_image_context_boundary_and_stale_revision(self):
  import re
  source=(ROOT/'components/ApiTask.brs').read_text()
  source=re.sub(r'function TaskPlexImageHolder\(.*?\nend function', '''function TaskPlexImageHolder(token as String) as Object
   m.receivedToken=token
   return {nativeHolder:true}
end function''',source,count=1,flags=re.S)
  boundary='''
function SessionRevision(provider as String) as Integer
 return m.revision
end function
function CheckImageContext() as Object
 m.top={}:m.revision=3
 session={baseUrl:"https://server.example",token:"private",local:false}
 good=TaskPlexImageContext(session,3)
 published=m.top.imageHolder
 m.top={}
 stale=TaskPlexImageContext(session,2)
 stalePublished=m.top.imageHolder<>invalid
 missing=TaskPlexImageContext({baseUrl:"https://server.example"},3)
 return {good:good,published:published,stale:stale,stalePublished:stalePublished,missing:missing}
end function
'''
  with tempfile.TemporaryDirectory() as root:
   fixture=Path(root)/'task.brs';fixture.write_text(source+'\n'+boundary)
   actual=run_function([ROOT/'source/adapters/PlexAdapter.brs',fixture],'CheckImageContext',[],root=Path(root))
  self.assertEqual(actual['good'],dict(ok=True,data=dict(imageBaseUrl='https://server.example')))
  self.assertEqual(actual['published'],dict(nativeHolder=True))
  self.assertEqual(actual['stale']['errorCode'],'session_changed')
  self.assertFalse(actual['stalePublished'])
  self.assertEqual(actual['missing']['errorCode'],'auth_required')
 def test_stale_image_result_never_reads_native_holder(self):
  actual=self.scene('SiloUILibrary.brs','''
   m.generation=2:m.provider="silo"
   task={unobserveField:function(name as String) as Boolean
    return true
   end function}
   m.pending={"1":{generation:1,purpose:"home_image_context",task:task}}
   event={getData:function() as Object
    return {requestId:1,ok:true,data:{imageBaseUrl:"https://old.example"}}
   end function}
   onApiResult(event)
   print FormatJson({pending:m.pending.Count(),provider:m.provider})
  ''')
  self.assertEqual(actual,dict(pending=0,provider='silo'))
 def test_plex_watched_actions(self):
  actual=self.scene('SiloUIDetail.brs','''
   m.provider="plex":m.detailToken=2:m.detailMarkPending=false
   DetailMark({itemId:"10",watched:false})
   first=m.sent.action:m.detailMarkPending=false
   DetailMark({itemId:"10",watched:true})
   print FormatJson([first,m.sent.action])
  ''',[('Api','sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)\n m.sent={action:action}\nend sub')])
  self.assertEqual(actual,['scrobble','unscrobble'])
 def test_plex_next_episode_uses_native_series_identity(self):
  with tempfile.TemporaryDirectory() as root:
   item=dict(type='episode',sourceId='plex:one',seriesItemId='show',seasonNumber=1,episodeNumber=1,itemId='a')
   next_item=dict(item,episodeNumber=2,itemId='b')
   actual=run_function([ROOT/'source/core/SiloUIPlayerPolicy.brs'],'SiloUIPlayerNext',[item,[next_item]],root=Path(root))
  self.assertEqual(actual,next_item)
 def test_plex_children_paging_keeps_visit_and_season_fence(self):
  actual=self.scene('SiloUIDetail.brs','''
   m.provider="plex":m.view="detail":m.detailToken=1:m.detailSeasonRequest=2:m.detailEpisodes=[]:m.detailItem={itemId:"show"}
   extra={visit:1,season:2,itemId:"30"}
   DetailResult("detail_episodes",{ok:true},{items:[{itemId:"a"}],hasMore:true,nextOffset:100},extra)
   DetailResult("detail_episodes",{ok:true},{items:[{itemId:"stale"}],hasMore:true,nextOffset:200},{visit:1,season:1,itemId:"30"})
   print FormatJson({sent:m.sent,items:m.detailEpisodes})
  ''',[('Api','sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)\n m.sent={action:action,params:params,extra:extra}\nend sub')])
  self.assertEqual(actual['sent'],dict(action='children',params=dict(itemId='30',offset=100,limit=100),extra=dict(visit=1,season=2,itemId='30')))
  self.assertEqual(actual['items'],[dict(itemId='a')])

 def test_cancel_source_picker_restores_cleared_home(self):
  actual=self.scene('SiloUIOnboarding.brs','''
   m.provider="plex":m.sourceId="plex:one":m.obImagesCleared=true
   handled=OnboardingKey("back")
   print FormatJson({handled:handled,reloaded:m.reloaded,cleared:m.obImagesCleared})
  ''',[('HomeLoad','sub HomeLoad(skipImages=false as Boolean)\n m.reloaded=true\nend sub'),('ShowView','sub ShowView(name as String)\nend sub'),('SetZone','sub SetZone(name as String)\nend sub')])
  self.assertEqual(actual,dict(handled=True,reloaded=True,cleared=False))

 def test_plex_hero_episode_fetches_its_own_season(self):
  actual=self.scene('SiloUIPlayer.brs','''
   m.provider="plex":m.playToken=3:m.detailEpisodes=[]:m.view="home":m.zone="heroButtons"
   m.playItem={itemId:"a",type:"episode",sourceId:"plex:one",seriesItemId:"show",seasonItemId:"season",seasonNumber:1,episodeNumber:1}
   m.video={setFocus:function(flag as Boolean) as Boolean
    return true
   end function}
   m.top={findNode:function(id as String) as Object
    return {}
   end function}
   m.nav={}:m.toast={}:m.progressTimer={}
   PlayerStart({},true)
   print FormatJson(m.sent)
  ''',[('Api','sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)\n m.sent={action:action,params:params,token:extra}\nend sub'),('onPlayerTracks','sub onPlayerTracks()\nend sub'),('PlayerUpdateNativeActions','sub PlayerUpdateNativeActions(cue as Object)\nend sub'),('PlayerCurrentCue','function PlayerCurrentCue() as Object\n return {}\nend function')])
  self.assertEqual(actual,dict(action='children',params=dict(itemId='season',limit=100),token=3))
