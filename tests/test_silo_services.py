"""Optional Silo surfaces at the real transport and shipping Scene seams."""
import json
import unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
FILES=[ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/adapters/SiloServices.brs']
SESSION={'baseUrl':'https://fixture.example','accessToken':'fixture','profileId':'owner'}
class SiloServicesTests(unittest.TestCase):
 def request(self,action,params=None):
  return run_function(FILES,'BuildSiloServicesRequest',['service_'+action,SESSION,params or {}])
 def decode(self,action,data,params=None):
  return run_function(FILES,'DecodeSiloServicesResponse',['service_'+action,json.dumps(data),params or {}])
 def test_requests_create_requires_external_identity_and_native_gate_body(self):
  self.assertFalse(self.request('request_create',{'title':'Example'})['ok'])
  r=self.request('request_create',{'title':'Example','tmdbId':42,'mediaType':'movie'})
  self.assertTrue(r['ok'])
  self.assertEqual('POST',r['method'])
  self.assertEqual({'title':'Example','tmdb_id':42,'media_type':'movie'},json.loads(r['body']))
  self.assertEqual('owner',r['headers']['X-Profile-Id'])
 def test_missing_or_disabled_capabilities_are_unavailable(self):
  for body in [{},{'allowed':True,'state':'disabled','requests_enabled':True},{'allowed':False,'state':'available','requests_enabled':True}]:
   self.assertFalse(self.decode('requests_cap',body)['data']['available'])
  self.assertTrue(self.decode('requests_cap',{'allowed':True,'state':'available','requests_enabled':True})['data']['available'])
 def test_discovery_and_requests_pages_are_bounded_and_private(self):
  r=self.request('request_search',{'query':'Some title','page':99})
  self.assertTrue(r['ok'])
  self.assertTrue(r['url'].endswith('/requests/search?q=Some%20title&media_type=all&page=20'))
  r=self.decode('request_search',{'page':1,'total_pages':50,'results':[{'tmdb_id':42,'title':'Example','media_type':'movie','request':{'requestable':True},'private_url':'secret'}]})
  self.assertEqual(42,r['data']['entries'][0]['tmdbId'])
  self.assertTrue(r['data']['entries'][0]['requestable'])
  self.assertNotIn('secret',json.dumps(r))
 def test_notifications_read_all_uses_observed_cutoff_not_client_clock(self):
  self.assertFalse(self.request('notifications_read_all',{})['ok'])
  r=self.request('notifications_read_all',{'through':'opaque-cutoff'})
  self.assertTrue(r['ok'])
  self.assertEqual({'through':'opaque-cutoff'},json.loads(r['body']))
  d=self.decode('notifications',{'items':[{'id':'n1','series_title':'Show','type':'available','created_at':'2026-10-15T00:00:00Z','read_at':None}],'read_cutoff':'opaque-cutoff','page':{'has_more':True,'next_cursor':'next'}})
  self.assertEqual('opaque-cutoff',d['data']['cutoff'])
  self.assertEqual('next',d['data']['nextCursor'])
  self.assertTrue(d['data']['entries'][0]['unread'])
 def test_calendar_requires_dates_and_timezone_and_bounded_output(self):
  self.assertFalse(self.request('calendar',{})['ok'])
  r=self.request('calendar',{'start':'2026-10-15','end':'2026-10-21','timezone':'America/Los_Angeles','filter':'watchlist'})
  self.assertTrue(r['ok'])
  self.assertIn('timezone=America%2FLos_Angeles',r['url'])
  d=self.decode('calendar',{'events':[{'date':'2026-10-15','items':[{'title':'Episode','content_id':'e1','type':'episode','local_air_date':'2026-10-15','poster_url':'secret'}]}]})
  self.assertEqual('e1',d['data']['entries'][0]['itemId'])
  self.assertNotIn('secret',json.dumps(d))
 def test_subtitle_timing_requires_a_specific_validator_and_bounds(self):
  p={'fileId':'file1','key':'stored-1','offsetMs':500,'scale':1}
  self.assertFalse(self.request('subtitle_timing',p)['ok'])
  self.assertFalse(self.request('subtitle_timing',{**p,'etag':'*'})['ok'])
  r=self.request('subtitle_timing',{**p,'etag':'"revision-1"'})
  self.assertTrue(r['ok'])
  self.assertEqual('"revision-1"',r['headers']['If-Match'])
  self.assertEqual({'offset_ms':500,'scale':1},json.loads(r['body']))
  self.assertFalse(self.request('subtitle_timing',{**p,'etag':'"revision-1"','offsetMs':600001})['ok'])
 def test_subtitle_search_download_and_ai_have_explicit_file_identity(self):
  self.assertFalse(self.request('subtitle_search',{})['ok'])
  r=self.request('subtitle_search',{'fileId':'file1','language':'en'})
  self.assertEqual({'media_file_id':'file1','languages':['en']},json.loads(r['body']))
  r=self.request('subtitle_ai_create',{'fileId':'file1','kind':'transcribe','targetLanguage':'en','sourceLanguage':'en','sourceIndex':-1})
  self.assertTrue(r['ok'])
  self.assertEqual(-1,json.loads(r['body'])['source_index'])
 def test_etag_capture_excludes_other_response_headers(self):
  d=run_function(ROOT/'source/network/Http.brs','HttpResponse',[{'captureETag':True},200,'{}',[{'ETag':'"rev-2"'},{'Set-Cookie':'private'},{'Authorization':'secret'}]])
  self.assertEqual('"rev-2"',d['etag'])
  self.assertNotIn('private',json.dumps(d))
  self.assertNotIn('secret',json.dumps(d))

 def test_request_progress_remains_server_reported_and_omits_integration_errors(self):
  d=self.decode('request_status',{'id':'r1','title':'Example','state':'processing','download':{'phase':'downloading','percent':43,'updated_at':'2026-10-15T00:00:00Z'},'last_error':'private integration address'})
  self.assertEqual('downloading • 43% • Reported 2026-10-15T00:00:00Z',d['data']['entry']['downloadSummary'])
  self.assertNotIn('private',json.dumps(d))

class ShippingServicesTests(unittest.TestCase):
 def scene(self,body):
  import tempfile
  from tools.brightscript import run_brightscript
  helpers='''
sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
 m.calls.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
sub Toast(message as String)
 m.messages.Push(message)
end sub
sub BrowsePagedChoices(title as String,labels as Object,handler as String)
 m.menus.Push({title:title,labels:labels})
end sub
'''
  with tempfile.TemporaryDirectory() as folder:
   fixture=Path(folder)/'scene.brs'
   fixture.write_text((ROOT/'components/SiloUIServices.brs').read_text()+helpers)
   return json.loads(run_brightscript([ROOT/'source/core/SiloUIFormat.brs',ROOT/'components/SiloUIDialogs.brs',fixture],'''
 m.calls=[] : m.messages=[] : m.menus=[] : m.servicesVisit=2 : m.servicesSerial=3
 m.servicesGeneration=8 : m.generation=8 : m.servicesOwnerView="onboarding" : m.view="onboarding" : m.servicesCaps={}
 m.provider="silo":m.sourceId="silo:test":m.profileId="p":m.servicesContext=BrowseCaptureContext():m.servicesOwner=m.servicesContext.owner
 '''+body,root=Path(folder)))
 def test_capability_denial_never_opens_request_actions(self):
  d=self.scene('''
 ServicesResult({ok:true},{available:false},{visit:2,serial:3,action:"requests_cap"})
 print FormatJson({calls:m.calls,menus:m.menus,messages:m.messages})
 ''')
  self.assertEqual([],d['calls'])
  self.assertEqual([],d['menus'])
  self.assertEqual(1,len(d['messages']))
 def test_old_or_departed_view_result_never_opens_dialog(self):
  d=self.scene('''
 ServicesResult({ok:true},{available:true},{visit:1,serial:3,action:"requests_cap"})
 m.view="home"
 ServicesResult({ok:true},{available:true},{visit:2,serial:3,action:"requests_cap"})
 print FormatJson({menus:m.menus,messages:m.messages})
 ''')
  self.assertEqual({'menus':[],'messages':[]},d)
 def test_moderation_first_checks_permission_instead_of_sending_mutation(self):
  d=self.scene('''
 ServicesAction({action:"moderation_cap"})
 print FormatJson(m.calls)
 ''')
  self.assertEqual('service_moderation_cap',d[0]['action'])
 def test_failed_request_mutation_never_reports_saved(self):
  d=self.scene('''
 ServicesResult({ok:false},{},{visit:2,serial:3,action:"request_create"})
 print FormatJson({menus:m.menus,messages:m.messages})
 ''')
  self.assertEqual([],d['menus'])
  self.assertNotIn('confirmed',' '.join(d['messages']))

 def test_empty_inbox_and_calendar_explain_results_without_losing_actions(self):
  for action,message,expected in [
   ('notifications','No notifications in this view.',['Mark inbox read through this snapshot','Refresh page','Server tools']),
   ('calendar','No releases for this week and filter.',['Calendar week/timezone/filter','Refresh page','Server tools'])]:
   with self.subTest(action=action):
    d=self.scene('''
 m.browseDialog={}
 ServicesPage("'''+action+'''",{entries:[],hasMore:false,cutoff:"fixture-cutoff"})
 print FormatJson({message:m.browseDialog.message,labels:m.menus[0].labels})
 ''')
    self.assertEqual(message,d['message'])
    self.assertEqual(expected,d['labels'])
 def test_nonempty_inbox_does_not_show_empty_state(self):
  d=self.scene('''
 m.browseDialog={}
 ServicesPage("notifications",{entries:[{id:"n1",title:"A show",state:"",unread:true}],hasMore:false,cutoff:"fixture-cutoff"})
 print FormatJson({message:m.browseDialog.message,labels:m.menus[0].labels})
 ''')
  self.assertIsNone(d['message'])
  self.assertIn('Unread • A show',d['labels'][0])
