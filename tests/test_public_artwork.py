"""Exact public metadata identity and optional artwork scheduling (candidate only)."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function

CANDIDATE = Path(__file__).resolve().parents[1]
ADAPTER = CANDIDATE/'source/adapters/MetadataAdapter.brs'
POLICY = CANDIDATE/'source/core/PublicArtworkPolicy.brs'
SCOPE = {'provider':'plex','sourceId':'plex:synthetic','profileId':'','generation':7}
ITEM = {'sourceId':SCOPE['sourceId'],'itemId':'501','type':'movie','tmdbId':'141','title':'Fixture'}
DATA = {'type':'movie','tmdbId':'141','posterUri':'https://image.tmdb.org/t/p/w342/fixture.jpg','backdropUri':'https://image.tmdb.org/t/p/w780/fixture.jpg'}
def focus(item=None, scope=None, **changes):
    return {'kind':'focus','scope':scope or SCOPE,'scopeKey':'route-7','key':'501','item':item or ITEM,'active':True,'nowMs':0,**changes}
def tick(now=240): return {'kind':'tick','nowMs':now}
def result(data=None, **changes):
    return {'kind':'result','owner':'pending','ok':True,'data':data or DATA,'nowMs':300,**changes}
BRIDGE = '''
function PublicArtworkTrace(events as Object) as Object
 state = PublicArtworkCreate()
 trace = []
 for each incoming in events
  if incoming.kind = "seed_cache"
   state.cache = incoming.cache
   state.viewer = incoming.scope
   trace.Push({state:PubArtCopy(state),effects:[],projection:PublicArtworkProjection(state)})
  else
  if incoming.kind = "result"
   if type(incoming.owner) = "String" then incoming.owner = state.pending
  end if
  outcome = PublicArtworkReduce(state,incoming)
  state = outcome.state
  trace.Push({state:state,effects:outcome.effects,projection:PublicArtworkProjection(state)})
  end if
 end for
 return trace
end function
'''
class PublicArtworkTests(unittest.TestCase):
 def run_trace(self, events):
  self.assertTrue(POLICY.is_file(), 'PublicArtworkPolicy missing')
  with tempfile.TemporaryDirectory() as d:
   bridge=Path(d)/'bridge.brs'; bridge.write_text(BRIDGE)
   return run_function([ADAPTER,POLICY,bridge],'PublicArtworkTrace',[events],root=Path(d))
 def test_exact_owned_id_prepares_only_after_original_debounce(self):
  t=self.run_trace([focus(),focus(nowMs=200),tick(239),tick(),result()])
  self.assertEqual([], t[1]['effects']); self.assertIsNone(t[2]['state']['pending'])
  request=t[3]['effects'][0]; self.assertEqual('metadata_artwork',request['action'])
  self.assertEqual({'type':'movie','tmdbId':'141'},request['params'])
  self.assertEqual(SCOPE,request['scope']); self.assertEqual('public_artwork',request['purpose'])
  self.assertEqual(DATA['posterUri'],t[4]['projection']['posterUri'])
  self.assertNotIn('sourceId',json.dumps(t[4]['projection']))
 def test_source_profile_item_kind_and_conflicting_ids_fail_closed(self):
  bad=[{**ITEM,'sourceId':'plex:foreign'},{**ITEM,'type':'episode'},{**ITEM,'tmdbId':''},
       {**ITEM,'tmdbId':'141','externalIds':{'tmdb':'142'}},{**ITEM,'tmdbId':'141','guids':['tmdb://142']},
       {**ITEM,'tmdbId':'141?auth=x'},{**ITEM,'itemId':''},{**ITEM,'tmdbId':141},{**ITEM,'tmdbId':{'id':'141'}}]
  for item in bad:
   with self.subTest(item=item):
    t=self.run_trace([focus(item),tick()]); self.assertEqual([],t[-1]['effects']); self.assertIsNone(t[-1]['state']['pending'])
 def test_silo_series_uses_fresh_native_identity_even_with_exact_guid(self):
  scope={**SCOPE,'provider':'silo','sourceId':'silo:https://synthetic.example.test','profileId':'p1'}
  item={'sourceId':scope['sourceId'],'itemId':'series-1','type':'series','guids':['tmdb://202']}
  t=self.run_trace([focus(item,scope),tick()]); self.assertEqual({'type':'tv','itemId':'series-1','itemType':'series'},t[-1]['effects'][0]['params'])
  self.assertEqual('',t[-1]['state']['pending']['tmdbId'])
 def test_late_read_cannot_paint_new_focus_and_only_one_read_runs(self):
  b={**ITEM,'itemId':'502','tmdbId':'142'}
  t=self.run_trace([focus(),tick(),focus(b,key='502',nowMs=260),tick(500),result(nowMs=510)])
  self.assertEqual([],t[3]['effects']); self.assertFalse(t[4]['projection']['active'])
  self.assertEqual('142',t[4]['effects'][0]['params']['tmdbId']); self.assertEqual(1,len(t[4]['state']['cache']))
 def test_wrong_owner_or_result_identity_cannot_paint(self):
  t=self.run_trace([focus(),tick(),result(owner={**SCOPE,'artId':99}),result(data={**DATA,'tmdbId':'142'})])
  self.assertIsNotNone(t[2]['state']['pending']); self.assertFalse(t[-1]['projection']['active']); self.assertIsNone(t[-1]['state']['pending'])
 def test_cache_hit_same_viewer_new_generation_but_profile_change_drops_cache(self):
  t=self.run_trace([focus(),tick(),result(),focus(scope={**SCOPE,'generation':8},scopeKey='route-8',nowMs=500),
                    focus(scope={**SCOPE,'generation':9,'profileId':'p2'},scopeKey='route-9',nowMs=600)])
  self.assertTrue(t[3]['projection']['active']); self.assertEqual([],t[3]['effects']); self.assertEqual([],t[-1]['state']['cache'])
 def test_failed_same_focus_is_suppressed_memory_retires_and_recovery_can_retry(self):
  t=self.run_trace([focus(),tick(),result(ok=False),focus(nowMs=400),tick(700),
                    {'kind':'memory','nowMs':800},focus(nowMs=900),tick(1200),{'kind':'recover','nowMs':1300},focus(nowMs=1300),tick(1540)])
  self.assertEqual([],t[4]['effects']); self.assertFalse(t[7]['projection']['active']); self.assertEqual([],t[7]['effects']); self.assertEqual('request',t[-1]['effects'][0]['type'])
 def test_caches_expire_and_cap_sixty_four_without_empty_success_entries(self):
  events=[{'kind':'seed_cache','scope':SCOPE,'cache':[{**DATA,'tmdbId':str(1000+i),'atMs':0} for i in range(1,64)]}]
  for i in range(3):
   events += [focus({**ITEM,'itemId':str(i+1),'tmdbId':str(i+1)},key=str(i+1),nowMs=i*1000),tick(i*1000+240),result(data={**DATA,'tmdbId':str(i+1)},nowMs=i*1000+300)]
  t=self.run_trace(events); self.assertEqual(64,len(t[-1]['state']['cache'])); self.assertEqual('1003',t[-1]['state']['cache'][0]['tmdbId'])
  t=self.run_trace([focus(),tick(),result(),focus(active=False,nowMs=500),focus(nowMs=600301),tick(600541)])
  self.assertEqual('request',t[-1]['effects'][0]['type'])
 def test_global_seed_requires_matching_catalog_id_and_does_not_become_owned(self):
  item={'provider':'metadata','catalogId':'metadata:movie:141','type':'movie','tmdbId':'141','thumbKey':DATA['posterUri']}
  t=self.run_trace([focus(item),tick()]); self.assertEqual('141',t[-1]['effects'][0]['params']['tmdbId'])
  t=self.run_trace([focus({**item,'catalogId':'metadata:movie:142'}),tick()]); self.assertEqual([],t[-1]['effects'])

 def test_bind_retirement_clears_public_cache_before_source_screen(self):
  t=self.run_trace([focus(),tick(),result(),{'kind':'bind','scope':{**SCOPE,'sourceId':''},'nowMs':500}])
  self.assertEqual([],t[-1]['state']['cache']);self.assertFalse(t[-1]['projection']['active'])
 def test_missing_id_fields_allow_exact_guid_and_large_clock_is_rejected(self):
  t=self.run_trace([focus({**ITEM,'tmdbId':'','externalIds':{'tmdb':''},'guids':['tmdb://141']}),tick()])
  self.assertEqual('141',t[-1]['effects'][0]['params']['tmdbId'])
  t=self.run_trace([focus(nowMs=1e40),tick()]);self.assertEqual([],t[-1]['effects'])

 def test_real_boxed_numeric_aliases_preserve_policy_flow_and_integer_scope(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'policy.brs';p.write_text(POLICY.read_text().replace('type(', 'PublicArtworkNativeType('))
   b=Path(d)/'bridge.brs';b.write_text(BRIDGE+"""
