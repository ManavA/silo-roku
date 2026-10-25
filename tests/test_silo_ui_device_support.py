"""On-demand device support through actual Scene dialog callbacks and SDK boundaries."""
import json,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class DeviceSupport(unittest.TestCase):
 def scene(self,body,device=''):
  files=[ROOT/s.attrib['uri'].removeprefix('pkg:/') for s in ET.parse(ROOT/'components/SiloUIScene.xml').getroot().findall('script')]
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d);player=folder/'player.brs'
   player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('CreateObject("roSGNode", "Dialog")','FixtureDialog()').replace('CreateObject("roDeviceInfo")','FixtureDevice()'))
   files=[player if p.name=='SiloUIPlayer.brs' else p for p in files]
   scene=folder/'scene.brs';scene.write_text((ROOT/'components/SiloUIScene.brs').read_text().replace('CreateObject("roSGNode", "ApiTask")','FixtureTask()'))
   files=[scene if p.name=='SiloUIScene.brs' else p for p in files]
   sdk=folder/'sdk.brs';sdk.write_text('''function FixtureDialog() as Object
 m.dialogCount++
 return {id:m.dialogCount,buttonSelected:0,observeField:sub(a,b)
 end sub,isSameNode:function(other)
 return m.id=other.id
 end function}
end function
function FixtureEvent(node) as Object
 return {node:node,getRoSGNode:function()
 return m.node
 end function}
end function
function FixtureDevice() as Object
 m.deviceCreates++
 return {queries:m.global.queries,GetModel:function()
 return "4660X"
 end function,GetModelDetails:function()
 return {ModelNumber:"4660X",ModelType:"STB",SerialNumber:"private-secret"}
 end function,GetOSVersion:function()
 return {major:"13",minor:"1",revision:"4",build:"1510"}
 end function,GetVideoMode:function()
 return "2160p60"
 end function,GetDisplayProperties:function()
 return {Hdr10:true,DolbyVision:false,HLG:"true"}
 end function,CanDecodeVideo:function(q)
 m.queries.Push(q)
 return {result:q.codec="mpeg4 avc"}
 end function,CanDecodeAudio:function(q)
 m.queries.Push(q)
 return {result:true}
 end function}
end function
'''.replace('return {Hdr10:true,DolbyVision:false,HLG:"true"}', 'throw "private-secret"' if device=='throw' else 'return {Hdr10:true,DolbyVision:false,HLG:"true"}').replace('return {result:q.codec="mpeg4 avc"}', 'return {result:"true"}' if device=='throw' else 'return {result:q.codec="mpeg4 avc"}')+'''
function FixtureTask() as Object
 return {observeField:sub(a,b)
 end sub}
end function
''')
   setup='''m.top=CreateObject("roSGNode","Node"):m.top.AddFields({dialog:invalid})
 m.global={queries:[]}:m.deviceCreates=0:m.dialogCount=0:m.pending={}:m.requestId=0
 m.view="detail":m.zone="detailButtons":m.generation=3:m.sourceId="silo:fixture":m.profileId="profile":m.provider="plex"
 '''
   out=run_brightscript([*files,sdk],setup+body,root=folder)
   try:return json.loads(out.strip().splitlines()[-1])
   except Exception:raise AssertionError(out)
 def test_request_info_is_optional_redacted_revalidated_and_returns_to_error(self):
  v=self.scene('''facts={quality:"original",selection:"auto",videoCodec:"hevc",audioCodec:"aac",hdr10:"yes",dolbyVision:"unknown",mpegts:true,separateAudio:false,dv7To81:false,hevcAdmitted:true,hlsEnabled:true,hlsSupported:true,originalEnabled:false,originalSupported:false,width:3840,height:2160,dvProfile:7,dvBaseCompatibility:6,secret:"private-secret"}
 PlayerShowFailure("prepare",{startRequestFacts:facts})
 d=m.top.dialog:buttons=d.buttons:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog:info=d.message:title=d.title
 d.buttonSelected=0:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog:restored=d.buttons
 m.playbackFailureRequestFacts.videoCodec="private-secret":d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({buttons:buttons,title:title,info:info.Split(Chr(10)),restored:restored,last:d.title,creates:m.deviceCreates})''')
  self.assertEqual(['OK','Device info','Request info'],v['buttons']);self.assertEqual(v['buttons'],v['restored'])
  self.assertEqual('Request info',v['title']);self.assertEqual('Playback error',v['last']);self.assertEqual(0,v['creates'])
  self.assertNotIn('private-secret',str(v));self.assertIn('DV profile 7',str(v['info']));self.assertIn('not output proof',str(v['info']))
 def test_request_info_optional_hls_hevc_is_strict_and_old_snapshots_keep_label(self):
  for value, expected in (('true','HEVC device/HLS yes/yes'),('false','HEVC device/HLS yes/no'),('invalid','HEVC admitted yes'),('"true"',None),('1',None)):
   with self.subTest(value=value):
    optional = '' if value == 'invalid' else 'facts["hlsHevcAdmitted"]='+value
    v=self.scene('facts={quality:"original",selection:"auto",videoCodec:"hevc",audioCodec:"aac",hdr10:"yes",dolbyVision:"unknown",mpegts:true,separateAudio:false,dv7To81:false,hevcAdmitted:true,hlsEnabled:true,hlsSupported:true,originalEnabled:false,originalSupported:false}\n'+optional+'''
 PlayerShowFailure("prepare",{startRequestFacts:facts})
 d=m.top.dialog:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({buttons:d.buttons,title:d.title,info:d.message.Split(Chr(10)),creates:m.deviceCreates})''')
    if expected is None:
     self.assertEqual(['OK','Device info'],v['buttons']);self.assertEqual('Playback error',v['title'])
    else:
     self.assertEqual('Request info',v['title']);self.assertIn(expected,v['info'])
    self.assertEqual(0,v['creates'])
 def test_request_info_optional_copy_mpegts_is_strict_and_old_snapshots_are_unknown(self):
  for value, expected in (('true','yes'),('false','no'),('invalid','unknown'),('"true"',None),('1',None)):
   with self.subTest(value=value):
    optional = '' if value == 'invalid' else 'facts["copyMpegts"]='+value
    v=self.scene('facts={quality:"original",selection:"auto",videoCodec:"hevc",audioCodec:"aac",hdr10:"yes",dolbyVision:"unknown",mpegts:true,separateAudio:false,dv7To81:false,hevcAdmitted:true,hlsEnabled:true,hlsSupported:true,originalEnabled:false,originalSupported:false}\n'+optional+'''
 PlayerShowFailure("prepare",{startRequestFacts:facts})
 d=m.top.dialog:buttons=d.buttons
 if buttons.Count()=3 then d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d))
 d=m.top.dialog
 print FormatJson({buttons:buttons,title:d.title,info:d.message.Split(Chr(10)),creates:m.deviceCreates})''')
    if expected is None:
     self.assertEqual(['OK','Device info'],v['buttons']);self.assertEqual('Playback error',v['title'])
    else:
     self.assertEqual('Request info',v['title']);self.assertIn('hls_copy_mpegts_v1 '+expected,v['info'])
    self.assertEqual(0,v['creates'])
 def test_attempt_info_preserves_first_and_last_attempt_and_resanitizes_history(self):
  v=self.scene('''facts={quality:"original",selection:"manual",videoCodec:"hevc",audioCodec:"ac3",hdr10:"yes",dolbyVision:"yes",mpegts:true,separateAudio:false,dv7To81:false,hevcAdmitted:true,hlsEnabled:true,hlsSupported:true,originalEnabled:false,originalSupported:false,width:3834,height:1602}
 attempts=[]
 for i=0 to 11
  attempt={request:SpCopy(facts),httpStatus:200,outcome:"adaptation_unavailable",originalReason:"qualified_route_not_enabled",url:"https://private-secret"}
  if i>0 then attempt.request.quality="480p"
  attempts.Push(attempt)
 end for
 PlayerShowFailure("prepare",{startRequestFacts:attempts[11].request,startAttempts:attempts})
 captured=ParseJson(FormatJson(m.playbackFailureAttempts)):count=m.playbackFailureAttempts.Count()
 m.playbackFailureAttempts[0].url="private-secret":m.playbackFailureAttempts[0].originalReason="private-secret"
 d=m.top.dialog:d.buttonSelected=3:onPlayerFailureChoice(FixtureEvent(d))
 title=m.top.dialog.title:info=m.top.dialog.message.Split(Chr(10))
 d=m.top.dialog:d.buttonSelected=0:onPlayerFailureChoice(FixtureEvent(d)):buttons=m.top.dialog.buttons
 d=m.top.dialog:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d))
 print FormatJson({title:title,info:info,captured:captured,count:count,buttons:buttons,requestTitle:m.top.dialog.title,requestLines:m.top.dialog.message.Split(Chr(10)).Count()})''')
  self.assertLessEqual(len(v['info']),11)
  v['info']='\n'.join(v['info'])
  self.assertEqual(['OK','Device info','Request info','Start attempts'],v['buttons'])
  self.assertEqual('Request info',v['requestTitle']);self.assertLessEqual(v['requestLines'],11)
  self.assertEqual(8,v['count'])
  self.assertEqual('Start attempts',v['title'])
  self.assertIn('First Start: original',v['info']);self.assertIn('Last Start: 480p',v['info'])
  self.assertIn('Original: qualified_route_not_enabled',v['info']);self.assertIn('3834',v['info'])
  self.assertIn('HTTP 200 / adaptation_unavailable',v['info'])
  self.assertNotIn('private-secret',v['info']+json.dumps(v['captured']))

 def test_info_back_creates_fresh_main_dialog_then_ok_dismisses_and_ignores_old_callback(self):
  v=self.scene('''PlayerShowFailure("detail",{}):old=m.top.dialog
 old.buttonSelected=1:onPlayerFailureChoice(FixtureEvent(old))
 info=m.top.dialog:info.buttonSelected=0:onPlayerFailureChoice(FixtureEvent(info)):fresh=m.top.dialog
 onPlayerFailureClosed(FixtureEvent(old)):onPlayerFailureChoice(FixtureEvent(old))
 fresh.buttonSelected=0:onPlayerFailureChoice(FixtureEvent(fresh))
 print FormatJson({fresh:fresh.id<>old.id,closed:fresh.close,current:m.playbackFailureDialog.id,count:m.dialogCount})''')
  self.assertTrue(v['fresh']);self.assertTrue(v['closed']);self.assertEqual(3,v['count'])
 def test_physical_back_closes_owned_info_and_error_modal_even_after_owner_change(self):
  for change in ('','m.view="home":m.generation++'):
   v=self.scene('''PlayerShowFailure("detail",{}):d=m.top.dialog:d.buttonSelected=1:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 '''+change+'''
 handled=onKeyEvent("back",true)
 print FormatJson({handled:handled,closed:d.close,creates:m.deviceCreates})''')
   self.assertTrue(v['handled']);self.assertTrue(v['closed']);self.assertEqual(1,v['creates'])
 def test_device_info_is_explicit_on_demand_same_dialog_and_back_retains_error(self):
  v=self.scene('''PlayerShowFailure("prepare",{errorCode:"unsupported_device"})
 before=m.deviceCreates:d=m.top.dialog:d.buttonSelected=1:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 info=d.message:buttons=d.buttons
 d.buttonSelected=0:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({before:before,creates:m.deviceCreates,queries:m.global.queries,info:info.Split(Chr(10)),buttons:buttons,error:d.message,closed:d.close,count:m.dialogCount})''')
  self.assertEqual(0,v['before']);self.assertEqual(1,v['creates']);self.assertEqual(3,v['count'])
  self.assertEqual(4,len(v['queries']));self.assertEqual(['Back'],v['buttons']);self.assertIsNone(v['closed'])
  self.assertLessEqual(len(v['info']),11)
  v['info']='\n'.join(v['info'])
  self.assertIn('4660X',v['info']);self.assertIn('Capability only',v['info']);self.assertIn('HLG Unknown',v['info']);self.assertNotIn('private',v['info'])
  self.assertTrue(v['error'].startswith('#2015:'))
 def test_stale_dialog_and_changed_owner_cannot_probe_or_close_current_modal(self):
  for change in ('m.generation=4','m.sourceId="other"','m.profileId="other"','m.view="home"'):
   with self.subTest(change=change):
    v=self.scene('''PlayerShowFailure("prepare",{errorCode:"unsupported_device"})
 d=m.top.dialog:d.buttonSelected=1
 '''+change+'''
 onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({creates:m.deviceCreates,closed:d.close,title:d.title})''')
    self.assertEqual(0,v['creates']);self.assertTrue(v['closed']);self.assertEqual('Playback error',v['title'])
  v=self.scene('''PlayerShowFailure("detail",{}):old=m.top.dialog:old.buttonSelected=1
 PlayerShowFailure("prepare",{errorCode:"unsupported_device"})
 onPlayerFailureChoice(FixtureEvent(old))
 print FormatJson({creates:m.deviceCreates,title:m.top.dialog.title})''')
  self.assertEqual(0,v['creates'])
 def test_missing_and_throwing_sdk_facts_are_independent_and_unknown(self):
  v=self.scene('''PlayerShowFailure("detail",{}):d=m.top.dialog:d.buttonSelected=1
 onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({lines:d.message.Split(Chr(10)),queries:m.global.queries})''',device='')
  self.assertIn('H264 Yes · HEVC No',v['lines'])
  self.assertEqual([{'codec':'mpeg4 avc'},{'codec':'hevc'},{'codec':'aac','container':'mp4','chcnt':2,'passthru':0},{'codec':'aac','container':'ts','chcnt':2,'passthru':0}],v['queries'])
 def test_optional_throw_and_malformed_result_do_not_hide_other_facts(self):
  v=self.scene('''PlayerShowFailure("detail",{}):d=m.top.dialog:d.buttonSelected=1:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({lines:d.message.Split(Chr(10)),queries:m.global.queries})''',device='throw')
  self.assertIn('HDR10 Unknown · HDR10+ Unknown',v['lines']);self.assertIn('H264 Unknown · HEVC Unknown',v['lines'])
  self.assertIn('AAC TS stereo Yes',v['lines']);self.assertEqual(4,len(v['queries']));self.assertNotIn('private',str(v))
 def test_late_report_ack_retains_snapshot_then_back_shows_ack_without_more_actions(self):
  v=self.scene('''m.provider="silo"
 PlayerShowFailure("prepare",{errorCode:"unsupported_device",report:{installationId:"fixture",playbackAttemptId:"fixture"}})
 d=m.top.dialog:d.buttonSelected=1:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog:snapshot=d.message
 PlayerResult("play_error_report",{ok:true},{reported:true},m.pending["1"].extra)
 same=d.message=snapshot:d.buttonSelected=0:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({same:same,error:d.message.Split(Chr(10)),requests:m.requestId,queries:m.global.queries.Count(),closed:d.close})''')
  self.assertTrue(v['same']);self.assertIn('Report sent to your Silo server.',v['error']);self.assertEqual(1,v['requests']);self.assertEqual(4,v['queries']);self.assertIsNone(v['closed'])

 def test_response_info_is_sanitized_snapshot_same_dialog_with_no_device_or_api_work(self):
  v=self.scene('''facts={httpStatus:201,protocol:"v3",outcome:"adaptation_unavailable",sessionId:"missing",playbackPlanPresent:false,playbackPlanObject:false,planSessionId:"unavailable",terminalShapeValid:true,token:"private-secret"}
 PlayerShowFailure("session",{errorCode:"allocation_identity_unknown",startResponseFacts:facts})
 d=m.top.dialog:original=d.buttons:facts.httpStatus=599:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 info=d.message:buttons=d.buttons:title=d.title
 d.buttonSelected=0:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({title:title,info:info.Split(Chr(10)),buttons:buttons,original:original,restored:d.buttons,error:d.message,devices:m.deviceCreates,requests:m.requestId,count:m.dialogCount,closed:d.close})''')
  self.assertEqual('Response info',v['title']);self.assertEqual(7,len(v['info']));self.assertIn('HTTP 201 · Protocol v3',v['info']);self.assertIn('Terminal shape valid Yes',v['info'])
  self.assertEqual(['OK','Device info','Response info'],v['original']);self.assertEqual(v['original'],v['restored']);self.assertEqual(['Back'],v['buttons'])
  self.assertEqual((0,0,3,None),(v['devices'],v['requests'],v['count'],v['closed']));self.assertNotIn('private-secret',str(v));self.assertIn('#3004',v['error'])

 def test_malformed_response_facts_keep_exact_two_button_ui_and_cannot_show_raw_text(self):
  for change in ('facts.protocol="private-secret"','facts.httpStatus="private-secret"','facts.terminalShapeValid="true"','facts.planSessionId="private-secret"','facts.Delete("outcome")'):
   with self.subTest(change=change):
    v=self.scene('''facts={httpStatus:200,protocol:"v3",outcome:"plan",sessionId:"invalid",playbackPlanPresent:true,playbackPlanObject:true,planSessionId:"null",terminalShapeValid:false}
 '''+change+'''
 PlayerShowFailure("session",{errorCode:"allocation_identity_unknown",startResponseFacts:facts})
 d=m.top.dialog:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({buttons:d.buttons,title:d.title,message:d.message,closed:d.close,requests:m.requestId,devices:m.deviceCreates})''')
    self.assertEqual(['OK','Device info'],v['buttons']);self.assertEqual('Playback error',v['title']);self.assertIsNone(v['closed']);self.assertNotIn('private-secret',str(v))

 def test_late_report_does_not_replace_response_info_and_new_failure_clears_snapshot(self):
  v=self.scene('''m.provider="silo"
 facts={httpStatus:200,protocol:"v3",outcome:"plan",sessionId:"missing",playbackPlanPresent:true,playbackPlanObject:true,planSessionId:"missing",terminalShapeValid:false}
 PlayerShowFailure("session",{errorCode:"allocation_identity_unknown",startResponseFacts:facts,report:{installationId:"fixture",playbackAttemptId:"fixture"}})
 d=m.top.dialog:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog:snapshot=d.message
 PlayerResult("play_error_report",{ok:true},{reported:true},m.pending["1"].extra)
 same=d.message=snapshot:d.buttonSelected=0:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog:ack=d.message
 PlayerShowFailure("detail",{}):d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({same:same,ack:ack.Split(Chr(10)),buttons:m.top.dialog.buttons,requests:m.requestId,devices:m.deviceCreates,snapshot:m.playbackFailureResponseFacts})''')
  self.assertTrue(v['same']);self.assertIn('Report sent','\n'.join(v['ack']));self.assertEqual(['OK','Device info'],v['buttons']);self.assertEqual(1,v['requests']);self.assertEqual(0,v['devices']);self.assertIsNone(v['snapshot'])

 def test_valid_facts_offer_optional_response_button(self):
  v=self.scene('''PlayerShowFailure("session",{errorCode:"allocation_identity_unknown",startResponseFacts:{httpStatus:200,protocol:"v3",outcome:"plan",sessionId:"missing",playbackPlanPresent:true,playbackPlanObject:true,planSessionId:"missing",terminalShapeValid:false}})
 print FormatJson(m.top.dialog.buttons)''')
  self.assertEqual(['OK','Device info','Response info'],v)

 def test_response_info_owner_and_node_fences_and_display_resanitization(self):
  for change in ('m.generation=4','m.sourceId="other"','m.profileId="other"','m.provider="silo"','m.view="home"','m.playbackFailureResponseFacts.outcome="private-secret"'):
   with self.subTest(change=change):
    v=self.scene('''facts={httpStatus:200,protocol:"v3",outcome:"plan",sessionId:"missing",playbackPlanPresent:true,playbackPlanObject:true,planSessionId:"missing",terminalShapeValid:false}
 PlayerShowFailure("session",{errorCode:"allocation_identity_unknown",startResponseFacts:facts})
 d=m.top.dialog:d.buttonSelected=2
 '''+change+'''
 onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({title:d.title,message:d.message,closed:d.close,requests:m.requestId,devices:m.deviceCreates})''')
    self.assertEqual('Playback error',v['title']);self.assertNotIn('private-secret',str(v));self.assertEqual(None if 'Facts.outcome' in change else True,v['closed']);self.assertEqual((0,0),(v['devices'],v['requests']))

 def test_response_info_states_no_cleanup_authority_and_handles_unknown_http(self):
  v=self.scene('''PlayerShowFailure("session",{errorCode:"allocation_identity_unknown",startResponseFacts:{httpStatus:"unknown",protocol:"invalid",outcome:"invalid",sessionId:"null",playbackPlanPresent:true,playbackPlanObject:false,planSessionId:"unavailable",terminalShapeValid:false}})
 d=m.top.dialog:d.buttonSelected=2:onPlayerFailureChoice(FixtureEvent(d)):d=m.top.dialog
 print FormatJson({lines:d.message.Split(Chr(10)),requests:m.requestId,devices:m.deviceCreates})''')
  self.assertLessEqual(len(v['lines']),8);self.assertIn('HTTP unknown','\n'.join(v['lines']));self.assertIn('Facts do not confirm cleanup.',v['lines']);self.assertEqual((0,0),(v['requests'],v['devices']))
