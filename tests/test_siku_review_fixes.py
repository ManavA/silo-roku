import json
import re
import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class ReviewFixTests(unittest.TestCase):
 def audio(self, body, robustness=False, scene=False):
  with tempfile.TemporaryDirectory() as d:
   stub=Path(d)/'boundary.brs';stub.write_text('''
sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
 copiedParams={}:copiedParams.Append(params)
 copiedOwner={}:copiedOwner.Append(owner)
 m.calls.Push({action:action,params:copiedParams,extra:extra,owner:copiedOwner})
end sub
sub Toast(message as String)
end sub
sub ObChoose(choice as Object)
 m.switched=true
end sub
''' + ('' if robustness else 'sub SiloUIDrainMaybeDone()\nend sub\n'))
   if scene:
    with stub.open("a") as f:
     f.write("\n"+re.search(r"sub onApiResult\(.*?\nend sub",(ROOT/"components/SiloUIScene.brs").read_text(),re.S).group(0))
   files=[ROOT/'components/SiloUIAudio.brs',ROOT/'source/core/SiloUIAudioPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',stub]
   if robustness:files.append(ROOT/'components/SiloUIRobustness.brs')
   output=run_brightscript(files,'''
    m.calls=[]:m.audioPlan={sessionId:"lease",installationId:"install"}
    m.audioOwner={provider:"silo",sourceId:"silo:old",profileId:"old",generation:1,sessionRevision:4}
    m.audioStarted=true:m.audioPositionReady=true:m.audioToken=1:m.audioSequence=0
    m.audioBook={itemId:"book",durationMs:60000}:m.audioQueue=[{offsetMs:0,durationMs:60000}]
    m.audioIndex=0:m.audioLocalMs=10000:m.audioNode={state:"playing"}
   '''+body,root=Path(d))
  return json.loads(output)
 def test_book_sync_serializes_and_coalesces_final_with_original_owner(self):
  r=self.audio('''
   SiloUIAudioSendProgress(false)
   m.audioLocalMs=20000:SiloUIAudioSendProgress(true)
   m.audioLocalMs=30000:SiloUIAudioSendProgress(true)
   before=m.calls.Count()
   m.audioOwner.profileId="new"
   SiloUIAudioSyncResult({ok:true},1)
   after=m.calls.Count()
   SiloUIAudioSyncResult({ok:true},1)
   duplicate=m.calls.Count()
   print FormatJson({before:before,after:after,duplicate:duplicate,calls:m.calls})
  ''')
  sync=[c for c in r['calls'] if c['action']=='audio_sync']
  self.assertEqual(len(sync),2)
  self.assertEqual([c['params']['positionMs'] for c in sync],[10000,30000])
  self.assertEqual([c['owner']['profileId'] for c in sync],['old','old'])
  self.assertEqual(r['after'],r['duplicate'])
 def test_transition_waits_for_newest_final_ack(self):
  r=self.audio('''
   m.transitionIntent={action:"profile"}:m.cleanupTickets={}:m.pending={}
   SiloUIAudioSendProgress(false)
   m.audioLocalMs=60000:SiloUIAudioSendProgress(true)
   SiloUIDrainMaybeDone():first=m.switched=true
   SiloUIAudioSyncResult({ok:true},1)
   second=m.switched=true
   SiloUIAudioSyncResult({ok:true},2)
   print FormatJson({first:first,second:second,switched:m.switched})
  ''',robustness=True)
  self.assertFalse(r['first']);self.assertFalse(r['second']);self.assertTrue(r['switched'])
 def services(self, body):
  with tempfile.TemporaryDirectory() as d:
   stub=Path(d)/'boundary.brs';stub.write_text('''
sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.calls.Push(action)
end sub
sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
 m.calls.Push(action)
end sub
sub Toast(message as String)
end sub
sub BrowsePagedChoices(title as String,labels as Object,handler as String,start=0 as Integer)
 m.menus.Push(title)
end sub
''')
   output=run_brightscript([ROOT/'components/SiloUIServices.brs',ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs',stub],'''
    m.calls=[]:m.menus=[]:m.provider="silo":m.sourceId="silo:old":m.profileId="p":m.generation=1
    m.view="detail":m.detailToken=7:m.detailItem={itemId:"a"}
    m.servicesOwner={provider:"silo",sourceId:"silo:old",profileId:"p",generation:1}
    m.servicesOwnerView="detail":m.servicesGeneration=1:m.servicesVisit=1:m.servicesSerial=1
    m.servicesDetailContext={token:7,itemId:"a"}:m.servicesCaps={}
    m.servicesContext=BrowseCaptureContext()
   '''+body,root=Path(d))
  return json.loads(output)
 def test_service_dispatch_and_result_reject_different_profile_or_detail_visit(self):
  r=self.services('''
   m.profileId="other"
   ServicesCall("notifications_read_all",{through:"cutoff"})
   m.profileId="p":m.servicesSerial=1:m.detailToken=8:m.detailItem={itemId:"b"}
   ServicesResult({ok:true},{available:true},{visit:1,serial:1,action:"requests_cap"})
   print FormatJson({calls:m.calls,menus:m.menus})
  ''')
  self.assertEqual(r,{'calls':[],'menus':[]})
 def test_replaced_confirmation_and_repeated_event_never_dispatch(self):
  r=self.services('''
   old={id:1}
   current={id:2,buttonSelected:0,isSameNode:function(other as Object) as Boolean
    return m.id=other.id
   end function}
   m.top={dialog:current}:m.browseDialog=current
   m.servicesMutation={action:"notifications_read_all"}:m.servicesReadCutoff="cutoff"
   ServicesBindDialog("confirm",current)
   oldEvent={node:old,getRoSGNode:function() as Object
    return m.node
   end function}
   currentEvent={node:current,getRoSGNode:function() as Object
    return m.node
   end function}
   onServicesConfirm(oldEvent)
   before=m.calls.Count()
   onServicesConfirm(currentEvent)
   m.servicesBusy=false
   onServicesConfirm(currentEvent)
   print FormatJson({before:before,calls:m.calls})
  ''')
  self.assertEqual(r,{'before':0,'calls':['service_notifications_read_all']})
 def test_onboarding_screen_change_fences_service_dispatch(self):
  r=self.services('''
   m.view="onboarding":m.servicesOwnerView="onboarding":m.servicesDetailContext=invalid
   m.obQrGeneration=4:m.servicesContext=BrowseCaptureContext():m.obQrGeneration=5
   ServicesCall("notifications_read_all",{through:"cutoff"})
   print FormatJson(m.calls)
  ''')
  self.assertEqual(r,[])
 def test_social_callback_cannot_mutate_after_profile_or_title_changes(self):
  with tempfile.TemporaryDirectory() as d:
   stub=Path(d)/'boundary.brs';stub.write_text('''
sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.calls.Push(action)
end sub
sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
 m.calls.Push(action)
end sub
''')
   files=[ROOT/'components/SiloUILibrary.brs',ROOT/'source/core/SiloUIFormat.brs',stub]
   dialogs=ROOT/'components/SiloUIDialogs.brs'
   if dialogs.exists():files.append(dialogs)
   out=run_brightscript(files,'''
    m.calls=[]:m.provider="silo":m.sourceId="silo:a":m.profileId="old":m.generation=1
    m.view="detail":m.detailToken=1:m.detailItem={itemId:"a"}:m.browseViewToken=1
    node={id:1,buttonSelected:0,isSameNode:function(other as Object) as Boolean
     return m.id=other.id
    end function}
    m.top={dialog:node}:m.browseDialog=node
    BrowseBindDialog(node,"onBrowseSocial")
    event={node:node,getRoSGNode:function() as Object
     return m.node
    end function}
    m.browseSocialItem={itemId:"a"}:m.profileId="new"
    onBrowseSocial(event)
    m.profileId="old":m.detailToken=2:m.detailItem={itemId:"b"}
    onBrowseSocial(event)
    print FormatJson(m.calls)
   ''',root=Path(d))
  self.assertEqual(json.loads(out),[])
 def test_keyboard_callback_checks_emitter_and_consumes_selection_once(self):
  r=self.services('''
   old={id:1}
   current={id:2,buttonSelected:0,text:"new search",isSameNode:function(other as Object) as Boolean
    return m.id=other.id
   end function}
   m.top={dialog:current}:m.servicesKeyboard=current:m.servicesKeyboardAction="request_search"
   ServicesBindDialog("keyboard",current)
   oldEvent={node:old,getRoSGNode:function() as Object
    return m.node
   end function}
   currentEvent={node:current,getRoSGNode:function() as Object
    return m.node
   end function}
   onServicesKeyboard(oldEvent)
   before=m.calls.Count()
   onServicesKeyboard(currentEvent)
   m.servicesBusy=false
   onServicesKeyboard(currentEvent)
   print FormatJson({before:before,calls:m.calls,text:current.text})
  ''')
  self.assertEqual(r,{'before':0,'calls':['service_request_search'],'text':''})
 def test_paged_library_dialogs_rebind_new_node_and_reject_returned_view(self):
  with tempfile.TemporaryDirectory() as d:
   source=(ROOT/'components/SiloUILibrary.brs').read_text()
   source=re.sub(r'sub BrowseDialog\(.*?\nend sub','''sub BrowseDialog(title as String,labels as Object,handler as String)
    m.nodeSerial=NumberOr(m.nodeSerial,0)+1
    node={id:m.nodeSerial,buttonSelected:0,isSameNode:function(other as Object) as Boolean
     return m.id=other.id
    end function}
    m.browseDialog=node:m.top.dialog=node
    BrowseBindDialog(node,handler)
end sub''',source,count=1,flags=re.S)
   p=Path(d)/'library.brs';p.write_text(source)
   out=run_brightscript([p,ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs'],'''
    m.top={}:m.provider="silo":m.sourceId="silo:a":m.profileId="p":m.generation=1
    m.view="library":m.libraryToken=4:m.browseViewToken=1
    BrowsePagedChoices("choices",["a","b","c","d","e","f","g"],"onLibraryChoice")
    first=m.browseDialog:first.buttonSelected=6
    oldEvent={node:first,getRoSGNode:function() as Object
     return m.node
    end function}
    page=BrowseChoiceIndex(oldEvent)
    m.browseDialog.buttonSelected=0
    currentEvent={node:m.browseDialog,getRoSGNode:function() as Object
     return m.node
    end function}
    stale=BrowseChoiceIndex(oldEvent)
    selected=BrowseChoiceIndex(currentEvent)
    duplicate=BrowseChoiceIndex(currentEvent)
    BrowsePagedChoices("choices",["a"],"onLibraryChoice")
    returnedEvent={node:m.browseDialog,getRoSGNode:function() as Object
     return m.node
    end function}
    m.browseViewToken=3
    returned=BrowseChoiceIndex(returnedEvent)
    print FormatJson([page,stale,selected,duplicate,returned])
   ''',root=Path(d))
  self.assertEqual(json.loads(out),[-1,-1,6,-1,-1])

 def test_old_generation_ack_drains_captured_final_before_scene_stale_drop(self):
  r=self.audio('''
   SiloUIAudioSendProgress(false)
   m.audioLocalMs=50000:SiloUIAudioSendProgress(true)
   m.provider="silo":m.sourceId="silo:new":m.profileId="new":m.generation=2
   task={unobserveField:sub(field as String)
   end sub}
   m.pending={"5":{purpose:"audio_sync",extra:1,generation:1,task:task,owner:m.audioOwner}}
   event={getData:function() as Object
    return {requestId:5,ok:true,generation:1}
   end function}
   onApiResult(event)
   print FormatJson(m.calls)
  ''',scene=True)
  sync=[x for x in r if x['action']=='audio_sync']
  self.assertEqual([x['params']['positionMs'] for x in sync],[10000,50000])
  self.assertEqual(sync[-1]['owner']['sourceId'],'silo:old')
  self.assertEqual(sync[-1]['owner']['profileId'],'old')
 def test_immediate_audio_seek_waits_for_latest_target_then_reports_progress(self):
  with tempfile.TemporaryDirectory() as d:
   stub=Path(d)/'boundary.brs';stub.write_text('''
function HomeProgressScope() as String
 return "owner"
end function
sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
 m.calls.Push({action:action,position:params.positionMs})
end sub
sub Toast(message as String)
end sub
''')
   out=run_brightscript([ROOT/'components/SiloUIAudio.brs',ROOT/'source/core/SiloUIAudioPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',stub],'''
    m.view="audio":m.audioScope="owner":m.audioSleepMs=0:m.calls=[]
    m.audioQueue=[{offsetMs:0,durationMs:120000}]:m.audioIndex=0:m.audioLocalMs=0
    m.audioPlan={startPositionMs:0,sessionId:"s",installationId:"i"}
    m.audioBook={itemId:"book",durationMs:120000}:m.audioOwner={provider:"silo",sourceId:"silo:a",profileId:"p",generation:1}
    m.audioStarted=true:m.audioPositionReady=false:m.audioSequence=0:m.audioTicks=14
    m.audioNode={state:"playing",position:0}
    m.top={label:{},findNode:function(id as String) as Object
     return m.label
    end function}
    SiloUIAudioKey("right")
    onSiloUIAudioTick()
    waiting=m.audioPositionReady
    premature=m.calls.Count()
    m.audioNode.position=30
    onSiloUIAudioTick()
    SiloUIAudioSendProgress(false)
    print FormatJson({waiting:waiting,premature:premature,ready:m.audioPositionReady,local:m.audioLocalMs,calls:m.calls})
   ''',root=Path(d))
  r=json.loads(out)
  self.assertFalse(r['waiting']);self.assertEqual(r['premature'],0)
  self.assertTrue(r['ready']);self.assertEqual(r['local'],30000)
  self.assertEqual(r['calls'][0],{'action':'audio_sync','position':30000})
 def test_immediate_chapter_seek_uses_new_target_and_rejects_stale_scope(self):
  with tempfile.TemporaryDirectory() as d:
   stub=Path(d)/'boundary.brs';stub.write_text('''
function HomeProgressScope() as String
 return "owner"
end function
''')
   out=run_brightscript([ROOT/'components/SiloUIAudio.brs',ROOT/'components/SiloUILibrary.brs',ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIAudioPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',stub],'''
    m.provider="silo":m.sourceId="silo:a":m.profileId="p":m.generation=1:m.view="audio":m.audioScope="owner"
    m.audioPlan={startPositionMs:0}:m.audioQueue=[{durationMs:120000}]:m.audioIndex=0
    m.audioToken=1:m.audioOptionsToken=1:m.audioPositionReady=false:m.audioNode={state:"playing",position:0}
    m.audioOptionChapters=[{start_seconds:60}]
    node={id:1,buttonSelected:8,isSameNode:function(other as Object) as Boolean
     return m.id=other.id
    end function}
    m.top={dialog:node}:m.browseDialog=node
    m.browsePaged={handler:"onSiloUIAudioOption",previous:-1,nextPage:-1,count:9,start:0}
    BrowseBindDialog(node,"onSiloUIAudioOption")
    event={node:node,getRoSGNode:function() as Object
     return m.node
    end function}
    onSiloUIAudioOption(event)
    target=m.audioSeekTargetMs
    m.audioScope="stale"
    SiloUIAudioSeek(90000)
    print FormatJson({target:target,seek:m.audioNode.seek,ready:m.audioPositionReady})
   ''',root=Path(d))
  self.assertEqual(json.loads(out),{'target':60000,'seek':60,'ready':False})
