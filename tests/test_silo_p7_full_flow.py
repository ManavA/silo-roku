"""Cold real Scene→Task→persistent holder, HTTP/SG/device leaves only.

Actual producer Tasks run in separate interpreter invocations. Technical DTOs and
SDK callbacks prove host control/ownership behavior, never native decoding.
"""
import copy,json,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from tests import test_silo_compat_playback_task as holder
from tests import test_silo_p7_producer_flow as producer
from tests.test_silo_ui_compat_continuation import SCENE_SDK
ROOT=Path(__file__).resolve().parents[1]

class P7FullFlow(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  producer.P7ProducerFlow.setUpClass()
  cls.expectedJob=copy.deepcopy(producer.P7ProducerFlow.scene_job)
  cls.producerResult=producer.P7ProducerFlow().run_task()['outcome']
  detail_job=producer.scene.OrdinaryNativeHdr10Scene().scene()['tasks'][0]['job']
  cls.detailResult=producer.task.CompatContinuation().job(enabled=False,scope=detail_job,mutate=producer.fixture,device=producer.DEVICE)['outcome']
 def transcript(self,control='media_roundtrip',mutate=None,automatic=False):
  wire={};producer.fixture(wire,{})
  data=dict(wire=wire,control=control,realEntry=True,detailResult=self.detailResult,producerResult=self.producerResult,entryJob=copy.deepcopy(self.expectedJob))
  def change(values):
   metadata=copy.deepcopy(producer.TECHNICAL['compat_metadata']);receipt=copy.deepcopy(producer.TECHNICAL['compat_receipt'])
   metadata['Id']=receipt['Id']=holder.SOURCE
   receipt['TranscodingUrl']='/Videos/'+holder.SOURCE+'/remux-dv-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId='+holder.SOURCE
   values['metadata']={'MediaSources':[metadata]};values['playback']={'PlaySessionId':'play-fixture','MediaSources':[receipt]}
   if mutate:mutate(values)
  ids=sorted({n.get('id') for n in ET.parse(ROOT/'components/SiloUIScene.xml').getroot().iter() if n.get('id')})
  encoded=json.dumps(ids).replace('"','""')
  # A 12-second native HLS window must not replace the 6,214-second source timeline.
  start='''sub FixtureSceneStart(data as Object)
 m.fixtureDuplicateDelivered=false:m.fixtureVideoRetirements=[]
 m.provider="silo":m.sourceId=m.fixtureSession.sourceId:m.profileId=m.fixtureSession.profileId:m.generation=7
 m.view="detail":m.zone="detailButtons":m.pending={}:m.cleanupTickets={}:m.requestId=0
 m.preferences={subtitles:"off",quality:"original"}:m.pillGroups={}:m.detailEpisodes=[]
 m.top=CreateObject("roSGNode","Group"):m.top.AddFields({memoryPressure:0,dialog:invalid})
 for each name in ParseJson("'''+encoded+'''")
  child=m.top.createChild("Group"):child.id=name:child.translation=[0,0]
  child.AddFields({control:"stop",fire:false,text:"",content:invalid,position:0.0,duration:12.0,state:"buffering",globalCaptionMode:"Off",availableAudioTracks:[],availableSubtitleTracks:[],currentSubtitleTrack:"",playbackActionButtons:[],playbackActionButtonSelected:0,mute:false,itemSelected:0,rowItemFocused:[0,0],streamingSegment:{}})
 end for
 m.nav=m.top.createChild("Group"):m.manualFocus=m.top.createChild("Group")
 m.backdrop=m.top.createChild("Group"):m.backdropOld=m.top.createChild("Group")
 m.backdropTimer={control:"stop"}:m.backdropFade={control:"stop"}
 m.toast=m.top.createChild("Label"):m.toastTimer={control:"stop"}
 m.sceneTop=m.top
 DetailInit():PlayerInit():m.sceneVideo=m.video
 detail=ScopeCatalogData(DecodeSiloResponse("detail",FormatJson(data.wire),{sourceId:m.sourceId}).data,m.sourceId)
 m.detailToken=4:m.detailVersions=detail.versions
 item=detail.item:item.durationMs=6214000:item.resumeMs=0:item.art={}
 choices=SiloUIDetailAudioChoices("silo",item,m.detailVersions,"")
 choice=choices[1]:choice.visit=m.detailToken:choice.sourceId=m.sourceId:choice.profileId=m.profileId:choice.generation=m.generation
 PlayItem(item,0,"",choice)
 onApiResult(FixtureSceneEvent(data.detailResult))
 child=m.pending["2"].task
 qualification=SpField(SpField(data.producerResult,"compatContinuation"),"instanceQualification")
 if qualification=invalid then qualification=SpField(SpField(data.entryJob,"params"),"instanceQualification")
 if qualification<>invalid then child.job.params["instanceQualification"]=SpCopy(qualification)
 m.fixtureEntryJob=ParseJson(FormatJson(child.job))
 onApiResult(FixtureSceneEvent(data.producerResult))
end sub
sub FixtureObserveField(field as String,callback as Dynamic)
end sub
'''
  if automatic:
   explicit_entry=''' choices=SiloUIDetailAudioChoices("silo",item,m.detailVersions,"")
 choice=choices[1]:choice.visit=m.detailToken:choice.sourceId=m.sourceId:choice.profileId=m.profileId:choice.generation=m.generation
 PlayItem(item,0,"",choice)'''
   assert start.count(explicit_entry)==1
   start=start.replace(explicit_entry,' PlayItem(item,0)',1)
  old='sub FixtureSceneStart(data as Object)'+SCENE_SDK.split('sub FixtureSceneStart(data as Object)',1)[1]
  overrides={old:start}
  overrides['m.results.Push(ParseJson(FormatJson(m.top.result)))']='m.results.Push(ParseJson(FormatJson(m.top.result)))\n if m.results.Count()>32 then m.fixtureBoundaryEnded=true:throw "finite real-entry callback checkpoint"'
  # Ordinary Back supplies the retirement event; observe the SDK Video command
  # before any compatibility Stopped request, not an invented native ACK.
  overrides['if Right(url,25)="/Sessions/Playing/Stopped" then key="compat/stopped"']='if Right(url,25)="/Sessions/Playing/Stopped"\n  key="compat/stopped"\n  m.fixtureVideoRetirements.Push({contentDetached:m.sceneVideo.content=invalid,control:m.sceneVideo.control,state:m.sceneVideo.state})\n  if m.sceneVideo.content<>invalid or m.sceneVideo.control<>"stop" then throw "local Video not retired before owned stopped"\n end if'
  overrides['PlayerClose(false,false):m.video.state="stopped":onVideoState():m.top=parent:return invalid']='m.fixtureBackHandled=PlayerKey("back"):m.video.state="stopped":onVideoState():m.top=parent:return invalid'
  overrides['return {scene:{holderCreated:true,holderCount:']='return {entryJob:m.fixtureEntryJob,videoRetirements:m.fixtureVideoRetirements,backHandled:m.fixtureBackHandled,scene:{holderCreated:true,holderCount:'
  return holder.CompatPlaybackTask().transcript(scene=data,change=change,device_overrides=producer.DEVICE,sdk_overrides=overrides)
 def test_real_audio_entry_reanchors_twice_and_back_retires_exact_owned_holder(self):
  result=self.transcript()
  self.assertNotIn('fixtureError',result,result)
  self.assertTrue(result['scene']['holderCreated'],result)
  def folded(value):
   if isinstance(value,dict):return {k.lower():folded(v) for k,v in value.items()}
   if isinstance(value,list):return [folded(v) for v in value]
   return value
  self.assertEqual(folded(self.expectedJob),folded(result['entryJob']))
  self.assertTrue(result['scene']['released']);self.assertFalse(result['scene']['bound'])
  self.assertTrue(result['results'][-1]['credentialRevoked']);self.assertTrue(result['privateCleared'])
  prepared=[r for r in result['results'] if r['phase']=='prepared']
  self.assertEqual([1,2,3],[r['planGeneration'] for r in prepared])
  self.assertEqual(['copied_p7_hdr10_fmp4']*3,[r['class'] for r in prepared])
  requests=[q for q in result['requests'] if '/PlaybackInfo' in q['url']]
  self.assertEqual(3,len(requests))
  for q in requests:
   body=json.loads(q['body']);self.assertEqual((holder.SOURCE,2,-1),(body['MediaSourceId'],body['AudioStreamIndex'],body['SubtitleStreamIndex']))
   self.assertEqual('ac3',body['DeviceProfile']['TranscodingProfiles'][0]['AudioCodec'])
  self.assertEqual([0,9000000000,1200000000],[json.loads(q['body'])['StartTimeTicks'] for q in requests])
  self.assertFalse(result['scene']['watched'])
  self.assertEqual([dict(contentDetached=True,control='stop',state='stopped')]*3,result['videoRetirements'])
  self.assertTrue(result['backHandled'])
  self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))
  stops=[json.loads(q['body']) for q in result['requests'] if '/Sessions/Playing/Stopped' in q['url']]
  self.assertEqual(['play-fixture','play-fixture-2','play-fixture-3'],[q['PlaySessionId'] for q in stops])
  self.assertEqual([0,9002000000,1202000000],[q['PositionTicks'] for q in stops])
  for q in stops:
   self.assertEqual((holder.SOURCE,holder.SOURCE,2,-1),(q['ItemId'],q['MediaSourceId'],q['AudioStreamIndex'],q['SubtitleStreamIndex']))
  self.assertEqual(3,sum('/Videos/ActiveEncodings?' in q['url'] for q in result['requests']))
  self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))

 def test_wrong_delivered_container_refuses_before_bind_and_revokes_owned_credential(self):
  def changed_receipt(values):
   values['playback']['MediaSources'][0]['TranscodingContainer']='ts'
  result=self.transcript(mutate=changed_receipt)
  self.assertNotIn('fixtureError',result,result)
  self.assertTrue(result['scene']['holderCreated'])
  self.assertFalse(result['scene']['bound'])
  self.assertTrue(result['scene']['released'])
  self.assertEqual('refused',result['results'][-1]['phase'])
  self.assertTrue(result['results'][-1]['mediaNeverRequested'])
  self.assertTrue(result['results'][-1]['credentialRevoked'])
  self.assertTrue(result['privateCleared'])
  self.assertEqual([],result['videoRetirements'])
  self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
  self.assertFalse(any('/Sessions/Playing' in q['url'] or '/playback/start' in q['url'] for q in result['requests']))
  self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))

if __name__=='__main__':unittest.main()