function PublicArtworkNativeType(value as Dynamic) as String
 native=type(value)
 if native="Integer" or native="roInt" then return "roInteger"
 if native="LongInteger" then return "roLongInteger"
 if native="Double" or native="Float" then return "roDouble"
 return native
end function
""")
   t=run_function([ADAPTER,p,b],'PublicArtworkTrace',[[focus(),tick(240.5),result()]],root=Path(d))
   self.assertTrue(t[-1]['projection']['active'])
   t=run_function([ADAPTER,p,b],'PublicArtworkTrace',[[focus(scope={**SCOPE,'generation':7.5}),tick()]],root=Path(d))
   self.assertEqual([],t[-1]['effects'])

 def test_current_plex_home_normalization_retains_exact_tmdb_guid(self):
  repo=Path(__file__).resolve().parents[1]
  if not (repo/'source/adapters/PlexAdapter.brs').exists(): repo=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   b=Path(d)/'hub.brs';b.write_text("""
function PublicArtworkFromPlexHub() as Object
 raw={ratingKey:"501",type:"movie",title:"Fixture",guid:"plex://movie/native-id",Guid:[{id:"tmdb://141"},{id:"imdb://tt0246578"}],thumb:"/library/metadata/501/thumb"}
 item=PlexNormalizeItem(raw,"plex:synthetic")
 return {guids:item.guids,focus:PubArtFocus({active:true,scope:{provider:"plex",sourceId:"plex:synthetic",profileId:"",generation:7},scopeKey:"route-7",key:"501",item:item},0)}
