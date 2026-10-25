"""Current query/filter/dialog owns bounded cache-first live search and recents."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import ROOT, run_function
BASE=Path(os.environ.get('SILO_LIVE_SEARCH_ROOT',str(ROOT)))
SCOPE={'provider':'plex','sourceId':'plex:fixture','profileId':'owner','generation':7}
def card(i='1',title='Moon',kind='movie',**kw):return {'provider':'plex','sourceId':'plex:fixture','itemId':i,'title':title,'type':kind,**kw}
DRIVER='''
function LiveSearchTrace(scope as Object,index as Object,recents as Object,events as Object) as Object
    state=LiveSearchCreate(scope,"dialog-1",recents)
    trace=[]
    for each event in events
        if not event.DoesExist("scope") then event["scope"]=scope
        if not event.DoesExist("dialogId") then event["dialogId"]=state.dialogId
        if event.kind="tick" or event.kind="result"
            if not event.DoesExist("owner") then event["owner"]=LiveSearchOwner(state)
        end if
        decision=LiveSearchReduce(state,event,index,event.nowMs)
        state=decision.state
        trace.Push({state:state,effects:decision.effects,accepted:decision.accepted,projection:LiveSearchProjection(state)})
    end for
    return trace
end function
function LiveSearchFilterFixture(values as Object,kind as String) as Object
    state=LiveSearchCreate({provider:"plex",sourceId:"plex:fixture",profileId:"owner",generation:7},"dialog-1",[])
    first=LiveSearchReduce(state,{kind:"edit",scope:state.scope,dialogId:state.dialogId,value:"moon"},values,0)
    second=LiveSearchReduce(first.state,{kind:"filter",scope:state.scope,dialogId:state.dialogId,filter:kind},values,1)
    return LiveSearchProjection(second.state)
end function
'''
class LiveSearchPolicyTests(unittest.TestCase):
    def trace(self,events,index=None,recents=None,scope=None):
        with tempfile.TemporaryDirectory(prefix='silo-live-search-policy-') as d:
            helper=Path(d)/'fixture.brs';helper.write_text(DRIVER)
            return run_function([ROOT/'tests/fixtures/legacy_policy_values.brs',ROOT/'source/core/RequestQueuePolicy.brs',ROOT/'source/core/SearchPolicy.brs',ROOT/'source/adapters/MetadataAdapter.brs',BASE/'source/core/LiveSearchPolicy.brs',helper],
                'LiveSearchTrace',[scope or SCOPE,index if index is not None else [card()],recents or [],events],root=Path(d))
    def event(self,kind,now=0,**kw):return {'kind':kind,'nowMs':now,**kw}
    def test_immediate_local_edits_restart_bounded_four_hundred_ms_provider_debounce(self):
        t=self.trace([self.event('edit',value='mo'),self.event('tick',399),self.event('edit',399,value='moon'),self.event('tick',798),self.event('tick',799),self.event('tick',900)])
        self.assertEqual('1',t[0]['projection']['items'][0]['itemId'])
        self.assertFalse(any(e['kind']=='request' for step in t[:4] for e in step['effects']))
        effect=t[4]['effects'][0];self.assertEqual(('search',{'query':'moon','limit':100}),(effect['action'],effect['params']))
        self.assertEqual([],t[5]['effects']);self.assertEqual([],t[-1]['state']['recents'])
    def test_submit_bypasses_debounce_records_only_submitted_query_and_does_not_duplicate_live_request(self):
        t=self.trace([self.event('edit',value='mo'),self.event('edit',50,value='moon'),self.event('submit',80,value='moon'),self.event('tick',500)])
        self.assertEqual(['moon'],t[2]['state']['recents']);self.assertEqual('request',t[2]['effects'][0]['kind']);self.assertEqual([],t[-1]['effects'])
        t=self.trace([self.event('edit',value='moon'),self.event('tick',400),self.event('submit',410,value='moon')])
        self.assertEqual([],t[-1]['effects']);self.assertFalse(t[-1]['state']['dialogOpen'])
    def test_short_or_empty_edit_retires_older_query_without_provider_or_recents_loss(self):
        t=self.trace([self.event('edit',value='moon'),self.event('tick',400),self.event('edit',410,value='m'),self.event('tick',1000),self.event('submit',1100,value='')],recents=['sun'])
        self.assertEqual([],t[-1]['state']['items']);self.assertEqual(['sun'],t[-1]['state']['recents']);self.assertEqual([],t[-1]['effects'])
        self.assertTrue(t[-1]['projection']['recentsVisible']);self.assertLessEqual(len(t[-1]['projection']['items']),10)
    def test_new_query_resets_kind_and_new_filter_changes_owner_before_results(self):
        index=[card('1'),card('2',kind='show'),card('3',kind='episode'),card('4',kind='season')]
        t=self.trace([self.event('edit',value='moon'),self.event('filter',20,filter='shows'),self.event('tick',420),self.event('edit',430,value='moons')],index=index)
        self.assertEqual(['2','4','3'],[c['itemId'] for c in t[1]['projection']['items']]);self.assertEqual('shows',t[2]['effects'][0]['owner']['filter'])
        self.assertEqual('all',t[-1]['state']['filter'])
    def test_filter_is_applied_before_local_limit_not_after_first_hundred_movies(self):
        index=[card(str(i+1),'Moon '+str(i)) for i in range(105)]+[card('999','Moon Show','show')]
        t=self.trace([self.event('edit',value='moon'),self.event('filter',1,filter='shows')],index=index)
        self.assertEqual(['999'],[c['itemId'] for c in t[-1]['projection']['items']])
    def test_result_requires_exact_source_profile_route_dialog_query_generation_and_filter(self):
        t=self.trace([self.event('edit',value='moon'),self.event('tick',400)])
        owner=t[-1]['effects'][0]['owner'];response={**SCOPE,'ok':True,'data':{'items':[card('2','Moon New')]}}
        edits=[('sourceId','plex:other'),('profileId','child'),('generation',8),('dialogId','dialog-2'),('queryId',99),('query','sun'),('filter','movies')]
        for field,value in edits:
            with self.subTest(field=field):
                bad={**owner,field:value}
                if field in SCOPE:bad['scope']={**owner['scope'],field:value};bad.pop(field,None)
                trace=self.trace([self.event('edit',value='moon'),self.event('tick',400),self.event('result',500,owner=bad,response=response)])
                self.assertFalse(trace[-1]['accepted']);self.assertEqual(['1'],[c['itemId'] for c in trace[-1]['state']['items']])
    def test_old_same_query_aba_response_cannot_replace_new_query(self):
        old=self.trace([self.event('edit',value='moon'),self.event('tick',400)])[-1]['effects'][0]['owner']
        response={**SCOPE,'ok':True,'data':{'items':[card('2')]}}
        t=self.trace([self.event('edit',value='moon'),self.event('tick',400),self.event('edit',401,value='sun'),self.event('edit',450,value='moon'),self.event('result',500,owner=old,response=response)])
        self.assertFalse(t[-1]['accepted']);self.assertEqual(['1'],[c['itemId'] for c in t[-1]['state']['items']])
    def test_provider_failure_or_empty_partial_window_retains_positive_cache_without_absence_claim(self):
        for response in ({**SCOPE,'ok':False,'errorCode':'timeout'},{**SCOPE,'ok':True,'data':{'items':[],'hasMore':True}}):
            t=self.trace([self.event('edit',value='moon'),self.event('tick',400),self.event('result',500,response=response)])
            self.assertEqual(['1'],[c['itemId'] for c in t[-1]['projection']['items']]);self.assertTrue(t[-1]['projection']['partial'])
            self.assertNotIn('No titles were found',t[-1]['projection']['status'])
    def test_content_focus_locks_result_order_until_focus_returns_then_publishes_fresh_copy(self):
        response={**SCOPE,'ok':True,'data':{'items':[card('2','Moon'),card('1','Moon Late',resumeMs=9000)]}}
        t=self.trace([self.event('edit',value='moon'),self.event('tick',400),self.event('focus',410,contentFocused=True),self.event('result',500,response=response),self.event('focus',510,contentFocused=False)])
        self.assertEqual(['1'],[c['itemId'] for c in t[3]['projection']['items']]);self.assertEqual('Moon',t[3]['projection']['items'][0]['title'])
        self.assertEqual(['2','1'],[c['itemId'] for c in t[-1]['projection']['items']]);self.assertEqual(9000,t[-1]['projection']['items'][1]['resumeMs'])
    def test_recents_are_ten_unique_bounded_submits_not_edits(self):
        events=[]
        for i in range(12):
            if i:events.append(self.event('open',i*500-1,nextDialogId='dialog-'+str(i+1)))
            events += [self.event('edit',i*500,value='Query '+str(i)),self.event('submit',i*500+1,value='Query '+str(i))]
        t=self.trace(events,index=[]);self.assertEqual(10,len(t[-1]['state']['recents']));self.assertEqual('Query 11',t[-1]['state']['recents'][0])
        self.assertTrue(all(len(q)<=120 for q in t[-1]['state']['recents']))
    def test_silo_uses_existing_catalog_query_with_no_invented_grouping_param(self):
        scope={**SCOPE,'provider':'silo','sourceId':'silo:fixture'}
        t=self.trace([self.event('edit',value='moon'),self.event('filter',5,filter='shows'),self.event('tick',405)],scope=scope,index=[])
        effect=t[-1]['effects'][0];self.assertEqual(('catalog_query',{'query':'moon','limit':100}),(effect['action'],effect['params']))
    def test_numeric_truthy_ok_is_not_a_provider_result_boolean(self):
        response={**SCOPE,'ok':1,'data':{'items':[card('2','Moon Fresh')]}}
        t=self.trace([self.event('edit',value='moon'),self.event('tick',400),self.event('result',500,response=response)])
        self.assertFalse(t[-1]['accepted']);self.assertEqual(t[-2]['projection'],t[-1]['projection'])
    def test_cancel_restores_committed_silo_cursor_not_live_edited_query_cursor(self):
        scope={**SCOPE,'provider':'silo','sourceId':'silo:fixture'}
        response={**scope,'ok':True,'data':{'items':[],'hasMore':True,'nextCursor':'moon-next'}}
        t=self.trace([self.event('edit',value='moon'),self.event('submit',1,value='moon'),self.event('result',2,response=response),
            self.event('open',3,nextDialogId='dialog-2'),self.event('edit',4,value='sun'),self.event('cancel',5)],scope=scope,index=[])
        self.assertEqual('moon',t[-1]['state']['query']);self.assertEqual('moon-next',t[-1]['state']['nextCursor'])
    def test_retire_drops_pending_data_and_stale_timer_cannot_reissue(self):
        t=self.trace([self.event('edit',value='moon'),self.event('tick',400),self.event('retire',410),self.event('tick',900)])
        self.assertFalse(t[-1]['accepted']);self.assertEqual([],t[-1]['effects']);self.assertEqual([],t[-1]['state']['items']);self.assertIsNone(t[-1]['state']['latestItems'])
if __name__=='__main__':unittest.main()
