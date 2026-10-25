"""Whole-edition native Audio admission through actual Task detail dispatch."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from tests import test_silo_ui_audio as audio
ROOT, POLICY, SILO, ADAPTER = audio.ROOT, audio.POLICY, audio.SILO, audio.ADAPTER
from tools.brightscript import run_brightscript

class AudiobookEditions(unittest.TestCase):
 def detail(self, raw, start=None):
  with tempfile.TemporaryDirectory() as directory:
   folder=Path(directory)
   task=folder/'task.brs'
   task.write_text((ROOT/'components/TaskSiloAudio.brs').read_text().replace('CreateObject("roDeviceInfo")','FixtureAudioDevice()'))
   api=folder/'api.brs'
   api.write_text(re.sub(r'function TaskSiloFetch\(.*?\nend function', '', (ROOT/'components/ApiTask.brs').read_text().replace('CreateObject("roDeviceInfo")','FixtureAudioDevice()'),count=1,flags=re.S))
   boundary=folder/'boundary.brs'
   boundary.write_text('''
function SessionRevision(provider as String) as Integer
 return 1
end function
function HttpRequest(request as Object, timeout as Integer) as Object
 if Instr(1,request.url,"/playback/capabilities") > 0
  return {ok:true,body:FormatJson({state:"available",allowed:true,protocol_versions:[3],deliveries:["original_http"],installation_id:"install-fixture"})}
 end if
 return {ok:true,body:FormatJson(m.raw)}
end function
function TaskSiloFetch(session as Object, action as String, params as Object, revision as Integer, timeout as Integer) as Object
 m.posted={fileId:params.fileId,startPositionMs:params.startPositionMs,allowAlternateVersions:params.allowAlternateVersions}
 return {ok:false,errorCode:"fixture_stop"}
end function
function FixtureAudioDevice() as Object
 return {GetRandomUUID:function() as String
  return "attempt-fixture"
 end function,GetModel:function() as String
  return "fixture"
 end function,CanDecodeAudio:function(format as Object) as Object
  return {result:format.codec="mp3" and format.container="mp3" and format.passthru=0}
 end function}
end function
''')
   params={'itemId':'audiobook:book'} if start is None else dict(itemId='audiobook:book',**start)
   arguments=json.dumps(params).replace('"','""')
   action='audio_detail' if start is None else 'audio_start'
   payload=json.dumps(raw).replace('"','""')
   out=run_brightscript([POLICY,SILO,ADAPTER,ROOT/'source/core/SiloPlaybackPolicy.brs',api,task,boundary],f'''
    m.raw=ParseJson("{payload}")
    session={{baseUrl:"https://fixture.example",accessToken:"fixture",profileId:"p",sourceId:"silo:test"}}
    result=TaskAudioAction(session,"{action}",ParseJson("{arguments}"),{{sourceId:"silo:test",profileId:"p"}},1)
    print FormatJson({{outcome:result,posted:m.posted}})
   ''',root=folder)
   result=json.loads(out)
   return result["outcome"] if start is None else result
 def variants(self):
  raw=audio.AudioTests().detail()
  alternate=copy.deepcopy(raw['playback_variants'][0]);alternate['variant_id']='alternate'
  for i,part in enumerate(alternate['parts']):
   part['default_file_id']=f'a{i+1}';part['versions'][0]['file_id']=f'a{i+1}'
  for part in raw['playback_variants'][0]['parts']:
   part['versions'][0].update(codec_audio='opus',container='ogg')
  raw['playback_variants'].append(alternate)
  return raw
 def test_unsupported_default_uses_complete_compatible_edition_at_start(self):
  raw=self.variants();raw['user_data']['position_seconds']=0
  result=self.detail(raw)
  self.assertTrue(result['ok'],result)
  self.assertEqual(['a1','a2'],[p['fileId'] for p in result['data']['queue']])
  self.assertEqual('alternate',result['data']['variantId'])
  self.assertEqual(0,result['data']['resumeMs'])
  self.assertEqual([0,60000],[p['offsetMs'] for p in result['data']['queue']])
 def test_saved_resume_uses_interchangeable_files_inside_same_presentation(self):
  raw=self.variants();first=raw['playback_variants'][0];alternate=raw['playback_variants'].pop()
  for part,other in zip(first['parts'],alternate['parts']):part['versions'].extend(other['versions'])
  result=self.detail(raw)
  self.assertTrue(result['ok'],result)
  self.assertEqual(['a1','a2'],[p['fileId'] for p in result['data']['queue']])
  self.assertEqual('v',result['data']['variantId'])
  self.assertEqual(75000,result['data']['resumeMs'])
  self.assertEqual([0,60000],[p['offsetMs'] for p in result['data']['queue']])
 def test_incomplete_candidate_is_skipped_without_borrowing_parts(self):
  raw=self.variants();raw['user_data']['position_seconds']=0
  incomplete=copy.deepcopy(raw['playback_variants'][1]);incomplete['parts'].pop()
  raw['playback_variants'].insert(1,incomplete)
  result=self.detail(raw)
  self.assertTrue(result['ok'],result)
  self.assertEqual(['a1','a2'],[p['fileId'] for p in result['data']['queue']])
 def test_unsupported_editions_cannot_be_combined_into_playable_book(self):
  raw=self.variants();raw['user_data']['position_seconds']=0
  raw['playback_variants'][0]['parts'][0]['versions'][0].update(codec_audio='mp3',container='mp3')
  raw['playback_variants'][1]['parts'][0]['versions'][0].update(codec_audio='opus',container='ogg')
  self.assertFalse(self.detail(raw)['ok'])
 def test_saved_resume_never_auto_switches_to_another_presentation(self):
  self.assertFalse(self.detail(self.variants())['ok'])
 def test_saved_resume_rejects_changed_part_timeline_inside_presentation(self):
  raw=self.variants();first=raw['playback_variants'][0];alternate=raw['playback_variants'].pop()
  for part,other in zip(first['parts'],alternate['parts']):
   other['versions'][0]['duration']+=1;part['versions'].extend(other['versions'])
  self.assertFalse(self.detail(raw)['ok'])
 def test_declared_missing_final_part_cannot_pass_observed_part_count(self):
  raw=audio.AudioTests().detail()
  for part in raw['playback_variants'][0]['parts']:
   part['versions'][0]['presentation_part_total']=3
  self.assertFalse(self.detail(raw)['ok'])

 def test_start_revalidates_whole_presentation_and_binds_requested_file(self):
  raw=self.variants();first=raw['playback_variants'][0];alternate=raw['playback_variants'].pop()
  for part,other in zip(first['parts'],alternate['parts']):part['versions'].extend(other['versions'])
  selected=self.detail(raw,start={'fileId':'a2','startPositionMs':15000})
  self.assertEqual('fixture_stop',selected['outcome']['errorCode'])
  self.assertEqual('a2',selected['posted']['fileId'])
  self.assertEqual(15000,selected['posted']['startPositionMs'])
  self.assertFalse(selected['posted']['allowAlternateVersions'])
  refused=self.detail(raw,start={'fileId':'p2','startPositionMs':15000})
  self.assertFalse(refused['outcome']['ok'])
  self.assertIsNone(refused['posted'])
 def test_missing_initial_part_is_incomplete(self):
  raw=audio.AudioTests().detail()
  for part in raw['playback_variants'][0]['parts']:part['part_index']+=1
  self.assertFalse(self.detail(raw)['ok'])
 def test_incomplete_default_does_not_hide_complete_edition_at_zero_progress(self):
  raw=self.variants();raw['user_data']['position_seconds']=0
  raw['playback_variants'][0]['parts'].pop()
  result=self.detail(raw)
  self.assertTrue(result['ok'],result)
  self.assertEqual(['a1','a2'],[p['fileId'] for p in result['data']['queue']])
 def test_legacy_single_file_keeps_declared_one_based_part_identity(self):
  raw=audio.AudioTests().detail();version=raw.pop('playback_variants')[0]['parts'][0]['versions'][0]
  version.update(presentation_part_index=1,presentation_part_total=1)
  raw['versions']=[version];raw['user_data']['position_seconds']=15
  result=self.detail(raw)
  self.assertTrue(result['ok'],result)
  self.assertEqual(['p1'],[p['fileId'] for p in result['data']['queue']])
 def test_selected_edition_continues_after_whole_book_progress_is_saved(self):
  selected=self.detail(self.variants(),start={'fileId':'a2','startPositionMs':15000})
  self.assertEqual('fixture_stop',selected['outcome']['errorCode'])
  self.assertEqual('a2',selected['posted']['fileId'])
  self.assertEqual(15000,selected['posted']['startPositionMs'])
 def test_zero_progress_rejects_alternates_that_change_future_part_timeline(self):
  raw=self.variants();raw['user_data']['position_seconds']=0
  first=raw['playback_variants'][0];alternate=raw['playback_variants'].pop()
  for part,other in zip(first['parts'],alternate['parts']):
   other['versions'][0]['duration']+=1;part['versions'].extend(other['versions'])
  self.assertFalse(self.detail(raw)['ok'])
