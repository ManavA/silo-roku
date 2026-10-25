"""Quality/file changes execute the one existing replacement owner."""
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.brightscript import run_function
from tests.test_provider_audio import config,scope,status,select,stopped,terminal,bound,result,TRACE
C=Path(__file__).resolve().parents[1]
def context(kind='quality',landed=True,**kw):
 v=config(landed=landed);v['changeKind']=kind;v['detail']['versionsComplete']=True
 first=v['detail']['versions'][0]
 first.update(sourceId='plex:source',itemId='1',mediaId='10',partId='100',partCount=1,durationMs=600000,container='mp4',videoCodec='h264',width=1920,height=1080)
 other={**first,'versionId':'file-2','mediaId':'20','partId':'200','mediaIndex':1,'audio':[]}
 v['detail']['versions'].append(other)
 v['session']['plan']['clientIntent']={'schemaVersion':1,'sourceId':'plex:source','itemId':'1','versionId':'file-1','owedStartMs':90000,'forceCompatible':False,'maxVideoBitrate':8000,'videoResolution':'1920x1080','audioStreamId':'22'}
 v.update(kw);return v
class ReplacementTests(unittest.TestCase):
 def trace(self,*events,ctx=None):
  with tempfile.TemporaryDirectory(prefix='silo_ui-replacement-') as d:
   p=Path(d)/'trace.brs';p.write_text(TRACE)
   files=[C/'tests/fixtures/legacy_policy_values.brs',C/'source/core/VideoOwnerPolicy.brs',C/'source/core/ProviderAudioPolicy.brs']
   helper=C/'source/core/PlexReplacementPolicy.brs'
   if helper.exists():files.append(helper)
   return run_function([*files,p],'ProviderAudioTrace',[ctx or context(),events],root=Path(d))
 def effects(self,rows,kind):return [e for row in rows for e in row['effects'] if e['kind']==kind]
 def pick(self,handle,**kw):return select(handle=handle,**kw)
 def test_quality_projection_is_requested_caps_and_does_not_export_private_file_or_auth(self):
  p=self.trace()[0]['projection'];self.assertTrue(p['available'])
  self.assertEqual(['Auto','Up to 720p / 4 Mbps','Up to 1080p / 8 Mbps','Up to 1080p / 20 Mbps'],[x['label'] for x in p['choices']])
  self.assertTrue(p['choices'][2]['selected'])
  for secret in ['sourceId','partId','mediaId','audioStreamId','synthetic-private','width','height']:self.assertNotIn(secret,str(p))
 def test_auto_keeps_actual_carried_audio_and_force_compatible_and_waits_both_barriers(self):
  c=context();c['session']['plan']['clientIntent']['forceCompatible']=True
  for receipts in [(stopped(),terminal()),(terminal(),stopped())]:
   rows=self.trace(self.pick('pr-1-0'),*receipts,ctx=c)
   req=self.effects(rows,'request');self.assertEqual(1,len(req));params=req[0]['params']
   self.assertEqual('22',params['audioStreamId']);self.assertTrue(params['forceTranscode'])
   self.assertNotIn('maxVideoBitrate',params);self.assertNotIn('videoResolution',params)
   self.assertEqual({'sourceId':'plex:source','itemId':'1','mediaId':'10','partId':'100','versionId':'file-1'},params['replacementFile'])
 def test_audio_replacement_retains_explicit_cap_and_records_exact_selected_lane(self):
  c=context('audio');rows=self.trace(select(),stopped(),terminal(),ctx=c)
  self.assertEqual(1,len(self.effects(rows,'request')))
  req=self.effects(rows,'request')[0]['params']
  self.assertIn('maxVideoBitrate',req);self.assertIn('videoResolution',req)
  self.assertEqual((8000,'1920x1080','22'),(req['maxVideoBitrate'],req['videoResolution'],req['audioStreamId']))
 def test_version_switch_unlanded_keeps_owed_resume_and_rejects_carried_foreign_audio_before_close(self):
  c=context('version',landed=False)
  denied=self.trace(self.pick('pr-1-1',landed=False),ctx=c);self.assertEqual([],self.effects(denied,'close'))
  del c['session']['plan']['clientIntent']['audioStreamId']
  rows=self.trace(self.pick('pr-1-1',landed=False),stopped(),terminal(),ctx=c)
  self.assertEqual(1,len(self.effects(rows,'request')))
  self.assertEqual(90000,self.effects(rows,'request')[0]['params']['startPositionMs'])
  self.assertEqual('file-2',self.effects(rows,'request')[0]['params']['versionId'])
  self.assertNotIn('confirmedPositionMs',self.effects(rows,'close')[0])
 def test_missing_ambiguous_multipart_or_too_short_file_cannot_close_decoder(self):
  for change in [{'partCount':2},{'durationMs':90000},{'mediaId':''}]:
   c=context('version');del c['session']['plan']['clientIntent']['audioStreamId'];c['detail']['versions'][1].update(change)
   rows=self.trace(self.pick('pr-1-1'),ctx=c);self.assertEqual([],self.effects(rows,'close'))
  c=context('version');del c['session']['plan']['clientIntent']['audioStreamId'];c['detail']['versions'].append(c['detail']['versions'][1])
  self.assertEqual([],self.effects(self.trace(self.pick('pr-1-1'),ctx=c),'close'))
 def test_accepted_queued_plan_cancel_releases_exact_new_lease_once_without_progress(self):
  rows=self.trace(select(),stopped(),terminal(),bound(),result(),{'kind':'cancel'},{'kind':'cancel'},ctx=config())
  self.assertTrue(rows[-3]['state'].get('installPending',False))
  clean=self.effects(rows,'cleanup');self.assertEqual(1,len(clean))
  self.assertEqual(('server-new','stop-1-late'),(clean[0]['plan']['sessionId'],clean[0]['stopId']))
  self.assertEqual(scope(sessionId='server-new'),rows[-1]['state']['lateCleanup']['scope'])
 def test_install_binding_requires_exact_operation_attempt_scope_and_version(self):
  base=[select(),stopped(),terminal(),bound(),result()]
  good={'kind':'install_bound','operationId':'audio-1','scope':scope(),'requestId':'new','versionId':'file-1'}
  for change in ({'operationId':'foreign'},{'requestId':'old'},{'versionId':'file-2'},{'scope':scope(profileId='child')}):
   row=self.trace(*base,{**good,**change},ctx=config())[-1]
   self.assertFalse(row['accepted']);self.assertTrue(row['state'].get('installPending',False))
  rows=self.trace(*base,good,{'kind':'cancel'},ctx=config())
  self.assertTrue(rows[-2]['accepted']);self.assertFalse(rows[-2]['state']['installPending'])
  self.assertEqual([],self.effects(rows,'cleanup'))
 def test_incomplete_inventory_cannot_open_replacement_or_close_current_decoder(self):
  c=context();c['detail']['versionsComplete']=False
  rows=self.trace(self.pick('pr-1-3'),ctx=c)
  self.assertFalse(rows[0]['projection']['available']);self.assertEqual([],self.effects(rows,'close'))
 def test_native_integer_alias_facade_keeps_real_numbers_and_rejects_invalid_file_facts(self):
  helper=C/'source/core/PlexReplacementPolicy.brs'
  for alias in ('roInteger','roLongInteger'):
   with tempfile.TemporaryDirectory(prefix='silo_ui-replacement-types-') as d:
    root=Path(d);p=root/'types.brs';source=helper.read_text().replace('type(','FixturePrType(')
    source+='\nfunction FixturePrType(v as Dynamic) as String\n k=Type(v)\n if k="Integer" or k="roInt" then return "'+alias+'"\n return k\nend function\nfunction FixturePrFacts(detail as Object,values as Object) as Object\n answers=[]\n for each value in values\n  answers.Push(PrNumber(value,604800000,true))\n end for\n return {file:PrFile(detail,"file-1",90000),answers:answers}\nend function\n'
    p.write_text(source);data=run_function(p,'FixturePrFacts',[context()['detail'],[7,True,'7',1.5,1e30,{},[]]],root=root)
    self.assertEqual(600000,data['file']['durationMs'])
    self.assertEqual(1,data['file']['version']['partCount']);self.assertEqual([True,False,False,False,False,False,False],data['answers'])
 def test_cancel_terminal_failure_and_optimistic_position_never_authorize_extra_allocation(self):
  rows=self.trace(self.pick('pr-1-3',native=status(position=300,renderedEpoch=1)),stopped(),terminal(False),{'kind':'cancel'},terminal())
  self.assertEqual([],self.effects(rows,'request'));self.assertEqual(1,len(self.effects(rows,'close')));self.assertEqual(92400,self.effects(rows,'close')[0]['confirmedPositionMs'])
if __name__=='__main__':unittest.main()
