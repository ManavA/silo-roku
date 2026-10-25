"""Siku browsing adaptation at the real Silo transport boundary."""
import json
import unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
ADAPTER=ROOT/'source/adapters/SiloAdapter.brs'
SESSION={'baseUrl':'https://fixture.example','accessToken':'fixture','profileId':'owner'}
class SikuBrowseTests(unittest.TestCase):
 def request(self, action, params):
  return run_function(ADAPTER,'BuildSiloRequest',[action,SESSION,params])
 def test_catalog_filters_preserve_native_rule_values(self):
  r=self.request('catalog_query',{'namePrefix':'B','genre':'Drama','watched':'unwatched','libraryId':'movies','limit':60})
  b=json.loads(r['body'])
  self.assertEqual('B',b['name_prefix'])
  self.assertEqual([{'match':'all','rules':[{'field':'genre','op':'contains','value':'Drama'},{'field':'watched','op':'eq','value':False}]}],b['groups'])
 def test_list_mutations_use_profile_scoped_header_and_no_body(self):
  for action,path,method in [('favorite_add','favorites','PUT'),('favorite_remove','favorites','DELETE'),('watchlist_add','watchlist','PUT'),('watchlist_remove','watchlist','DELETE')]:
   with self.subTest(action=action):
    r=self.request(action,{'itemId':'movie:fixture'})
    self.assertTrue(r['ok'])
    self.assertTrue(r['url'].endswith('/'+path+'/movie%3Afixture'))
    self.assertEqual(method,r['method'])
    self.assertEqual('owner',r['headers']['X-Profile-Id'])
 def test_person_search_is_bounded_video_only(self):
  r=self.request('people',{'query':'Jane Doe','limit':999})
  self.assertTrue(r['ok'])
  self.assertTrue(r['url'].endswith('/catalog/people?q=Jane%20Doe&limit=36&media_scope=video'))

 def test_home_dismissal_requires_surface_identity_and_progress_receipt(self):
  self.assertFalse(self.request('home_dismiss',{'itemId':'movie:fixture','surface':'continue_watching'})['ok'])
  r=self.request('home_dismiss',{'itemId':'movie:fixture','surface':'continue_watching','progressUpdatedAt':'2026-01-02T03:04:05.000Z'})
  self.assertTrue(r['ok'])
  self.assertEqual({'progress_updated_at':'2026-01-02T03:04:05.000Z'},json.loads(r['body']))
  self.assertTrue(r['url'].endswith('/home/dismissals/continue_watching/movie%3Afixture'))
 def test_optional_selection_response_has_only_bounded_public_identity(self):
  items=[{'id':str(i),'name':'Collection '+str(i),'poster_url':'https://private.invalid/signed'} for i in range(75)]
  r=run_function(ADAPTER,'DecodeSiloResponse',['collections',json.dumps({'items':items}),{}])
  self.assertTrue(r['ok'])
  self.assertEqual(60,len(r['data']['entries']))
  self.assertEqual({'id':'0','title':'Collection 0','source':'user_collection'},r['data']['entries'][0])

class ShippingBrowseTests(unittest.TestCase):
 def component(self, body):
  import tempfile
  from tools.brightscript import run_brightscript
  helpers='''
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.calls.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
sub Toast(message as String)
 m.messages.Push(message)
end sub
'''
  with tempfile.TemporaryDirectory() as folder:
   fixture=Path(folder)/'browse.brs'
   fixture.write_text((ROOT/'components/SiloUILibrary.brs').read_text()+helpers)
   return json.loads(run_brightscript([ROOT/'source/core/SiloUIFormat.brs',ROOT/'components/SiloUIDialogs.brs',fixture],body,root=Path(folder)))
 def test_shipping_query_wires_library_list_and_filters(self):
  state=self.component('''
 m.calls=[] : m.provider="silo" : m.libraryType="movie" : m.libraryCursor="page2"
 m.libraryTitle={} : m.libraryFormatFilter="" : m.librarySortProvider="silo" : m.librarySorts=[{sort:"title",order:"asc"}] : m.pillGroups={libraryTabs:{index:0}}
 m.libraryId="video-library" : m.librarySource="favorites" : m.libraryCollection=""
 m.libraryPerson="" : m.libraryGenre="Drama" : m.libraryWatched="unwatched" : m.libraryPrefix="B"
 m.libraryToken=7
 LibraryQuery(false)
 print FormatJson(m.calls)
 ''')
  self.assertEqual('catalog_query',state[0]['action'])
  self.assertEqual({'type':'movie','sort':'title','order':'asc','limit':60,'libraryId':'video-library','source':'favorites','collectionId':'','genre':'Drama','watched':'unwatched','namePrefix':'B','cursor':'page2','formatFilter':''},state[0]['params'])
  self.assertEqual(7,state[0]['extra'])
 def test_fifth_empty_page_stops_even_with_alternating_cursors(self):
  state=self.component('''
 m.provider="silo" : m.libraryToken=7 : m.libraryPages=4 : m.libraryCursor="a" : m.libraryRequestedCursor="a"
 m.libraryRetryButtons={visible:false} : m.libraryEmpty={} : m.zone="grid"
 m.grid={content:{getChildCount:function() as Integer
 return 0
 end function}}
 LibraryResult("lib_page",{ok:true},{items:[],nextCursor:"b",hasMore:true},7)
 print FormatJson({more:m.libraryMore,pages:m.libraryPages})
 ''')
  self.assertEqual({'more':False,'pages':5},state)
 def test_mutations_report_success_only_after_current_confirmed_response(self):
  state=self.component('''
 m.browseMutationContext=BrowseCaptureContext()
 m.messages=[] : m.browseMutationToken=4 : m.browseMutationPending=true : m.homeReload=false : m.libraryReload=false
 BrowseResult("browse_social",{ok:true},{},3)
 stale=m.messages.Count()
 BrowseResult("browse_social",{ok:false},{},4)
 failedReload=m.homeReload
 m.browseMutationPending=true
 BrowseResult("browse_social",{ok:true},{},4)
 print FormatJson({stale:stale,failedReload:failedReload,messages:m.messages,homeReload:m.homeReload,libraryReload:m.libraryReload,pending:m.browseMutationPending})
 ''')
  self.assertEqual(0,state['stale'])
  self.assertFalse(state['failedReload'])
  self.assertEqual('Saved.',state['messages'][-1])
  self.assertTrue(state['homeReload'])
  self.assertTrue(state['libraryReload'])
  self.assertFalse(state['pending'])

 def test_page_window_exposes_explicit_continuation_after_memory_bound(self):
  state=self.component('''
 m.provider="silo" : m.libraryToken=7 : m.libraryPages=4 : m.libraryCursor="a" : m.libraryRequestedCursor="a"
 m.libraryRetryButtons={visible:false} : m.libraryEmpty={} : m.zone="grid"
 m.grid={content:{getChildCount:function() as Integer
 return 0
 end function}}
 LibraryResult("lib_page",{ok:true},{items:[],nextCursor:"b",hasMore:true},7)
 print FormatJson({automatic:m.libraryMore,manual:m.libraryHasNext,cursor:m.libraryCursor})
 ''')
  self.assertEqual({'automatic':False,'manual':True,'cursor':'b'},state)
