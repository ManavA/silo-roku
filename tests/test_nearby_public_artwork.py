"""Bounded neighborhood grants, exact identity, serialized optional jobs."""
from pathlib import Path
import tempfile
import unittest
import sys
C=Path(__file__).resolve().parents[1]
ROOT=C if (C/'tools/brightscript.py').exists() else Path.cwd()
sys.path.insert(0,str(ROOT))
from tools.brightscript import run_function
SCOPE={'provider':'plex','sourceId':'plex:synthetic','profileId':'','generation':7}
def candidate(n): return {'key':str(n),'item':{'sourceId':SCOPE['sourceId'],'itemId':str(n),'type':'movie','tmdbId':str(n)}}
def focus(n=1, ids=range(1,15), **changes):
 return {'kind':'focus','scope':SCOPE,'scopeKey':'route-7','active':True,**candidate(n),'neighbors':[candidate(i) for i in ids if i!=n],'nowMs':0,**changes}
def data(n): return {'type':'movie','tmdbId':str(n),'posterUri':f'https://image.tmdb.org/t/p/w342/a{n}.jpg','backdropUri':f'https://image.tmdb.org/t/p/w780/a{n}.jpg'}
BRIDGE='''
function NearbyArtworkTrace(events as Object) as Object
 state=PublicArtworkCreate()
 trace=[]
 for each event in events
  if event.kind="reply"
   owner=PubArtCopy(state.pending)
   event={kind:"result",owner:owner,data:event.data,ok:event.ok,nowMs:event.nowMs}
  end if
  outcome=PublicArtworkReduce(state,event)
  state=outcome.state
  trace.Push({state:state,effects:outcome.effects,projection:PublicArtworkProjection(state)})
 end for
 return trace
end function
'''
def tick(now=240):return {'kind':'tick','nowMs':now}
def reply(n,now=300,ok=True):return {'kind':'reply','data':data(n),'ok':ok,'nowMs':now}
class NearbyArtworkTests(unittest.TestCase):
 def trace(self,events):
  with tempfile.TemporaryDirectory() as d:
   b=Path(d)/'fixture.brs';b.write_text(BRIDGE)
   return run_function([ROOT/'source/adapters/MetadataAdapter.brs',C/'source/core/PublicArtworkPolicy.brs',b],'NearbyArtworkTrace',[events],root=Path(d))
 def test_focus_first_max_twelve_grants_one_read_and_original_deadline(self):
  events=[focus(),focus(nowMs=200),tick(239),tick(),tick(250)]
  for n in range(1,13): events.append(reply(n,300+n))
  t=self.trace(events)
  self.assertEqual(240,t[1]['state']['wanted']['readyAtMs']);self.assertEqual([],t[4]['effects'])
  self.assertEqual('1',t[3]['effects'][0]['params']['tmdbId'])
  self.assertEqual(12,len(t[-1]['projection']['cards']));self.assertIsNone(t[-1]['state']['pending'])
  self.assertEqual([str(i) for i in range(1,13)],[c['key'] for c in t[-1]['projection']['cards']])
  self.assertEqual(12,len(t[-1]['state']['targets']));self.assertEqual(12,len(t[-1]['state']['assets']))
  self.assertEqual([str(i) for i in range(1,13)],[step['effects'][0]['params']['tmdbId'] for step in t if step['effects'] and step['effects'][0]['type']=='request'])
  self.assertEqual(list(range(1,13)),[step['effects'][0]['artworkOwner']['artId'] for step in t if step['effects'] and step['effects'][0]['type']=='request'])
  self.assertTrue(all(len([effect for effect in step['effects'] if effect['type']=='request'])<=1 for step in t))
 def test_retained_neighbor_reply_only_grants_same_item_and_never_becomes_new_hero(self):
  t=self.trace([focus(ids=[1,2]),tick(),focus(2,ids=[1,2],nowMs=260),reply(1,300),tick(499),tick(500),reply(2,550)])
  self.assertFalse(t[3]['projection']['active']);self.assertEqual(['1'],[c['key'] for c in t[3]['projection']['cards']])
  self.assertEqual(500,t[4]['state']['wanted']['readyAtMs']);self.assertEqual(1,t[4]['effects'][0]['milliseconds']);self.assertEqual('2',t[5]['effects'][0]['params']['tmdbId']);self.assertEqual('2',t[-1]['projection']['key'])
 def test_departed_result_cannot_regrant_and_foreground_clears_every_card(self):
  t=self.trace([focus(ids=[1,2]),tick(),focus(3,ids=[3,4],nowMs=260),reply(1,300),tick(500),reply(3,550),focus(active=False,nowMs=600),reply(4,650)])
  self.assertEqual([],t[3]['projection']['cards']);self.assertEqual([],t[-1]['projection']['cards']);self.assertFalse(t[-1]['projection']['active'])
 def test_same_route_key_changed_item_identity_invalidates_old_grant_and_read(self):
  f=focus(ids=[1,2]);changed=focus(ids=[1,2],nowMs=260);changed['item']['tmdbId']='99'
  t=self.trace([f,tick(),changed,reply(1,300),tick(500)])
  self.assertEqual([],t[3]['projection']['cards']);self.assertEqual('99',t[-1]['effects'][0]['params']['tmdbId'])
 def test_invalid_foreign_duplicate_and_missing_id_neighbors_do_not_fetch_or_grant(self):
  f=focus(ids=[1]);f['neighbors']=[candidate(1),candidate(2),candidate(2),{'key':'foreign','item':{**candidate(3)['item'],'sourceId':'plex:foreign'}},{'key':'empty','item':{**candidate(4)['item'],'tmdbId':''}}]
  t=self.trace([f,tick(),reply(1),reply(2,400)])
  self.assertEqual(['1','2'],[c['key'] for c in t[-1]['projection']['cards']]);self.assertIsNone(t[-1]['state']['pending'])
 def test_failed_neighbor_is_suppressed_duplicate_focus_does_not_refetch_and_memory_drops_all(self):
  f=focus(ids=[1,2,3])
  t=self.trace([f,tick(),reply(1),reply(2,400,False),reply(3,500),focus(ids=[1,2,3],nowMs=600),tick(900),{'kind':'memory','nowMs':1000},reply(3,1100)])
  self.assertEqual([],t[6]['effects']);self.assertEqual([],t[-1]['projection']['cards']);self.assertEqual([],t[-1]['state']['cache'])

 def test_equal_metadata_id_uses_one_read_but_separate_verified_item_grants(self):
  f=focus(ids=[1]);f['neighbors']=[{'key':'2','item':{**candidate(2)['item'],'tmdbId':'1'}}]
  t=self.trace([f,tick(),reply(1)])
  self.assertEqual(['1','2'],[c['key'] for c in t[-1]['projection']['cards']]);self.assertIsNone(t[-1]['state']['pending']);self.assertLessEqual(len(t[-1]['state']['assets']),12)

 def test_neighbors_inspect_twenty_four_raw_entries_then_stop(self):
  f=focus(ids=[1]);f['neighbors']=[candidate(1) for _ in range(23)]+[candidate(2),candidate(3)]
  t=self.trace([f,tick(),reply(1),reply(2,400)])
  self.assertEqual(['1','2'],[target['key'] for target in t[0]['state']['targets']])
  self.assertEqual(['1','2'],[card['key'] for card in t[-1]['projection']['cards']]);self.assertIsNone(t[-1]['state']['pending'])
