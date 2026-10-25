"""Previous uses exact bounded inventories and fresh native detail, never ID arithmetic."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit
from tools.brightscript import ROOT, run_function
BASE=Path(os.environ.get('SILO_PREVIOUS_ROOT',str(ROOT)))
def reference(name):
    spec=importlib.util.spec_from_file_location('previous_'+name,ROOT/'tests'/('test_'+name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
TASK_REF=reference('episode_neighbor_task')
TASK_REF.WORKER=BASE/'components/EpisodeNeighborTask.brs'
TASK_REF.POLICY=BASE/'source/core/EpisodeNeighbors.brs'
TASK_REF.FILES=[BASE/'source/core/EpisodeNeighbors.brs' if p.name=='EpisodeNeighbors.brs' else p for p in TASK_REF.FILES]
POLICY_REF=reference('episode_neighbors')
POLICY_REF.POLICY=BASE/'source/core/EpisodeNeighbors.brs'
DRIVER='''
function PreviousDrive(anchor as Object,scope as Object,answers as Object,direction as Dynamic) as Object
    state=EpisodeNeighborsStart(anchor,scope,direction)
    requests=[]
    snapshots=[]
    for each answer in answers
        request=EpisodeNeighborsRequest(state)
        if request=invalid then exit for
        requests.Push(request)
        state=EpisodeNeighborsResult(state,request,answer)
        snapshots.Push(EpisodeNeighborsOutcome(state))
    end for
    return {requests:requests,outcome:EpisodeNeighborsOutcome(state),snapshots:snapshots,next:EpisodeNeighborsRequest(state)}
end function
'''
class PreviousEpisodeProducerTests(unittest.TestCase):
    def setUp(self):self.policy=POLICY_REF.EpisodeNeighborsTests();self.worker=TASK_REF.EpisodeNeighborTaskTests()
    def drive(self,answers,anchor=None,scope=None,direction='previous'):
        with tempfile.TemporaryDirectory(prefix='silo-previous-policy-') as d:
            helper=Path(d)/'fixtures.brs';helper.write_text(DRIVER)
            return run_function([BASE/'source/core/EpisodeNeighbors.brs',helper],'PreviousDrive',
                [anchor or self.policy.episode(),scope or POLICY_REF.SCOPE,answers,direction],root=Path(d))
    def job(self,provider='plex',anchor=None,direction='previous'):
        anchor=anchor or self.worker.anchor(provider)
        job=self.worker.job(provider,anchor=anchor);job['params']['direction']=direction;return job
    def test_same_season_uses_exact_preceding_native_leaf_with_reverse_proof_and_fresh_bounded_detail(self):
        p=self.policy;before=p.episode('700',3);anchor=p.episode()
        detail=p.detail(before);detail['data']['headers']={'secret':'synthetic-private'}
        detail['data']['versions'][0]['url']='https://private.example.test/private'
        result=self.drive([p.page([before,anchor,p.episode('2',11)]),detail])
        self.assertEqual('700',result['outcome']['candidate']['itemId'])
        proof=result['outcome']['proof'];self.assertEqual(('700','101'),(proof['currentItemId'],proof['nextItemId']))
        self.assertTrue(p.call('EpisodeNeighborsProofMatches',proof,before,anchor,POLICY_REF.SCOPE))
        self.assertEqual('700',result['outcome']['detail']['item']['itemId'])
        self.assertNotIn('private',json.dumps(result['outcome']))
    def test_previous_waits_for_complete_current_inventory_and_never_infers_missing_anchor(self):
        p=self.policy;before=p.episode('700',8)
        result=self.drive([p.page([before,p.episode()],has_more=True),p.page([p.episode('500',12)],offset=2),p.detail(before)])
        self.assertEqual('pending',result['snapshots'][0]['status'])
        self.assertEqual(['current','current','candidate_detail'],[r['stage'] for r in result['requests']])
        self.assertEqual('known',result['outcome']['status'])
        missing=self.drive([p.page([before])]);self.assertEqual('ambiguous',missing['outcome']['status']);self.assertEqual('missing_anchor',missing['outcome']['errorCode'])
    def test_previous_cross_season_reads_complete_adjacent_inventory_and_uses_last_not_head(self):
        p=self.policy;anchor=p.episode('101',1,2,parentItemId='210',seasonItemId='210')
        leaves=[p.episode(str(500+i),i+1) for i in range(48)];last=p.episode('900',52)
        steps=[p.page([anchor]),p.page([p.season(),p.season('210',2)]),p.page(leaves,has_more=True),p.page([last],offset=48),p.detail(last)]
        result=self.drive(steps,anchor)
        self.assertEqual('900',result['outcome']['candidate']['itemId'])
        self.assertEqual(['current','seasons','adjacent','adjacent','candidate_detail'],[r['stage'] for r in result['requests']])
        self.assertEqual(('900','101'),(result['outcome']['proof']['currentItemId'],result['outcome']['proof']['nextItemId']))
        self.assertEqual('pending',result['snapshots'][2]['status'])
    def test_first_native_episode_is_verified_boundary_only_after_complete_season_order(self):
        p=self.policy;result=self.drive([p.page([p.episode()]),p.page([p.season()])])
        self.assertEqual('verified_end',result['outcome']['status']);self.assertIsNone(result['outcome']['candidate'])
        self.assertEqual(['current','seasons'],[r['stage'] for r in result['requests']])
    def test_partial_mixed_duplicate_foreign_or_empty_adjacent_never_proves_previous(self):
        p=self.policy;before=p.episode('700',8)
        inventories=[p.page([before,p.episode()],rawCount=3),p.page([before,p.episode()],hasMore='false'),
            p.page([before,p.episode(),before]),p.page([before,p.episode('102',type='movie')]),
            p.page([before,p.episode('102',parentItemId='999')])]
        for response in inventories:
            with self.subTest(response=response):self.assertEqual('ambiguous',self.drive([response])['outcome']['status'])
        anchor=p.episode('101',1,2,parentItemId='210',seasonItemId='210')
        empty=self.drive([p.page([anchor]),p.page([p.season(),p.season('210',2)]),p.page([])],anchor)
        self.assertEqual('ambiguous',empty['outcome']['status']);self.assertEqual('empty_adjacent',empty['outcome']['errorCode'])
    def test_missing_or_foreign_unavailable_fresh_detail_does_not_enable_previous(self):
        p=self.policy;before=p.episode('700',8)
        for detail in (p.detail(before,versions=[]),p.detail(before,versions=[{'versionId':'foreign'}]),p.detail(p.episode('999',8))):
            with self.subTest(detail=detail):self.assertEqual('ambiguous',self.drive([p.page([before,p.episode()]),detail])['outcome']['status'])
    def test_real_plex_worker_preserves_scope_direction_and_read_only_endpoint_sequence(self):
        w=self.worker;anchor=w.anchor(episodeNumber=2,itemId='100')
        result=w.run_job(self.job(anchor=anchor),responses=[w.plex_page([w.plex_episode('700',1),w.plex_episode('100',2)],total=2),w.plex_detail(w.plex_episode('700',1,playable=True))])
        self.assertEqual(('known','previous','700'),(result['outcome']['status'],result['outcome']['direction'],result['outcome']['candidate']['itemId']))
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])
        self.assertEqual(['/library/metadata/10/children','/library/metadata/700'],[urlsplit(r['url']).path for r in result['requests']])
        self.assertEqual([4000,4000],result['timeouts']);self.assertNotIn('synthetic-private',json.dumps(result['outcome']))
    def test_real_silo_worker_uses_existing_series_season_endpoints_and_exact_file_detail(self):
        w=self.worker;anchor=w.anchor('silo',episodeNumber=2)
        result=w.run_job(self.job('silo',anchor),provider='silo',responses=[w.response({'items':[w.silo_episode('700',1),w.silo_episode('100',2)]}),w.response(w.silo_episode('700',1,playable=True))])
        self.assertEqual('known',result['outcome']['status']);self.assertEqual('fixture-file',result['outcome']['detail']['versions'][0]['versionId'])
        self.assertEqual(['/api/v2/catalog/series/1/seasons/1/episodes','/api/v2/catalog/items/700'],[urlsplit(r['url']).path for r in result['requests']])
        partial=w.run_job(self.job('silo',anchor),provider='silo',responses=[w.response({'items':[w.silo_episode('700',1),w.silo_episode('100',2)],'page':{'has_more':True,'next_cursor':'opaque'}})])
        self.assertEqual('ambiguous',partial['outcome']['status']);self.assertEqual(1,len(partial['requests']))
    def test_invalid_direction_or_session_revision_and_profile_drift_cannot_return_previous(self):
        w=self.worker
        invalid=w.run_job(self.job(direction='sideways'),responses=[])
        self.assertEqual('ambiguous',invalid['outcome']['status']);self.assertEqual([],invalid['requests'])
        for options in ({'change_revision':True},{'changed_session':w.session(profileId='other')}):
            with self.subTest(options=options):
                result=w.run_job(self.job(),**options)
                self.assertEqual('session_changed',result['outcome']['errorCode']);self.assertNotIn('candidate',result['outcome'])
    def test_silo_explicit_mixed_wire_context_cannot_be_hidden_by_endpoint_normalization(self):
        w=self.worker;anchor=w.anchor('silo',episodeNumber=2)
        for patch in ({'type':'movie'},{'series_id':'foreign'}):
            before=w.silo_episode('700',1);before.update(patch)
            result=w.run_job(self.job('silo',anchor),provider='silo',responses=[w.response({'items':[before,w.silo_episode('100',2)]}),w.response(w.silo_episode('700',1,playable=True))])
            self.assertNotEqual('known',result['outcome']['status'])
            self.assertEqual(1,len(result['requests']))
    def test_silo_malformed_pagination_cannot_masquerade_as_complete_previous_inventory(self):
        w=self.worker;anchor=w.anchor('silo',episodeNumber=2)
        for page in ({'has_more':'false'},{'has_more':False,'next_cursor':17}):
            result=w.run_job(self.job('silo',anchor),provider='silo',responses=[w.response({'items':[w.silo_episode('700',1),w.silo_episode('100',2)],'page':page}),w.response(w.silo_episode('700',1,playable=True))])
            self.assertNotEqual('known',result['outcome']['status']);self.assertEqual(1,len(result['requests']))
    def test_previous_adjacent_page_bound_and_direction_fence_do_not_widen_existing_limits(self):
        p=self.policy;anchor=p.episode('101',1,2,parentItemId='210',seasonItemId='210')
        pages=[p.page([p.episode(str(500+48*page+i),48*page+i+1) for i in range(48)],offset=page*48,has_more=True) for page in range(4)]
        result=self.drive([p.page([anchor]),p.page([p.season(),p.season('210',2)]),*pages],anchor)
        self.assertEqual('inventory_budget',result['outcome']['errorCode']);self.assertIsNone(result['next'])
        state=p.call('EpisodeNeighborsStart',p.episode(),POLICY_REF.SCOPE,'previous')
        request=p.call('EpisodeNeighborsRequest',state);request['direction']='next'
        self.assertEqual(state,p.call('EpisodeNeighborsResult',state,request,p.page([p.episode()])))
    def test_omitted_direction_preserves_existing_next_envelope_and_boundaries(self):
        result=self.worker.run_job()
        self.assertEqual('101',result['outcome']['candidate']['itemId']);self.assertNotIn('direction',result['outcome']);self.assertNotIn('detail',result['outcome'])
if __name__=='__main__':unittest.main()
