"""Persistent holder commands against source-shaped stock P7 DTOs; host seams only."""
import copy,json,unittest
from pathlib import Path
from tests import test_silo_compat_playback_task as holder
ROOT=Path(__file__).resolve().parents[1]
KIND='experimental_query_p7_hdr10_fmp4_v1'
AAC_KIND='experimental_query_p7_hdr10_aac_fmp4_v1'
AAC_QUALIFICATION_KIND='stock48ae-p7-hdr10-aac2-v1'
AAC_QUALIFICATION={'schemaVersion':1,'kind':AAC_QUALIFICATION_KIND,'approved':True,'sourceId':'silo:https://silo.example','profileId':'fixture-owner','generation':7,'sessionRevision':0}

class P7CompatHolder(unittest.TestCase):
 def transcript(self,mutate=None,*,aac=False,qualification=AAC_QUALIFICATION,include_qualification=True,start=25000,**kwargs):
  technical=json.loads((ROOT/'tests/fixtures/silo/stock_p7_hdr10_technical_metadata.json').read_text())
  def change(values):
   version=copy.deepcopy(technical['native_version']);version['file_id']='731'
   values['detail']['versions']=[version]
   metadata=copy.deepcopy(technical['compat_metadata']);receipt=copy.deepcopy(technical['compat_receipt'])
   metadata['Id']=receipt['Id']=holder.SOURCE
   if aac:
    receipt['DefaultAudioStreamIndex']=1
    for stream in receipt['MediaStreams']:
     if stream['Type']=='Audio':stream['IsDefault']=stream['Index']==1
   receipt['TranscodingUrl']='/Videos/'+holder.SOURCE+'/remux-dv-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId='+holder.SOURCE
   values['metadata']={'MediaSources':[metadata]};values['playback']={'PlaySessionId':'play-fixture','MediaSources':[receipt]}
   if mutate:mutate(values)
  device={'format.codec="eac3" and format.chcnt<=6':'(format.codec="eac3" or format.codec="ac3") and format.chcnt<=6'}
  options={'eligibilityKind':AAC_KIND if aac else KIND,'startPositionMs':start}
  if aac:options.update(audioTrackId='file:731:audio:0',audioTrackIndex=0)
  if aac and include_qualification:options['instanceQualification']=qualification
  return holder.CompatPlaybackTask().transcript(change=change,options=options,device_overrides=device,**kwargs)
 def aac_commands(self,*,bind_qualification=AAC_QUALIFICATION,seek_qualification=AAC_QUALIFICATION):
  def expression(value):
   return 'ParseJson("'+json.dumps(value,separators=(',',':')).replace('"','""')+'","i")'
  bind='command.instanceQualification='+expression(bind_qualification) if bind_qualification is not None else ''
  seek='command.instanceQualification='+expression(seek_qualification) if seek_qualification is not None else ''
  schedule='''if m.sceneData=invalid
  r=m.top.result
  if r.planGeneration<>invalid then m.fixturePlanGeneration=r.planGeneration
  command={action:"close",commandId:"close-"+r.phase,holderId:"holder-1",attemptId:"attempt-1",owner:m.owner,localRetired:true,planGeneration:m.fixturePlanGeneration,positionMs:25000,isPaused:false}
  if r.phase="prepared"
   command.action="bind":command.commandId="bind-"+r.planGeneration.ToStr():command.bindingNonce="binding-"+r.planGeneration.ToStr():command.eligibilityKind="AAC_KIND"
   BIND_QUALIFICATION
  else if r.phase="binding"
   command.action="playing":command.commandId="playing-"+r.planGeneration.ToStr()
  else if r.phase="playing" and r.planGeneration<2
   command.action="seek":command.commandId="seek-"+r.planGeneration.ToStr():command.targetPositionMs=120000:command.startPaused=false:command.eligibilityKind="AAC_KIND"
   SEEK_QUALIFICATION
  end if
  m.top.command=command
 end if'''
  schedule=schedule.replace('AAC_KIND',AAC_KIND).replace('BIND_QUALIFICATION',bind).replace('SEEK_QUALIFICATION',seek)
  return {'if m.sceneData=invalid and m.top.result.phase="prepared" then m.top.command={action:"close",commandId:"close-1",holderId:"holder-1",attemptId:"attempt-1",owner:m.owner}':schedule}
 def commands(self,mode='roundtrip'):
  schedule='''if m.sceneData=invalid
  r=m.top.result
  if r.planGeneration<>invalid then m.fixturePlanGeneration=r.planGeneration
  command={action:"close",commandId:"close-"+r.phase,holderId:"holder-1",attemptId:"attempt-1",owner:m.owner,localRetired:true,planGeneration:m.fixturePlanGeneration,positionMs:25000,isPaused:false}
  if r.phase="prepared"
   command.action="bind":command.commandId="bind-"+r.planGeneration.ToStr():command.bindingNonce="binding-"+r.planGeneration.ToStr():command.eligibilityKind="experimental_query_p7_hdr10_fmp4_v1"
   if "MODE"="missing_bind" then command.Delete("eligibilityKind")
  else if r.phase="binding"
   command.action="playing":command.commandId="playing-"+r.planGeneration.ToStr()
  else if r.phase="playing" and r.planGeneration<3
   command.action="seek":command.commandId="seek-"+r.planGeneration.ToStr():command.targetPositionMs=120000:command.startPaused=false:command.eligibilityKind="experimental_query_p7_hdr10_fmp4_v1"
   if r.planGeneration=2 then command.targetPositionMs=60000
   if "MODE"="wrong_seek" then command.eligibilityKind="experimental_query_p8_ts_v1"
  end if
  m.top.command=command
 end if'''.replace('MODE',mode)
  return {'if m.sceneData=invalid and m.top.result.phase="prepared" then m.top.command={action:"close",commandId:"close-1",holderId:"holder-1",attemptId:"attempt-1",owner:m.owner}':schedule}
 def test_public_stock_transport_stays_unqualified_without_redirect_proof(self):
  def root_origin(v):v['discovery']['jellyfin']['public_url']='https://compat.example'
  result=self.transcript(mutate=root_origin,start=0)
  self.assertNotIn('stockQualification',result['results'][0])
 def test_prepared_holder_derives_bound_stock_authority_without_qa_injection(self):
  def root_origin(v):v['discovery']['jellyfin']['public_url']='https://compat.example'
  result=self.transcript(mutate=root_origin,start=0,transport_origin="https://compat.example")
  prepared=result['results'][0]
  self.assertIn('stockQualification',prepared)
  q=prepared['stockQualification']
  self.assertEqual('731',q['fileId'])
  self.assertEqual(1,q['audioOrdinal'])
  self.assertEqual(2,q['audioStreamIndex'])
  self.assertEqual('https://compat.example',q['origin'])
  self.assertNotIn('token',str(q).lower())
 def test_bind_play_reanchor_generations_and_close_keep_p7_kind_class_and_audio(self):
  result=self.transcript(sdk_overrides=self.commands())
  self.assertEqual(['prepared','binding','playing','prepared','binding','playing','prepared','binding','playing','closed'],[r['phase'] for r in result['results']],result)
  for r in result['results']:
   self.assertTrue(r['ok'],r)
   if r['phase']=='prepared':self.assertEqual('copied_p7_hdr10_fmp4',r['class'])
  self.assertTrue(result['results'][-1]['credentialRevoked']);self.assertTrue(result['results'][-1]['mediaClosed']);self.assertTrue(result['privateCleared'])
  requests=[q for q in result['requests'] if '/PlaybackInfo' in q['url']]
  self.assertEqual(3,len(requests))
  self.assertEqual([250000000,1200000000,600000000],[json.loads(q['body'])['StartTimeTicks'] for q in requests])
  for q in requests:
   body=json.loads(q['body']);self.assertEqual((2,-1),(body['AudioStreamIndex'],body['SubtitleStreamIndex']))
  self.assertEqual(3,sum('/Sessions/Playing/Stopped' in q['url'] for q in result['requests']))
  self.assertEqual(3,sum('/Videos/ActiveEncodings?' in q['url'] for q in result['requests']))

 def lower_params(self):
  key=' m.top={command:{action:"prepare"'
  return {key:' lower={}\n for each key in params\n  lower[LCase(key)]=params[key]\n end for\n params=ParseJson(FormatJson(lower))\n'+key}
 def test_serialized_lowercase_p7_selectors_keep_exact_request(self):
  result=self.transcript(sdk_overrides=self.lower_params())
  self.assertEqual(['prepared','closed'],[r['phase'] for r in result['results']],result)
  request=next(q for q in result['requests'] if '/PlaybackInfo' in q['url'])
  self.assertEqual(2,json.loads(request['body'])['AudioStreamIndex'])
 def test_explicit_null_lowercase_kind_cannot_downgrade_to_legacy(self):
  overrides=self.lower_params()
  null_params=dict(itemid='fixture-item',fileid='731',audiotrackid='file:731:audio:1',audiotrackindex=1,subtitlemode='off',qualitypreference='original',startpositionms=25000,eligibilitykind=None)
  serialized=json.dumps(null_params).replace('"','""')
  overrides={k:v.replace('params=ParseJson(FormatJson(lower))','params=ParseJson("'+serialized+'")') for k,v in overrides.items()}
  result=holder.CompatPlaybackTask().transcript(options={'eligibilityKind':None},sdk_overrides=overrides)
  self.assertFalse(any('/QuickConnect/Initiate' in q['url'] for q in result['requests']),result)
  self.assertFalse(result['results'][-1]['ok'])
 def test_missing_bind_or_wrong_seek_kind_refuses_but_owned_close_still_revokes(self):
  for mode,phase,negotiations in [('missing_bind','binding_refused',1),('wrong_seek','seek_refused',1)]:
   with self.subTest(mode=mode):
    result=self.transcript(sdk_overrides=self.commands(mode))
    self.assertIn(phase,[r['phase'] for r in result['results']])
    self.assertEqual('closed',result['results'][-1]['phase']);self.assertTrue(result['results'][-1]['credentialRevoked']);self.assertTrue(result['privateCleared'])
    self.assertEqual(negotiations,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
 def test_reanchor_rejects_changed_unselected_inventory_before_second_negotiation(self):
  def mutate(values):
   values['reanchorDetail']=copy.deepcopy(values['detail']);values['reanchorDetail']['versions'][0]['audio_tracks'][2]['language']='fr'
  overrides=self.commands()
  key='if m.fixtureDetailCount>1 then body=FormatJson(m.values["native/reanchor_detail"])'
  overrides[key]=key+'\n  if m.fixtureDetailCount>1 then m.values["compat/metadata"].MediaSources[0].MediaStreams[3]["Language"]="fr"'
  result=self.transcript(mutate=mutate,sdk_overrides=overrides)
  self.assertIn('seek_refused',[r['phase'] for r in result['results']],result)
  self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
  self.assertTrue(result['privateCleared']);self.assertTrue(result['results'][-1]['credentialRevoked'])

 def test_wrong_allocated_ts_receipt_revokes_without_releasing_binding(self):
  def mutate(values):values['playback']['MediaSources'][0]['TranscodingContainer']='ts'
  result=self.transcript(mutate=mutate)
  self.assertEqual(['refused'],[r['phase'] for r in result['results']])
  self.assertEqual('unsafe_recipe',result['results'][0]['errorCode']);self.assertTrue(result['results'][0]['credentialRevoked'])
  self.assertTrue(result['privateCleared']);self.assertFalse(any('/Sessions/Playing' in q['url'] for q in result['requests']))
  self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))

 def test_prepare_p7_uses_exact_selected_ac3_off_and_retires_unused_credential(self):
  result=self.transcript()
  self.assertEqual(['prepared','closed'],[r['phase'] for r in result['results']],result)
  self.assertEqual('copied_p7_hdr10_fmp4',result['results'][0]['class'])
  request=next(q for q in result['requests'] if '/PlaybackInfo' in q['url']);body=json.loads(request['body'])
  self.assertEqual((holder.SOURCE,2,-1),(body['MediaSourceId'],body['AudioStreamIndex'],body['SubtitleStreamIndex']))
  self.assertTrue(body['AllowAudioStreamCopy']);self.assertNotIn('MaxAudioChannels',body)
  self.assertEqual('mp4',body['DeviceProfile']['TranscodingProfiles'][0]['Container'])
  self.assertEqual('ac3',body['DeviceProfile']['TranscodingProfiles'][0]['AudioCodec'])
  self.assertEqual('Bearer '+holder.TOKEN,request['headers']['Authorization']);self.assertNotIn(holder.TOKEN,request['url'])
  self.assertTrue(result['results'][-1]['credentialRevoked']);self.assertTrue(result['privateCleared'])
  self.assertEqual(0,result['mediaRequests']);self.assertFalse(any('.m3u8' in q['url'] for q in result['requests']))

 def test_aac_qualification_survives_prepare_bind_seek_and_owned_close(self):
  result=self.transcript(aac=True,sdk_overrides=self.aac_commands())
  self.assertNotIn('fixtureError',result,result)
  self.assertEqual(['prepared','binding','playing','prepared','binding','playing','closed'],[r['phase'] for r in result['results']],result)
  prepared=[r for r in result['results'] if r['phase']=='prepared']
  self.assertEqual(['converted_p7_hdr10_aac_fmp4']*2,[r['class'] for r in prepared])
  self.assertEqual([True,False],[r['mediaNeverRequested'] for r in prepared])
  requests=[q for q in result['requests'] if '/PlaybackInfo' in q['url']]
  self.assertEqual(2,len(requests))
  for request in requests:
   body=json.loads(request['body'])
   profile=body['DeviceProfile']['TranscodingProfiles'][0]
   self.assertEqual((holder.SOURCE,1,-1),(body['MediaSourceId'],body['AudioStreamIndex'],body['SubtitleStreamIndex']))
   self.assertFalse(body['AllowAudioStreamCopy']);self.assertEqual(2,body['MaxAudioChannels'])
   self.assertEqual(('hls','mp4','aac','2'),(profile['Protocol'],profile['Container'],profile['AudioCodec'],profile['MaxAudioChannels']))
  self.assertEqual(0,result['mediaRequests']);self.assertFalse(any('.m3u8' in q['url'] for q in result['requests']))
  self.assertTrue(result['results'][-1]['credentialRevoked']);self.assertTrue(result['results'][-1]['mediaClosed']);self.assertTrue(result['privateCleared'])

 def test_aac_qualification_is_required_at_prepare_and_rechecked_at_bind_and_seek(self):
  missing=self.transcript(aac=True,include_qualification=False)
  self.assertEqual('refused',missing['results'][-1]['phase'],missing)
  self.assertFalse(any('/compat/connect-info' in q['url'] or '/QuickConnect/Initiate' in q['url'] or '/PlaybackInfo' in q['url'] for q in missing['requests']))
  self.assertTrue(missing['privateCleared'])
  stale=copy.deepcopy(AAC_QUALIFICATION);stale['sessionRevision']=1
  for action in ('bind','seek'):
   with self.subTest(action=action):
    result=self.transcript(aac=True,sdk_overrides=self.aac_commands(bind_qualification=stale if action=='bind' else AAC_QUALIFICATION,seek_qualification=stale if action=='seek' else AAC_QUALIFICATION))
    phase='binding_refused' if action=='bind' else 'seek_refused'
    self.assertIn(phase,[r['phase'] for r in result['results']],result)
    self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in result['requests']))
    self.assertTrue(result['results'][-1]['credentialRevoked']);self.assertTrue(result['privateCleared'])

if __name__=='__main__':unittest.main()
