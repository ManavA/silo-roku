"""Actual allocation/API callback and PlayerStart; SDK factories/fields only."""
import copy,json,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from tools.brightscript import run_brightscript
from tests import test_silo_ordinary_p8_original as transport
ROOT=Path(__file__).resolve().parents[1]
class OrdinaryP8Scene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result=transport.OrdinaryP8Original().start()
        if not result['outcome']['ok']:raise AssertionError('actual Task receipt unavailable')
        cls.plan=result['outcome']['plan']
    def scene(self,stale=False,output_changed=False):
        plan=copy.deepcopy(self.plan)
        if stale:plan['originalPlayback']['scope']['generation']=6
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);files=[]
            for script in ET.parse(ROOT/'components/SiloUIScene.xml').getroot().findall('script'):
                name=script.get('uri').removeprefix('pkg:/');text=(ROOT/name).read_text()
                text=text.replace('CreateObject("roSGNode", "ApiTask")','FixtureTask()').replace('CreateObject("roDeviceInfo")','FixtureDevice()').replace('CreateObject("roHttpAgent")','FixtureAgent()').replace('m.video.SetHttpAgent(agent)','FixtureSetHttpAgent(agent)')
                if output_changed:text=text.replace('device.GetVideoMode()', '"1080p"')
                file=root/Path(name).name;file.write_text(text);files.append(file)
            sdk=root/'SDK.brs';sdk.write_text('''
function FixtureTask() as Object
 return {observeField:sub(field as String,callback as String)
 end sub,unobserveField:sub(field as String)
 end sub}
end function
function FixtureAgent() as Object
 return {SetCertificatesFile:sub(path as String)
 end sub,AddHeader:sub(name as String,value as String)
 end sub}
end function
sub FixtureSetHttpAgent(agent as Object)
end sub
function FixtureDevice() as Object
 return {GetModel:function() as String
 return "C000X"
 end function,GetModelDetails:function() as Object
 return {ModelNumber:"C208X"}
 end function,GetOSVersion:function() as Object
 return {major:"16",minor:"0",revision:"4",build:"834"}
 end function,GetVideoMode:function() as String
 return "2160p60"
 end function,GetDisplayProperties:function() as Object
 return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}
 end function,GetRandomUUID:function() as String
 return "10000000-0000-4000-8000-000000000009"
 end function}
end function
function FixtureEvent(payload as Object) as Object
 return {payload:payload,getData:function() as Object
 return m.payload
 end function}
end function
''');files.append(sdk)
            payload=json.dumps(plan).replace('"','""')
            output=run_brightscript(files,'''m.provider="silo":m.sourceId="silo:https://silo.example":m.profileId="fixture-owner":m.generation=7
 m.view="detail":m.zone="detailButtons":m.pending={}:m.cleanupTickets={}:m.requestId=0:m.playToken=1:m.playLoading=true
 m.preferences={subtitles:"off",quality:"original"}:m.trackPref={}:m.trackPrefLanes={}:m.playMarkers=[]:m.originalGeneration=0:m.upNextDismissed=false:m.introDismissed=false
 m.playItem={itemId:"fixture-item",type:"movie",title:"Fixture",durationMs:7200000}
 m.playVersions=[{versionId:"731",durationMs:7200000}]:m.detailEpisodes=[]
 m.top=CreateObject("roSGNode","Group")
 for each name in ["home","detail","library","search","playerChapters"]
 child=m.top.createChild("Group"):child.id=name
 end for
 m.video=CreateObject("roSGNode","Node")
 m.video.AddFields({content:invalid,state:"buffering",position:0.0,globalCaptionMode:"Off",availableAudioTracks:[],availableSubtitleTracks:[],playbackActionButtons:[],mute:false,control:"",visible:false})
 m.nav=m.top.createChild("Group"):m.toast=m.top.createChild("Label")
 m.toastTimer={control:"stop"}:m.progressTimer={control:"stop"}:m.upNextTimer={control:"stop"}:m.playClock=CreateObject("roTimespan")
 m.subtitleBindingGeneration=0
 Api("playback_start",{itemId:"fixture-item",fileId:"731"},"play_start",1)
 returned=ParseJson("'''+payload+'''")
 onApiResult(FixtureEvent({requestId:1,ok:true,sessionRevision:0,plan:returned,data:{}}))
 print FormatJson({guard:m.originalPlayback<>invalid,bound:m.video.content<>invalid,tickets:m.cleanupTickets.Count(),pending:m.pending.Count(),loading:m.playLoading})
''',root=root)
            return json.loads(output.strip().splitlines()[-1])
    def test_actual_allocation_callback_accepts_current_ordinary_scope(self):
        self.assertEqual(dict(guard=True,bound=True,tickets=0,pending=0,loading=False),self.scene())
    def test_actual_allocation_callback_rejects_stale_descriptor_generation(self):
        self.assertEqual(dict(guard=False,bound=False,tickets=1,pending=1,loading=False),self.scene(stale=True))

    def test_actual_allocation_callback_rejects_fresh_output_change(self):
        self.assertEqual(dict(guard=False,bound=False,tickets=1,pending=1,loading=False),self.scene(output_changed=True))
