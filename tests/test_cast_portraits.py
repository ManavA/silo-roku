import tempfile, unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
class CastPortraitTests(unittest.TestCase):
 def test_cast_cards_bound_labels_and_count_without_exposing_photo(self):
  people=[dict(personId='p',name='N'*200,role='Actor | Narrator',photo_url='https://secret.test/signed')]*10
  with tempfile.TemporaryDirectory() as tmp:
   result=run_function([ROOT/'source/core/SiloUIDetailPolicy.brs'],'SiloUICastPeople',[people],root=Path(tmp))
  self.assertEqual(len(result),8)
  self.assertEqual(result[0],dict(personId='p',name='N'*80,role='Actor , Narrator'))
 def test_person_metadata_identity_is_checked_and_image_headers_are_empty(self):
  import json
  with tempfile.TemporaryDirectory() as tmp:
   result=run_function([ROOT/'source/core/ArtworkPolicy.brs',ROOT/'source/core/PersonPhotoPolicy.brs'],'PersonPhotoRequest',['p',json.dumps(dict(id='p',photo_url='https://images.example.test/photo.jpg?signature=private'))],root=Path(tmp))
  self.assertTrue(result['ok'])
  self.assertEqual(result['headers'],{})
 def test_person_identity_mismatch_and_oversized_metadata_reject(self):
  import json
  for body in [json.dumps(dict(id='other',photo_url='https://example.test/a.jpg')),' '*32769,json.dumps(dict(id='p',photo_url='http://example.test/a.jpg'))]:
   with tempfile.TemporaryDirectory() as tmp:
    result=run_function([ROOT/'source/core/ArtworkPolicy.brs',ROOT/'source/core/PersonPhotoPolicy.brs'],'PersonPhotoRequest',['p',body],root=Path(tmp))
   self.assertFalse(result['ok'])
 def test_card_recycling_clears_previous_photo_before_new_loading(self):
  from tools.brightscript import run_brightscript
  import json
  with tempfile.TemporaryDirectory() as tmp:
   output=run_brightscript([ROOT/'components/CastCard.brs'],'''m.photo={}:m.initial={}:m.name={}:m.role={}
    c={personName:"First",personRole:"Role",photoUri:"tmp:/old.jpg",observeField:sub(a,b)
    end sub,unobserveField:sub(a)
    end sub}
    m.top={itemContent:c}:onContent():m.photo.loadStatus="ready":onPhoto():first=m.photo.visible
    c2={personName:"Next",personRole:"",photoUri:"",observeField:sub(a,b)
    end sub,unobserveField:sub(a)
    end sub}
    m.top.itemContent=c2:onContent()
    print FormatJson([first,m.photo.uri,m.photo.visible,m.name.text,m.initial.text])''',root=Path(tmp))
  self.assertEqual(json.loads(output),[True,'',False,'Next','N'])
 def test_photo_job_rejects_url_or_foreign_fields(self):
  job=dict(sourceId='silo:test',profileId='profile',generation=2,visit=3,itemId='movie',personId='person',index=0,requestId=4)
  for value,expected in [(job,True),({**job,'personId':'https://private.test'},False),({**job,'url':'https://private.test'},False),({**job,'index':8},False)]:
   with tempfile.TemporaryDirectory() as tmp:
    result=run_function([ROOT/'source/core/ArtworkPolicy.brs',ROOT/'source/core/PersonPhotoPolicy.brs'],'PersonPhotoJobValid',[value],root=Path(tmp))
   self.assertEqual(result,expected)
 def test_cards_have_bounded_geometry_and_separate_captions(self):
  import xml.etree.ElementTree as ET
  card=ET.parse(ROOT/'components/CastCard.xml').getroot()
  fields={n.get('id'):n for n in card.findall('./children/*')}
  self.assertEqual([fields['photo'].get(k) for k in ['width','height','loadWidth','loadHeight','loadDisplayMode']],['96','124','96','124','scaleToFit'])
  self.assertEqual([fields['name'].get(k) for k in ['width','height','maxLines']],['144','28','1'])
  self.assertEqual([fields['role'].get(k) for k in ['width','height','maxLines']],['144','44','2'])
  scene=ET.parse(ROOT/'components/SiloUIScene.xml').getroot().find('.//*[@id="detailCast"]')
  self.assertEqual((scene.tag,scene.get('itemComponentName'),scene.get('numRows')),('RowList','CastCard','1'))
 def worker(self, stage="", job_override=None, cleanup=None):

  import json
  job=dict(sourceId='silo:test',profileId='profile',generation=2,visit=3,itemId='movie',personId='person',index=0,requestId=4)
  if job_override is not None: job=job_override
  with tempfile.TemporaryDirectory() as tmp:
   tmp=Path(tmp)
   source=(ROOT/'components/PersonPhotoTask.brs').read_text()
   for name in ['PersonPhotoFetch','PersonPhotoInspectFile','PersonPhotoRenameFile']:
    source=source.replace('function '+name+'(','function Unused'+name+'(',1)
   source=source.replace('sub PersonPhotoDeleteFile(','sub UnusedPersonPhotoDeleteFile(',1)
   worker=tmp/'worker.brs';worker.write_text(source)
   boundary=tmp/'boundary.brs';boundary.write_text('''
function LoadSession(provider)
 if m.failureStage="registry" then throw "credentials must not be loaded"
 return {sourceId:"silo:test",profileId:"profile",baseUrl:"https://silo.example.test",accessToken:"private"}
end function
function SessionRevision(provider)
 return 5
end function
function HttpRequest(request,timeout)
 if m.failureStage="metadata" then throw "private metadata error"
 return {ok:true,body:FormatJson({id:"person",photo_url:"https://cdn.example.test/photo.jpg?signature=secret"})}
end function
function PersonPhotoFetch(request,timeout,path)
 if m.failureStage="download" then throw "private download error"
 m.headers=request.headers
 return {ok:true,contentType:"image/jpeg"}
end function
function PersonPhotoInspectFile(path)
 if m.failureStage="file" then throw "private file error"
 return {ok:true,encodedBytes:2048,firstBytesHex:"ffd8ffe000104a4649460001"}
end function
function PersonPhotoRenameFile(fromPath,toPath)
 return true
end function
sub PersonPhotoDeleteFile(path)
 m.deleted.Push(path)
 if m.failureStage="cleanup" then throw "private cleanup error"
end sub
function RunPhoto(job,stage,cleanup)
 m.failureStage=stage
 m.deleted=[]
 m.top={job:job,cancelled:false,cleanupPaths:cleanup}
 runPersonPhoto()
 return {result:m.top.result,headers:m.headers,deleted:m.deleted}
end function
''')
   files=[ROOT/'source/core/ServerUrlPolicy.brs',ROOT/'source/auth/SessionPolicy.brs',ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/core/ArtworkPolicy.brs',ROOT/'source/core/PersonPhotoPolicy.brs',worker,boundary]
   result=run_function(files,'RunPhoto',[job,stage,cleanup or []],root=tmp)
  return result
 def test_worker_publishes_only_owned_local_file_with_empty_image_headers(self):
  import json
  job=dict(sourceId='silo:test',profileId='profile',generation=2,visit=3,itemId='movie',personId='person',index=0,requestId=4)
  result=self.worker()
  self.assertEqual(result['headers'],{})
  self.assertEqual(result['result'],dict(owner=job,uri='tmp:/personphoto-2-4.jpg',sessionRevision=5))
  self.assertNotIn('secret',json.dumps(result))

 def test_worker_exceptions_publish_terminal_private_empty_result(self):
  import json
  for stage in ['metadata','download','file','cleanup']:
   with self.subTest(stage=stage):
    result=self.worker(stage)['result']
    self.assertEqual(result['uri'],'')
    self.assertEqual(result['owner']['personId'],'person')
    self.assertNotIn('private',json.dumps(result))
 def callback(self, revision, photo_uri="tmp:/personphoto-2-4.jpg"):
  import json
  from tools.brightscript import run_brightscript
  with tempfile.TemporaryDirectory() as tmp:
   tmp=Path(tmp)
   source=(ROOT/'components/SiloUIDetail.brs').read_text().replace('CreateObject("roSGNode", "PersonPhotoTask")','FakeTask()')
   source=source.replace('sub DetailPhotoDelete(uri as String)','sub UnusedDetailPhotoDelete(uri as String)')
   source=source.replace('function DetailPhotoSessionRevision()','function UnusedDetailPhotoSessionRevision()')
   fixture=tmp/'detail.brs';fixture.write_text(source+'''
function DetailPhotoSessionRevision()
 return m.revision
end function
sub DetailPhotoDelete(uri as String)
 m.deleted=uri
end sub
function FakeTask()
 return {observeField:sub(a,b)
 end sub}
end function
''')
   output=run_brightscript([fixture],'''
    m.revision='''+str(revision)+''':m.requestId=4:m.view="detail":m.sourceId="silo:test":m.profileId="profile":m.generation=2:m.detailVisit=3:m.detailItem={itemId:"movie"}
    m.card={personId:"person",photoUri:""}
    row={getChild:function(i)
     return m.card
    end function,card:m.card}
    m.detailCast={content:{getChild:function(i)
     return m.row
    end function,row:row}}
    owner={sourceId:"silo:test",profileId:"profile",generation:2,visit:3,itemId:"movie",personId:"person",index:0}
    task={cancelled:false,unobserveField:sub(a)
    end sub}
    event={getRoSGNode:function()
     return m.task
    end function,getData:function()
     return m.result
    end function,task:task,result:{owner:owner,uri:"tmp:/personphoto-2-4.jpg",sessionRevision:5}}
    m.detailPhotoTask=task:m.detailPhotoQueue=[{personId:"next",index:1}]
    onDetailPhoto(event)
    print FormatJson({uri:m.card.photoUri,deleted:m.deleted,next:m.detailPhotoTask.job.personId,queue:m.detailPhotoQueue.Count()})
'''.replace('uri:"tmp:/personphoto-2-4.jpg"','uri:'+json.dumps(photo_uri)),root=tmp)
  return json.loads(output)
 def test_scene_rejects_revision_changed_after_worker_completion_and_advances(self):
  result=self.callback(6)
  self.assertEqual(result,dict(uri='',deleted='tmp:/personphoto-2-4.jpg',next='next',queue=0))

 def test_terminal_worker_failure_allows_scene_to_start_next_person(self):
  for stage in ['metadata','download','file']:
   outcome=self.worker(stage)['result']
   result=self.callback(outcome['sessionRevision'],outcome['uri'])
   self.assertEqual((result['uri'],result['next'],result['queue']),('','next',0))

 def test_invalid_worker_job_never_echoes_unknown_private_fields(self):
  import json
  job=dict(sourceId='silo:test',profileId='profile',generation=2,visit=3,itemId='movie',personId='person',index=0,requestId=4,url='https://private.test/signed',token='secret-token')
  outcome=self.worker(job_override=job)['result']
  self.assertEqual(outcome,dict(owner={},uri='',sessionRevision=-1))
  self.assertNotIn('secret',json.dumps(outcome))
  self.assertNotIn('https:',json.dumps(outcome))
 def test_cast_border_clears_when_native_row_loses_focus_and_returns(self):
  from tools.brightscript import run_brightscript
  import json
  with tempfile.TemporaryDirectory() as tmp:
   output=run_brightscript([ROOT/'components/CastCard.brs'],'''m.border={}:m.top={focusPercent:1,rowFocusPercent:1,itemHasFocus:true,rowHasFocus:true}
    onFocus():focused=m.border.visible
    m.top.rowFocusPercent=0:onFocus():left=m.border.visible
    m.top.rowFocusPercent=1:onFocus():returned=m.border.visible
    m.top.rowHasFocus=false:onFocus():blurred=m.border.visible
    m.top.rowHasFocus=true:onFocus():refocused=m.border.visible
    print FormatJson([focused,left,returned,blurred,refocused])''',root=Path(tmp))
  self.assertEqual(json.loads(output),[True,False,True,False,True])

 def test_cleanup_worker_deletes_local_paths_without_loading_session(self):
  result=self.worker('registry',job_override={},cleanup=['tmp:/personphoto-2-4.jpg'])
  self.assertIn('tmp:/personphoto-2-4.jpg',result['deleted'])
  self.assertEqual(result['result'],dict(owner={},uri='',sessionRevision=-1))
 def test_scene_cleanup_runs_after_leave_profile_change_and_memory_pressure(self):
  import json
  from tools.brightscript import run_brightscript
  with tempfile.TemporaryDirectory() as tmp:
   tmp=Path(tmp)
   source=(ROOT/'components/SiloUIDetail.brs').read_text().replace('CreateObject("roSGNode", "PersonPhotoTask")','FakeTask()')
   fixture=tmp/'detail.brs';fixture.write_text(source+'''
function FakeTask()
 return {observeField:sub(a,b)
 end sub,unobserveField:sub(a)
 end sub}
end function
''')
   output=run_brightscript([fixture],'''
    m.view="home":m.memoryHigh=true:m.profileId="changed":m.detailPhotoQueue=[]
    card={photoUri:"tmp:/personphoto-2-4.jpg"}
    row={card:card,getChildCount:function()
     return 1
    end function,getChild:function(i)
     return m.card
    end function}
    m.detailCast={content:{row:row,getChild:function(i)
     return m.row
    end function}}
    old=FakeTask():m.detailPhotoTask=old
    DetailPhotosClear()
    cleared=card.photoUri:cancelled=old.cancelled
    event={task:old,result:{owner:{},uri:"tmp:/personphoto-2-5.jpg",sessionRevision:4},getData:function()
     return m.result
    end function,getRoSGNode:function()
     return m.task
    end function}
    onDetailPhoto(event)
    print FormatJson([cleared,cancelled,m.detailPhotoTask.cleanupPaths,m.detailPhotoTask.job,m.detailPhotoQueue])
''',root=tmp)
  self.assertEqual(json.loads(output),['',True,['tmp:/personphoto-2-4.jpg','tmp:/personphoto-2-5.jpg'],{},[]])
 def test_cleanup_worker_bounds_and_validates_paths_and_remains_terminal_on_file_error(self):
  valid=['tmp:/personphoto-2-'+str(i)+'.jpg' for i in range(9)]
  result=self.worker('registry',job_override={},cleanup=valid)
  self.assertEqual([p for p in result['deleted'] if p],valid[:8])
  result=self.worker('cleanup',job_override={},cleanup=['https://private.test/a','tmp:/unrelated.jpg',valid[0]])
  self.assertEqual([p for p in result['deleted'] if p],[valid[0]])
  self.assertEqual(result['result'],dict(owner={},uri='',sessionRevision=-1))
