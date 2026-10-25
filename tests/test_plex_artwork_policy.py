"""Plex artwork keeps exact owned identity until a fresh provider proof returns."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
SCOPE = dict(provider='plex', sourceId='plex:fixture', profileId='viewer', generation=7)
DATA = dict(type='movie', tmdbId='141', posterUri='https://image.tmdb.org/t/p/w342/fixture.jpg',
            backdropUri='https://image.tmdb.org/t/p/w780/fixture.jpg')
BRIDGE = '''
function PlexArtworkCases(cases as Object) as Object
 output=[]
 for each events in cases
  state=PublicArtworkCreate():trace=[]:saved=invalid
  for each incoming in events
   effects=[]
   if incoming.kind="seed_cache"
    state.cache=PubArtCopy(incoming.cache):state.viewer=PubArtCopy(incoming.scope)
   else if incoming.kind="save_owner"
    saved=PubArtCopy(state.pending)
   else
    event=PubArtCopy(incoming)
    if event.kind="reply"
     owner=PubArtCopy(state.pending)
     if PubArtTrue(HmField(event,"saved")) then owner=PubArtCopy(saved)
     changes=HmField(event,"ownerChanges")
     if type(changes)<>"roAssociativeArray" then changes={}
     if type(owner)="roAssociativeArray"
      for each key in changes
       owner[key]=changes[key]
      end for
     end if
     event={kind:"result",owner:owner,ok:event.ok,data:event.data,nowMs:event.nowMs}
    end if
    reduced=PublicArtworkReduce(state,event):state=reduced.state:effects=reduced.effects
   end if
   trace.Push({state:PubArtCopy(state),effects:effects,projection:PublicArtworkProjection(state)})
  end for
  output.Push(trace)
 end for
 return output
end function
'''


def item(native='501', kind='movie', **changes):
    return {'provider':'plex','sourceId':SCOPE['sourceId'],'itemId':native,'type':kind,
            'availability':'owned','title':'Display title only',**changes}


def focus(value=None, **changes):
    return {'kind':'focus','scope':deepcopy(SCOPE),'scopeKey':'route-7','key':'card-501',
            'item':item() if value is None else value,'active':True,'nowMs':0,**changes}


def tick(now=240):
    return dict(kind='tick', nowMs=now)


def reply(kind='movie', now=300, **changes):
    return {'kind':'reply','ok':True,'data':{**DATA,'type':kind},'nowMs':now,**changes}


class PlexArtworkPolicyTests(unittest.TestCase):
    def cases(self, cases):
        with tempfile.TemporaryDirectory(prefix='silo-plex-art-policy-') as directory:
            bridge=Path(directory)/'fixture.brs';bridge.write_text(BRIDGE)
            return run_function([ROOT/'source/adapters/MetadataAdapter.brs',
                ROOT/'source/core/PublicArtworkPolicy.brs',bridge],
                'PlexArtworkCases',[cases],root=Path(directory))

    def trace(self, events):
        return self.cases([events])[0]

    def test_missing_or_unusable_movie_show_ids_request_exact_native_proof_after_original_dwell(self):
        cases=[]
        for kind in ('movie','show'):
            for hints in ({},{'tmdbId':''},{'guids':['plex://movie/native']},
                          {'tmdbId':'141','externalIds':{'tmdb':'142'}},
                          {'tmdbId':141},{'guids':['tmdb://141']*17}):
                wanted=focus(item(kind=kind,**hints))
                cases.append([wanted,{**wanted,'nowMs':200},tick(239),tick(),tick(250)])
        for trace in self.cases(cases):
            self.assertIsNotNone(trace[0]['state']['wanted'])
            self.assertEqual(240,trace[1]['state']['wanted']['readyAtMs'])
            self.assertEqual([],trace[1]['effects']);self.assertIsNone(trace[2]['state']['pending'])
            request=trace[3]['effects'][0];owner=request['artworkOwner']
            self.assertEqual('metadata_artwork',request['action']);self.assertEqual('public_artwork',request['purpose'])
            self.assertEqual(SCOPE,request['scope']);self.assertTrue(owner['identityRequired']);self.assertEqual('',owner['tmdbId'])
            expected='tv' if owner['nativeType']=='show' else 'movie'
            self.assertEqual(dict(type=expected,itemId='501',itemType=owner['nativeType']),request['params'])
            self.assertEqual([],trace[-1]['effects'])

    def test_episode_never_treats_leaf_or_summary_series_tmdb_as_show_proof(self):
        value=item(kind='episode',tmdbId='999',guids=['tmdb://999'],seriesItemId='900',
                   externalIds={'tmdb':'999'},seriesTmdbId='202',
                   thumbKey='/library/private',url='https://private.example.test/image?token=synthetic')
        trace=self.trace([focus(value),tick(),reply('tv',data={**DATA,'type':'tv','tmdbId':'202'})])
        self.assertEqual(1,len(trace[1]['effects']))
        self.assertEqual(dict(type='tv',itemId='501',itemType='episode'),trace[1]['effects'][0]['params'])
        self.assertEqual('',trace[1]['state']['pending']['tmdbId'])
        self.assertTrue(trace[-1]['projection']['active']);self.assertEqual([],trace[-1]['state']['cache'])
        public=json.dumps(trace[-1]['projection']);owner=json.dumps(trace[1]['state']['pending'])
        for text in ('private.example.test','synthetic','thumbKey','seriesTmdbId','seriesItemId','999'):
            self.assertNotIn(text,public);self.assertNotIn(text,owner)

    def test_foreign_unowned_nonleaf_and_malformed_native_candidates_are_inert(self):
        bad=[]
        for hints in ({},{'tmdbId':'141'}):
            for changes in ({'provider':'silo'},{'provider':'other'},{'sourceId':'plex:foreign'},
                            {'availability':'unavailable'},{'availability':True}):
                bad.append({**item(**hints),**changes})
        for native in ('','../501','/library/metadata/501','501?x=y',' 501','501\n','5'*21,501,True,None):
            bad.append(item(native=native))
            bad.append(item(native=native,kind='episode',tmdbId='999'))
        bad.extend(item(kind=kind) for kind in ('season','series','tv','person'))
        absent=item();absent.pop('provider');bad.append(absent)
        for trace in self.cases([[focus(value),tick()] for value in bad]):
            self.assertIsNone(trace[-1]['state']['wanted']);self.assertEqual([],trace[-1]['effects'])

    def test_existing_exact_movie_show_and_metadata_seeds_keep_public_cache_path(self):
        cases=[]
        for kind in ('movie','show'):
            value=item(kind=kind,tmdbId='141')
            legacy={**value};legacy.pop('provider')
            for candidate in (value,legacy):
                wanted=focus(candidate)
                cases.append([wanted,tick(),reply('tv' if kind=='show' else 'movie'),
                    {**wanted,'scope':{**SCOPE,'generation':8},'scopeKey':'route-8','nowMs':500}])
        seed=dict(provider='metadata',catalogId='metadata:show:141',type='show',tmdbId='141')
        cases.append([focus(seed),tick(),reply('tv')])
        for trace in self.cases(cases):
            request=trace[1]['effects'][0]
            self.assertEqual({'type':request['artworkOwner']['type'],'tmdbId':'141'},request['params'])
            self.assertFalse(request['artworkOwner']['identityRequired'])
            self.assertTrue(trace[-1]['projection']['active']);self.assertEqual(1,len(trace[-1]['state']['cache']))
            self.assertEqual([],trace[-1]['effects'])

    def test_fresh_identity_grants_never_read_or_write_cross_route_public_uri_cache(self):
        wanted=focus(item(kind='episode',tmdbId='141'))
        seeded=dict(kind='seed_cache',scope=SCOPE,cache=[{**DATA,'type':'tv','atMs':0}])
        trace=self.trace([seeded,wanted,tick(),reply('tv'),{**wanted,'nowMs':400},
            {**wanted,'scope':{**SCOPE,'generation':8},'scopeKey':'route-8','nowMs':500},tick(740)])
        self.assertFalse(trace[1]['projection']['active']);self.assertTrue(trace[3]['projection']['active'])
        self.assertTrue(trace[4]['projection']['active']);self.assertEqual([],trace[4]['effects'])
        self.assertFalse(trace[5]['projection']['active'])
        self.assertEqual(dict(type='tv',itemId='501',itemType='episode'),trace[-1]['effects'][0]['params'])
        self.assertEqual(1,len(trace[-1]['state']['cache']))
        plain=self.trace([wanted,tick(),reply('tv')]);self.assertEqual([],plain[-1]['state']['cache'])

    def test_one_serial_read_twelve_targets_and_twenty_four_inspected_neighbors(self):
        neighbors=[dict(key=f'card-{n}',item=item(str(n),kind='episode',tmdbId='141')) for n in range(502,520)]
        events=[focus(item(kind='episode'),neighbors=neighbors),tick(),tick(250)]
        events.extend(reply('tv',now=300+n) for n in range(12))
        trace=self.trace(events)
        self.assertEqual(12,len(trace[0]['state']['targets']));self.assertEqual([],trace[2]['effects'])
        self.assertEqual(12,len(trace[-1]['projection']['cards']));self.assertIsNone(trace[-1]['state']['pending'])
        self.assertEqual([],trace[-1]['state']['cache']);self.assertEqual(12,len(trace[-1]['state']['assets']))
        requests=[effect for row in trace for effect in row['effects'] if effect['type']=='request']
        self.assertEqual(['501']+[str(n) for n in range(502,513)],[row['params']['itemId'] for row in requests])
        self.assertTrue(all(len([e for e in row['effects'] if e['type']=='request'])<=1 for row in trace))
        duplicates=[dict(key='card-501',item=item(kind='episode')) for _ in range(23)]
        bounded=self.trace([focus(item(kind='episode'),neighbors=duplicates+neighbors[:2])])
        self.assertEqual(['card-501','card-502'],[x['key'] for x in bounded[0]['state']['targets']])

    def test_late_owner_route_key_and_memory_retirement_cannot_regrant(self):
        wanted=focus(item(kind='episode'))
        retirements=[{**wanted,'key':'new-key','nowMs':250},
            {**wanted,'scope':{**SCOPE,'generation':8},'scopeKey':'route-8','nowMs':250},
            {**wanted,'scope':{**SCOPE,'profileId':'other'},'nowMs':250},
            {**wanted,'active':False,'nowMs':250},{'kind':'memory','nowMs':250}]
        for trace in self.cases([[wanted,tick(),retire,reply('tv')] for retire in retirements]):
            self.assertFalse(trace[-1]['projection']['active']);self.assertEqual([],trace[-1]['projection']['cards'])
            self.assertEqual([],trace[-1]['state']['cache'])
        other=focus(item('502',kind='episode'),key='card-502',nowMs=250)
        trace=self.trace([wanted,tick(),dict(kind='save_owner'),other,reply('tv',now=300),tick(490),
                          reply('tv',now=500,saved=True),reply('tv',now=510)])
        self.assertIsNotNone(trace[-2]['state']['pending']);self.assertFalse(trace[-2]['projection']['active'])
        self.assertEqual('card-502',trace[-1]['projection']['key']);self.assertTrue(trace[-1]['projection']['active'])

    def test_pipeline_result_requires_current_owner_strict_type_public_id_and_safe_uri(self):
        wanted=focus(item(kind='episode'))
        bad=[dict(data={**DATA,'type':'movie'}),dict(data={**DATA,'type':'tv','tmdbId':141}),
             dict(data={**DATA,'type':'tv','tmdbId':'0141'}),dict(data={**DATA,'type':'tv','tmdbId':'141\n'}),
             dict(data={**DATA,'type':'tv','tmdbId':'141?token=x'}),dict(ok=1)]
        for trace in self.cases([[wanted,tick(),reply('tv',**change)] for change in bad]):
            self.assertFalse(trace[-1]['projection']['active']);self.assertIsNone(trace[-1]['state']['pending'])
        trace=self.trace([wanted,tick(),reply('tv',ownerChanges={'key':'foreign'}),reply('tv',now=350)])
        self.assertIsNotNone(trace[2]['state']['pending']);self.assertFalse(trace[2]['projection']['active'])
        self.assertTrue(trace[-1]['projection']['active'])
        trace=self.trace([wanted,tick(),reply('tv',data={**DATA,'type':'tv','posterUri':'https://private.example.test/art',
            'backdropUri':'','headers':{'Authorization':'synthetic-secret'}}),{**wanted,'nowMs':400},tick(640)])
        self.assertFalse(trace[-1]['projection']['active']);self.assertEqual([],trace[-1]['effects'])
        self.assertNotIn('private.example.test',json.dumps(trace[-1]['projection']))
        self.assertNotIn('synthetic-secret',json.dumps(trace[-1]['projection']))

    def test_card_projection_carries_only_safe_granted_backdrops_including_backdrop_only(self):
        cases=[]
        for poster,backdrop in (('',DATA['backdropUri']),(DATA['posterUri'],DATA['backdropUri']),
                               (DATA['posterUri'],'https://private.example.test/art')):
            cases.append([focus(item(tmdbId='141')),tick(),reply(data={**DATA,
                'posterUri':poster,'backdropUri':backdrop})])
        for trace in self.cases(cases):
            self.assertEqual(1,len(trace[-1]['projection']['cards']))
            card=trace[-1]['projection']['cards'][0]
            expected=trace[-1]['state']['asset']
            self.assertEqual(expected['posterUri'],card['posterUri'])
            self.assertEqual(expected['backdropUri'],card['backdropUri'])
            self.assertNotIn('private.example.test',json.dumps(card))


if __name__=='__main__':
    unittest.main()
