import json
import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'source/core/SiloUIAudioPolicy.brs'
ADAPTER=ROOT/'source/adapters/SiloAudioAdapter.brs'
SILO=ROOT/'source/adapters/SiloAdapter.brs'
class AudioTests(unittest.TestCase):
 def call(self,name,*args):
  with tempfile.TemporaryDirectory() as d:
   return run_function([POLICY,SILO,ADAPTER],name,list(args),root=Path(d))
 def test_audio_part_start_keeps_book_progress_client_owned_even_at_zero(self):
  session={'profileId':'profile'}
  caps={'video_evidence':'declared','audio_evidence':'platform_attested','codecs_video':[],'codecs_video_hardware':[],'codecs_audio':['mp3'],'containers':['mp3']}
  context={'protocol_version':3,'device':{'platform':'roku'},'deliveries':{},'output':{}}
  params={'fileId':'part-2','installationId':'install','playbackAttemptId':'attempt','clientCapabilities':caps,'clientPlaybackContext':context,'startPositionMs':0,'progressPersistence':'client','allowAlternateVersions':False}
  body=self.call('SiloStartBody',session,params)['body']
  self.assertEqual(body['start_position'],0)
  self.assertEqual(body['progress_persistence'],'client')
  del params['startPositionMs']
  self.assertEqual(self.call('SiloStartBody',session,params)['errorCode'],'invalid_request')
 def test_book_resume_maps_global_to_part_without_changing_session_clock(self):
  queue=[{'fileId':'p1','durationMs':60000,'offsetMs':0},{'fileId':'p2','durationMs':90000,'offsetMs':60000}]
  self.assertEqual(self.call('SiloUIAudioTarget',queue,75000),{'index':1,'localMs':15000,'globalMs':75000})
  self.assertEqual(self.call('SiloUIAudioTarget',queue,60000)['index'],1)
  self.assertEqual(self.call('SiloUIAudioGlobal',queue,1,17000),77000)
  self.assertEqual(self.call('SiloUIAudioTarget',queue,999999)['localMs'],89000)
 def detail(self):
  def file(id,duration):return {'file_id':id,'duration':duration,'codec_video':'','codec_audio':'mp3','container':'mp3','chapters':[{'start_seconds':0,'end_seconds':20,'title':'Opening'}]}
  return {'content_id':'audiobook:book','type':'audiobook','title':'A book','user_data':{'position_seconds':75},'playback_variants':[{'variant_id':'v','part_count':2,'parts':[{'part_index':1,'default_file_id':'p1','versions':[file('p1',60)]},{'part_index':2,'default_file_id':'p2','versions':[file('p2',90)]}]}]}
 def test_detail_creates_complete_ordered_bounded_parts_and_chapters(self):
  r=self.call('SiloAudioDetail',self.detail(),'silo:fixture','audiobook:book')
  self.assertTrue(r['ok'])
  self.assertEqual([p['offsetMs'] for p in r['data']['queue']],[0,60000])
  self.assertEqual(r['data']['resumeMs'],75000)
  self.assertEqual(r['data']['durationMs'],150000)
  bad=self.detail();bad['playback_variants'][0]['part_count']=3
  self.assertFalse(self.call('SiloAudioDetail',bad,'silo:fixture','audiobook:book')['ok'])
  bad=self.detail();bad['content_id']='audiobook:other'
  self.assertFalse(self.call('SiloAudioDetail',bad,'silo:fixture','audiobook:book')['ok'])
 def test_whole_book_sync_uses_milliseconds_and_requires_matching_success_receipt(self):
  session={'baseUrl':'https://fixture.example','accessToken':'fixture','profileId':'p'}
  req=self.call('BuildSiloAudioRequest','audio_sync',session,{'itemId':'audiobook:book','positionMs':75000,'durationMs':150000})
  self.assertTrue(req['ok'])
  self.assertTrue(req['url'].endswith('/sync/progress'))
  self.assertEqual(json.loads(req['body']),{'items':[{'media_item_id':'audiobook:book','position_ms':75000,'duration_ms':150000}]})
  self.assertTrue(self.call('SiloAudioSyncReceipt',{'items':[{'index':0,'media_item_id':'audiobook:book','status':'success'}]},'audiobook:book'))
  self.assertFalse(self.call('SiloAudioSyncReceipt',{'items':[{'index':0,'media_item_id':'other','status':'success'}]},'audiobook:book'))
  self.assertFalse(self.call('SiloAudioSyncReceipt',{'items':[{'index':0,'media_item_id':'audiobook:book','status':'failure'}]},'audiobook:book'))
 def test_audio_plan_pins_original_file_and_rejects_video_remux_or_foreign_credentials(self):
  session={'baseUrl':'https://fixture.example','accessToken':'fixture','profileId':'p'}
  part={'fileId':'p2','container':'mp3','codec':'mp3','durationMs':90000}
  raw={'protocol_version':3,'outcome':'plan','session_id':'lease','playback_plan':{'session_id':'lease','plan_id':'plan','plan_attempt_key':'attempt','requested_media_file_id':'p2','effective_media_file_id':'p2','delivery':'original_http','source':{'media_file_id':'p2','video_codec':'','audio_codec':'mp3'},'stream':{'url':'/api/v2/stream/lease','protocol':'http_progressive','container':'mp3','header_refresh':'none','headers':{}},'timeline':{'player_start_seconds':15,'timeline_offset_seconds':0,'can_seek_anywhere':True}}}
  result=self.call('SiloAudioPlan',raw,session,part,15000)
  self.assertTrue(result['ok'])
  self.assertEqual(result['streamFormat'],'mp3')
  self.assertIn('Authorization',result['headers'])
  raw['playback_plan']['stream']['url']='https://cdn.example/signed'
  result=self.call('SiloAudioPlan',raw,session,part,15000)
  self.assertNotIn('Authorization',result['headers'])
  raw['playback_plan']['delivery']='server_remux_progressive'
  self.assertFalse(self.call('SiloAudioPlan',raw,session,part,15000)['ok'])
 def test_audio_only_formats_never_inherit_video_codec_claims(self):
  self.assertEqual(self.call('SiloAudioFormat','aac','m4b'),'mp4')
  self.assertEqual(self.call('SiloAudioFormat','aac','aac'),'es.aac-adts')
  self.assertEqual(self.call('SiloAudioFormat','truehd','mkv'),'')
 def test_audio_node_and_worker_are_in_shipping_namespaces(self):
  import xml.etree.ElementTree as ET
  scene=ET.parse(ROOT/'components/SiloUIScene.xml').getroot()
  self.assertIsNotNone(scene.find('.//Audio[@id="audioNode"]'))
  scripts=[s.attrib['uri'] for s in scene.findall('script')]
  self.assertIn('pkg:/components/SiloUIAudio.brs',scripts)
  task=ET.parse(ROOT/'components/ApiTask.xml').getroot()
  self.assertIn('pkg:/components/TaskSiloAudio.brs',[s.attrib['uri'] for s in task.findall('script')])
 def test_worker_hides_audio_when_capability_denies_and_filters_permitted_libraries(self):
  from tools.brightscript import run_brightscript
  with tempfile.TemporaryDirectory() as d:
   stub=Path(d)/'boundary.brs';stub.write_text('''
function SessionRevision(provider as String) as Integer
 return 1
end function
function HttpRequest(request as Object,timeout as Integer) as Object
 if Instr(1,request.url,"/playback/capabilities") > 0
  return {ok:true,body:FormatJson({state:"available",allowed:m.allowed,protocol_versions:[3]})}
 end if
 return {ok:true,body:FormatJson({items:[{id:"video",name:"Movies",type:"movies"},{id:"books",name:"Books",type:"audiobooks"}]})}
end function
''')
   out=run_brightscript([POLICY,SILO,ADAPTER,ROOT/'components/ApiTask.brs',ROOT/'components/TaskSiloAudio.brs',stub],'''
    session={baseUrl:"https://fixture.example",accessToken:"fixture",profileId:"p",sourceId:"silo:test"}
    scope={sourceId:"silo:test",profileId:"p"}
    m.allowed=false
    denied=TaskAudioAction(session,"audio_libraries",{},scope,1)
    m.allowed=true
    allowed=TaskAudioAction(session,"audio_libraries",{},scope,1)
    print FormatJson({denied:denied,allowed:allowed})
   ''',root=Path(d))
  r=json.loads(out)
  self.assertFalse(r['denied']['ok'])
  self.assertEqual(r['allowed']['data']['entries'],[{'id':'books','title':'Books'}])
 def test_native_timer_stops_sleep_and_waits_for_cleanup_before_next_part(self):
  from tools.brightscript import run_brightscript
  import re
  with tempfile.TemporaryDirectory() as d:
   source=(ROOT/'components/SiloUIAudio.brs').read_text()
   source=re.sub(r'sub SiloUIAudioRelease\(.*?\nend sub','sub SiloUIAudioRelease()\n m.released=true\nend sub',source,count=1,flags=re.S)
   p=Path(d)/'audio.brs';p.write_text(source)
   stub=Path(d)/'boundary.brs';stub.write_text('''
function HomeProgressScope() as String
 return "owner"
end function
sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.sent=action
end sub
''')
   out=run_brightscript([POLICY,ROOT/'components/SiloUIRobustness.brs',ROOT/'source/core/SiloUIFormat.brs',p,stub],'''
    m.view="audio":m.audioScope="owner":m.audioSleepMs=100
    m.audioSleepClock={TotalMilliseconds:function() as Integer
      return 200
    end function}
    m.top={label:{},findNode:function(id as String) as Object
      return m.label
    end function}
    onSiloUIAudioTick()
    slept=m.released
    m.audioSleepMs=0:m.audioNext={index:0,localMs:500}:m.cleanupTickets={pending:true}
    m.audioQueue=[{fileId:"file"}]:m.audioBook={itemId:"book"}:m.audioToken=2
    onSiloUIAudioTick()
    blocked=m.sent=invalid
    m.cleanupTickets={}
    onSiloUIAudioTick()
    print FormatJson({slept:slept,blocked:blocked,sent:m.sent})
   ''',root=Path(d))
  self.assertEqual(json.loads(out),{'slept':True,'blocked':True,'sent':'audio_start'})
 def test_stale_audio_allocation_is_retired_with_captured_owner(self):
  from tools.brightscript import run_brightscript
  import re
  with tempfile.TemporaryDirectory() as d:
   source=(ROOT/'components/SiloUIRobustness.brs').read_text()
   source=re.sub(r'sub SiloUIQueueCleanup\(.*?\nend sub','sub SiloUIQueueCleanup(plan as Object,owner as Object)\n m.retired={plan:plan,owner:owner}\nend sub',source,count=1,flags=re.S)
   p=Path(d)/'owner.brs';p.write_text(source)
   out=run_brightscript([ROOT/'source/core/SiloPlaybackPolicy.brs',p],'''
    m.generation=2:m.audioToken=8:m.view="audio"
    entry={purpose:"audio_start",generation:1,extra:7,owner:{provider:"silo",sourceId:"silo:old",profileId:"old",generation:1}}
    result={ok:true,sessionRevision:4,plan:{sessionId:"lease",installationId:"install"}}
    stale=SiloUIAllocationResult(entry,result)
    print FormatJson({stale:stale,retired:m.retired})
   ''',root=Path(d))
  result=json.loads(out)
  self.assertTrue(result['stale'])
  self.assertEqual(result['retired']['owner']['sourceId'],'silo:old')
  self.assertEqual(result['retired']['owner']['sessionRevision'],4)
 def test_audio_clock_keeps_seconds_readable_at_start_and_across_hours(self):
  self.assertEqual(self.call('SiloUIAudioTime',0),'0:00')
  self.assertEqual(self.call('SiloUIAudioTime',75000),'1:15')
  self.assertEqual(self.call('SiloUIAudioTime',3661000),'1:01:01')
