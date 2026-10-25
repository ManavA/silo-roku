"""Silo grants prove their exact current native owner without cache shortcuts."""
import copy
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function

CANDIDATE=Path(__file__).resolve().parents[1]
ROOT=Path(__file__).resolve().parents[1]
SCOPE={'provider':'silo','sourceId':'silo:https://synthetic.example.test','profileId':'p1','generation':7}
DATA={'type':'movie','tmdbId':'141','posterUri':'https://image.tmdb.org/t/p/w342/fixture.jpg','backdropUri':'https://image.tmdb.org/t/p/w780/fixture.jpg'}
def item(n=1,kind='movie',**changes):return {'sourceId':SCOPE['sourceId'],'itemId':f'native-{n}','type':kind,'title':'Fixture',**changes}
def focus(n=1,**changes):return {'kind':'focus','scope':SCOPE,'scopeKey':'route-7','key':f'native-{n}','item':item(n),'active':True,'nowMs':0,**changes}
def tick(now=240):return {'kind':'tick','nowMs':now}
def reply(now=300,**changes):return {'kind':'reply','data':DATA,'ok':True,'nowMs':now,**changes}
BRIDGE='''
function SiloArtworkTrace(events as Object) as Object
    state=PublicArtworkCreate()
    trace=[]
    for each event in events
        if event.kind="seed_cache"
            state.cache=event.cache
            state.viewer=event.scope
            trace.Push({state:PubArtCopy(state),effects:[],projection:PublicArtworkProjection(state)})
        else
            if event.kind="reply" then event={kind:"result",owner:PubArtCopy(state.pending),ok:event.ok,data:event.data,nowMs:event.nowMs}
            outcome=PublicArtworkReduce(state,event)
            state=outcome.state
            trace.Push({state:PubArtCopy(state),effects:outcome.effects,projection:PublicArtworkProjection(state)})
        end if
    end for
    return trace
end function
'''
class SiloArtworkPolicyTests(unittest.TestCase):
    def trace(self,events):
        with tempfile.TemporaryDirectory(prefix='silo_ui-silo-art-policy-') as directory:
            p=Path(directory);bridge=p/'fixture.brs';bridge.write_text(BRIDGE)
            return run_function([ROOT/'source/adapters/MetadataAdapter.brs',CANDIDATE/'source/core/PublicArtworkPolicy.brs',bridge],'SiloArtworkTrace',[events],root=p)


    def test_missing_id_owned_movie_requests_private_pipeline_after_original_dwell(self):
        data=self.trace([focus(),focus(nowMs=200),tick(239),tick(),tick(250),reply()])
        self.assertIsNotNone(data[1]['state']['wanted'],'missing-ID Silo candidate was rejected')
        self.assertEqual(240,data[1]['state']['wanted']['readyAtMs']);self.assertEqual([],data[1]['effects'])
        self.assertEqual({'type':'movie','itemId':'native-1','itemType':'movie'},data[3]['effects'][0]['params'])
        self.assertEqual('public_artwork',data[3]['effects'][0]['purpose']);self.assertEqual([],data[4]['effects'])
        self.assertTrue(data[-1]['projection']['active']);self.assertEqual([],data[-1]['state']['cache'])

    def test_all_owned_silo_ids_require_fresh_proof_even_when_tmdb_is_present(self):
        for hint in ({'tmdbId':'141'},{'guids':['tmdb://141']},{'tmdbId':'141','externalIds':{'tmdb':'other'}}):
            value=self.trace([{'kind':'seed_cache','scope':SCOPE,'cache':[{**DATA,'atMs':0}]},focus(item=item(**hint)),tick()])
            self.assertFalse(value[1]['projection']['active']);self.assertEqual('native-1',value[2]['effects'][0]['params']['itemId'])

    def test_current_grant_retained_but_new_route_and_departure_never_reuse_private_identity(self):
        value=self.trace([focus(),tick(),reply(),focus(nowMs=400),tick(640),focus(scope={**SCOPE,'generation':8},scopeKey='route-8',nowMs=700),tick(940),reply(1000)])
        self.assertTrue(value[3]['projection']['active']);self.assertEqual([],value[4]['effects'])
        self.assertFalse(value[5]['projection']['active']);self.assertEqual('native-1',value[6]['effects'][0]['params']['itemId'])
        self.assertEqual([],value[-1]['state']['cache'])
        value=self.trace([focus(),tick(),focus(2,key='native-2',nowMs=250),reply(300),tick(490)])
        self.assertEqual([],value[3]['projection']['cards']);self.assertEqual('native-2',value[-1]['effects'][0]['params']['itemId'])

    def test_exact_series_and_foreign_unowned_or_bad_native_id_are_inert(self):
        value=self.trace([focus(item=item(kind='series')),tick(),reply(data={**DATA,'type':'tv','tmdbId':'202'})])
        self.assertEqual(1,len(value[1]['effects']),'verified series candidate produced no request')
        self.assertEqual({'type':'tv','itemId':'native-1','itemType':'series'},value[1]['effects'][0]['params']);self.assertTrue(value[-1]['projection']['active'])
        for change in ({'type':'show'},{'type':'tv'},{'sourceId':'silo:foreign'},{'availability':'unavailable'},{'itemId':'../native-1'},{'itemId':''}):
            value=self.trace([focus(item={**item(),**change}),tick()]);self.assertEqual([],value[-1]['effects'])

    def test_owned_episode_requires_fresh_parent_pipeline_and_same_owner_failure_suppression(self):
        wanted=focus(item=item(kind='episode',tmdbId='999',seriesId='untrusted-summary'))
        value=self.trace([wanted,tick(),reply(ok=False),{**wanted,'nowMs':400},tick(640)])
        self.assertEqual(1,len(value[1]['effects']))
        self.assertEqual({'type':'tv','itemId':'native-1','itemType':'episode'},value[1]['effects'][0]['params'])
        self.assertEqual([],value[-1]['effects']);self.assertFalse(value[-1]['projection']['active'])
        self.assertEqual([],value[-1]['state']['cache'])
        value=self.trace([wanted,tick(),reply(data={**DATA,'type':'tv','tmdbId':'202'}),
                          {**wanted,'scope':{**SCOPE,'generation':8},'scopeKey':'route-8','nowMs':400},tick(640)])
        self.assertTrue(value[2]['projection']['active']);self.assertFalse(value[3]['projection']['active'])
        self.assertEqual({'type':'tv','itemId':'native-1','itemType':'episode'},value[-1]['effects'][0]['params'])
        self.assertEqual([],value[-1]['state']['cache'])
        for provider in ('plex','metadata'):
            scope={**SCOPE,'provider':provider,'sourceId':provider+':synthetic'}
            value=self.trace([focus(scope=scope,item=item(kind='episode',sourceId=scope['sourceId'],tmdbId='999')),tick()])
            self.assertEqual([],value[-1]['effects'])
        for change in ({'availability':'unavailable'},{'sourceId':'silo:foreign'},{'provider':'metadata'}):
            value=self.trace([focus(item={**item(kind='episode',tmdbId='999'),**change}),tick()])
            self.assertEqual([],value[-1]['effects'])


    def test_episode_neighbors_remain_twelve_private_targets_and_one_request_at_a_time(self):
        candidates=[{'key':f'native-{n}','item':item(n,kind='episode',tmdbId='999')} for n in range(2,17)]
        events=[focus(item=item(kind='episode'),neighbors=candidates),tick()]
        for n in range(1,13):events.append(reply(300+n,data={**DATA,'type':'tv','tmdbId':'202'}))
        value=self.trace(events)
        self.assertEqual(12,len(value[0]['state']['targets']))
        self.assertEqual(12,len(value[-1]['projection']['cards']));self.assertIsNone(value[-1]['state']['pending'])
        self.assertEqual([f'native-{n}' for n in range(2,13)],[v['effects'][0]['params']['itemId'] for v in value[2:-1]])
        self.assertEqual([],value[-1]['state']['cache'])
        self.assertTrue(all(len(v['effects'])<=1 for v in value))

    def test_result_type_id_strict_boolean_and_original_owner_are_required(self):
        for change in ({'type':'tv'},{'tmdbId':''},{'tmdbId':'0'},{'tmdbId':141},{'tmdbId':'141?token=x'},{'tmdbId':'000141'},{'tmdbId':'141\n'}):
            value=self.trace([focus(),tick(),reply(data={**DATA,**change})]);self.assertFalse(value[-1]['projection']['active'])
        value=self.trace([focus(),tick(),reply(ok=1)]);self.assertFalse(value[-1]['projection']['active'])
        events=[focus(),tick(),{'kind':'result','owner':{**SCOPE,'artId':1},'ok':True,'data':DATA,'nowMs':300}]
        value=self.trace(events);self.assertIsNotNone(value[-1]['state']['pending']);self.assertFalse(value[-1]['projection']['active'])

    def test_focus_first_twelve_targets_one_task_at_a_time_no_identity_dedup_shortcut(self):
        candidates=[{'key':f'native-{n}','item':item(n,tmdbId='141')} for n in range(2,17)]
        events=[focus(neighbors=candidates),tick()]
        for n in range(1,13):events.append(reply(300+n))
        value=self.trace(events)
        self.assertEqual(1,len(value[1]['effects']),'focused identity candidate produced no request')
        self.assertEqual('native-1',value[1]['effects'][0]['params']['itemId'])
        self.assertEqual(12,len(value[0]['state']['targets']))
        self.assertEqual(12,len(value[-1]['projection']['cards']));self.assertIsNone(value[-1]['state']['pending'])
        self.assertEqual([f'native-{n}' for n in range(2,13)],[v['effects'][0]['params']['itemId'] for v in value[2:-1]])
        self.assertEqual([],value[-1]['state']['cache'])

    def test_same_focus_failure_suppressed_and_memory_foreground_profile_retire_grants(self):
        value=self.trace([focus(),tick(),reply(ok=False),focus(nowMs=400),tick(640)])
        self.assertEqual([],value[-1]['effects']);self.assertFalse(value[-1]['projection']['active'])
        for retirement in ({'kind':'memory','nowMs':400},focus(active=False,nowMs=400),focus(scope={**SCOPE,'profileId':'other'},nowMs=400)):
            value=self.trace([focus(),tick(),retirement,reply(450)])
            self.assertEqual([],value[-1]['projection']['cards']);self.assertEqual([],value[-1]['state']['cache'])

    def test_public_seeds_and_plex_keep_exact_id_cache_path(self):
        seed={'provider':'metadata','catalogId':'metadata:movie:141','type':'movie','tmdbId':'141'}
        for wanted in (focus(item=seed),focus(scope={**SCOPE,'provider':'plex','sourceId':'plex:synthetic'},item={**item(),'sourceId':'plex:synthetic','tmdbId':'141'})):
            value=self.trace([wanted,tick(),reply(),{**wanted,'scope':{**wanted['scope'],'generation':8},'scopeKey':'route-8','nowMs':500}])
            self.assertEqual({'type':'movie','tmdbId':'141'},value[1]['effects'][0]['params'])
            self.assertTrue(value[-1]['projection']['active']);self.assertEqual([],value[-1]['effects'])

    def test_private_pipeline_dto_type_is_exact_not_trimmed(self):
        value=self.trace([focus(),tick(),reply(data={**DATA,'type':'movie\n'})])
        self.assertFalse(value[-1]['projection']['active'])