end function
""")
   x=run_function([repo/'source/adapters/PlexAdapter.brs',ADAPTER,POLICY,b],'PublicArtworkFromPlexHub',[],root=Path(d))
  self.assertIn('tmdb://141',x['guids']);self.assertEqual('141',x['focus']['tmdbId'])

class PublicArtworkAdapterTests(unittest.TestCase):
 def call(self,fn,*args):
  with tempfile.TemporaryDirectory() as d: return run_function(ADAPTER,fn,list(args),root=Path(d))
 def test_exact_public_request_drops_every_private_param(self):
  req=self.call('BuildMetadataRequest','metadata_artwork',{'baseUrl':'https://metadata.example','token':'SECRET'}, {'type':'movie','tmdbId':'141','itemId':'private','headers':{'Authorization':'SECRET'}})
  self.assertTrue(req['ok']); self.assertEqual('https://metadata.example/v1/enrich/movie/141',req['url']); self.assertEqual(4000,req['timeoutMs'])
  self.assertEqual('GET',req['method']); self.assertEqual('',req['body']); self.assertNotIn('SECRET',json.dumps(req)); self.assertNotIn('private',json.dumps(req))
 def test_bad_identity_request_rejected_without_guessing(self):
  for params in ({'type':'episode','tmdbId':'141'},{'type':'tv','tmdbId':'0'},{'type':'movie','tmdbId':'../141'},{'type':'movie','title':'Fixture'}):
   self.assertEqual('invalid_request',self.call('BuildMetadataRequest','metadata_artwork',{'baseUrl':'https://metadata.example'},params)['errorCode'])
 def test_decode_checks_returned_exact_identity_and_projects_only_public_uris(self):
  body={'type':'movie','tmdbId':'141','posterPath':'/fixture.jpg','backdropPath':'/fixture.png','token':'SECRET','cast':[{'private':'value'}]}
  d=self.call('DecodeMetadataResponse','metadata_artwork',json.dumps(body),{'type':'movie','tmdbId':'141'})
  self.assertEqual({'type':'movie','tmdbId':'141','posterUri':DATA['posterUri'],'backdropUri':'https://image.tmdb.org/t/p/w780/fixture.png'},d['data'])
  for field,value in (('type','tv'),('tmdbId','142')):
   self.assertEqual('invalid_response',self.call('DecodeMetadataResponse','metadata_artwork',json.dumps({**body,field:value}),{'type':'movie','tmdbId':'141'})['errorCode'])
 def test_missing_or_unsafe_paths_remain_title_only_and_body_is_capped(self):
  for path in (None,'https://private.test/a?token=x','/../a.jpg','/a.jpg?token=x','/a.svg'):
   d=self.call('DecodeMetadataResponse','metadata_artwork',json.dumps({'type':'movie','tmdbId':'141','posterPath':path}),{'type':'movie','tmdbId':'141'})
   self.assertTrue(d['ok']); self.assertEqual('',d['data']['posterUri'])
  self.assertEqual('response_too_large',self.call('DecodeMetadataResponse','metadata_artwork',' '*98305,{'type':'movie','tmdbId':'141'})['errorCode'])
