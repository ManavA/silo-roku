"""Already admitted settings writes survive only their own viewer's route change."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
SCOPE=dict(provider='plex',sourceId='plex:fixture',profileId='owner',generation=7)
PREF=dict(schemaVersion=1,sourceId='plex:fixture',profileId='owner',personalized=True,
          cloudDecisions=True,stillWatchingCheck=True,gatewayOrigin='https://fixture.example.test')
HARNESS='''
function DqFixture(scope as Object,pref as Object,cases as Object) as Object
    out=[]
    for each entry in cases
        record={}:record.SetModeCaseSensitive()
        for each field in pref
            record[field]=pref[field]
        end for
        for each field in RqValue(entry,"record",{})
            record[field]=entry.record[field]
        end for
        job={provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,
            action:"decision_pref_set",params:{preference:record},decisionPreferenceOwner:{operationId:"decision-pref-1",revision:1}}
        for each field in RqValue(entry,"job",{})
            job[field]=entry.job[field]
        end for
        purpose=RqValue(entry,"purpose","decision_pref_set")
        queue=RqCreate(scope)
        admitted=RqOffer(queue,{job:job,purpose:purpose,cleanup:false})
        newer={provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,generation:8}
        for each field in RqValue(entry,"scope",{})
            newer[field]=entry.scope[field]
        end for
        rebound=RqRebind(admitted.state,newer)
        read={provider:newer.provider,sourceId:newer.sourceId,profileId:newer.profileId,generation:newer.generation,
            action:"decision_pref_get",params:{}}
        queue=RqOffer(rebound,{job:read,purpose:"decision_pref_get",cleanup:false}).state
        taken=RqTake(queue)
        out.Push({retained:rebound.queued.Count(),first:taken.next,
            blocked:RqTake(taken.state).next,offer:admitted.accepted})
    end for
    return out
end function
'''

class DecisionPreferenceQueueTests(unittest.TestCase):
    def cases(self,cases):
        with tempfile.TemporaryDirectory(prefix='silo-decision-queue-') as directory:
            p=Path(directory);f=p/'fixture.brs';f.write_text(HARNESS)
            return run_function([ROOT/'source/core/RequestQueuePolicy.brs',f],'DqFixture',[SCOPE,PREF,cases],root=p)

    def test_admitted_same_viewer_write_precedes_new_generation_read_exclusively(self):
        out=self.cases([{}])[0]
        self.assertTrue(out['offer']);self.assertEqual(1,out['retained'])
        self.assertEqual('decision_pref_set',out['first']['job']['action'])
        self.assertTrue(out['first']['exclusive']);self.assertIsNone(out['blocked'])

    def test_source_or_profile_change_drops_old_write_without_cleanup_authority(self):
        out=self.cases([dict(scope=dict(profileId='other')),dict(scope=dict(sourceId='plex:other'))])
        self.assertTrue(all(x['retained']==0 for x in out))
        self.assertTrue(all(x['first']['job']['action']=='decision_pref_get' for x in out))

    def test_wrong_action_purpose_or_missing_typed_owner_cannot_gain_retention(self):
        cases=[dict(job=dict(action='detail')),dict(purpose='delivery'),
               dict(job=dict(decisionPreferenceOwner={})),
               dict(job=dict(decisionPreferenceOwner=dict(operationId='op',revision=True)))]
        self.assertTrue(all(x['retained']==0 for x in self.cases(cases)))

    def test_malformed_record_and_ambiguous_case_aliases_are_not_retained(self):
        cases=[dict(record={key:value}) for key,value in (
            ('personalized','true'),('schemaVersion',True),('gatewayOrigin',None),
            ('sourceid','plex:other'),('SOURCEID','plex:other'),('unknown',True))]
        self.assertTrue(all(x['retained']==0 for x in self.cases(cases)))


if __name__=='__main__':unittest.main()
